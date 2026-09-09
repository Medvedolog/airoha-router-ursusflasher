#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path


def load_impl():
    path = Path(__file__).with_name("mf2_ramreadonly_transform_impl.py")
    spec = importlib.util.spec_from_file_location("mf2_ramreadonly_transform_impl", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load MF2 transform implementation: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replace_regex(text: str, pattern: str, replacement: str, label: str) -> str:
    out, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, got {count}")
    return out


def c_concat_pattern(token: str) -> str:
    # The embedded UI is emitted as adjacent C string literals and may split a
    # board token at arbitrary byte boundaries, e.g. "No"\n"kia" or
    # "XG-04"\n"0G-MD". Match the semantic token across those boundaries.
    sep = r'(?:"\s*")?'
    return sep.join(re.escape(ch) for ch in token)


def canonicalize_embedded_ui(root: Path) -> None:
    path = root / "include/ursusweb_ui.inc"
    data = path.read_text(encoding="utf-8")
    replacements = (
        ("Nokia XG-040G-MD", "Nokia XG-040G-MF"),
        ("Nokia_XG-040G-MD", "Nokia_XG-040G-MF"),
        ("nokia_xg-040g-md", "nokia_xg-040g-mf"),
        ("nokia,xg-040g-md", "nokia,xg-040g-mf"),
        ("openwrt-airoha-an7581-nokia_xg-040g-md-ubi-preloader.bin",
         "openwrt-airoha-an7583-nokia_xg-040g-mf-ubi-preloader.bin"),
    )
    changed = 0
    for old, new in replacements:
        data, count = re.subn(c_concat_pattern(old), lambda _m, new=new: new, data)
        changed += count
        if re.search(c_concat_pattern(old), data):
            raise SystemExit(f"MF2 embedded UI token survived C-concat rewrite: {old}")
    path.write_text(data, encoding="utf-8")
    print(f"MF2_EMBEDDED_UI_CANONICALIZE=PASS replacements={changed}")


def harden_entrypoints(root: Path) -> None:
    ubi_path = root / "cmd/ursusubi.c"
    update_path = root / "cmd/ursusupdate.c"
    web_path = root / "cmd/ursusweb.c"
    dispatch_path = root / "cmd/ursusdispatch.c"

    ubi = ubi_path.read_text(encoding="utf-8")
    ubi = replace_regex(
        ubi,
        r'int ursus_ubi_update_step\(void\)\n\{.*?\n\}\n\n(?=int ursus_ubi_update_fit\()',
        '''int ursus_ubi_update_step(void)\n{\n    printf("URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE_STEP\\n");\n    return -EROFS;\n}\n\n''',
        "UBI update step gate",
    )
    ubi = replace_regex(
        ubi,
        r'int ursus_ubi_migration_step\(void\)\n\{.*?\n\}\n\n(?=int ursus_ubi_migrate_from_stock\()',
        '''int ursus_ubi_migration_step(void)\n{\n    printf("URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION_STEP\\n");\n    return -EROFS;\n}\n\n''',
        "UBI migration step gate",
    )
    ubi_path.write_text(ubi, encoding="utf-8")

    update = update_path.read_text(encoding="utf-8")
    update = replace_regex(
        update,
        r'int ursus_fip_update_step\(void\)\n\{.*?\n\}\n\n(?=static int ursus_update_run\()',
        '''int ursus_fip_update_step(void)\n{\n    printf("URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE_STEP\\n");\n    return -EROFS;\n}\n\n''',
        "FIP update step gate",
    )
    update_path.write_text(update, encoding="utf-8")

    web = web_path.read_text(encoding="utf-8")
    web = replace_regex(
        web,
        r'static int ursus_factory_install\(void\)\n\{.*?\n\}\n\n(?=static int ursus_factory_reset_settings\()',
        '''static int ursus_factory_install(void)\n{\n    printf("URSUS_MF2_READONLY_REJECT operation=FACTORY_INSTALL\\n");\n    return -EROFS;\n}\n\n''',
        "factory install gate",
    )
    web = replace_regex(
        web,
        r'static int ursus_factory_reset_settings\(void\)\n\{.*?\n\}\n\n(?=static const char \*ursus_ubi_vol_type_name\()',
        '''static int ursus_factory_reset_settings(void)\n{\n    printf("URSUS_MF2_READONLY_REJECT operation=FACTORY_SETTINGS_RESET\\n");\n    return -EROFS;\n}\n\n''',
        "factory settings reset gate",
    )

    # The preserved MF2 transform originally rejected every HTTP POST. That is
    # broader than the actual RAM-only safety contract: uploading, validating
    # and booting an initramfs/FIT only stages bytes in DRAM and then hands off
    # via bootm. Permit only that narrow Expert path. Keep the real U-Boot Web
    # console and every install/update/reset route blocked so the HTTP surface
    # cannot bypass the persistent-write gates below.
    global_post_gate = '''    if (!strncmp(c->reqhdr, "POST ", 5)) {\n        ursus_logf("MF2 READONLY: rejected HTTP POST\\n");\n        return ursus_http_start_response(pcb, c, 403, "application/json",\n            "{\\\"result\\\":\\\"REJECTED\\\",\\\"reason_class\\\":\\\"READ_ONLY_BRINGUP\\\",\\\"reason\\\":\\\"MF2 RAM-only build: persistent operations disabled\\\"}\\n");\n    }\n'''
    selective_post_gate = '''    if (URSUS_REQ_MATCH(c->reqhdr, "POST /api/initramfs-begin ") ||\n        URSUS_REQ_MATCH(c->reqhdr, "POST /api/initramfs-chunk ") ||\n        URSUS_REQ_MATCH(c->reqhdr, "POST /api/expert/discard ") ||\n        URSUS_REQ_MATCH(c->reqhdr, "POST /api/expert/boot-once ")) {\n        ursus_logf("URSUS_MF2_RAM_POST_ALLOW route=initramfs_or_boot_once\\n");\n    } else if (!strncmp(c->reqhdr, "POST ", 5)) {\n        ursus_logf("MF2 READONLY: rejected HTTP POST\\n");\n        return ursus_http_start_response(pcb, c, 403, "application/json",\n            "{\\\"result\\\":\\\"REJECTED\\\",\\\"reason_class\\\":\\\"READ_ONLY_BRINGUP\\\",\\\"reason\\\":\\\"MF2 RAM-only build: persistent operations disabled\\\"}\\n");\n    }\n'''
    if web.count(global_post_gate) != 1:
        raise SystemExit(f"MF2 selective POST policy: expected one global gate, got {web.count(global_post_gate)}")
    web = web.replace(global_post_gate, selective_post_gate, 1)

    status_old = '\\\"ram_read_only\\\":true,\\\"persistent_write_enabled\\\":false,\\\"boot_fdt_compatible\\\"'
    status_new = '\\\"ram_read_only\\\":true,\\\"persistent_write_enabled\\\":false,\\\"ram_boot_enabled\\\":true,\\\"boot_fdt_compatible\\\"'
    if web.count(status_old) != 1:
        raise SystemExit(f"MF2 status RAM boot capability: expected one marker, got {web.count(status_old)}")
    web = web.replace(status_old, status_new, 1)

    # MF2 boots straight into ursusweb instead of ursusdispatch. TEST61's
    # recovery LED latch therefore never ran on real MF hardware even though
    # the native AN7583 gpio-leds device (red:wan, GPIO27 active-low) was
    # present and the DM LED driver was linked. Start the existing Ursus
    # recovery pattern explicitly before network bring-up: native DM only,
    # no AN7581 raw GPIO/MMIO. It ends in steady red while WebFailsafe runs.
    led_anchor = '''    ret = net_lwip_eth_start();\n'''
    led_start = '''    printf("URSUS_MF2_LED_RECOVERY_PATTERN board=AN7583 driver=native-dm label=red:wan\\n");\n    ursus_led_recovery_latched();\n    ret = net_lwip_eth_start();\n'''
    if web.count(led_anchor) != 1:
        raise SystemExit(f"MF2 native recovery LED hook: expected one exact match, got {web.count(led_anchor)}")
    web = web.replace(led_anchor, led_start, 1)
    web_path.write_text(web, encoding="utf-8")

    dispatch = dispatch_path.read_text(encoding="utf-8")
    old = '''    printf("URSUS_STOCK_BOOT_SELECTED\\n");\n    ret = run_command("ursusstockboot", 0);\n    printf(ret ? "URSUS_STOCKBOOT_RETURNED ret=%d\\n" :\n                 "URSUS_STOCKBOOT_UNEXPECTED_RETURN ret=%d\\n", ret);\n    return ursus_enter_webfailsafe("STOCKBOOT_RETURN", 0);\n'''
    new = '''    printf("URSUS_MF2_STOCKBRIDGE_DISABLED board=AN7583 mode=RAM_ONLY\\n");\n    return ursus_enter_webfailsafe("MF2_NO_STOCKBRIDGE", 0);\n'''
    if dispatch.count(old) != 1:
        raise SystemExit(f"StockBridge fallback gate: expected one exact match, got {dispatch.count(old)}")
    dispatch = dispatch.replace(old, new, 1)
    dispatch_path.write_text(dispatch, encoding="utf-8")

    required = {
        ubi_path: (
            "URSUS_MF2_READONLY_REJECT operation=SETTINGS_RESET_BACKEND",
            "URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE_STEP",
            "URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION_STEP",
        ),
        update_path: (
            "URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE_STEP",
        ),
        web_path: (
            "URSUS_MF2_READONLY_REJECT operation=FACTORY_INSTALL",
            "URSUS_MF2_READONLY_REJECT operation=FACTORY_SETTINGS_RESET",
            "URSUS_MF2_RAM_POST_ALLOW route=initramfs_or_boot_once",
            "ram_boot_enabled",
            "URSUS_MF2_LED_RECOVERY_PATTERN board=AN7583 driver=native-dm label=red:wan",
        ),
        dispatch_path: (
            "URSUS_MF2_STOCKBRIDGE_DISABLED board=AN7583 mode=RAM_ONLY",
        ),
    }
    for path, markers in required.items():
        data = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in data:
                raise SystemExit(f"MF2 hardening marker missing in {path}: {marker}")

    board_identity_files = (
        root / "cmd/ursusweb.c",
        root / "cmd/ursusupdate.c",
        root / "cmd/ursusubi.c",
        root / "cmd/ursusdispatch.c",
        root / "include/ursusweb_ui.inc",
        root / "cmd/Makefile",
    )
    forbidden = (
        "Nokia XG-040G-MD",
        "Nokia_XG-040G-MD",
        "nokia_xg-040g-md",
        "nokia,xg-040g-md",
        "NOKIA_XG040GMD",
        "URSUSBOOT_MD",
        "TCBOOT_MD",
    )
    leaks = []
    for path in board_identity_files:
        data = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in data or re.search(c_concat_pattern(token), data):
                leaks.append(f"{path.relative_to(root)}:{token}")
    if leaks:
        raise SystemExit("MF2 board identity leak after transform: " + ", ".join(leaks))

    print("MF2_ENTRYPOINT_HARDENING=PASS")


def transform(root: Path) -> None:
    root = root.resolve()
    ui_include = root / "include/ursusweb_ui.inc"
    compat_ui = root / "cmd/ursusweb_ui.inc"
    if not ui_include.is_file():
        raise SystemExit(f"missing TEST61 UI include: {ui_include}")
    if compat_ui.exists() or compat_ui.is_symlink():
        raise SystemExit(f"unexpected pre-existing compatibility UI path: {compat_ui}")

    # The preserved implementation expected cmd/ursusweb_ui.inc. TEST61 stores
    # it under include/. A temporary relative symlink keeps the implementation
    # immutable while all writes still land in the canonical include file.
    compat_ui.symlink_to(Path("../include/ursusweb_ui.inc"))
    try:
        impl = load_impl()
        impl.transform(root)
    finally:
        if compat_ui.is_symlink():
            compat_ui.unlink()

    canonicalize_embedded_ui(root)
    harden_entrypoints(root)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    args = ap.parse_args()
    transform(args.source_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

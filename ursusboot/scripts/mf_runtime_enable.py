#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import re
import shutil
from pathlib import Path

VERSION = "0.1.0-TEST62"
MD_PRELOADER_SHA = "6c3b2339d036340396730a13adfe35c0d2a4dddedeffb6f9965a24e0c7908808"
MF_PRELOADER_SHA = "778d10a65276085b70bec005248fc87ec208b43b0239502f15ade20fe528301e"
MD_BL2_SHA = "6f9c928bad500de0339bbfdfa354c17a7ac044f96c913f3a01301971d6cd659d"
MF_BL2_SHA = "c655479c4d14b4f6d1a7a5eb8de80bfb204b3cdf46c9e48a5c6f3aea22d98131"
MD_PRELOADER_SIZE = "113447"
MF_PRELOADER_SIZE = "118333"


def _load_validator_module() -> object:
    path = Path(__file__).with_name("mf3_persist2_validator.py")
    spec = importlib.util.spec_from_file_location("mf_runtime_validator", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load MF validator source: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rewrite_identity(text: str) -> str:
    replacements = (
        ("Nokia XG-040G-MD", "Nokia XG-040G-MF"),
        ("Nokia_XG-040G-MD", "Nokia_XG-040G-MF"),
        ("nokia_xg-040g-md", "nokia_xg-040g-mf"),
        ("nokia,xg-040g-md-ubi", "nokia,xg-040g-mf-ubi"),
        ("nokia,xg-040g-md", "nokia,xg-040g-mf"),
        ("xg-040g-md", "xg-040g-mf"),
        ("NOKIA_XG040GMD_STOCK", "NOKIA_XG040GMF_STOCK"),
        ("URSUSBOOT_MD", "URSUSBOOT_MF"),
        ("TCBOOT_MD", "TCBOOT_MF"),
        ("XG040GMC2P5G", "XG040GMF"),
        ("AN7581DT", "AN7583DT"),
        ("Airoha AN7581", "Airoha AN7583"),
        ("AN7581", "AN7583"),
        ("an7581", "an7583"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _byte_array(hexstr: str) -> str:
    return ", ".join("0x" + hexstr[i:i + 2] for i in range(0, len(hexstr), 2))


def _replace_digest_bytes(text: str, old_hex: str, new_hex: str) -> tuple[str, int]:
    old = ["0x" + old_hex[i:i + 2] for i in range(0, len(old_hex), 2)]
    new = _byte_array(new_hex)
    pattern = r"\s*,\s*".join(re.escape(item) for item in old)
    return re.subn(pattern, new, text, flags=re.I)


def _patch_mf_transition_constants(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    counts["preloader_sha_text"] = text.count(MD_PRELOADER_SHA)
    text = text.replace(MD_PRELOADER_SHA, MF_PRELOADER_SHA)
    counts["bl2_sha_text"] = text.count(MD_BL2_SHA)
    text = text.replace(MD_BL2_SHA, MF_BL2_SHA)
    text, counts["preloader_sha_bytes"] = _replace_digest_bytes(text, MD_PRELOADER_SHA, MF_PRELOADER_SHA)
    text, counts["bl2_sha_bytes"] = _replace_digest_bytes(text, MD_BL2_SHA, MF_BL2_SHA)
    counts["preloader_size"] = text.count(MD_PRELOADER_SIZE)
    text = text.replace(MD_PRELOADER_SIZE, MF_PRELOADER_SIZE)
    return text, counts


def _restore_file(root: Path, pristine: Path, rel: str) -> Path:
    src = pristine / rel
    dst = root / rel
    if not src.is_file() or not dst.is_file():
        raise SystemExit(f"runtime restore source missing: {rel}")
    shutil.copy2(src, dst)
    return dst


def _patch_mf_stockbridge(text: str) -> str:
    hdr2_count = text.count("HDR2")
    if hdr2_count < 1:
        raise SystemExit("MF StockBridge HDR2 anchor missing")
    text = text.replace("HDR2", "HDR3")

    # Nokia tcboot on the real MF supplies all six SerDes arguments. The stock
    # environment does not necessarily contain pon/ethernet/usb1, so treating
    # those three as optional passthrough produced a vendor-kernel NULL deref in
    # ECNT_SERDES_CFG_PROBE. Make the proven MF board contract explicit.
    old_passthrough = '"serdes_pon", "serdes_ethernet", "serdes_usb1", "board_args",'
    if old_passthrough not in text:
        raise SystemExit("MF StockBridge SerDes passthrough anchor missing")
    text = text.replace(old_passthrough, '"board_args",', 1)

    old_args = '''if (append_arg(out, outsz, "serdes_wifi1", "05") ||
        append_arg(out, outsz, "serdes_wifi2", "05") ||
        append_arg(out, outsz, "serdes_usb2", "02"))'''
    new_args = '''if (append_arg(out, outsz, "serdes_pon", "00") ||
        append_arg(out, outsz, "serdes_ethernet", "12") ||
        append_arg(out, outsz, "serdes_wifi1", "05") ||
        append_arg(out, outsz, "serdes_wifi2", "05") ||
        append_arg(out, outsz, "serdes_usb1", "00") ||
        append_arg(out, outsz, "serdes_usb2", "02"))'''
    if old_args not in text:
        raise SystemExit("MF StockBridge tcboot SerDes argument anchor missing")
    text = text.replace(old_args, new_args, 1)

    old_marker = 'URSUS_STOCKBOOT_TCBOOT_MF_ARGS wifi1=05 wifi2=05 usb2=02'
    new_marker = 'URSUS_STOCKBOOT_TCBOOT_MF_ARGS pon=00 ethernet=12 wifi1=05 wifi2=05 usb1=00 usb2=02'
    if old_marker not in text:
        raise SystemExit("MF StockBridge tcboot marker anchor missing")
    text = text.replace(old_marker, new_marker, 1)
    print(f"MF_STOCKBRIDGE_FORMAT from=HDR2 to=HDR3 replacements={hdr2_count}")
    print("MF_STOCKBRIDGE_SERDES pon=00 ethernet=12 wifi1=05 wifi2=05 usb1=00 usb2=02")
    return text


def transform(root: Path, pristine: Path) -> None:
    root = root.resolve()
    pristine = pristine.resolve()

    # Restore all persistent writer entrypoints from TEST61 before applying the
    # MF board specialization. In particular, do not inherit the RAM-only
    # FIP_UPDATE rejection into persistent/RAM-repair TEST62.
    restored = (
        "cmd/ursusweb.c",
        "cmd/ursusubi.c",
        "cmd/ursusdispatch.c",
        "cmd/ursusupdate.c",
        "cmd/Makefile",
    )
    for rel in restored:
        _restore_file(root, pristine, rel)

    transition_counts: dict[str, dict[str, int]] = {}
    for rel in ("cmd/ursusweb.c", "cmd/ursusubi.c", "cmd/ursusdispatch.c", "cmd/ursusstock.c"):
        path = root / rel
        text = _rewrite_identity(path.read_text(encoding="utf-8"))
        text, counts = _patch_mf_transition_constants(text)
        transition_counts[rel] = counts
        if rel == "cmd/ursusstock.c":
            text = _patch_mf_stockbridge(text)
        path.write_text(text, encoding="utf-8")
        if rel in ("cmd/ursusweb.c", "cmd/ursusubi.c"):
            print(f"MF_RUNTIME_CONSTANTS file={rel} " + " ".join(f"{k}={v}" for k, v in counts.items()))

    for key in ("preloader_sha_bytes", "bl2_sha_bytes"):
        if sum(transition_counts[p][key] for p in ("cmd/ursusweb.c", "cmd/ursusubi.c")) < 1:
            raise SystemExit(f"MF transition raw digest anchor missing: {key}")

    validator = _load_validator_module()
    update = root / "cmd/ursusupdate.c"
    u = _rewrite_identity(update.read_text(encoding="utf-8"))
    u = validator.replace_func(u, "ursus_fip_parse", validator.FIP_PARSE)
    u = validator.replace_func(u, "ursus_fip_validate_current", validator.VALIDATE_CURRENT)
    u = validator.replace_func(u, "ursus_fip_validate_buf", validator.VALIDATE_BUF)
    u = validator.replace_func(u, "ursus_fip_validate", validator.VALIDATE)
    u = u.replace("MF2_STOCK_FIP_VALIDATION_DISABLED", "NOKIA_XG040GMF_STOCK")
    if "URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE" in u:
        raise SystemExit("MF FIP self-update read-only gate survived pristine restore")
    if "URSUS_FIP_SELFUPDATE_ENABLED=1" not in u:
        raise SystemExit("MF FIP self-update backend marker missing")
    update.write_text(u, encoding="utf-8")

    web = root / "cmd/ursusweb.c"
    w = web.read_text(encoding="utf-8")
    status_old = '"\\\"soc\\\":\\\"Airoha AN7583\\\",\\\"boot_fdt_compatible\\\":\\\"%s\\\",\\\"dram_mib\\\":%u,"'
    status_new = '"\\\"soc\\\":\\\"Airoha AN7583\\\",\\\"ram_read_only\\\":false,\\\"persistent_write_enabled\\\":true,\\\"ram_boot_enabled\\\":true,\\\"boot_fdt_compatible\\\":\\\"%s\\\",\\\"dram_mib\\\":%u,"'
    if status_old in w:
        w = w.replace(status_old, status_new, 1)
    elif "persistent_write_enabled" not in w:
        raise SystemExit("MF runtime status capability anchor missing")
    web.write_text(w, encoding="utf-8")

    ui_path = root / "include/ursusweb_ui.inc"
    ui = _rewrite_identity(ui_path.read_text(encoding="utf-8"))
    ui = ui.replace("openwrt-airoha-an7583-nokia_xg-040g-mf-ubi-preloader.bin", "nokia-xg-040g-mf-an7583-production-preloader.bin")
    old_expr = "S.image_type==='OPENWRT_UBI'"
    new_expr = "(S.image_type==='OPENWRT_UBI'||S.image_type==='OPENWRT_UBI_SYSUPGRADE')"
    if old_expr not in ui:
        raise SystemExit("MF WebFailsafe migration image_type anchor missing")
    ui = ui.replace(old_expr, new_expr)
    ui_path.write_text(ui, encoding="utf-8")

    led = (root / "cmd/ursusled.c").read_text(encoding="utf-8")
    for token in ('#define LED_STATUS_RED "red:wan"', '#define LED_USB1_GREEN "green:usb-1"', '#define LED_USB2_GREEN "green:usb-2"'):
        if token not in led:
            raise SystemExit(f"MF runtime LED label missing: {token}")
    for token in ("0x1fa20000", "0x1fb58000"):
        if token in led:
            raise SystemExit(f"AN7581 raw LED MMIO survived MF runtime: {token}")

    make = (root / "cmd/Makefile").read_text(encoding="utf-8")
    if "ursusstock.o" not in make:
        raise SystemExit("MF runtime StockBridge object is not linked")
    dispatch = (root / "cmd/ursusdispatch.c").read_text(encoding="utf-8")
    if 'run_command("ursusstockboot", 0)' not in dispatch:
        raise SystemExit("MF runtime stock boot dispatch is missing")
    if "URSUS_MF2_STOCKBRIDGE_DISABLED" in dispatch:
        raise SystemExit("MF RAM-only StockBridge gate survived runtime transform")

    stock_text = (root / "cmd/ursusstock.c").read_text(encoding="utf-8")
    for marker in (
        "HDR3",
        'append_arg(out, outsz, "serdes_pon", "00")',
        'append_arg(out, outsz, "serdes_ethernet", "12")',
        'append_arg(out, outsz, "serdes_usb1", "00")',
        "URSUS_STOCKBOOT_TCBOOT_MF_ARGS pon=00 ethernet=12 wifi1=05 wifi2=05 usb1=00 usb2=02",
    ):
        if marker not in stock_text:
            raise SystemExit(f"MF runtime StockBridge marker missing: {marker}")
    if "HDR2" in stock_text:
        raise SystemExit("MF runtime StockBridge still contains HDR2")

    web_text = web.read_text(encoding="utf-8")
    ubi_text = (root / "cmd/ursusubi.c").read_text(encoding="utf-8")
    combined = web_text + ubi_text
    if "MF2 RAM-only build: persistent operations disabled" in combined:
        raise SystemExit("MF RAM-only HTTP POST gate survived runtime transform")
    for marker in (
        "URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE",
        "URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION",
        "URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE_STEP",
        "URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION_STEP",
        "URSUS_MF2_READONLY_REJECT operation=SETTINGS_RESET_BACKEND",
    ):
        if marker in combined:
            raise SystemExit(f"MF recovery write gate survived runtime transform: {marker}")

    if MF_PRELOADER_SHA not in combined:
        raise SystemExit("MF production preloader SHA was not bound into runtime Web/UBI source")
    if MF_BL2_SHA not in combined:
        raise SystemExit("MF BL2 candidate SHA was not bound into runtime Web/UBI source")
    if MD_PRELOADER_SHA in combined or MD_BL2_SHA in combined:
        raise SystemExit("MD transition hash leaked into MF runtime Web/UBI source")

    version_h = root / "include/ursus_version.h"
    vh = version_h.read_text(encoding="utf-8")
    vh, n = re.subn(r'#define URSUS_VERSION "[^"]+"', f'#define URSUS_VERSION "{VERSION}"', vh, count=1)
    if n != 1:
        raise SystemExit("MF runtime version header anchor missing")
    version_h.write_text(vh, encoding="utf-8")
    (root / ".scmversion").write_text(f"-UrsusBoot-{VERSION}\n", encoding="ascii")

    identity_files = ("cmd/ursusweb.c", "cmd/ursusubi.c", "cmd/ursusdispatch.c", "cmd/ursusstock.c", "cmd/ursusupdate.c", "include/ursusweb_ui.inc")
    leaks: list[str] = []
    for rel in identity_files:
        data = (root / rel).read_text(encoding="utf-8")
        for token in ("Nokia XG-040G-MD", "nokia,xg-040g-md", "nokia_xg-040g-md", "AN7581DT", "XG040GMC2P5G"):
            if token in data:
                leaks.append(f"{rel}:{token}")
    if leaks:
        raise SystemExit("MF runtime board identity leak: " + ", ".join(leaks))

    print("MF_RUNTIME_ENABLE=PASS writers=ubi/install/reset/fip stockbridge=hdr3+serdes fip-selfupdate=enabled validator=mf-general")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    ap.add_argument("pristine_root", type=Path)
    args = ap.parse_args()
    transform(args.source_root, args.pristine_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

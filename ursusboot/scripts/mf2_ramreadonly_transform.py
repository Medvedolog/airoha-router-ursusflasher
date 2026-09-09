#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

VERSION = "0.1.0-mf2-ram1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, data: str) -> None:
    path.write_text(data, encoding="utf-8")


def replace_exact(text: str, old: str, new: str, label: str, count: int = 1) -> str:
    got = text.count(old)
    if got != count:
        raise SystemExit(f"{label}: expected {count} exact matches, got {got}")
    return text.replace(old, new, count)


def replace_regex(text: str, pattern: str, new: str, label: str) -> str:
    # Use a callable replacement so backslashes in generated C source are not
    # interpreted a second time by re.sub (for example C "\\n" -> real LF).
    out, count = re.subn(pattern, lambda _match: new, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label}: expected one regex match, got {count}")
    return out


def transform(root: Path) -> None:
    web = root / "cmd/ursusweb.c"
    update = root / "cmd/ursusupdate.c"
    ubi = root / "cmd/ursusubi.c"
    led = root / "cmd/ursusled.c"
    gpio_makefile = root / "drivers/gpio/Makefile"
    version_h = root / "include/ursus_version.h"
    scm = root / ".scmversion"

    for path in (web, update, ubi, led, gpio_makefile, version_h, scm):
        if not path.is_file():
            raise SystemExit(f"missing source file: {path}")

    # Dedicated MF identity. Keep this board-specific rather than spreading
    # runtime if(MF) branches through the shared UrsusBoot sources.
    w = read(web)
    w = w.replace("Nokia XG-040G-MD", "Nokia XG-040G-MF")
    w = w.replace("Airoha AN7581", "Airoha AN7583")
    w = w.replace("nokia,xg-040g-md-ubi", "nokia,xg-040g-mf-ubi")
    w = w.replace("nokia,xg-040g-md", "nokia,xg-040g-mf")

    old_ubi_probe = '''    if ((ret == 0 || ret == -EUCLEAN) && retlen == 4 && !memcmp(head, "UBI#", 4)) {\n        strcpy(ursus_current_layout, "OPENWRT_UBI");\n        printf("URSUS_BADBLOCK_SCAN source=UBI skip_full_mtd_scan=1\\n");\n        if (ursus_ubi_probe_diag(&ursus_ubi_diag)) {\n            printf("URSUS_UBI_DIAGNOSTIC_PROBE_FAILED\\n");\n        } else {\n            ursus_ubi_fip = ursus_ubi_diag.fip.present && ursus_ubi_diag.fip.valid;\n            ursus_ubi_fit = (ursus_ubi_diag.fit.present && ursus_ubi_diag.fit.valid) ||\n                            (ursus_ubi_diag.fit_old.present && ursus_ubi_diag.fit_old.valid);\n            ursus_bad_blocks = ursus_ubi_diag.bad_pebs;\n        }\n        ursus_boot_fip = ursus_ubi_fip;\n    } else {\n'''
    new_ubi_probe = '''    if ((ret == 0 || ret == -EUCLEAN) && retlen == 4 && !memcmp(head, "UBI#", 4)) {\n        /* MF2 is a RAM-only bring-up image. Do not attach/detach UBI here:\n         * raw MTD reads and bad-block queries are sufficient to prove NAND\n         * geometry and the physical UBI signature without changing state. */\n        strcpy(ursus_current_layout, "OPENWRT_UBI");\n        printf("URSUS_MF2_READONLY_UBI_PROBE raw_mtd_only=1 attach=0\\n");\n        if (nand->erasesize) {\n            printf("URSUS_BADBLOCK_SCAN source=MTD full_scan=1 readonly=1\\n");\n            for (off = 0; off < nand->size; off += nand->erasesize) {\n                ret = mtd_block_isbad(nand, off);\n                if (ret > 0)\n                    ursus_bad_blocks++;\n            }\n        }\n        memset(&ursus_ubi_diag, 0, sizeof(ursus_ubi_diag));\n        ursus_ubi_fip = false;\n        ursus_ubi_fit = false;\n        ursus_boot_fip = false;\n    } else {\n'''
    w = replace_exact(w, old_ubi_probe, new_ubi_probe, "web raw-only UBI probe")

    post_anchor = '''    if (URSUS_REQ_MATCH(c->reqhdr, "GET /api/log ") ||\n        URSUS_REQ_MATCH(c->reqhdr, "GET /api/operation-log "))\n        return ursus_http_start_response(pcb, c, 200, "text/plain; charset=utf-8", ursus_web_log);\n'''
    post_gate = post_anchor + '''    if (!strncmp(c->reqhdr, "POST ", 5)) {\n        ursus_logf("MF2 READONLY: rejected HTTP POST\\n");\n        return ursus_http_start_response(pcb, c, 403, "application/json",\n            "{\\\"result\\\":\\\"REJECTED\\\",\\\"reason_class\\\":\\\"READ_ONLY_BRINGUP\\\",\\\"reason\\\":\\\"MF2 RAM-only build: persistent operations disabled\\\"}\\n");\n    }\n'''
    w = replace_exact(w, post_anchor, post_gate, "web POST gate")

    settings_anchor = '''static int do_ursussettings(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])\n{\n    bool fip_ok = false, fit_ok = false;\n    int ret;\n\n'''
    settings_gate = settings_anchor + '''    printf("URSUS_MF2_READONLY_REJECT operation=SETTINGS_RESET\\n");\n    return CMD_RET_FAILURE;\n\n'''
    w = replace_exact(w, settings_anchor, settings_gate, "ursussettings gate")

    status_old = '''             "\\\"soc\\\":\\\"Airoha AN7583\\\",\\\"boot_fdt_compatible\\\":\\\"%s\\\",\\\"dram_mib\\\":%u,"\n'''
    status_new = '''             "\\\"soc\\\":\\\"Airoha AN7583\\\",\\\"ram_read_only\\\":true,\\\"persistent_write_enabled\\\":false,\\\"boot_fdt_compatible\\\":\\\"%s\\\",\\\"dram_mib\\\":%u,"\n'''
    w = replace_exact(w, status_old, status_new, "status read-only capability")
    write(web, w)

    u = read(update)
    u = u.replace("Nokia XG-040G-MD / Airoha AN7581", "Nokia XG-040G-MF / Airoha AN7583")
    u = u.replace("nokia,xg-040g-md-ubi", "nokia,xg-040g-mf-ubi")
    u = u.replace("nokia,xg-040g-md", "nokia,xg-040g-mf")
    start_anchor = '''int ursus_fip_update_start(ulong addr, size_t len)\n{\n    bool is_ubi = false;\n    int ret;\n    const u8 *buf;\n\n'''
    start_gate = start_anchor + '''    printf("URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE\\n");\n    return -EROFS;\n\n'''
    u = replace_exact(u, start_anchor, start_gate, "FIP update gate")
    write(update, u)

    q = read(ubi)
    q = q.replace("Nokia XG-040G-MD", "Nokia XG-040G-MF")
    upd_anchor = '''int ursus_ubi_update_start(ulong fit_addr, size_t fit_len, bool keep_settings)\n{\n'''
    upd_gate = upd_anchor + '''    printf("URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE\\n");\n    return -EROFS;\n\n'''
    q = replace_exact(q, upd_anchor, upd_gate, "UBI update gate")
    mig_anchor = '''int ursus_ubi_migration_start(ulong fit_addr, size_t fit_len,\n                              ulong preloader_addr, size_t preloader_len)\n{\n'''
    mig_gate = mig_anchor + '''    printf("URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION\\n");\n    return -EROFS;\n\n'''
    q = replace_exact(q, mig_anchor, mig_gate, "UBI migration gate")
    write(ubi, q)

    # TEST61's LED module contains MD/AN7581 raw SCU + MT7531 register access.
    # MF2 must not guess AN7583 register mappings. Use only native DM LED labels
    # present in the MF DTS and make the LAN LED helper/command inert.
    l = read(led)
    l = replace_exact(l, '#define LED_STATUS_RED "status-red"', '#define LED_STATUS_RED "red:wan"', "MF red LED label")
    l = replace_exact(l, '#define LED_USB1_GREEN "usb1-green"', '#define LED_USB1_GREEN "green:usb-1"', "MF USB1 LED label")
    l = replace_exact(l, '#define LED_USB2_GREEN "usb2-green"', '#define LED_USB2_GREEN "green:usb-2"', "MF USB2 LED label")
    l = replace_regex(
        l,
        r'/\* Nokia XG-040G-MD / AN7581 LAN2-LAN4 front-panel PHY LED0 routing\..*?\n}\n\n(?=struct ursus_led_step)',
        '''/* MF2 / AN7583: LAN link LEDs are left entirely to the native AN7583\n * Ethernet/PCS/device-tree path.  The MD raw SCU/MT7531 MMIO sequence is not\n * applicable to MF and is deliberately absent from this RAM-only build. */\nvoid ursus_lan_led_enable(void)\n{\n    printf("URSUS_MF2_LAN_LED_SETUP raw_mmio=disabled native_an7583=1\\n");\n}\n\n''',
        "remove AN7581 LAN LED MMIO",
    )
    l = replace_regex(
        l,
        r'static int do_ursuslanled\(struct cmd_tbl \*cmdtp, int flag, int argc,\n\s+char \*const argv\[\]\)\n\{.*?U_BOOT_CMD\(ursuslanled, 2, 0, do_ursuslanled,\n\s+"Nokia LAN2-LAN4 hardware PHY LED routing",\n\s+"<status\|enable>"\);',
        '''static int do_ursuslanled(struct cmd_tbl *cmdtp, int flag, int argc,\n                           char *const argv[])\n{\n    if (argc != 2)\n        return CMD_RET_USAGE;\n    if (strcmp(argv[1], "status") && strcmp(argv[1], "enable"))\n        return CMD_RET_USAGE;\n    printf("URSUS_MF2_LAN_LED_STATUS raw_mmio=disabled native_an7583=1 action=%s\\n",\n           argv[1]);\n    return CMD_RET_SUCCESS;\n}\n\nU_BOOT_CMD(ursuslanled, 2, 0, do_ursuslanled,\n           "MF2 AN7583 LAN LED diagnostics; raw MMIO disabled",\n           "<status|enable>");''',
        "replace AN7581 LAN LED command",
    )
    write(led, l)

    gm = read(gpio_makefile)
    gm = replace_exact(
        gm,
        "obj-y += ursus_an7581_safe_gpio.o",
        "# MF2 AN7583: do not link the MD-only ursus_an7581_safe_gpio driver",
        "remove AN7581 safe GPIO object",
    )
    write(gpio_makefile, gm)

    vh = read(version_h)
    vh2, n = re.subn(r'#define URSUS_VERSION "[^"]+"', f'#define URSUS_VERSION "{VERSION}"', vh, count=1)
    if n != 1:
        raise SystemExit("version header: expected one URSUS_VERSION")
    write(version_h, vh2)
    write(scm, f"-UrsusBoot-{VERSION}\n")

    final_web = read(web)
    final_update = read(update)
    final_ubi = read(ubi)
    final_led = read(led)
    final_gpio_makefile = read(gpio_makefile)
    checks = {
        "mf identity": "Nokia XG-040G-MF" in final_web,
        "mf soc": "Airoha AN7583" in final_web,
        "readonly status": "persistent_write_enabled\\\":false" in final_web,
        "POST gate": "MF2 READONLY: rejected HTTP POST" in final_web,
        "settings gate": "URSUS_MF2_READONLY_REJECT operation=SETTINGS_RESET" in final_web,
        "FIP gate": "URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE" in final_update,
        "UBI update gate": "URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE" in final_ubi,
        "migration gate": "URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION" in final_ubi,
        "no MD compatible in web": "nokia,xg-040g-md" not in final_web,
        "no MD compatible in update": "nokia,xg-040g-md" not in final_update,
        "native MF red LED": 'LED_STATUS_RED "red:wan"' in final_led,
        "native MF USB1 LED": 'LED_USB1_GREEN "green:usb-1"' in final_led,
        "native MF USB2 LED": 'LED_USB2_GREEN "green:usb-2"' in final_led,
        "AN7581 SCU base removed": "0x1fa20000" not in final_led,
        "MT7531 raw base removed": "0x1fb58000" not in final_led,
        "AN7581 raw helpers removed": "ursus_scu_read" not in final_led and "ursus_lanphy_c45_write" not in final_led,
        "AN7581 safe GPIO object removed": "obj-y += ursus_an7581_safe_gpio.o" not in final_gpio_makefile,
        "MF2 LAN LED no-op marker": "URSUS_MF2_LAN_LED_SETUP raw_mmio=disabled" in final_led,
        "no multiline C printf literal": re.search(r'printf\("[^"\\]*\n', final_led) is None,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise SystemExit("MF2 transform invariant failed: " + ", ".join(failed))
    print("MF2_RAMREADONLY_TRANSFORM=PASS")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    args = ap.parse_args()
    transform(args.source_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

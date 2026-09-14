#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"board policy anchor {label!r}: expected 1, found {count}")
    return text.replace(old, new, 1)


def sub_once(text: str, pattern: str, repl: str, label: str, flags: int = 0) -> str:
    # Use a callable replacement so backslashes in generated C strings are copied
    # literally. A plain replacement string would let re.sub() reinterpret \\n,
    # backreferences and other escapes, corrupting source such as printf("%s\\n").
    text, count = re.subn(pattern, lambda _m: repl, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"board policy regex anchor {label!r}: expected 1, found {count}")
    return text


def patch_dispatch(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "#include <ursus_board_policy.h>" not in text:
        text = replace_once(
            text,
            "#include <ursus_version.h>\n",
            "#include <ursus_version.h>\n#include <ursus_board_policy.h>\n",
            "dispatch include",
        )

    text = sub_once(text, r"^#define URSUS_FACTORY_KERNEL_OFF\s+.*$", "#define URSUS_FACTORY_KERNEL_OFF  URSUS_BOARD_FACTORY_KERNEL_OFF", "factory off", re.M)
    text = sub_once(text, r"^#define URSUS_FACTORY_KERNEL_SIZE\s+.*$", "#define URSUS_FACTORY_KERNEL_SIZE URSUS_BOARD_FACTORY_KERNEL_SIZE", "factory size", re.M)
    text = replace_once(text, "mtd_read(nand, 0x00020000ULL, sizeof(hdr), &retlen, hdr)", "mtd_read(nand, URSUS_BOARD_UBI_PROBE_OFF, sizeof(hdr), &retlen, hdr)", "ubi probe offset")
    text = replace_once(text, "if (ursus_ubi_present(nand)) {", "if (URSUS_BOARD_ALLOW_UBI_BOOT && ursus_ubi_present(nand)) {", "ubi policy")
    text = replace_once(text, "if (ursus_factory_kernel_present(nand)) {", "if (URSUS_BOARD_ALLOW_FACTORY_FIT && ursus_factory_kernel_present(nand)) {", "factory policy")
    text = replace_once(text, "printf(\"URSUS_DISPATCH_BEGIN\\n\");", "printf(\"URSUS_DISPATCH_BEGIN\\n\");\n    printf(\"URSUS_BOARD_PROFILE=%s\\n\", URSUS_BOARD_POLICY_ID);", "profile marker")
    text = text.replace(
        'URSUS_PRODUCT_VERSION " boot-held Reset / stock-layout + UBI dispatcher"',
        'URSUS_PRODUCT_VERSION " modular Airoha boot/recovery dispatcher"',
    )
    path.write_text(text, encoding="utf-8")


def patch_stock(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "#include <ursus_board_policy.h>" not in text:
        text = replace_once(
            text,
            "#include <ursus_version.h>\n",
            "#include <ursus_version.h>\n#include <ursus_board_policy.h>\n",
            "stock include",
        )

    defs = {
        "STOCK_MASTER_BASE": "URSUS_BOARD_STOCK_MASTER_BASE",
        "STOCK_SLAVE_BASE": "URSUS_BOARD_STOCK_SLAVE_BASE",
        "STOCK_SLOT_SIZE": "URSUS_BOARD_STOCK_SLOT_SIZE",
        "STOCK_ENV_BASE": "URSUS_BOARD_STOCK_ENV_BASE",
        "STOCK_ENV_SIZE": "URSUS_BOARD_STOCK_ENV_SIZE",
        "STOCK_TRX_HDR_SIZE": "URSUS_BOARD_STOCK_TRX_HDR_SIZE",
        "FIT_MAX_SIZE": "URSUS_BOARD_STOCK_FIT_MAX_SIZE",
        "ORACLE_FIT_SIZE": "URSUS_BOARD_ORACLE_FIT_SIZE",
        "ORACLE_KERNEL_OFF": "URSUS_BOARD_ORACLE_KERNEL_OFF",
        "ORACLE_KERNEL_SIZE": "URSUS_BOARD_ORACLE_KERNEL_SIZE",
        "ORACLE_ROOTFS_OFF": "URSUS_BOARD_ORACLE_ROOTFS_OFF",
        "ORACLE_ROOTFS_SIZE": "URSUS_BOARD_ORACLE_ROOTFS_SIZE",
    }
    for name, value in defs.items():
        text = sub_once(text, rf"^#define {name}\s+.*$", f"#define {name:<24} {value}", f"stock define {name}", re.M)

    text = sub_once(text, r"^#define HDR[23]_SIZE\s+STOCK_TRX_HDR_SIZE$", "#define STOCK_HDR_SIZE         STOCK_TRX_HDR_SIZE", "stock HDR size", re.M)
    text = text.replace("HDR2_SIZE", "STOCK_HDR_SIZE").replace("HDR3_SIZE", "STOCK_HDR_SIZE")
    text = sub_once(text, r'memcmp\(hdrpage, "HDR[23]", 4\)', "memcmp(hdrpage, URSUS_BOARD_STOCK_HDR_MAGIC, 4)", "stock HDR magic")
    text = re.sub(r"URSUS_STOCKBOOT_%s_HDR[23]_INVALID", "URSUS_STOCKBOOT_%s_HDR_INVALID", text)

    text = replace_once(
        text,
        'root = bootflag ? "/dev/mtdblock5 ro" : stock_env_get(se, "root");',
        'root = bootflag ? URSUS_BOARD_ROOT_SLAVE : stock_env_get(se, "root");',
        "stock root primary",
    )
    text = replace_once(
        text,
        'root = bootflag ? "/dev/mtdblock5 ro" : "/dev/mtdblock3 ro";',
        'root = bootflag ? URSUS_BOARD_ROOT_SLAVE : URSUS_BOARD_ROOT_MASTER;',
        "stock root fallback",
    )

    serdes_pattern = r'''    if \(append_arg\(out, outsz, "serdes_[\s\S]+?\n        return -ENOSPC;\n\n    /\* Match the Nokia stock boot ABI'''
    serdes_repl = '''    if (URSUS_BOARD_APPEND_SERDES_ARGS(out, outsz))\n        return -ENOSPC;\n\n    /* Match the Nokia stock boot ABI'''
    text = sub_once(text, serdes_pattern, serdes_repl, "stock SerDes policy")

    text = sub_once(
        text,
        r'    printf\("URSUS_STOCKBOOT_TCBOOT_[^"\n]+\\n"\);',
        '    printf("%s\\n", URSUS_BOARD_STOCK_ARGS_MARKER);',
        "stock args marker",
    )
    text = replace_once(
        text,
        "if (chosen->fit_size == ORACLE_FIT_SIZE &&",
        "if (URSUS_BOARD_ORACLE_FIT_SIZE && chosen->fit_size == ORACLE_FIT_SIZE &&",
        "stock oracle gate",
    )
    text = replace_once(text, 'printf("URSUS_STOCKBOOT_BEGIN\\n");', 'printf("URSUS_STOCKBOOT_BEGIN\\n");\n    printf("URSUS_BOARD_PROFILE=%s\\n", URSUS_BOARD_POLICY_ID);', "stock profile marker")
    text = text.replace(
        'URSUS_PRODUCT_VERSION " StockBridge boot with Nokia tcboot board-argument parity"',
        'URSUS_PRODUCT_VERSION " modular stock-slot StockBridge"',
    )
    path.write_text(text, encoding="utf-8")


def verify(root: Path) -> None:
    dispatch = (root / "cmd/ursusdispatch.c").read_text(encoding="utf-8")
    stock = (root / "cmd/ursusstock.c").read_text(encoding="utf-8")
    for token in (
        "URSUS_BOARD_POLICY_ID",
        "URSUS_BOARD_ALLOW_UBI_BOOT",
        "URSUS_BOARD_ALLOW_FACTORY_FIT",
        "URSUS_BOARD_UBI_PROBE_OFF",
    ):
        if token not in dispatch:
            raise SystemExit(f"board policy dispatch marker missing: {token}")
    for token in (
        "URSUS_BOARD_STOCK_MASTER_BASE",
        "URSUS_BOARD_STOCK_SLAVE_BASE",
        "URSUS_BOARD_STOCK_ENV_BASE",
        "URSUS_BOARD_STOCK_HDR_MAGIC",
        "URSUS_BOARD_APPEND_SERDES_ARGS",
        "URSUS_BOARD_ROOT_MASTER",
        "URSUS_BOARD_ROOT_SLAVE",
    ):
        if token not in stock:
            raise SystemExit(f"board policy stock marker missing: {token}")
    for forbidden in (
        "#define STOCK_MASTER_BASE     0x",
        "#define STOCK_SLAVE_BASE      0x",
        'memcmp(hdrpage, "HDR2", 4)',
        'memcmp(hdrpage, "HDR3", 4)',
    ):
        if forbidden in stock:
            raise SystemExit(f"hard-coded board policy survived: {forbidden}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply a modular UrsusBoot board policy to MD-derived common source")
    ap.add_argument("root", type=Path)
    ap.add_argument("policy", type=Path)
    args = ap.parse_args()
    root = args.root.resolve()
    policy = args.policy.resolve()
    if not policy.is_file():
        raise SystemExit(f"board policy header missing: {policy}")
    include = root / "include" / "ursus_board_policy.h"
    if not include.parent.is_dir():
        raise SystemExit(f"U-Boot include directory missing: {include.parent}")
    shutil.copy2(policy, include)
    patch_dispatch(root / "cmd" / "ursusdispatch.c")
    patch_stock(root / "cmd" / "ursusstock.c")
    verify(root)
    print(f"URSUS_BOARD_POLICY_APPLY=PASS policy={policy.stem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

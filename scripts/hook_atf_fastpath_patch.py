#!/usr/bin/env python3
"""Make OpenWrt's arm-trusted-firmware-airoha apply the UBI scan fast-path patch
inside Build/Prepare, right after the atf-airoha sources are unpacked.

Patching build_dir after `make .../prepare` is not enough: `make .../compile`
may run Build/Prepare again, re-extract atf-airoha over the tree and silently
drop the patch (seen in "MD AN7581 TEST62 + fast BL2" run #5). Hooking the
patch into Build/Prepare means every (re)extraction is patched, and a patch that
does not apply fails the build.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ANCHOR = (
    "\t$(eval $(call Download,atf-airoha))\n"
    "\t$(TAR) -C $(PKG_BUILD_DIR) --strip-components=1 -xf $(DL_DIR)/$(FILE)\n"
    "endef\n"
)
MARK = "# URSUS_ATF_FASTPATH_HOOK"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--openwrt", required=True)
    ap.add_argument("--patch", required=True)
    args = ap.parse_args()
    patch = Path(args.patch).resolve()
    if not patch.is_file() or patch.stat().st_size == 0:
        raise SystemExit(f"fast-path patch missing: {patch}")
    mk = Path(args.openwrt) / "package" / "boot" / "arm-trusted-firmware-airoha" / "Makefile"
    s = mk.read_text(encoding="utf-8")
    if MARK in s:
        raise SystemExit("fast-path hook already present")
    if s.count(ANCHOR) != 1:
        raise SystemExit("atf-airoha Build/Prepare anchor not found exactly once")
    hook = (
        "\t$(eval $(call Download,atf-airoha))\n"
        "\t$(TAR) -C $(PKG_BUILD_DIR) --strip-components=1 -xf $(DL_DIR)/$(FILE)\n"
        f"\t{MARK}\n"
        f"\tpatch -d $(PKG_BUILD_DIR) -p1 --forward < {patch}\n"
        "\tgrep -Fq nandflash_read_range $(PKG_BUILD_DIR)/plat/ecnt/en7523/bl2_boot_nand_ubi.c\n"
        "endef\n"
    )
    mk.write_text(s.replace(ANCHOR, hook), encoding="utf-8")
    print(f"ATF_FASTPATH_HOOK=INSTALLED makefile={mk} patch={patch}")


if __name__ == "__main__":
    main()

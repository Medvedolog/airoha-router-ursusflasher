#!/usr/bin/env python3
"""Overlay the MF (AN7583) TEST62 runtime + fast BL2 CI artifact onto an exported kit tree.

MF counterpart of apply_md_test62_overlay.py: the MF UrsusBoot TEST62 runtime
(u-boot.runtime.lzma, UART RAM FIP) and the fast-scan AN7583 UBI preloader,
whose SHA256 must be compiled into that runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

from apply_md_test62_overlay import is_fip, require_pinned, set_preloader_role, sha256, tb_fw_payload, wrap_tb_fw

MF_VERSION = "0.1.0-TEST62"
RUNTIME = "u-boot.runtime.lzma"
RAM_FIP = f"ursusboot-mf-{MF_VERSION}-runtime-ram.fip"
UART_PRELOADER = f"ursusboot-mf-{MF_VERSION}-uart-preloader.bin"
FAST_BL2_NAME = "openwrt-airoha-an7583-nokia-xg040mf-TEST62-fast-ubi-preloader.bin"
CANONICAL_PRELOADER = "nokia-xg-040g-mf-an7583-production-preloader.bin"
BUILD_INFO = "MF-RUNTIME-BUILD-INFO.txt"


def apply_overlay(tree: Path, artifacts: Path) -> None:
    tree = tree.resolve()
    art = artifacts.resolve()
    for name in (RUNTIME, RAM_FIP, UART_PRELOADER, FAST_BL2_NAME, "u-boot.bin", BUILD_INFO):
        p = art / name
        if not p.is_file() or p.stat().st_size == 0:
            raise FileNotFoundError(f"required MF TEST62 artifact missing: {p}")
    info = (art / BUILD_INFO).read_text(encoding="utf-8", errors="replace")
    if f"UrsusBoot {MF_VERSION}" not in info or "UBI_PRELOADER_SHA256=" not in info:
        raise RuntimeError("MF build-info does not identify a TEST62 runtime pinned to a fast preloader")
    bl33 = (art / "u-boot.bin").read_bytes()
    if MF_VERSION.encode() not in bl33 or b"Nokia XG-040G-MF" not in bl33:
        raise RuntimeError("MF u-boot.bin is not the MF TEST62 runtime")

    pay = tree / "data" / "payloads" / "mf"
    (pay / "ursusboot").mkdir(parents=True, exist_ok=True)
    (pay / "recovery").mkdir(parents=True, exist_ok=True)
    (pay / "proven").mkdir(parents=True, exist_ok=True)
    shutil.copy2(art / RUNTIME, pay / "ursusboot" / RUNTIME)
    shutil.copy2(art / RAM_FIP, pay / "recovery" / RAM_FIP)
    shutil.copy2(art / UART_PRELOADER, pay / "recovery" / UART_PRELOADER)
    for stale in (pay / "recovery").glob("*TEST61*"):
        stale.unlink()

    dst = pay / "proven" / CANONICAL_PRELOADER
    blob = (art / FAST_BL2_NAME).read_bytes()
    dst.write_bytes(blob if is_fip(blob) else wrap_tb_fw(blob))
    tb_fw_payload(dst.read_bytes())
    require_pinned(bl33, dst, "MF TEST62 runtime")
    set_preloader_role(tree, "mf", dst, "MF TEST62 fast BL2")

    (tree / "MF_TEST62_PROVENANCE.txt").write_text(
        f"URSUSBOOT_MF={MF_VERSION}\n"
        f"RUNTIME_LZMA_SHA256={sha256(pay / 'ursusboot' / RUNTIME)}\n"
        f"RAW_BL33_SHA256={hashlib.sha256(bl33).hexdigest()}\n"
        f"RAM_FIP_SHA256={sha256(pay / 'recovery' / RAM_FIP)}\n"
        f"UART_PRELOADER_SHA256={sha256(pay / 'recovery' / UART_PRELOADER)}\n"
        f"FAST_BL2_RAW_SHA256={hashlib.sha256(tb_fw_payload(dst.read_bytes())).hexdigest()}\n"
        f"FAST_BL2_PRELOADER_FIP_SHA256={sha256(dst)}\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True)
    ap.add_argument("--artifacts", required=True)
    args = ap.parse_args()
    apply_overlay(Path(args.tree), Path(args.artifacts))


if __name__ == "__main__":
    main()

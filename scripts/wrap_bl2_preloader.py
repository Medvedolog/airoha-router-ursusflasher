#!/usr/bin/env python3
"""Wrap a raw Airoha BL2 (<soc>-bl2.bin) into the UBI preloader FIP form
(byte-identical to `fiptool create --tb-fw`), as UrsusBoot and BL2-LAST expect."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from apply_md_test62_overlay import is_fip, tb_fw_payload, wrap_tb_fw

MAX_PRELOADER = 0x20000 - 0x800  # must fit the 128 KiB BL2 candidate after the 0x800 FF prefix


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bl2", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    raw = Path(args.bl2).read_bytes()
    if not raw or is_fip(raw):
        raise SystemExit("expected a raw, non-empty BL2 image")
    fip = wrap_tb_fw(raw)
    if len(fip) > MAX_PRELOADER:
        raise SystemExit(f"preloader FIP {len(fip)} bytes exceeds {MAX_PRELOADER}")
    assert tb_fw_payload(fip) == raw
    Path(args.out).write_bytes(fip)
    print(f"PRELOADER_FIP={args.out} size={len(fip)} sha256={hashlib.sha256(fip).hexdigest()} "
          f"bl2_sha256={hashlib.sha256(raw).hexdigest()}")


if __name__ == "__main__":
    main()

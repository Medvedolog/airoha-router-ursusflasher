#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def patch(root: Path) -> None:
    path = root / "drivers/net/airoha_eth.c"
    if not path.is_file():
        raise SystemExit(f"missing Airoha ethernet driver: {path}")

    text = path.read_text(encoding="utf-8")
    marker = "URSUS_MF2_HWTEST5_PHY_LED0"
    if marker in text:
        raise SystemExit("HWTEST5 PHY LED patch already applied")

    anchor = "Disable BMCR_PDOWN for every PHY"
    pos = text.find(anchor)
    if pos < 0:
        raise SystemExit("AN7583 PHY power-up loop anchor not found")

    lines = text.splitlines()
    anchor_line = text[:pos].count("\n") + 1
    lo = max(1, anchor_line - 22)
    hi = min(len(lines), anchor_line + 48)
    print(f"MF2_HWTEST5_SOURCE_INSPECT file={path.relative_to(root)} anchor_line={anchor_line}")
    for no in range(lo, hi + 1):
        print(f"SRC {no:04d}: {lines[no - 1]}")

    raise SystemExit("HWTEST5 source inspection complete; implement against captured AN7583 loop")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    args = ap.parse_args()
    patch(args.source_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

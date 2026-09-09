#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import board_profiles as bp


def main() -> int:
    md = bp.match_profile(model="XG-040G-MD", soc="AN7581")
    assert md and md[0] == "md"
    assert md[1]["model"] == "Nokia XG-040G-MD"

    mf = bp.match_profile(model="XG-040G-MF", soc="Airoha AN7583")
    assert mf and mf[0] == "mf"
    assert mf[1]["flash"]["nand_size"] == 0x10000000
    assert mf[1]["flash"]["erase_size"] == 0x20000
    assert mf[1]["flash"]["bl2_size"] == 0x20000
    assert mf[1]["flash"]["ubi_size"] == 0x0FFE0000
    assert mf[1]["flash"]["bosa_offset"] == 0x051C0000
    assert mf[1]["flash"]["ri_offset"] == 0x05200000
    assert not bp.persistent_writes_enabled(mf[1])

    assert bp.match_profile(model="XG-040G-MF", soc="AN7581") is None
    assert bp.match_profile(model="XG-040G-MD", soc="AN7583") is None

    owrt_mf = bp.canonical_identity(board="airoha,nokia-xg-040g-mf", soc="AN7583")
    assert owrt_mf == ("mf", "Nokia XG-040G-MF", "Airoha AN7583")

    print("PASS: MF1 board profiles and cross-family identity gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

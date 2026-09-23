#!/usr/bin/env python3
"""An MF stock backup passes the default (slot-layout) backup validator.

MF hardware session: stock restore over SSH stopped at STAGE_R1 with the rc12
refusal "MF normal OpenWrt install remains blocked pending a separate HW gate",
although MF install and restore are hardware-proven. Sparse zero dumps with the
MF-A slot sizes must validate as family MF, the MD layout as MD.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import proven_backend as pb  # noqa: E402

pb._LANG = "en"


def make(tmp: Path, slots: dict[int, int]) -> Path:
    sizes = dict(pb.FIXED_EXPECTED)
    sizes.update(slots)
    for n in pb.EXPECTED_NUMBERS:
        with (tmp / f"mtd{n}.bin").open("wb") as f:
            f.truncate(sizes[n])
    return tmp


ok = True
for fam, slots in (("mf", pb.MF_SLOT_LAYOUTS[0]), ("md", pb.SLOT_LAYOUTS[0])):
    with tempfile.TemporaryDirectory() as d:
        try:
            got = pb.verify_backup(make(Path(d), slots)).get("stock_family")
            good = got == fam
            detail = got
        except pb.Error as exc:
            good, detail = False, str(exc)
    print(("PASS " if good else "FAIL ") + f"{fam.upper()} stock backup validates with the default validator: {detail}")
    ok &= good
print("selftest_mf_backup_gate: " + ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)

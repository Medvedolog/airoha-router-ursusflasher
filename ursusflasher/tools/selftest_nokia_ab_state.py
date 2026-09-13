#!/usr/bin/env python3
import importlib.util
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("nokia_ab_state", HERE / "nokia_ab_state.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def blob(active: int, curimg: int, startok: int, count: int, size: int = 0x40000) -> bytes:
    return struct.pack("<4I", active, curimg, startok, count) + b"\xff" * (size - 16)


# Hardware-observed MD post-success state supplied during Vanilla A/B NIOKR.
flag = mod.parse_blob(blob(0, 0, 1, 15), "flag")
flagback = mod.parse_blob(blob(0, 0, 0, 15), "flagback")
r = mod.reconcile(flag, flagback)
assert flag["slot"] == "MAIN"
assert flag["tail_erased_ff"] is True
assert r["confidence"] == "HIGH_SELECTOR_MATCH_STARTOK_DIVERGED"
assert r["resolved_slot"] == "MAIN"
assert r["writer_safe"] is False

# Matching selector state is accepted read-only, but writer remains disabled.
flag2 = mod.parse_blob(blob(0, 1, 0, 7), "flag")
flagback2 = mod.parse_blob(blob(0, 1, 0, 7), "flagback")
r2 = mod.reconcile(flag2, flagback2)
assert r2["confidence"] == "HIGH_MATCH"
assert r2["resolved_slot"] == "SLAVE"
assert r2["writer_safe"] is False

# Selector disagreement must never resolve to a slot.
flag3 = mod.parse_blob(blob(0, 0, 0, 7), "flag")
flagback3 = mod.parse_blob(blob(0, 1, 0, 7), "flagback")
r3 = mod.reconcile(flag3, flagback3)
assert r3["confidence"] == "LOW_SELECTOR_DIVERGED"
assert r3["resolved_slot"] == "UNKNOWN"
assert r3["writer_safe"] is False

print("selftest_nokia_ab_state: PASS")

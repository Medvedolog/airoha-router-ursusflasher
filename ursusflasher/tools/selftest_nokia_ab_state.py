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
    return struct.pack("<5I", active, curimg, startok, count, 0xFFFFFFFF) + b"\xff" * (size - 20)


# Hardware-observed MD post-success state supplied during Vanilla A/B NIOKR.
flag_blob = blob(0, 0, 1, 15)
flag = mod.parse_blob(flag_blob, "flag")
flagback = mod.parse_blob(blob(0, 0, 0, 15), "flagback")
r = mod.reconcile(flag, flagback)
assert flag["current_slot"] == "MAIN"
assert flag["requested_slot"] == "MAIN"
assert flag["switch_pending"] is False
assert flag["tail_erased_ff"] is True
assert r["confidence"] == "HIGH_SELECTOR_MATCH_STARTOK_DIVERGED"
assert r["resolved_current_slot"] == "MAIN"
assert r["writer_safe"] is False

# Offline stock-compatible request to boot SLAVE changes active only.
p = mod.plan_activation(flag_blob, 1)
assert p["target_slot"] == "SLAVE"
assert p["write_required"] is True
assert p["changed_fields"] == ["active"]
assert p["old"] == {
    "active": 0,
    "curimg": 0,
    "startok": 1,
    "count": 15,
    "reserved": 0xFFFFFFFF,
}
assert p["new"] == {
    "active": 1,
    "curimg": 0,
    "startok": 1,
    "count": 15,
    "reserved": 0xFFFFFFFF,
}
assert bytes.fromhex(p["payload_hex"]) == struct.pack("<5I", 1, 0, 1, 15, 0xFFFFFFFF)
assert p["flagback_write"] is False
assert p["device_writer_enabled"] is False

# Requesting the already-current image is a no-op, matching stock swdl_active().
p_same = mod.plan_activation(flag_blob, 0)
assert p_same["write_required"] is False
assert p_same["changed_fields"] == []

# Selector disagreement must never resolve to a current slot.
flag3 = mod.parse_blob(blob(0, 0, 0, 7), "flag")
flagback3 = mod.parse_blob(blob(1, 1, 0, 7), "flagback")
r3 = mod.reconcile(flag3, flagback3)
assert r3["confidence"] == "LOW_SELECTOR_DIVERGED"
assert r3["resolved_current_slot"] == "UNKNOWN"
assert r3["writer_safe"] is False

print("selftest_nokia_ab_state: PASS")

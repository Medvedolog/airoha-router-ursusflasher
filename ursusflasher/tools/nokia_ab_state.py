#!/usr/bin/env python3
"""Read-only parser for Nokia/Airoha stock A/B flag state."""
from __future__ import annotations

import argparse
import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

STATE_SIZE = 16
ERASED = 0xFF


@dataclass(frozen=True)
class ABState:
    active: int
    curimg: int
    startok: int
    count: int

    @property
    def fields_plausible(self) -> bool:
        return self.active in (0, 1) and self.curimg in (0, 1) and self.startok in (0, 1)

    @property
    def slot(self) -> str:
        # curimg=0 -> MAIN is hardware-observed on MD/MF stock bootlogs.
        # curimg=1 -> SLAVE is the inverse mapping and remains hardware-acceptance gated.
        return "MAIN" if self.curimg == 0 else "SLAVE" if self.curimg == 1 else "UNKNOWN"


def parse_blob(blob: bytes, label: str) -> dict:
    if len(blob) < STATE_SIZE:
        raise ValueError(f"{label}: short read: {len(blob)} bytes, need at least {STATE_SIZE}")
    state = ABState(*struct.unpack_from("<4I", blob, 0))
    tail = blob[STATE_SIZE:]
    tail_erased = all(b == ERASED for b in tail)
    return {
        "label": label,
        "size": len(blob),
        "state": asdict(state),
        "slot": state.slot,
        "fields_plausible": state.fields_plausible,
        "tail_erased_ff": tail_erased,
        "extra_non_ff_bytes": sum(1 for b in tail if b != ERASED),
    }


def reconcile(flag: dict, flagback: dict) -> dict:
    a = ABState(**flag["state"])
    b = ABState(**flagback["state"])
    same_selector = (a.active, a.curimg) == (b.active, b.curimg)
    same_count = a.count == b.count
    same_startok = a.startok == b.startok
    valid = (
        flag["fields_plausible"]
        and flag["tail_erased_ff"]
        and flagback["fields_plausible"]
        and flagback["tail_erased_ff"]
    )

    if valid and same_selector and same_count and same_startok:
        confidence = "HIGH_MATCH"
    elif valid and same_selector and same_count and {a.startok, b.startok} <= {0, 1}:
        # Observed on stock MD/MF after successful userspace boot: primary startok=1,
        # backup startok=0 while selector/count agree. Do not infer write ordering here.
        confidence = "HIGH_SELECTOR_MATCH_STARTOK_DIVERGED"
    elif valid and same_selector:
        confidence = "MEDIUM_SELECTOR_MATCH_STATE_DIVERGED"
    elif valid:
        confidence = "LOW_SELECTOR_DIVERGED"
    else:
        confidence = "INVALID_OR_UNKNOWN"

    return {
        "confidence": confidence,
        "selector_agrees": same_selector,
        "count_agrees": same_count,
        "startok_agrees": same_startok,
        "resolved_curimg": a.curimg if same_selector else None,
        "resolved_slot": a.slot if same_selector else "UNKNOWN",
        "writer_safe": False,
        "writer_reason": "read-only parser; stock selector commit/rollback semantics are not proven",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only Nokia/Airoha flag+flagback parser")
    ap.add_argument("--flag", required=True, type=Path)
    ap.add_argument("--flagback", required=True, type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    flag = parse_blob(args.flag.read_bytes(), "flag")
    flagback = parse_blob(args.flagback.read_bytes(), "flagback")
    report = {"flag": flag, "flagback": flagback, "reconciliation": reconcile(flag, flagback)}

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for item in (flag, flagback):
            s = item["state"]
            print(
                f"{item['label']}: active={s['active']} curimg={s['curimg']} "
                f"startok={s['startok']} count={s['count']} slot={item['slot']}"
            )
            print(
                f"  size=0x{item['size']:x} tail_erased_ff={item['tail_erased_ff']} "
                f"extra_non_ff={item['extra_non_ff_bytes']}"
            )
        r = report["reconciliation"]
        print(
            f"reconciliation: {r['confidence']} selector_agrees={r['selector_agrees']} "
            f"resolved_slot={r['resolved_slot']}"
        )
        print(f"writer_safe={r['writer_safe']} reason={r['writer_reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

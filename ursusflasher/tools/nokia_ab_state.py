#!/usr/bin/env python3
"""Read-only parser and offline planner for Nokia/Airoha stock A/B flag state."""
from __future__ import annotations

import argparse
import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

# Stock libupgrade read_flag()/write_flag() operate on exactly 20 bytes.
STATE_SIZE = 20
ERASED = 0xFF
RESERVED_ERASED = 0xFFFFFFFF


@dataclass(frozen=True)
class ABState:
    active: int
    curimg: int
    startok: int
    count: int
    reserved: int

    @property
    def fields_plausible(self) -> bool:
        return (
            self.active in (0, 1)
            and self.curimg in (0, 1)
            and self.startok in (0, 1)
            and self.reserved == RESERVED_ERASED
        )

    @property
    def current_slot(self) -> str:
        # Hardware-observed and stock libupgrade-confirmed mapping.
        return "MAIN" if self.curimg == 0 else "SLAVE" if self.curimg == 1 else "UNKNOWN"

    @property
    def requested_slot(self) -> str:
        # Stock swdl_active(image) writes the requested image to active, not curimg.
        return "MAIN" if self.active == 0 else "SLAVE" if self.active == 1 else "UNKNOWN"


def parse_blob(blob: bytes, label: str) -> dict:
    if len(blob) < STATE_SIZE:
        raise ValueError(f"{label}: short read: {len(blob)} bytes, need at least {STATE_SIZE}")
    state = ABState(*struct.unpack_from("<5I", blob, 0))
    tail = blob[STATE_SIZE:]
    tail_erased = all(b == ERASED for b in tail)
    return {
        "label": label,
        "size": len(blob),
        "state": asdict(state),
        "current_slot": state.current_slot,
        "requested_slot": state.requested_slot,
        "switch_pending": state.active != state.curimg,
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
    same_reserved = a.reserved == b.reserved
    valid = (
        flag["fields_plausible"]
        and flag["tail_erased_ff"]
        and flagback["fields_plausible"]
        and flagback["tail_erased_ff"]
    )

    if valid and same_selector and same_count and same_startok and same_reserved:
        confidence = "HIGH_MATCH"
    elif valid and same_selector and same_count and same_reserved and {a.startok, b.startok} <= {0, 1}:
        # Hardware-observed after successful stock boot: primary startok=1,
        # flagback startok=0 while selector/count agree.
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
        "reserved_agrees": same_reserved,
        "resolved_curimg": a.curimg if same_selector else None,
        "resolved_current_slot": a.current_slot if same_selector else "UNKNOWN",
        "resolved_active": a.active if same_selector else None,
        "resolved_requested_slot": a.requested_slot if same_selector else "UNKNOWN",
        "switch_pending": (a.active != a.curimg) if same_selector else None,
        "writer_safe": False,
        "writer_reason": "device writer intentionally disabled; only stock-compatible offline activation planning is implemented",
    }


def plan_activation(flag_blob: bytes, target: int) -> dict:
    """Build the exact 20-byte payload stock swdl_active() would request, without writing it.

    Reverse-engineered stock contract:
      * read 20 bytes from mtd8
      * if target == curimg: no write is required
      * otherwise modify only field 0 (active)
      * preserve curimg/startok/count/reserved
      * stock write_flag() erases one mtd8 eraseblock and writes these 20 bytes
      * flagback is not written by stock userspace
    """
    if target not in (0, 1):
        raise ValueError("target must be 0 (MAIN) or 1 (SLAVE)")
    parsed = parse_blob(flag_blob, "flag")
    if not parsed["fields_plausible"] or not parsed["tail_erased_ff"]:
        raise ValueError("flag state is not stock-plausible")
    old = ABState(**parsed["state"])
    new = ABState(target, old.curimg, old.startok, old.count, old.reserved)
    payload = struct.pack("<5I", new.active, new.curimg, new.startok, new.count, new.reserved)
    return {
        "target": target,
        "target_slot": new.requested_slot,
        "write_required": target != old.curimg,
        "old": asdict(old),
        "new": asdict(new),
        "changed_fields": [] if target == old.curimg else ["active"],
        "payload_hex": payload.hex(),
        "payload_size": len(payload),
        "stock_write_scope": "mtd8 only; erase one eraseblock then write 20-byte payload",
        "flagback_write": False,
        "device_writer_enabled": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only Nokia/Airoha flag+flagback parser")
    ap.add_argument("--flag", required=True, type=Path)
    ap.add_argument("--flagback", required=True, type=Path)
    ap.add_argument("--plan-active", choices=("main", "slave"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    flag_blob = args.flag.read_bytes()
    flag = parse_blob(flag_blob, "flag")
    flagback = parse_blob(args.flagback.read_bytes(), "flagback")
    report = {"flag": flag, "flagback": flagback, "reconciliation": reconcile(flag, flagback)}
    if args.plan_active:
        report["activation_plan"] = plan_activation(flag_blob, 0 if args.plan_active == "main" else 1)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for item in (flag, flagback):
            s = item["state"]
            print(
                f"{item['label']}: active={s['active']} curimg={s['curimg']} "
                f"startok={s['startok']} count={s['count']} reserved=0x{s['reserved']:08x} "
                f"current={item['current_slot']} requested={item['requested_slot']} "
                f"switch_pending={item['switch_pending']}"
            )
            print(
                f"  size=0x{item['size']:x} tail_erased_ff={item['tail_erased_ff']} "
                f"extra_non_ff={item['extra_non_ff_bytes']}"
            )
        r = report["reconciliation"]
        print(
            f"reconciliation: {r['confidence']} selector_agrees={r['selector_agrees']} "
            f"current={r['resolved_current_slot']} requested={r['resolved_requested_slot']} "
            f"switch_pending={r['switch_pending']}"
        )
        print(f"writer_safe={r['writer_safe']} reason={r['writer_reason']}")
        if args.plan_active:
            p = report["activation_plan"]
            print(
                f"activation_plan: target={p['target_slot']} write_required={p['write_required']} "
                f"changed_fields={','.join(p['changed_fields']) or 'none'} payload={p['payload_hex']}"
            )
            print("  device_writer_enabled=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

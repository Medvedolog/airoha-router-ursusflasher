#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path

FIP_MAGIC = 0xAA640001
NT_UUID = bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4")
CHECKSUM_UUID = bytes.fromhex("a2cceab7f8254b279704633a6fd69ad8")
ALIGN = 0x400
FIP_PHYS_OFF = 0x800
ENV_PHYS_OFF = 0x7C000
MAX_FIP_SIZE = ENV_PHYS_OFF - FIP_PHYS_OFF


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def align_up(value: int, align: int = ALIGN) -> int:
    return (value + align - 1) // align * align


def parse(data: bytes):
    if len(data) < 56:
        raise ValueError("FIP too small")
    magic, serial, flags = struct.unpack_from("<IIQ", data, 0)
    if magic != FIP_MAGIC:
        raise ValueError("bad FIP magic")
    entries = []
    pos = 16
    for _ in range(64):
        if pos + 40 > len(data):
            raise ValueError("FIP TOC truncated")
        uid = data[pos:pos + 16]
        off, size, eflags = struct.unpack_from("<QQQ", data, pos + 16)
        if uid == b"\0" * 16:
            if off == 0 or off > len(data):
                raise ValueError(f"invalid FIP terminator end 0x{off:x}")
            return serial, flags, entries, pos, off
        if size == 0:
            raise ValueError(f"zero-sized FIP entry {uid.hex()}")
        if off < 0x400 or off + size > len(data):
            raise ValueError(f"entry OOB {uid.hex()} off=0x{off:x} size=0x{size:x}")
        entries.append({
            "uuid": uid,
            "off": off,
            "size": size,
            "flags": eflags,
            "toc_pos": pos,
            "payload": data[off:off + size],
        })
        pos += 40
    raise ValueError("missing FIP terminator")


def _padding_byte(template: bytes, nt_end: int, old_end: int) -> int:
    pad = template[nt_end:old_end]
    if not pad:
        return 0x00
    unique = set(pad)
    if len(unique) == 1 and next(iter(unique)) in (0x00, 0xFF):
        return next(iter(unique))
    raise ValueError("native FIP tail padding is non-uniform; refusing to guess repack padding")


def rebuild(template: bytes, nt_payload: bytes):
    _serial, _flags, entries, term_pos, old_end = parse(template)
    nts = [e for e in entries if e["uuid"] == NT_UUID]
    if len(nts) != 1:
        raise ValueError(f"expected exactly one NT_FW entry, found {len(nts)}")
    nt = nts[0]

    # XG140 native stock donor currently has no Routerich/MTK checksum entry.
    # Do not synthesize foreign integrity metadata into a Nokia/Airoha FIP.
    if any(e["uuid"] == CHECKSUM_UUID for e in entries):
        raise ValueError(
            "native donor contains checksum metadata; this XG140 repacker only accepts checksum-free stock lineage"
        )

    # Preserve all native entries byte-for-byte by allowing only the proven
    # topology where NT_FW is the final FIP payload. Then no native entry needs
    # to move when BL33 grows.
    later = [e for e in entries if e is not nt and e["off"] >= nt["off"]]
    if later:
        ids = ",".join(e["uuid"].hex() for e in later)
        raise ValueError(f"NT_FW is not the final FIP payload; refusing to move native entries: {ids}")
    max_non_nt_end = max((e["off"] + e["size"] for e in entries if e is not nt), default=0)
    if max_non_nt_end > nt["off"]:
        raise ValueError("native entry overlaps NT_FW start")

    old_nt_end = nt["off"] + nt["size"]
    if old_nt_end > old_end:
        raise ValueError("NT_FW exceeds declared FIP end")
    pad_byte = _padding_byte(template, old_nt_end, old_end)

    new_nt_end = nt["off"] + len(nt_payload)
    final_end = align_up(new_nt_end)
    if final_end > MAX_FIP_SIZE:
        raise ValueError(
            f"FIP too large: physical end=0x{FIP_PHYS_OFF + final_end:x}, env starts at 0x{ENV_PHYS_OFF:x}"
        )

    out = bytearray(template[:nt["off"]])
    out.extend(nt_payload)
    out.extend(bytes([pad_byte]) * (final_end - len(out)))

    # Keep native NT offset/flags; change only payload size.
    struct.pack_into("<QQQ", out, nt["toc_pos"] + 16, nt["off"], len(nt_payload), nt["flags"])
    # TOC terminator stays in the native location; only declared FIP end changes.
    struct.pack_into("<QQQ", out, term_pos + 16, final_end, 0, 0)

    final = bytes(out)
    _s, _f, new_entries, _tp, new_end = parse(final)
    if new_end != len(final):
        raise ValueError("repacked terminator mismatch")
    if [e["uuid"] for e in new_entries] != [e["uuid"] for e in entries]:
        raise ValueError("FIP entry order/set changed")

    old_by = {e["uuid"]: e for e in entries}
    new_by = {e["uuid"]: e for e in new_entries}
    for uid, old in old_by.items():
        new = new_by[uid]
        if uid == NT_UUID:
            if new["off"] != old["off"] or new["flags"] != old["flags"]:
                raise ValueError("NT_FW offset/flags changed")
            if new["payload"] != nt_payload:
                raise ValueError("NT_FW payload mismatch")
            continue
        if (new["off"], new["size"], new["flags"]) != (old["off"], old["size"], old["flags"]):
            raise ValueError(f"native metadata changed for UUID {uid.hex()}")
        if new["payload"] != old["payload"]:
            raise ValueError(f"native payload changed for UUID {uid.hex()}")

    return final, {
        "entry_count": len(entries),
        "nt_off": nt["off"],
        "old_nt_size": nt["size"],
        "new_nt_size": len(nt_payload),
        "old_fip_end": old_end,
        "new_fip_end": final_end,
        "physical_end": FIP_PHYS_OFF + final_end,
        "padding_byte": pad_byte,
        "sha256": sha(final),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Repack native Nokia/Bell XG140 stock FIP by replacing only final NT_FW/BL33"
    )
    ap.add_argument("template", type=Path)
    ap.add_argument("nt", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()

    out, report = rebuild(args.template.read_bytes(), args.nt.read_bytes())
    args.output.write_bytes(out)
    print("BUILD=PASS")
    for key, value in report.items():
        shown = hex(value) if isinstance(value, int) and key != "entry_count" else value
        print(f"{key}={shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import struct
from pathlib import Path

FIP_MAGIC = 0xAA640001


def load_medve(path: Path):
    spec = importlib.util.spec_from_file_location("medve_recovery_safe_fip", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load pinned MedveFlasher parser: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rebuild(medve, source: bytes, new_bl33: bytes, raw_bl33: bytes) -> tuple[bytes, dict]:
    serial, flags, entries, _term_pos, old_end = medve.parse_fip(source)
    if len(entries) != 2:
        raise ValueError(f"expected Medve MF BL31+BL33 FIP, got {len(entries)} entries")
    if old_end != len(source):
        raise ValueError(f"source FIP terminator mismatch: {old_end} != {len(source)}")

    source_payloads = [source[o:o + s] for _uuid, o, s, _eflags in entries]
    bl31 = source_payloads[0]
    if medve.lzma_decode(new_bl33) != raw_bl33:
        raise ValueError("new MF2 BL33 compressed payload does not round-trip to u-boot.bin")

    header_size = 16 + 40 * (len(entries) + 1)
    if entries[0][1] != header_size:
        raise ValueError(f"unexpected Medve MF FIP payload start: 0x{entries[0][1]:x} != 0x{header_size:x}")

    payloads = [bl31, new_bl33]
    offsets = []
    cursor = header_size
    for payload in payloads:
        offsets.append(cursor)
        cursor += len(payload)

    out = bytearray(cursor)
    struct.pack_into("<IIQ", out, 0, FIP_MAGIC, serial, flags)
    pos = 16
    for idx, (uuid, _old_off, _old_size, eflags) in enumerate(entries):
        out[pos:pos + 16] = uuid
        struct.pack_into("<QQQ", out, pos + 16, offsets[idx], len(payloads[idx]), eflags)
        pos += 40
    out[pos:pos + 16] = b"\x00" * 16
    struct.pack_into("<QQQ", out, pos + 16, cursor, 0, 0)
    for off, payload in zip(offsets, payloads):
        out[off:off + len(payload)] = payload

    final = bytes(out)
    serial2, flags2, entries2, _term2, end2 = medve.parse_fip(final)
    if serial2 != serial or flags2 != flags:
        raise ValueError("FIP header serial/flags changed")
    if end2 != len(final):
        raise ValueError("rebuilt FIP terminator does not match file length")
    if len(entries2) != 2:
        raise ValueError("rebuilt FIP entry count changed")

    for before, after in zip(entries, entries2):
        if before[0] != after[0] or before[3] != after[3]:
            raise ValueError("FIP UUID or entry flags changed")

    out_bl31 = final[entries2[0][1]:entries2[0][1] + entries2[0][2]]
    out_bl33 = final[entries2[1][1]:entries2[1][1] + entries2[1][2]]
    if out_bl31 != bl31:
        raise ValueError("BL31 compressed bytes changed")
    if out_bl33 != new_bl33:
        raise ValueError("BL33 compressed bytes changed after packing")
    if medve.lzma_decode(out_bl33) != raw_bl33:
        raise ValueError("packed BL33 round-trip mismatch")

    report = {
        "parser_source": "MedveFlasher recovery-safe-uboot-source/patch_recovery_safe_fip.py",
        "source_sha256": medve.sha256(source),
        "output_sha256": medve.sha256(final),
        "source_size": len(source),
        "output_size": len(final),
        "entry_count": 2,
        "bl31_compressed_sha256": medve.sha256(bl31),
        "bl31_byte_exact": True,
        "source_bl33_compressed_sha256": medve.sha256(source_payloads[1]),
        "mf2_bl33_compressed_sha256": medve.sha256(new_bl33),
        "mf2_bl33_raw_sha256": medve.sha256(raw_bl33),
        "mf2_bl33_roundtrip": True,
        "serial_preserved": True,
        "flags_preserved": True,
        "uuid_flags_preserved": True,
    }
    return final, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--medve-patcher", type=Path, required=True)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--bl33", type=Path, required=True)
    ap.add_argument("--bl33-raw", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()

    medve = load_medve(args.medve_patcher.resolve())
    final, report = rebuild(
        medve,
        args.source.read_bytes(),
        args.bl33.read_bytes(),
        args.bl33_raw.read_bytes(),
    )
    args.output.write_bytes(final)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="ascii")
    for key, value in report.items():
        print(f"{key}={value}")
    print("MF2_MEDVE_FIP_REPACK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

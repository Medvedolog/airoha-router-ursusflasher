#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import lzma
import struct
from pathlib import Path

FIP_MAGIC = 0xAA640001
FIP_SERIAL = 0x12345678
SOC_FW_UUID = bytes.fromhex("47d4086d4cfe98469b952950cbbd5a00")
NT_FW_UUID = bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4")


def parse_fip(blob: bytes):
    if len(blob) < 136:
        raise ValueError("FIP too small")
    if struct.unpack_from("<I", blob, 0)[0] != FIP_MAGIC or struct.unpack_from("<I", blob, 4)[0] != FIP_SERIAL:
        raise ValueError("unexpected FIP header")
    entries = []
    pos = 16
    end_marker = None
    while pos + 40 <= len(blob):
        uuid = blob[pos : pos + 16]
        off, size, flags = struct.unpack_from("<QQQ", blob, pos + 16)
        if uuid == b"\0" * 16:
            end_marker = (off, size, flags, pos)
            break
        if not size or off + size > len(blob):
            raise ValueError(f"invalid FIP entry range off={off:#x} size={size:#x}")
        entries.append((uuid, off, size, flags, blob[off : off + size]))
        pos += 40
    if end_marker is None or end_marker[0] != len(blob):
        raise ValueError("FIP physical size does not match end marker")
    return entries, end_marker


def repack(donor: bytes, nt_fw: bytes) -> bytes:
    entries, end_marker = parse_fip(donor)
    if [entry[0] for entry in entries] != [SOC_FW_UUID, NT_FW_UUID]:
        raise ValueError("expected canonical two-entry SOC_FW + NT_FW Vanilla FIP")
    first_off = entries[0][1]
    if first_off != end_marker[3] + 40:
        raise ValueError("unexpected FIP payload start")
    if entries[1][1] != entries[0][1] + entries[0][2]:
        raise ValueError("donor FIP payloads are not contiguous")

    header = donor[:16]
    soc = entries[0][4]
    soc_flags = entries[0][3]
    nt_flags = entries[1][3]
    soc_off = first_off
    nt_off = soc_off + len(soc)
    final_size = nt_off + len(nt_fw)
    toc = bytearray()
    toc += SOC_FW_UUID + struct.pack("<QQQ", soc_off, len(soc), soc_flags)
    toc += NT_FW_UUID + struct.pack("<QQQ", nt_off, len(nt_fw), nt_flags)
    toc += b"\0" * 16 + struct.pack("<QQQ", final_size, 0, 0)
    out = header + bytes(toc) + soc + nt_fw
    if len(out) != final_size:
        raise AssertionError("repacked FIP size mismatch")
    check, _end = parse_fip(out)
    if check[0][4] != soc:
        raise AssertionError("SOC_FW changed while repacking Vanilla FIP")
    if check[1][4] != nt_fw:
        raise AssertionError("NT_FW changed while repacking Vanilla FIP")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace only NT_FW in a canonical OpenWrt Airoha Vanilla FIP")
    parser.add_argument("--donor", type=Path, required=True)
    parser.add_argument("--nt-fw", type=Path, required=True, help="current Vanilla U-Boot u-boot.lzma")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-marker", action="append", default=[])
    args = parser.parse_args()

    nt_fw = args.nt_fw.read_bytes()
    try:
        raw = lzma.decompress(nt_fw, format=lzma.FORMAT_ALONE)
    except lzma.LZMAError as exc:
        raise SystemExit(f"ERROR: NT_FW is not standard LZMA-alone: {exc}") from exc
    for marker in args.require_marker:
        if marker.encode("ascii") not in raw:
            raise SystemExit(f"ERROR: rebuilt Vanilla U-Boot lacks required marker {marker!r}")
    out = repack(args.donor.read_bytes(), nt_fw)
    args.output.write_bytes(out)
    print(f"VANILLA_FIP_REPACK=PASS raw_uboot={len(raw)} nt_fw={len(nt_fw)} fip={len(out)}")
    print("NT_FW_SHA256", hashlib.sha256(nt_fw).hexdigest())
    print("FIP_SHA256", hashlib.sha256(out).hexdigest())
    for marker in args.require_marker:
        print(f"MARKER_{marker}=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
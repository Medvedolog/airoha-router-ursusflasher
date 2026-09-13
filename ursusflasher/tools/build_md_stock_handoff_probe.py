#!/usr/bin/env python3
"""Build an OFFLINE Nokia MD tcboot handoff probe from a stock slot template.

This tool never writes a device.  It preserves the stock FIP and HDR2 bytes and
replaces only the first image at NT-FW+0x100 with a valid legacy U-Boot image.
The payload is a 4-byte AArch64 infinite branch (`b .`).  The intended hardware
acceptance signal is tcboot/bootm reaching the standalone image entry point; the
probe itself performs no I/O and no NAND operation.

This is an engineering probe, NOT a release/installer artifact.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import struct
from pathlib import Path

FIP_MAGIC = 0xAA640001
FIP_SERIAL = 0x12345678
FIP_HEADER_SIZE = 16
FIP_ENTRY_SIZE = 40
MAX_FIP_ENTRIES = 32
NOKIA_NT_FW_UUID = bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4")
HDR2_SIZE = 0x100
LEGACY_MAGIC = 0x27051956
IH_OS_U_BOOT = 17
IH_ARCH_ARM64 = 22
IH_TYPE_STANDALONE = 1
IH_COMP_NONE = 0
DEFAULT_LOAD = 0x81E00000
PROBE_PAYLOAD = struct.pack("<I", 0x14000000)  # AArch64: b .


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_nt_fw(slot: bytes) -> tuple[int, int]:
    if len(slot) < 0x1000:
        raise ValueError("slot is too small for FIP")
    magic, serial = struct.unpack_from("<II", slot, 0)
    if magic != FIP_MAGIC or serial != FIP_SERIAL:
        raise ValueError(f"invalid FIP header: magic=0x{magic:08x} serial=0x{serial:08x}")
    off = FIP_HEADER_SIZE
    for _ in range(MAX_FIP_ENTRIES):
        uuid = slot[off : off + 16]
        if uuid == b"\0" * 16:
            break
        image_off, image_size, _flags = struct.unpack_from("<QQQ", slot, off + 16)
        if uuid == NOKIA_NT_FW_UUID:
            if image_off + image_size > len(slot):
                raise ValueError("NT-FW entry exceeds slot")
            return image_off, image_size
        off += FIP_ENTRY_SIZE
    raise ValueError("Nokia NT-FW FIP entry not found")


def make_legacy_uimage(payload: bytes, load: int, entry: int, name: str) -> bytes:
    if not payload:
        raise ValueError("empty payload")
    name_bytes = name.encode("ascii", "strict")[:32].ljust(32, b"\0")
    dcrc = binascii.crc32(payload) & 0xFFFFFFFF
    fields = (LEGACY_MAGIC, 0, 0, len(payload), load, entry, dcrc,
              IH_OS_U_BOOT, IH_ARCH_ARM64, IH_TYPE_STANDALONE, IH_COMP_NONE,
              name_bytes)
    header = struct.pack(">7I4B32s", *fields)
    hcrc = binascii.crc32(header) & 0xFFFFFFFF
    fields = (LEGACY_MAGIC, hcrc, 0, len(payload), load, entry, dcrc,
              IH_OS_U_BOOT, IH_ARCH_ARM64, IH_TYPE_STANDALONE, IH_COMP_NONE,
              name_bytes)
    return struct.pack(">7I4B32s", *fields) + payload


def build_probe(template: bytes, load: int = DEFAULT_LOAD) -> tuple[bytes, dict]:
    nt_off, nt_size = find_nt_fw(template)
    if template[nt_off : nt_off + 4] != b"HDR2":
        raise ValueError("MD NT-FW does not begin with HDR2")
    if nt_size <= HDR2_SIZE + 64:
        raise ValueError("NT-FW span is too small")

    image_off = nt_off + HDR2_SIZE
    probe = make_legacy_uimage(PROBE_PAYLOAD, load, load, "UrsusBoot MD HANDOFF PROBE")
    if len(probe) != 68:
        raise AssertionError("unexpected probe size")

    out = bytearray(template)
    old = bytes(out[image_off : image_off + len(probe)])
    out[image_off : image_off + len(probe)] = probe

    # Safety invariant for this experiment: FIP + HDR2 stay byte-identical.
    if out[:image_off] != template[:image_off]:
        raise AssertionError("outer FIP/HDR2 changed")
    if out[image_off + len(probe) :] != template[image_off + len(probe) :]:
        raise AssertionError("bytes outside probe span changed")

    hcrc = struct.unpack_from(">I", probe, 4)[0]
    dcrc = struct.unpack_from(">I", probe, 24)[0]
    manifest = {
        "artifact": "MD_TCBOOT_HANDOFF_PROBE",
        "release_artifact": False,
        "device_writer_enabled": False,
        "slot_size": len(template),
        "nt_fw_offset": nt_off,
        "nt_fw_size": nt_size,
        "image_offset": image_off,
        "changed_offset": image_off,
        "changed_size": len(probe),
        "load_address": load,
        "entry_address": load,
        "legacy_header_crc32": f"{hcrc:08x}",
        "payload_crc32": f"{dcrc:08x}",
        "template_sha256": sha256(template),
        "old_span_sha256": sha256(old),
        "new_span_sha256": sha256(probe),
        "output_sha256": sha256(bytes(out)),
        "expected_behavior": "tcboot bootm transfers control to standalone image, then probe loops forever",
        "nand_writes_from_probe": 0,
    }
    return bytes(out), manifest


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline Nokia MD stock-slot tcboot handoff probe builder")
    ap.add_argument("template", type=Path, help="raw stock nsb_master/nsb_slave slot image")
    ap.add_argument("output", type=Path)
    ap.add_argument("--manifest", type=Path)
    ap.add_argument("--load", type=lambda s: int(s, 0), default=DEFAULT_LOAD)
    args = ap.parse_args()

    template = args.template.read_bytes()
    output, manifest = build_probe(template, args.load)
    args.output.write_bytes(output)
    manifest_path = args.manifest or args.output.with_suffix(args.output.suffix + ".json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

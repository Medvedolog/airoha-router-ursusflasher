#!/usr/bin/env python3
"""Build an OFFLINE MD stock-compatible TRANSITION slot candidate.

The builder takes a raw stock `nsb_*` slot from the same board family and a
prebuilt legacy uImage containing UrsusBoot TRANSITION.  It preserves the
stock FIP TOC and HDR2 byte-for-byte and replaces only the image bytes starting
at NT-FW+0x100.  Bytes after the uImage remain from the stock template.

No device access or writer exists in this tool.  The resulting image is an
engineering candidate until tcboot hardware acceptance proves the legacy-image
path on Nokia XG-040G-MD.
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
MD_TEXT_BASE = 0x81E00000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_nt_fw(slot: bytes) -> tuple[int, int]:
    if len(slot) < 0x1000:
        raise ValueError("slot is too small for FIP")
    magic, serial = struct.unpack_from("<II", slot, 0)
    if magic != FIP_MAGIC or serial != FIP_SERIAL:
        raise ValueError(f"invalid FIP header: magic=0x{magic:08x} serial=0x{serial:08x}")
    pos = FIP_HEADER_SIZE
    for _ in range(MAX_FIP_ENTRIES):
        uuid = slot[pos : pos + 16]
        if uuid == b"\0" * 16:
            break
        image_off, image_size, _flags = struct.unpack_from("<QQQ", slot, pos + 16)
        if uuid == NOKIA_NT_FW_UUID:
            if image_off + image_size > len(slot):
                raise ValueError("NT-FW entry exceeds slot")
            return image_off, image_size
        pos += FIP_ENTRY_SIZE
    raise ValueError("Nokia NT-FW FIP entry not found")


def validate_uimage(data: bytes) -> dict:
    if len(data) < 64:
        raise ValueError("legacy uImage is shorter than its 64-byte header")
    magic,hcrc,ts,size,load,entry,dcrc,os_id,arch,img_type,comp,name = struct.unpack(
        ">7I4B32s", data[:64]
    )
    if magic != LEGACY_MAGIC:
        raise ValueError(f"not a legacy uImage: magic=0x{magic:08x}")
    if size != len(data) - 64:
        raise ValueError(f"uImage payload size mismatch: header={size} actual={len(data)-64}")
    header = bytearray(data[:64])
    struct.pack_into(">I", header, 4, 0)
    calc_hcrc = binascii.crc32(header) & 0xFFFFFFFF
    calc_dcrc = binascii.crc32(data[64:]) & 0xFFFFFFFF
    if calc_hcrc != hcrc:
        raise ValueError(f"uImage header CRC mismatch: stored={hcrc:08x} calc={calc_hcrc:08x}")
    if calc_dcrc != dcrc:
        raise ValueError(f"uImage data CRC mismatch: stored={dcrc:08x} calc={calc_dcrc:08x}")
    if (os_id, arch, img_type, comp) != (IH_OS_U_BOOT, IH_ARCH_ARM64, IH_TYPE_STANDALONE, IH_COMP_NONE):
        raise ValueError(
            "uImage contract mismatch: expected OS=u-boot arch=arm64 type=standalone compression=none"
        )
    if load != MD_TEXT_BASE or entry != MD_TEXT_BASE:
        raise ValueError(
            f"MD TRANSITION load/entry must both equal TEXT_BASE 0x{MD_TEXT_BASE:x}; "
            f"got load=0x{load:x} entry=0x{entry:x}"
        )
    return {
        "payload_size": size,
        "load_address": load,
        "entry_address": entry,
        "header_crc32": f"{hcrc:08x}",
        "data_crc32": f"{dcrc:08x}",
        "name": name.split(b"\0", 1)[0].decode("ascii", "replace"),
    }


def build_slot(template: bytes, uimage: bytes) -> tuple[bytes, dict]:
    ui = validate_uimage(uimage)
    nt_off, nt_size = find_nt_fw(template)
    if template[nt_off : nt_off + 4] != b"HDR2":
        raise ValueError("MD NT-FW does not begin with HDR2")
    image_off = nt_off + HDR2_SIZE
    image_capacity = nt_size - HDR2_SIZE
    if len(uimage) > image_capacity:
        raise ValueError(f"uImage 0x{len(uimage):x} exceeds NT-FW image capacity 0x{image_capacity:x}")

    out = bytearray(template)
    old_span = bytes(out[image_off : image_off + len(uimage)])
    out[image_off : image_off + len(uimage)] = uimage

    # Current Phase-A experiment intentionally preserves the vendor outer
    # wrapper and all bytes outside the new image span.
    if out[:image_off] != template[:image_off]:
        raise AssertionError("FIP/HDR2 changed unexpectedly")
    if out[image_off + len(uimage) :] != template[image_off + len(uimage) :]:
        raise AssertionError("bytes after transition uImage changed unexpectedly")

    manifest = {
        "artifact": "URSUSBOOT_MD_TRANSITION_SLOT_CANDIDATE",
        "board": "Nokia XG-040G-MD",
        "soc": "AN7581",
        "mode": "TRANSITION",
        "persistence_target": "NONE",
        "final_target": "OFFICIAL_OPENWRT",
        "hardware_acceptance": "PENDING",
        "release_artifact": False,
        "device_writer_enabled": False,
        "slot_size": len(template),
        "nt_fw_offset": nt_off,
        "nt_fw_size": nt_size,
        "image_offset": image_off,
        "image_capacity": image_capacity,
        "changed_offset": image_off,
        "changed_size": len(uimage),
        "outer_fip_hdr2_preserved": True,
        "stock_tail_preserved": True,
        "template_sha256": sha256(template),
        "uimage_sha256": sha256(uimage),
        "replaced_span_sha256": sha256(old_span),
        "output_sha256": sha256(bytes(out)),
        "uimage": ui,
        "expected_tcboot_path": "FIP -> HDR2 -> IH_MAGIC -> bootm standalone -> 0x81e00000",
    }
    return bytes(out), manifest


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline Nokia MD UrsusBoot TRANSITION stock-slot builder")
    ap.add_argument("template", type=Path, help="raw stock MD nsb_master/nsb_slave slot")
    ap.add_argument("uimage", type=Path, help="UrsusBoot TRANSITION legacy uImage")
    ap.add_argument("output", type=Path)
    ap.add_argument("--manifest", type=Path)
    args = ap.parse_args()

    template = args.template.read_bytes()
    uimage = args.uimage.read_bytes()
    output, manifest = build_slot(template, uimage)
    args.output.write_bytes(output)
    mpath = args.manifest or args.output.with_suffix(args.output.suffix + ".json")
    mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

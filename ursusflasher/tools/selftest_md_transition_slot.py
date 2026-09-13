#!/usr/bin/env python3
import binascii
import importlib.util
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("build_md_transition_slot", HERE / "build_md_transition_slot.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)

# Synthetic stock slot with a Nokia NT-FW entry and HDR2 wrapper.
slot = bytearray(b"\xff" * 0x10000)
struct.pack_into("<IIQ", slot, 0, mod.FIP_MAGIC, mod.FIP_SERIAL, 0)
slot[0x10:0x20] = mod.NOKIA_NT_FW_UUID
struct.pack_into("<QQQ", slot, 0x20, 0x2000, 0x8000, 0)
slot[0x38:0x48] = b"\0" * 16
slot[0x2000:0x2004] = b"HDR2"

payload = b"TRANSITION-TEST-PAYLOAD"
name = b"UrsusBoot MD TRANSITION1".ljust(32, b"\0")
dcrc = binascii.crc32(payload) & 0xffffffff
header = struct.pack(">7I4B32s", mod.LEGACY_MAGIC, 0, 0, len(payload),
                     mod.MD_TEXT_BASE, mod.MD_TEXT_BASE, dcrc,
                     mod.IH_OS_U_BOOT, mod.IH_ARCH_ARM64,
                     mod.IH_TYPE_STANDALONE, mod.IH_COMP_NONE, name)
hcrc = binascii.crc32(header) & 0xffffffff
uimage = struct.pack(">7I4B32s", mod.LEGACY_MAGIC, hcrc, 0, len(payload),
                     mod.MD_TEXT_BASE, mod.MD_TEXT_BASE, dcrc,
                     mod.IH_OS_U_BOOT, mod.IH_ARCH_ARM64,
                     mod.IH_TYPE_STANDALONE, mod.IH_COMP_NONE, name) + payload

before = bytes(slot)
out, manifest = mod.build_slot(before, uimage)
assert len(out) == len(before)
assert manifest["hardware_acceptance"] == "PENDING"
assert manifest["device_writer_enabled"] is False
assert manifest["outer_fip_hdr2_preserved"] is True
assert manifest["image_offset"] == 0x2100
assert out[:0x2100] == before[:0x2100]
assert out[0x2100:0x2100 + len(uimage)] == uimage
assert out[0x2100 + len(uimage):] == before[0x2100 + len(uimage):]
assert manifest["uimage"]["load_address"] == mod.MD_TEXT_BASE
assert manifest["uimage"]["entry_address"] == mod.MD_TEXT_BASE

print("selftest_md_transition_slot: PASS")

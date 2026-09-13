#!/usr/bin/env python3
import importlib.util
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("build_md_stock_handoff_probe", HERE / "build_md_stock_handoff_probe.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)

# Minimal synthetic stock-slot shape: FIP header, one Nokia NT-FW entry,
# HDR2 at NT-FW start and erased bytes elsewhere.
slot = bytearray(b"\xff" * 0x8000)
struct.pack_into("<IIQ", slot, 0, mod.FIP_MAGIC, mod.FIP_SERIAL, 0)
slot[0x10:0x20] = mod.NOKIA_NT_FW_UUID
struct.pack_into("<QQQ", slot, 0x20, 0x2000, 0x5000, 0)
slot[0x38:0x48] = b"\0" * 16
slot[0x2000:0x2004] = b"HDR2"

before = bytes(slot)
out, manifest = mod.build_probe(before)
assert len(out) == len(before)
assert manifest["nt_fw_offset"] == 0x2000
assert manifest["image_offset"] == 0x2100
assert manifest["changed_size"] == 68
assert manifest["device_writer_enabled"] is False
assert manifest["release_artifact"] is False
assert out[:0x2100] == before[:0x2100]
assert out[0x2100 + 68:] == before[0x2100 + 68:]
assert out[0x2100:0x2104] == struct.pack(">I", mod.LEGACY_MAGIC)

# Validate legacy header and both CRCs.
probe = out[0x2100:0x2100 + 68]
fields = struct.unpack(">7I4B32s", probe[:64])
assert fields[0] == mod.LEGACY_MAGIC
assert fields[3] == 4
assert fields[4] == mod.DEFAULT_LOAD
assert fields[5] == mod.DEFAULT_LOAD
assert fields[7] == mod.IH_OS_U_BOOT
assert fields[8] == mod.IH_ARCH_ARM64
assert fields[9] == mod.IH_TYPE_STANDALONE
assert probe[64:] == mod.PROBE_PAYLOAD

import binascii
hdr = bytearray(probe[:64])
stored_hcrc = struct.unpack_from(">I", hdr, 4)[0]
struct.pack_into(">I", hdr, 4, 0)
assert stored_hcrc == (binascii.crc32(hdr) & 0xffffffff)
assert fields[6] == (binascii.crc32(probe[64:]) & 0xffffffff)

print("selftest_md_stock_handoff_probe: PASS")

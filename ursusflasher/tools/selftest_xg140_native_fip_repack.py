#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPACK = ROOT / "ursusflasher" / "tools" / "repack_xg140_native_fip.py"
spec = importlib.util.spec_from_file_location("xg140_repack", REPACK)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Synthetic form of the native Nokia bootloader lineage observed by the project:
# 9 TOC entries, NT_FW last, no Routerich/MTK checksum UUID.
uids = [
    bytes.fromhex("5ff9ec0b4d223e4da544c39d81c73f0a"),
    bytes.fromhex("d6e269ea5d63e4118d8c9fbabe9956a5"),
    bytes.fromhex("827ee890f860e411a1b4777a21b4f94c"),
    bytes.fromhex("8ab8beccf960e4119ad0eb4822d8dcf8"),
    bytes.fromhex("8ad5832afb60e4118aafdf30bbc49859"),
    bytes.fromhex("e2b20c205e63e4119ce8abccf92bb666"),
    bytes.fromhex("8ec4c1f35d63e411a7a987ee40b23fa7"),
    bytes.fromhex("47d4086d4cfe98469b952950cbbd5a00"),
    mod.NT_UUID,
]
offsets = [0x400, 0x1C800, 0x1D000, 0x1DC00, 0x1E400, 0x1EC00, 0x1F400, 0x1FC00, 0x29C00]
sizes = [0x1C100, 0x6CF, 0xA0E, 0x7DA, 0x7EA, 0x672, 0x682, 0x9D1D, 0x224DC]
old_end = 0x4C400

template = bytearray(old_end)
struct.pack_into("<IIQ", template, 0, mod.FIP_MAGIC, 0x12345678, 0)
pos = 16
for i, (uid, off, size) in enumerate(zip(uids, offsets, sizes)):
    struct.pack_into("<16sQQQ", template, pos, uid, off, size, 0)
    pos += 40
    template[off:off + size] = bytes([0x30 + i]) * size
struct.pack_into("<16sQQQ", template, pos, b"\0" * 16, old_end, 0, 0)

new_nt = b"U" * 290276
out, report = mod.rebuild(bytes(template), new_nt)

_, _, old_entries, _, _ = mod.parse(bytes(template))
_, _, new_entries, _, new_end = mod.parse(out)
assert len(old_entries) == 9 == len(new_entries)
assert mod.CHECKSUM_UUID not in {e["uuid"] for e in new_entries}
assert [e["uuid"] for e in old_entries] == [e["uuid"] for e in new_entries]
assert new_end == len(out) == 0x70C00
assert report["physical_end"] == 0x71400
assert report["physical_end"] < mod.ENV_PHYS_OFF

for old, new in zip(old_entries, new_entries):
    if old["uuid"] == mod.NT_UUID:
        assert new["off"] == old["off"]
        assert new["flags"] == old["flags"]
        assert new["payload"] == new_nt
        assert new["size"] == len(new_nt)
    else:
        assert (new["off"], new["size"], new["flags"]) == (old["off"], old["size"], old["flags"])
        assert new["payload"] == old["payload"]

print("XG140_NATIVE_FIP_REPACK_SELFTEST=PASS")

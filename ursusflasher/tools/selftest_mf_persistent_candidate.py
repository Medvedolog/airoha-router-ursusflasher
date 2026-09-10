#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import lzma
import random
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
sys.path.insert(0, str(SRC))

import mf_persistent as mf


def align_up(value: int, alignment: int = 0x400) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def deterministic_bytes(size: int, seed: int) -> bytes:
    rnd = random.Random(seed)
    return bytes(rnd.randrange(0, 256) for _ in range(size))


def lzma_payload(prefix: bytes, body_size: int, seed: int) -> bytes:
    raw = prefix + deterministic_bytes(body_size, seed)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


def build_synthetic_stock() -> bytes:
    boot = bytearray(b"\x00" * mf.BOOT_AREA_SIZE)
    boot[:mf.FIP_PHYS_OFF] = (b"MF-STOCK-PREFIX-" * 256)[:mf.FIP_PHYS_OFF]
    boot[mf.STOCK_ENV_OFF:] = (b"MF-STOCK-ENV-" * 2048)[:mf.STOCK_ENV_SIZE]

    bl31_uuid = bytes.fromhex("47d4086d4cfe98469b952950cbbd5a00")
    uuids = [
        bytes.fromhex("5ff9ec0b4d223e4da544c39d81c73f0a"),
        bytes.fromhex("d6e269ea5d63e4118d8c9fbabe9956a5"),
        bytes.fromhex("827ee890f860e411a1b4777a21b4f94c"),
        bytes.fromhex("8ab8beccf960e4119ad0eb4822d8dcf8"),
        bytes.fromhex("8ad5832afb60e4118aafdf30bbc49859"),
        bytes.fromhex("e2b20c205e63e4119ce8abccf92bb666"),
        bytes.fromhex("8ec4c1f35d63e411a7a987ee40b23fa7"),
        bl31_uuid,
        mf.NT_FW_UUID,
    ]
    payloads = [
        deterministic_bytes(0x3100 + i * 0x31, 100 + i) for i in range(7)
    ]
    payloads.append(lzma_payload(b"BL31-NATIVE\x00Airoha AN7583\x00", 18000, 208))
    payloads.append(lzma_payload(b"STOCK-U-BOOT\x00Airoha AN7583\x00", 42000, 209))

    fip = memoryview(boot)[mf.FIP_PHYS_OFF:mf.STOCK_ENV_OFF]
    struct.pack_into("<IIQ", fip, 0, mf.FIP_MAGIC, 0x12345678, 0)
    toc_pos = 16
    payload_off = align_up(16 + 40 * (len(uuids) + 1))
    offsets: list[int] = []
    for uuid, payload in zip(uuids, payloads):
        offsets.append(payload_off)
        fip[toc_pos:toc_pos + 16] = uuid
        struct.pack_into("<QQQ", fip, toc_pos + 16, payload_off, len(payload), 0)
        fip[payload_off:payload_off + len(payload)] = payload
        payload_off = align_up(payload_off + len(payload))
        toc_pos += 40
    fip[toc_pos:toc_pos + 16] = b"\x00" * 16
    struct.pack_into("<QQQ", fip, toc_pos + 16, payload_off, 0, 0)
    return bytes(boot)


def main() -> int:
    source = build_synthetic_stock()
    before = mf.parse_fip_from_boot_area(source)
    source_nt = next(e for e in before.entries if e.uuid == mf.NT_FW_UUID)

    # Deliberately larger than the synthetic stock BL33 to exercise in-place
    # growth while all native early-stage entries remain fixed.
    candidate_lzma = lzma_payload(
        b"UrsusBoot 0.1.0-TEST61\x00Nokia XG-040G-MF\x00Airoha AN7583\x00",
        150000,
        999,
    )
    candidate, report = mf.build_stock_derived_candidate(source, candidate_lzma)
    after = mf.parse_fip_from_boot_area(candidate)
    candidate_nt = next(e for e in after.entries if e.uuid == mf.NT_FW_UUID)

    assert len(candidate) == mf.BOOT_AREA_SIZE
    assert candidate[:mf.FIP_PHYS_OFF] == source[:mf.FIP_PHYS_OFF]
    assert candidate[mf.STOCK_ENV_OFF:] == source[mf.STOCK_ENV_OFF:]
    assert candidate_nt.offset == source_nt.offset
    assert candidate_nt.size == len(candidate_lzma)
    assert candidate_nt.size > source_nt.size
    assert after.declared_end > before.declared_end
    assert report.fip_entries == 9
    assert report.prefix_byte_exact
    assert report.environment_byte_exact
    assert report.non_bl33_entries_byte_exact
    assert report.native_bl31_preserved
    assert report.candidate_identity == "URSUSBOOT_MF_AN7583"
    assert report.source_sha256 == hashlib.sha256(source).hexdigest()
    assert report.candidate_sha256 == hashlib.sha256(candidate).hexdigest()

    print(
        "MF_PERSISTENT_CANDIDATE_SELFTEST=PASS "
        f"source_nt_fw={source_nt.size} candidate_nt_fw={candidate_nt.size} "
        f"source_end=0x{before.declared_end:x} candidate_end=0x{after.declared_end:x}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

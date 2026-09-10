#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import math
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

FIP_MAGIC = 0xAA640001
BOOT_AREA_SIZE = 0x80000
FIP_PHYS_OFF = 0x800
STOCK_ENV_OFF = 0x7C000
STOCK_ENV_SIZE = 0x4000
FIP_MAX_LEN = STOCK_ENV_OFF - FIP_PHYS_OFF

# TF-A NT_FW_CONFIG? No: this is the raw UUID byte sequence present in the
# Airoha FIP TOC for NT_FW / BL33. Keep byte order exactly as stored on flash.
NT_FW_UUID = bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4")
ZERO_UUID = b"\x00" * 16


@dataclass(frozen=True)
class FipEntry:
    uuid_hex: str
    offset: int
    size: int
    flags: int
    toc_pos: int

    @property
    def uuid(self) -> bytes:
        return bytes.fromhex(self.uuid_hex)

    @property
    def end(self) -> int:
        return self.offset + self.size


@dataclass(frozen=True)
class FipLayout:
    serial: int
    flags: int
    entries: tuple[FipEntry, ...]
    terminator_pos: int
    declared_end: int
    alignment: int

    @property
    def toc_end(self) -> int:
        return self.terminator_pos + 40


@dataclass(frozen=True)
class CandidateReport:
    source_sha256: str
    candidate_sha256: str
    source_size: int
    candidate_size: int
    fip_offset: int
    fip_entries: int
    fip_toc_end: int
    source_fip_end: int
    candidate_fip_end: int
    fip_alignment: int
    nt_fw_offset: int
    source_nt_fw_size: int
    candidate_nt_fw_size: int
    candidate_bl33_raw_size: int
    source_serial: int
    source_flags: int
    prefix_byte_exact: bool
    environment_byte_exact: bool
    non_bl33_entries_byte_exact: bool
    native_bl31_preserved: bool
    candidate_identity: str


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _align_up(value: int, alignment: int) -> int:
    if alignment <= 0 or alignment & (alignment - 1):
        raise ValueError(f"invalid FIP alignment 0x{alignment:x}")
    return (value + alignment - 1) & ~(alignment - 1)


def _infer_alignment(entries: list[FipEntry], declared_end: int) -> int:
    alignment = 0
    for value in [e.offset for e in entries] + [declared_end]:
        if value:
            alignment = math.gcd(alignment, value)
    if alignment < 16 or alignment > 0x10000 or alignment & (alignment - 1):
        raise ValueError(f"cannot infer sane FIP alignment: 0x{alignment:x}")
    return alignment


def parse_fip_from_boot_area(boot_area: bytes) -> FipLayout:
    if len(boot_area) != BOOT_AREA_SIZE:
        raise ValueError(
            f"MF stock boot-area must be exactly 0x{BOOT_AREA_SIZE:x} bytes, got 0x{len(boot_area):x}"
        )

    fip = boot_area[FIP_PHYS_OFF:STOCK_ENV_OFF]
    if len(fip) < 56:
        raise ValueError("FIP area is too small")

    magic, serial, flags = struct.unpack_from("<IIQ", fip, 0)
    if magic != FIP_MAGIC:
        raise ValueError(f"unexpected FIP magic 0x{magic:08x} at physical 0x{FIP_PHYS_OFF:x}")

    entries: list[FipEntry] = []
    pos = 16
    terminator_pos = -1
    declared_end = 0
    while pos + 40 <= len(fip):
        uuid = fip[pos:pos + 16]
        offset, size, entry_flags = struct.unpack_from("<QQQ", fip, pos + 16)
        if uuid == ZERO_UUID:
            terminator_pos = pos
            declared_end = offset
            if size != 0 or entry_flags != 0:
                raise ValueError("FIP terminator has non-zero size/flags")
            break
        entries.append(
            FipEntry(
                uuid_hex=uuid.hex(),
                offset=offset,
                size=size,
                flags=entry_flags,
                toc_pos=pos,
            )
        )
        if len(entries) > 64:
            raise ValueError("unreasonable FIP entry count")
        pos += 40

    if terminator_pos < 0:
        raise ValueError("FIP terminator not found")
    if not entries:
        raise ValueError("FIP contains no payload entries")

    toc_end = terminator_pos + 40
    if declared_end < toc_end or declared_end > FIP_MAX_LEN:
        raise ValueError(
            f"FIP declared end 0x{declared_end:x} outside allowed range 0x{toc_end:x}..0x{FIP_MAX_LEN:x}"
        )

    ordered = sorted(entries, key=lambda e: e.offset)
    previous_end = toc_end
    for entry in ordered:
        if entry.offset < toc_end:
            raise ValueError(f"FIP payload overlaps TOC: {entry.uuid_hex}")
        if entry.offset < previous_end:
            raise ValueError(f"FIP payload overlap at 0x{entry.offset:x}: {entry.uuid_hex}")
        if entry.end > declared_end:
            raise ValueError(f"FIP payload exceeds declared end: {entry.uuid_hex}")
        previous_end = entry.end

    nt = [e for e in entries if e.uuid == NT_FW_UUID]
    if len(nt) != 1:
        raise ValueError(f"expected exactly one NT_FW/BL33 entry, found {len(nt)}")

    # The stock-derived strategy deliberately does not shift native early-stage
    # payloads. Growing BL33 is safe only while NT_FW is the final payload.
    nt_entry = nt[0]
    if nt_entry is not max(entries, key=lambda e: e.offset):
        raise ValueError("NT_FW/BL33 is not the final FIP payload; in-place growth is not applicable")

    alignment = _infer_alignment(entries, declared_end)
    return FipLayout(
        serial=serial,
        flags=flags,
        entries=tuple(entries),
        terminator_pos=terminator_pos,
        declared_end=declared_end,
        alignment=alignment,
    )


def _decode_candidate_bl33(payload: bytes) -> bytes:
    if len(payload) < 13 or payload[0] != 0x5D:
        raise ValueError("candidate BL33 is not an Airoha LZMA-Alone payload")
    try:
        raw = lzma.decompress(payload, format=lzma.FORMAT_ALONE)
    except lzma.LZMAError as exc:
        raise ValueError(f"candidate BL33 LZMA decode failed: {exc}") from exc
    if not raw:
        raise ValueError("candidate BL33 decompressed to an empty image")
    return raw


def _validate_mf_ursusboot_identity(raw: bytes) -> str:
    # Normal persistent installation is strict about the candidate being an MF
    # UrsusBoot build. Raw/debrick recovery has a separate permissive path.
    if b"UrsusBoot" not in raw:
        raise ValueError("candidate BL33 does not contain UrsusBoot identity")
    board_ok = b"Nokia XG-040G-MF" in raw or b"nokia,xg-040g-mf" in raw
    soc_ok = b"AN7583" in raw or b"an7583" in raw
    if not board_ok or not soc_ok:
        raise ValueError("candidate BL33 is not identified as Nokia XG-040G-MF / AN7583")
    return "URSUSBOOT_MF_AN7583"


def _entry_payload(boot_area: bytes, entry: FipEntry) -> bytes:
    start = FIP_PHYS_OFF + entry.offset
    return boot_area[start:start + entry.size]


def _find_native_bl31(layout: FipLayout) -> FipEntry | None:
    # TF-A BL31 UUID byte sequence as stored by fiptool/Airoha. This is used for
    # an explicit preservation report, not as a requirement for parsing stock.
    bl31_uuid = bytes.fromhex("47d4086d4cfe98469b952950cbbd5a00")
    found = [e for e in layout.entries if e.uuid == bl31_uuid]
    return found[0] if len(found) == 1 else None


def build_stock_derived_candidate(boot_area: bytes, candidate_bl33_lzma: bytes) -> tuple[bytes, CandidateReport]:
    layout = parse_fip_from_boot_area(boot_area)
    raw_bl33 = _decode_candidate_bl33(candidate_bl33_lzma)
    identity = _validate_mf_ursusboot_identity(raw_bl33)

    nt = next(e for e in layout.entries if e.uuid == NT_FW_UUID)
    new_payload_end = nt.offset + len(candidate_bl33_lzma)
    new_declared_end = _align_up(new_payload_end, layout.alignment)
    if new_declared_end > FIP_MAX_LEN:
        raise ValueError(
            f"candidate BL33 does not fit before stock ENV: FIP end 0x{new_declared_end:x}, max 0x{FIP_MAX_LEN:x}"
        )

    out = bytearray(boot_area)
    payload_start = FIP_PHYS_OFF + nt.offset
    payload_end = payload_start + len(candidate_bl33_lzma)

    # Keep the source image as the candidate base. Only the final NT_FW payload
    # and its unavoidable TOC/end metadata are modified. No native early-stage
    # FIP payload is shifted or repacked.
    out[payload_start:payload_end] = candidate_bl33_lzma

    # If a future candidate is smaller than stock BL33, remove stale compressed
    # bytes using the padding byte already used by this stock FIP. This does not
    # affect any declared payload entry.
    if len(candidate_bl33_lzma) < nt.size:
        pad_region = boot_area[
            FIP_PHYS_OFF + nt.end:
            FIP_PHYS_OFF + layout.declared_end
        ]
        pad_byte = pad_region[0] if pad_region and all(x == pad_region[0] for x in pad_region) else 0x00
        out[payload_end:FIP_PHYS_OFF + nt.end] = bytes([pad_byte]) * (nt.size - len(candidate_bl33_lzma))

    # FIP TOC: UUID[16], offset[8], size[8], flags[8]. Offset/UUID/flags stay
    # native; only NT_FW size changes. The null terminator's offset records the
    # aligned physical end of this FIP.
    struct.pack_into("<Q", out, FIP_PHYS_OFF + nt.toc_pos + 24, len(candidate_bl33_lzma))
    struct.pack_into("<Q", out, FIP_PHYS_OFF + layout.terminator_pos + 16, new_declared_end)

    candidate = bytes(out)
    new_layout = parse_fip_from_boot_area(candidate)
    new_nt = next(e for e in new_layout.entries if e.uuid == NT_FW_UUID)

    if new_nt.offset != nt.offset or new_nt.flags != nt.flags or new_nt.uuid_hex != nt.uuid_hex:
        raise AssertionError("NT_FW metadata changed beyond size")
    if new_nt.size != len(candidate_bl33_lzma):
        raise AssertionError("candidate NT_FW size was not recorded correctly")
    if new_layout.serial != layout.serial or new_layout.flags != layout.flags:
        raise AssertionError("FIP header serial/flags changed")

    non_bl33_exact = True
    for old_entry, new_entry in zip(layout.entries, new_layout.entries):
        if old_entry.uuid == NT_FW_UUID:
            continue
        if old_entry != new_entry:
            non_bl33_exact = False
            break
        if _entry_payload(boot_area, old_entry) != _entry_payload(candidate, new_entry):
            non_bl33_exact = False
            break
    if not non_bl33_exact:
        raise AssertionError("non-BL33 FIP entry or payload changed")

    prefix_exact = candidate[:FIP_PHYS_OFF] == boot_area[:FIP_PHYS_OFF]
    env_exact = candidate[STOCK_ENV_OFF:] == boot_area[STOCK_ENV_OFF:]
    if not prefix_exact or not env_exact:
        raise AssertionError("protected stock prefix/environment changed")

    bl31 = _find_native_bl31(layout)
    native_bl31_preserved = True
    if bl31 is not None:
        new_bl31 = next((e for e in new_layout.entries if e.uuid_hex == bl31.uuid_hex), None)
        native_bl31_preserved = bool(
            new_bl31
            and new_bl31 == bl31
            and _entry_payload(candidate, new_bl31) == _entry_payload(boot_area, bl31)
        )
    if not native_bl31_preserved:
        raise AssertionError("native BL31 changed")

    report = CandidateReport(
        source_sha256=sha256(boot_area),
        candidate_sha256=sha256(candidate),
        source_size=len(boot_area),
        candidate_size=len(candidate),
        fip_offset=FIP_PHYS_OFF,
        fip_entries=len(layout.entries),
        fip_toc_end=layout.toc_end,
        source_fip_end=layout.declared_end,
        candidate_fip_end=new_layout.declared_end,
        fip_alignment=layout.alignment,
        nt_fw_offset=nt.offset,
        source_nt_fw_size=nt.size,
        candidate_nt_fw_size=new_nt.size,
        candidate_bl33_raw_size=len(raw_bl33),
        source_serial=layout.serial,
        source_flags=layout.flags,
        prefix_byte_exact=prefix_exact,
        environment_byte_exact=env_exact,
        non_bl33_entries_byte_exact=non_bl33_exact,
        native_bl31_preserved=native_bl31_preserved,
        candidate_identity=identity,
    )
    return candidate, report


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build a Nokia XG-040G-MF stock-derived persistent UrsusBoot boot-area candidate"
    )
    ap.add_argument("--boot-area", required=True, type=Path, help="actual 0x80000 boot-area/mtd0 read from this device")
    ap.add_argument("--bl33-lzma", required=True, type=Path, help="MF UrsusBoot BL33 in Airoha LZMA-Alone form")
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    source = args.boot_area.read_bytes()
    bl33 = args.bl33_lzma.read_bytes()
    candidate, report = build_stock_derived_candidate(source, bl33)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(candidate)
    report_json = json.dumps(asdict(report), indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report_json, encoding="ascii")

    print("MF_STOCK_DERIVED_CANDIDATE=PASS")
    for key, value in asdict(report).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

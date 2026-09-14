from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"
if TOOLS.is_dir():
    sys.path.insert(0, str(TOOLS))
else:
    sys.path.insert(0, str(HERE / "tools"))

import repack_xg140_native_fip as repack

FAMILY = "xg140"
MODEL = "Bell/Nokia XG-140G-MD"
SOC = "Airoha AN7581DT"
BOOT_AREA_SIZE = 0x80000
FIP_OFF = 0x800
ENV_OFF = 0x7C000
EXPECTED_PROFILE = "xg140-md"
EXPECTED_ROLE = "persistent"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def project_root() -> Path:
    repo = HERE.parent.parent
    return repo if (repo / "payloads").is_dir() else HERE.parent


def payload_dir() -> Path:
    root = project_root()
    if (root / "payloads").is_dir():
        return root / "payloads" / FAMILY / "ursusboot"
    return root / "data" / "payloads" / FAMILY / "ursusboot"


def require_bl33() -> tuple[Path, dict]:
    directory = payload_dir()
    bl33 = directory / "u-boot.persistent.lzma"
    info_path = directory / "BUILD_INFO.json"
    if not bl33.is_file():
        raise RuntimeError(f"XG140 persistent BL33 payload missing: {bl33}")
    if not info_path.is_file():
        raise RuntimeError(f"XG140 payload metadata missing: {info_path}")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    if info.get("board_profile") != EXPECTED_PROFILE:
        raise RuntimeError(f"XG140 payload board_profile mismatch: {info.get('board_profile')!r}")
    if info.get("runtime_role") != EXPECTED_ROLE:
        raise RuntimeError(f"XG140 payload runtime_role mismatch: {info.get('runtime_role')!r}")
    raw = bl33.read_bytes()
    got = sha256_bytes(raw)
    if int(info.get("size") or -1) != len(raw) or str(info.get("sha256") or "").lower() != got:
        raise RuntimeError("XG140 persistent BL33 size/SHA256 mismatch against BUILD_INFO.json")
    if len(raw) < 13:
        raise RuntimeError("XG140 persistent BL33 is too small")
    return bl33, info


def extract_native_fip(live: bytes) -> tuple[bytes, dict]:
    if len(live) != BOOT_AREA_SIZE:
        raise RuntimeError(f"XG140 live mtd0 size {len(live):#x}, expected {BOOT_AREA_SIZE:#x}")
    if live[FIP_OFF:FIP_OFF + 8] != bytes.fromhex("010064aa78563412"):
        raise RuntimeError("XG140 live mtd0 has no Airoha FIP at physical 0x800")
    window = live[FIP_OFF:ENV_OFF]
    _serial, _flags, entries, _term, declared_end = repack.parse(window)
    if declared_end <= 0 or declared_end > len(window):
        raise RuntimeError(f"XG140 native FIP declared end invalid: 0x{declared_end:x}")
    donor = window[:declared_end]
    nts = [e for e in entries if e["uuid"] == repack.NT_UUID]
    if len(nts) != 1:
        raise RuntimeError(f"XG140 native FIP must contain exactly one NT_FW, found {len(nts)}")
    return donor, {
        "entry_count": len(entries),
        "declared_end": declared_end,
        "donor_sha256": sha256_bytes(donor),
        "prefix_sha256": sha256_bytes(live[:FIP_OFF]),
        "vendor_env_sha256": sha256_bytes(live[ENV_OFF:]),
    }


def build_candidate(live: bytes, bl33: bytes) -> tuple[bytes, dict]:
    donor, donor_meta = extract_native_fip(live)
    hybrid, report = repack.rebuild(donor, bl33)
    if FIP_OFF + len(hybrid) >= ENV_OFF:
        raise RuntimeError(f"XG140 native-hybrid FIP overlaps vendor env: end=0x{FIP_OFF + len(hybrid):x}")

    candidate = bytearray(live)
    candidate[FIP_OFF:FIP_OFF + len(hybrid)] = hybrid
    old_end = donor_meta["declared_end"]
    if len(hybrid) < old_end:
        pad_byte = int(report.get("padding_byte", 0))
        candidate[FIP_OFF + len(hybrid):FIP_OFF + old_end] = bytes([pad_byte]) * (old_end - len(hybrid))
    final = bytes(candidate)
    if final[:FIP_OFF] != live[:FIP_OFF]:
        raise RuntimeError("XG140 candidate changed BootROM prefix")
    if final[ENV_OFF:] != live[ENV_OFF:]:
        raise RuntimeError("XG140 candidate changed protected vendor env")

    return final, {
        **donor_meta,
        **report,
        "candidate_sha256": sha256_bytes(final),
        "candidate_size": len(final),
        "fip_sha256": sha256_bytes(hybrid),
        "fip_size": len(hybrid),
    }

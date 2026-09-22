#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
from pathlib import Path


TEST62_VERSION = "0.1.0-alpha5-UBIUX1-TEST62"
FIP_NAME = "ursusboot-md-0.1.0-alpha5-UBIUX1-TEST62-update.fip"
FAST_BL2_NAME = "openwrt-airoha-an7581-nokia-xg040md-TEST62-fast-ubi-preloader.bin"
CANONICAL_PRELOADER = "openwrt-airoha-an7581-nokia_xg-040g-md-ubi-preloader.bin"

# The hardware-proven UBI preloader is a FIP with a single TB_FW (BL2) entry,
# exactly as produced by `fiptool create --tb-fw <bl2>`. The TEST62 CI artifact
# carries the raw an7581-bl2.bin, so it is wrapped the same way here.
FIP_TOC_NAME = 0xAA640001
FIP_TOC_SERIAL = 0x12345678
TB_FW_UUID = bytes.fromhex("5ff9ec0b4d223e4da544c39d81c73f0a")


def is_fip(blob: bytes) -> bool:
    return len(blob) >= 16 and struct.unpack_from("<I", blob, 0)[0] == FIP_TOC_NAME


def wrap_tb_fw(bl2: bytes) -> bytes:
    """Byte-identical equivalent of `fiptool create --tb-fw bl2`."""
    off = 16 + 2 * 40
    return (
        struct.pack("<IIQ", FIP_TOC_NAME, FIP_TOC_SERIAL, 0)
        + TB_FW_UUID + struct.pack("<QQQ", off, len(bl2), 0)
        + bytes(16) + struct.pack("<QQQ", off + len(bl2), 0, 0)
        + bl2
    )


def tb_fw_payload(fip: bytes) -> bytes:
    """Return the BL2 of a single-entry TB_FW FIP, rejecting anything else."""
    if not is_fip(fip):
        raise RuntimeError("preloader is not a FIP")
    entries = []
    pos = 16
    while True:
        uuid = fip[pos:pos + 16]
        off, size, _flags = struct.unpack_from("<QQQ", fip, pos + 16)
        pos += 40
        if uuid == bytes(16):
            break
        entries.append((uuid, off, size))
    if len(entries) != 1 or entries[0][0] != TB_FW_UUID:
        raise RuntimeError(f"preloader FIP must hold exactly one TB_FW entry, got {len(entries)}")
    _uuid, off, size = entries[0]
    if off + size > len(fip):
        raise RuntimeError("preloader FIP TB_FW entry out of bounds")
    return fip[off:off + size]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def apply_overlay(tree: Path, artifacts: Path) -> None:
    tree = tree.resolve()
    artifacts = artifacts.resolve()
    fip = artifacts / FIP_NAME
    raw = artifacts / "u-boot.bin"
    preloader = artifacts / FAST_BL2_NAME
    for p in (fip, raw, preloader):
        if not p.is_file() or p.stat().st_size == 0:
            raise FileNotFoundError(f"required TEST62 artifact missing: {p}")

    marker = artifacts / "TEST62-BUILD_INFO.txt"
    if marker.is_file() and TEST62_VERSION not in marker.read_text(encoding="utf-8", errors="replace"):
        raise RuntimeError("TEST62 build-info does not identify the expected candidate")

    payload_dir = tree / "data" / "payloads" / "md" / "ursusboot"
    payload_dir.mkdir(parents=True, exist_ok=True)
    dst_fip = payload_dir / FIP_NAME
    dst_preloader = payload_dir / CANONICAL_PRELOADER
    shutil.copy2(fip, dst_fip)
    raw_bl2 = preloader.read_bytes()
    dst_preloader.write_bytes(raw_bl2 if is_fip(raw_bl2) else wrap_tb_fw(raw_bl2))
    tb_fw_payload(dst_preloader.read_bytes())
    # Ship only the TEST62 candidate; a leftover TEST61 FIP must not be installable.
    for stale in payload_dir.glob("*TEST61*.fip"):
        stale.unlink()

    temp = {
        "schema": 1,
        "role": "TEMPORARY_ITEM4_URSUSBOOT",
        "version": TEST62_VERSION,
        "fip_path": f"data/payloads/md/ursusboot/{FIP_NAME}",
        "fip_size": dst_fip.stat().st_size,
        "fip_sha256": sha256(dst_fip),
        "raw_bl33_sha256": sha256(raw),
        "provenance": "MD TEST62 + fast BL2 CI artifact",
    }
    (tree / "data" / "ITEM4_TEMP_URSUSBOOT.json").write_text(
        json.dumps(temp, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    manifest_path = tree / "data" / "FIRMWARE_BUNDLE.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hits = [
        item for item in manifest.get("files", [])
        if item.get("role") == "STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE"
    ]
    if len(hits) != 1:
        raise RuntimeError("expected exactly one STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE")
    hits[0]["sha256"] = sha256(dst_preloader)
    hits[0]["size"] = dst_preloader.stat().st_size
    hits[0]["provenance"] = "TEST62 fast BL2"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # VERSION is the UrsusFlasher kit version (shown and checked by the host);
    # the UrsusBoot TEST62 identity lives in ITEM4_TEMP_URSUSBOOT.json.

    (tree / "TEST62_PROVENANCE.txt").write_text(
        f"URSUSBOOT={TEST62_VERSION}\n"
        f"FIP_SHA256={sha256(dst_fip)}\n"
        f"RAW_BL33_SHA256={sha256(raw)}\n"
        f"FAST_BL2_RAW_SHA256={sha256(preloader)}\n"
        f"FAST_BL2_PRELOADER_FIP_SHA256={sha256(dst_preloader)}\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True)
    ap.add_argument("--artifacts", required=True)
    args = ap.parse_args()
    apply_overlay(Path(args.tree), Path(args.artifacts))


if __name__ == "__main__":
    main()

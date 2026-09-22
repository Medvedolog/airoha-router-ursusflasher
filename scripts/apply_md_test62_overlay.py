#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


TEST62_VERSION = "0.1.0-alpha5-UBIUX1-TEST62"
FIP_NAME = "ursusboot-md-0.1.0-alpha5-UBIUX1-TEST62-update.fip"
FAST_BL2_NAME = "openwrt-airoha-an7581-nokia-xg040md-TEST62-fast-ubi-preloader.bin"
CANONICAL_PRELOADER = "openwrt-airoha-an7581-nokia_xg-040g-md-ubi-preloader.bin"


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
    shutil.copy2(preloader, dst_preloader)
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

    for version_path in (tree / "VERSION", tree / "data" / "VERSION"):
        version_path.write_text(TEST62_VERSION + "\n", encoding="utf-8", newline="\n")

    (tree / "TEST62_PROVENANCE.txt").write_text(
        f"URSUSBOOT={TEST62_VERSION}\n"
        f"FIP_SHA256={sha256(dst_fip)}\n"
        f"RAW_BL33_SHA256={sha256(raw)}\n"
        f"FAST_BL2_SHA256={sha256(dst_preloader)}\n",
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

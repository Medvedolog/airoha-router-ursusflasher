#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from repo_common import ROOT, export_tree, sha256, write_manifest

VERSION = "0.1.0-alpha5-UBIUX1-TRANSITION1"
PAYLOAD_NAME = f"ursusboot-md-{VERSION}.uimg"


def rebuild_payload_manifest(tree: Path) -> None:
    rows = []
    payload_root = tree / "data" / "payloads"
    for p in sorted(payload_root.rglob("*"), key=lambda x: x.relative_to(payload_root).as_posix()):
        if p.is_file():
            rows.append(f"{sha256(p)}  {p.relative_to(tree).as_posix()}")
    (tree / "PAYLOAD_SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    write_manifest(tree)


def zip_tree(tree: Path, zpath: Path) -> str:
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "1789300800"))
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    zip_dt = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second - dt.second % 2)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(tree.rglob("*"), key=lambda x: x.relative_to(tree).as_posix()):
            if not p.is_file():
                continue
            arc = p.relative_to(tree.parent).as_posix()
            info = zipfile.ZipInfo(arc, date_time=zip_dt)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            z.writestr(info, p.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return hashlib.sha256(zpath.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uimage", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=Path("dist-transition"))
    ap.add_argument("--source-sha", default=os.environ.get("GITHUB_SHA", "UNKNOWN"))
    ap.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "UNKNOWN"))
    args = ap.parse_args()
    if not args.uimage.is_file():
        raise SystemExit(f"missing TRANSITION uImage: {args.uimage}")

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    package_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("-", 1)[0]
    name = f"UrsusFlasher-{package_version}-MD-AB-TRANSITION1-PUBLIC-TEST"

    with tempfile.TemporaryDirectory() as td:
        tree = export_tree(Path(td) / name)
        payload_dir = tree / "data" / "payloads" / "md" / "transition"
        payload_dir.mkdir(parents=True, exist_ok=True)
        dst = payload_dir / PAYLOAD_NAME
        shutil.copy2(args.uimage, dst)
        meta = {
            "schema": 1,
            "mode": "TRANSITION",
            "board": "MD",
            "soc": "AN7581",
            "version": VERSION,
            "filename": PAYLOAD_NAME,
            "sha256": sha256(dst),
            "source_commit": args.source_sha,
            "github_actions_run_id": str(args.run_id),
            "persistence_target": "NONE",
            "final_target": "OFFICIAL_OPENWRT",
            "hardware_acceptance": "PENDING",
            "stock_bootloader_policy": "KEEP_MTD0_TCBOOT_UNCHANGED",
            "selector_contract": "WRITE_INACTIVE_NSB_SLAVE_THEN_MTD8_ACTIVE_0_TO_1; DO_NOT_WRITE_FLAGBACK",
        }
        (payload_dir / "TRANSITION1.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (tree / "TRANSITION1_TEST.txt").write_text(
            "MD A/B TRANSITION1 hardware-test bundle.\n"
            "Run START_MD_TRANSITION.cmd (Windows) or START_MD_TRANSITION.sh (Linux/macOS).\n"
            "This path preserves stock mtd0/tcboot, writes a device-derived nsb_slave candidate, verifies readback, then requests SLAVE by changing only mtd8.active.\n"
            "mtd9/flagback is read-only. MAIN/nsb_master is not written.\n"
            "Hardware acceptance is PENDING. Keep UART connected for the first run.\n",
            encoding="utf-8", newline="\n",
        )
        release_note = tree / "PUBLIC_TEST_RELEASE.txt"
        if release_note.is_file():
            release_note.write_text(release_note.read_text(encoding="utf-8") + "MD A/B TRANSITION1 is included as an explicit hardware-test launcher; it is not yet part of ONE-CLICK.\n", encoding="utf-8", newline="\n")
        rebuild_payload_manifest(tree)
        zpath = out / f"{name}.zip"
        digest = zip_tree(tree, zpath)
        (out / f"{name}.zip.sha256.txt").write_text(f"{digest}  {zpath.name}\n", encoding="utf-8", newline="\n")
        print(zpath)


if __name__ == "__main__":
    main()

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

from repo_common import ROOT, sha256, write_manifest

VERSION = "0.1.0-alpha5-UBIUX1-TRANSITION2"
PAYLOAD_NAME = f"ursusboot-md-{VERSION}.linuximg"
META_NAME = "TRANSITION2.json"
TEST_INFO_NAME = "TRANSITION2_NETDBG1_TEST.txt"


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


def overlay_current_host(tree: Path) -> None:
    for name in (
        "START_ONECLICK.cmd", "START_ONECLICK.sh",
        "START_EXPERT.cmd", "START_EXPERT.sh",
        "START_MD_TRANSITION.cmd", "START_MD_TRANSITION.sh",
        "VERSION",
    ):
        shutil.copy2(ROOT / name, tree / name)
    shutil.copy2(ROOT / "VERSION", tree / "data" / "VERSION")

    src_root = ROOT / "ursusflasher" / "src"
    current_top_py = set()
    for src in sorted(src_root.rglob("*")):
        if not src.is_file() or src.name.endswith((".pyc", ".pyo")) or "__pycache__" in src.parts:
            continue
        rel = src.relative_to(src_root)
        dst = tree / "data" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if len(rel.parts) == 1 and rel.suffix == ".py":
            current_top_py.add(rel.name)
    for packed in (tree / "data").glob("*.py"):
        if packed.name not in current_top_py:
            packed.unlink()

    for name in ("UI_TERMS.json", "FIRMWARE_CAPABILITIES.json", "BOARD_PROFILES.json", "FIRMWARE_BUNDLES.json"):
        shutil.copy2(ROOT / "config" / name, tree / "data" / name)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--linux-image", type=Path, required=True)
    ap.add_argument("--base-zip", type=Path, required=True,
                    help="Audited full UrsusFlasher hardware-kit ZIP from GitHub Actions")
    ap.add_argument("--out-dir", type=Path, default=Path("dist-transition"))
    ap.add_argument("--source-sha", default=os.environ.get("GITHUB_SHA", "UNKNOWN"))
    ap.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "UNKNOWN"))
    ap.add_argument("--base-run-id", default="34589613011")
    args = ap.parse_args()
    if not args.linux_image.is_file():
        raise SystemExit(f"missing TRANSITION Linux Image: {args.linux_image}")
    if not args.base_zip.is_file():
        raise SystemExit(f"missing audited base ZIP: {args.base_zip}")

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    package_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip().split("-", 1)[0]
    name = f"UrsusFlasher-{package_version}-MD-AB-TRANSITION2-NETDBG1-PUBLIC-TEST"

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        with zipfile.ZipFile(args.base_zip) as z:
            z.extractall(tdp / "base")
        roots = [p for p in (tdp / "base").iterdir() if p.is_dir()]
        if len(roots) != 1:
            raise SystemExit(f"audited base ZIP must contain one root directory, got: {roots}")
        tree = tdp / name
        roots[0].rename(tree)

        frozen = {}
        for rel in ("data/payloads", "fw"):
            base = tree / rel
            for p in base.rglob("*"):
                if p.is_file():
                    frozen[p.relative_to(tree).as_posix()] = sha256(p)

        overlay_current_host(tree)

        payload_dir = tree / "data" / "payloads" / "md" / "transition"
        payload_dir.mkdir(parents=True, exist_ok=True)
        # Remove stale engineering transition payloads from an audited base kit;
        # the current host policy must resolve exactly one TRANSITION2 payload.
        for stale in payload_dir.glob("TRANSITION*.json"):
            stale.unlink()
        for stale in payload_dir.glob("ursusboot-md-*-TRANSITION*.linuximg"):
            stale.unlink()

        dst = payload_dir / PAYLOAD_NAME
        shutil.copy2(args.linux_image, dst)
        meta = {
            "schema": 2,
            "mode": "TRANSITION",
            "board": "MD",
            "soc": "AN7581",
            "version": VERSION,
            "filename": PAYLOAD_NAME,
            "sha256": sha256(dst),
            "source_commit": args.source_sha,
            "github_actions_run_id": str(args.run_id),
            "audited_base_actions_run_id": str(args.base_run_id),
            "audited_base_zip_sha256": sha256(args.base_zip),
            "persistence_target": "NONE",
            "final_target": "OFFICIAL_OPENWRT",
            "hardware_acceptance": "PENDING",
            "netdbg_build": "TRANSITION2-NETDBG1",
            "netreset_command": "ursusnetreset",
            "netreset_experiment": "TRANSITION2-NETRESET1",
            "stock_inner_format": "ARM64_LINUX_IMAGE_HANDOFF",
            "stock_wrapper_contract": "PRESERVE_FIP_HDR2_FIT_FDT_ROOTFS_AND_KERNEL_SIZE; PATCH_KERNEL_DATA_COMPRESSION_HASH_ONLY",
            "stock_kernel_load_entry": "0x80088000",
            "ursusboot_text_base": "0x81e00000",
            "stock_bootloader_policy": "KEEP_MTD0_TCBOOT_UNCHANGED",
            "selector_contract": "WRITE_INACTIVE_NSB_SLAVE_THEN_MTD8_ACTIVE_0_TO_1; DO_NOT_WRITE_FLAGBACK",
        }
        (payload_dir / META_NAME).write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (tree / "BUILD_COMMIT.txt").write_text(args.source_sha + "\n", encoding="ascii", newline="\n")
        (tree / TEST_INFO_NAME).write_text(
            "MD A/B TRANSITION2 NETDBG1 stock-FIT hardware-test bundle.\n"
            "Run START_MD_TRANSITION.cmd (Windows) or START_MD_TRANSITION.sh (Linux/macOS), or use EXPERT item 4.\n"
            "This full UrsusFlasher kit is derived from the audited 0.2.62 Actions artifact.\n"
            "The live nsb_slave is used as the stock template. FIP, HDR2, FIT topology, fdt@1, filesystem@1, kernel type/os/load/entry and all declared sizes are preserved.\n"
            "Only kernel@1 data, compression (lzma->none), and the existing SHA1 value are changed.\n"
            "kernel@1 remains an ARM64 Linux Image at stock 0x80088000; its handoff shim copies TRANSITION U-Boot to 0x81e00000 and branches there.\n"
            "TRANSITION2 contains NETDBG1 RX/QDMA/FEMEM diagnostics and the one-shot UART command ursusnetreset.\n"
            "mtd0/tcboot, mtd9/flagback and MAIN/nsb_master are not written. Hardware acceptance is PENDING.\n",
            encoding="utf-8", newline="\n",
        )

        # Existing audited payloads/fw stay byte-exact except stale transition
        # engineering files deliberately replaced above by the current payload.
        for rel, expected in frozen.items():
            if rel.startswith("data/payloads/md/transition/"):
                continue
            p = tree / rel
            if not p.is_file() or sha256(p) != expected:
                raise AssertionError(f"audited hardware byte changed: {rel}")

        host_policy = (tree / "data" / "stock_ab_transition.py").read_bytes()
        assert host_policy == (ROOT / "ursusflasher" / "src" / "stock_ab_transition.py").read_bytes()
        assert PAYLOAD_NAME.encode() in host_policy
        assert META_NAME.encode() in host_policy
        assert dst.is_file() and (payload_dir / META_NAME).is_file()
        assert not list(payload_dir.glob("*TRANSITION1*"))
        assert (tree / "data" / "stock_fit_wrapper.py").read_bytes() == (ROOT / "ursusflasher" / "src" / "stock_fit_wrapper.py").read_bytes()
        assert (tree / "START_MD_TRANSITION.cmd").read_bytes() == (ROOT / "START_MD_TRANSITION.cmd").read_bytes()
        assert (tree / "START_MD_TRANSITION.sh").read_bytes() == (ROOT / "START_MD_TRANSITION.sh").read_bytes()

        rebuild_payload_manifest(tree)
        zpath = out / f"{name}.zip"
        digest = zip_tree(tree, zpath)
        (out / f"{name}.zip.sha256.txt").write_text(f"{digest}  {zpath.name}\n", encoding="utf-8", newline="\n")
        print(f"TRANSITION_ROLLUP_QA=PASS frozen_hardware_files={len(frozen)} payload={PAYLOAD_NAME} meta={META_NAME}")
        print(zpath)


if __name__ == "__main__":
    main()

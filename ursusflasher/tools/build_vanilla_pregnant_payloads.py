#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from build_pregnant_runtime import patch_fit

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "openwrt" / "pregnant-overlay"
UNAMEONE = ROOT / "config" / "UNAMEONE_2026-09-16_PAYLOADS.json"
BOOTCHAIN = ROOT / "config" / "VANILLA_BOOT_CHAIN_PROFILES.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path: Path, spec: dict, role: str) -> None:
    if not path.is_file():
        raise SystemExit(f"ERROR: missing {role}: {path}")
    size = path.stat().st_size
    digest = sha256(path)
    if size != int(spec["size"]) or digest != str(spec["sha256"]).lower():
        raise SystemExit(
            f"ERROR: {role} integrity mismatch: {path.name} "
            f"size={size} sha256={digest} expected_size={spec['size']} expected_sha256={spec['sha256']}"
        )


def file_spec(path: Path, *, source: str) -> dict:
    return {
        "filename": path.name,
        "size": path.stat().st_size,
        "sha256": sha256(path),
        "source": source,
    }


def build_family(
    *,
    profile: str,
    family: str,
    recovery: Path,
    snapshot_version: Path,
    fip: Path,
    preloader: Path,
    output_root: Path,
    unameone: dict,
    bootchain: dict,
) -> None:
    prod_spec = unameone["profiles"][profile]["ubi_sysupgrade"]
    production = ROOT / "fw" / prod_spec["filename"]
    verify(production, prod_spec, f"{profile} pinned UnameOne production")

    boot_profile = bootchain["profiles"][profile]
    verify(fip, boot_profile["fip"], f"{profile} pinned Vanilla FIP")
    verify(preloader, boot_profile["preloader"], f"{profile} pinned Vanilla preloader")

    if not recovery.is_file() or recovery.stat().st_size < 1024 * 1024:
        raise SystemExit(f"ERROR: invalid official recovery FIT: {recovery}")
    if not snapshot_version.is_file():
        raise SystemExit(f"ERROR: snapshot version file missing: {snapshot_version}")

    out = output_root / family
    out.mkdir(parents=True, exist_ok=True)
    runtime = out / "runtime.itb"
    runtime_blob, surgery = patch_fit(recovery.read_bytes(), OVERLAY, family)
    runtime.write_bytes(runtime_blob)

    prod_out = out / production.name
    fip_out = out / "vanilla-bl31-uboot.fip"
    pre_out = out / "vanilla-preloader.bin"
    shutil.copyfile(production, prod_out)
    shutil.copyfile(fip, fip_out)
    shutil.copyfile(preloader, pre_out)

    recovery_spec = file_spec(recovery, source="official OpenWrt snapshot UBI recovery")
    version = snapshot_version.read_text(encoding="utf-8", errors="replace").strip()
    payload = {
        "schema": 1,
        "mode": "VANILLA_PREGNANT_MIGRATION",
        "profile": profile,
        "family": family,
        "production_edition": unameone.get("edition"),
        "production_build_date": unameone.get("build_date"),
        "unameone_sha256": prod_spec["sha256"],
        "transient": {
            "policy": "fresh/current official OpenWrt UBI-recovery runtime; not the production child",
            "openwrt_version_buildinfo": version,
            **recovery_spec,
            "surgery": surgery,
        },
        "boot_chain": {
            "manifest": "config/VANILLA_BOOT_CHAIN_PROFILES.json",
            "source_repository": bootchain["source"]["repository"],
            "source_commit": bootchain["source"]["commit"],
            "fip_status": boot_profile["fip"].get("status"),
            "preloader_status": boot_profile["preloader"].get("status"),
            "bl2_written_last": True,
        },
        "files": {
            "runtime": file_spec(runtime, source="patched official OpenWrt UBI-recovery FIT"),
            "production": file_spec(prod_out, source="repository fw/ exact pinned UnameOne child"),
            "fip": file_spec(fip_out, source="pinned proven Vanilla boot chain"),
            "preloader": file_spec(pre_out, source="pinned proven Vanilla boot chain"),
        },
    }
    (out / "PAYLOAD.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"PREGNANT_PAYLOAD_{family.upper()}=PASS "
        f"runtime={payload['files']['runtime']['sha256']} "
        f"production={payload['files']['production']['sha256']} "
        f"fip={payload['files']['fip']['sha256']} preloader={payload['files']['preloader']['sha256']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble exact MD/MF UrsusFlasher Vanilla pregnant payload directories")
    parser.add_argument("--md-recovery", type=Path, required=True)
    parser.add_argument("--mf-recovery", type=Path, required=True)
    parser.add_argument("--md-version", type=Path, required=True)
    parser.add_argument("--mf-version", type=Path, required=True)
    parser.add_argument("--md-fip", type=Path, required=True)
    parser.add_argument("--mf-fip", type=Path, required=True)
    parser.add_argument("--md-preloader", type=Path, required=True)
    parser.add_argument("--mf-preloader", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "payloads" / "vanilla-pregnant")
    args = parser.parse_args()

    unameone = json.loads(UNAMEONE.read_text(encoding="utf-8"))
    bootchain = json.loads(BOOTCHAIN.read_text(encoding="utf-8"))
    args.output_root.mkdir(parents=True, exist_ok=True)

    build_family(
        profile="xg040-md", family="md", recovery=args.md_recovery, snapshot_version=args.md_version,
        fip=args.md_fip, preloader=args.md_preloader, output_root=args.output_root,
        unameone=unameone, bootchain=bootchain,
    )
    build_family(
        profile="xg040-mf", family="mf", recovery=args.mf_recovery, snapshot_version=args.mf_version,
        fip=args.mf_fip, preloader=args.mf_preloader, output_root=args.output_root,
        unameone=unameone, bootchain=bootchain,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

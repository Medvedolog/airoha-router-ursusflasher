#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import proven_backend as pb


def tr(ru: str, en: str) -> str:
    return pb.tr(ru, en)


def verify_kit() -> None:
    """Verify only resources used by current ONE-KEY/EXPERT paths.

    Historical MedveFlasher transition bundles, launcher/source trees and
    vendored Rich are deliberately not part of the UrsusFlasher runtime kit.
    """
    root_version = pb.KIT / "VERSION"
    data_version = pb.DATA / "VERSION"
    manifest_path = pb.DATA / "MANIFEST.json"
    required = (
        root_version,
        data_version,
        manifest_path,
        pb.STOCK_WEB,
        pb.BACKUP_AGENT,
        pb.RECOVERY_PRELOADER,
        pb.RECOVERY_FIP,
        pb.RECOVERY_INITRAMFS,
        pb.MF_RECOVERY_METADATA,
        pb.MF_RECOVERY_PRELOADER,
        pb.MF_RECOVERY_FIP,
        pb.MF_STOCK_RECOVERY_INITRAMFS,
        pb.STOCK_AUDIT_SCRIPT,
        pb.STOCK_AUDIT_PARSER,
        pb.FIRMWARE_CAPABILITIES,
        pb.RECOVERY_TFTP_CLIENT,
        pb.RECOVERY_SCP_CLIENT,
    )
    for path in required:
        if not path.is_file():
            raise pb.Error(f"повреждён комплект: отсутствует {path.relative_to(pb.KIT)}")

    root_version_text = root_version.read_text(encoding="utf-8").strip()
    data_version_text = data_version.read_text(encoding="utf-8").strip()
    if root_version_text != pb.APP_VERSION or data_version_text != pb.APP_VERSION:
        raise pb.Error(tr(
            f"VERSION/data/VERSION не совпадают с кодом {pb.APP_VERSION}",
            f"VERSION/data/VERSION do not match code version {pb.APP_VERSION}",
        ))

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise pb.Error(tr(
            f"не удалось прочитать MANIFEST.json: {exc}",
            f"failed to read MANIFEST.json: {exc}",
        )) from exc
    if manifest.get("version") != pb.APP_VERSION or manifest.get("build_tag") != pb.BUILD_TAG:
        raise pb.Error(tr(
            "MANIFEST.json version/build_tag не совпадают с кодом",
            "MANIFEST.json version/build_tag do not match the code",
        ))
    release = manifest.get("release") or {}
    if (
        release.get("version") != pb.APP_VERSION
        or release.get("build_tag") != pb.BUILD_TAG
        or release.get("archive_root") != f"UrsusFlasher-{pb.APP_VERSION}"
    ):
        raise pb.Error(tr(
            "MANIFEST.json release metadata не совпадает с UrsusFlasher",
            "MANIFEST.json release metadata does not match UrsusFlasher",
        ))

    pb._verify_exact_artifact(pb.RECOVERY_TFTP_CLIENT, 7792, pb.RECOVERY_TFTP_CLIENT_SHA, "pinned AArch64 nokia-tftp")
    pb._verify_exact_artifact(pb.RECOVERY_SCP_CLIENT, 6072, pb.RECOVERY_SCP_CLIENT_SHA, "pinned AArch64 nokia-scp")
    pb._verify_exact_artifact(pb.RECOVERY_PRELOADER, 113447, pb.RECOVERY_PRELOADER_SHA, "AN7581 preloader")
    pb._verify_exact_artifact(pb.RECOVERY_FIP, pb.RECOVERY_FIP_SIZE, pb.RECOVERY_FIP_SHA, "AN7581 recovery-safe FIP")
    pb._verify_recovery_safe_fip(
        pb.RECOVERY_FIP,
        pb.BACKUP_RECOVERY_BL31_COMPRESSED_SHA,
        pb.BACKUP_RECOVERY_BL33_COMPRESSED_SHA,
        "AN7581 recovery-safe FIP",
    )
    pb._verify_exact_artifact(pb.RECOVERY_INITRAMFS, pb.RECOVERY_INITRAMFS_SIZE, pb.RECOVERY_INITRAMFS_SHA, "AN7581 stock-recovery initramfs")

    pb._load_mf_snapshot_metadata()
    pb._verify_exact_artifact(pb.MF_RECOVERY_PRELOADER, pb.MF_RECOVERY_PRELOADER_SIZE, pb.MF_RECOVERY_PRELOADER_SHA, "AN7583 preloader")
    pb._verify_exact_artifact(pb.MF_RECOVERY_FIP, pb.MF_RECOVERY_FIP_SIZE, pb.MF_RECOVERY_FIP_SHA, "AN7583 recovery-safe FIP")
    pb._verify_recovery_safe_fip(
        pb.MF_RECOVERY_FIP,
        "6d97815b5cdf905eff874062f9364ebe41a2a11f4b25944a82aea4fcbdd71e35",
        "3bb4cf1aa950dd212e1b5781abf55c239ff61326d5ca0c19e9f2c010285f5bb1",
        "AN7583 recovery-safe FIP",
    )
    pb._verify_exact_artifact(
        pb.MF_STOCK_RECOVERY_INITRAMFS,
        pb.MF_STOCK_RECOVERY_INITRAMFS_SIZE,
        pb.MF_STOCK_RECOVERY_INITRAMFS_SHA,
        "AN7583 stock-recovery initramfs",
    )

    try:
        caps = json.loads(pb.FIRMWARE_CAPABILITIES.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise pb.Error(tr(
            f"не удалось прочитать FIRMWARE_CAPABILITIES.json: {exc}",
            f"failed to read FIRMWARE_CAPABILITIES.json: {exc}",
        )) from exc
    if caps.get("version") != pb.APP_VERSION:
        raise pb.Error(tr(
            "FIRMWARE_CAPABILITIES.json version не совпадает с кодом",
            "FIRMWARE_CAPABILITIES.json version does not match the code",
        ))

    legacy = (
        pb.DATA / "transition-bundle.bin",
        pb.DATA / "transition-manual-bundle.bin",
        pb.DATA / "mf-transition-bundle.bin",
        pb.DATA / "mf-transition-manual-bundle.bin",
        pb.DATA / "stock-launcher.sh.in",
        pb.DATA / "env_patcher.py",
        pb.DATA / "vendor",
        pb.RECOVERY_DIR / "manual-transition-source",
        pb.RECOVERY_DIR / "transition-control-source",
        pb.RECOVERY_DIR / "transition-network-source",
        pb.RECOVERY_DIR / "recovery-clients-source",
        pb.RECOVERY_DIR / "recovery-safe-uboot-source",
    )
    leaked = [path for path in legacy if path.exists()]
    if leaked:
        names = ", ".join(str(path.relative_to(pb.KIT)) for path in leaked)
        raise pb.Error(tr(
            f"в комплект попало legacy MedveFlasher-наследие: {names}",
            f"legacy MedveFlasher assets leaked into the kit: {names}",
        ))


def install() -> None:
    """Replace the inherited broad verifier in the already-imported backend."""
    pb.verify_kit = verify_kit

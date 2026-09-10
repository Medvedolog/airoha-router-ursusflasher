#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import re
import struct
from pathlib import Path

FIP_MAGIC = 0xAA640001
EXPECTED_PRELOADER_SIZE = 118322
EXPECTED_PRELOADER_SHA256 = "c2ac1c183b18bc34632c958dfe0bd1dfdfb607f090e39c41126956641893362f"
EXPECTED_BL31_COMPRESSED_SHA256 = "6d97815b5cdf905eff874062f9364ebe41a2a11f4b25944a82aea4fcbdd71e35"

FORBIDDEN_BOARD_TOKENS = (
    b"Nokia XG-040G-MD",
    b"Nokia_XG-040G-MD",
    b"nokia_xg-040g-md",
    b"nokia,xg-040g-md",
    b"NOKIA_XG040GMD",
    b"URSUSBOOT_MD",
    b"TCBOOT_MD",
    b"openwrt-airoha-an7581-nokia_xg-040g-md-ubi-preloader.bin",
    b"Airoha EN8811H",
)

# The recovery RAM image deliberately exposes only generic UART/XMODEM + raw
# MTD tools. High-level FIP/UBI/settings writers remain blocked.
REQUIRED_BINARY_MARKERS = (
    b"0.1.0-TEST61",
    b"Nokia XG-040G-MF",
    b"Airoha AN7583",
    b"URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE",
    b"URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE_STEP",
    b"URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE",
    b"URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE_STEP",
    b"URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION",
    b"URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION_STEP",
    b"URSUS_MF2_READONLY_REJECT operation=SETTINGS_RESET",
    b"URSUS_MF2_READONLY_REJECT operation=SETTINGS_RESET_BACKEND",
    b"URSUS_MF2_READONLY_REJECT operation=FACTORY_INSTALL",
    b"URSUS_MF2_READONLY_REJECT operation=FACTORY_SETTINGS_RESET",
    b"URSUS_MF2_STOCKBRIDGE_DISABLED board=AN7583 mode=RAM_ONLY",
    b"URSUS_MF2_LAN_LED_SETUP raw_mmio=disabled native_an7583=1",
)

FORBIDDEN_SYMBOL_TOKENS = (
    "ursus_scu_read",
    "ursus_scu_write",
    "ursus_lanphy_c45",
    "ursus_an7581_safe_gpio",
    "do_ursusstockboot",
    "ursusstockboot",
    "en8811h_config",
    "en8811h_probe",
)

FORBIDDEN_CONFIG_Y = (
    "CONFIG_CMD_MTD_MARKBAD",
    "CONFIG_CMD_MTD_NAND_WRITE_TEST",
    "CONFIG_CMD_UBI",
    "CONFIG_CMD_UBI_RENAME",
    "CONFIG_CMD_ERASEENV",
    "CONFIG_CMD_NAND",
    "CONFIG_CMD_SF",
    "CONFIG_CMD_PXE",
    "CONFIG_ENV_IS_IN_MTD",
    "CONFIG_ENV_IS_IN_UBI",
    "CONFIG_PHY_AIROHA_EN8811",
)

REQUIRED_CONFIG_Y = (
    "CONFIG_TARGET_AN7583",
    "CONFIG_MTD",
    "CONFIG_DM_MTD",
    "CONFIG_MTD_SPI_NAND",
    "CONFIG_CMD_MTD",
    "CONFIG_CMD_LOADB",
    "CONFIG_NET_LWIP",
    "CONFIG_AIROHA_ETH",
    "CONFIG_PCS_AIROHA_AN7583",
    "CONFIG_PINCTRL_AIROHA_AN7583",
    "CONFIG_ENV_IS_NOWHERE",
    "CONFIG_CONSOLE_RECORD",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def one(paths: list[Path], label: str) -> Path:
    if len(paths) != 1:
        raise SystemExit(f"{label}: expected exactly one file, got {[p.name for p in paths]}")
    return paths[0]


def parse_fip(data: bytes):
    if len(data) < 136:
        raise SystemExit("FIP too small")
    magic, serial, flags = struct.unpack_from("<IIQ", data, 0)
    if magic != FIP_MAGIC:
        raise SystemExit(f"bad FIP magic 0x{magic:08x}")
    entries = []
    pos = 16
    while pos + 40 <= len(data):
        uuid = data[pos:pos + 16]
        offset, size, eflags = struct.unpack_from("<QQQ", data, pos + 16)
        if uuid == b"\x00" * 16:
            if offset != len(data) or size != 0:
                raise SystemExit(f"FIP terminator mismatch offset={offset} size={size} file={len(data)}")
            return serial, flags, entries
        if offset + size > len(data):
            raise SystemExit("FIP entry exceeds file")
        entries.append((uuid, offset, size, eflags))
        pos += 40
    raise SystemExit("FIP terminator missing")


def audit(outdir: Path) -> dict:
    outdir = outdir.resolve()
    if not outdir.is_dir():
        raise SystemExit(f"artifact directory missing: {outdir}")

    preloader = one(list(outdir.glob("*uart-preloader.bin")), "preloader")
    fip = one(list(outdir.glob("*ram.fip")), "RAM FIP")
    uboot = outdir / "u-boot.bin"
    sym = outdir / "u-boot.sym"
    config = outdir / "u-boot.MF_RAM.full.config"
    env = outdir / "MF_RAM.env"
    report_path = outdir / "MF-FIP-REPACK.json"
    for path in (uboot, sym, config, env, report_path):
        if not path.is_file():
            raise SystemExit(f"artifact file missing: {path.name}")

    pre = preloader.read_bytes()
    if len(pre) != EXPECTED_PRELOADER_SIZE or sha256(pre) != EXPECTED_PRELOADER_SHA256:
        raise SystemExit(f"preloader mismatch size={len(pre)} sha256={sha256(pre)}")

    raw = uboot.read_bytes()
    for token in FORBIDDEN_BOARD_TOKENS:
        if token in raw:
            raise SystemExit(f"forbidden board/LAN1 token leaked into u-boot.bin: {token!r}")
    for marker in REQUIRED_BINARY_MARKERS:
        if marker not in raw:
            raise SystemExit(f"required MF binary marker missing: {marker!r}")

    hwtest8 = b"URSUS_MF2_HWTEST8_LED_BEGIN" in raw
    if hwtest8:
        for marker in (b"URSUS_MF2_HWTEST8_LED_END result=OK", b"URSUS_MF2_HWTEST7_PHY_PROBE_BEGIN"):
            if marker not in raw:
                raise SystemExit(f"HWTEST8 binary marker missing: {marker!r}")

    syms = sym.read_text(encoding="utf-8", errors="replace")
    for token in FORBIDDEN_SYMBOL_TOKENS:
        if token in syms:
            raise SystemExit(f"forbidden MD/LAN1 symbol leaked into link: {token}")

    cfg = config.read_text(encoding="utf-8")
    for name in FORBIDDEN_CONFIG_Y:
        if re.search(rf"^{re.escape(name)}=y$", cfg, re.M):
            raise SystemExit(f"forbidden config enabled: {name}=y")
    for name in REQUIRED_CONFIG_Y:
        if not re.search(rf"^{re.escape(name)}=y$", cfg, re.M):
            raise SystemExit(f"required MF recovery config missing: {name}=y")
    if 'CONFIG_DEFAULT_DEVICE_TREE="an7583-nokia-xg-040g-mf"' not in cfg:
        raise SystemExit("wrong MF default device tree")

    env_text = env.read_text(encoding="utf-8")
    if not re.search(r"^bootcmd=ursusweb$", env_text, re.M):
        raise SystemExit("MF bootcmd is not ursusweb")
    if re.search(r"saveenv|mtd\s+(?:erase|write)|ubi\s+(?:write|create|remove|rename|detach)", env_text):
        raise SystemExit("persistent command leaked into MF default environment")

    fip_data = fip.read_bytes()
    _serial, _flags, entries = parse_fip(fip_data)
    if len(entries) != 2:
        raise SystemExit(f"MF RAM FIP must contain recovery BL31+BL33 only, got {len(entries)} entries")
    payloads = [fip_data[o:o + s] for _uuid, o, s, _eflags in entries]
    bl31, bl33 = payloads
    if sha256(bl31) != EXPECTED_BL31_COMPRESSED_SHA256:
        raise SystemExit(f"BL31 compressed bytes changed: {sha256(bl31)}")
    try:
        decoded = lzma.decompress(bl33, format=lzma.FORMAT_ALONE)
    except lzma.LZMAError as exc:
        raise SystemExit(f"BL33 LZMA decode failed: {exc}") from exc
    if decoded != raw:
        raise SystemExit(f"BL33 does not round-trip to u-boot.bin decoded={sha256(decoded)} raw={sha256(raw)}")
    if len(bl33) < 13 or struct.unpack_from("<Q", bl33, 5)[0] != len(raw):
        raise SystemExit("BL33 LZMA known-size header mismatch")

    report = json.loads(report_path.read_text(encoding="ascii"))
    expected_report = {
        "entry_count": 2,
        "bl31_byte_exact": True,
        "mf2_bl33_roundtrip": True,
        "mf2_bl33_lzma_known_size": True,
        "mf2_bl33_lzma_eopm": False,
        "serial_preserved": True,
        "flags_preserved": True,
        "uuid_flags_preserved": True,
    }
    for key, expected in expected_report.items():
        if report.get(key) != expected:
            raise SystemExit(f"FIP report mismatch {key}={report.get(key)!r} expected={expected!r}")
    if report.get("output_sha256") != sha256(fip_data):
        raise SystemExit("FIP report/output SHA mismatch")
    if report.get("bl31_compressed_sha256") != EXPECTED_BL31_COMPRESSED_SHA256:
        raise SystemExit("FIP report BL31 SHA mismatch")
    if report.get("mf2_bl33_raw_sha256") != sha256(raw):
        raise SystemExit("FIP report raw BL33 SHA mismatch")
    if report.get("mf2_bl33_compressed_sha256") != sha256(bl33):
        raise SystemExit("FIP report compressed BL33 SHA mismatch")

    result = {
        "result": "PASS",
        "mode": "RAM_RECOVERY",
        "target": "Nokia XG-040G-MF / Airoha AN7583",
        "version": "0.1.0-TEST61",
        "preloader_size": len(pre),
        "preloader_sha256": sha256(pre),
        "fip_size": len(fip_data),
        "fip_sha256": sha256(fip_data),
        "bl31_compressed_sha256": sha256(bl31),
        "bl33_compressed_sha256": sha256(bl33),
        "uboot_size": len(raw),
        "uboot_sha256": sha256(raw),
        "fip_entries": 2,
        "bl31_byte_exact": True,
        "bl33_roundtrip": True,
        "serial_xmodem_receive": "ENABLED_CONFIG_CMD_LOADB",
        "raw_mtd_cli": "ENABLED_CONFIG_CMD_MTD",
        "ursus_high_level_persistent_entrypoints": "HARD_REJECT_EROFS",
        "persistent_env": "NOWHERE",
        "md_board_identity": "ABSENT",
        "md_stockbridge": "NOT_LINKED",
        "recovery_ports": "LAN2_LAN3_LAN4_AN7583_INTERNAL_GPHY" if hwtest8 else "LAN2_LAN3_AN7583_INTERNAL_GPHY",
        "lan1_en8811": "NOT_LINKED_OUT_OF_SCOPE",
    }
    (outdir / "MF-INDEPENDENT-AUDIT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print("MF_RAM_RECOVERY_ARTIFACT_AUDIT=PASS")
    for key, value in result.items():
        print(f"{key}={value}")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", type=Path)
    args = ap.parse_args()
    audit(args.outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

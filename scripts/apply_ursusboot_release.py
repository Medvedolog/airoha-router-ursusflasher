#!/usr/bin/env python3
"""Put an airoha-ursusboot release (MD + MF, one exact commit) into a kit tree.

Inputs are the dist/<board>/ directories produced by airoha-ursusboot's
scripts/ci/build-release.sh at the commit pinned in config/URSUSBOOT_PIN.json.
Fails closed unless both boards come from exactly that commit and version, every
file matches its PROVENANCE.json digest, and each UrsusBoot build has the
packaged UBI preloader compiled in. Writes data/URSUSBOOT_RELEASE.json, which
the host reads (ursusflasher/src/ursusboot_release.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import shutil
import struct
from pathlib import Path

FIP_TOC_NAME = 0xAA640001
TB_FW_UUID = bytes.fromhex("5ff9ec0b4d223e4da544c39d81c73f0a")

# Kit layout: what the host already looks for.
LAYOUT = {
    "md": {
        "update_fip": ("ursusboot-update.fip", "data/payloads/md/ursusboot/ursusboot-md-{v}-update.fip"),
        "u_boot_bin": ("u-boot.bin", "data/payloads/md/ursusboot/ursusboot-md-{v}-u-boot.bin"),
        "install_mtd0": ("ursusboot-install-mtd0.bin", "data/payloads/md/ursusboot/ursusboot-md-{v}-install-mtd0.bin"),
        # Own name: openwrt-airoha-an7581-nokia_xg-040g-md-ubi-preloader.bin is the proven RC
        # preloader that UART repair (items 5/9) and the bootrom backup require by SHA256.
        "ubi_preloader": ("ursusboot-ubi-preloader.fip", "data/payloads/md/ursusboot/ursusboot-md-{v}-ubi-preloader.fip"),
        # TEST64+: the one Vanilla OpenWrt U-Boot FIP this UrsusBoot may install (item 4 last leg).
        "vanilla_fip": ("vanilla-u-boot.fip", "data/payloads/md/vanilla/vanilla-u-boot-md-{v}.fip"),
        # t66+: Fudan-capable RECOVERY_SAFE RAM U-Boot for BootROM/UART recovery (RC18 FIP, same BL31).
        "recovery_safe_fip": ("recovery-safe-u-boot.fip", "data/recovery/recovery-safe-u-boot-md-{v}.fip"),
    },
    "mf": {
        "update_fip": ("ursusboot-update.fip", "data/payloads/mf/ursusboot/ursusboot-mf-{v}-update.fip"),
        "runtime_lzma": ("u-boot.runtime.lzma", "data/payloads/mf/ursusboot/u-boot.runtime.lzma"),
        "u_boot_bin": ("u-boot.bin", "data/payloads/mf/ursusboot/ursusboot-mf-{v}-u-boot.bin"),
        "runtime_ram_fip": ("ursusboot-runtime-ram.fip", "data/payloads/mf/recovery/ursusboot-mf-{v}-runtime-ram.fip"),
        "uart_preloader": ("ursusboot-uart-preloader.bin", "data/payloads/mf/recovery/ursusboot-mf-{v}-uart-preloader.bin"),
        "ubi_preloader": ("ursusboot-ubi-preloader.fip", "data/payloads/mf/ursusboot/ursusboot-mf-{v}-ubi-preloader.fip"),
        "vanilla_fip": ("vanilla-u-boot.fip", "data/payloads/mf/vanilla/vanilla-u-boot-mf-{v}.fip"),
        "recovery_safe_fip": ("recovery-safe-u-boot.fip", "data/recovery/mf/recovery-safe-u-boot-mf-{v}.fip"),
    },
}
BOARD_PROFILE = {"md": "xg040-md", "mf": "xg040-mf"}
# BL31 of the MedveFlasher RC18 RECOVERY_SAFE FIP each board's RAM U-Boot is packed into
# (proven_backend BACKUP_RECOVERY_BL31_COMPRESSED_SHA / MF_RECOVERY_BL31_COMPRESSED_SHA).
RC18_BL31 = {"md": "a81dbbe98acb1dabc2afcbf72e73ad87e24efa8dd88e559612a024c28ece920e",
             "mf": "6d97815b5cdf905eff874062f9364ebe41a2a11f4b25944a82aea4fcbdd71e35"}
COMPATIBLE = {"md": b"nokia,xg-040g-md", "mf": b"nokia,xg-040g-mf"}
# Superseded UrsusBoot builds that must not remain installable next to the release.
STALE = {
    "md-recovery": ("data/recovery", ("recovery-safe-u-boot-md-*.fip",)),
    "mf-recovery": ("data/recovery/mf", ("recovery-safe-u-boot-mf-*.fip",)),
    "md": ("data/payloads/md/ursusboot", ("*TEST61*.fip", "*TEST62*.fip", "*TEST63*.fip", "*TEST61*-u-boot.bin", "*TEST63*-u-boot.bin", "*TEST63*.bin", "*UBIUX1-TEST64*", "*-alpha5-t64-*", "*-alpha5-t65-*", "*-alpha5-t66-*", "*-alpha5-t67-*", "*-alpha5-t68-*", "*-alpha5-t69-*", "*-alpha5-t70-*", "*-alpha5-t71-*")),
    "mf": ("data/payloads/mf/recovery", ("*TEST61*", "*TEST62*", "*TEST63*", "*UBIUX1-TEST64*", "*-alpha5-t64-*", "*-alpha5-t65-*", "*-alpha5-t66-*", "*-alpha5-t67-*", "*-alpha5-t68-*", "*-alpha5-t69-*", "*-alpha5-t70-*", "*-alpha5-t71-*")),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tb_fw_payload(fip: bytes) -> bytes:
    if len(fip) < 16 or struct.unpack_from("<I", fip, 0)[0] != FIP_TOC_NAME:
        raise RuntimeError("UBI preloader is not a FIP")
    entries, pos = [], 16
    while True:
        uuid = fip[pos:pos + 16]
        off, size, _flags = struct.unpack_from("<QQQ", fip, pos + 16)
        pos += 40
        if uuid == bytes(16):
            break
        entries.append((uuid, off, size))
    if len(entries) != 1 or entries[0][0] != TB_FW_UUID or entries[0][1] + entries[0][2] > len(fip):
        raise RuntimeError("UBI preloader must be a FIP with exactly one TB_FW entry")
    return fip[entries[0][1]:entries[0][1] + entries[0][2]]


def bl2_candidate_sha(preloader: bytes) -> str:
    img = b"\xff" * 0x800 + preloader
    return hashlib.sha256(img + b"\xff" * (0x20000 - len(img))).hexdigest()


def fip_entries(fip: bytes) -> list[bytes]:
    if len(fip) < 16 or struct.unpack_from("<I", fip, 0)[0] != FIP_TOC_NAME:
        raise RuntimeError("not a FIP")
    out, pos = [], 16
    while True:
        uuid = fip[pos:pos + 16]
        off, size, _flags = struct.unpack_from("<QQQ", fip, pos + 16)
        pos += 40
        if uuid == bytes(16):
            return out
        if off + size > len(fip):
            raise RuntimeError("FIP entry outside the file")
        out.append(fip[off:off + size])


def check_recovery_safe(fam: str, dist: Path, prov: dict) -> None:
    """BootROM/UART RAM U-Boot: RC18 FIP shape + BL31, Fudan FM25G02B, RC18 safe env."""
    rs = dist / "recovery-safe-u-boot.fip"
    if not rs.is_file() or not prov.get("recovery_safe_fip_sha256"):
        raise RuntimeError(f"{fam}: release has no RECOVERY_SAFE RAM U-Boot (t66+ required)")
    fip = rs.read_bytes()
    entries = fip_entries(fip)
    if len(entries) != 2:
        raise RuntimeError(f"{fam}: RECOVERY_SAFE FIP must be exactly BL31+BL33")
    bl31, bl33 = entries
    if hashlib.sha256(fip).hexdigest() != prov["recovery_safe_fip_sha256"] or len(fip) != prov["recovery_safe_fip_size"]:
        raise RuntimeError(f"{fam}: RECOVERY_SAFE FIP disagrees with PROVENANCE.json")
    if hashlib.sha256(bl31).hexdigest() != RC18_BL31[fam] or prov["recovery_safe_bl31_sha256"] != RC18_BL31[fam]:
        raise RuntimeError(f"{fam}: RECOVERY_SAFE BL31 is not the RC18 BL31")
    if hashlib.sha256(bl33).hexdigest() != prov["recovery_safe_bl33_sha256"]:
        raise RuntimeError(f"{fam}: RECOVERY_SAFE BL33 disagrees with PROVENANCE.json")
    if len(bl33) < 13 or bl33[0] != 0x5D or struct.unpack_from("<Q", bl33, 5)[0] in (0, 2**64 - 1):
        raise RuntimeError(f"{fam}: RECOVERY_SAFE BL33 is not known-size LZMA-Alone")
    raw = lzma.decompress(bl33, format=lzma.FORMAT_ALONE)
    if raw != (dist / "recovery-safe-u-boot.bin").read_bytes():
        raise RuntimeError(f"{fam}: RECOVERY_SAFE BL33 does not decompress to recovery-safe-u-boot.bin")
    for marker in (b"U-Boot 2026.07", b"FM25G02B", b"medveflasher_recovery_safe=rc18", b"bootdelay=-1",
                   b"bootcmd=echo RECOVERY_SAFE_RC18", b"RCSAFE00", COMPATIBLE[fam]):
        if marker not in raw:
            raise RuntimeError(f"{fam}: RECOVERY_SAFE U-Boot lacks {marker.decode()}")
    for marker in (b"UrsusBoot-", b"ursusdispatch", COMPATIBLE["mf" if fam == "md" else "md"]):
        if marker in raw:
            raise RuntimeError(f"{fam}: RECOVERY_SAFE U-Boot unexpectedly contains {marker.decode()}")


def load_board(fam: str, dist: Path, pin: dict) -> dict:
    prov = json.loads((dist / "PROVENANCE.json").read_text(encoding="utf-8"))
    want = {"repo": pin["repo"], "commit": pin["commit"], "board": BOARD_PROFILE[fam]}
    for key, value in want.items():
        if prov.get(key) != value:
            raise RuntimeError(f"{fam}: PROVENANCE {key}={prov.get(key)!r}, pinned {value!r}")
    if pin.get("version") and prov.get("version") != pin["version"]:
        raise RuntimeError(f"{fam}: PROVENANCE version {prov.get('version')!r}, pinned {pin['version']!r}")
    for name, digest in prov["files"].items():
        if sha256(dist / name) != digest:
            raise RuntimeError(f"{fam}: {name} does not match PROVENANCE.json")
    pre = (dist / "ursusboot-ubi-preloader.fip").read_bytes()
    tb_fw_payload(pre)
    if hashlib.sha256(pre).hexdigest() != prov["ubi_preloader_sha256"] or bl2_candidate_sha(pre) != prov["ubi_bl2_image_sha256"]:
        raise RuntimeError(f"{fam}: UBI preloader digests disagree with PROVENANCE.json")
    bl33 = (dist / "u-boot.bin").read_bytes()
    if fam == "mf":
        runtime_lzma = (dist / "u-boot.runtime.lzma").read_bytes()
        if lzma.decompress(runtime_lzma, format=lzma.FORMAT_ALONE) != bl33:
            raise RuntimeError("mf: u-boot.runtime.lzma does not decompress to u-boot.bin")
        update_fip = dist / "ursusboot-update.fip"
        if not update_fip.is_file():
            raise RuntimeError("mf: canonical persistent repair ursusboot-update.fip is missing (t70+ required)")
        if sha256(update_fip) != prov.get("ursusboot_update_fip_sha256"):
            raise RuntimeError("mf: ursusboot-update.fip disagrees with PROVENANCE.json")
        entries = fip_entries(update_fip.read_bytes())
        if len(entries) != 2 or entries[-1] != runtime_lzma:
            raise RuntimeError("mf: persistent repair FIP BL33 is not the pinned u-boot.runtime.lzma")
        if prov.get("persistent_fip_bl33_sha256") != hashlib.sha256(runtime_lzma).hexdigest():
            raise RuntimeError("mf: persistent repair BL33 digest disagrees with PROVENANCE.json")
    # UrsusBoot memcmp()s the uploaded preloader against these compiled-in arrays.
    for digest in (prov["ubi_preloader_sha256"], prov["ubi_bl2_image_sha256"]):
        if bytes.fromhex(digest) not in bl33:
            raise RuntimeError(f"{fam}: UrsusBoot is not built for the packaged preloader ({digest})")
    if prov["version"].encode() not in bl33:
        raise RuntimeError(f"{fam}: u-boot.bin does not identify {prov['version']}")
    # UrsusBoot memcmp()s the uploaded Vanilla FIP against this compiled-in array.
    van = dist / "vanilla-u-boot.fip"
    if not van.is_file() or not prov.get("vanilla_fip_sha256"):
        raise RuntimeError(f"{fam}: release has no pinned Vanilla FIP (TEST64+ required)")
    if sha256(van) != prov["vanilla_fip_sha256"] or bytes.fromhex(prov["vanilla_fip_sha256"]) not in bl33:
        raise RuntimeError(f"{fam}: Vanilla FIP is not the one pinned into this UrsusBoot")
    check_recovery_safe(fam, dist, prov)
    return prov


def set_preloader_role(tree: Path, fam: str, rel: str, digest: str, size: int, provenance: str) -> None:
    targets = [(tree / "data" / "FIRMWARE_BUNDLES.json", lambda m: m["profiles"][fam]["files"])]
    if fam == "md":
        targets.append((tree / "data" / "FIRMWARE_BUNDLE.json", lambda m: m["files"]))
    for path, files_of in targets:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        hits = [f for f in files_of(manifest) if f.get("role") == "STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE"]
        if len(hits) != 1:
            raise RuntimeError(f"{path.name}: {fam} needs exactly one STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE")
        hits[0].update({"path": rel, "sha256": digest, "size": size, "provenance": provenance})
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def apply_release(tree: Path, md_dist: Path, mf_dist: Path, pin_path: Path) -> dict:
    tree = tree.resolve()
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    if len(pin.get("commit", "")) != 40:
        raise RuntimeError("config/URSUSBOOT_PIN.json must name a full 40-hex commit")
    provs = {"md": load_board("md", md_dist.resolve(), pin), "mf": load_board("mf", mf_dist.resolve(), pin)}
    if provs["md"]["version"] != provs["mf"]["version"]:
        raise RuntimeError("MD and MF UrsusBoot versions differ")
    version = provs["md"]["version"]

    release = {"schema": 1, "repo": pin["repo"], "commit": pin["commit"], "version": version, "boards": {}}
    for fam, dist in (("md", md_dist.resolve()), ("mf", mf_dist.resolve())):
        for key in (fam, f"{fam}-recovery"):
            base, patterns = STALE[key]
            for pattern in patterns:
                for stale in (tree / base).glob(pattern):
                    stale.unlink()
        files = {}
        for role, (src_name, dst_tmpl) in LAYOUT[fam].items():
            dst = tree / dst_tmpl.format(v=version)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dist / src_name, dst)
            files[role] = {"path": dst.relative_to(tree).as_posix(), "sha256": sha256(dst), "size": dst.stat().st_size}
        pre = files["ubi_preloader"]
        set_preloader_role(tree, fam, pre["path"], pre["sha256"], pre["size"],
                           f"airoha-ursusboot {pin['commit'][:12]} fast BL2")
        prov_dst = tree / "data" / "ursusboot-provenance" / f"{fam}.json"
        prov_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dist / "PROVENANCE.json", prov_dst)
        release["boards"][fam] = {
            "version": version,
            "board": BOARD_PROFILE[fam],
            "ubi_preloader_sha256": provs[fam]["ubi_preloader_sha256"],
            "ubi_bl2_image_sha256": provs[fam]["ubi_bl2_image_sha256"],
            "atf_source_version": provs[fam]["atf_source_version"],
            "openwrt_ref": provs[fam]["openwrt_ref"],
            "vanilla_fip_sha256": provs[fam]["vanilla_fip_sha256"],
            "vanilla_uboot_variant": provs[fam].get("vanilla_uboot_variant", ""),
            "recovery_safe_bl31_sha256": provs[fam]["recovery_safe_bl31_sha256"],
            "recovery_safe_bl33_sha256": provs[fam]["recovery_safe_bl33_sha256"],
            "files": files,
        }

    # Legacy MD item4 descriptor, still read by older ursusboot_install code paths.
    md = release["boards"]["md"]["files"]
    (tree / "data" / "ITEM4_TEMP_URSUSBOOT.json").write_text(json.dumps({
        "schema": 1,
        "role": "TEMPORARY_ITEM4_URSUSBOOT",
        "version": version,
        "fip_path": md["update_fip"]["path"],
        "fip_size": md["update_fip"]["size"],
        "fip_sha256": md["update_fip"]["sha256"],
        "raw_bl33_sha256": md["u_boot_bin"]["sha256"],
        "provenance": f"{pin['repo']}@{pin['commit']}",
    }, indent=2) + "\n", encoding="utf-8", newline="\n")
    caps = tree / "data" / "FIRMWARE_CAPABILITIES.json"
    if caps.is_file():
        c = json.loads(caps.read_text(encoding="utf-8"))
        for container in [c] + [v for v in c.values() if isinstance(v, dict)]:
            if "URSUSBOOT_VERSION" in container:
                container["URSUSBOOT_VERSION"] = version
        caps.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (tree / "data" / "URSUSBOOT_RELEASE.json").write_text(json.dumps(release, indent=2) + "\n",
                                                            encoding="utf-8", newline="\n")
    (tree / "URSUSBOOT_PROVENANCE.txt").write_text(
        f"URSUSBOOT_REPO={pin['repo']}\nURSUSBOOT_COMMIT={pin['commit']}\nURSUSBOOT_VERSION={version}\n"
        + "".join(f"{fam.upper()}_UBI_PRELOADER_SHA256={b['ubi_preloader_sha256']}\n"
                  f"{fam.upper()}_UBI_BL2_IMAGE_SHA256={b['ubi_bl2_image_sha256']}\n"
                  f"{fam.upper()}_VANILLA_FIP_SHA256={b['vanilla_fip_sha256']}\n"
                  f"{fam.upper()}_RECOVERY_SAFE_FIP_SHA256={b['files']['recovery_safe_fip']['sha256']}\n"
                  for fam, b in release["boards"].items()),
        encoding="utf-8", newline="\n")
    return release


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True)
    ap.add_argument("--md", required=True, help="airoha-ursusboot dist/xg040-md")
    ap.add_argument("--mf", required=True, help="airoha-ursusboot dist/xg040-mf")
    ap.add_argument("--pin", required=True, help="config/URSUSBOOT_PIN.json")
    args = ap.parse_args()
    apply_release(Path(args.tree), Path(args.md), Path(args.mf), Path(args.pin))


if __name__ == "__main__":
    main()

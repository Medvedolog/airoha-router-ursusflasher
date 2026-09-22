#!/usr/bin/env python3
"""Verify a canonical UrsusFlasher operator ZIP against the exact TEST62 CI artifacts.

Fails (non-zero exit) unless the ZIP contains, for MD (--artifacts) and, for a
two-target kit, MF (--mf-artifacts): exactly the TEST62 UrsusBoot build and the
fast BL2 preloader it was compiled to accept; plus only the canonical
launchers, runtime in data/, the _poll() /api/status-loss fix, backup reuse and
the OpenWrt UBI sysupgrade routes.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import lzma
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_md_test62_overlay import (  # noqa: E402
    CANONICAL_PRELOADER,
    FAST_BL2_NAME,
    FIP_NAME,
    TEST62_VERSION,
    tb_fw_payload,
)
import apply_mf_test62_overlay as mf  # noqa: E402

MD_OLD_PRELOADER_SHA = "6c3b2339d036340396730a13adfe35c0d2a4dddedeffb6f9965a24e0c7908808"
MF_OLD_PRELOADER_SHA = "778d10a65276085b70bec005248fc87ec208b43b0239502f15ade20fe528301e"

LAUNCHERS = {"START_ONECLICK.cmd", "START_ONECLICK.sh", "START_EXPERT.cmd", "START_EXPERT.sh"}
RUNTIME = (
    "one_key.py", "expert.py", "expert_airoha.py", "ursusboot_pregnant.py",
    "ursus_web_client.py", "ursusboot_install.py", "proven_backend.py",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


NT_FW_UUID = bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4")


def fip_entry(fip: bytes, uuid: bytes) -> bytes:
    pos = 16
    while pos + 40 <= len(fip):
        u = fip[pos:pos + 16]
        off, size, _flags = struct.unpack_from("<QQQ", fip, pos + 16)
        if u == bytes(16):
            break
        if u == uuid:
            return fip[off:off + size]
        pos += 40
    raise SystemExit(f"FAIL FIP entry {uuid.hex()} not found")


def check(cond: bool, label: str, detail: str = "") -> None:
    if not cond:
        raise SystemExit(f"FAIL {label}{': ' + detail if detail else ''}")
    print(f"PASS {label}{': ' + detail if detail else ''}")


def verify_layout(root: Path) -> None:
    starts = {p.name for p in root.iterdir() if p.name.upper().startswith("START")}
    check(starts == LAUNCHERS, "launchers", ",".join(sorted(starts)))
    stray = sorted(p.name for p in root.iterdir() if p.is_file() and p.suffix == ".py")
    check(not stray, "no runtime at kit root", ",".join(stray) or "none")
    missing = [n for n in RUNTIME if not (root / "data" / n).is_file()]
    check(not missing, "runtime in data/", ",".join(missing) or "all present")


def verify_checksums(root: Path) -> None:
    rows = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    bad = []
    for row in rows:
        if not row.strip():
            continue
        want, rel = row.split(None, 1)
        p = root / rel.strip().lstrip("*")
        if not p.is_file() or sha256(p) != want:
            bad.append(rel)
    check(not bad and rows, "SHA256SUMS", f"{len(rows)} entries" if not bad else ",".join(bad[:5]))


def verify_test62(root: Path, art: Path) -> None:
    info = (art / "TEST62-BUILD_INFO.txt").read_text(encoding="utf-8", errors="replace")
    check(TEST62_VERSION in info, "artifact identifies TEST62")
    check("ATF_FASTPATH_BL2=PASS" in info, "artifact fast BL2 patch marker")

    ub = root / "data" / "payloads" / "md" / "ursusboot"
    fip = ub / FIP_NAME
    check(fip.is_file(), "TEST62 FIP present", fip.name)
    check(sha256(fip) == sha256(art / FIP_NAME), "TEST62 FIP == artifact", sha256(fip))
    # BL33 in the FIP is LZMA-compressed: identify TEST62 on the raw BL33 and
    # prove the FIP's NT_FW entry carries exactly that build's u-boot.lzma.
    check(TEST62_VERSION.encode() in (art / "u-boot.bin").read_bytes(),
          "artifact u-boot.bin identifies TEST62")
    nt = fip_entry(fip.read_bytes(), NT_FW_UUID)
    lz = (art / "u-boot.lzma").read_bytes()
    check(nt[:len(lz)] == lz and not nt[len(lz):].strip(b"\x00\xff"), "FIP NT_FW == artifact u-boot.lzma",
          f"{len(lz)} bytes")
    old = sorted(p.name for p in ub.glob("*TEST61*"))
    check(not old, "no TEST61 FIP left", ",".join(old) or "none")

    temp = json.loads((root / "data" / "ITEM4_TEMP_URSUSBOOT.json").read_text(encoding="utf-8"))
    check(temp.get("version") == TEST62_VERSION, "ITEM4_TEMP version", str(temp.get("version")))
    check(temp.get("fip_path") == f"data/payloads/md/ursusboot/{FIP_NAME}", "ITEM4_TEMP fip_path")
    check(temp.get("fip_sha256") == sha256(fip), "ITEM4_TEMP fip_sha256")
    check(temp.get("raw_bl33_sha256") == sha256(art / "u-boot.bin"), "ITEM4_TEMP raw_bl33_sha256")

    pre = ub / CANONICAL_PRELOADER
    art_bl2 = (art / FAST_BL2_NAME).read_bytes()
    try:
        art_bl2 = tb_fw_payload(art_bl2)
    except RuntimeError:
        pass  # artifact carries the raw BL2
    packed_bl2 = tb_fw_payload(pre.read_bytes())
    check(packed_bl2 == art_bl2, "preloader = FIP{TB_FW = TEST62 fast BL2 from artifact}",
          hashlib.sha256(packed_bl2).hexdigest())
    want = sha256(pre)
    bl33 = (art / "u-boot.bin").read_bytes()
    check(bytes.fromhex(want) in bl33 and bytes.fromhex(MD_OLD_PRELOADER_SHA) not in bl33
          and MD_OLD_PRELOADER_SHA.encode() not in bl33,
          "MD TEST62 BL33 pinned to the packaged fast preloader", want)
    manifest = json.loads((root / "data" / "FIRMWARE_BUNDLE.json").read_text(encoding="utf-8"))
    hit = [f for f in manifest["files"] if f.get("role") == "STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE"]
    check(len(hit) == 1 and hit[0].get("sha256") == want and hit[0].get("provenance") == "TEST62 fast BL2",
          "FIRMWARE_BUNDLE preloader role -> TEST62 fast BL2", want)
    check_bundles_role(root, "md", want)
    versions = {(root / "VERSION").read_text(encoding="utf-8").strip(),
                (root / "data" / "VERSION").read_text(encoding="utf-8").strip()}
    check(len(versions) == 1 and TEST62_VERSION not in versions, "kit VERSION intact", ",".join(versions))


def check_bundles_role(root: Path, family: str, want: str) -> None:
    bundles = json.loads((root / "data" / "FIRMWARE_BUNDLES.json").read_text(encoding="utf-8"))
    hit = [f for f in bundles["profiles"][family]["files"] if f.get("role") == "STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE"]
    check(len(hit) == 1 and hit[0].get("sha256") == want, f"FIRMWARE_BUNDLES {family} preloader role", want)


def verify_mf(root: Path, art: Path) -> None:
    pay = root / "data" / "payloads" / "mf"
    info = (art / mf.BUILD_INFO).read_text(encoding="utf-8", errors="replace")
    check(f"UrsusBoot {mf.MF_VERSION}" in info, "MF artifact identifies TEST62 runtime")
    runtime = pay / "ursusboot" / mf.RUNTIME
    check(sha256(runtime) == sha256(art / mf.RUNTIME), "MF runtime lzma == artifact", sha256(runtime))
    bl33 = (art / "u-boot.bin").read_bytes()
    check(lzma.decompress(runtime.read_bytes(), format=lzma.FORMAT_ALONE) == bl33,
          "MF runtime lzma decompresses to artifact u-boot.bin")
    check(mf.MF_VERSION.encode() in bl33 and b"Nokia XG-040G-MF" in bl33, "MF BL33 identity TEST62 / XG-040G-MF")
    for name in (mf.RAM_FIP, mf.UART_PRELOADER):
        check(sha256(pay / "recovery" / name) == sha256(art / name), f"MF recovery {name} == artifact")
    old = sorted(p.name for p in pay.rglob("*TEST61*"))
    check(not old, "no MF TEST61 payloads left", ",".join(old) or "none")

    pre = pay / "proven" / mf.CANONICAL_PRELOADER
    art_bl2 = (art / mf.FAST_BL2_NAME).read_bytes()
    try:
        art_bl2 = tb_fw_payload(art_bl2)
    except RuntimeError:
        pass
    packed = tb_fw_payload(pre.read_bytes())
    check(packed == art_bl2, "MF preloader = FIP{TB_FW = MF fast BL2 from artifact}", hashlib.sha256(packed).hexdigest())
    want = sha256(pre)
    check(bytes.fromhex(want) in bl33 and bytes.fromhex(MF_OLD_PRELOADER_SHA) not in bl33
          and MF_OLD_PRELOADER_SHA.encode() not in bl33,
          "MF TEST62 runtime pinned to the packaged fast preloader", want)
    check_bundles_role(root, "mf", want)


def verify_multi(root: Path, families: tuple[str, ...]) -> None:
    okm = importlib.import_module("one_key_multi")
    for fam in families:
        for role in ("OPENWRT_UBI_SYSUPGRADE", "STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE"):
            p = Path(okm.require_role(fam, role)).resolve()
            check(root.resolve() in p.parents, f"one_key_multi.require_role({fam}, {role})",
                  p.relative_to(root.resolve()).as_posix())
    if "mf" in families:
        compat = importlib.import_module("mf_uart_test62_compat")
        prof = compat.family_profile("mf")
        check(prof["preloader"].name == mf.UART_PRELOADER and prof["fip"].name == mf.RAM_FIP
              and root.resolve() in prof["fip"].parents, "MF UART recovery resolves to kit TEST62 pair")


def verify_runtime(root: Path) -> None:
    data = root / "data"
    sys.path.insert(0, str(data))
    one_key = importlib.import_module("one_key")
    for role in ("OPENWRT_UBI_SYSUPGRADE", "STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE"):
        p = Path(one_key.require_bundle_role(role)).resolve()
        check(root.resolve() in p.parents, f"require_bundle_role({role})", p.relative_to(root.resolve()).as_posix())
    ubi = Path(one_key.require_bundle_role("OPENWRT_UBI_SYSUPGRADE"))
    check(ubi.name.endswith("-md-ubi-squashfs-sysupgrade.itb"), "OpenWrt UBI sysupgrade image", ubi.name)

    ui = importlib.import_module("ursusboot_install")
    check(ui.TARGET_URSUS == TEST62_VERSION and ui.PAYLOAD.name == FIP_NAME,
          "ursusboot_install targets TEST62", f"{ui.TARGET_URSUS} {ui.PAYLOAD.name}")

    route = (data / "ursusboot_pregnant.py").read_text(encoding="utf-8")
    for needle in (
        'one_key.require_bundle_role("OPENWRT_UBI_SYSUPGRADE")',
        'one_key.require_bundle_role("STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE")',
        'uw.update_firmware(',
        'preloader=preloader',
    ):
        check(needle in route, "STOCK->UBI route", needle)
    for needle in ('verify_stock_restore_backup', 'skip_full_backup=reuse_backup'):
        check(needle in route, "backup reuse", needle)

    verify_poll(importlib.import_module("ursus_web_client"))


def verify_poll(uw) -> None:
    """Functional: _poll() must survive /api/status 404 during an active operation."""
    uw.time.sleep = lambda _s: None

    def run(status_script, log_text):
        calls = {"status": 0}

        def fake_request(host, method, path, **_kw):
            if path == "/api/status":
                i = calls["status"]
                calls["status"] += 1
                code, body = status_script[min(i, len(status_script) - 1)]
                return code, {}, json.dumps(body).encode() if isinstance(body, dict) else body
            if path == "/api/log":
                return 200, {}, log_text.encode()
            return 404, {}, b"not found"

        uw._request = fake_request
        return uw._poll("192.0.2.1", bootloader=False, timeout=30)

    active = {"product": "UrsusBoot", "operation_active": True, "operation_stage": "UBI", "operation_percent": 50}
    done = {"product": "UrsusBoot", "operation_active": False, "operation_complete": True,
            "operation_stage": "COMPLETE", "operation_percent": 100}
    r = run([(200, active), (404, b"not found"), (404, b"not found"), (200, done)], "")
    check(bool(r.get("operation_complete")), "_poll survives /api/status 404 then status COMPLETE")
    r = run([(200, active), (404, b"not found")], "... UBI: 100% - COMPLETE\n")
    check(r.get("status_source") == "api-log-fallback", "_poll /api/status 404 + /api/log COMPLETE fallback")
    try:
        run([(200, active), (404, b"not found")], "URSUS_UBI_MIGRATION_FAILED\n")
    except uw.UrsusWebError:
        check(True, "_poll /api/status 404 + /api/log FAILED is an error")
    else:
        check(False, "_poll /api/status 404 + /api/log FAILED is an error")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--artifacts", required=True, help="MD TEST62 + fast BL2 artifact dir")
    ap.add_argument("--mf-artifacts", default=None, help="MF TEST62 + fast BL2 artifact dir (two-target kit)")
    args = ap.parse_args()
    art = Path(args.artifacts).resolve()
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(args.zip) as z:
            z.extractall(td)
        tops = [p for p in Path(td).iterdir()]
        check(len(tops) == 1 and tops[0].is_dir(), "single top-level kit dir", tops[0].name if tops else "")
        root = tops[0]
        verify_layout(root)
        verify_checksums(root)
        verify_test62(root, art)
        families = ("md",)
        if args.mf_artifacts:
            verify_mf(root, Path(args.mf_artifacts).resolve())
            families = ("md", "mf")
        else:
            check(not (root / "data" / "payloads" / "mf").exists(), "MD-only kit carries no MF payloads")
        verify_runtime(root)
        verify_multi(root, families)
    print("verify_test62_kit: PASS families=" + ",".join(families))


if __name__ == "__main__":
    main()

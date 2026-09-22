#!/usr/bin/env python3
"""Verify a canonical MD direct item4 operator ZIP against the exact TEST62 artifact.

Fails (non-zero exit) unless the ZIP contains exactly the TEST62 FIP and the
TEST62 fast BL2 from --artifacts, only the canonical launchers, runtime in
data/, the _poll() /api/status-loss fix, backup reuse and the OpenWrt UBI
sysupgrade route.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
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
    manifest = json.loads((root / "data" / "FIRMWARE_BUNDLE.json").read_text(encoding="utf-8"))
    hit = [f for f in manifest["files"] if f.get("role") == "STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE"]
    check(len(hit) == 1 and hit[0].get("sha256") == want and hit[0].get("provenance") == "TEST62 fast BL2",
          "FIRMWARE_BUNDLE preloader role -> TEST62 fast BL2", want)
    versions = {(root / "VERSION").read_text(encoding="utf-8").strip(),
                (root / "data" / "VERSION").read_text(encoding="utf-8").strip()}
    check(len(versions) == 1 and TEST62_VERSION not in versions, "kit VERSION intact", ",".join(versions))


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
    ap.add_argument("--artifacts", required=True)
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
        verify_runtime(root)
    print("verify_md_item4_kit: PASS")


if __name__ == "__main__":
    main()

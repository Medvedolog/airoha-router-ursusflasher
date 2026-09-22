#!/usr/bin/env python3
"""Verify the canonical MD+MF operator ZIP against the pinned airoha-ursusboot release.

Fails (non-zero exit) unless: only the canonical launchers and runtime in data/;
SHA256SUMS holds; data/URSUSBOOT_RELEASE.json names exactly the pinned
repo/commit/version; every released file is byte-identical to the
airoha-ursusboot dist/ it came from; each board's UrsusBoot accepts the packaged
UBI preloader; every host consumer (ONE-CLICK, EXPERT, web/TFTP/XMODEM FIP
update, item4 install, MF UART recovery) resolves to the release; no superseded
TEST61/TEST62 UrsusBoot stays installable; plus the STOCK->UBI route, backup
reuse and the functional _poll() /api/status-loss test.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

LAUNCHERS = {"START_ONECLICK.cmd", "START_ONECLICK.sh", "START_EXPERT.cmd", "START_EXPERT.sh"}
RUNTIME = (
    "one_key.py", "one_key_multi.py", "expert.py", "expert_airoha.py", "ursusboot_pregnant.py",
    "ursus_web_client.py", "ursusboot_install.py", "ursusboot_update.py", "ursusboot_release.py",
    "proven_backend.py",
)
SRC_NAME = {
    "update_fip": "ursusboot-update.fip", "u_boot_bin": "u-boot.bin",
    "install_mtd0": "ursusboot-install-mtd0.bin", "ubi_preloader": "ursusboot-ubi-preloader.fip",
    "runtime_lzma": "u-boot.runtime.lzma", "runtime_ram_fip": "ursusboot-runtime-ram.fip",
    "uart_preloader": "ursusboot-uart-preloader.bin",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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


def verify_release(root: Path, pin: dict, dists: dict[str, Path]) -> dict:
    rel = json.loads((root / "data" / "URSUSBOOT_RELEASE.json").read_text(encoding="utf-8"))
    for key in ("repo", "commit", "version"):
        check(rel.get(key) == pin.get(key), f"release {key} == pin", str(rel.get(key)))
    for fam, dist in dists.items():
        board = rel["boards"][fam]
        prov = json.loads((dist / "PROVENANCE.json").read_text(encoding="utf-8"))
        check(prov["commit"] == pin["commit"] and prov["version"] == pin["version"],
              f"{fam} artifacts from pinned commit", prov["commit"][:12])
        kit_prov = json.loads((root / "data" / "ursusboot-provenance" / f"{fam}.json").read_text(encoding="utf-8"))
        check(kit_prov == prov, f"{fam} PROVENANCE.json carried into the kit")
        for role, f in board["files"].items():
            kit_file = root / f["path"]
            check(sha256(kit_file) == f["sha256"] == sha256(dist / SRC_NAME[role]),
                  f"{fam} {role} == airoha-ursusboot dist", f["path"])
        bl33 = (root / board["files"]["u_boot_bin"]["path"]).read_bytes()
        pre = board["files"]["ubi_preloader"]
        check(bytes.fromhex(board["ubi_preloader_sha256"]) in bl33 and bytes.fromhex(board["ubi_bl2_image_sha256"]) in bl33
              and pre["sha256"] == board["ubi_preloader_sha256"],
              f"{fam} UrsusBoot accepts the packaged UBI preloader", pre["sha256"])
        bundles = json.loads((root / "data" / "FIRMWARE_BUNDLES.json").read_text(encoding="utf-8"))
        hit = [x for x in bundles["profiles"][fam]["files"] if x.get("role") == "STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE"]
        check(len(hit) == 1 and hit[0]["sha256"] == pre["sha256"] and hit[0]["path"] == pre["path"],
              f"FIRMWARE_BUNDLES {fam} preloader role -> release")
    md_bundle = json.loads((root / "data" / "FIRMWARE_BUNDLE.json").read_text(encoding="utf-8"))
    hit = [x for x in md_bundle["files"] if x.get("role") == "STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE"]
    check(len(hit) == 1 and hit[0]["sha256"] == rel["boards"]["md"]["files"]["ubi_preloader"]["sha256"],
          "FIRMWARE_BUNDLE md preloader role -> release")
    stale = sorted(p.relative_to(root).as_posix() for pat in ("*TEST61*.fip", "*TEST62*.fip", "*TEST61*-u-boot.bin")
                   for p in (root / "data/payloads/md/ursusboot").glob(pat))
    stale += sorted(p.relative_to(root).as_posix() for p in (root / "data/payloads/mf/recovery").glob("*TEST6[12]*"))
    check(not stale, "no superseded TEST61/TEST62 UrsusBoot installable", ",".join(stale) or "none")
    versions = {(root / "VERSION").read_text().strip(), (root / "data" / "VERSION").read_text().strip()}
    check(len(versions) == 1 and pin["version"] not in versions, "kit VERSION intact", ",".join(versions))
    return rel


def verify_host(root: Path, rel: dict) -> None:
    data = root / "data"
    sys.path.insert(0, str(data))
    v = rel["version"]
    md = rel["boards"]["md"]["files"]
    mf = rel["boards"]["mf"]["files"]
    one_key = importlib.import_module("one_key")
    check(one_key.TARGET_URSUS == v, "ONE-CLICK target UrsusBoot", one_key.TARGET_URSUS)
    okm = importlib.import_module("one_key_multi")
    check(okm.MD_TARGET == v and okm.MF_TARGET == v, "multi-board targets", f"{okm.MD_TARGET} {okm.MF_TARGET}")
    ui = importlib.import_module("ursusboot_install")
    check(ui.TARGET_URSUS == v and ui.PAYLOAD.resolve() == (root / md["update_fip"]["path"]).resolve()
          and ui.EXPECTED_HYBRID_FIP_SHA256 == md["update_fip"]["sha256"]
          and ui.EXPECTED_U_BOOT_SHA256 == md["u_boot_bin"]["sha256"],
          "item4 install -> release FIP", ui.PAYLOAD.name)
    uu = importlib.import_module("ursusboot_update")
    meta = uu._production_meta()
    check(uu.PRODUCTION_PAYLOAD.resolve() == (root / md["update_fip"]["path"]).resolve()
          and meta["version"] == v and meta["fip_sha256"] == md["update_fip"]["sha256"],
          "EXPERT web/TFTP/XMODEM FIP update -> release FIP", uu.PRODUCTION_PAYLOAD.name)
    compat = importlib.import_module("mf_uart_test62_compat")
    prof = compat.family_profile("mf")
    check(prof["preloader"].resolve() == (root / mf["uart_preloader"]["path"]).resolve()
          and prof["fip"].resolve() == (root / mf["runtime_ram_fip"]["path"]).resolve(),
          "MF UART recovery -> release pair", prof["fip"].name)
    mri = importlib.import_module("mf_runtime_install")
    check(Path(mri.require_bl33()).resolve() == (root / mf["runtime_lzma"]["path"]).resolve(),
          "MF runtime install -> release BL33")
    for fam in ("md", "mf"):
        for role in ("OPENWRT_UBI_SYSUPGRADE", "STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE"):
            p = Path(okm.require_role(fam, role)).resolve()
            check(root.resolve() in p.parents, f"one_key_multi.require_role({fam}, {role})",
                  p.relative_to(root.resolve()).as_posix())
    for role in ("OPENWRT_UBI_SYSUPGRADE", "STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE"):
        p = Path(one_key.require_bundle_role(role)).resolve()
        check(root.resolve() in p.parents, f"require_bundle_role({role})", p.relative_to(root.resolve()).as_posix())

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
    ap.add_argument("--ursusboot-md", required=True)
    ap.add_argument("--ursusboot-mf", required=True)
    ap.add_argument("--pin", required=True)
    args = ap.parse_args()
    pin = json.loads(Path(args.pin).read_text(encoding="utf-8"))
    dists = {"md": Path(args.ursusboot_md).resolve(), "mf": Path(args.ursusboot_mf).resolve()}
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(args.zip) as z:
            z.extractall(td)
        tops = list(Path(td).iterdir())
        check(len(tops) == 1 and tops[0].is_dir(), "single top-level kit dir", tops[0].name if tops else "")
        root = tops[0]
        verify_layout(root)
        verify_checksums(root)
        rel = verify_release(root, pin, dists)
        verify_host(root, rel)
    print(f"verify_kit: PASS ursusboot={pin['repo']}@{pin['commit']} version={pin['version']}")


if __name__ == "__main__":
    main()

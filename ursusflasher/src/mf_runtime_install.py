#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import re
import shlex
import sys
import time
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import board_profiles as bp
import console_ui as ui
import device_state as ds
import mf_persistent
import proven_backend as pb
import ursusboot_install as transport

BOOT_AREA_SIZE = mf_persistent.BOOT_AREA_SIZE
ERASE_SIZE = 0x20000


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _root() -> Path:
    repo = HERE.parent.parent
    return repo if (repo / "payloads").is_dir() else HERE.parent


def _bl33_candidates() -> list[Path]:
    root = _root()
    out = []
    env = os.environ.get("URSUS_MF_BL33_LZMA", "").strip()
    if env:
        out.append(Path(env).expanduser())
    if (root / "payloads").is_dir():
        out += [
            root / "payloads" / "mf" / "ursusboot" / "u-boot.runtime.lzma",
            root / "work" / "mf-runtime" / "out" / "u-boot.runtime.lzma",
        ]
    else:
        out += [root / "data" / "payloads" / "mf" / "ursusboot" / "u-boot.runtime.lzma"]
    return out


def require_bl33() -> Path:
    for path in _bl33_candidates():
        if path.is_file():
            raw = path.read_bytes()
            # The common builder performs the authoritative LZMA+identity check.
            probe = bytearray(BOOT_AREA_SIZE)
            # A synthetic source cannot be parsed as stock; decode/identity is
            # intentionally reached later against the actual device FIP.
            if len(raw) < 13 or raw[0] != 0x5D:
                raise RuntimeError(f"MF runtime BL33 is not Airoha LZMA-Alone: {path}")
            return path.resolve()
    raise RuntimeError("bundled MF runtime BL33 is missing (u-boot.runtime.lzma)")


def _family_from_state(state: ds.DeviceState) -> str | None:
    key = str(state.evidence.get("board_profile") or "")
    if key.startswith("mf"):
        return "mf"
    if key.startswith("md"):
        return "md"
    match = bp.match_profile(model=state.model, soc=state.soc)
    return match[0] if match else None


def _open_stock_access_auto(host: str) -> pb.StockAccess:
    """Authenticate stock Web, prove MF identity, then use the proven service bootstrap.

    The inherited automatic bootstrap still carries the historical MD-only
    stock_web.SUPPORTED_INSTALL_MODELS gate.  For this already-proven MF call
    only, extend that in-memory gate while the common bootstrap provisions the
    transport, then restore it immediately.  The durable model gate remains the
    BOARD_PROFILES match above; unknown/wrong models never reach this bridge.
    """
    module = pb._load_stock_web_module()
    user = str(getattr(module, "DEFAULT_WEB_USER", "CMCCAdmin") or "CMCCAdmin")
    password = str(getattr(module, "DEFAULT_WEB_PASSWORD", "") or "")
    if not password:
        raise RuntimeError("stock Web default password is unavailable")

    client = module.StockWeb(host)
    try:
        client.login(user, password, allow_plain=False)
        info = module.StockSetup(client).read_device_info()
    except getattr(module, "LoginError"):
        client = module.StockWeb(host)
        client.login(user, password, allow_plain=True)
        info = module.StockSetup(client).read_device_info()
    finally:
        try:
            client.logout()
        except Exception:
            pass

    model = str(info.get("model") or "")
    chipset = str(info.get("chipset") or "")
    match = bp.match_profile(model=model, soc=chipset)
    if not match or match[0] != "mf":
        raise RuntimeError(
            "stock device is not positively identified as Nokia XG-040G-MF / AN7583: "
            f"model={info.get('model')} chipset={info.get('chipset')}"
        )

    pb._STARTUP_DEVICE_PROFILE.clear()
    pb._STARTUP_DEVICE_PROFILE.update({
        "family": "mf", "model": model or "XG-040G-MF",
        "chipset": chipset or "AN7583", "host": host,
        "verified": True, "source": "ursusflasher-mf-runtime-stock-web",
    })
    pb._STARTUP_WEB_AUTH.clear()
    pb._STARTUP_WEB_AUTH.update({"host": host, "user": user, "password": password})

    old_supported = tuple(getattr(module, "SUPPORTED_INSTALL_MODELS", ("XG-040G-MD",)))
    module.SUPPORTED_INSTALL_MODELS = tuple(dict.fromkeys(old_supported + ("XG-040G-MF",)))
    try:
        access = pb._automatic_stock_web_access(host, module, offer_interactive_plain_retry=False)
    finally:
        module.SUPPORTED_INSTALL_MODELS = old_supported

    # _automatic_stock_web_access predates multi-board StockAccess metadata.
    # Identity was positively re-read and BOARD_PROFILES-matched above, so
    # carry that proof into the family-aware MF writer instead of losing it.
    access.family = "mf"
    access.model_name = model
    access.chipset = chipset
    access.model_verified = True
    access.model_verification_source = "mf-runtime-stock-web-board-profile"
    return access


def _open_stock_access_interactive() -> pb.StockAccess:
    """Use the mature family-aware MF stock install access path.

    proven_backend._install_access(MF_INSTALL_PROFILE) deliberately re-reads
    model/chipset through the live stock Web UI and rejects anything except MF.
    Unlike the legacy generic ask_credentials model gate, it does not encode
    AN7581 as the only accepted stock-install family and it still asks for the
    Nokia IP before touching the device.
    """
    access = pb._install_access(pb.MF_INSTALL_PROFILE)
    if getattr(access, "family", "") != "mf":
        access.close_web(announce=False)
        raise RuntimeError("MF installer requires positively identified MF stock")
    return access


def _write_result(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_fip_derived(current_fip: bytes, bl33: bytes) -> tuple[bytes, mf_persistent.CandidateReport]:
    """Reuse the stock-derived parser for a UBI-resident FIP without inventing a second parser."""
    if len(current_fip) > mf_persistent.FIP_MAX_LEN:
        raise RuntimeError(f"current MF FIP is too large: {len(current_fip)}")
    fake = bytearray(BOOT_AREA_SIZE)
    fake[mf_persistent.FIP_PHYS_OFF:mf_persistent.FIP_PHYS_OFF + len(current_fip)] = current_fip
    candidate_boot, report = mf_persistent.build_stock_derived_candidate(bytes(fake), bl33)
    start = mf_persistent.FIP_PHYS_OFF
    candidate_fip = candidate_boot[start:start + report.candidate_fip_end]
    return candidate_fip, report


def _find_mf_fip_volume(host: str) -> dict | None:
    cmd = (
        "for p in /sys/class/ubi/ubi*_*; do [ -f \"$p/name\" ] || continue; "
        "n=$(cat \"$p/name\" 2>/dev/null); [ \"$n\" = fip ] || continue; "
        "b=$(basename \"$p\"); t=$(cat \"$p/type\" 2>/dev/null || echo unknown); "
        "d=$(cat \"$p/data_bytes\" 2>/dev/null || echo 0); echo FIPVOL=$b TYPE=$t DATA=$d; done"
    )
    _rc, out = pb.ssh_run(host, cmd, timeout=30, quiet=True, batch_mode=True)
    hits = re.findall(r"FIPVOL=(ubi\d+_\d+)\s+TYPE=([^\s]+)\s+DATA=(\d+)", out)
    if not hits:
        return None
    if len(hits) != 1:
        raise RuntimeError(f"multiple UBI volumes named fip: {hits}")
    dev, typ, data = hits[0]
    if typ != "static":
        raise RuntimeError(f"MF fip volume is {typ}, expected static")
    data_bytes = int(data)
    if data_bytes <= 0 or data_bytes > mf_persistent.FIP_MAX_LEN:
        raise RuntimeError(f"MF fip data_bytes is invalid: {data_bytes}")
    return {"device": f"/dev/{dev}", "sysfs": dev, "type": typ, "data_bytes": data_bytes}


def _read_exact(host: str, command: str, expected: int) -> bytes:
    blob = pb.ssh_read_binary(host, command, timeout=240)
    if len(blob) != expected:
        raise RuntimeError(f"SSH read size mismatch: {len(blob)} != {expected}")
    return blob


def _raw_target(host: str) -> tuple[dict, bytes]:
    entries = transport._ssh_mtd_table(host)
    candidates = []
    for e in entries:
        name = str(e.get("name") or "").lower()
        if e.get("size", 0) < BOOT_AREA_SIZE:
            continue
        exact = e.get("size") == BOOT_AREA_SIZE and name in ("bootloader", "boot", "mtd0")
        master = e.get("offset") == 0 or (e.get("offset") is None and e.get("index") == 0 and name in ("all_flash", "all-flash", "flash", "master"))
        if exact or master:
            candidates.append(e)
    proven = []
    for e in candidates:
        try:
            blob = _read_exact(host, f"dd if={shlex.quote(e['device'])} bs={ERASE_SIZE} count=4 2>/dev/null", BOOT_AREA_SIZE)
            mf_persistent.parse_fip_from_boot_area(blob)
            proven.append((e, blob))
        except Exception:
            pass
    if len(proven) != 1:
        raise RuntimeError(f"MF raw boot target is not unambiguous: proven={len(proven)}")
    return proven[0]


def _raw_writer(host: str, target: dict) -> str:
    _rc, out = pb.ssh_run(host, "for x in mtd_debug flash_erase nandwrite mtd; do command -v $x >/dev/null 2>&1 && echo TOOL:$x; done", timeout=30, quiet=True, batch_mode=True)
    tools = set(re.findall(r"TOOL:([A-Za-z0-9_]+)", out))
    if "mtd_debug" in tools:
        return "mtd_debug"
    if "flash_erase" in tools and "nandwrite" in tools:
        return "flash_erase+nandwrite"
    if target.get("size") == BOOT_AREA_SIZE and "mtd" in tools:
        return "mtd"
    raise RuntimeError("no safe single MF raw boot writer is available")


def _write_raw(host: str, target: dict, remote: str, writer: str) -> None:
    dev = shlex.quote(target["device"])
    if writer == "mtd_debug":
        cmd = f"mtd_debug erase {dev} 0 {BOOT_AREA_SIZE} && mtd_debug write {dev} 0 {BOOT_AREA_SIZE} {shlex.quote(remote)}"
    elif writer == "flash_erase+nandwrite":
        cmd = f"flash_erase {dev} 0 4 && nandwrite -p -s 0 {dev} {shlex.quote(remote)}"
    elif writer == "mtd":
        cmd = f"mtd -f write {shlex.quote(remote)} {shlex.quote(target['name'])}"
    else:
        raise RuntimeError(f"unsupported MF writer: {writer}")
    # One selected writer only. No automatic alternate writer after this boundary.
    pb.ssh_run(host, cmd + " && sync", timeout=600, quiet=True, batch_mode=True)


def install_from_openwrt(*, host: str, unattended: bool = False, recovery_after: bool = False) -> int:
    state = ds.probe_device_state(host, interactive_ssh=True)
    if _family_from_state(state) != "mf" or not state.current_system.startswith("OPENWRT"):
        raise RuntimeError("root SSH target is not positively identified as MF OpenWrt")
    bl33_path = require_bl33()
    bl33 = bl33_path.read_bytes()
    stamp = _stamp()
    root = _root()
    work = root / "work"
    private = work / "private" / "mf-runtime-install"
    results = work / "results"
    private.mkdir(parents=True, exist_ok=True)
    result_path = results / f"mf-runtime-openwrt-{stamp}.json"
    result = {"operation":"MF_DEVICE_DERIVED_RUNTIME_INSTALL","route":"openwrt","status":"RUNNING","started_at":stamp,"bl33_sha256":pb.sha_file(bl33_path)}

    fipvol = _find_mf_fip_volume(host)
    if fipvol:
        current = _read_exact(host, f"dd if={shlex.quote(fipvol['device'])} bs=1 count={fipvol['data_bytes']} 2>/dev/null", fipvol["data_bytes"])
        before = private / f"fip-before-{stamp}.bin"; before.write_bytes(current)
        candidate, report = _build_fip_derived(current, bl33)
        target = private / f"fip-target-{stamp}.bin"; target.write_bytes(candidate)
        result.update({"backend":"ubi_fip","backup":str(before),"candidate":asdict(report),"target_sha256":mf_persistent.sha256(candidate)})
        if current[:len(candidate)] == candidate and len(current) == len(candidate):
            result["status"]="ALREADY_EXACT"; _write_result(result_path,result)
        else:
            remote = "/tmp/ursusboot-mf-runtime.fip"
            pb.scp_copy_to_recovery(host, target, remote, timeout=600)
            _rc, check = pb.ssh_run(host, f"wc -c < {remote}; sha256sum {remote}", timeout=60, quiet=True, batch_mode=True)
            expected = mf_persistent.sha256(candidate)
            if str(len(candidate)) not in check or expected not in check.lower():
                raise RuntimeError("MF runtime FIP transfer verification failed")
            if not unattended:
                ui.rule(tr("РАЗРЕШЁННОЕ ДЕЙСТВИЕ", "RESOLVED ACTION"), style="amber2")
                print(tr(f"  MF UBI volume fip: {fipvol['device']}, {len(candidate)} bytes; readback SHA256 required.", f"  MF UBI fip volume: {fipvol['device']}, {len(candidate)} bytes; readback SHA256 required."))
                if ui.prompt(tr("Начать запись? [y/N]: ", "Start writing? [y/N]: ")).strip().lower() not in ("y","yes","д","да"):
                    return 2
            pb.ssh_run(host, f"ubiupdatevol {shlex.quote(fipvol['device'])} {remote} && sync", timeout=600, quiet=True, batch_mode=True)
            rb = _read_exact(host, f"dd if={shlex.quote(fipvol['device'])} bs=1 count={len(candidate)} 2>/dev/null", len(candidate))
            if mf_persistent.sha256(rb) != expected:
                result["status"]="READBACK_MISMATCH"; _write_result(result_path,result); raise RuntimeError("MF UBI fip readback SHA256 mismatch; do not reboot")
            result["status"]="WRITE_AND_READBACK_PASS"; result["readback_sha256"]=expected; _write_result(result_path,result)
    else:
        target_obj, live = _raw_target(host)
        before = private / f"bootarea-before-{stamp}.bin"; before.write_bytes(live)
        candidate, report = mf_persistent.build_stock_derived_candidate(live, bl33)
        target = private / f"bootarea-target-{stamp}.bin"; target.write_bytes(candidate)
        expected = report.candidate_sha256
        result.update({"backend":"raw_boot_area","raw_target":target_obj,"backup":str(before),"candidate":asdict(report),"target_sha256":expected})
        if mf_persistent.sha256(live) == expected:
            result["status"]="ALREADY_EXACT"; _write_result(result_path,result)
        else:
            writer = _raw_writer(host, target_obj); result["writer"] = writer
            remote = "/tmp/ursusboot-mf-bootarea.bin"
            pb.scp_copy_to_recovery(host, target, remote, timeout=600)
            _rc, check = pb.ssh_run(host, f"wc -c < {remote}; sha256sum {remote}", timeout=60, quiet=True, batch_mode=True)
            if str(BOOT_AREA_SIZE) not in check or expected not in check.lower():
                raise RuntimeError("MF boot-area transfer verification failed")
            if not unattended:
                ui.rule(tr("РАЗРЕШЁННОЕ ДЕЙСТВИЕ", "RESOLVED ACTION"), style="amber2")
                print(tr(f"  MF boot area {target_obj['device']} 0x0..0x7ffff; writer={writer}; full readback required.", f"  MF boot area {target_obj['device']} 0x0..0x7ffff; writer={writer}; full readback required."))
                if ui.prompt(tr("Начать запись? [y/N]: ", "Start writing? [y/N]: ")).strip().lower() not in ("y","yes","д","да"):
                    return 2
            _write_raw(host, target_obj, remote, writer)
            rb = _read_exact(host, f"dd if={shlex.quote(target_obj['device'])} bs={ERASE_SIZE} count=4 2>/dev/null", BOOT_AREA_SIZE)
            if mf_persistent.sha256(rb) != expected:
                result["status"]="READBACK_MISMATCH"; _write_result(result_path,result); raise RuntimeError("MF boot-area readback mismatch; do not reboot")
            result["status"]="WRITE_AND_READBACK_PASS"; result["readback_sha256"]=expected; _write_result(result_path,result)

    if recovery_after:
        ui.note(tr("После reboot сразу зажмите Reset до 2 коротких + 3 длинных красных миганий и постоянного красного света.", "After reboot immediately hold Reset through 2 short + 3 long red flashes and steady red."))
        ui.prompt(tr("Нажмите Enter для перезагрузки OpenWrt: ", "Press Enter to reboot OpenWrt: "))
        try: pb.ssh_run(host, "sync; reboot -f", timeout=30, allow_disconnect=True, quiet=True)
        except Exception: pass
    return 0


def install_from_stock(*, host: str, unattended: bool = False, skip_full_backup: bool = False, recovery_after: bool = False) -> int:
    access = _open_stock_access_auto(host) if unattended else _open_stock_access_interactive()
    bl33_path = require_bl33(); bl33 = bl33_path.read_bytes()
    stamp = _stamp(); root = _root(); work = root / "work"
    private = work / "private" / "mf-runtime-install"; backups = work / "backups"; results = work / "results"
    private.mkdir(parents=True, exist_ok=True); backups.mkdir(parents=True, exist_ok=True)
    before = private / f"mf-mtd0-before-{stamp}.bin"; target = private / f"mf-mtd0-runtime-{stamp}.bin"; result_path = results / f"mf-runtime-stock-{stamp}.json"
    result = {"operation":"MF_DEVICE_DERIVED_RUNTIME_INSTALL","route":"stock","status":"RUNNING","started_at":stamp,"bl33_sha256":pb.sha_file(bl33_path)}
    telnet = None
    try:
        if not skip_full_backup:
            full = backups / f"stock-mf-full-{stamp}"
            pb.backup_tftp(access, access.host, full, expected_family="mf", allow_service_provisioning=False)
            result["full_stock_backup"] = str(full)
        else:
            result["full_stock_backup"] = None; result["full_stock_backup_skipped"] = True
        telnet = pb.login_root_family(access, "mf", allow_service_provisioning=True)
        pb.require_supported_model_over_telnet(access, telnet)
        pf = transport.mtd0_write_preflight(telnet); result["preflight"] = pf
        _remote, live_sha = transport.capture_live_mtd0(telnet, access, before)
        live = before.read_bytes()
        candidate, report = mf_persistent.build_stock_derived_candidate(live, bl33)
        target.write_bytes(candidate); expected = report.candidate_sha256
        result.update({"source_mtd0_sha256":live_sha,"candidate":asdict(report),"target_sha256":expected,"private_backup":str(before)})
        if live_sha != expected:
            remote = transport.upload_candidate(telnet, access, target)
            rc, check = telnet.command_clean(f"wc -c < {remote}; sha256sum {remote}", timeout=60)
            if rc or str(BOOT_AREA_SIZE) not in check or expected not in check.lower():
                raise RuntimeError("MF candidate transfer verification failed")
            if not unattended:
                ui.rule(tr("РАЗРЕШЁННОЕ ДЕЙСТВИЕ", "RESOLVED ACTION"), style="amber2")
                print(tr(f"  Nokia XG-040G-MF: mtd0 0x0..0x7ffff; writer={pf['writer']}; stock FIP components/env preserved; full SHA256 readback.", f"  Nokia XG-040G-MF: mtd0 0x0..0x7ffff; writer={pf['writer']}; stock FIP components/env preserved; full SHA256 readback."))
                if ui.prompt(tr("Начать запись? [y/N]: ", "Start writing? [y/N]: ")).strip().lower() not in ("y","yes","д","да"):
                    result["status"]="CANCELLED_BEFORE_WRITE"; _write_result(result_path,result); return 2
            rc, out = transport.write_image(telnet, remote, pf["writer"])
            if rc:
                result["status"]="WRITE_STATE_UNKNOWN"; result["write_output_tail"]=out[-4000:]; _write_result(result_path,result); raise RuntimeError("MF mtd0 writer failed; no alternate writer attempted")
            rb = transport.remote_mtd0_sha(telnet)
            if rb != expected:
                result["status"]="READBACK_MISMATCH"; result["readback_sha256"]=rb; _write_result(result_path,result); raise RuntimeError("MF mtd0 readback mismatch; do not reboot")
            result["readback_sha256"] = rb; result["status"]="WRITE_AND_READBACK_PASS"
        else:
            result["status"]="ALREADY_EXACT"; result["readback_sha256"]=live_sha
        result["completed_at"]=_stamp(); _write_result(result_path,result)
        if recovery_after:
            ui.note(tr("После reboot сразу зажмите Reset до 2 коротких + 3 длинных красных миганий и постоянного красного света.", "After reboot immediately hold Reset through 2 short + 3 long red flashes and steady red."))
            ui.prompt(tr("Нажмите Enter для перезагрузки Nokia: ", "Press Enter to reboot Nokia: "))
            try: telnet.command_clean("sync; reboot", timeout=20)
            except Exception: pass
        return 0
    finally:
        if telnet:
            try: telnet.close()
            except Exception: pass
        access.close_web(announce=False)


def run_install(*, host: str = "192.168.1.1", route: str = "auto", unattended: bool = False, skip_full_backup: bool = False, recovery_after: bool = False) -> int:
    route = route.lower().strip()
    if route == "auto":
        state = ds.probe_device_state(host, interactive_ssh=False)
        if state.current_system == "NOKIA_STOCK": route = "stock"
        elif state.current_system.startswith("OPENWRT"): route = "openwrt"
        else: raise RuntimeError("MF installer could not identify a writable running system")
    if route == "stock":
        return install_from_stock(host=host, unattended=unattended, skip_full_backup=skip_full_backup, recovery_after=recovery_after)
    if route == "openwrt":
        return install_from_openwrt(host=host, unattended=unattended, recovery_after=recovery_after)
    raise RuntimeError(f"unsupported MF install route: {route}")
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
_REPO_ROOT = HERE.parent.parent
REPO_MODE = (_REPO_ROOT / "payloads").is_dir() and (_REPO_ROOT / "config").is_dir()
ROOT = _REPO_ROOT if REPO_MODE else HERE.parent
WORK = ROOT / "work" / "stock-ab-transition"
LOG_ROOT = ROOT / "logs"

sys.path.insert(0, str(HERE))
import proven_backend as pb  # noqa: E402
import console_ui as ui  # noqa: E402
import ursusboot_install as ubi  # noqa: E402
import stock_fit_wrapper as sfw  # noqa: E402


@dataclass(frozen=True)
class TransitionPolicy:
    profile: str
    family: str
    payload_root: Path
    payload_name: str
    payload_meta_name: str
    slot_size: int
    flag_size: int
    erase_size: int
    flag_mtd: int
    flagback_mtd: int
    master_mtd: int
    slave_mtd: int
    nt_fw_uuid: bytes


MD_POLICY = TransitionPolicy(
    profile="xg040-md",
    family="md",
    payload_root=(ROOT / "payloads" / "md" / "transition") if REPO_MODE else (ROOT / "data" / "payloads" / "md" / "transition"),
    payload_name="ursusboot-md-0.1.0-alpha5-UBIUX1-TRANSITION2.linuximg",
    payload_meta_name="TRANSITION2.json",
    slot_size=0x02880000,
    flag_size=0x00040000,
    erase_size=0x00020000,
    flag_mtd=8,
    flagback_mtd=9,
    master_mtd=14,
    slave_mtd=15,
    nt_fw_uuid=bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4"),
)

# MF is intentionally a distinct board policy.  Do not inherit MD MTD indices,
# offsets or HDR/FIT assumptions.  The common orchestration is ready for it,
# but production write enablement requires the MF secondary-slot wrapper policy
# and payload to be described explicitly here first.
POLICIES = {MD_POLICY.profile: MD_POLICY}


class _Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()

    def __getattr__(self, name):
        return getattr(self.streams[0], name)


def _enable_transcript(stamp: str, policy: TransitionPolicy) -> Path:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    path = LOG_ROOT / f"{policy.profile.upper()}_TRANSITION_{stamp}.log"
    log = path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = _Tee(sys.__stdout__, log)
    sys.stderr = _Tee(sys.__stderr__, log)
    print(f"[LOG] {path}")
    return path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _policy(profile: str) -> TransitionPolicy:
    try:
        return POLICIES[profile]
    except KeyError as exc:
        if profile == "xg040-mf":
            raise RuntimeError(
                "xg040-mf transition policy is not encoded yet; refusing to copy MD MTD indices/offsets/HDR assumptions"
            ) from exc
        raise RuntimeError(f"unsupported stock transition profile: {profile}") from exc


def _load_payload(policy: TransitionPolicy) -> tuple[bytes, dict]:
    payload = policy.payload_root / policy.payload_name
    payload_meta = policy.payload_root / policy.payload_meta_name
    if not payload.is_file() or not payload_meta.is_file():
        raise RuntimeError(f"TRANSITION payload is missing from the UrsusFlasher bundle: {policy.payload_root}")
    meta = json.loads(payload_meta.read_text(encoding="utf-8"))
    data = payload.read_bytes()
    expected = str(meta.get("sha256") or "").lower()
    got = sha256_bytes(data)
    if not expected or got != expected:
        raise RuntimeError(f"TRANSITION payload SHA256 mismatch: {got} != {expected or 'missing'}")
    if str(meta.get("mode")) != "TRANSITION":
        raise RuntimeError("payload metadata does not identify TRANSITION mode")
    if str(meta.get("board") or "").lower() != policy.family:
        raise RuntimeError(f"payload board mismatch: expected {policy.family}")
    if str(meta.get("stock_inner_format")) != "ARM64_LINUX_IMAGE_HANDOFF":
        raise RuntimeError("payload metadata does not identify stock-compatible Linux Image handoff")
    sfw.validate_linux_image(data)
    return data, meta


def build_transition_slot(stock_slot: bytes, linux_image: bytes, policy: TransitionPolicy = MD_POLICY) -> tuple[bytes, dict]:
    return sfw.build_transition_slot(
        stock_slot,
        linux_image,
        slot_size=policy.slot_size,
        nt_fw_uuid=policy.nt_fw_uuid,
    )


def parse_flag(blob: bytes, policy: TransitionPolicy = MD_POLICY) -> dict:
    if len(blob) != policy.flag_size:
        raise RuntimeError(f"flag size mismatch: {len(blob):#x} != {policy.flag_size:#x}")
    active, curimg, startok, count = struct.unpack_from("<4I", blob, 0)
    if active not in (0, 1) or curimg not in (0, 1) or startok not in (0, 1):
        raise RuntimeError(f"implausible flag fields: active={active} curimg={curimg} startok={startok}")
    return {"active": active, "curimg": curimg, "startok": startok, "count": count}


def build_activation_flag(flag: bytes, target: int, policy: TransitionPolicy = MD_POLICY) -> tuple[bytes, dict]:
    state = parse_flag(flag, policy)
    if target not in (0, 1):
        raise RuntimeError("target image must be 0 or 1")
    out = bytearray(flag)
    struct.pack_into("<I", out, 0, target)
    if out[4:] != flag[4:]:
        raise RuntimeError("activation flag changed fields other than active")
    return bytes(out), {"before": state, "after": parse_flag(bytes(out), policy)}


def _require_stock_geometry(telnet: pb.Telnet, policy: TransitionPolicy) -> None:
    rc, text = telnet.command_clean("cat /proc/mtd", timeout=20)
    if rc:
        raise RuntimeError("cannot read /proc/mtd")
    rows = {name: (int(size, 16), int(erase, 16), int(idx)) for idx, size, erase, name in re.findall(
        r'mtd(\d+):\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+\"([^\"]+)\"', text
    )}
    expected = {
        "flag": (policy.flag_size, policy.erase_size, policy.flag_mtd),
        "flagback": (policy.flag_size, policy.erase_size, policy.flagback_mtd),
        "nsb_master": (policy.slot_size, policy.erase_size, policy.master_mtd),
        "nsb_slave": (policy.slot_size, policy.erase_size, policy.slave_mtd),
    }
    for name, want in expected.items():
        got = rows.get(name)
        if got != want:
            raise RuntimeError(f"stock MTD geometry mismatch for {name}: {got} != {want}")


def _capture(telnet: pb.Telnet, access: pb.StockAccess, dev: str, size: int, local: Path) -> str:
    remote = f"/tmp/ursus-ab-{local.name}"
    bs = 131072
    count = (size + bs - 1) // bs
    rc, text = telnet.command_clean(
        f"rm -f {shlex.quote(remote)}; dd if={shlex.quote(dev)} of={shlex.quote(remote)} bs={bs} count={count} 2>/dev/null && wc -c < {shlex.quote(remote)} && sha256sum {shlex.quote(remote)}",
        timeout=300,
    )
    if rc:
        raise RuntimeError(f"failed to capture {dev}")
    hashes = re.findall(r"\b([0-9a-fA-F]{64})\b", text)
    sizes = re.findall(r"(?:^|\n)\s*(\d+)\s*(?:\n|$)", text)
    if not hashes or not sizes or int(sizes[-1]) != size:
        raise RuntimeError(f"capture metadata invalid for {dev}")
    expected = hashes[-1].lower()
    ubi.receive_remote_file(telnet, access.host, remote, local, port=1069, block_size=4096)
    if local.stat().st_size != size or sha256_file(local) != expected:
        raise RuntimeError(f"PC copy mismatch for {dev}")
    return expected


def _verify_remote_upload(telnet: pb.Telnet, local: Path, remote: str) -> str:
    expected = sha256_file(local)
    rc, text = telnet.command_clean(f"wc -c < {shlex.quote(remote)}; sha256sum {shlex.quote(remote)}", timeout=180)
    if rc or str(local.stat().st_size) not in text or expected not in text.lower():
        raise RuntimeError(f"uploaded file verification failed: {remote}")
    return expected


def _upload_with_backend(
    backend: str,
    telnet: pb.Telnet,
    access: pb.StockAccess,
    local: Path,
    remote: str,
) -> str:
    if backend == "tcp":
        pb.send_file_to_router(telnet, access.host, local, remote)
    elif backend == "tftp":
        pb.send_file_to_router_tftp(telnet, access.host, local, remote, port=1069, block_size=4096)
    else:
        raise RuntimeError(f"unsupported frozen upload backend: {backend}")
    return _verify_remote_upload(telnet, local, remote)


def _select_and_preflight_transport(
    telnet: pb.Telnet,
    access: pb.StockAccess,
    slot_candidate: Path,
    flag_candidate: Path,
) -> tuple[str, str, str]:
    """Choose one proven transfer primitive before the destructive boundary.

    Both transaction inputs are uploaded and SHA/size-verified while NAND is
    still untouched.  Another backend may be tried only here.  The returned
    backend is frozen and no automatic switch is permitted after confirmation.
    """
    remote_slot = f"/tmp/ursus-{access.family}-transition-slot.bin"
    remote_flag = f"/tmp/ursus-{access.family}-transition-flag.bin"
    failures: list[str] = []
    for backend in ("tcp", "tftp"):
        try:
            telnet.command_clean(f"rm -f {shlex.quote(remote_slot)} {shlex.quote(remote_flag)}", timeout=20)
            _upload_with_backend(backend, telnet, access, slot_candidate, remote_slot)
            _upload_with_backend(backend, telnet, access, flag_candidate, remote_flag)
            ui.status("READY", f"Stock transfer backend preflight passed and frozen: {backend}")
            return backend, remote_slot, remote_flag
        except Exception as exc:
            failures.append(f"{backend}: {exc}")
            pb._write_session_only(f"[TRANSITION-TRANSPORT-PREFLIGHT] {backend}: {exc!r}")
    raise RuntimeError("no proven stock transfer backend passed preflight: " + "; ".join(failures))


def _mtd_writer_preflight(telnet: pb.Telnet) -> str:
    rc, text = telnet.command_clean(
        "for x in mtd mtd_debug flash_erase nandwrite; do command -v $x 2>/dev/null && echo TOOL:$x; done; "
        "echo __MTD_HELP__; mtd --help 2>&1 || mtd 2>&1 || true",
        timeout=20,
    )
    tools = set(re.findall(r"TOOL:([A-Za-z0-9_+.-]+)", text))
    help_text = text.split("__MTD_HELP__", 1)[-1].lower()
    if "mtd" in tools and "write" in help_text:
        method = "mtd"
    elif "mtd_debug" in tools:
        method = "mtd_debug"
    elif "flash_erase" in tools and "nandwrite" in tools:
        method = "flash_erase+nandwrite"
    else:
        raise RuntimeError("no supported stock MTD writer is available; need mtd write, mtd_debug, or flash_erase+nandwrite")
    ui.status("READY", f"Stock MTD writer selected and frozen: {method}")
    return method


def _write_partition(telnet: pb.Telnet, remote: str, part: str, dev: str, size: int, method: str, erase_size: int, timeout: int = 600) -> None:
    qremote = shlex.quote(remote)
    qpart = shlex.quote(part)
    qdev = shlex.quote(dev)
    if size <= 0 or size % erase_size:
        raise RuntimeError(f"unsafe write size for {part}: 0x{size:x}")
    if method == "mtd":
        cmd = f"mtd write {qremote} {qpart} && sync"
    elif method == "mtd_debug":
        cmd = f"mtd_debug erase {qdev} 0 {size} && mtd_debug write {qdev} 0 {size} {qremote} && sync"
    elif method == "flash_erase+nandwrite":
        cmd = f"flash_erase {qdev} 0 0 && nandwrite -p {qdev} {qremote} && sync"
    else:
        raise RuntimeError(f"unsupported MTD writer method: {method}")
    rc, text = telnet.command_clean(cmd, timeout=timeout)
    if rc:
        raise RuntimeError(f"{method} write failed for {part}: {text[-1000:]}")


def _remote_partition_sha(telnet: pb.Telnet, dev: str, timeout: int = 300) -> str:
    rc, text = telnet.command_clean(f"dd if={shlex.quote(dev)} bs=131072 2>/dev/null | sha256sum", timeout=timeout)
    if rc:
        raise RuntimeError(f"readback SHA failed for {dev}")
    hashes = re.findall(r"\b([0-9a-fA-F]{64})\b", text)
    if not hashes:
        raise RuntimeError(f"readback SHA missing for {dev}")
    return hashes[-1].lower()


def run(*, host: str = "192.168.1.1", profile: str = "xg040-md", unattended: bool = False, dry_run: bool = False, reboot: bool = True) -> int:
    policy = _policy(profile)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = _enable_transcript(stamp, policy)
    ui.enable()
    linux_image, payload_meta = _load_payload(policy)
    WORK.mkdir(parents=True, exist_ok=True)
    run_dir = WORK / f"{policy.family}-{stamp}"
    run_dir.mkdir(parents=True)
    access = telnet = None
    try:
        access, telnet = ubi.open_root_auto(host) if unattended else ubi.open_root()
        if access.family != policy.family:
            raise RuntimeError(f"board profile mismatch: selected {policy.profile}, stock Web reports {access.family}")
        _require_stock_geometry(telnet, policy)
        writer = _mtd_writer_preflight(telnet)

        # Production contract: complete backup of every live /proc/mtd entry via
        # the already proven UrsusFlasher backup backend, then validation, before
        # candidate staging is authorized.
        full_backup = run_dir / "full-stock-backup"
        pb.backup_tftp(access, access.host, full_backup, expected_family=access.family, allow_service_provisioning=True)
        backup_result = pb.verify_stock_restore_backup(full_backup)
        ui.status("READY", f"Complete stock backup verified: {full_backup}")

        flag_path = run_dir / f"mtd{policy.flag_mtd}_flag_before.bin"
        flagback_path = run_dir / f"mtd{policy.flagback_mtd}_flagback_before.bin"
        master_path = run_dir / f"mtd{policy.master_mtd}_nsb_master_before.bin"
        slave_path = run_dir / f"mtd{policy.slave_mtd}_nsb_slave_before.bin"
        flag_sha = _capture(telnet, access, f"/dev/mtd{policy.flag_mtd}", policy.flag_size, flag_path)
        flagback_sha = _capture(telnet, access, f"/dev/mtd{policy.flagback_mtd}", policy.flag_size, flagback_path)
        master_sha = _capture(telnet, access, f"/dev/mtd{policy.master_mtd}", policy.slot_size, master_path)
        slave_sha = _capture(telnet, access, f"/dev/mtd{policy.slave_mtd}", policy.slot_size, slave_path)

        flag = flag_path.read_bytes()
        flagback = flagback_path.read_bytes()
        fs = parse_flag(flag, policy)
        fbs = parse_flag(flagback, policy)
        ui.status("INFO", f"Stock A/B state: flag={fs}; flagback={fbs}")
        if fs["curimg"] != 0 or fs["active"] != 0 or fbs["curimg"] != fs["curimg"]:
            ui.status("INFO", "A/B selector state is advisory; structural/profile invariants remain authoritative.")

        slot_candidate, slot_meta = build_transition_slot(slave_path.read_bytes(), linux_image, policy)
        slot_candidate_path = run_dir / f"mtd{policy.slave_mtd}_nsb_slave_transition.bin"
        slot_candidate_path.write_bytes(slot_candidate)
        flag_candidate, flag_meta = build_activation_flag(flag, 1, policy)
        flag_candidate_path = run_dir / f"mtd{policy.flag_mtd}_flag_activate_slave.bin"
        flag_candidate_path.write_bytes(flag_candidate)

        # Preflight transfer before y/N.  Failure can move to another proven
        # backend only here.  Both remote candidates are verified while NAND is
        # untouched; after y/N no transport selection occurs at all.
        transport, remote_slot, remote_flag = _select_and_preflight_transport(
            telnet, access, slot_candidate_path, flag_candidate_path
        )

        report = {
            "operation": f"{policy.profile}_stock_ab_transition",
            "profile": policy.profile,
            "payload": payload_meta,
            "slot": slot_meta,
            "selector": flag_meta,
            "flagback_observed": fbs,
            "backup": {
                "full_directory": str(full_backup),
                "verification": backup_result,
                "flag_sha256": flag_sha,
                "flagback_sha256": flagback_sha,
                "nsb_master_sha256": master_sha,
                "nsb_slave_sha256": slave_sha,
            },
            "writer": writer,
            "transport": transport,
            "log": str(log_path),
            "dry_run": dry_run,
        }
        (run_dir / "TRANSITION_PLAN.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

        ui.status("READY", f"SLAVE candidate prepared: SHA256 {slot_meta['candidate_sha256']}")
        ui.status("READY", "Stock FIP/HDR2/FIT topology preserved; only allowed kernel data/compression/hash fields changed.")
        ui.status("READY", f"Selector request: active {fs['active']} -> 1; remaining flag fields preserved")
        ui.status("READY", f"Preflight: full backup VERIFIED; writer={writer}; transport={transport}; uploads SHA-verified")
        if dry_run:
            ui.status("READY", "Dry-run complete; NAND was not modified.")
            return 0

        ans = ui.prompt(pb.tr(
            "Preflight пройден. Записать TRANSITION в nsb_slave и активировать SLAVE? [д/Н]: ",
            "Preflight passed. Write TRANSITION to nsb_slave and activate SLAVE? [y/N]: ",
        )).strip().lower()
        if ans not in ("д", "да", "y", "yes"):
            ui.status("STOP", pb.tr("Операция отменена; NAND не изменялась.", "Operation cancelled; NAND was not modified."))
            return 0

        # ---------------- destructive boundary ----------------
        # transport and writer are frozen; do not auto-switch either below.
        _write_partition(telnet, remote_slot, "nsb_slave", f"/dev/mtd{policy.slave_mtd}", policy.slot_size, writer, policy.erase_size, timeout=900)
        got = _remote_partition_sha(telnet, f"/dev/mtd{policy.slave_mtd}", timeout=600)
        if got != slot_meta["candidate_sha256"]:
            raise RuntimeError(f"nsb_slave readback mismatch: {got} != {slot_meta['candidate_sha256']}")
        ui.status("READY", "nsb_slave TRANSITION write/readback verified; MAIN remains untouched.")

        expected_flag_sha = sha256_file(flag_candidate_path)
        _write_partition(telnet, remote_flag, "flag", f"/dev/mtd{policy.flag_mtd}", policy.flag_size, writer, policy.erase_size, timeout=120)
        got_flag = _remote_partition_sha(telnet, f"/dev/mtd{policy.flag_mtd}", timeout=120)
        if got_flag != expected_flag_sha:
            raise RuntimeError(f"flag readback mismatch: {got_flag} != {expected_flag_sha}")
        ui.status("READY", "Stock tcboot selector request verified: active=1; flagback untouched.")

        if reboot:
            ui.status("ACTION", pb.tr("Перезагрузка в SLAVE/TRANSITION через штатный tcboot.", "Rebooting into SLAVE/TRANSITION through stock tcboot."))
            try:
                telnet.send_line("sync; reboot")
            except Exception:
                pass
        else:
            ui.status("ACTION", pb.tr("Требуется перезагрузка для применения selector.", "A reboot is required to apply the selector."))
        return 0
    finally:
        if telnet:
            try:
                telnet.close()
            except Exception:
                pass
        if access:
            try:
                access.close_web(announce=False)
            except Exception:
                pass


def run_expert(*, host: str, profile: str) -> int:
    """Production EXPERT item 4 entrypoint.

    EXPERT owns the UI/session; this backend owns the board-policy transaction.
    The standalone launcher is retained only as a developer/HW-test wrapper.
    """
    return run(host=host, profile=profile, unattended=True, dry_run=False, reboot=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="UrsusFlasher stock A/B TRANSITION backend (developer/HW-test wrapper)")
    ap.add_argument("--host", default=os.environ.get("NOKIA_HOST", "192.168.1.1"))
    ap.add_argument("--profile", default="xg040-md", choices=("xg040-md", "xg040-mf"))
    ap.add_argument("--unattended", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-reboot", action="store_true")
    args = ap.parse_args(argv)
    return run(host=args.host, profile=args.profile, unattended=args.unattended, dry_run=args.dry_run, reboot=not args.no_reboot)


if __name__ == "__main__":
    raise SystemExit(main())

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
from pathlib import Path

HERE = Path(__file__).resolve().parent
_REPO_ROOT = HERE.parent.parent
REPO_MODE = (_REPO_ROOT / "payloads").is_dir() and (_REPO_ROOT / "config").is_dir()
ROOT = _REPO_ROOT if REPO_MODE else HERE.parent
PAYLOAD_ROOT = (ROOT / "payloads" / "md" / "transition") if REPO_MODE else (ROOT / "data" / "payloads" / "md" / "transition")
PAYLOAD = PAYLOAD_ROOT / "ursusboot-md-0.1.0-alpha5-UBIUX1-TRANSITION1.linuximg"
PAYLOAD_META = PAYLOAD_ROOT / "TRANSITION1.json"
WORK = ROOT / "work" / "stock-ab-transition"

sys.path.insert(0, str(HERE))
import proven_backend as pb  # noqa: E402
import console_ui as ui  # noqa: E402
import ursusboot_install as ubi  # noqa: E402
import stock_fit_wrapper as sfw  # noqa: E402

SLOT_SIZE = 0x02880000
FLAG_SIZE = 0x00040000
ERASE_SIZE = 0x00020000
NT_FW_UUID = bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_payload() -> tuple[bytes, dict]:
    if not PAYLOAD.is_file() or not PAYLOAD_META.is_file():
        raise RuntimeError(f"TRANSITION1 payload is missing from the UrsusFlasher bundle: {PAYLOAD_ROOT}")
    meta = json.loads(PAYLOAD_META.read_text(encoding="utf-8"))
    data = PAYLOAD.read_bytes()
    expected = str(meta.get("sha256") or "").lower()
    got = sha256_bytes(data)
    if not expected or got != expected:
        raise RuntimeError(f"TRANSITION1 payload SHA256 mismatch: {got} != {expected or 'missing'}")
    if str(meta.get("mode")) != "TRANSITION" or str(meta.get("board")) != "MD":
        raise RuntimeError("TRANSITION1 metadata does not identify MD TRANSITION mode")
    if str(meta.get("stock_inner_format")) != "ARM64_LINUX_IMAGE_HANDOFF":
        raise RuntimeError("TRANSITION1 metadata does not identify stock-compatible Linux Image handoff")
    sfw.validate_linux_image(data)
    return data, meta


def build_transition_slot(stock_slot: bytes, linux_image: bytes) -> tuple[bytes, dict]:
    return sfw.build_transition_slot(
        stock_slot,
        linux_image,
        slot_size=SLOT_SIZE,
        nt_fw_uuid=NT_FW_UUID,
    )


def parse_flag(blob: bytes) -> dict:
    if len(blob) != FLAG_SIZE:
        raise RuntimeError(f"flag size mismatch: {len(blob):#x} != {FLAG_SIZE:#x}")
    active, curimg, startok, count = struct.unpack_from("<4I", blob, 0)
    if active not in (0, 1) or curimg not in (0, 1) or startok not in (0, 1):
        raise RuntimeError(f"implausible flag fields: active={active} curimg={curimg} startok={startok}")
    return {"active": active, "curimg": curimg, "startok": startok, "count": count}


def build_activation_flag(flag: bytes, target: int) -> tuple[bytes, dict]:
    state = parse_flag(flag)
    if target not in (0, 1):
        raise RuntimeError("target image must be 0 or 1")
    if state["curimg"] == target:
        raise RuntimeError(f"requested target {target} is already curimg")
    out = bytearray(flag)
    struct.pack_into("<I", out, 0, target)
    if out[4:] != flag[4:]:
        raise RuntimeError("activation flag changed fields other than active")
    return bytes(out), {"before": state, "after": parse_flag(bytes(out))}


def _require_stock_geometry(telnet: pb.Telnet) -> None:
    rc, text = telnet.command_clean("cat /proc/mtd", timeout=20)
    if rc:
        raise RuntimeError("cannot read /proc/mtd")
    rows = {name: (int(size, 16), int(erase, 16), int(idx)) for idx, size, erase, name in re.findall(
        r'mtd(\d+):\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+\"([^\"]+)\"', text
    )}
    expected = {
        "flag": (FLAG_SIZE, ERASE_SIZE, 8),
        "flagback": (FLAG_SIZE, ERASE_SIZE, 9),
        "nsb_master": (SLOT_SIZE, ERASE_SIZE, 14),
        "nsb_slave": (SLOT_SIZE, ERASE_SIZE, 15),
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
        timeout=240,
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


def _upload(telnet: pb.Telnet, access: pb.StockAccess, local: Path, remote: str) -> str:
    pb.send_file_to_router_tftp(telnet, access.host, local, remote, port=1069, block_size=4096)
    expected = sha256_file(local)
    rc, text = telnet.command_clean(f"wc -c < {shlex.quote(remote)}; sha256sum {shlex.quote(remote)}", timeout=120)
    if rc or expected not in text.lower():
        raise RuntimeError(f"uploaded file verification failed: {remote}")
    return expected


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
        raise RuntimeError(
            "no supported stock MTD writer is available; need mtd write, mtd_debug, or flash_erase+nandwrite"
        )
    ui.status("READY", f"Stock MTD writer selected: {method}")
    return method


def _write_partition(
    telnet: pb.Telnet,
    remote: str,
    part: str,
    dev: str,
    size: int,
    method: str,
    timeout: int = 600,
) -> None:
    qremote = shlex.quote(remote)
    qpart = shlex.quote(part)
    qdev = shlex.quote(dev)
    if size <= 0 or size % ERASE_SIZE:
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


def run(*, host: str = "192.168.1.1", unattended: bool = False, dry_run: bool = False, reboot: bool = True) -> int:
    ui.enable()
    linux_image, payload_meta = _load_payload()
    WORK.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = WORK / stamp
    run_dir.mkdir(parents=True)
    access = telnet = None
    try:
        access, telnet = ubi.open_root_auto(host) if unattended else ubi.open_root()
        _require_stock_geometry(telnet)
        writer = _mtd_writer_preflight(telnet)

        flag_path = run_dir / "mtd8_flag_before.bin"
        flagback_path = run_dir / "mtd9_flagback_before.bin"
        slave_path = run_dir / "mtd15_nsb_slave_before.bin"
        _capture(telnet, access, "/dev/mtd8", FLAG_SIZE, flag_path)
        _capture(telnet, access, "/dev/mtd9", FLAG_SIZE, flagback_path)
        _capture(telnet, access, "/dev/mtd15", SLOT_SIZE, slave_path)

        flag = flag_path.read_bytes()
        flagback = flagback_path.read_bytes()
        fs = parse_flag(flag)
        fbs = parse_flag(flagback)
        if fs["curimg"] != 0:
            raise RuntimeError(f"hardware-test gate requires current MAIN/curimg=0, got {fs}")
        if fs["active"] != 0:
            raise RuntimeError(f"pending selector request already exists; refusing to overwrite it: {fs}")
        if fbs["curimg"] != fs["curimg"]:
            raise RuntimeError(f"flag/flagback curimg diverged: flag={fs} flagback={fbs}")

        slot_candidate, slot_meta = build_transition_slot(slave_path.read_bytes(), linux_image)
        slot_candidate_path = run_dir / "mtd15_nsb_slave_transition1.bin"
        slot_candidate_path.write_bytes(slot_candidate)
        flag_candidate, flag_meta = build_activation_flag(flag, 1)
        flag_candidate_path = run_dir / "mtd8_flag_activate_slave.bin"
        flag_candidate_path.write_bytes(flag_candidate)

        report = {
            "operation": "md_stock_ab_transition",
            "payload": payload_meta,
            "slot": slot_meta,
            "selector": flag_meta,
            "flagback_observed": fbs,
            "writer": writer,
            "dry_run": dry_run,
        }
        (run_dir / "TRANSITION_PLAN.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

        ui.status("READY", f"SLAVE candidate prepared: SHA256 {slot_meta['candidate_sha256']}")
        ui.status("READY", "Stock FIP/HDR2/FIT topology preserved; only kernel data/compression/hash changed.")
        ui.status("READY", "Selector request: active 0 -> 1; curimg/startok/count preserved")
        if dry_run:
            ui.status("READY", "Dry-run complete; NAND was not modified.")
            return 0

        ans = ui.prompt(pb.tr("Записать TRANSITION в nsb_slave и активировать SLAVE? [д/Н]: ", "Write TRANSITION to nsb_slave and activate SLAVE? [y/N]: ")).strip().lower()
        if ans not in ("д", "да", "y", "yes"):
            ui.status("STOP", pb.tr("Операция отменена; NAND не изменялась.", "Operation cancelled; NAND was not modified."))
            return 0

        remote_slot = "/tmp/ursus-md-transition-slot.bin"
        _upload(telnet, access, slot_candidate_path, remote_slot)
        _write_partition(telnet, remote_slot, "nsb_slave", "/dev/mtd15", SLOT_SIZE, writer, timeout=900)
        got = _remote_partition_sha(telnet, "/dev/mtd15", timeout=600)
        if got != slot_meta["candidate_sha256"]:
            raise RuntimeError(f"nsb_slave readback mismatch: {got} != {slot_meta['candidate_sha256']}")
        ui.status("READY", "nsb_slave TRANSITION write/readback verified; MAIN remains untouched.")

        remote_flag = "/tmp/ursus-md-flag-activate-slave.bin"
        expected_flag_sha = _upload(telnet, access, flag_candidate_path, remote_flag)
        _write_partition(telnet, remote_flag, "flag", "/dev/mtd8", FLAG_SIZE, writer, timeout=120)
        got_flag = _remote_partition_sha(telnet, "/dev/mtd8", timeout=120)
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="UrsusFlasher MD stock A/B TRANSITION backend")
    ap.add_argument("--host", default=os.environ.get("NOKIA_HOST", "192.168.1.1"))
    ap.add_argument("--unattended", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-reboot", action="store_true")
    args = ap.parse_args(argv)
    return run(host=args.host, unattended=args.unattended, dry_run=args.dry_run, reboot=not args.no_reboot)


if __name__ == "__main__":
    raise SystemExit(main())

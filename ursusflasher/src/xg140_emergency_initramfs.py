#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

# Emergency bundle must be non-interactive after START_*.cmd.  The shared
# backend only asks for language when NOKIA_LANG is absent.
os.environ.setdefault("NOKIA_LANG", "ru")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import proven_backend as proven
import ursus_web_client as uw
import xg140_emergency_persistent as base

LOADADDR = 0x85000000
RESCUE_READY = "URSUS_XG140_RESCUE_INITRAMFS=1"
RESCUE_BOARD = "BOARD=XG140GMC2P5G"
INSTALL_COMPLETE = "URSUS_XG140_INSTALL_COMPLETE"
PERSISTENT_MARKERS = ("0.1.0-xg140-native1", "UrsusBoot")


class RescueError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_rescue(root: Path) -> Path:
    preferred = root / "xg140-rescue-initramfs.itb"
    if preferred.is_file():
        return preferred
    matches = sorted(root.glob("*xg*140*initramfs*.itb"))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise RescueError("xg140 rescue initramfs FIT is missing from the artifact")
    raise RescueError("more than one XG140 initramfs FIT is present; artifact is ambiguous")


def _read(sp, log, timeout: float = 0.20) -> str:
    return base._read_text(sp, log, timeout)


def _fresh_ecnt(sp, log, timeout: float = 8.0) -> str:
    time.sleep(0.15)
    sp.write(b"\r")
    deadline = time.time() + timeout
    transcript = ""
    while time.time() < deadline:
        text = _read(sp, log, 0.20)
        if text:
            transcript = (transcript + text)[-16384:]
        if "ecnt>" in transcript.lower():
            return transcript
    raise RescueError("tcboot ECNT> did not return after XMODEM; NAND untouched")


def _tcboot_command(sp, log, command: str, timeout: float = 30.0) -> str:
    sp.reset_input()
    base._send_line(sp, command)
    deadline = time.time() + timeout
    transcript = ""
    while time.time() < deadline:
        text = _read(sp, log, 0.20)
        if text:
            transcript = (transcript + text)[-131072:]
        if "ecnt>" in transcript.lower():
            return transcript
    raise RescueError(f"tcboot command did not return ECNT>: {command}")


def _boot_rescue(sp, log, image: Path) -> None:
    print(f"[AUTO] XMODEM rescue FIT {image.name} -> RAM 0x{LOADADDR:x}")
    proven._uboot_wait_quiet(sp, log, quiet=0.15, timeout=1.0)
    sp.reset_input()
    base._send_line(sp, f"loadx 0x{LOADADDR:x}")
    time.sleep(0.35)
    proven.xmodem_send(sp, image, image.name, log)
    _fresh_ecnt(sp, log)
    print("[AUTO] Rescue FIT transfer complete; validating with stock tcboot iminfo")
    info = _tcboot_command(sp, log, f"iminfo 0x{LOADADDR:x}", 30.0)
    gates = ("FIT image found", "AArch64", "Linux")
    missing = [gate for gate in gates if gate.lower() not in info.lower()]
    if missing:
        raise RescueError("tcboot iminfo rejected rescue FIT: missing " + ", ".join(missing))
    print("[AUTO] tcboot FIT validation PASS; bootm rescue initramfs")
    sp.reset_input()
    base._send_line(sp, f"bootm 0x{LOADADDR:x}")


def _wait_rescue_shell(sp, log, timeout: float = 240.0) -> None:
    deadline = time.time() + timeout
    transcript = ""
    last_enter = 0.0
    last_probe = 0.0
    saw_linux = False
    while time.time() < deadline:
        text = _read(sp, log, 0.25)
        if text:
            transcript = (transcript + text)[-131072:]
            low = transcript.lower()
            if "starting kernel" in low or "linux version" in low:
                saw_linux = True
            if RESCUE_READY.lower() in low and RESCUE_BOARD.lower() in low:
                print("\n[AUTO] XG140 rescue initramfs identity confirmed")
                return
        low = transcript.lower()
        now = time.time()
        if "please press enter to activate this console" in low and now - last_enter > 1.0:
            sp.write(b"\r")
            last_enter = now
        if ("root@openwrt" in low or "root@(none)" in low or "ash" in low) and now - last_probe > 1.0:
            base._send_line(sp, "cat /etc/ursus-xg140-rescue-id")
            last_probe = now
        # Some initramfs builds do not echo a recognizable prompt. Once Linux is
        # clearly alive, a harmless identity read also activates the console.
        if saw_linux and now - last_probe > 3.0:
            sp.write(b"\r")
            time.sleep(0.05)
            base._send_line(sp, "cat /etc/ursus-xg140-rescue-id")
            last_probe = now
    raise RescueError("XG140 rescue initramfs shell/identity was not confirmed; NAND untouched")


def _linux_command(sp, log, command: str, timeout: float = 30.0) -> tuple[int, str]:
    token = f"__URSUS_DONE_{int(time.time() * 1000)}__"
    sp.reset_input()
    base._send_line(sp, f"{command}; rc=$?; echo {token}:$rc")
    deadline = time.time() + timeout
    transcript = ""
    while time.time() < deadline:
        text = _read(sp, log, 0.20)
        if text:
            transcript = (transcript + text)[-262144:]
        pos = transcript.rfind(token + ":")
        if pos >= 0:
            tail = transcript[pos + len(token) + 1:]
            digits = ""
            for ch in tail:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if digits:
                return int(digits), transcript
    raise RescueError(f"rescue Linux command timed out: {command}")


def _send_hybrid_to_linux(sp, log, hybrid: Path) -> None:
    print(f"[AUTO] XMODEM native-hybrid FIP -> rescue Linux /tmp/ursusboot.fip ({hybrid.stat().st_size} bytes)")
    sp.reset_input()
    base._send_line(sp, "rm -f /tmp/ursusboot.fip; rx /tmp/ursusboot.fip")
    time.sleep(0.45)
    proven.xmodem_send(sp, hybrid, "native-hybrid FIP", log)
    # rx may print its shell prompt before xmodem_send releases the port. Force a
    # fresh command/marker instead of depending on that prompt.
    expected_sha = _sha256(hybrid)
    expected_size = hybrid.stat().st_size
    rc, out = _linux_command(
        sp, log,
        "test -f /tmp/ursusboot.fip && echo URSUS_FIP_SIZE=$(wc -c < /tmp/ursusboot.fip) && sha256sum /tmp/ursusboot.fip",
        20.0,
    )
    if rc != 0 or f"URSUS_FIP_SIZE={expected_size}" not in out or expected_sha not in out.lower():
        raise RescueError("rescue Linux did not verify the transferred hybrid FIP; NAND untouched")
    print(f"[AUTO] Rescue Linux FIP verification PASS SHA256={expected_sha}")


def _install_persistent(sp, log, hybrid: Path) -> None:
    print("[AUTO] Starting RAM-Linux boot-area transaction; mtd0 write begins only after target-side preflight")
    rc, out = _linux_command(sp, log, "/usr/sbin/xg140-ursus-install /tmp/ursusboot.fip", 180.0)
    if rc != 0 or INSTALL_COMPLETE not in out:
        tail = out[-4000:].replace("\r", " | ").replace("\n", " | ")
        raise RescueError(f"persistent mtd0 transaction did not complete: rc={rc}; UART tail={tail!r}")
    expected_fip_sha = _sha256(hybrid)
    if expected_fip_sha not in out.lower():
        raise RescueError("persistent transaction completed without echoing the expected FIP SHA")
    print("[AUTO] PERSISTENT MTD0 WRITE + FULL READBACK PASS")


def _reboot_and_observe(sp, log, timeout: float = 90.0) -> bool:
    print("[AUTO] Rebooting from rescue initramfs after proven readback")
    sp.reset_input()
    base._send_line(sp, "sync; reboot -f")
    deadline = time.time() + timeout
    transcript = ""
    while time.time() < deadline:
        text = _read(sp, log, 0.25)
        if text:
            transcript = (transcript + text)[-131072:]
            low = transcript.lower()
            if any(marker.lower() in low for marker in PERSISTENT_MARKERS):
                print("\n[AUTO] Persistent UrsusBoot boot marker observed after reboot")
                return True
    print("\n[AUTO] Write/readback is proven, but persistent boot marker was not observed before timeout; no automatic rewrite will be attempted")
    return False


def main() -> int:
    cfg = base._load_local_config()
    host = str(base._value(None, cfg, "host", "XG140_HOST", base.HOST_DEFAULT))
    backup_raw = base._value(None, cfg, "backup", "XG140_MTD0_BACKUP")
    port_raw = base._value(None, cfg, "port", "XG140_COM", "auto")
    username = base._value(None, cfg, "tcboot_user", "XG140_TCBOOT_USER")
    password = base._value(None, cfg, "tcboot_password", "XG140_TCBOOT_PASSWORD")
    if not backup_raw:
        raise RescueError("no mtd0 backup configured in emergency.local.json")
    backup = Path(str(backup_raw)).expanduser().resolve()
    if not backup.is_file():
        raise RescueError(f"mtd0 backup not found: {backup}")

    root = HERE.parent
    rescue = _find_rescue(root)
    lzma_path = root / "u-boot.lzma"
    repacker = root / "repack_xg140_native_fip.py"
    for required in (rescue, lzma_path, repacker):
        if not required.is_file():
            raise RescueError(f"artifact is incomplete: {required.name} missing")

    print("=== XG140 EMERGENCY INITRAMFS BRIDGE ===")
    print(f"[AUTO] backup={backup}")
    print(f"[AUTO] rescue={rescue.name} size={rescue.stat().st_size} SHA256={_sha256(rescue)}")
    print("[AUTO] path: stock tcboot -> FIT/bootm -> RAM Linux -> hybrid mtd0 -> full readback")
    print("[AUTO] no y/N; no raw U-Boot go handoff")

    # If a correct UrsusBoot is already alive, retain the proven Web updater fast
    # path and avoid UART entirely.
    try:
        st = uw.status(host)
    except Exception:
        st = None

    with tempfile.TemporaryDirectory(prefix="xg140-rescue-") as td_raw:
        td = Path(td_raw)
        hybrid = td / "ursusboot-xg140-native-persistent.fip"
        base._build_hybrid(backup, repacker, lzma_path, hybrid)

        if st and st.get("product") == "UrsusBoot":
            print("[AUTO] UrsusBoot HTTP already alive; using device-side Web updater fast path")
            final = uw.update_bootloader(host, hybrid, confirm=False)
            if not final.get("operation_complete"):
                raise RescueError("UrsusBoot Web updater did not prove completion")
            print("[AUTO] PERSISTENT WRITE + READBACK PASS via UrsusBoot Web updater")
            return 0

        port = base._auto_port(str(port_raw) if port_raw is not None else None)
        proven.probe_serial_port(port)
        log_path = root / time.strftime("xg140-rescue-uart-%Y%m%d-%H%M%S.log")
        log = log_path.open("ab", buffering=0)
        sp = proven.RecoverySerial(port)
        try:
            base._acquire_tcboot(sp, log, str(username) if username else None,
                                 str(password) if password else None, base.UART_WAIT_SECONDS)
            _boot_rescue(sp, log, rescue)
            _wait_rescue_shell(sp, log)
            rc, ident = _linux_command(
                sp, log,
                "cat /etc/ursus-xg140-rescue-id; tr -d '\\000' < /proc/device-tree/model; grep '\"bootloader\"' /proc/mtd",
                15.0,
            )
            if rc != 0 or RESCUE_READY not in ident or RESCUE_BOARD not in ident or 'mtd0: 00080000' not in ident:
                raise RescueError("rescue Linux identity/geometry gate failed; NAND untouched")
            _send_hybrid_to_linux(sp, log, hybrid)
            _install_persistent(sp, log, hybrid)
            boot_seen = _reboot_and_observe(sp, log)
        finally:
            try:
                sp.close()
            finally:
                log.close()
        print(f"[AUTO] UART log: {log_path}")
        if boot_seen:
            print("[AUTO] DONE: write/readback + persistent boot marker PASS")
        else:
            print("[AUTO] DONE WITH BOOT CHECK PENDING: write/readback PASS; inspect UART log before any further write")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nXG140 rescue interrupted by operator", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"\nXG140 RESCUE FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)

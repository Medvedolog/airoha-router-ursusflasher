#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import proven_backend as proven
import ursus_web_client as uw
import xg140_native_persistent_install as native

HOST_DEFAULT = "192.168.1.1"
LOADADDR = 0x81E00000
HTTP_WAIT_SECONDS = 150
UART_WAIT_SECONDS = 600


class EmergencyError(RuntimeError):
    pass


def _load_local_config() -> dict:
    candidates = [
        HERE / "emergency.local.json",
        HERE.parent / "emergency.local.json",
    ]
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise EmergencyError(f"cannot read {path.name}: {exc}") from exc
            if not isinstance(data, dict):
                raise EmergencyError(f"{path.name} must contain a JSON object")
            return data
    return {}


def _value(args_value, cfg: dict, cfg_key: str, env_key: str, default=None):
    if args_value not in (None, ""):
        return args_value
    if cfg.get(cfg_key) not in (None, ""):
        return cfg[cfg_key]
    if os.environ.get(env_key) not in (None, ""):
        return os.environ[env_key]
    return default


def _windows_vcp_ports() -> list[str]:
    if os.name != "nt":
        return []
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
    except Exception:
        return []
    preferred = []
    fallback = []
    try:
        idx = 0
        while True:
            try:
                dev, port, _typ = winreg.EnumValue(key, idx)
            except OSError:
                break
            idx += 1
            port = str(port).upper()
            dev_l = str(dev).lower()
            if "bthmodem" in dev_l or "serial0" in dev_l:
                continue
            fallback.append(port)
            if any(token in dev_l for token in ("vcp", "usb", "ftdi", "silab", "cp210", "ch34", "prolific")):
                preferred.append(port)
    finally:
        try:
            winreg.CloseKey(key)
        except Exception:
            pass
    return preferred or fallback


def _auto_port(explicit: str | None) -> str:
    if explicit and explicit.lower() != "auto":
        return explicit.upper() if os.name == "nt" else explicit

    preferred = _windows_vcp_ports()
    if len(preferred) == 1:
        print(f"[AUTO] UART: {preferred[0]} (Windows VCP)")
        return preferred[0]

    ports = [str(p) for p in proven.list_serial_ports()]
    if os.name != "nt":
        usbish = [p for p in ports if "ttyUSB" in p or "ttyACM" in p]
        if len(usbish) == 1:
            print(f"[AUTO] UART: {usbish[0]}")
            return usbish[0]
    if len(ports) == 1:
        print(f"[AUTO] UART: {ports[0]}")
        return ports[0]

    if preferred:
        raise EmergencyError("more than one USB/VCP UART candidate: " + ", ".join(preferred) + "; set XG140_COM or emergency.local.json port")
    raise EmergencyError("UART port could not be selected uniquely; set XG140_COM or emergency.local.json port")


def _read_text(sp, log, timeout: float = 0.20) -> str:
    data = sp.read(4096, timeout)
    if not data:
        return ""
    log.write(data)
    log.flush()
    text = data.decode("utf-8", "replace")
    print(text, end="", flush=True)
    return text


def _send_line(sp, text: str = "") -> None:
    sp.write(text.encode("utf-8", "strict") + b"\r")


def _acquire_tcboot(sp, log, username: str | None, password: str | None, timeout: float) -> None:
    print("[AUTO] Waiting for stock tcboot. If stock Linux is already running, power-cycle the XG140 once; no keyboard input is required.")
    deadline = time.time() + timeout
    transcript = ""
    sent_user = False
    sent_password = False
    last_cr = 0.0
    announced_linux = False

    while time.time() < deadline:
        text = _read_text(sp, log, 0.20)
        if text:
            transcript = (transcript + text)[-65536:]
        low = transcript.lower()

        if "ecnt>" in low:
            print("\n[AUTO] tcboot ECNT> acquired")
            return

        if "hit any key to stop autoboot" in low:
            sp.write(b"\r")
            transcript = ""
            last_cr = time.time()
            sent_user = False
            sent_password = False
            continue

        # tcboot firmware has used both UserName: and Username: spellings.
        if ("username:" in low or "user name:" in low) and not sent_user:
            if not username:
                raise EmergencyError("tcboot requested a username but no local emergency credential is configured")
            _send_line(sp, username)
            sent_user = True
            transcript = ""
            continue

        if "password:" in low and sent_user and not sent_password:
            if not password:
                raise EmergencyError("tcboot requested a password but no local emergency credential is configured")
            _send_line(sp, password)
            sent_password = True
            transcript = ""
            continue

        if ("starting kernel" in low or "linux version" in low) and not announced_linux:
            print("\n[AUTO] Stock Linux started before tcboot was captured. Script remains armed; power-cycle once and it will catch autoboot.")
            announced_linux = True

        # A blank CR is harmless at stock console and exposes tcboot auth on builds
        # which do not print it until input arrives.
        now = time.time()
        if now - last_cr > 0.75:
            sp.write(b"\r")
            last_cr = now

    raise EmergencyError("tcboot was not acquired before emergency UART timeout")


def _ram_boot_ursus(sp, log, image: Path) -> None:
    print(f"[AUTO] XMODEM {image.name} -> RAM 0x{LOADADDR:x}")
    proven._uboot_wait_quiet(sp, log, quiet=0.15, timeout=1.0)
    sp.reset_input()
    proven._uboot_send_line(sp, f"loadx 0x{LOADADDR:x}")
    time.sleep(0.35)
    proven.xmodem_send(sp, image, image.name, log)
    proven._uboot_read_until_prompt(sp, log, 900, f"loadx {image.name}")
    print(f"[AUTO] Jumping to UrsusBoot at 0x{LOADADDR:x}")
    proven._uboot_send_line(sp, f"go 0x{LOADADDR:x}")
    # Do not wait for an ECNT prompt: control has intentionally left stock tcboot.
    time.sleep(2.0)


def _wait_ursus(host: str, timeout: float, label: str) -> dict | None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            st = uw.status(host)
            print(f"[AUTO] {label}: UrsusBoot HTTP ready version={st.get('version')!r} layout={st.get('current_layout')!r}")
            return st
        except Exception as exc:
            last_error = exc
            time.sleep(1.0)
    if last_error:
        print(f"[AUTO] {label}: HTTP not ready ({last_error})")
    return None


def _read_emergency_backup(path: Path) -> bytes:
    # Emergency mode intentionally does NOT require one pre-recorded 0x0..0x7ff
    # prefix SHA. The first 0x800 bytes are device/firmware specific and are not
    # used as the FIP donor. The device-side STOCK writer preserves the LIVE
    # prefix byte-for-byte. Keep structural gates that prove this is still an
    # XG140-style mtd0 donor: exact size, valid stock env CRC and Airoha FIP.
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rb") as f:
            boot = f.read()
    else:
        boot = path.read_bytes()
    if len(boot) != native.MTD0_SIZE:
        raise EmergencyError(f"mtd0 size mismatch: 0x{len(boot):x}, expected 0x{native.MTD0_SIZE:x}")
    prefix_sha = native.sha(boot[:native.FIP_OFF])
    print(f"[AUTO] donor BootROM prefix SHA256={prefix_sha} (informational; exact-match gate disabled in emergency mode)")
    env = boot[native.ENV_OFF:native.MTD0_SIZE]
    stored = struct.unpack_from("<I", env, 0)[0]
    calc = zlib.crc32(env[4:]) & 0xffffffff
    if stored != calc:
        raise EmergencyError(f"stock env CRC mismatch: stored={stored:08x} calc={calc:08x}")
    if boot[native.FIP_OFF:native.FIP_OFF + 8] != bytes.fromhex("010064aa78563412"):
        raise EmergencyError("Airoha FIP header not found at physical 0x800")
    return boot


def _build_hybrid(backup_path: Path, repacker: Path, lzma_path: Path, out_path: Path) -> None:
    boot = _read_emergency_backup(backup_path)
    donor, entries = native.validate_native_donor(boot)
    _check_entries, end = native.parse_fip(donor)
    print(f"[AUTO] mtd0 SHA256={native.sha(boot)}")
    print(f"[AUTO] donor FIP entries={len(entries)} size=0x{len(donor):x} declared_end=0x{end:x}")
    donor_path = out_path.parent / "xg140-stock-native.fip"
    donor_path.write_bytes(donor)
    subprocess.run([sys.executable, str(repacker), str(donor_path), str(lzma_path), str(out_path)], check=True)
    new = out_path.read_bytes()
    if len(new) >= native.ENV_OFF - native.FIP_OFF:
        raise EmergencyError(f"rebuilt FIP reaches protected env: size=0x{len(new):x}")
    native.compare_lineage(donor, new)
    print(f"[AUTO] hybrid FIP size=0x{len(new):x} SHA256={native.sha(new)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Unattended XG140 UART -> RAM UrsusBoot -> persistent native FIP emergency path")
    ap.add_argument("backup", nargs="?", help="this XG140 own mtd0_bootloader.bin or .bin.gz")
    ap.add_argument("--port", default=None, help="UART port; default auto")
    ap.add_argument("--host", default=None, help="UrsusBoot IPv4 address")
    ap.add_argument("--tcboot-user", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--tcboot-password", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--uart-timeout", type=float, default=UART_WAIT_SECONDS)
    ap.add_argument("--http-timeout", type=float, default=HTTP_WAIT_SECONDS)
    ap.add_argument("--no-reboot", action="store_true", help="do not reboot after proven readback")
    args = ap.parse_args()

    cfg = _load_local_config()
    host = str(_value(args.host, cfg, "host", "XG140_HOST", HOST_DEFAULT))
    backup_raw = _value(args.backup, cfg, "backup", "XG140_MTD0_BACKUP")
    port_raw = _value(args.port, cfg, "port", "XG140_COM", "auto")
    username = _value(args.tcboot_user, cfg, "tcboot_user", "XG140_TCBOOT_USER")
    password = _value(args.tcboot_password, cfg, "tcboot_password", "XG140_TCBOOT_PASSWORD")

    if not backup_raw:
        raise EmergencyError("no mtd0 backup path configured; pass it as the first argument or set emergency.local.json backup")
    backup = Path(str(backup_raw)).expanduser().resolve()
    if not backup.is_file():
        raise EmergencyError(f"mtd0 backup not found: {backup}")

    root = HERE.parent
    uboot = root / "u-boot.bin"
    lzma_path = root / "u-boot.lzma"
    repacker = root / "repack_xg140_native_fip.py"
    for required in (uboot, lzma_path, repacker):
        if not required.is_file():
            raise EmergencyError(f"artifact is incomplete: {required.name} missing")

    print("=== XG140 EMERGENCY AUTO ===")
    print(f"[AUTO] host={host}")
    print(f"[AUTO] backup={backup}")
    print("[AUTO] no y/N; machine invariants and target readback remain mandatory")

    with tempfile.TemporaryDirectory(prefix="xg140-emergency-") as td_raw:
        td = Path(td_raw)
        hybrid = td / "ursusboot-xg140-native-persistent.fip"
        _build_hybrid(backup, repacker, lzma_path, hybrid)

        # Fast path: if the correct RAM/persistent UrsusBoot is already alive,
        # do not touch UART at all.
        st = _wait_ursus(host, 3.0, "probe")
        if st is None:
            port = _auto_port(str(port_raw) if port_raw is not None else None)
            proven.probe_serial_port(port)
            log_path = root / time.strftime("xg140-emergency-uart-%Y%m%d-%H%M%S.log")
            log = log_path.open("ab", buffering=0)
            sp = proven.RecoverySerial(port)
            try:
                _acquire_tcboot(sp, log, str(username) if username else None,
                                str(password) if password else None, args.uart_timeout)
                _ram_boot_ursus(sp, log, uboot)
            finally:
                try:
                    sp.close()
                finally:
                    log.close()
            print(f"[AUTO] UART log: {log_path}")

            st = _wait_ursus(host, args.http_timeout, "post-RAM-boot")
            if st is None:
                raise EmergencyError("UrsusBoot HTTP did not appear after automatic RAM boot; persistent flash was not touched")

        # Deliberately no operator confirmation and no host-side model/version
        # ceremony here. update_bootloader still performs the bootloader's own
        # candidate validation, starts exactly one STOCK writer and waits until
        # its full readback operation reports complete or failed.
        print("[AUTO] Uploading native-hybrid FIP and starting persistent mtd0 transaction")
        final = uw.update_bootloader(host, hybrid, confirm=False)
        stage = final.get("operation_stage")
        tx = final.get("operation_transaction_state")
        if not final.get("operation_complete"):
            raise EmergencyError(f"persistent transaction did not prove completion: stage={stage!r} transaction={tx!r}")
        print(f"[AUTO] PERSISTENT WRITE + READBACK PASS stage={stage!r} transaction={tx!r}")

        if not args.no_reboot:
            print("[AUTO] Rebooting after proven readback")
            uw.reboot(host)
        print("[AUTO] DONE")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nEMERGENCY AUTO interrupted by operator", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"\nEMERGENCY AUTO FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)

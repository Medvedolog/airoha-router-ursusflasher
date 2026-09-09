#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import socket
import time
from pathlib import Path

import proven_backend as proven

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
PAYLOAD_DIR = HERE / "payloads" / "mf" / "ursusboot"
PRELOADER = PAYLOAD_DIR / "ursusboot-mf-0.1.0-mf2-ram1-uart-preloader.bin"
FIP = PAYLOAD_DIR / "ursusboot-mf-0.1.0-mf2-ram1-ram.fip"
PRELOADER_SIZE = 118322
PRELOADER_SHA256 = "c2ac1c183b18bc34632c958dfe0bd1dfdfb607f090e39c41126956641893362f"
# HWTEST6 network-restore baseline: HWTEST4 pinmux only, no HWTEST5 PBUS/MMD LED writes.
FIP_SIZE = 293816
FIP_SHA256 = "439026f4068f3ea0a9db259e4fc9ea1f23407f8ff94d29e7fd0ccbdbf5df31d1"

IDENTITY_VERSION = b"0.1.0-mf2-ram1+g4267f0f3"
IDENTITY_BOARD = b"Nokia XG-040G-MF"
IDENTITY_SOC = b"AN7583"
READY_MARKERS = (b"URSUS_WEBFAILSAFE_READY", b"URSUS_HTTP_LISTEN_OK port=80")
LED_MARKER = b"URSUS_MF2_LED_RECOVERY_PATTERN"
HTTP_HOST = "192.168.1.1"
HTTP_PORT = 80


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path: Path, size: int, digest: str, label: str) -> None:
    if not path.is_file():
        raise proven.Error(f"{label} missing: {path}")
    if path.stat().st_size != size:
        raise proven.Error(f"{label} size mismatch: {path.stat().st_size} != {size}")
    actual = sha256(path)
    if actual != digest:
        raise proven.Error(f"{label} SHA256 mismatch: {actual} != {digest}")


def choose_port() -> str:
    ports = proven.list_serial_ports()
    if ports:
        print("\nUART ports:")
        for index, port in enumerate(ports, 1):
            print(f"  {index}. {port}")
    raw = input("UART port or list number: ").strip()
    if raw.isdigit() and ports and 1 <= int(raw) <= len(ports):
        return ports[int(raw) - 1]
    return raw.upper() if os.name == "nt" else raw


def _seen(tail: bytes, marker: bytes) -> bool:
    return marker.lower() in tail.lower()


def wait_host_http(attempts: int = 10, delay: float = 0.5) -> tuple[bool, str]:
    last_error = ""
    for _ in range(attempts):
        try:
            with socket.create_connection((HTTP_HOST, HTTP_PORT), timeout=1.0):
                return True, ""
        except OSError as exc:
            last_error = str(exc)
            time.sleep(delay)
    return False, last_error


def main() -> int:
    print("UrsusBoot-MF MF2 HWTEST6 RAMBOOT / READ-ONLY NETWORK RESTORE")
    print("Nokia XG-040G-MF / Airoha AN7583")
    print("No erase/write/saveenv operation is issued by this launcher.\n")
    verify(PRELOADER, PRELOADER_SIZE, PRELOADER_SHA256, "AN7583 UART preloader")
    verify(FIP, FIP_SIZE, FIP_SHA256, "UrsusBoot-MF MF2 HWTEST6 RAM FIP")
    print(f"[OK] preloader SHA256 {PRELOADER_SHA256}")
    print(f"[OK] MF2 FIP SHA256   {FIP_SHA256}")

    port = choose_port()
    if not port:
        raise proven.Error("UART port was not specified")
    proven.probe_serial_port(port)
    results = KIT / "results"
    results.mkdir(exist_ok=True)
    log_path = results / time.strftime("mf2-ramboot-%Y%m%d-%H%M%S-uart.log")

    serial_port = proven.RecoverySerial(port)
    try:
        with log_path.open("ab", buffering=0) as log:
            print("\n[READY] Hold Reset BEFORE power-on, power the router, and keep Reset held.")
            print("Press x / repeated C is detected automatically. VCC from USB-UART must NOT be connected.")
            proven.wait_bootrom_xmodem(serial_port, log, "AN7583 preloader", discard_stale=False)
            proven.xmodem_send(serial_port, PRELOADER, "UrsusBoot-MF AN7583 preloader (RAM)", log)
            proven.wait_bootrom_xmodem(serial_port, log, "UrsusBoot-MF MF2 FIP")
            proven.xmodem_send(serial_port, FIP, "UrsusBoot-MF MF2 BL31+U-Boot FIP (RAM)", log)

            print("\n[TRANSFER COMPLETE] MF2 was delivered to RAM.")
            print("Monitoring UART through WebFailsafe startup; UART listen markers alone are not treated as network PASS.")
            deadline = time.time() + 120
            tail = b""
            version_seen = False
            board_seen = False
            soc_seen = False
            led_seen = False
            web_ready = False
            http_ready = False

            while time.time() < deadline:
                data = serial_port.read(4096, 0.5)
                if not data:
                    continue
                log.write(data)
                log.flush()
                print(data.decode("utf-8", "replace"), end="", flush=True)
                tail = (tail + data)[-65536:]
                version_seen = version_seen or _seen(tail, IDENTITY_VERSION)
                board_seen = board_seen or _seen(tail, IDENTITY_BOARD)
                soc_seen = soc_seen or _seen(tail, IDENTITY_SOC)
                led_seen = led_seen or _seen(tail, LED_MARKER)
                web_ready = web_ready or _seen(tail, READY_MARKERS[0])
                http_ready = http_ready or _seen(tail, READY_MARKERS[1])
                if web_ready and http_ready:
                    break

            print("\n")
            identity_ok = version_seen and (board_seen or soc_seen)
            if identity_ok:
                print("[PASS] UrsusBoot-MF HWTEST6 identity observed on UART.")
            else:
                print("[CHECK REQUIRED] HWTEST6 identity was not fully observed on UART.")

            if led_seen:
                print("[PASS] Native-DM MF2 recovery LED sequence was started.")
            else:
                print("[INFO] Native-DM MF2 recovery LED marker was not observed in this build/log.")

            host_http_ok = False
            if web_ready and http_ready:
                print("[PASS] UART reports WebFailsafe listen state at 192.168.1.1:80.")
                print("[CHECK] Verifying TCP/80 reachability from this computer...")
                host_http_ok, error = wait_host_http()
                if host_http_ok:
                    print("[PASS] Host TCP connection to 192.168.1.1:80 succeeded.")
                    print("Continue LAN2/LAN3 acceptance without writing NAND.")
                else:
                    print(f"[CHECK REQUIRED] UART says HTTP is listening but host TCP/80 is unreachable: {error}")
                    print("This is a network-path failure; do not count UART listen markers alone as Web PASS.")
            else:
                print("[CHECK REQUIRED] WebFailsafe-ready markers were not observed within 120 s.")
                print("Do not write NAND. Keep the UART log for analysis.")

            print(f"UART log: {log_path}")
            return 0 if identity_ok and web_ready and http_ready and host_http_ok else 2
    finally:
        serial_port.close()


if __name__ == "__main__":
    raise SystemExit(main())

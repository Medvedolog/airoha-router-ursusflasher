#!/usr/bin/env python3
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import xg140_emergency_persistent as emergency


def _ram_boot_ursus_observed(sp, log, image: Path) -> None:
    print(f"[AUTO] XMODEM {image.name} -> RAM 0x{emergency.LOADADDR:x}")
    emergency.proven._uboot_wait_quiet(sp, log, quiet=0.15, timeout=1.0)
    sp.reset_input()
    emergency.proven._uboot_send_line(sp, f"loadx 0x{emergency.LOADADDR:x}")
    time.sleep(0.35)
    emergency.proven.xmodem_send(sp, image, image.name, log)

    # xmodem_send can consume the ECNT> emitted immediately after EOT/ACK.
    # Ask stock tcboot for one fresh prompt before issuing go.
    time.sleep(0.20)
    sp.write(b"\r")
    deadline = time.time() + 5.0
    transcript = ""
    while time.time() < deadline:
        text = emergency._read_text(sp, log, 0.20)
        if text:
            transcript = (transcript + text)[-4096:]
        if "ecnt>" in transcript.lower():
            break
    else:
        raise emergency.EmergencyError(
            "successful XMODEM transfer, but fresh tcboot ECNT> was not observed after EOT; NAND untouched"
        )

    print("[AUTO] Fresh tcboot ECNT> confirmed after XMODEM")
    print(f"[AUTO] Jumping to UrsusBoot at 0x{emergency.LOADADDR:x}")
    sp.reset_input()
    emergency.proven._uboot_send_line(sp, f"go 0x{emergency.LOADADDR:x}")

    # Observe the execution handoff instead of closing UART blindly. A pending
    # character can abort the new U-Boot autoboot and leave it at UrsusBoot>;
    # if that happens start WebFailsafe explicitly. Conversely, ECNT> after go
    # proves that control returned to stock tcboot.
    deadline = time.time() + 25.0
    transcript = ""
    saw_ursus = False
    sent_ursusweb = False
    while time.time() < deadline:
        text = emergency._read_text(sp, log, 0.25)
        if text:
            transcript = (transcript + text)[-32768:]
        low = transcript.lower()

        if "webfailsafe started" in low or "ursusboot 0.1.0-xg140-native1: http://" in low:
            print("\n[AUTO] UART confirmed UrsusBoot WebFailsafe")
            return

        if "ursusboot" in low or "u-boot 2026.07-ursusboot" in low:
            saw_ursus = True

        if "ursusboot>" in low and not sent_ursusweb:
            print("\n[AUTO] UrsusBoot prompt reached; starting WebFailsafe explicitly")
            emergency.proven._uboot_send_line(sp, "ursusweb")
            sent_ursusweb = True
            transcript = ""
            deadline = max(deadline, time.time() + 20.0)
            continue

        if "ecnt>" in low and not saw_ursus:
            tail = transcript[-1200:].replace("\r", " ").replace("\n", " | ")
            raise emergency.EmergencyError(
                "tcboot ECNT> returned after go 0x81e00000; UrsusBoot did not take control; "
                f"UART tail={tail!r}; NAND untouched"
            )

        if ("unknown command" in low or "command not found" in low) and not saw_ursus:
            tail = transcript[-1200:].replace("\r", " ").replace("\n", " | ")
            raise emergency.EmergencyError(
                f"tcboot rejected RAM jump command; UART tail={tail!r}; NAND untouched"
            )

    if saw_ursus:
        print("\n[AUTO] UrsusBoot startup was seen on UART; continuing with HTTP identity probe")
        return
    print("\n[AUTO] No conclusive UART banner after go; continuing with HTTP probe, UART log retained")


def main() -> int:
    emergency._ram_boot_ursus = _ram_boot_ursus_observed
    return emergency.main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nEMERGENCY AUTO interrupted by operator", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"\nEMERGENCY AUTO FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)

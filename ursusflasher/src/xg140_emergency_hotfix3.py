#!/usr/bin/env python3
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import xg140_emergency_persistent as emergency


def _ram_boot_ursus_ecnt(sp, log, image: Path) -> None:
    print(f"[AUTO] XMODEM {image.name} -> RAM 0x{emergency.LOADADDR:x}")
    emergency.proven._uboot_wait_quiet(sp, log, quiet=0.15, timeout=1.0)
    sp.reset_input()
    emergency.proven._uboot_send_line(sp, f"loadx 0x{emergency.LOADADDR:x}")
    time.sleep(0.35)
    emergency.proven.xmodem_send(sp, image, image.name, log)

    # xmodem_send may consume the ECNT> bytes printed immediately after
    # EOT/ACK. Force stock tcboot to emit a fresh prompt with a harmless CR.
    # The generic RAM-U-Boot prompt detector cannot be used here because stock
    # tcboot uses ECNT>, not AN7581>/U-Boot>/UrsusBoot>.
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
    emergency.proven._uboot_send_line(sp, f"go 0x{emergency.LOADADDR:x}")
    time.sleep(2.0)


def main() -> int:
    emergency._ram_boot_ursus = _ram_boot_ursus_ecnt
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

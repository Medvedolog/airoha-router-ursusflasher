#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ursus_web_client as uw

HOST = "192.168.1.1"
EXPECTED_PREFIX_SHA256 = "82830140f4f8842702d0569065c27071b7cc24e0876e6c487cb4d9d81c294dd7"
EXPECTED_TB_FW_SHA256 = "07c9e1542a3de845055faa2244bbd07adc8c5a136811a61a0d678ec8fff5ee5e"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_payload() -> Path:
    roots = [HERE, HERE.parent, HERE.parent.parent, Path.cwd()]
    names = ["ursusboot-xg140-0.1.0-xg140-persist1-update.fip"]
    for root in roots:
        for name in names:
            p = (root / name).resolve()
            if p.is_file():
                return p
    raw = input("Path to ursusboot-xg140-0.1.0-xg140-persist1-update.fip: ").strip().strip('"')
    p = Path(raw).expanduser().resolve()
    if not p.is_file():
        raise SystemExit(f"Persistent FIP not found: {p}")
    return p


def require_xg140_ram_state(st: dict) -> None:
    if st.get("product") != "UrsusBoot":
        raise SystemExit("Target is not UrsusBoot")
    version = str(st.get("version") or "")
    board = " ".join(str(st.get(k) or "") for k in ("board", "model", "board_name", "compatible"))
    if "xg140" not in version.lower() and "xg-140g" not in board.lower() and "140g" not in board.lower():
        raise SystemExit(f"XG140 identity not confirmed: version={version!r} board={board!r}")
    if st.get("current_layout") != "STOCK":
        raise SystemExit(f"Expected STOCK layout before persistent install, got {st.get('current_layout')!r}")
    storage = str(st.get("bootloader_update_layout") or "")
    if storage and storage != "STOCK":
        raise SystemExit(f"Bootloader updater does not report STOCK storage: {storage!r}")


def main() -> int:
    payload = find_payload()
    data = payload.read_bytes()
    if data[:8] != bytes.fromhex("010064aa78563412"):
        raise SystemExit("Persistent FIP header mismatch")
    if len(data) >= (0x7C000 - 0x800):
        raise SystemExit(f"Persistent FIP overlaps protected stock env window: 0x{len(data):x}")

    print("XG-140G-MD persistent UrsusBoot installer")
    print("Write scope: stock bootloader FIP window only; prefix 0x0..0x7ff and env 0x7c000..0x7ffff must remain unchanged.")
    print(f"Payload: {payload}")
    print(f"Size: 0x{len(data):x}")
    print(f"SHA256: {sha256(payload)}")
    print(f"Expected BootROM prefix SHA256: {EXPECTED_PREFIX_SHA256}")
    print(f"Expected early-boot TB_FW SHA256: {EXPECTED_TB_FW_SHA256}\n")

    st = uw.status(HOST)
    require_xg140_ram_state(st)
    print("Preflight: XG140 RAM UrsusBoot + STOCK layout confirmed.")
    print("Uploading candidate to RAM for UrsusBoot-side validation...")

    # update_bootloader performs the only operator confirmation and invokes the
    # transactional STOCK updater in UrsusBoot. No separate second confirmation.
    final = uw.update_bootloader(HOST, payload, confirm=True)

    result = {
        "version": final.get("version"),
        "current_layout": final.get("current_layout"),
        "bootloader_update_layout": final.get("bootloader_update_layout"),
        "bootloader_update_complete": final.get("bootloader_update_complete"),
        "bootloader_update_failed": final.get("bootloader_update_failed"),
        "bootloader_update_stage": final.get("bootloader_update_stage"),
        "bootloader_update_error": final.get("bootloader_update_error"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not final.get("bootloader_update_complete") or final.get("bootloader_update_failed"):
        raise SystemExit("Persistent bootloader transaction did not finish successfully")
    if str(final.get("bootloader_update_layout") or "") not in ("", "STOCK"):
        raise SystemExit("Updater completed but storage class was not STOCK")

    print("\nPersistent UrsusBoot write/readback completed.")
    print("Reboot the router. Expected next boot: UrsusBoot 0.1.0-xg140-persist1, not tcboot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

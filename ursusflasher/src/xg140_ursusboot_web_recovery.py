#!/usr/bin/env python3
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ursus_web_client as uw

HOST = "192.168.1.1"


def choose_image() -> Path:
    raw = input("Path to Bell XG-140G-MD sysupgrade (.bin/.itb): ").strip().strip('"')
    p = Path(raw).expanduser().resolve()
    if not p.is_file():
        raise SystemExit(f"Image not found: {p}")
    name = p.name.lower()
    if "xg-140g-md" not in name and "xg140" not in name:
        answer = input("Filename does not identify XG-140G-MD. Continue to bootloader validation? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            raise SystemExit("Cancelled before upload")
    return p


def wait_ursusboot(timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            st = uw.status(HOST)
            version = str(st.get("version") or "")
            model = str(st.get("model") or st.get("board") or "")
            if "xg140" not in version.lower() and "140g" not in model.lower():
                raise RuntimeError(f"Unexpected UrsusBoot identity: version={version!r} model={model!r}")
            return st
        except Exception as exc:
            last = exc
            time.sleep(1.0)
    raise SystemExit(f"UrsusBoot WebFailsafe did not become ready at http://{HOST}/: {last}")


def main() -> int:
    print("XG-140G-MD UrsusBoot RAM recovery -> stock-layout OpenWrt sysupgrade")
    print("This helper never installs BL2/preloader. The stock tcboot boot area is outside this operation.\n")
    image = choose_image()
    print(f"Waiting for XG140 UrsusBoot at {HOST}:80 ...")
    st = wait_ursusboot()
    print(f"UrsusBoot ready: version={st.get('version')} layout={st.get('current_layout')}")
    if st.get("current_layout") not in ("STOCK", "OPENWRT_STOCK_LAYOUT"):
        raise SystemExit(f"Unexpected layout for this recovery path: {st.get('current_layout')!r}")
    print(f"Uploading {image.name} to RAM for bootloader-side validation...")
    # preloader=None is deliberate: XG140 RAM recovery must not migrate BL2.
    final = uw.update_firmware(HOST, image, confirm=True, preloader=None, keep_settings=False)
    print(f"Completed: stage={final.get('operation_stage')} transaction={final.get('operation_transaction_state')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

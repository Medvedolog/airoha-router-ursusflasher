#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(script: Path, root: Path) -> None:
    subprocess.check_call([sys.executable, str(script), str(root)])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    args = ap.parse_args()
    root = args.source_root.resolve()
    here = Path(__file__).resolve().parent
    dts = root / "arch/arm/dts/an7583-nokia-xg-040g-mf.dts"
    eth = root / "drivers/net/airoha_eth.c"
    cmd = root / "cmd/ursusmfphy.c"
    if not dts.is_file() or not eth.is_file():
        raise SystemExit("MF board source is incomplete")

    text = dts.read_text(encoding="utf-8")
    if "URSUS_MF2_LAN23_LED_PINMUX" not in text:
        run(here / "mf2_lan23_led_pinmux.py", root)
        text = dts.read_text(encoding="utf-8")
    if "URSUS_MF2_HWTEST7_LAN234_LED_PINMUX" not in text or not cmd.is_file():
        run(here / "mf2_hwtest7_phy_probe.py", root)
    if "URSUS_MF2_HWTEST8_LED_FIX" not in eth.read_text(encoding="utf-8"):
        run(here / "mf2_hwtest8_led_fix.py", root)

    text = dts.read_text(encoding="utf-8")
    eth_text = eth.read_text(encoding="utf-8")
    for token in (
        'function = "phy2_led0";', 'pins = "gpio2";',
        'function = "phy3_led0";', 'pins = "gpio3";',
        'function = "phy4_led0";', 'pins = "gpio4";',
        "URSUS_MF2_HWTEST7_LAN234_LED_PINMUX",
    ):
        if token not in text:
            raise SystemExit(f"MF HWTEST8 DTS invariant missing: {token}")
    for token in (
        "URSUS_MF2_HWTEST8_LED_FIX",
        "static const u8 phys[] = { 0x0a, 0x0b, 0x0c };",
        "URSUS_MF2_HWTEST8_ON_MASK          0xc07f",
        "URSUS_MF2_HWTEST8_ON_SET           0xc007",
        "URSUS_MF2_HWTEST8_BLINK_MASK       0x03ff",
        "URSUS_MF2_HWTEST8_BLINK_SET        0x003f",
        "URSUS_MF2_HWTEST8_LED_END result=OK",
    ):
        if token not in eth_text:
            raise SystemExit(f"MF HWTEST8 Ethernet invariant missing: {token}")
    print("MF_BOARD_HWTEST8=PASS lan2=0x0a/gpio2 lan3=0x0b/gpio3 lan4=0x0c/gpio4 backend=native-c45-rmw")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

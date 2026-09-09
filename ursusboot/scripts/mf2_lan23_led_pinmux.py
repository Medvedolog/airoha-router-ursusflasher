#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def patch(root: Path) -> None:
    dts = root / "arch/arm/dts/an7583-nokia-xg-040g-mf.dts"
    if not dts.is_file():
        raise SystemExit(f"missing MF board DTS: {dts}")

    text = dts.read_text(encoding="utf-8")
    marker = "URSUS_MF2_LAN23_LED_PINMUX"
    if marker in text:
        raise SystemExit("MF2 LAN2/LAN3 LED pinmux already applied")

    pattern = r'&gdm1\s*\{\s*status\s*=\s*"okay";\s*\};'
    match = re.search(pattern, text, flags=re.S)
    if not match:
        raise SystemExit("MF board DTS gdm1 anchor not found")

    replacement = '''/* URSUS_MF2_LAN23_LED_PINMUX
 * Hardware evidence from OpenWrt on Nokia XG-040G-MF:
 *   LAN2 = AN7583 internal GPHY2 / MT7530-MMIO, LED0 on gpio2
 *   LAN3 = AN7583 internal GPHY3 / MT7530-MMIO, LED0 on gpio3
 * LAN1 is the separate EN8811H path and is deliberately out of scope.
 * LAN4 remains deferred for MF2 acceptance.
 *
 * Use the native AN7583 pinctrl functions already implemented by U-Boot.
 * No AN7581 SCU/MT7531 raw-MMIO LED programming is used here.
 */
&an7583_pinctrl {
\tursus_gswp2_led0_pins: ursus-gswp2-led0-pins {
\t\tmux {
\t\t\tfunction = "phy2_led0";
\t\t\tpins = "gpio2";
\t\t};
\t};

\tursus_gswp3_led0_pins: ursus-gswp3-led0-pins {
\t\tmux {
\t\t\tfunction = "phy3_led0";
\t\t\tpins = "gpio3";
\t\t};
\t};
};

&gdm1 {
\tstatus = "okay";
\tpinctrl-names = "default";
\tpinctrl-0 = <&ursus_gswp2_led0_pins>, <&ursus_gswp3_led0_pins>;
};'''

    text = text[:match.start()] + replacement + text[match.end():]
    dts.write_text(text, encoding="utf-8")

    out = dts.read_text(encoding="utf-8")
    required = (
        marker,
        'function = "phy2_led0";',
        'pins = "gpio2";',
        'function = "phy3_led0";',
        'pins = "gpio3";',
        'pinctrl-names = "default";',
        '<&ursus_gswp2_led0_pins>, <&ursus_gswp3_led0_pins>',
    )
    for token in required:
        if token not in out:
            raise SystemExit(f"MF2 LAN LED pinmux marker missing after patch: {token}")

    forbidden = ('function = "phy1_led0";', 'function = "phy4_led0";')
    for token in forbidden:
        if token in out:
            raise SystemExit(f"MF2 LAN LED pinmux touched out-of-scope port: {token}")

    print("MF2_LAN23_LED_PINMUX=PASS gpio2=phy2_led0 gpio3=phy3_led0 lan1=untouched lan4=untouched")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    args = ap.parse_args()
    patch(args.source_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

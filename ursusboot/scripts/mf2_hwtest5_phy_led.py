#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def _find_powerdown_anchor(root: Path) -> tuple[Path, str]:
    matches: list[tuple[Path, str]] = []
    needle = "phy_clear_bits(phydev, MII_BMCR, BMCR_PDOWN);"
    for path in (root / "drivers" / "net").rglob("*.c"):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if needle in text:
            matches.append((path, text))
    if len(matches) != 1:
        shown = ", ".join(str(p.relative_to(root)) for p, _ in matches[:12]) or "none"
        raise SystemExit(f"AN7583 PHY BMCR_PDOWN anchor count={len(matches)}: {shown}")
    return matches[0]


def patch(root: Path) -> None:
    path, text = _find_powerdown_anchor(root)
    marker = "URSUS_MF2_HWTEST5_PHY_LED0"
    if marker in text:
        raise SystemExit("HWTEST5 PHY LED patch already applied")

    anchor = """    ret = phy_clear_bits(phydev, MII_BMCR, BMCR_PDOWN);\n    if (ret)\n        return ret;\n"""
    if text.count(anchor) != 1:
        raise SystemExit(
            f"AN7583 PHY powerdown sequence count={text.count(anchor)} in {path.relative_to(root)}"
        )

    insert = anchor + """

    /* URSUS_MF2_HWTEST5_PHY_LED0
     * Nokia XG-040G-MF routes LAN2/LAN3 RJ45 LEDs from the internal GPHY
     * LED0 outputs through gpio2/gpio3. TEST4 proved pinmux alone is not
     * sufficient: the LED may latch and activity does not blink.
     *
     * Program the MediaTek SoC PHY vendor LED block. LED0 is active-low,
     * ON for negotiated 10/100/1000 link and BLINK for TX/RX activity.
     * PHY MMD registers are volatile: no NAND/environment write is performed.
     */
    ret = phy_modify_mmd(phydev, MDIO_MMD_VEND2, 0x24,
                         0xc07f, 0xc007);
    if (ret)
        return ret;
    ret = phy_modify_mmd(phydev, MDIO_MMD_VEND2, 0x25,
                         0x03ff, 0x003f);
    if (ret)
        return ret;

    printf("URSUS_MF2_HWTEST5_PHY_LED0 phy=%d on=link10/100/1000 blink=txrx polarity=active-low\\n",
           phydev->addr);
"""

    out = text.replace(anchor, insert, 1)
    path.write_text(out, encoding="utf-8")

    verify = path.read_text(encoding="utf-8")
    required = (
        marker,
        "phy_modify_mmd(phydev, MDIO_MMD_VEND2, 0x24",
        "0xc07f, 0xc007",
        "phy_modify_mmd(phydev, MDIO_MMD_VEND2, 0x25",
        "0x03ff, 0x003f",
        "polarity=active-low",
    )
    for token in required:
        if token not in verify:
            raise SystemExit(f"HWTEST5 PHY LED marker missing after patch: {token}")

    print(f"MF2_HWTEST5_PHY_LED=PASS driver={path.relative_to(root)} anchor=BMCR_PDOWN")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    args = ap.parse_args()
    patch(args.source_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

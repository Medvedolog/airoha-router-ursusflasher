#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def patch(root: Path) -> None:
    candidates = (
        root / "drivers/net/phy/mediatek/mtk-ge-soc.c",
        root / "drivers/net/phy/mediatek-ge-soc.c",
    )
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise SystemExit("AN7583 MediaTek SoC PHY driver not found")

    text = path.read_text(encoding="utf-8")
    marker = "URSUS_MF2_HWTEST5_PHY_LED0"
    if marker in text:
        raise SystemExit("HWTEST5 PHY LED patch already applied")

    pattern = (
        r"static int an7583_phy_config_init\(struct phy_device \*phydev\)\n"
        r"\{.*?\n\}"
    )
    match = re.search(pattern, text, flags=re.S)
    if not match:
        raise SystemExit(f"AN7583 config_init anchor not found in {path}")

    replacement = r'''static int an7583_phy_config_init(struct phy_device *phydev)
{
    int ret;

    /* AN7583 internal GPHYs power up with BMCR_PDOWN set. */
    ret = phy_clear_bits(phydev, MII_BMCR, BMCR_PDOWN);
    if (ret)
        return ret;

    /* URSUS_MF2_HWTEST5_PHY_LED0
     * Nokia XG-040G-MF routes LAN2/LAN3 RJ45 LEDs from the internal GPHY
     * LED0 outputs through gpio2/gpio3.  TEST4 proved that pinmux alone is
     * insufficient: LED state can latch and activity does not blink.
     *
     * Program the same MDIO_MMD_VEND2 LED block used by the Linux MediaTek
     * SoC PHY driver.  LED0 is active-low on this board, ON for negotiated
     * 10/100/1000 link and BLINK for TX/RX activity at all three speeds.
     * This changes PHY volatile registers only; no flash/environment write.
     */
    ret = phy_modify_mmd(phydev, MDIO_MMD_VEND2, 0x24,
                         0xc07f, 0xc007);
    if (ret)
        return ret;
    ret = phy_modify_mmd(phydev, MDIO_MMD_VEND2, 0x25,
                         0x03ff, 0x003f);
    if (ret)
        return ret;

    printf("URSUS_MF2_HWTEST5_PHY_LED0 phy=%d on=link10/100/1000 blink=txrx polarity=active-low\n",
           phydev->addr);
    return 0;
}'''

    out = text[:match.start()] + replacement + text[match.end():]
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

    print(f"MF2_HWTEST5_PHY_LED=PASS driver={path.relative_to(root)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    args = ap.parse_args()
    patch(args.source_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

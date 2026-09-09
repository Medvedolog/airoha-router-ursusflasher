#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def patch(root: Path) -> None:
    path = root / "drivers/net/airoha_eth.c"
    if not path.is_file():
        raise SystemExit(f"missing Airoha ethernet driver: {path}")

    text = path.read_text(encoding="utf-8")
    marker = "URSUS_MF2_HWTEST5_PHY_LED0"
    if marker in text:
        raise SystemExit("HWTEST5 PHY LED patch already applied")

    # TEST61 uses the AN7583 PBUS switch path, not an upstream MediaTek PHY
    # driver.  Keep the existing proven BMCR_PDOWN sequence and add only the
    # Clause-22-indirect MMD accesses required for the two hardware LEDs.
    init_anchor = "static int airoha_switch_init(struct udevice *dev, struct airoha_eth *eth)\n"
    if text.count(init_anchor) != 1:
        raise SystemExit(f"airoha_switch_init anchor count={text.count(init_anchor)}")

    helpers = r'''/* URSUS_MF2_HWTEST5_PHY_LED0
 * AN7583 internal GPHY LED registers are MediaTek-compatible MMD VEND2
 * registers.  The switch PBUS exposed here already performs Clause 22
 * accesses for BMCR, so use the standard Clause-22 MMD indirect sequence
 * (0x0d/0x0e) instead of inventing a second MDIO backend.
 *
 * Nokia XG-040G-MF Linux DTS proves:
 *   LAN2 = gsw_phy2 / phy2_led0 / active-low
 *   LAN3 = gsw_phy3 / phy3_led0 / active-low
 * The PBUS PHY loop is zero-based (0..3 => PHY1..PHY4), hence only ports
 * 1 and 2 are modified here.  LAN1/EN8811 and LAN4 remain untouched.
 */
#define URSUS_MF2_MII_MMD_CTRL          0x0d
#define URSUS_MF2_MII_MMD_DATA          0x0e
#define URSUS_MF2_MII_MMD_NOINCR        0x4000
#define URSUS_MF2_MMD_VEND2             0x1f
#define URSUS_MF2_LED0_ON_CTRL           0x24
#define URSUS_MF2_LED0_BLINK_CTRL        0x25
#define URSUS_MF2_LED_ON_LINK_MASK       0x0007
#define URSUS_MF2_LED_ON_CLEAR_MASK      0x007f
#define URSUS_MF2_LED_ON_POLARITY_LOW    0x4000
#define URSUS_MF2_LED_BLINK_TXRX_ALL     0x003f

static int ursus_mf2_pbus_wait(struct airoha_eth *eth)
{
    int try;
    u32 val;

    for (try = 0; try < AIROHA_MAX_PBUS_TRY; try++) {
        val = airoha_switch_rr(eth, SWITCH_PBUS_PHY_IAC);
        if (!(val & SWITCH_PBUS_PHY_START))
            return 0;
        udelay(AIROHA_PBUS_SLEEP);
    }

    return -ETIMEDOUT;
}

static int ursus_mf2_pbus_c22_read(struct airoha_eth *eth, int port,
                                   u16 reg, u16 *value)
{
    int ret;

    airoha_switch_wr(eth, SWITCH_PBUS_PHY_IAC,
                     SWITCH_PBUS_PHY_START |
                     SWITCH_PBUS_PHY_CMD_READ |
                     FIELD_PREP(SWITCH_PBUS_PHY_PORTADDR, port) |
                     FIELD_PREP(SWITCH_PBUS_PHY_REGADDR,
                                AIROHA_PBUS_C22_MASK | reg));
    ret = ursus_mf2_pbus_wait(eth);
    if (ret)
        return ret;

    *value = airoha_switch_rr(eth, SWITCH_PBUS_PHY_IARD) & 0xffff;
    return 0;
}

static int ursus_mf2_pbus_c22_write(struct airoha_eth *eth, int port,
                                    u16 reg, u16 value)
{
    airoha_switch_wr(eth, SWITCH_PBUS_PHY_IAWD, value);
    airoha_switch_wr(eth, SWITCH_PBUS_PHY_IAC,
                     SWITCH_PBUS_PHY_START |
                     SWITCH_PBUS_PHY_CMD_WRITE |
                     FIELD_PREP(SWITCH_PBUS_PHY_PORTADDR, port) |
                     FIELD_PREP(SWITCH_PBUS_PHY_REGADDR,
                                AIROHA_PBUS_C22_MASK | reg));
    return ursus_mf2_pbus_wait(eth);
}

static int ursus_mf2_pbus_mmd_modify(struct airoha_eth *eth, int port,
                                     u16 devad, u16 reg, u16 mask, u16 set)
{
    u16 value;
    int ret;

    ret = ursus_mf2_pbus_c22_write(eth, port, URSUS_MF2_MII_MMD_CTRL,
                                   devad);
    if (ret)
        return ret;
    ret = ursus_mf2_pbus_c22_write(eth, port, URSUS_MF2_MII_MMD_DATA,
                                   reg);
    if (ret)
        return ret;
    ret = ursus_mf2_pbus_c22_write(eth, port, URSUS_MF2_MII_MMD_CTRL,
                                   devad | URSUS_MF2_MII_MMD_NOINCR);
    if (ret)
        return ret;
    ret = ursus_mf2_pbus_c22_read(eth, port, URSUS_MF2_MII_MMD_DATA,
                                  &value);
    if (ret)
        return ret;

    value = (value & ~mask) | set;
    return ursus_mf2_pbus_c22_write(eth, port, URSUS_MF2_MII_MMD_DATA,
                                    value);
}

static int ursus_mf2_setup_phy_led0(struct airoha_eth *eth, int port)
{
    int ret;

    /* Linux MediaTek GPHY model:
     * LED0 ON: link 10/100/1000, no force/link-down/duplex latch.
     * Nokia MF DTS: active-low.
     * LED0 BLINK: TX/RX at 10/100/1000, replacing stale bootstrap state.
     * Preserve LED enable bit (15), which HWTEST4 already proved active.
     */
    ret = ursus_mf2_pbus_mmd_modify(eth, port, URSUS_MF2_MMD_VEND2,
                                    URSUS_MF2_LED0_ON_CTRL,
                                    URSUS_MF2_LED_ON_CLEAR_MASK |
                                    URSUS_MF2_LED_ON_POLARITY_LOW,
                                    URSUS_MF2_LED_ON_LINK_MASK |
                                    URSUS_MF2_LED_ON_POLARITY_LOW);
    if (ret)
        return ret;

    /* Blink register is entirely trigger state for the GPHY LED0 path. */
    ret = ursus_mf2_pbus_mmd_modify(eth, port, URSUS_MF2_MMD_VEND2,
                                    URSUS_MF2_LED0_BLINK_CTRL,
                                    0x0fff,
                                    URSUS_MF2_LED_BLINK_TXRX_ALL);
    if (!ret)
        printf("URSUS_MF2_HWTEST5_PHY_LED0 phy=%d on=link10/100/1000 blink=txrx polarity=active-low\n",
               port + 1);
    return ret;
}

'''
    text = text.replace(init_anchor, helpers + init_anchor, 1)

    power_anchor = "\t\t/* Disable BMCR_PDOWN for every PHY */\n"
    pos = text.find(power_anchor)
    if pos < 0:
        raise SystemExit("AN7583 BMCR_PDOWN loop anchor not found")

    tail_anchor = "\t\t}\n\t}\n\n\treturn 0;\n}"
    tail = text.find(tail_anchor, pos)
    if tail < 0:
        raise SystemExit("AN7583 switch-init tail anchor not found")

    replacement = r'''		}

		/* HWTEST5: only PHY2/LAN2 and PHY3/LAN3.  Failure is visible and
		 * fail-closed for this test image rather than silently accepting
		 * an unknown LED state. */
		for (i = 1; i <= 2; i++) {
			int ret = ursus_mf2_setup_phy_led0(eth, i);

			if (ret) {
				printf("URSUS_MF2_HWTEST5_PHY_LED0_FAIL phy=%d ret=%d\n",
				       i + 1, ret);
				return ret;
			}
		}
	}

	return 0;
}'''
    text = text[:tail] + replacement + text[tail + len(tail_anchor):]
    path.write_text(text, encoding="utf-8")

    verify = path.read_text(encoding="utf-8")
    required = (
        marker,
        "URSUS_MF2_MII_MMD_NOINCR",
        "URSUS_MF2_LED0_ON_CTRL",
        "URSUS_MF2_LED0_BLINK_CTRL",
        "URSUS_MF2_LED_ON_POLARITY_LOW",
        "URSUS_MF2_LED_BLINK_TXRX_ALL",
        "for (i = 1; i <= 2; i++)",
        "URSUS_MF2_HWTEST5_PHY_LED0_FAIL",
    )
    for token in required:
        if token not in verify:
            raise SystemExit(f"HWTEST5 PHY LED marker missing after patch: {token}")

    print("MF2_HWTEST5_PHY_LED=PASS driver=drivers/net/airoha_eth.c phy2=LAN2 phy3=LAN3 mmd=cl22-indirect")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    args = ap.parse_args()
    patch(args.source_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

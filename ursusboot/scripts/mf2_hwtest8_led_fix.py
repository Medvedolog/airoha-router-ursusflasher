#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def patch(root: Path) -> None:
    eth = root / "drivers/net/airoha_eth.c"
    if not eth.is_file():
        raise SystemExit(f"missing Airoha Ethernet source: {eth}")

    text = eth.read_text(encoding="utf-8")
    marker = "URSUS_MF2_HWTEST8_LED_FIX"
    if marker in text:
        raise SystemExit("HWTEST8 LED fix already applied")

    helper = r'''
/* URSUS_MF2_HWTEST8_LED_FIX
 * HWTEST7 proved LAN2/3/4 as PHY 0x0a/0x0b/0x0c and native C45 reads
 * through mt7531-mdio-mmio. Configure only volatile VEND2 LED0 state.
 */
#define URSUS_MF2_HWTEST8_MMD_VEND2       0x1f
#define URSUS_MF2_HWTEST8_LED0_ON_CTRL    0x24
#define URSUS_MF2_HWTEST8_LED0_BLINK_CTRL 0x25
#define URSUS_MF2_HWTEST8_ON_MASK          0xc07f
#define URSUS_MF2_HWTEST8_ON_SET           0xc007
#define URSUS_MF2_HWTEST8_BLINK_MASK       0x03ff
#define URSUS_MF2_HWTEST8_BLINK_SET        0x003f

static int ursus_mf2_hwtest8_led_fix(struct airoha_eth *eth)
{
	static const u8 phys[] = { 0x0a, 0x0b, 0x0c };
	int i;

	if (!eth->switch_mdio_dev) {
		printf("URSUS_MF2_HWTEST8_LED_BUS_FAIL reason=no-mt7531-mdio\n");
		return -ENODEV;
	}

	printf("URSUS_MF2_HWTEST8_LED_BEGIN bus=mt7531-mdio phys=0a,0b,0c mode=volatile-rmw\n");
	for (i = 0; i < ARRAY_SIZE(phys); i++) {
		int lan = i + 2;
		int addr = phys[i];
		int old_on, old_blink, rb_on, rb_blink, ret;
		u16 new_on, new_blink;

		old_on = dm_mdio_read(eth->switch_mdio_dev, addr,
					 URSUS_MF2_HWTEST8_MMD_VEND2,
					 URSUS_MF2_HWTEST8_LED0_ON_CTRL);
		old_blink = dm_mdio_read(eth->switch_mdio_dev, addr,
					    URSUS_MF2_HWTEST8_MMD_VEND2,
					    URSUS_MF2_HWTEST8_LED0_BLINK_CTRL);
		if (old_on < 0 || old_blink < 0) {
			printf("URSUS_MF2_HWTEST8_LED_FAIL lan=%d addr=0x%02x stage=read-before on=%d blink=%d\n",
			       lan, addr, old_on, old_blink);
			return -EIO;
		}

		new_on = (old_on & ~URSUS_MF2_HWTEST8_ON_MASK) |
			 URSUS_MF2_HWTEST8_ON_SET;
		new_blink = (old_blink & ~URSUS_MF2_HWTEST8_BLINK_MASK) |
			    URSUS_MF2_HWTEST8_BLINK_SET;

		ret = dm_mdio_write(eth->switch_mdio_dev, addr,
				    URSUS_MF2_HWTEST8_MMD_VEND2,
				    URSUS_MF2_HWTEST8_LED0_ON_CTRL, new_on);
		if (ret) {
			printf("URSUS_MF2_HWTEST8_LED_FAIL lan=%d addr=0x%02x stage=write-on ret=%d\n",
			       lan, addr, ret);
			return ret;
		}
		ret = dm_mdio_write(eth->switch_mdio_dev, addr,
				    URSUS_MF2_HWTEST8_MMD_VEND2,
				    URSUS_MF2_HWTEST8_LED0_BLINK_CTRL, new_blink);
		if (ret) {
			printf("URSUS_MF2_HWTEST8_LED_FAIL lan=%d addr=0x%02x stage=write-blink ret=%d\n",
			       lan, addr, ret);
			return ret;
		}

		rb_on = dm_mdio_read(eth->switch_mdio_dev, addr,
				      URSUS_MF2_HWTEST8_MMD_VEND2,
				      URSUS_MF2_HWTEST8_LED0_ON_CTRL);
		rb_blink = dm_mdio_read(eth->switch_mdio_dev, addr,
					 URSUS_MF2_HWTEST8_MMD_VEND2,
					 URSUS_MF2_HWTEST8_LED0_BLINK_CTRL);
		if (rb_on < 0 || rb_blink < 0) {
			printf("URSUS_MF2_HWTEST8_LED_FAIL lan=%d addr=0x%02x stage=readback on=%d blink=%d\n",
			       lan, addr, rb_on, rb_blink);
			return -EIO;
		}
		if ((rb_on & URSUS_MF2_HWTEST8_ON_MASK) != URSUS_MF2_HWTEST8_ON_SET ||
		    (rb_blink & URSUS_MF2_HWTEST8_BLINK_MASK) != URSUS_MF2_HWTEST8_BLINK_SET) {
			printf("URSUS_MF2_HWTEST8_LED_FAIL lan=%d addr=0x%02x stage=verify before=0x%04x/0x%04x requested=0x%04x/0x%04x readback=0x%04x/0x%04x\n",
			       lan, addr, old_on & 0xffff, old_blink & 0xffff,
			       new_on, new_blink, rb_on & 0xffff, rb_blink & 0xffff);
			return -EIO;
		}
		printf("URSUS_MF2_HWTEST8_LED lan=%d addr=0x%02x before=0x%04x/0x%04x after=0x%04x/0x%04x policy=link10,100,1000+txrx+active-low\n",
		       lan, addr, old_on & 0xffff, old_blink & 0xffff,
		       rb_on & 0xffff, rb_blink & 0xffff);
	}
	printf("URSUS_MF2_HWTEST8_LED_END result=OK\n");
	return 0;
}

'''

    func_anchor = "static int airoha_eth_init(struct udevice *dev)\n"
    if text.count(func_anchor) != 1:
        raise SystemExit(f"airoha_eth_init anchor count={text.count(func_anchor)}")
    func_pos = text.index(func_anchor)
    text = text[:func_pos] + helper + text[func_pos:]

    # Only modify the body of airoha_eth_init; the same qid/q sequence also
    # exists in another helper in this source snapshot.
    body_pos = text.index(func_anchor) + len(func_anchor)
    prefix, body = text[:body_pos], text[body_pos:]
    start_anchor = '''\tqid = 0;\n\tq = &qdma->q_rx[qid];\n\n'''
    if start_anchor not in body:
        raise SystemExit("airoha_eth_init body anchor missing")
    body = body.replace(
        start_anchor,
        start_anchor + '''\t/* Program only internal GPHY LED0 state before RX DMA starts. */\n\tif (port->id == 1) {\n\t\tint led_ret = ursus_mf2_hwtest8_led_fix(qdma->eth);\n\n\t\tif (led_ret)\n\t\t\treturn led_ret;\n\t}\n\n''',
        1,
    )
    text = prefix + body
    eth.write_text(text, encoding="utf-8")

    out = eth.read_text(encoding="utf-8")
    required = (
        marker,
        "URSUS_MF2_HWTEST8_LED_BEGIN",
        "URSUS_MF2_HWTEST8_LED_END result=OK",
        "URSUS_MF2_HWTEST8_ON_MASK          0xc07f",
        "URSUS_MF2_HWTEST8_ON_SET           0xc007",
        "URSUS_MF2_HWTEST8_BLINK_MASK       0x03ff",
        "URSUS_MF2_HWTEST8_BLINK_SET        0x003f",
        "static const u8 phys[] = { 0x0a, 0x0b, 0x0c };",
        "dm_mdio_read(eth->switch_mdio_dev",
        "dm_mdio_write(eth->switch_mdio_dev",
        "ursus_mf2_hwtest8_led_fix(qdma->eth)",
    )
    for token in required:
        if token not in out:
            raise SystemExit(f"HWTEST8 marker missing after patch: {token}")

    forbidden = (
        "URSUS_MF2_HWTEST5_PHY_LED0",
        "ursus_mf2_setup_phy_led0",
        "URSUS_MF2_LED_ON_POLARITY_LOW",
        "MDIO_DEVAD_NONE + URSUS_MF2_HWTEST8_MMD_VEND2",
    )
    for token in forbidden:
        if token in out:
            raise SystemExit(f"forbidden LED path/address expression in HWTEST8: {token}")

    print("MF2_HWTEST8_LED_FIX=PASS phys=0a,0b,0c backend=mt7531-mdio-mmio on=c007/mask=c07f blink=003f/mask=03ff readback=required persistent=none")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    args = ap.parse_args()
    patch(args.source_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

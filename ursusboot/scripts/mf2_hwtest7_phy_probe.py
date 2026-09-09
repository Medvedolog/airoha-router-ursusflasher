#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def patch(root: Path) -> None:
    dts = root / "arch/arm/dts/an7583-nokia-xg-040g-mf.dts"
    cmd = root / "cmd/ursusmfphy.c"
    makefile = root / "cmd/Makefile"

    if not dts.is_file():
        raise SystemExit(f"missing MF board DTS: {dts}")
    if not makefile.is_file():
        raise SystemExit(f"missing U-Boot cmd Makefile: {makefile}")
    if cmd.exists():
        raise SystemExit(f"HWTEST7 command already exists: {cmd}")

    text = dts.read_text(encoding="utf-8")
    if "URSUS_MF2_LAN23_LED_PINMUX" not in text:
        raise SystemExit("HWTEST7 requires the proven HWTEST4/HWTEST6 LAN2/LAN3 pinmux baseline")
    if "URSUS_MF2_HWTEST7_LAN234_LED_PINMUX" in text:
        raise SystemExit("HWTEST7 LAN2/LAN3/LAN4 pinmux already applied")

    old_comment = " * LAN4 remains deferred for MF2 acceptance.\n"
    if text.count(old_comment) != 1:
        raise SystemExit(f"LAN4 baseline comment anchor count={text.count(old_comment)}")
    text = text.replace(
        old_comment,
        " * URSUS_MF2_HWTEST7_LAN234_LED_PINMUX\n"
        " * HWTEST7 extends only the native pinmux to LAN4 / gpio4 -> phy4_led0.\n",
        1,
    )

    block_anchor = '''\tursus_gswp3_led0_pins: ursus-gswp3-led0-pins {
\t\tmux {
\t\t\tfunction = "phy3_led0";
\t\t\tpins = "gpio3";
\t\t};
\t};
};'''
    if text.count(block_anchor) != 1:
        raise SystemExit(f"LAN3 pinmux block anchor count={text.count(block_anchor)}")
    block_replacement = '''\tursus_gswp3_led0_pins: ursus-gswp3-led0-pins {
\t\tmux {
\t\t\tfunction = "phy3_led0";
\t\t\tpins = "gpio3";
\t\t};
\t};

\tursus_gswp4_led0_pins: ursus-gswp4-led0-pins {
\t\tmux {
\t\t\tfunction = "phy4_led0";
\t\t\tpins = "gpio4";
\t\t};
\t};
};'''
    text = text.replace(block_anchor, block_replacement, 1)

    old_list = '<&ursus_gswp2_led0_pins>, <&ursus_gswp3_led0_pins>;'
    new_list = '<&ursus_gswp2_led0_pins>, <&ursus_gswp3_led0_pins>, <&ursus_gswp4_led0_pins>;'
    if text.count(old_list) != 1:
        raise SystemExit(f"LAN2/LAN3 pinctrl list anchor count={text.count(old_list)}")
    text = text.replace(old_list, new_list, 1)
    dts.write_text(text, encoding="utf-8")

    cmd.write_text(r'''// SPDX-License-Identifier: GPL-2.0+
/*
 * URSUS_MF2_HWTEST7_PHY_PROBE
 *
 * Nokia XG-040G-MF / AN7583 read-only internal-GPHY diagnostic.
 *
 * Important: this command uses the switch's existing mt7531-mdio-mmio DM
 * device.  It performs dm_mdio_read() only.  There are no PHY register
 * writes, no LED programming and no persistent storage operations.
 *
 * Linux DTS mapping:
 *   LAN2 -> internal PHY address 0x0a
 *   LAN3 -> internal PHY address 0x0b
 *   LAN4 -> internal PHY address 0x0c
 *
 * MMD VEND2 LED0 registers 0x24/0x25 are read through the driver's native
 * Clause-45 read transaction.  The address phase is transport state only;
 * LED configuration is never modified.
 */
#include <command.h>
#include <dm.h>
#include <dm/uclass.h>
#include <miiphy.h>
#include <linux/mii.h>

#define URSUS_MF2_LED_MMD_VEND2        0x1f
#define URSUS_MF2_LED0_ON_CTRL         0x24
#define URSUS_MF2_LED0_BLINK_CTRL      0x25

struct ursus_mf2_phy_map {
    int lan;
    int addr;
};

static const struct ursus_mf2_phy_map ursus_mf2_phys[] = {
    { 2, 0x0a },
    { 3, 0x0b },
    { 4, 0x0c },
};

static int ursus_mf2_dump_phy(struct udevice *mdio, int lan, int addr)
{
    int bmcr, bmsr_latched, bmsr, id1, id2, led_on, led_blink;

    bmcr = dm_mdio_read(mdio, addr, MDIO_DEVAD_NONE, MII_BMCR);
    bmsr_latched = dm_mdio_read(mdio, addr, MDIO_DEVAD_NONE, MII_BMSR);
    /* BMSR link status is latch-low, so the second read is current state. */
    bmsr = dm_mdio_read(mdio, addr, MDIO_DEVAD_NONE, MII_BMSR);
    id1 = dm_mdio_read(mdio, addr, MDIO_DEVAD_NONE, MII_PHYSID1);
    id2 = dm_mdio_read(mdio, addr, MDIO_DEVAD_NONE, MII_PHYSID2);
    led_on = dm_mdio_read(mdio, addr, URSUS_MF2_LED_MMD_VEND2,
                          URSUS_MF2_LED0_ON_CTRL);
    led_blink = dm_mdio_read(mdio, addr, URSUS_MF2_LED_MMD_VEND2,
                             URSUS_MF2_LED0_BLINK_CTRL);

    if (bmcr < 0 || bmsr_latched < 0 || bmsr < 0 || id1 < 0 || id2 < 0 ||
        led_on < 0 || led_blink < 0) {
        printf("URSUS_MF2_HWTEST7_PHY_FAIL lan=%d addr=0x%02x bmcr=%d bmsr1=%d bmsr2=%d id1=%d id2=%d led_on=%d led_blink=%d\n",
               lan, addr, bmcr, bmsr_latched, bmsr, id1, id2,
               led_on, led_blink);
        return -EIO;
    }

    printf("URSUS_MF2_HWTEST7_PHY lan=%d addr=0x%02x link=%s bmcr=0x%04x bmsr1=0x%04x bmsr2=0x%04x id=0x%04x:0x%04x led0_on=0x%04x led0_blink=0x%04x\n",
           lan, addr, (bmsr & BMSR_LSTATUS) ? "up" : "down",
           bmcr & 0xffff, bmsr_latched & 0xffff, bmsr & 0xffff,
           id1 & 0xffff, id2 & 0xffff, led_on & 0xffff, led_blink & 0xffff);
    return 0;
}

static int do_ursusmfphy(struct cmd_tbl *cmdtp, int flag, int argc,
                         char *const argv[])
{
    struct udevice *mdio;
    int i, ret, failed = 0;

    ret = uclass_get_device_by_name(UCLASS_MDIO, "mt7531-mdio", &mdio);
    if (ret) {
        printf("URSUS_MF2_HWTEST7_PHY_BUS_FAIL name=mt7531-mdio ret=%d\n", ret);
        return CMD_RET_FAILURE;
    }

    printf("URSUS_MF2_HWTEST7_PHY_PROBE_BEGIN mode=read-only bus=mt7531-mdio phys=0a,0b,0c\n");
    for (i = 0; i < ARRAY_SIZE(ursus_mf2_phys); i++) {
        ret = ursus_mf2_dump_phy(mdio, ursus_mf2_phys[i].lan,
                                 ursus_mf2_phys[i].addr);
        if (ret)
            failed = 1;
    }
    printf("URSUS_MF2_HWTEST7_PHY_PROBE_END result=%s\n",
           failed ? "READ_ERROR" : "OK");

    return failed ? CMD_RET_FAILURE : CMD_RET_SUCCESS;
}

U_BOOT_CMD(
    ursusmfphy, 1, 1, do_ursusmfphy,
    "read-only Nokia MF LAN2/LAN3/LAN4 PHY + LED0 register snapshot",
    ""
);
''', encoding="utf-8")

    m = makefile.read_text(encoding="utf-8")
    obj = "obj-y += ursusmfphy.o"
    if obj in m:
        raise SystemExit("HWTEST7 command already linked")
    if not m.endswith("\n"):
        m += "\n"
    m += "\n# URSUS_MF2_HWTEST7_PHY_PROBE read-only diagnostic\n" + obj + "\n"
    makefile.write_text(m, encoding="utf-8")

    out = dts.read_text(encoding="utf-8")
    required_dts = (
        "URSUS_MF2_HWTEST7_LAN234_LED_PINMUX",
        'function = "phy2_led0";',
        'pins = "gpio2";',
        'function = "phy3_led0";',
        'pins = "gpio3";',
        'function = "phy4_led0";',
        'pins = "gpio4";',
        '<&ursus_gswp2_led0_pins>, <&ursus_gswp3_led0_pins>, <&ursus_gswp4_led0_pins>',
    )
    for token in required_dts:
        if token not in out:
            raise SystemExit(f"HWTEST7 DTS marker missing: {token}")

    src = cmd.read_text(encoding="utf-8")
    required_src = (
        "URSUS_MF2_HWTEST7_PHY_PROBE",
        "dm_mdio_read",
        "0x0a",
        "0x0b",
        "0x0c",
        "URSUS_MF2_LED0_ON_CTRL",
        "URSUS_MF2_LED0_BLINK_CTRL",
        "uclass_get_device_by_name(UCLASS_MDIO, \"mt7531-mdio\"",
    )
    for token in required_src:
        if token not in src:
            raise SystemExit(f"HWTEST7 command marker missing: {token}")
    if "dm_mdio_write" in src:
        raise SystemExit("HWTEST7 read-only command unexpectedly contains dm_mdio_write")

    print("MF2_HWTEST7_PHY_PROBE=PASS lan2=0x0a lan3=0x0b lan4=0x0c c22=read c45_led0=read-only pinmux234=1")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_root", type=Path)
    args = ap.parse_args()
    patch(args.source_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

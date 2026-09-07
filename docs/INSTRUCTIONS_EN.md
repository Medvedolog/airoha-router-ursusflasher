# UrsusFlasher 0.2.55 — operating instructions

This document covers Nokia XG-040G-MD on Airoha AN7581.

## Ethernet

Use **LAN2 or LAN3** for flashing.

- LAN1 is attached to the separate Airoha EN8811H PHY and is not the preferred transition/recovery port.
- LAN4 becomes WAN after the bundled OpenWrt build boots, so access to `192.168.1.1` may be lost when the PC is connected there.
- USB-UART recovery requires a 3.3 V adapter. Connect TX, RX and GND only; do not connect VCC.

## ONE-CLICK

Run `START_ONECLICK.cmd` on Windows or `./START_ONECLICK.sh` on Linux/macOS.

The flasher detects the current state first and then selects the transport.

### Nokia factory firmware

Control uses the stock HTTP/Web interface and a root Telnet session. TFTP is used for the complete flash backup and for transferring the prepared `mtd0` image. The complete `mtd0..mtd16` backup must validate before the first NAND write.

### Installed OpenWrt or RAM/initramfs OpenWrt

Control uses root SSH and binary SSH streaming/SCP as appropriate. The flasher distinguishes a persistent flash root from a RAM root. An existing UBI `fip` volume is preferred; a physical boot block is used only when the target and current contents are unambiguous.

### UrsusBoot Recovery

Control and chunked file upload use the UrsusBoot HTTP API at `192.168.1.1`.

## EXPERT

Run `START_EXPERT.cmd` or `./START_EXPERT.sh` for manual operations.

Actions marked `!` may write persistent flash/NAND. Passive menu detection is informational; each selected action performs its own authoritative preflight and may request credentials when needed.

## Bootloader update transports

- Nokia factory firmware: Telnet + TFTP.
- Installed OpenWrt: SSH + SCP.
- OpenWrt running from RAM/initramfs: SSH + SCP.
- UrsusBoot Recovery: HTTP API; TFTP is available as the fallback FIP transport when WebFailsafe upload does not complete.
- Airoha BootROM: USB-UART + XMODEM to start the recovery environment in RAM.

## Verification

Before writing, UrsusFlasher verifies the applicable device identity, layout, target object, file size/hash and backup state.

After writing, bootloader objects are read back completely and compared with the expected content or SHA256. A mismatch does not trigger an automatic retry with another writer.

## Full backup

A full Nokia factory backup captures `mtd0..mtd16` plus device metadata and checksums. For OpenWrt, selecting item 7 may interactively request the root SSH password to identify the current layout; the password is not stored and no temporary key is installed. OpenWrt UBI exact capture then uses Airoha BootROM/RAM to save the full 256 MiB physical `mtd0_all_flash.bin.gz` plus SHA256 and derived BL2/UBI views, without writing NAND.

## UrsusBoot Recovery entry

After reboot, hold Reset immediately after the router-wide LED restart. Keep it held through 2 short + 3 long red flashes and release it when the red LED becomes steady. Then open `http://192.168.1.1`.

Holding Reset before power-on enters Airoha BootROM instead of normal UrsusBoot Recovery.

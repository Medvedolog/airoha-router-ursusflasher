# UrsusFlasher 0.2.56 — operating instructions

This document covers Nokia XG-040G-MD on Airoha AN7581.

## Required first: factory-reset the Nokia

**The router must be factory-reset before every iteration** — before the first install and before any retry after a failed attempt.

Perform the reset **from the Nokia stock firmware**: press and hold the Reset button for **at least 20 seconds**, release it, and wait for the router to finish rebooting.

Without it the stock system is in an unknown state: changed settings, services left enabled or disabled, and leftovers from earlier attempts. Device detection and stock access can then behave differently from what UrsusFlasher expects.

## Ethernet

Use **LAN2 or LAN3** for flashing.

- LAN1 is attached to the separate Airoha EN8811H PHY and is not the preferred transition/recovery port.
- LAN4 becomes WAN after the bundled OpenWrt build boots, so access to `192.168.1.1` may be lost when the PC is connected there.
- USB-UART recovery requires a 3.3 V adapter. Connect TX, RX and GND only; do not connect VCC.

## ONE-CLICK

**ONE-CLICK always installs OpenWrt with the UBI layout.** The kit carries two images — one for UBI and one for the factory layout — but every ONE-CLICK path uses the UBI one and offers no choice.

If you need the **factory layout**, do it manually in one of two ways:

- **EXPERT item 3, "Записать пользовательскую прошивку OpenWrt"** — point it at the bundled `fw/openwrt-airoha-an7581-nokia_xg-040g-md-squashfs-sysupgrade.bin`. The item accepts any `.bin`/`.itb`, the image class is detected automatically, and the write takes the factory-layout path.
- **The UrsusBoot web UI** — upload the same file in Recovery and press "Install into factory layout".

The transition is one-way: the factory layout can be installed from Nokia stock, but not from an already installed OpenWrt UBI — such an image is refused before any write.

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

## UrsusBoot web UI: what appears, what disappears, what is refused

The page does not show everything at once. It reshapes itself around the state the bootloader reports about the router and about the uploaded file. A missing control is a condition that is not met, not a fault.

| Control | Shown when |
|---|---|
| Operation progress panel | an operation is running |
| **Reboot into OpenWrt / with new UrsusBoot** | the operation completed successfully |
| **Install into factory layout** | the bootloader reports that install is available |
| **Install/update UBI** | the bootloader reports that a UBI update is available |
| **Keep OpenWrt settings** checkbox | the router is **already** in the UBI layout **and** the uploaded image is a UBI sysupgrade |
| **Reset OpenWrt settings** button | the current layout is already `OPENWRT_UBI` or `OPENWRT_STOCK_LAYOUT` and no operation is running |
| Migration box | you are in a migration context |

The two that are most often mistaken for missing features:

- **No "Keep OpenWrt settings" during a first install.** By design: migrating from Nokia stock or from the factory layout leaves nothing to keep, and the flag is forced to 0. The checkbox is for updating UBI on top of an already installed UBI system.
- **No "Reset OpenWrt settings" right after an install.** It is for a router already running a recognised OpenWrt; while you are still in Recovery the layout has not been re-detected yet.

Buttons can also be present but disabled: **Migrate to UBI** needs every transition precheck to pass, and **Update UrsusBoot** needs a valid FIP and no active, completed or failed operation.

Even a visible button does not guarantee a write. The bootloader refuses with a reason class:

```text
OPERATION_LOCKED     no validated image of the required class; another operation is active;
                     a preflight did not pass; confirmation missing
LAYOUT_UNSUPPORTED   the current layout does not support this operation
WRITE_FAILED         the write or reset did not complete
```

Every destructive action additionally requires an exact confirmation from the page — `INSTALL-UBI`, `INSTALL-OPENWRT-STOCK-LAYOUT`, `UPDATE-URSUSBOOT`, `RESET-OPENWRT-SETTINGS`, `REBOOT`.

**Known behaviour:** the reboot button answers `REBOOTING`, but the actual reset runs after the connection closes. If the browser holds the connection open the router may stay powered on; power-cycle it by hand. In the UART log the successful path is marked `URSUS_UBI_MIGRATION_OPERATOR_REBOOT`.

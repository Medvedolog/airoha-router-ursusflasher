# UrsusFlasher payload policy

This branch keeps only payloads that are current runtime inputs, current TEST61 artifacts, proven emergency inputs, or reproducible-build inputs. Superseded HWFIX/UIFIX/TEST57-TEST60 engineering binaries are intentionally removed.

## MD / AN7581

Runtime and recovery inputs under `payloads/md/ursusboot/`:

- `ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip` — frozen production/test target.
- `ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-u-boot.bin` and `.lzma` — current TEST61 BL33 references.
- `ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-BUILD_INFO.txt` — current build provenance.
- `ursusboot-md-0.1.0-alpha3-update.fip` — proven emergency FIP.
- `ursusboot-md-0.1.0-alpha3-ram-installer.fip` — proven BootROM/XMODEM RAM helper.
- `ursusboot-md-0.1.0-alpha3-bl2.bin` — proven emergency BL2.
- `openwrt-airoha-an7581-nokia_xg-040g-md-ubi-preloader.bin` — proven MD preloader / STOCK->UBI BL2 candidate.
- `stock_mtd0_reference.bin` — direct-stock structural reference used by the host installer.
- `openwrt-6.18.44-mtd-rw.ko` and `ursus-mtd-raw` — host-side raw MTD support for the pinned OpenWrt ABI.
- `ursus-mtd-raw.c` — source for the helper; source-only and excluded from the hardware-test ZIP payload set.
- `ursusboot-md-0.1.0-alpha4-FUDAN1-update.fip` — reproducible TEST61 build donor only; excluded from the hardware-test ZIP payload set.

`payloads/md/bootrom-backup/` contains the pinned MD recovery source artifacts used to populate `data/recovery/` during packaging. They are excluded from `data/payloads/` in the hardware-test ZIP to avoid duplicate large binaries.

## MF / AN7583

MF payloads are produced/staged by CI from pinned source/proven lineages:

- `payloads/mf/ursusboot/u-boot.runtime.lzma` — current device-derived persistent runtime BL33.
- `payloads/mf/recovery/ursusboot-mf-0.1.0-TEST61-uart-preloader.bin` — current BootROM UART preloader.
- `payloads/mf/recovery/ursusboot-mf-0.1.0-TEST61-ram.fip` — current RAM Recovery FIP.
- `payloads/mf/proven/nokia-xg-040g-mf-an7583-production-preloader.bin` — pinned STOCK/Factory->UBI BL2 candidate.

Historical MF production FIP/sysupgrade/transition copies are not duplicated under `data/payloads`; the transition/recovery backend has its own canonical package resources.

## Firmware

OpenWrt firmware is not a payload. The canonical paired MD/MF UnameOne set lives only in `fw/`; see `fw/README.md` and `config/FIRMWARE_BUNDLES.json`.

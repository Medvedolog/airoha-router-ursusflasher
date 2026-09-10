# Canonical OpenWrt firmware bundle

`fw/` contains the paired UnameOne OpenWrt snapshot set used by UrsusFlasher 0.2.62 hardware testing for both Nokia XG-040G families.

Exactly eight firmware files are canonical:

```text
MD / AN7581
openwrt-airoha-an7581-nokia_xg-040g-md-squashfs-sysupgrade.bin
openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb
openwrt-airoha-an7581-nokia_xg-040g-md-initramfs-uImage.itb
openwrt-airoha-an7581-nokia_xg-040g-md-ubi-initramfs-recovery.itb

MF / AN7583
openwrt-airoha-an7583-nokia_xg-040g-mf-squashfs-sysupgrade.bin
openwrt-airoha-an7583-nokia_xg-040g-mf-ubi-squashfs-sysupgrade.itb
openwrt-airoha-an7583-nokia_xg-040g-mf-initramfs-uImage.itb
openwrt-airoha-an7583-nokia_xg-040g-mf-ubi-initramfs-recovery.itb
```

Roles and authoritative size/SHA256 values are in `config/FIRMWARE_BUNDLES.json`.

ONE-CLICK selects firmware only after positive MD/MF identification. The normal STOCK/Factory -> UBI path uses the matching `*-ubi-squashfs-sysupgrade.itb`; the non-UBI `*-squashfs-sysupgrade.bin` is retained for factory-layout OpenWrt operations. The two initramfs images per board are bundled for recovery/manual use and are not a mandatory ONE-CLICK dependency.

No mutable OpenWrt snapshot is downloaded at runtime and CI must not replace these files with older MedveFlasher firmware.

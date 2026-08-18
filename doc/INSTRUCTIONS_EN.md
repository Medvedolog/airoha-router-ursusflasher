# UrsusFlasher 0.1.0-md-lab1fix10 — instructions

## Purpose

UrsusFlasher installs OpenWrt on Nokia XG-040G-MD / Airoha AN7581 while keeping tcboot as a permanent recovery loader. Runtime uses Python 3 standard library only; no `pip` and no MedveFlasher runtime dependency are required.

## Start

Windows:

```text
START.cmd
```

Linux:

```text
./START.sh
```

The first screen always selects the language, followed by the beginner menu.

## Bundled OpenWrt sysupgrade

Default image:

```text
fw/openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb
size   10518808
SHA256 b0556660c1939a9dc1ebbce5b4a3b3c8318c76eacae04de53ce047b43af8d867
```

A different `.itb` may be selected. Before any destructive action Ursus parses FIT/FDT, resolves `/configurations/default`, verifies image hashes, locates the UBI partition by `label="ubi"`, and reads the actual `#address-cells/#size-cells` and `reg`. Unexpected structures fail closed.

The official ITB is not rewritten on the PC. tcboot modifies only the working FDT in RAM before kernel handoff.

## Backup policy

```text
1. Recommended: create a new STOCKSET and continue
2. Use an existing OWN Ursus/MedveFlasher STOCKSET
3. EXPERT: continue with a foreign/unbound backup
4. EXPERT: continue with manually dumped MTD partitions
5. EXPERT: continue WITHOUT a backup
0. Back
```

Safe paths 1–2 require a valid restore-validator and current-device binding. Expert override does not disable the model/SoC gate, UID0, mtd0 geometry, tcboot SHA/readback, or FIT/FDT validation.

## Writing tcboot

The destructive write requires the exact phrase:

```text
FLASH TCBOOT MD
```

NAND erase does not begin before `__URSUS_ERASE_BEGIN__`. After writing, Ursus performs a complete 0x80000 `/dev/mtd0` readback and byte-for-byte comparison.

## Entering tcboot WebFailsafe — HW VERIFIED

Use exactly this sequence on MD:

```text
1. Power the Nokia off.
2. Power it on.
3. IMMEDIATELY after power-on press Reset.
4. Hold Reset for 10 seconds.
5. Release Reset.
6. Open http://192.168.1.1/.
```

**Do not hold Reset before applying power.** That enters the separate early Airoha BootROM `Press x` path.

## Installing/updating OpenWrt through tcboot

After WebFailsafe is detected, the wizard can upload the selected ITB to `/flashing.html` using its built-in HTTP/1.0 multipart uploader.

On the tcboot side:

1. the FIT and Nokia XG-040G-MD UBI profile are validated;
2. on the first migration, stock BOSA/RI calibration is saved, only the UBI region is formatted, and core UBI volumes are created;
3. on an existing Ursus UBI layout, tcboot verifies the core volumes and never erases mtd0/tcboot;
4. old `fit` and `rootfs_data` volumes are removed;
5. the new `fit` is created using the exact upload size, written, fully read back, and checked with `cmp.b`;
6. `rootfs_data` is recreated;
7. bootcmd is saved and the device resets.

Important: the current WebFailsafe update is a **recovery-style reinstall**. tcboot survives the sysupgrade, but `rootfs_data` is intentionally recreated, so this is not a configuration-preserving OpenWrt sysupgrade.

## Verified MD status

Verified on real XG-040G-MD hardware:

- tcboot mtd0 write and full readback;
- WebFailsafe via `power ON -> immediate Reset -> 10 seconds`;
- upload of the official OpenWrt UBI sysupgrade;
- complete FIT write/readback;
- runtime FDT UBI partition fixup;
- Linux 6.18.44 boot;
- UBI attach, UBIFS `rootfs_data`, overlay, and `procd`;
- a repeated tcboot Web sysupgrade after OpenWrt was already installed;
- tcboot remains in NAND and WebFailsafe remains available after sysupgrade.

## Layout

```text
0x00000000..0x0007ffff  tcboot
0x00080000..0x000fffff  tcboot environment
0x00100000..0x0fffffff  UBI / OpenWrt
```

This physical separation of the first 1 MiB from the UBI region is what makes tcboot persistent across Web sysupgrade.

Implementation details: `doc/ARCHITECTURE_EN.md`.

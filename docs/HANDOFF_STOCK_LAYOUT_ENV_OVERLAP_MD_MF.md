# HANDOFF / TODO — MD/MF stock-layout OpenWrt vs persistent UrsusBoot

Date: 2026-10-05  
Repo: `Medvedolog/airoha-router-ursusflasher`  
Branch: `dev/ursusboot-http-backup-client`  
Baseline: `789e0ed49c93eedb7339705db444dc65642e0f7b` (`0.2.79-dev-recovery`)

## TL;DR

A real compatibility hazard was found for **both Nokia XG-040G-MD and XG-040G-MF** when these two conditions are combined:

1. persistent UrsusBoot is installed in the original 512 KiB boot area;
2. OpenWrt is then run in the old Nokia/factory/stock NAND layout.

Installing stock-layout OpenWrt from UrsusBoot WebFailsafe itself preserves the bootloader and is safe. The dangerous operation is a later normal `sysupgrade` from that running stock-layout OpenWrt: upstream OpenWrt calls `fw_setenv`, and the raw `u-boot-env` lives inside the same 128 KiB NAND eraseblock that may contain the tail of the persistent UrsusBoot FIP.

Result after reboot can be:

```
BL2 -> damaged FIP/BL33 -> LZMA res 1 -> PANIC
```

This is not an Ethernet corruption bug. In the field incident Ethernet failed during the normal UrsusBoot -> UBI handoff; the device was then manipulated manually and ended up running stock-layout OpenWrt. The network failure only exposed the dangerous intermediate combination.

## Proven layout conflict

Upstream OpenWrt stock-parts for both MD and MF:

```text
0x00000-0x7ffff  bootloader   (read-only)
0x60000-0x7ffff  u-boot-env   (writable, one 128 KiB eraseblock)
```

The actual environment is at physical `0x7c000`, but `fw_setenv` must erase/rewrite the containing NAND eraseblock `0x60000-0x7ffff`.

Relevant upstream files:

- `target/linux/airoha/dts/an758x-nokia_xg-040g-stock-parts.dtsi`
- `package/boot/uboot-tools/uboot-envtools/files/airoha_an7581`
- `package/boot/uboot-tools/uboot-envtools/files/airoha_an7583`
- `target/linux/airoha/an7581/base-files/lib/upgrade/platform.sh`
- `target/linux/airoha/an7583/base-files/lib/upgrade/platform.sh`

Both MD and MF stock-layout `platform_pre_upgrade()` call:

```sh
fw_setenv bootcmd "flash read 0xc0000 0x800000 0x85000000; bootm 0x85000000"
```

Current MD UrsusBoot FIP also extends into this eraseblock (`physical_fip_end=0x7b800`).  
MF `mf_persistent.py` currently protects the logical env start at `0x7c000`; the field device proved that its generated persistent image also had live FIP data inside `0x60000-0x7ffff`.

## Why WebFailsafe factory/non-UBI install itself did not corrupt UrsusBoot

Current UrsusBoot `src/u-boot/cmd/ursusweb.c::ursus_factory_install()` explicitly preserves the bootloader:

```text
URSUS_STOCK_LAYOUT_BOOTLOADER_PRESERVE=1
```

It writes only:

- factory-layout rootfs/UBI areas;
- raw FIT kernel starting at `0x0c0000`.

It does **not** erase/write `0x00000-0x7ffff`.

Therefore this sequence can work normally:

```
persistent UrsusBoot
-> WebFailsafe
-> install non-UBI/factory-layout OpenWrt
-> boot OpenWrt
```

The mine is the **next normal sysupgrade from that running OpenWrt**, because of the upstream `fw_setenv` hook.

## Field evidence

On the affected MF device:

- a saved `mf-mtd0-runtime-*.bin` was the exact boot-area image installed by UrsusFlasher;
- comparison with the damaged current boot area showed the first 384 KiB unchanged;
- all differences were confined to `0x60000-0x7ffff`;
- restoring exactly that 128 KiB block from the saved runtime image restored full byte equality (`MTD1_OK`);
- the earlier boot failure was `LZMA: res 1` followed by PANIC.

This is structurally consistent with the raw `u-boot-env` eraseblock being rewritten. The exact user command that first triggered the write was not captured, so do not overstate that part as a logged fact.

## Decisions already made

Do **not** solve this by:

- shrinking the persistent FIP limit to `0x60000`;
- removing persistent UrsusBoot;
- replacing the current ONE-KEY persistent handoff architecture;
- renaming/removing `/etc/fw_env.config` as the project-level fix.

Persistent UrsusBoot remains supported.

The normal ONE-KEY target remains:

```
Nokia factory
-> persistent UrsusBoot
-> UrsusBoot Recovery
-> STOCK -> UBI migration
-> OpenWrt UBI
```

ONE-KEY does not intentionally create stock-layout OpenWrt.

## TODO for the next session

### P0 — stop creating new stock-layout OpenWrt on MD/MF

**UrsusBoot repo**

File: `src/u-boot/cmd/ursusweb.c`

- retire/reject `POST /api/install-openwrt-stock-layout` for Nokia MD/MF;
- stop advertising `URSUS_STOCK_LAYOUT_INSTALL_ENABLED=1`;
- reject `URSUS_IMG_NONUBI_SYSUPGRADE` as an install/update target on MD/MF WebFailsafe;
- keep classification of non-UBI images if useful for diagnostics;
- keep detection of existing `OPENWRT_STOCK_LAYOUT`.

### P0 — keep stock-layout only as a migration source

**UrsusBoot**

Keep:

```
STOCK / OPENWRT_STOCK_LAYOUT
    -> validated UBI sysupgrade + board-specific transition BL2
    -> OPENWRT_UBI
```

Existing `OPENWRT_STOCK_LAYOUT` devices must remain recoverable/migratable.

### P0 — align UrsusFlasher policy

Files to inspect/update:

- `ursusflasher/src/one_key_multi.py`
- `ursusflasher/src/expert.py`
- `ursusflasher/src/device_state.py`
- `config/MANIFEST.json`
- `config/FIRMWARE_CAPABILITIES.json`

Policy:

- `OPENWRT_STOCK_LAYOUT` remains a recognized source/recovery state;
- it must not be a normal final target;
- custom/EXPERT flows must not create another stock-layout OpenWrt on MD/MF;
- from existing stock-layout OpenWrt offer/route only backup/diagnostics, stock restore, or migration to UBI as appropriate;
- do not break Nokia factory -> persistent UrsusBoot -> UBI ONE-KEY.

### P1 — tests

Add source/contract tests proving:

1. WebFailsafe cannot arm `INSTALL_OPENWRT_STOCK_LAYOUT` for MD/MF.
2. UBI migration from `STOCK` still works.
3. UBI migration from existing `OPENWRT_STOCK_LAYOUT` still works.
4. UBI -> UBI update still works.
5. ONE-KEY factory -> persistent UrsusBoot -> UBI route is unchanged.
6. No regression to full stock restore/emergency recovery.

## Current status

`0.2.79-dev-recovery` fixes the retry/audit behavior of the UrsusBoot Recovery handoff. It does **not** yet close this stock-layout/`fw_setenv` compatibility hazard.

No code fix for this handoff has been committed yet in this document's baseline. Treat the next implementation as a new dev iteration and keep `main` untouched until explicitly requested.

# UrsusBoot

**Compact OpenWrt-aware recovery and installation U-Boot for Airoha router platforms.**

UrsusBoot grew out of the OpenWrt U-Boot bootloader ecosystem and targets Airoha devices where a small persistent recovery environment is especially valuable. It combines WebFailsafe, OpenWrt image awareness, UBI migration and recovery primitives while staying small enough for constrained boot areas.

## Why UrsusBoot

The main advantage is simple: **it provides much of the functionality normally associated with a much larger recovery environment while fitting into an approximately 512 KiB boot-area contract.** No Linux kernel or userspace is required just to validate, migrate and install OpenWrt images.

Typical capabilities include:

- WebFailsafe recovery UI;
- OpenWrt `sysupgrade` / FIT awareness;
- stock / stock-layout / canonical UBI detection;
- UBI creation and migration;
- FIP and bootloader update paths;
- readback verification and fail-closed validation;
- recovery over network and Airoha BootROM/UART paths.

## What UrsusBoot actually is

UrsusBoot is **not a rewrite and not a custom bootloader**. It is the ordinary U-Boot that OpenWrt builds for Airoha — upstream U-Boot 2026.07 with the OpenWrt and Airoha platform patches — configured down to what a router actually needs, with a recovery layer added on top. Anyone who knows U-Boot will recognize everything inside it.

**Nothing Airoha-relevant was removed.** The build keeps 65 stock U-Boot commands, including the whole `mtd`/`ubi` stack, the full environment set, networking (`ping`, `tftpboot`, `wget`, `dhcp`, `dns`, `sntp`, `mii`, `mdio`), booting (`bootm`, `booti`, `bootflow`, `bootd`, `go`, `elf`), partitions (`part`, `gpt`), hashing and CRC, LZMA/LZ4/gzip decompression, and `gpio`/`pinmux`/`led`/`button`/`smc`. On top of those sit seven UrsusBoot commands, so the running bootloader offers 72 commands in total and a completely unlocked console.

**What was turned off is what a NAND router never reaches for.** 95 command groups and their subsystems are disabled: every filesystem (ext4, FAT, btrfs, squashfs, erofs, UBIFS, exFAT, cramfs, ZFS), every storage bus the board does not have (USB, MMC/SD, SATA, SCSI, NVMe, PCI, IDE, parallel SPI flash, OneNAND), the EFI loader, video, the bootmenu/bootstd/bootmeth machinery, TPM, i2c, ADC, DFU, fuse, pstore and a long tail of demos and benchmarks. Signature verification (`FIT_SIGNATURE`/RSA) is also off — FIT **hashes** are verified, FIT signatures are not.

That is the whole trick behind the size: no functionality was reinvented to fit the ~512 KiB boot-area contract, it was simply not compiled in.

What UrsusBoot genuinely adds on top of stock U-Boot:

- a **WebFailsafe web UI with a real U-Boot console in the browser** — the console tab runs the actual command line, not a curated subset;
- an **OpenWrt-aware image pipeline** — staging, classification and fail-closed validation of sysupgrade/FIT images before anything is written;
- **UBI creation, update and migration** with readback verification and typed refusal reasons;
- a **boot dispatcher** that picks a boot path from what is really on NAND and falls back to recovery instead of to a dead prompt;
- **FIP/bootloader self-update** and Airoha BootROM/UART recovery paths.

## Repository policy: self-contained

This repository is intended to be **self-contained**. A normal build must not clone or download code, templates or binary donors from any other projects.

The only external build dependency permitted by policy is an **OpenWrt SDK/toolchain** appropriate for the target Airoha SoC. Board templates, boot-area templates, FIP lineage inputs, patches, configuration and build scripts belong in this repository.

The Nokia XG-040G-MD and XG-040G-MF board templates included here are 512 KiB stock boot-area templates. Device identity is not sourced from these templates; model-specific identity such as MAC/serial/GPON data belongs to the RI/BOSA/device-identity path and must be handled separately.

## No donor dump required

For supported boards the build/install flow does not require a user to dump `mtd0` first.

```text
board stock template + UrsusBoot FIP
                 |
                 v
      ready 512 KiB install mtd0
```

Example:

```bash
URSUS_FIP=reference/md/ursusboot-test61-update.fip \
  ./build.sh xg040-md persistent
```

This emits `dist/xg040-md/ursusboot-install-mtd0.bin`.

For a completely bricked unit the same board template can be used by the Airoha BootROM/UART recovery flow. For a running Nokia stock firmware, a host installer can write the board-correct image through the rooted stock environment and verify readback. Device MAC/identity can be restored or configured separately from the sticker/device identity source when required.

## Repository layout

```text
build.sh                  single build entry point
scripts/                  host-side build and QA helpers
config/                   Kconfig fragments, full configs, board profiles
boards/                   board policy headers + 512 KiB stock boot-area templates
reference/                reference FIP used when no URSUS_FIP is given
src/u-boot/               complete U-Boot 2026.07 source tree with UrsusBoot on top
dist/                     build output (git-ignored)
```

The UrsusBoot delta inside `src/u-boot/` is deliberately small and localized:

```text
cmd/ursusdispatch.c       boot dispatcher
cmd/ursusweb.c            WebFailsafe HTTP server, validation and staging
cmd/ursusubi.c            UBI update/migration engine
cmd/ursusupdate.c         FIP (bootloader) validation and update
cmd/ursusstock.c          stock bridge boot
cmd/ursusled.c            LAN/status LED policy
include/ursusweb_ui.inc   embedded web UI (HTML/CSS/JS as a C string)
include/ursus_*.h         shared headers
include/ursus_logo.inc    embedded logo/favicon
drivers/gpio/ursus_an7581_safe_gpio.c
defenvs/                  per-board default environments
```

## Host-side scripts

| Script | Purpose |
|---|---|
| `build.sh` | Build U-Boot for a board and, when a FIP is available, emit a ready `mtd0` install image. |
| `scripts/make-install-mtd0.py` | Merge a 512 KiB stock boot-area template with a FIP into a flashable `mtd0` image. Validates size, FIP magic and that the FIP does not overlap the preserved env area. Prints the SHA256. |
| `scripts/qa.sh` | Offline QA: byte-checks the board templates and the reference FIP, validates `board-profiles.json`, compiles the Python helpers, asserts the source tree is complete and self-contained. Run by CI. |
| `scripts/resolve_board_profile.py` | Read one field of one profile out of `config/board-profiles.json`. |
| `scripts/apply_kconfig_fragment.py` | Apply a `.cfg` Kconfig fragment onto a `.config`. |
| `scripts/apply_board_policy.py` | Apply a board policy header/anchors to the source tree. |
| `scripts/apply_runtime_role.py` | Switch the default environment between the `persistent` and `ram-recovery` runtime roles. |

Building:

```bash
OPENWRT_SDK=/path/to/openwrt-sdk ./build.sh xg040-md
URSUS_FIP=reference/md/ursusboot-test61-update.fip \
  OPENWRT_SDK=/path/to/openwrt-sdk ./build.sh xg040-md
```

```bash
OPENWRT_SDK=/path/to/openwrt-sdk ./build.sh xg040-md ram-recovery
```

`OPENWRT_SDK` (or the third positional argument) must point at an extracted OpenWrt SDK; the AArch64 cross compiler is located inside it automatically. Outputs land in `dist/<board>/`.

Boards, configs, templates and roles all come from `config/board-profiles.json` — `build.sh` hardcodes nothing and refuses unknown boards, unknown roles and roles a board does not allow. A board that is described but not yet buildable (no `config` declared) fails with an explicit message rather than a confusing build error.

The runtime role is applied **at source level** before the build: `ram-recovery` rewrites `bootcmd` in the default environment inside the tree, so it needs a clean checkout and cannot be applied twice in a row. Restore with:

```bash
git checkout -- src/u-boot/defenvs src/u-boot/include
```

### Runtime roles

| Role | `bootcmd` | Purpose |
|---|---|---|
| `persistent` | `ursusdispatch` | Normal persistent supervisor boot from flash. |
| `ram-recovery` | `ursusweb;true` | RAM-only WebFailsafe recovery: go straight to the web UI and never touch the boot path. |

## Built-in commands

UrsusBoot adds seven U-Boot commands. All of them are ordinary console commands and can be composed from the environment or typed by hand over UART.

| Command | Arguments | What it does |
|---|---|---|
| `ursusdispatch` | — | The boot policy. Samples the Reset button at boot; if held past the debounce window it latches recovery and enters WebFailsafe. Otherwise it picks a boot path from what is actually on NAND: UBI present → `ursusubiboot`; stock factory kernel present → direct `mtd read` + `bootm`; otherwise → `ursusstockboot`. **Every path that returns falls back to WebFailsafe rather than to a dead prompt.** |
| `ursusweb` | — | Runs WebFailsafe: brings up Ethernet and lwIP, serves the UI and HTTP API on `192.168.1.1:80`, and polls a live UART shell in the same loop. Re-entry is a no-op (`URSUS_WEB_ALREADY_RUNNING`). |
| `ursusubiboot` | — | Boot OpenWrt from the UBI `fit` volume. |
| `ursusstockboot` | `[master\|slave]` | StockBridge boot with Nokia `tcboot` board-argument parity. |
| `ursusupdate` | `check\|write <addr> <len>` | Validate, and optionally write, an UrsusBoot FIP staged in RAM. |
| `ursussettings` | `reset` | Erase and recreate only `rootfs_data` on an OpenWrt UBI or factory layout. Firmware and bootloader are untouched. |
| `ursuslanled` | `status\|enable` | Nokia LAN2-LAN4 hardware PHY LED routing. |

### Environment scripts

`defenvs/<soc>_<board>_env` holds the default environment. The useful entry points:

| Variable | Role |
|---|---|
| `bootcmd` | `ursusdispatch` — the dispatcher above. |
| `boot_tftp`, `boot_tftp_forever` | Netboot a recovery image, optionally in a retry loop. |
| `boot_tftp_write_fip`, `boot_tftp_write_bl2` | Fetch and write the bootloader over TFTP. |
| `ubi_write_production`, `ubi_read_production` | Write/read the OpenWrt `fit` volume. |
| `ubi_write_fip`, `ubi_create_env`, `ubi_format` | UBI volume management for the boot area. |
| `ethaddr_factory` | Derive the factory MAC from the `ri` volume. |
| `reset_factory` | Zero both `ubootenv` volumes back to defaults. |

> These TFTP paths run from the dispatcher or the console **instead of** WebFailsafe, not alongside it. WebFailsafe itself never issues a network command.

## Web UI

WebFailsafe serves one self-contained page from flash — no external assets, no CDN, RU/EN switchable. Layout:

```text
+-----------------------------------------------------------+
| UrsusBoot   <bear>                              [RU] [EN]  |
+-----------------------------------------------------------+
| tile: model/SoC | tile: layout | tile: flash | tile: state |
+---------------------------------+-------------------------+
| Install OpenWrt                 | UrsusBoot status        |
|   [ drop / pick firmware file ] |   version, build        |
|   [x] keep settings             |   layout, FIP, FIT      |
|   [Check firmware]              |   NAND geometry         |
|   [Install OpenWrt]/[Update]    |   UBI PEB/LEB counters  |
|   [OpenWrt UBI migration]       |   bad blocks            |
|   [Reset OpenWrt settings]      |   network state         |
|   validation result + reasons   |   [Reboot into OpenWrt] |
+---------------------------------+-------------------------+
| Tabs: Validation log | U-Boot console | Initramfs/FIT |    |
|       Update UrsusBoot                                     |
+-----------------------------------------------------------+
| Diagnostics (operation log, progress, stage, transaction)  |
+-----------------------------------------------------------+
```

The left column is the main firmware channel, the right column is read-only state plus the reboot control, and the tab strip holds the expert tools. Status is polled from `GET /api/status`; the log from `GET /api/log` and `GET /api/operation-log`.

### What each button does

Every button that can write requires an explicit confirmation header, and **no write happens inside the HTTP handler**: the endpoint validates, arms a pending operation, answers, and the NAND work then runs in the `ursusweb` main loop where progress is reported. Reboot is always manual.

| Button | Endpoint | Confirmation | Preconditions | Effect |
|---|---|---|---|---|
| **Check firmware** | `POST /api/firmware-begin` + `…/firmware-chunk` | — | — | Stages the file into RAM and classifies it. Read-only. |
| **Remove file** | `POST /api/discard` | — | — | Drops the staged image and its metadata. |
| **Install OpenWrt** | `POST /api/install-openwrt-stock-layout` | `INSTALL-OPENWRT-STOCK-LAYOUT` | Validated non-UBI sysupgrade; layout `STOCK` or `OPENWRT_STOCK_LAYOUT` | Arms the stock-layout install. |
| **Update OpenWrt** | `POST /api/install-ubi` | `INSTALL-UBI` + `X-Ursus-Keep-Settings: 1\|0` | Validated UBI sysupgrade; layout `OPENWRT_UBI`; no other operation active | Starts the UBI update. Answers `reboot: MANUAL`. |
| **OpenWrt UBI migration** | `POST /api/install-ubi` | `INSTALL-UBI` + `X-Ursus-Keep-Settings: 0` | Validated UBI sysupgrade; layout `STOCK`/`OPENWRT_STOCK_LAYOUT`; validated UBI preloader **and** a valid 128 KiB BL2 candidate | Reformats NAND to the canonical UBI layout. BL2 is committed last. |
| **Reset OpenWrt settings** | `POST /api/reset-openwrt-settings` | `RESET-OPENWRT-SETTINGS` | An OpenWrt layout; no operation active | Erases and recreates only `rootfs_data`. |
| **Check initramfs** | `POST /api/initramfs-begin` + `…/initramfs-chunk` | — | — | Stages and validates a standalone FIT. Read-only. |
| **Boot once** | `POST /api/expert/boot-once` | — | A validated bootable FIT | Boots the staged FIT from RAM. Writes nothing; `automatic_sysupgrade: false`. |
| **Validate UrsusBoot FIP** | `POST /api/ursus-fip-begin` + `…/ursus-fip-chunk` | — | — | Stages and validates a FIP. Read-only. |
| **Update UrsusBoot** | `POST /api/update-ursusboot` | `UPDATE-URSUSBOOT` | Fully received, validated FIP; no migration or FIP update active | Writes the bootloader FIP with readback verification. |
| **Reboot into OpenWrt** | `POST /api/reboot` | `REBOOT` | **A flash operation must have completed** | Reboots. Refused with 409 at any other time. |
| **Run** (console tab) | `POST /api/console` | `X-Ursus-Command` | — | Runs the command on the real U-Boot command line and returns the captured output. No allowlist. |

### Preparation and flashing pipeline

```text
pick file
  -> POST /api/<kind>-begin      declare size, generation, filename
  -> POST /api/<kind>-chunk ...  stream into the RAM staging window
  -> classify + validate         container, FIT, hashes, fwtool metadata,
                                 supported_devices, layout applicability
  -> status/log show a class     OK or a specific refusal reason
  -> operator confirms           explicit button + confirmation header
  -> operation armed             endpoint answers, then the main loop works
  -> write + readback verify     progress, stage and transaction state
  -> manual reboot               only after a completed operation
```

Recognized image classes: OpenWrt non-UBI sysupgrade (tar), OpenWrt UBI sysupgrade (FIT with fwtool metadata), standalone FIT (Expert channel only), factory kernel and factory rootfs (recognized, never accepted by the main channel).

Refusals are typed rather than generic — `OK`, `UPLOAD_INCOMPLETE`, `BAD_CONTAINER`, `BAD_FIT`, `HASH_MISMATCH`, `METADATA_MISSING`, `DEVICE_MISMATCH`, `UNSUPPORTED_IMAGE_CLASS`, `IMAGE_TOO_LARGE`, `LAYOUT_UNSUPPORTED`, `OPERATION_LOCKED` — so the UI and any host orchestrator can explain exactly why an image was rejected.

### HTTP API

```text
GET  /                              UI
GET  /logo.svg  /favicon.svg        embedded assets
GET  /api/status                    full machine-readable state
GET  /api/log                       validation log
GET  /api/operation-log             flash operation log
POST /api/console                   run a U-Boot command (X-Ursus-Command)
POST /api/firmware-begin|-chunk     main firmware channel
POST /api/initramfs-begin|-chunk    expert FIT channel
POST /api/ubi-preloader-begin|-chunk  migration preloader
POST /api/ursus-fip-begin|-chunk    bootloader FIP
POST /api/discard                        drop staged firmware
POST /api/expert/discard                 drop staged initramfs
POST /api/ubi-preloader-discard          drop staged preloader
POST /api/ursus-fip-discard              drop staged FIP
POST /api/install-openwrt-stock-layout   install (confirmation required)
POST /api/install-ubi                    update or migrate (confirmation required)
POST /api/reset-openwrt-settings         rootfs_data reset (confirmation required)
POST /api/update-ursusboot               bootloader update (confirmation required)
POST /api/expert/boot-once               RAM boot of a validated FIT
POST /api/reboot                         reboot (confirmation + completed operation)
```

Upload headers: `X-Ursus-Total`, `X-Ursus-Generation` and `X-Ursus-Filename` on `begin`; `X-Ursus-Offset`, `X-Ursus-Total` and `X-Ursus-Generation` on each `chunk`. A generation mismatch invalidates the session rather than silently mixing two uploads.

## UrsusFlasher: the recommended host orchestrator

[UrsusFlasher](https://github.com/Medvedolog/airoha-router-ursusflasher) is the companion **Windows and Linux installer/orchestrator/backup tool**. UrsusBoot is deliberately usable on its own, but UrsusFlasher provides the convenient operator layer around it:

- detects known Airoha/Nokia models and current boot/storage state;
- performs backups and validates them;
- installs or updates UrsusBoot from Nokia stock Linux, OpenWrt or UrsusBoot Recovery;
- performs readback verification and recovery workflows;
- handles Airoha BootROM/XMODEM/UART recovery for bricked devices;
- can be used as a transport/orchestrator for a **custom locally built UrsusBoot**, including Airoha hardware not yet represented by a first-class UrsusFlasher board profile, through the explicit Airoha UART/Brick-mode recovery path.

In other words, **UrsusBoot is the bootloader/recovery framework; UrsusFlasher is the operator-friendly installer, backup and recovery workstation around it.**

## Baseline

The initial public standalone baseline is the TEST61 lineage used by the Nokia XG-040G-MD work, with subsequent board modularization for XG-040G-MF / AN7583 and other Airoha targets. Historical TEST57-TEST60 iteration scripts are intentionally not part of the public build surface; TEST61 is treated as the clean baseline.

## Porting model

Porting should be board-policy driven rather than fork driven:

```text
UrsusBoot core
  +-- common WebFailsafe / image / UBI logic
  +-- Airoha SoC support
  +-- board policy
  |     +-- NAND geometry
  |     +-- boot/FIP layout
  |     +-- Ethernet/reset quirks
  |     +-- identity locations
  |     +-- supported image classes
  +-- storage policy
```

See `docs/PORTING.md`.

## Credits and lineage

UrsusBoot exists because a substantial amount of bootloader and OpenWrt work came before it. Particular thanks and respect go to:

- **Daniel Golle (dangowrt)** — for the OpenWrt U-Boot/UBI installation model, recovery-oriented bootloader work and the broader idea that the bootloader can understand OpenWrt rather than merely chainload it: https://github.com/dangowrt
- **hanwckf** — for the MediaTek `bl-mt798x` work, failsafe Web UI, multi-layout and direct firmware installation ideas that became a reference point for the wider router community: https://github.com/hanwckf/bl-mt798x
- **Yuzhii0718** — for continuing and extending that ecosystem, including modern WebFailsafe, DHCP/recovery and Airoha/MediaTek bootloader work used as a practical reference: https://github.com/Yuzhii0718
- **OpenWrt developers** — for the platform, image formats, U-Boot integration and the SDK/toolchain this project builds against: https://github.com/openwrt/openwrt
- **U-Boot and Trusted Firmware-A developers** — for the upstream boot stack on which all of this ultimately rests.

UrsusBoot is not presented as an isolated invention. It is a compact Airoha-focused continuation of ideas developed across that community, with its own board-policy, recovery, validation and transactional safety work layered on top.

## Safety

A successful software build or CI run is **not** hardware validation. New board ports must be treated as unproven until tested on real hardware with a documented recovery path.

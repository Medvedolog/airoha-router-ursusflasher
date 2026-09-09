# Development checkpoint — `feature/mf-an7583` / MF2 HWTEST4 / STOCKRESTORE1 (2026-09-09)

- Added the MD/MF `BoardProfile` layer and family-aware device/write policy. MD remains the reference production/HW baseline; MF broad persistent writers remain disabled.
- Added native Airoha AN7583 UrsusBoot-MF MF2 RAM bring-up. MF2 uses `ENV_IS_NOWHERE`, `bootcmd=ursusweb`, no generic MTD/UBI writer commands, hard `-EROFS` gates on Ursus persistent entry points, and globally rejects HTTP POST in RAM-only mode.
- MF2 source/build artifact auditing now checks the exact AN7583 target, BL31 byte identity, BL33 LZMA round-trip, forbidden MD identity leakage, writer Kconfig state, and generated reports.
- HWTEST4 narrows the first Ethernet acceptance target to AN7583 internal GPHY LAN2/LAN3 only: `gpio2 -> phy2_led0`, `gpio3 -> phy3_led0`. LAN1/EN8811 is explicitly not linked and LAN4 remains deferred.
- HWTEST4 FIP: 294272 bytes, SHA256 `5ac6d1fad0805d4fe256fa44ac99043f4874137b39023fb1c44cf6ca105a52f6`; U-Boot SHA256 `1f4ddd95758f3621e58fa4d9c2db5d41705050686c0cb0b4e65bf4e2036c1c4e`; UART preloader remains 118322 bytes / SHA256 `c2ac1c183b18bc34632c958dfe0bd1dfdfb607f090e39c41126956641893362f`.
- GitHub Actions run `34360701468` passed build, compiled-source scope checks, independent artifact audit, and artifact upload. Artifact: `ursusboot-mf2-ram1-an7583-hwtest4`, ZIP SHA256 `48ea1830f0d8befd0f31d5bd4de9659cd1a2d089c5f3e391b4b6edd2926de162`.
- `mf_ramboot.py` now pins the exact green HWTEST4 FIP identity instead of the previous MF2 candidate.
- EXPERT item 6 is now wired to a common MD/MF stock-restore coordinator. It chooses a family-specific no-UART U-Boot -> RAM recovery-initramfs route when a proven running OpenWrt/recovery environment is available, otherwise the BootROM/XMODEM UART route.
- Fixed the retained no-UART restore cross-board bug where the old helper could select the MD recovery initramfs for an MF backup.
- Stock restore preserves the Ursus transaction policy: one meaningful `[y/N]`, no automatic second bootcmd/writer after an unknown handoff, critical readback, and BL2 last when BL2 is touched.
- MF `restore_nokia` is the only profile-scoped persistent-write exception; MF install/OpenWrt/bootloader/custom/recover writers remain blocked.
- Permanent `stock-restore-qa.yml` and integration selftests are green. Ursus restore integration is **STATIC QA PASS / HW ACCEPTANCE REQUIRED**; the underlying UART destructive backend has MedveFlasher hardware lineage, but the Ursus coordinator itself is not yet declared HW-proven.
- Remaining recovery debt: direct network-U-Boot entry when no production OpenWrt is alive, and emergency compatible-donor backup restore with explicit RI serial/MAC reconstruction.
- MF2/HWTEST4 status is **STATIC QA PASS / HW-TEST CANDIDATE**, not hardware proof.

# 0.2.61 PUBLIC TEST — TEST61 / SAFETYREG1

- TEST59/60 are revoked for new hardware runs: split identity between `.scmversion` and `URSUS_VERSION` could make ONE-CLICK launch an unnecessary second FIP write after a proven direct mtd0 write/readback.
- IDENTITY1: TEST61 reports one identity through native `version`, Web/API and build metadata.
- NOAUTOFIP1: ONE-CLICK never updates an already installed UrsusBoot automatically; self-update is an explicit WebFailsafe/EXPERT operator action only.
- UBIATTACH2: explicit FIP self-update reuses the expected active UBI attachment without `ubi detach`; an attachment mismatch stops before the writer.
- UPLOADRETRY1/UPLOADABORT2: reconnect grace is 75 s; a new full upload cycle requires `[y/N]`; failure before the operation POST is recorded as `transaction_state=NOT_STARTED`.
- SESSIONRECOVERY1: upload/validation/precheck failure before a writer does not lock the next attempt.
- Direct stock mtd0 write always has one `[y/N]` after backup/preflight. EXPERT item 1 may explicitly skip the full backup for the current test run; the required live mtd0 capture remains.
- POSTSYSRESET1: after a successful UBI update with `keep_settings=1`, UrsusFlasher offers an optional OpenWrt settings reset.
- DIAGSTATE1: stock self-update no longer reports a false `UBI_VERIFY` success stage.
- EMERGENCYMETA1: production TEST61 FIP metadata and emergency BootROM alpha3 metadata use separate manifest/hash fields.
- REPROZIP1: PUBLIC TEST packaging uses a fixed `SOURCE_DATE_EPOCH`; independent builds must produce the same ZIP SHA256.
- ROUTE1 integration: a positive `nokia_stock` fingerprint now reaches the authenticated read-only stock probe; generic HTTP remains ambiguous.
- Fixed direct launch from a Git checkout, `config/UI_TERMS.json` discovery, the GitHub-safe SDK file list, and the TEST61 payload reference manifest. Manifest and ZIP path ordering is canonical across Windows and Linux.
- CONFIGTRIM1 remains enabled. TEST61 is source/build/package QA only and requires hardware safety regression.

# UrsusFlasher changelog

## 0.2.56 — alpha5-UBIUX1 / ROUTE1 / ROOTFSENV1

- Persistent UrsusBoot target is now `0.1.0-alpha5-UBIUX1`; Fudan/SkyHigh NAND driver lineage is unchanged from alpha4-FUDAN1.
- UrsusBoot Recovery permits `OPENWRT_STOCK_LAYOUT → OPENWRT_UBI` through the same physical migration backend as `NOKIA_STOCK → OPENWRT_UBI`; BOSA/RI/FIP are preserved and full BL2 is committed last.
- Web Recovery adds a keep-OpenWrt-settings checkbox for UBI updates and a separate reset-settings action. UART/U-Boot adds `ursussettings reset`.
- Fresh/reset `rootfs_data` uses MAX−16 PEB and persists the exact byte size in `rootfs_data_max`, keeping later standard OpenWrt sysupgrade overlay sizing consistent. Existing user data is not shrunk when settings are preserved.
- ROUTE1 removes the Telnet-port-as-STOCK heuristic. OpenWrt and Nokia STOCK routes require positive environment proof; ambiguous state stops without a stock fallback.
- Host `web-fit` asks whether to preserve settings on UBI updates.

# UrsusFlasher change log

This file lists released behavior only.

## 0.2.55 — STATEUI8 / DIAGAUTH1 / BACKUPRAW1

- EXPERT items 7, 10 and 11 may perform an interactive read-only root SSH probe when passive detection is incomplete. System OpenSSH asks for the password; UrsusFlasher does not store it or install a temporary key.
- Item 7 no longer calls the inherited global `verify_kit()` and no longer depends on legacy `transition-bundle.bin` payloads.
- The MD read-only BootROM path pins only the required RAM preloader, RC18 RECOVERY_SAFE FIP and recovery initramfs by exact size/SHA256.
- OpenWrt UBI exact backup captures the full physical 256 MiB `mtd0_all_flash.bin.gz` through BootROM → RAM → read-only `/dev/mtd0` → TFTP, with per-chunk reread SHA256 and a final full-image SHA256.
- UBI backups also contain `mtd1_bl2.bin.gz`, `mtd2_ubi.bin.gz`, `RAW_BACKUP.json` and `SHA256SUMS.txt`; EXPERT item 8 validates this format.
- Nokia STOCK keeps the existing `mtd0..mtd16` backup format. FUDAN1 and bundled OpenWrt images are unchanged.

## 0.2.54 — STATEUI7 / MENUOPS1

- EXPERT item 2 now covers both UrsusBoot install and update; item 4 is hidden and retained as a compatibility alias.
- Every EXPERT item has a short action/transport explanation.
- Custom OpenWrt can be flashed from installed OpenWrt via SSH upload, `sysupgrade -T`, and `sysupgrade -v -n`, or from UrsusBoot Recovery over HTTP.
- FUDAN1 and bundled OpenWrt images are unchanged.

## 0.2.53 — ERRORUI1 / SSHBIN1

- EXPERT and ONE-CLICK now print one short `[CAUSE] ...` line in the operator UI while retaining the full exception in the session log.
- UrsusBoot installation from OpenWrt no longer depends on a remote `base64` utility for FIP/boot-block reads; binary stdout is captured directly over system OpenSSH with stderr kept separate.
- Fixes the observed Chinese OpenWrt failure `ash: line 0: base64: not found` before any FIP write began.
- FUDAN1 and OpenWrt firmware images are unchanged.

## 0.2.52 — STATEUI6 / ACTIONPREFLIGHT1

- Passive `DeviceState` no longer acts as a global write gate.
- Actions 1, 2 and 5 remain selectable when passive detection is incomplete; each operation performs its own authoritative preflight.
- OpenWrt SSH authentication may prompt only after an action is selected.
- Device state was removed from the EXPERT header and remains available through informational item 10.
- Build-change prose was removed from the EXPERT banner and kept in the changelog.
- Fixed explicit UTF-8 reading in `selftest_rootfsmax2.py` on Windows.

## 0.2.51 — STATEUI5

- Refined Russian operator terminology.
- Renamed the normal bootloader action to distinguish it from emergency recovery.
- Firmware payloads and writer backends are unchanged from 0.2.50.

## 0.2.50 — STATEUI4

- Added `PERSISTENT_ROOT`, `RAM_ROOT` and `UNKNOWN` execution-environment classification.
- Bootloader installation now reports the resolved Telnet/SSH method.

## 0.2.49 — PAYLOADREFRESH1

- Replaced the two production Nokia XG-040G-MD sysupgrade images with the UnameOne build dated 2026-09-06.
- Kept the existing service/recovery initramfs assets.
- Added the LAN2/LAN3 flashing recommendation and documented LAN4-as-WAN behavior.

## 0.2.48 — STATEUI3

- Machine values without a registered UI translation now fail closed.
- Added complete enum translation coverage tests.

## 0.2.47 — STATEUI2

- Made `probe_status` monotonic within one probe run.
- Routed DeviceState values and probe reasons through the UI translation layer.

## 0.2.46 — STATEUI1

- Added the common read-only `DeviceState`.
- Added full read-only flash backup and the durable host operation journal.
- Introduced the stable EXPERT 1–12 task menu.

## 0.2.45 — FUDAN1 / SSH1

- Added Fudan FM25G01B/FM25G02B support to UrsusBoot.
- Added persistent UrsusBoot installation from OpenWrt over root SSH.
- Added full readback verification for UBI FIP and raw boot-block writes.

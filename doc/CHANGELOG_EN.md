# CHANGELOG

## 0.1.0-md-lab1fix10 — 2026-08-18

- Cleaned release packaging: root now contains one short `README.md`, launchers, version/checksums, and runtime directories.
- Moved/reworked `README_RU.md` / `README_EN.md` as `doc/INSTRUCTIONS_RU.md` / `doc/INSTRUCTIONS_EN.md`.
- Moved historical patch notes under `doc/history/`; renamed `docs/` to `doc/`.
- Rewrote `doc/ARCHITECTURE_RU.md` and `doc/ARCHITECTURE_EN.md` as the canonical architecture + tcboot know-how documents.
- Promoted the exact patch8 bear WebFailsafe bytes to HW VERIFIED.
- HW VERIFIED: a repeated tcboot Web sysupgrade after booted OpenWrt preserves tcboot and WebFailsafe.
- Documented current update semantics: `fit` and `rootfs_data` are recreated; tcboot survives, but overlay/configuration is not preserved.
- Reset instruction remains hardware-fixed: power ON -> immediately Reset -> hold 10 seconds -> release.

## 0.1.0-md-lab1fix9 — 2026-08-18

- Patch7 FDT-AWARE is hardware-confirmed end-to-end through OpenWrt: `reg=<0x00100000 0x0ff00000>`, Linux 6.18.44, correct UBI attach, UBIFS `rootfs_data`, overlay, and `procd` console.
- tcboot WebFailsafe entry is standardized from hardware testing: power ON -> immediately press Reset -> hold **10 seconds** -> release.
- Patch8 keeps the HW-verified FDT/UBI/boot core and changes tcboot Web branding only: `🐻 OPENWRT`, `🐻 UPDATING`, `🐻 UrsusFlasher WebFailsafe`, marker `UrsusITB FDT p8`.
- Default patch8 SHA256: `7c202a9c35dfcc10b85a1ad7f3d8cf34dbabfcb23287f26d9b5376f582772766`.
- Exact patch8 bytes: static/rebuild QA PASS; short HW Web regression pending.

## 0.1.0-md-lab1fix8 — 2026-08-18

- Hardware patch6 reached `Starting kernel`, Linux 6.18.44 and `Machine model: Nokia XG-040G-MD (UBI)`; failure was localized to a malformed runtime `ubi reg` produced by the old raw-memory `cp.b`.
- Added stdlib FIT/FDT preflight: `/configurations/default`, dynamic kernel/FDT/loadables names, image-hash verification, recursive exactly-one `label=ubi` discovery, `#address-cells/#size-cells` decoding, and geometry gate.
- Removed hardcoded working-FDT RAM address and `cp.b`; patch7 uses `fdt set $up reg <generated cells>` plus `fdt print $up reg`.
- tcboot is now deterministically personalized for the selected sysupgrade's actual UBI node path before NAND write; router-side SHA and full mtd0 byte readback use that generated tcboot.
- Added `.itb` selection; the exact 10,518,808-byte hardware-tested sysupgrade is bundled under `fw/` as the default.
- Added a built-in tcboot HTTP/1.0 multipart uploader using field `firmware`, exact Content-Length, no chunked transfer, and no Expect.
- tcboot FIT gate is no longer pinned to literal `config-1/kernel-1/fdt-1/rootfs-1`; profile description remains the model safety gate.
- Status: `PATCH7_FDTAWARE_LAB_WRITE_NOT_YET_HW_VERIFIED`.

## 0.1.0-md-lab1fix7 — 2026-08-18

- The patch5 hardware run confirmed a complete FIT write/readback: `fit` = 10,518,808 bytes and kernel/FDT/rootfs hashes pass after reset.
- The failure is localized after `bootm fdt`: the FDT is relocated, then `subcommand failed (err=-1)` is returned.
- Patch6 BOOTFIX keeps tcboot/WebFailsafe and removes the separate `bootm cmdline` and `bootm bdt` stages.
- The ARM64 boot chain is now `start -> loados -> ramdisk -> fdt -> runtime UBI-reg patch -> prep -> go`.
- UART markers cover begin/success for each bootm stage and `U:KERNEL_GO`.
- tcboot remains the permanent recovery loader for later OpenWrt reinstalls through WebFailsafe.
- Patch6 status: `LAB_WRITE_BOOTFIX`; next hardware gate is `Starting kernel` + Linux boot + Reset WebFailsafe after power-cycle.

## 0.1.0-md-lab1fix6 — 2026-08-18

- Fixed the destructive-confirmation input race by flushing queued console input immediately before the prompt.
- An empty Enter no longer cancels and can never authorize a NAND write.
- Destructive cancellation is explicit only: `0`, `CANCEL`, or `ОТМЕНА`.
- A mismatched confirmation phrase is re-prompted; NAND remains unchanged until exact confirmation.
- The tcboot payload remains patch5 unchanged.


## 0.1.0-md-lab1fix5 — 2026-08-18

- The hardware patch4 run reached full UBI migration, volume creation, environment save and reset, but created a 256 KiB `fit` volume: an intermediate `ubi read ... ri 0x40000` clobbered U-Boot's global `$filesize`. After reset the FIT header parsed, but the kernel hash failed.
- Patch5 snapshots the HTTP upload size/address immediately as `us`/`ua` and uses only those pinned values for `ubi create fit`, `ubi write`, full readback and `cmp.b`.
- Fixed stock `bosa`/`ri` preservation: unsupported `flash read` is replaced with raw `mtd read ubi` at relative offsets `0x50c0000` and `0x5100000` before `mtd erase ubi`.
- CAL_SAVE is now fail-closed: erase cannot start unless both calibration dumps were read successfully.
- Patch5 remains `LAB_WRITE` until a new stock → tcboot → full sysupgrade → OpenWrt → power-cycle → Reset Web recovery hardware run passes.


## 0.1.0-md-lab1fix4 — 2026-08-18

- Fixed the first HW direct-sysupgrade failure: removed the negative boundary probe `mtd read ubi ... 0xff00000`, whose intentional `-22` failure aborted the HTTP upgrade before `mtd erase ubi`.
- UBI state is now detected without expected failures: successful offset-0 read plus UBI magic; if magic exists attach must succeed, otherwise stock→UBI migration is used.
- Expanded UART trace with `U:UBI_PROBE_BEGIN`, `U:UBI_EXISTING_MAGIC`, `U:UBI_ATTACH_BEGIN/OK`, `U:ERROR_*`, and explicit format BEGIN/DONE.
- The first failed HW upload is confirmed as a pre-erase failure; UBI was not formatted by that attempt.
- Retains the manual MD power-cycle + Reset 10 s prompt, HTTP/1.0 tcboot detection, stdlib-only runtime, and expert backup policy.


## 0.1.0-md-lab1fix2 — 2026-08-18

- Added expert backup policy: foreign/unbound backup, manual MTD dumps, or no backup under explicit operator responsibility.
- Preserved the safe path: new STOCKSET or existing Ursus/MedveFlasher STOCKSET with restore validation plus DEVICE_MAC match.
- Fixed MD tcboot readback to use `/dev/mtd0` rather than `/dev/mtd0ro`.
- Post-write verification is now a complete `mtd_debug read` plus byte-for-byte `cmp`; the extra readback SHA was removed.
- The redundant pre-write live-`mtd0` SHA remains removed.

## 0.1.0-md-lab1fix1 — 2026-08-18

- Removed the erroneous pre-write current-`mtd0` SHA comparison against STOCKSET that stopped the first hardware run with `router=missing`.
- Kept the live destructive gate geometry-only; content proof is performed after write by complete tcboot readback.
- Switched readback to the proven stock `mtd_debug read /dev/mtd0ro`, followed by one SHA256 comparison.
- Added an `Install OpenWrt` sub-option to reuse an existing STOCKSET without another TFTP backup.
- Existing backups are fully revalidated through `verify_stock_restore_backup()` and must match the current Nokia through `DEVICE_MAC.txt`.
- The main beginner menu remains the stable three-action UI.

## 0.1.0-md-lab1 — 2026-08-18

- Added the first independent UrsusFlasher MD LAB runtime.
- Language selection is the first screen: Russian / English.
- Main UI uses the stable 3-action beginner menu.
- Ported the MedveFlasher stock Web AES/RSA/login backend.
- Ported the hardware-tested Telnet login, UID0 discovery and FTP provisioning semantics.
- Ported the hardware-tested TFTP STOCKSET `mtd0..mtd16` path with retries, completion markers and restore validation.
- Added pinned tcboot patch1 write to `mtd0` only, guarded by live geometry and complete readback SHA256.
- Added post-reboot tcboot `/flashing.html` detection.
- Bundled direct-sysupgrade patch1 but do not auto-run it in the first hardware gate.
- Deferred UFNAND1; it does not block LAB1 and STOCKSET is the mandatory backup gate.
- Removed Rich as a required runtime dependency; LAB1 imports on Python stdlib only.
- Added offline TFTP PUT/GET selftests plus stock Web crypto/parser selftest.
## 0.1.0-md-lab1fix3 — 2026-08-18

- Hardware finding: tcboot mtd0 write/readback passed; MD WebFailsafe requires a power-cycle and Reset immediately after power-on for 10 s.
- The post-write wizard now prompts that hardware gesture instead of assuming software reboot will enter WebFailsafe.
- tcboot detection uses a minimal HTTP/1.0 socket probe and a 404 control route.
- Added stdlib-only ANSI console styling: dim timestamps, colored menu choices and status classes.
- Added patch3 TRACE UART markers for FIT checks, UBI formatting, volume creation, calibration restore, FIT write/readback, env save and reset.
- Stock Nokia restore is not accepted as supported by the patched `/flashing.html`; use the UART/BootROM recovery path.

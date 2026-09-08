<div align="center">

<img src="img/ursus-bear.svg" alt="" width="72" height="72">

# UrsusFlasher

### OpenWrt on the Nokia XG-040G-MD: install, back up, recover

**Airoha AN7581 · 256 MiB SPI-NAND · UrsusBoot · OpenWrt**

![UrsusFlasher](https://img.shields.io/badge/UrsusFlasher-0.2.61-6f4b2f)
![UrsusBoot](https://img.shields.io/badge/UrsusBoot-0.1.0--alpha5--UBIUX1--TEST61-b36b32)
![Target](https://img.shields.io/badge/Nokia-XG--040G--MD-555)
![OpenWrt](https://img.shields.io/badge/OpenWrt-r36009%2B75-00a4ef)
![TEST61](https://img.shields.io/badge/TEST61-hardware_safety_regression_required-c27b00)

**[📦 Published builds](https://github.com/Medvedolog/airoha-router-ursusflasher/releases)** · [instructions](INSTRUCTIONS_EN.md) · [changelog](CHANGELOG_EN.md) · [emergency recovery](EMERGENCY_URSUSBOOT_RU.md)

🇷🇺 [Читать по-русски](../README.md)

</div>

---

## In short

The kit is two things, and they do different jobs.

**UrsusFlasher** runs on your computer. It looks at the state the router is in and picks how to talk to it: the stock firmware's web interface, SSH into an installed OpenWrt, the bootloader's own web page, or — when everything else is gone — USB-UART.

**UrsusBoot** lives in the router. It is a bootloader with a built-in recovery environment: it can accept an image over the network, verify it and write it. It is what turns "the router does not boot" from a verdict into an ordinary procedure.

No internet is needed while flashing — every image is in the kit.

<div align="center">

<img src="img/ursusboot-alpha5-recovery.png" alt="UrsusBoot 0.1.0-alpha5-UBIUX1 web interface: OpenWrt install on the left, state and diagnostics on the right" width="760">

<sub>UrsusBoot 0.1.0-alpha5-UBIUX1 in recovery. Left: the OpenWrt install panel and a one-shot initramfs boot that writes nothing. Right: state and diagnostics — layout, the `fip` and `fit` volumes, NAND and bad blocks.</sub>

</div>

That is a router with OpenWrt already installed: the layout is `OPENWRT_UBI`, which is exactly why the **Reset OpenWrt settings** button is visible. On stock firmware that spot is empty — what appears under which conditions is spelled out in the [instructions](INSTRUCTIONS_EN.md).

---

## Current development status

The current PUBLIC TEST candidate in `main` is **UrsusFlasher 0.2.61** with **UrsusBoot `0.1.0-alpha5-UBIUX1-TEST61`**. TEST61 contains the SAFETYREG1 fixes and still requires a complete hardware regression cycle before a new GitHub Release is published or the build is treated as production. The Releases page may therefore still contain an older published test build.

TEST59 and TEST60 are revoked for new hardware runs because their split build identity could make ONE-CLICK attempt an unnecessary second FIP write after a direct `mtd0` write/readback had already succeeded.

---

## Where UrsusBoot came from

At first there was none. Early UrsusFlasher ran on top of `tcboot` — a bootloader that arrived from the vendor as a finished binary. It worked, and that was confirmed on real hardware, but no sources ever turned up with it.

So the direction changed: the bootloader is now built from current OpenWrt/Airoha U-Boot with a WebFailsafe interface and a policy layer of its own. That is UrsusBoot. `tcboot` remains in the history as a reference for behaviour — it was compared against, but it is no longer in the kit.

The layout changed with it. Early experiments moved the start of UBI to make room for the bootloader, and that had a price: the official OpenWrt image no longer fit, and its flash map had to be patched on the fly. The layout now matches what OpenWrt expects for this board:

```text
0x00000000..0x0001ffff   BL2
0x00020000..end of NAND  UBI
                           ubootenv, ubootenv2, bosa, ri
                           fip          ← UrsusBoot goes here
                           fit          ← kernel and root filesystem
                           rootfs_data
```

Because of that the official `*-ubi-*` OpenWrt image installs as it is, with no rework. And the bootloader is stored not in a separate slice of raw flash but in the `fip` volume inside UBI — where the board's own boot chain looks for it.

### This is ordinary U-Boot, not something homegrown

The base is **U-Boot v2026.07** plus the OpenWrt/Airoha patches for this board and the UrsusBoot layer on top: the recovery page, the write policy and the checks. There is no from-scratch fork here, and anything you know from U-Boot behaves as usual.

**The native command line is reachable from two places.** Over UART it is the familiar prompt: the line goes straight into `run_command()`. In the web interface there is a "U-Boot console" tab, and it is **the same command line** — no allowlist, no write-operation lock. The source says so itself: *the real U-Boot command line*.

Which carries a warning: the console does not restrain you. The checks and confirmations described below guard the buttons of the web interface, not what you type by hand.

**What is available.** The build keeps the MTD and UBI command paths, networking with `tftpboot`, `ping`, `dhcp`, `wget`, `mii`, `mdio`, the environment commands, `bootm`, `fdt`, `gpio`, `led`, `button`, `hash`, `crc32`, and `lzma`/`unzip` decompression. TEST60/TEST61 CONFIGTRIM1 deliberately disables the UBIFS filesystem commands (`ubifsmount`, `ubifsload`, `ubifsls`, `ubifsumount`); the UBI layer itself remains enabled.

**What is disabled.** Another 93 command options are built without support, and that is worth stating plainly rather than waving it off as "almost nothing was cut". Gone are filesystems this path never touches (`ext2/4`, `fat`, `squashfs`, `btrfs`, `zfs`), buses and media the board does not have (`pci`, `ide`, `sf`/`spi`, `onenand`), and some debugging conveniences (`memtest`, `md5sum`, `sha1sum`, `date`, `bootmenu`, `history`, `cat`, `xxd`, `nfs`). Everything needed to boot, reach the network, work with NAND and recover is present.

---

## What UrsusBoot does and does not do

**It does:**

- accept an OpenWrt firmware image (UBI or factory) over the network — through its own web page, or over TFTP if that page is not answering;
- verify the image before writing: type, size, checksum;
- repartition when the image requires it, write, and **read back**, comparing what landed against what should have;
- enter Recovery on Reset even when the installed system is gone: after the router-wide LED restart, hold Reset through **2 short + 3 long** red flashes and release it on steady red; holding Reset **before power-on** enters Airoha BootROM instead;
- determine the router's current layout and the class of the uploaded image, and report both;
- work on its own: installing or reinstalling OpenWrt needs neither a working system on the router nor UrsusFlasher on a PC — its own web page is enough.

It survives a `sysupgrade` run from inside OpenWrt: that writes `fit` and `rootfs_data` and leaves the `fip` volume alone. And it can perform a sysupgrade itself. Two routes to the same result, not one instead of the other.

**It does not:**

- replace a backup: it can bring the router back to life, but it will not bring back your factory data if there is no copy;
- overwrite itself during an ordinary OpenWrt update: updating the bootloader is a separate operation, not a side effect of flashing;
- decide which transitions between layouts are permitted — those are UrsusFlasher's rules, see below.

One practical conclusion: **a backup is not a formality.** The bootloader can be restored; factory MAC addresses and calibration data cannot.

### Not every transition between layouts is allowed

UrsusBoot determines the layout and the image class; UrsusFlasher on the PC decides which transition is permitted:

| From | To | |
|---|---|---|
| Nokia stock | OpenWrt, UBI layout | allowed, if a validated transition candidate is confirmed |
| Nokia stock | OpenWrt, factory layout | allowed, if a validated image for it exists |
| OpenWrt, factory layout | OpenWrt, UBI layout | allowed **from Recovery**, since 0.2.56 |
| OpenWrt, UBI layout | OpenWrt, factory layout | **refused** |

Before 0.2.56 the move from the factory layout into UBI was closed: you chose the layout once, when leaving stock firmware. It exists now, but only through UrsusBoot Recovery and along the same destructive migration path as the move from Nokia stock — with the same checks of the UBI image, the transition preloader/BL2 and the physical layout.

The way back is still closed: you cannot return from UBI to the factory layout. Try it and UrsusFlasher refuses before any write and explains why.

---

## Current TEST61 safety-regression changes

- **IDENTITY1:** native `version`, Web/API, build metadata and host manifest all identify the bootloader as TEST61.
- **NOAUTOFIP1:** ONE-CLICK never self-updates an already installed UrsusBoot. A newer bundled bootloader is reported, but installing it is a separate explicit WebFailsafe/EXPERT action.
- **UBIATTACH2:** explicit FIP self-update reuses the expected active UBI attachment and does not run `ubi detach`; a mismatched attachment stops before the writer.
- **UPLOADRETRY1 / UPLOADABORT2:** interrupted HTTP upload remains RAM-only/`NOT_STARTED` before the operation POST, uses a 75-second reconnect grace, and requires `[y/N]` before starting a completely new transfer session.
- **SESSIONRECOVERY1:** upload, validation or precheck failure before a writer no longer locks out the next attempt.
- A direct stock `mtd0` write always gets one ordinary `[y/N]` after backup/preflight. EXPERT item 1 may explicitly skip the long full stock backup for that one test run, but the live `mtd0` capture remains mandatory.
- **POSTSYSRESET1:** after a successful UBI update with settings preserved, the host can offer an optional OpenWrt settings reset.
- **EMERGENCYMETA1:** production TEST61 and the pinned emergency alpha3 BootROM lineage use separate manifest/hash fields.
- CONFIGTRIM1 remains enabled; TEST61 still requires hardware safety regression.

---

## Getting started

> [!IMPORTANT]
> **Factory-reset the Nokia first.** This is required before every iteration — before the first install and before any retry after a failure. The reset is done on the stock firmware: hold Reset for **at least 20 seconds**, release, and wait for the reboot.
>
> Otherwise the stock system is in an unknown state: changed settings, services left on or off, and leftovers from earlier attempts, because of which device detection and access can behave differently from what is expected.

Unpack the archive and run from its folder:

| | Windows | Linux / macOS |
|---|---|---|
| **Ordinary install** | `START_ONECLICK.cmd` | `./START_ONECLICK.sh` |
| **Manual mode** | `START_EXPERT.cmd` | `./START_EXPERT.sh` |

Python **3.12+** and an Ethernet cable are all you need. No third-party Python packages are required.

If the task is simple — "install OpenWrt" — run **ONE-CLICK**. If you need something specific: update only the bootloader, take a backup, work out why the router is silent — **EXPERT**.

### Which port to use

**Use LAN2 or LAN3 for flashing.**

- **LAN1** is a separate 2.5 Gbit/s chip (EN8811H PHY) that needs its own initialisation. It is not suitable for flashing.
- **LAN4** becomes WAN once the bundled OpenWrt boots, and `192.168.1.1` will disappear on it in the middle of the job.

---

## How ONE-CLICK works

ONE-CLICK does not assume the router is in one particular state. It looks first and picks the route afterwards.

**The router is on Nokia stock firmware.** The flasher signs into the web interface, gets root over Telnet and takes a full copy of the flash over TFTP. The copy is verified. Only then is a new boot block prepared, written, read back in full and compared. The router then goes into UrsusBoot Recovery, which is where OpenWrt is handed over.

**OpenWrt is already on the router.** The conversation runs over root SSH. If the `fip` volume exists, that is what gets updated; the physical boot block is touched only when the target is confirmed unambiguously. Then read-back, comparison, and the move into Recovery. A system installed in flash and a system running from RAM are told apart and shown separately.

**UrsusBoot Recovery is already open.** Then the bootloader does not need reinstalling: the image is transferred in chunks, verified by the bootloader and written.

For the ordinary Nokia-stock ONE-CLICK path, the full backup is mandatory. Immediately before the persistent `mtd0` write, after backup/preflight, the flasher asks one ordinary `[y/N]`. EXPERT item 1 may explicitly skip the long full stock backup for that single test run; the live `mtd0` capture needed to preserve the ROM prefix/environment is still mandatory. ONE-CLICK does not automatically update an already installed UrsusBoot.

### ONE-CLICK always installs the UBI layout

Worth saying outright, because it offers no choice. The kit carries two OpenWrt images — one for the UBI layout and one for the factory layout — but **every ONE-CLICK path takes the UBI one**. That is deliberate: UBI is the target layout, the bootloader lives in it and everything else works there.

If you specifically need the **factory layout**, there are two routes and both are manual:

- **EXPERT, item 3 "Записать пользовательскую прошивку OpenWrt"** (write a custom OpenWrt image). It accepts any `.bin`/`.itb` — point it at the bundled `fw/openwrt-airoha-an7581-nokia_xg-040g-md-squashfs-sysupgrade.bin`. The image class is detected automatically and the write takes the factory-layout path.
- **The UrsusBoot web interface directly.** Upload the same file in Recovery and press "Install into factory layout".

Mind the one-way rule from the table above: you can move to the factory layout from Nokia stock, but **not** from an already installed OpenWrt UBI — such an image is refused before any write.

---

## Control and file-transfer channels

| Router state | Commands go over | Files go over |
|---|---|---|
| Nokia stock | HTTP/Web + Telnet | TFTP |
| OpenWrt in flash | SSH | SCP |
| OpenWrt from RAM | SSH | SCP |
| UrsusBoot Recovery | HTTP API | HTTP in chunks |
| UrsusBoot Recovery, fallback | UrsusBoot console | TFTP |
| Router does not boot | USB-UART → Airoha BootROM | XMODEM |

USB-UART is connected by **TX, RX and GND** only. VCC is not connected to the board.

---

## The EXPERT menu: which route each item takes

A `!` marks an item that can write to flash.

### Install

| | Item | Route |
|---|---|---|
| `!` | **1** Install OpenWrt | the ONE-CLICK route; on Nokia stock EXPERT may explicitly skip the full backup for this run; one `[y/N]` remains immediately before direct `mtd0` write |
| `!` | **2** Install or update UrsusBoot | Nokia stock → Web + Telnet; OpenWrt → SSH; Recovery → HTTP, TFTP on failure |
| `!` | **3** Write a custom OpenWrt image | OpenWrt → SSH, `sysupgrade -T` first, then the write; Recovery → HTTP |

Item **4** is merged into the second: typing `4` still works as an alias, kept out of habit.

### If the router does not boot

| | Item | Route |
|---|---|---|
| `!` | **5** Recover the bootloader | USB-UART → Airoha BootROM → service UrsusBoot in RAM → write and verify |
| `!` | **6** Restore the Nokia factory firmware | **not working yet** — the path is designed but not wired up |

### Backups

| Item | Route |
|---|---|
| **7** Take a full flash copy | SSH only to learn the layout → BootROM/USB-UART → read NAND from RAM → copy to the PC. Writes nothing |
| **8** Verify a backup | locally on the PC: contents, sizes, SHA256 |
| **9** Assemble a recovery kit | **not working yet** |

### Look

| Item | Route |
|---|---|
| **10** Device state and available operations | passive Web/SSH probe; asks for a password when needed |
| **11** Flash, layout and bad blocks | Web/SSH, USB-UART when needed; read-only |
| **12** Verify the kit files | local SHA256 and contents check |

Items **6** and **9** can be selected in this build but not executed: they say plainly that the backend is not wired up instead of pretending.

---

## What is checked before a write

The work is split into three independent things: determine the state, transfer the file, write. Checks stand between them.

Verified are the kit files, the model and SoC, the current layout, the specific write target, the state of the backup, and — on the router side already — the size and hash of the transferred file.

The background diagnostics in EXPERT neither permit nor forbid anything; they are informational. Whatever an operation actually needs, it checks itself, after you have chosen it. The root password, if one is needed, is asked for by the system OpenSSH; UrsusFlasher does not store it and installs no keys on the router.

---

## What is checked after a write

A successful return code from a write command proves nothing, so the result is read back: the whole 512 KiB of the boot block with a SHA256 comparison, and for the `fip` volume the entire written FIP. Where possible, the environment that actually answered after the reboot is checked too.

If the comparison does not match, there is no automatic retry by another route: this is the case where stopping and looking is the right move.

---

## Backups

Item **7** writes nothing.

On Nokia stock it saves `mtd0..mtd16` together with layout information and the data needed to prove later that the copy belongs to this device. No extra services are enabled just for the sake of copying.

If a copy cannot be taken safely from the running system, the Airoha BootROM route is used: the environment comes up in RAM, flash is not modified while it does, and the read happens from a state where nothing is writing to NAND behind your back. For OpenWrt with UBI this saves the entire physical 256 MiB `mtd0` (`mtd0_all_flash.bin.gz`) with a repeated SHA256 check, plus the convenient `mtd1_bl2` and `mtd2_ubi` slices.

A copy taken from a running, writable OpenWrt is not presented as an exact copy for a full restore.

---

## What is in the kit

Two OpenWrt images (UnameOne build of 2026-09-06, `r36009+75-6c315233aa`, kernel 6.18.44):

```text
fw/openwrt-airoha-an7581-nokia_xg-040g-md-squashfs-sysupgrade.bin       factory layout
fw/openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb   UBI layout
```

The current candidate bundles UrsusBoot `0.1.0-alpha5-UBIUX1-TEST61`. It keeps the Fudan/SkyHigh NAND line while carrying SAFETYREG1 and CONFIGTRIM1. TEST59/60 are retained only as forensic history and are revoked for new hardware runs.

> **TEST61 status:** source/build/package QA is complete, but a full hardware safety regression is still required. Historical full stock→OpenWrt ONE-CLICK PASS belongs to TEST57/SkyHigh; Fudan acceptance remains open.

Exact sizes and checksums of every component are in `SHA256SUMS` and `data/MANIFEST.json`. The full build version string lives in `VERSION`: it is long and meant for tooling, not for people.

---

## Checking that the kit is intact

From the menu, item **12**. From the command line, for the whole repository:

```bash
python3 scripts/verify_repo.py
```

It checks the checksums, the manifests, the boot components, the syntax of the Python files and the built-in selftests.

On Windows, clone the repository into a short path. If Git complains about `Filename too long`:

```powershell
git config --global core.longpaths true
```

`.gitattributes` pins LF for text and CRLF for `.cmd`, so `SHA256SUMS` matches regardless of the `core.autocrlf` setting.

---

## Releases

Published user kits are listed on the [Releases page](https://github.com/Medvedolog/airoha-router-ursusflasher/releases). The current 0.2.61/TEST61 candidate stays in `main` until the complete hardware cycle passes; no new Release is created merely because source/build/package QA passed. When publication is intentionally started, GitHub Actions (**Public test release**) verifies the repository, builds the archive and verifies the built archive separately.

SDKs, compilers, build trees and development tools are not in that archive: they belong to the repository, not to whoever is flashing a router.

---

## Documentation

- [`INSTRUCTIONS_EN.md`](INSTRUCTIONS_EN.md) — how to use it, step by step.
- [`EMERGENCY_URSUSBOOT_RU.md`](EMERGENCY_URSUSBOOT_RU.md) — USB-UART recovery when the router is silent (Russian).
- [`CHANGELOG_EN.md`](CHANGELOG_EN.md) — what changed from version to version.
- [`../FILES.md`](../FILES.md) — what the repository is made of.

---

## Licences

See [`../LICENSE-NOTICE.md`](../LICENSE-NOTICE.md). The repository contains components from several external projects; their notices and licences must be preserved when redistributing.

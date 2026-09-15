# Development changelog — modular Airoha branch

**Branch:** `feature/ursusboot-modular-airoha`  
**Current baseline date:** 2026-09-15  
**Scope:** engineering changes not yet promoted to `main` or release.

Published/release history remains in `docs/CHANGELOG_RU.md`.

---

## 2026-09-15 — TRANSITION2 HW findings / EXPERT integration correction

### Architectural correction: Vanilla Transition moves into EXPERT

The standalone `START_MD_TRANSITION.cmd/.sh` path exposed duplicate plumbing and caused regressions that the main UrsusFlasher stack had already solved elsewhere.

Decision:

```text
Vanilla Transition is NOT a ONE-CLICK action.
Vanilla Transition is a dedicated UrsusFlasher EXPERT action.
```

Target UI:

```text
START_EXPERT
-> EXPERT item 4
-> Stock Nokia -> Vanilla OpenWrt (TRANSITION)
```

Item 4 is intentionally reclaimed: current `expert.py` no longer displays it and typed `4` is only redirected to item 2 after install/update UrsusBoot were merged.

The transition action must reuse existing common UrsusFlasher infrastructure:

```text
DeviceState
board_profiles
stock Web authentication
Telnet credential discovery/enablement
root/su acquisition
full backup backend
proven transport backends
transaction logging
common y/N UI
full readback/verification
```

The standalone transition launcher becomes developer/HWTEST-only or is removed from the public operator kit after EXPERT integration.

### Full stock backup clarified

Production stock -> transition requires the classic complete stock backup:

```text
all live /proc/mtd partitions
exact sizes + erase sizes
SHA256 each
/proc/mtd snapshot
identity/MAC/serial/RI/factory metadata where applicable
BACKUP_MANIFEST.json
```

The temporary four-partition backup (`flag`, `flagback`, `nsb_master`, `nsb_slave`) is insufficient and must not remain the production contract.

### Mandatory stock factory-reset preparation

Before first UrsusFlasher use on Nokia stock:

```text
hold Reset >= 30 seconds with router powered on
release
wait for stock Web UI to boot fully
then run UrsusFlasher
```

Hardware observation: a shorter hold may not fully reset Nokia stock configuration.

### TRANSITION2 regression A — overly strict FIT validator

`stock_fit_wrapper.py` was introduced by:

```text
db18eb3b99005d3a8916687c5da49cc43d578f6b
transition: add stock FIT wrapper contract
```

The structural validator incorrectly hard-coded:

```text
/images/kernel@1/compression == lzma
```

A real factory-reset XG-040G-MD reported:

```text
/images/kernel@1/compression == none
```

This was a firmware fingerprint mistaken for a safety invariant.

Correct policy:

```text
validate FIP/HDR2/FIT structure
validate kernel type/arch/os and board-required load/entry/spans
accept supported stock compression variants
inject TRANSITION kernel as compression=none
recalculate hash
preserve everything outside explicitly allowed kernel/compression/hash fields byte-for-byte
```

Corrective commit:

```text
9398c87fce8a32d4c9591bf92e96f96d7d32da2c
transition2: accept stock FIT none compression
```

### TRANSITION2 regression B — mandatory standalone TFTP transport

Next hardware run progressed to candidate creation and operator confirmation, then failed during transfer:

```text
SLAVE candidate prepared
operator confirmed y
send_file_to_router_tftp(... port=1069, block_size=4096)
-> stock TFTP client returned ERROR
```

No flash write had started in this failed run.

Root cause is architectural: standalone `stock_ab_transition.py` made TFTP the mandatory transfer instead of using the existing proven UrsusFlasher transport model.

Production fix:

```text
EXPERT item 4
-> select/preflight proven transport before destructive boundary
-> use that transport consistently for the transaction
```

TFTP remains one available mechanism, not a mandatory `TFTP or die` gate.

### Gate policy tightened to real invariants only

Hard-stops remain for:

```text
wrong model/profile
NAND geometry/write span mismatch
candidate structural invalidity
protected region violation
payload does not fit
full backup invalid/missing
upload SHA mismatch
post-write readback mismatch
selector readback mismatch
```

Not generic hard-stops:

```text
none vs lzma stock compression
active/curimg/startok/count differing from one previous sample
HW_PENDING / partial advisory probe
one transport unavailable while another proven transport exists before write
```

One meaningful `y/N` remains the normal destructive confirmation. No backend/writer switch after write begins.

---

## 2026-09-15 — Vanilla product contract

### Vanilla final storage is UBI only

For MD/MF Vanilla Transition:

```text
VANILLA -> canonical OpenWrt UBI layout
```

Removed from Vanilla design:

```text
factory/non-UBI final option
factory-vs-UBI selection
fallback to factory layout
Nokia A/B as final OpenWrt layout
persistent UrsusBoot in final boot chain
```

Factory/non-UBI remains supported only by the separate persistent UrsusBoot product.

### Shared OpenWrt firmware bundle

OpenWrt artifacts are stored once where genuinely compatible across MD/MF:

```text
factory/non-UBI image
initramfs recovery image
sysupgrade/UBI image
manifest/provenance/SHA256
```

Only actual board-specific transition/bootchain artifacts are split:

```text
TRANSITION wrapper
BL2/preloader
FIP/BL31/U-Boot
A/B/HDR/FIT policy
layout/write spans
NAND enablement
```

### Persistent UrsusBoot payloads retained

Do not remove:

```text
OpenWrt factory/non-UBI payloads for persistent UrsusBoot workflows
OpenWrt initramfs images for UrsusBoot recovery/rescue
```

---

## 2026-09-15 — MD no-UART hardware evidence

Real Nokia XG-040G-MD / Fudan FM25G02B proved:

```text
stock tcboot can select SLOT2
stock-compatible FIT/hash verification passes
ARM64 Linux Image shim starts UrsusBoot TRANSITION
Fudan NAND is detected
stock retry counter decreases on failed SLOT2 boots
tcboot eventually rolls back automatically to untouched SLOT1
```

TRANSITION1 runtime was rejected because it continued into stock boot policy and caused a hybrid MASTER-kernel/SLAVE-rootfs failure.

TRANSITION2 requirement:

```text
shim -> TRANSITION runtime
-> remain in WebFailsafe/transition execution
-> do not default to stock MASTER boot
```

---

## 2026-09-15 — MF requirement

XG-040G-MF / AN7583 is a required production-equivalent Vanilla target.

Required architecture:

```text
common transition runtime
+ xg040-md board policy
+ xg040-mf board policy
```

MF gets the same:

```text
full all-MTD backup contract
stock secondary-slot transition
selector policy
RAM TRANSITION
vanilla bootchain
canonical UBI final layout
shared OpenWrt firmware bundle where compatible
full readback verification
```

Do not copy MD MTD indices, offsets or HDR assumptions into MF. Transition staging must become board-profile driven.

---

## 2026-09-15 — XG140 independent track

XG140 remains on the device-derived native-hybrid persistent path.

Known physical boot area:

```text
mtd0 size          0x80000
native FIP start   0x800
vendor env         0x7c000..0x7ffff
```

Rejected:

```text
tcboot -> loadx raw u-boot.bin -> go 0x81e00000
```

Correct emergency path:

```text
stock tcboot
-> XMODEM Linux FIT initramfs @0x85000000
-> rescue Linux in RAM
-> native-hybrid FIP write
-> full 0x80000 readback
-> reboot
```

---

## Current next engineering sequence

```text
1. Reclaim EXPERT item 4 for Stock Nokia -> Vanilla OpenWrt (TRANSITION).
2. Remove production dependence on standalone START_MD_TRANSITION.
3. Reuse common DeviceState/board_profiles/stock Web/Telnet/root plumbing.
4. Reuse proven full backup of every live /proc/mtd partition.
5. Reuse proven transport selection; remove mandatory standalone TFTP path.
6. Keep structural FIT validation, remove firmware-fingerprint gates.
7. HW-accept MD stock -> TRANSITION2 Web/API through EXPERT.
8. Implement and HW-test MD TRANSITION -> vanilla BL2/FIP -> UBI -> OpenWrt.
9. Refactor transition staging to common board-profile-driven MD/MF backend.
10. Build/HW-accept MF secondary-slot TRANSITION.
11. HW-test MF final UBI-only migration.
12. Keep persistent UrsusBoot + factory/non-UBI + initramfs recovery payloads.
13. Continue XG140 track independently.
```

## Repository rules

- Do not change `main` without explicit instruction.
- Do not merge/tag/release without explicit instruction.
- Do not commit device backups, plaintext credentials, serial/GPON secrets.
- First stock Nokia use: Reset **30+ seconds**, then wait for stock Web.
- Stock -> transition: full verified backup of **all** live `/proc/mtd`.
- Vanilla Transition lives in **EXPERT item 4**, not ONE-CLICK.
- Minimum ceremony: one meaningful `y/N` after automatic preflight.
- No automatic backend/writer switch after destructive write begins.
- Vanilla MD/MF final storage = canonical **UBI only**.
- Persistent UrsusBoot retains factory/non-UBI and initramfs recovery support.

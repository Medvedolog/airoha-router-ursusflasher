# UrsusBoot / UrsusFlasher — active development handoff

**Updated:** 2026-09-15  
**Repository:** `Medvedolog/airoha-router-ursusflasher`  
**Active branch:** `feature/ursusboot-modular-airoha`  
**Do not touch:** `main`, tags, releases unless explicitly requested  
**Primary active targets:** Nokia XG-040G-MD / XG-040G-MF  
**Independent recovery target:** Bell/Nokia XG-140G-MD

This handoff supersedes the old XG140-only context. Current priority is the multimodel UrsusBoot/UrsusFlasher architecture and safe no-UART Vanilla transition for MD/MF.

---

## 1. Core architecture

```text
common core
  -> SoC module
  -> board/DTS module
  -> storage/env policy
  -> boot/layout board policy
  -> runtime role
```

Profiles:

```text
xg040-md  -> AN7581/AN7581DT family
xg040-mf  -> AN7583
xg140-md  -> AN7581DT family
```

Runtime roles:

```text
persistent    normal UrsusBoot supervisor
ram-recovery  RAM-only WebFailsafe/recovery
transition    one-shot RAM migration environment, persistence target NONE
```

UrsusFlasher owns policy/orchestration. UrsusBoot owns compact execution/recovery functions.

---

## 2. Product separation

### Persistent UrsusBoot

Keep supported:

```text
persistent UrsusBoot
OpenWrt factory/non-UBI payload path
OpenWrt initramfs recovery/rescue payloads
OpenWrt sysupgrade/UBI payloads where supported
```

### Vanilla Transition

Separate one-shot product:

```text
stock Nokia
-> temporary TRANSITION UrsusBoot in RAM
-> canonical OpenWrt BL2/FIP/U-Boot
-> canonical OpenWrt UBI
-> OpenWrt
```

Vanilla final layout is **UBI only**. No factory/non-UBI final option, no factory-vs-UBI menu, no persistent UrsusBoot in final boot chain.

### Shared OpenWrt firmware bundle

Use one shared firmware artifact wherever the exact artifact is compatible with MD and MF:

```text
factory/non-UBI image
initramfs image
sysupgrade/UBI image
manifest/provenance/SHA256
```

Board-specific only where actually different:

```text
TRANSITION wrapper
BL2/preloader
FIP/BL31/U-Boot
stock A/B/HDR/FIT policy
write spans/layout policy
NAND-specific enablement
```

---

## 3. Mandatory stock first-run preparation

Before the first UrsusFlasher run on Nokia stock:

```text
router powered on
-> hold Reset >= 30 seconds
-> release
-> wait until stock Web UI is fully available
-> start UrsusFlasher
```

Hardware observation: shorter holds may not perform a complete Nokia factory reset.

---

## 4. Full backup contract

Before any stock -> TRANSITION/destructive migration, use the proven UrsusFlasher full backup backend.

Backup means **all live `/proc/mtd` partitions**, not only A/B service partitions.

Required:

```text
/proc/mtd snapshot
mtd0..mtdN complete dumps
partition names
exact sizes
erase sizes
SHA256 each
DEVICE_IDENTITY / MAC / serial / RI / factory metadata where applicable
BACKUP_MANIFEST.json
```

Every live partition must exist on the PC with exact-size and SHA verification before destructive staging.

Do not commit backups, credentials, serial/GPON identity data or device secrets.

---

## 5. EXPERT is the production UI for Vanilla Transition

Do **not** evolve `START_MD_TRANSITION.cmd/.sh` into a second user-facing flasher.

Production operator flow:

```text
START_EXPERT.cmd / START_EXPERT.sh
-> UrsusFlasher EXPERT
-> item 4: Stock Nokia -> Vanilla OpenWrt (TRANSITION)
```

Why item 4: current `expert.py` no longer displays item 4 and maps a typed `4` to item 2 because bootloader install/update were merged. Reclaim item 4 for Vanilla Transition.

Item 4 must reuse existing UrsusFlasher infrastructure:

```text
DeviceState
board_profiles
stock Web auth
Telnet credentials/enablement
root/su acquisition
full_backup_readonly/proven backup backend
proven transfer backends
common logging
common y/N
common readback/verification
```

Standalone transition launcher becomes developer/HWTEST-only or is removed from public package after EXPERT integration.

---

## 6. Gate policy

Hard stops only for real destructive invariants:

```text
wrong model/profile
NAND geometry / exact span mismatch
candidate structurally invalid
protected boundary violation
payload does not fit
full backup missing/invalid
upload SHA mismatch
post-write readback mismatch
selector readback mismatch
```

Do not gate on firmware fingerprints or advisory state alone:

```text
compression none vs lzma
active/curimg/startok/count differs from previous sample
HW_PENDING
partial passive probe
one transport unavailable while another proven transport is still available before write
```

One meaningful `y/N` after automatic preflight. Once destructive write starts, do not auto-switch writer/backend.

---

## 7. MD hardware facts proven so far

Real XG-040G-MD with Fudan FM25G02B proved:

```text
stock tcboot selects SLOT2 when requested
stock-compatible FIT/hash passes
the ARM64 Linux Image shim starts UrsusBoot TRANSITION
Fudan NAND is detected
stock failure counter decreases on failed SLOT2 boots
tcboot eventually rolls back automatically to untouched SLOT1
```

TRANSITION1 itself was rejected as final runtime because it continued into stock boot policy and produced a hybrid MASTER-kernel/SLAVE-rootfs failure.

Required TRANSITION2 behavior:

```text
shim -> UrsusBoot TRANSITION
-> enter/stay in WebFailsafe/transition execution
-> do not default to stock MASTER boot
```

---

## 8. 2026-09-15 regression findings

### Regression A — overly strict FIT validator

`stock_fit_wrapper.py` was added in commit:

```text
db18eb3b99005d3a8916687c5da49cc43d578f6b
transition: add stock FIT wrapper contract
```

It hard-coded:

```text
/images/kernel@1/compression == lzma
```

Real factory-reset MD stock returned:

```text
/images/kernel@1/compression == none
```

The strict fingerprint was not a valid safety invariant. Fixed direction: retain structural FIP/HDR2/FIT validation, but accept supported stock compression variants and always inject TRANSITION Linux Image as `compression=none`, recomputing hash while preserving all non-allowed bytes.

Latest corrective commit at time of this handoff:

```text
9398c87fce8a32d4c9591bf92e96f96d7d32da2c
transition2: accept stock FIT none compression
```

### Regression B — standalone mandatory TFTP upload

Next hardware attempt reached:

```text
SLAVE candidate prepared
operator y/N accepted
send_file_to_router_tftp(... port=1069, block_size=4096)
-> TFTP client returned ERROR
```

No flash write had started. Candidate/selector were not written in that failed attempt.

Root architectural problem: standalone `stock_ab_transition.py` duplicated transfer orchestration and made TFTP mandatory instead of using the existing UrsusFlasher proven transport model.

Production fix is not another TFTP-specific hotfix. Integrate transition into EXPERT item 4 and reuse common proven transport selection/preflight.

---

## 9. MD production transition flow

```text
EXPERT item 4
-> detect/confirm xg040-md
-> stock Web/Telnet/root through existing backend
-> mandatory full backup all live /proc/mtd
-> build stock-compatible secondary candidate
-> transfer via preflighted proven transport
-> verify uploaded candidate SHA
-> one y/N at latest safe point
-> write nsb_slave
-> full readback
-> request SLAVE using board selector policy
   MD proven rule: change active only
-> selector readback
-> reboot
-> tcboot -> SLOT2
-> shim -> TRANSITION2 RAM
-> reconnect through common network/Web API
```

Only after TRANSITION2 Web/API acceptance proceed to final Vanilla migration.

---

## 10. MF requirement

MF is not optional follow-up work.

Same product flow:

```text
EXPERT item 4
-> xg040-mf board policy
-> full all-MTD backup
-> MF stock secondary-slot candidate
-> MF selector policy
-> TRANSITION RAM
-> vanilla OpenWrt bootchain
-> canonical UBI
```

Do not copy MD MTD indices/offsets/HDR assumptions. Make transition staging board-profile driven.

Reuse existing AN7583 RAM/persistent groundwork and MF backup/identity helpers.

---

## 11. Final Vanilla transaction — MD/MF

All payloads are bundled ahead of time. No live Internet download during destructive migration.

```text
TRANSITION fully in RAM
-> receive shared OpenWrt firmware bundle + board-specific bootchain payloads
-> verify manifest/SHA/profile/NAND geometry/spans
-> verify complete stock backup
-> one y/N
---------------- destructive boundary ----------------
-> write canonical OpenWrt BL2/preloader
-> full readback
-> write canonical OpenWrt FIP/BL31/U-Boot
-> full readback
-> canonical UBI repartition/format
-> deploy compatible OpenWrt UBI/sysupgrade payload
-> verify UBI attach/volumes/FIT/rootfs
-> sync
-> reboot
```

Final target:

```text
BootROM
-> OpenWrt BL2/preloader
-> OpenWrt FIP/BL31
-> OpenWrt U-Boot
-> canonical OpenWrt UBI
-> OpenWrt
```

UrsusBoot/tcboot/Nokia A/B are absent from the active final boot target.

---

## 12. Nokia selector contract

Known fields:

```text
active   requested slot
curimg   actually booted slot
startok  userspace success state
count    retry/state counter
```

For MD proven request pattern: change only `active`. Do not manually mirror `flagback`; tcboot owns reconciliation.

The values of `curimg/startok/count` are diagnostics, not generic stop-gates unless a specific board-policy invariant proves otherwise.

---

## 13. XG140 independent path

Known lab target:

```text
Bell/Nokia XG-140G-MD
XG140GMC2P5G
AN7581DT
512 MiB
SkyHigh S35ML02G3 256 MiB NAND
```

Persistent boot area:

```text
mtd0 size          0x80000
native FIP start   0x800
vendor env         0x7c000..0x7ffff
```

Persistent candidate is device-derived native-hybrid: preserve live prefix/native trusted FIP entries/vendor env; replace only NT_FW/BL33.

Rejected UART method:

```text
tcboot -> loadx raw u-boot.bin -> go 0x81e00000
```

Correct emergency path:

```text
stock tcboot
-> XMODEM Linux FIT initramfs @0x85000000
-> bootm
-> rescue Linux in RAM
-> native-hybrid FIP write
-> full 0x80000 readback
-> reboot
```

---

## 14. Immediate next work

```text
1. Integrate Vanilla Transition into EXPERT item 4.
2. Remove production dependency on standalone START_MD_TRANSITION.
3. Reuse common stock auth/root/full-backup/logging/transport plumbing.
4. Make transition staging board-profile driven.
5. Add structural FIT tests for both none and lzma stock compression variants.
6. HW-test MD stock -> TRANSITION2 without UART through EXPERT.
7. Implement/accept MD TRANSITION -> vanilla BL2/FIP -> UBI -> OpenWrt.
8. Add MF secondary-slot transition policy and HW acceptance.
9. HW-test MF final UBI-only Vanilla migration.
10. Preserve persistent UrsusBoot factory/non-UBI and initramfs recovery paths.
11. Continue XG140 work independently.
```

---

## 15. Repository rules

- Do not change `main` without explicit instruction.
- Do not merge/tag/release without explicit instruction.
- Do not commit backups, credentials, serial/GPON data or unique device identity.
- Before first UrsusFlasher run on Nokia stock: Reset **30+ seconds**, then wait for full stock Web boot.
- Stock -> transition requires full verified backup of **all** live `/proc/mtd` partitions.
- Vanilla Transition belongs in **EXPERT item 4**, not ONE-CLICK.
- Avoid unnecessary gates; keep real structure/geometry/boundary/readback checks.
- One meaningful `y/N` per normal destructive transaction.
- No automatic backend/writer switch after write starts.
- Vanilla MD/MF final storage = canonical **UBI only**.
- Persistent UrsusBoot keeps factory/non-UBI support and initramfs recovery payloads.
- OpenWrt firmware artifacts are shared across MD/MF when genuinely compatible.

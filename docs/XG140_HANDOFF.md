# UrsusBoot / UrsusFlasher — active development handoff

**Updated:** 2026-09-15  
**Repository:** `Medvedolog/airoha-router-ursusflasher`  
**Active branch:** `feature/ursusboot-modular-airoha`  
**Do not touch:** `main`, tags, releases unless explicitly requested  
**Primary lab target:** Bell/Nokia XG-140G-MD  
**Secondary active targets:** Nokia XG-040G-MD / XG-040G-MF

This handoff supersedes the old XG140-only RAM/raw-U-Boot handoff. The project is a multimodel Airoha UrsusBoot/UrsusFlasher stack.

---

## 1. Architectural decision

UrsusBoot is one modular codebase:

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
xg040-md  -> AN7581
xg040-mf  -> AN7583
xg140-md  -> AN7581DT / AN7581 family
```

Runtime roles:

```text
persistent    bootcmd=ursusdispatch
ram-recovery  bootcmd=ursusweb;true
transition    one-shot RAM migration environment, persistence target NONE
```

Common WebFailsafe, network stack, dispatcher, StockBridge and writer code stay common. Board-specific physical addresses, HDR/FIT rules, SerDes policy and env ownership belong in board policy.

---

## 2. Operator/UI contract

Engineering EXPERT must not hide capabilities because network probing is incomplete.

Keep only hard machine invariants immediately around destructive writes:

```text
target geometry
candidate structure
protected-region boundaries
writer-specific identity/lineage
full post-write readback
```

No automatic fallback to a second writer after a write starts. Normal destructive flow uses one meaningful `y/N` after automatic preflight.

### Mandatory stock Nokia first-run preparation

Before the **first** UrsusFlasher run on a router still running Nokia stock firmware, perform a hardware factory reset:

```text
router powered on
-> hold Reset for at least 30 seconds
-> release
-> wait for stock Nokia Web UI to finish booting
-> only then start UrsusFlasher
```

Hardware observation on 2026-09-15: shorter reset holds may not perform a complete Nokia factory reset. Treat **30+ seconds** as the operator requirement for the initial stock baseline.

This is a preparation step, not an extra confirmation gate inside UrsusFlasher.

---

## 3. Full stock backup contract

For every stock -> transition/destructive migration, UrsusFlasher must use the classic/proven full backup behavior.

**Backup means ALL partitions from the live `/proc/mtd`, not only the partitions touched by the operation.**

Required output:

```text
/proc/mtd snapshot
mtd0..mtdN complete binary dumps
partition names
exact sizes
erase sizes
SHA256 for every dump
DEVICE_IDENTITY / MAC / serial / RI / factory metadata where applicable
BACKUP_MANIFEST.json
```

Every current `/proc/mtd` entry must exist on the PC with matching exact size and SHA256 before destructive staging may begin.

MD and MF transition must reuse the common proven UrsusFlasher backup backend. The temporary four-partition backup implementation in `stock_ab_transition.py` is not the final contract and must be replaced/refactored.

Do not commit backups, plaintext credentials, serial/GPON secrets or unique device identity data.

---

## 4. Product separation: Persistent vs Vanilla

Do not merge the two products conceptually.

### Persistent UrsusBoot product

Persistent UrsusBoot remains supported and keeps its OpenWrt payloads:

```text
persistent UrsusBoot
+ OpenWrt factory/non-UBI image path
+ OpenWrt initramfs images for recovery/rescue through UrsusBoot
```

Factory payload support must remain in the bundle for this product.

Initramfs images must remain available for recovery through UrsusBoot/WebFailsafe/UART-supported recovery flows.

### Vanilla Transition product

Vanilla is a separate one-shot migration product:

```text
stock Nokia
-> temporary TRANSITION UrsusBoot in RAM
-> canonical OpenWrt boot chain
-> canonical OpenWrt UBI storage
-> Ursus-specific persistent code absent
```

**Vanilla has exactly one final storage mode: UBI.**

Forbidden in Vanilla:

```text
factory/non-UBI final layout
factory-vs-UBI menu
fallback from UBI migration to factory layout
keeping Nokia A/B as final OpenWrt storage layout
persistent UrsusBoot in final boot chain
```

Factory/non-UBI remains only a Persistent UrsusBoot/OpenWrt path.

---

## 5. MD Vanilla Transition — proven bootstrap facts

Target: Nokia XG-040G-MD / AN7581.

Current bootstrap design:

```text
stock MAIN
-> full verified stock backup
-> build stock-compatible SLAVE candidate
-> write/readback nsb_slave
-> change only flag.active -> 1
-> leave flagback untouched
-> readback selector
-> reboot
-> stock tcboot chooses SLAVE
-> stock-compatible Linux Image shim
-> UrsusBoot TRANSITION in RAM
```

Hardware-proven on real XG-040G-MD with Fudan FM25G02B:

```text
tcboot selected SLOT2
stock FIT/hash validation passed
Linux Image shim started U-Boot 2026.07 UrsusBoot TRANSITION
Fudan FM25G02B was recognized
stock tcboot retry counter decreased on failed SLOT2 boots
tcboot eventually returned automatically to untouched stock SLOT1
```

This proves the no-UART A/B bootstrap and stock rollback mechanism.

The old TRANSITION1 runtime then continued into stock boot policy. That path is rejected for the transition role. TRANSITION2 must enter/stay in WebFailsafe/transition execution and never attempt to boot stock MASTER as its default action.

The next MD hardware test is therefore:

```text
stock SLOT1
-> run corrected TRANSITION2 stager without UART
-> complete full MTD backup PASS
-> stage SLOT2/readback PASS
-> reboot
-> tcboot -> SLOT2
-> shim -> TRANSITION2
-> Web/API/network PASS
-> remain in transition environment
```

Only then run the first final Vanilla destructive migration test.

---

## 6. Final Vanilla migration contract — MD and MF

The same high-level transaction applies to MD and MF, with board-specific layout/payload policy:

```text
TRANSITION running entirely from RAM
-> receive pre-packaged board-specific vanilla payload set from UrsusFlasher
-> verify manifest/SHA/profile/NAND geometry
-> verify complete stock backup is present
-> one y/N
---------------- destructive boundary ----------------
-> write canonical OpenWrt BL2/preloader
-> full readback
-> write canonical OpenWrt FIP/BL31/U-Boot
-> full readback
-> canonical OpenWrt UBI repartition/format
-> deploy OpenWrt UBI/sysupgrade payload
-> verify UBI attach/volumes/FIT/rootfs contract
-> sync
-> reboot
```

Final boot target:

```text
BootROM
-> OpenWrt BL2/preloader
-> OpenWrt FIP/BL31
-> OpenWrt U-Boot
-> OpenWrt UBI
```

No tcboot, Nokia A/B or UrsusBoot remains in the final boot target.

All payloads must be bundled ahead of time. Do not download boot-critical payloads from the Internet during a destructive migration.

Expected bundle classes:

```text
payloads/md/transition/*
payloads/md/vanilla/{bl2,fip-or-u-boot,sysupgrade,manifest}
payloads/mf/transition/*
payloads/mf/vanilla/{bl2,fip-or-u-boot,sysupgrade,manifest}
```

Provenance must record OpenWrt commit, U-Boot version/commit, ATF/BL2 commit, required NAND patches, board profile, SHA256 and expected write spans/layout.

---

## 7. MF Vanilla Transition requirement

MF is not optional follow-up work. XG-040G-MF / AN7583 needs the same complete user-facing Vanilla Transition product.

Architecture:

```text
common transition runtime
  + xg040-md board policy
  + xg040-mf board policy
```

MF needs:

```text
full stock backup of all /proc/mtd
MF stock secondary-slot wrapper/HDR policy
MF A/B selector policy
TRANSITION runtime in RAM
MF vanilla BL2/preloader
MF vanilla FIP/BL31/U-Boot
MF canonical UBI layout
MF OpenWrt UBI/sysupgrade payload
readback/verification
```

Do not clone MD physical constants. `stock_ab_transition` must become board-profile driven.

MF already has AN7583 RAM/persistent groundwork and backup compatibility helpers; reuse them rather than implementing a parallel reduced backup path.

---

## 8. XG140 hardware facts and persistent path

```text
Model family        Bell/Nokia XG-140G-MD
Board ID            XG140GMC2P5G
SoC                 Airoha AN7581DT
DRAM                512 MiB DDR4
SPI-NAND            SkyHigh S35ML02G3, 256 MiB
Erase/page/OOB      128 KiB / 2048 B / 128 B
```

Physical boot area:

```text
mtd0 size          0x80000
native FIP start   0x800
vendor env         0x7c000..0x7ffff
```

Persistent XG140 image is device-derived native-hybrid:

```text
live BootROM prefix        KEEP
native FIP                 KEEP
all non-NT_FW entries      KEEP byte-for-byte
NT_FW / BL33               REPLACE with modular XG140 UrsusBoot
live vendor env            KEEP byte-for-byte
```

Rejected emergency method:

```text
tcboot -> loadx raw u-boot.bin -> go 0x81e00000
```

Correct XG140 emergency method:

```text
stock tcboot
-> XMODEM Linux FIT initramfs @ 0x85000000
-> iminfo
-> bootm
-> rescue Linux in RAM
-> transfer native-hybrid FIP
-> reconstruct live 512-KiB mtd0
-> write once
-> full 512-KiB readback
-> reboot
-> persistent modular UrsusBoot
```

---

## 9. Nokia A/B selector contract

Known fields:

```text
active   requested slot
curimg   actually booted slot
startok  stock userspace success state
count    stock retry/state counter
```

For the proven MD request pattern, modify only `active`. Do not manually mirror `flagback`; stock tcboot owns reconciliation.

On MD hardware the retry/fallback path is now proven: after unsuccessful SLOT2 attempts, stock tcboot returned automatically to untouched SLOT1.

Keep selector manipulation separate from persistent boot-area installation.

---

## 10. Vanilla definition

Vanilla OpenWrt may contain necessary upstream/board hardware-support patches, including MD Fudan/FMSH SPI-NAND support, but no Ursus-specific persistent functionality.

Required final state:

```text
UrsusBoot persistent code  ABSENT
TRANSITION staging         not part of boot target
final U-Boot               OpenWrt-compatible provenance
final storage              canonical UBI only
OpenWrt userspace          boots normally
identity/MAC/RI/BOSA       verified/preserved as required
```

---

## 11. Immediate development priorities

1. Finish corrected MD TRANSITION2 runtime and package.
2. Replace reduced transition backup with proven **full all-MTD backup**.
3. HW-accept MD no-UART TRANSITION2 Web/API stop point.
4. Implement MD `TRANSITION -> vanilla BL2/FIP -> UBI -> OpenWrt` backend; UBI only.
5. Refactor transition staging into common board-profile-driven code.
6. Build MF stock-secondary TRANSITION from common runtime + MF policy.
7. Package MF vanilla BL2/FIP/U-Boot/UBI OpenWrt payload set.
8. HW-accept MF transition bootstrap.
9. HW-test MF final UBI-only vanilla migration.
10. Keep persistent UrsusBoot + OpenWrt factory and initramfs recovery payload paths intact.
11. Continue XG140 persistent emergency/hardware acceptance independently.

---

## 12. Repository and safety rules

- Do not change `main` without explicit instruction.
- Do not merge/tag/release without explicit instruction.
- Do not commit plaintext stock credentials, unique serial/GPON data or full device backups.
- Before first UrsusFlasher run on Nokia stock, factory reset with **Reset held 30+ seconds** and wait for normal stock Web boot.
- Stock -> transition always captures a full verified backup of **all** current `/proc/mtd` partitions.
- Avoid unnecessary UI/policy gates in EXPERT/HWTEST.
- Normal destructive flow: one meaningful `y/N` after automatic preflight summary.
- Structural geometry/boundary/readback checks remain automatic.
- Never retry a different writer automatically after destructive write begins.
- Vanilla MD/MF final target is **UBI only**.
- Persistent UrsusBoot product keeps OpenWrt factory/non-UBI support and initramfs recovery images.

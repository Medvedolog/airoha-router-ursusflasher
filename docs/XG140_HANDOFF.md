# UrsusBoot / UrsusFlasher — active development handoff

**Updated:** 2026-09-15  
**Repository:** `Medvedolog/airoha-router-ursusflasher`  
**Active branch:** `feature/ursusboot-modular-airoha`  
**Do not touch:** `main`, tags, releases unless explicitly requested  
**Primary lab target:** Bell/Nokia XG-140G-MD  
**Secondary active targets:** Nokia XG-040G-MD / XG-040G-MF

This file supersedes the old XG140-only RAM/raw-U-Boot handoff. The project is now a multimodel Airoha UrsusBoot/UrsusFlasher stack.

---

## 1. Architectural decision

UrsusBoot is one modular codebase, not one fork per router.

```text
common core
  -> SoC module
  -> board/DTS module
  -> storage/env policy
  -> boot/layout board policy
  -> runtime role
```

Current profiles:

```text
xg040-md  -> AN7581
xg040-mf  -> AN7583
xg140-md  -> AN7581DT / AN7581 family, MD-derived common core
```

Runtime roles:

```text
persistent    bootcmd=ursusdispatch
ram-recovery  bootcmd=ursusweb;true
transition    one-shot RAM migration environment, persistence target NONE
```

Common WebFailsafe, network stack, dispatcher, StockBridge and writer code must stay common. Board-specific physical addresses, HDR/FIT rules, SerDes policy and env ownership belong in board policy.

---

## 2. Operator/UI contract

Engineering EXPERT must not hide capabilities because network probing is incomplete.

Current policy:

- all top-level EXPERT actions selectable;
- MD/MF/XG140 can always be selected manually;
- Telnet and UART can always be selected manually;
- manual selection wins over stale/absent auto-detection;
- mismatch is advisory warning, not STOP;
- concrete backend determines whether requested transport really works.

Keep only hard machine invariants immediately around destructive writes:

```text
target geometry
candidate structure
protected-region boundaries
writer-specific identity/lineage
full post-write readback
```

No automatic fallback to a second writer after a write starts.

---

## 3. XG140 hardware facts

```text
Model family        Bell/Nokia XG-140G-MD
Board ID            XG140GMC2P5G
SoC                 Airoha AN7581DT
DRAM                512 MiB DDR4
SPI-NAND            SkyHigh S35ML02G3, 256 MiB
Erase/page/OOB      128 KiB / 2048 B / 128 B
```

Stock layout:

```text
bootloader   0x00000000..0x00080000
romfile      0x00080000..0x000c0000
nsb_master   0x000c0000..0x02940000
nsb_slave    0x02940000..0x051c0000
bosa         0x051c0000..0x05200000
ri           0x05200000..0x05240000
flag         0x05240000..0x05280000
flagback     0x05280000..0x052c0000
config       0x052c0000..0x05cc0000
data         0x05cc0000..0x0dda0000
oopsfs       0x0dda0000..0x0e1a0000
log          0x0e1a0000..0x0eba0000
```

Physical boot area:

```text
mtd0 size          0x80000
native FIP start   0x800
vendor env         0x7c000..0x7ffff
```

A restore-grade backup of the lab unit already exists locally. Do not commit it or device credentials.

Current lab condition: stock MAIN/slot1 payload is damaged, but stock tcboot and UART are alive. This is an emergency/recovery test state, not a pristine stock unit.

---

## 4. XG140 raw-U-Boot experiment is closed

Do **not** return to:

```text
tcboot
 -> loadx raw u-boot.bin @ 0x81e00000
 -> go 0x81e00000
```

Real hardware result:

```text
Bad FIT kernel image format
Application terminated, rc = 0x1
ECNT>
```

XMODEM transfer itself was clean; the failure is the nested raw U-Boot handoff/runtime context. More HOTFIXes around raw `go` are not useful.

---

## 5. Correct XG140 UART emergency path

Use stock tcboot only as a Linux FIT loader:

```text
stock tcboot
 -> XMODEM XG140 rescue initramfs FIT @ 0x85000000
 -> iminfo
 -> bootm 0x85000000
 -> rescue Linux in RAM
 -> transfer native-hybrid FIP
 -> reconstruct live 512-KiB mtd0 candidate
 -> preserve live prefix
 -> preserve live vendor env
 -> write boot area once
 -> full 512-KiB readback/compare
 -> reboot
 -> persistent modular UrsusBoot
```

`START_EXPERT.cmd -> 2 -> XG140 -> UART` is intended to route here.

The rescue build is packaged in the current multimodel HWTEST kit. It no longer depends on the rejected raw-U-Boot handoff.

---

## 6. XG140 persistent target

Persistent UrsusBoot is inserted as NT_FW/BL33 into this unit's own native FIP.

```text
live BootROM prefix        KEEP
native FIP                 KEEP
all non-NT_FW entries      KEEP byte-for-byte
NT_FW / BL33               REPLACE with modular XG140 UrsusBoot
live vendor env            KEEP byte-for-byte
```

Normal target chain:

```text
BootROM
 -> native XG140 FIP / trusted firmware
 -> modular UrsusBoot
 -> ursusdispatch
 -> ursusstockboot / OpenWrt policy
 -> Nokia stock Linux or OpenWrt
```

Do not restore stock tcboot as the desired final first-stage BL33 merely to boot Nokia Linux. MD already proves that UrsusBoot can act as persistent supervisor and boot stock Nokia Linux; XG140 should use the same common StockBridge class with XG140 board policy.

XG140-specific policy intentionally disables unproven MD assumptions such as MD UBI autodetect, MD factory FIT probes and MD SerDes overrides.

---

## 7. Current modular baseline / CI

Key modular baseline before documentation refresh:

```text
0a671eb35453593665d13ebcdd3a39f7da1c6b10  modular profile/runtime baseline
9efd850b902f2859dc55a986c9f9a3fa4a1474fa  keep UrsusBoot transports selectable
6f489a33eddb026b1f2970eff46293789a7df95e  expose EXPERT actions in HWTEST
7cb9c0cd0a7a19e632881e8fa44c9a30b6e743f5  package XG140 UART rescue in multimodel kit
5993429874f7ec2287931a4a5bcba199de826fe2  feed-independent rescue/package baseline
```

Latest verified package workflow before this documentation update:

```text
run          34900134319
head         5993429874f7ec2287931a4a5bcba199de826fe2
conclusion   SUCCESS
artifact     UrsusFlasher-Airoha-Multimodel-HWTEST-5993429874f7ec2287931a4a5bcba199de826fe2
artifact id  10371938945
size         103842149 bytes
digest       sha256:8714a98ede51fb9d3615cff1ebbe0fec68cdced86f9d98f35152e8edaecfab4e
```

Workflow passed:

```text
host-side multimodel module validation
XG140 persistent modular BL33 build
XG140 payload staging
OpenWrt XG140 rescue initramfs preparation/build
rescue payload staging
multimodel operator-kit packaging
packaged runtime/import/SHA verification
artifact upload
```

CI success is not persistent hardware acceptance.

---

## 8. Next XG140 hardware test

Use the multimodel EXPERT kit, not the older `12d6b05a` kit with UART disabled.

For the current UART/tcboot lab unit:

```text
START_EXPERT.cmd
 -> 2 Install/update UrsusBoot
 -> 4 Bell/Nokia XG-140G-MD
 -> 2 UART
```

Expected high-level sequence:

```text
capture tcboot
 -> load rescue FIT
 -> boot rescue Linux
 -> obtain/build device-derived native hybrid
 -> write/readback mtd0
 -> reboot
 -> BootROM/native FIP/UrsusBoot
```

First hardware acceptance ends only after:

```text
full mtd0 readback PASS
cold boot UrsusBoot PASS
Web/API/network PASS
ursusdispatch -> stock/OpenWrt boot path observed
```

Do not call XG140 production-ready before this.

---

## 9. XG-040G-MD Vanilla TRANSITION status

Goal: use stock secondary/SLAVE slot as a temporary UrsusBoot TRANSITION bootstrap for no-UART Vanilla OpenWrt migration.

Implemented pieces:

```text
ursusboot/configs/ursusboot-transition-handoff.cfg
ursusboot/scripts/build_md_transition1.sh
ursusboot/patches/190-md-transition1-handoff.patch
ursusflasher/src/stock_ab_transition.py
ursusflasher/src/stock_fit_wrapper.py
START_MD_TRANSITION.cmd / .sh
```

MD transition image uses a stock-compatible ARM64 Linux Image handoff shim:

```text
stock tcboot loads Linux-style image
 -> shim executes at stock kernel load address
 -> copies TRANSITION U-Boot to 0x81e00000
 -> cache maintenance
 -> branches into UrsusBoot TRANSITION
```

Host transaction currently:

```text
capture flag/flagback/nsb_slave
 -> rebuild SLAVE while preserving stock FIP/HDR/FIT topology
 -> write/readback nsb_slave
 -> change flag.active only: 0 -> 1
 -> leave flagback untouched
 -> readback selector
 -> reboot through stock tcboot
```

Status:

```text
SOURCE/BUILD PATH IMPLEMENTED
HOST A/B TRANSACTION IMPLEMENTED
HW STOCK-TCBOOT -> TRANSITION ACCEPTANCE PENDING
FINAL VANILLA MIGRATION NOT YET ACCEPTED
```

Do not claim MD TRANSITION HW-PASS until the no-input reboot into TRANSITION Web/API has been observed and repeated on real MD hardware.

The old `md-transition1-build.yml` still contains legacy branch coupling and should be moved into the modular profile/runtime-role CI before final use.

---

## 10. XG-040G-MF Vanilla TRANSITION status

MF has significant AN7583 groundwork for RAM and persistent UrsusBoot, but no complete MF equivalent of the MD slot2 TRANSITION pipeline yet.

Missing as a coherent path:

```text
MF transition build/profile
MF stock-compatible slot wrapper/HDR policy
MF board-profile-driven A/B staging backend
MF hardware tcboot -> TRANSITION acceptance
```

Do not clone MD code wholesale. Refactor transition into:

```text
common transition runtime
 + MD board policy
 + MF board policy
```

Then make `stock_ab_transition.py` profile-driven instead of hard-coded MD `mtd8/mtd9/mtd14/mtd15` assumptions.

---

## 11. Nokia A/B selector contract

Known selector fields:

```text
active   requested slot
curimg   actually booted slot
startok  stock userspace success state
count    stock retry/state counter
```

For the proven request pattern, modify only `active`. Do not manually mirror `flagback`; stock tcboot owns reconciliation unless a board-specific test proves otherwise.

Keep selector manipulation separate from persistent boot-area installation.

---

## 12. Vanilla definition

Final Vanilla OpenWrt may use necessary OpenWrt board/hardware-support patches, including MD Fudan/FMSH SPI-NAND support, but must contain no Ursus-specific persistent functionality.

TRANSITION is temporary RAM tooling only.

After successful Vanilla migration:

```text
UrsusBoot persistent code  ABSENT
TRANSITION staging         not part of boot target
final U-Boot               OpenWrt-compatible provenance
OpenWrt userspace          boots normally
identity/MAC/RI/BOSA       verified
```

---

## 13. Immediate development priorities

Priority order after the current XG140 emergency test:

1. Hardware-test XG140 UART FIT/initramfs -> persistent modular UrsusBoot.
2. Prove XG140 cold boot and common StockBridge behavior.
3. Integrate/read-only Nokia A/B selector for XG140 only after persistent boot works.
4. Refactor MD TRANSITION into the common modular `transition` runtime role.
5. Convert `stock_ab_transition.py` to board-profile-driven layout.
6. Build MF TRANSITION from the same common role + MF policy.
7. Hardware accept MD transition bootstrap.
8. Hardware accept MF transition bootstrap.
9. Only then implement/enable destructive final Vanilla migration in ONE-KEY.

---

## 14. Repository and safety rules

- Do not change `main` without explicit instruction.
- Do not merge/tag/release without explicit instruction.
- Do not commit plaintext stock credentials, unique serial/GPON data or full device backups.
- Avoid unnecessary UI/policy gates in EXPERT/HWTEST.
- Normal destructive flow: one meaningful `y/N` after automatic preflight summary.
- Emergency flows may be unattended when explicitly designed that way.
- Structural geometry/boundary/readback checks remain automatic.
- Never retry a different writer automatically after a destructive write has begun.

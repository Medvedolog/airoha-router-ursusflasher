# Development changelog — modular Airoha branch

**Branch:** `feature/ursusboot-modular-airoha`  
**Started as current baseline:** 2026-09-15  
**Scope:** engineering changes not yet promoted to `main` or release.

Published/release history remains in `docs/CHANGELOG_RU.md`. This file tracks the active multimodel development line.

---

## 2026-09-15 — MULTIMODEL1 / MIN-GATES / XG140-RESCUE / TRANSITION-STATUS

### Modular UrsusBoot architecture

- UrsusBoot is now treated as one multimodel Airoha codebase instead of per-router forks.
- Composition contract is `common -> SoC -> board/DTS -> storage/env -> board policy -> runtime role`.
- Active profiles: `xg040-md` / AN7581, `xg040-mf` / AN7583, `xg140-md` / AN7581DT family.
- XG140 is MD-derived at common-core level but owns its own DTS/layout/env/boot policy.
- Common `ursusdispatch`, `ursusstock`, WebFailsafe/network/API remain shared.
- Model identity in WebFailsafe is policy-driven through `URSUS_BOARD_MODEL`; stale hard-coded XG-040G-MD identity is rejected by build checks.

### Runtime roles

- `persistent`: `bootcmd=ursusdispatch`.
- `ram-recovery`: `bootcmd=ursusweb;true`.
- Runtime role is selected before compilation; post-build byte patching of bootcmd is no longer the design.
- `transition` is now explicitly part of the architecture: temporary RAM environment, `ENV_IS_NOWHERE`, persistence target NONE, final target Vanilla/OpenWrt boot chain.

### UrsusFlasher EXPERT: minimum policy gates

- Engineering EXPERT no longer disables operations solely from DeviceState/HW_PENDING/advisory network probe.
- All top-level EXPERT actions remain selectable.
- MD/MF/XG140 can be selected manually even if auto-detection fails.
- Telnet and UART transports remain manually selectable.
- Manual model/transport choice wins over stale or absent probe data; disagreement is warning only.
- Backends now own concrete transport failure handling.
- Hard stops are retained only immediately around destructive operations: real geometry/write span, candidate structural validity, protected boundaries/lineage and mandatory readback.
- No automatic fallback to another writer after destructive write begins.

Relevant commits:

```text
9efd850b902f2859dc55a986c9f9a3fa4a1474fa  expert: keep all UrsusBoot transports selectable
6f489a33eddb026b1f2970eff46293789a7df95e  expert: expose all menu actions in HWTEST
```

### XG140 persistent modular BL33

- XG140 persistent BL33 is built from the common modular core with profile `xg140-md`.
- Final boot-area candidate is device-derived: live prefix and vendor env are preserved, native FIP is retained and only NT_FW/BL33 is replaced.
- Known XG140 physical boot area remains `0x80000`, native FIP starts at `0x800`, protected vendor env is `0x7c000..0x7ffff`.
- XG140 does not inherit unproven MD UBI autodetect, factory FIT probes or SerDes overrides.
- Target normal chain is `BootROM -> native XG140 FIP -> modular UrsusBoot -> ursusdispatch -> StockBridge/OpenWrt`.

### XG140 raw-U-Boot UART path retired

Real hardware proved that:

```text
tcboot -> XMODEM raw u-boot.bin -> go 0x81e00000
```

returns to tcboot with `Application terminated, rc=1`. XMODEM was clean; nested raw U-Boot runtime/handoff is the rejected part.

Do not create additional HOTFIXes around this path.

### XG140 UART FIT/initramfs bridge

Correct emergency path is now:

```text
stock tcboot
 -> XMODEM rescue Linux FIT @ 0x85000000
 -> iminfo
 -> bootm
 -> rescue Linux in RAM
 -> transfer/rebuild native-hybrid FIP
 -> write 512-KiB boot area once
 -> full readback
 -> reboot into persistent modular UrsusBoot
```

`START_EXPERT.cmd -> Install/update UrsusBoot -> XG140 -> UART` routes to this design.

Relevant packaging commits:

```text
7cb9c0cd0a7a19e632881e8fa44c9a30b6e743f5  ci: bundle XG140 UART rescue into multimodel expert kit
5993429874f7ec2287931a4a5bcba199de826fe2  ci: make XG140 rescue initramfs feed-independent
```

### Multimodel CI baseline

GitHub Actions:

```text
run          34900134319
head         5993429874f7ec2287931a4a5bcba199de826fe2
conclusion   SUCCESS
artifact     UrsusFlasher-Airoha-Multimodel-HWTEST-5993429874f7ec2287931a4a5bcba199de826fe2
artifact id  10371938945
size         103842149 bytes
digest       sha256:8714a98ede51fb9d3615cff1ebbe0fec68cdced86f9d98f35152e8edaecfab4e
```

Passed stages include host-side multimodel validation, modular XG140 persistent BL33 build, rescue initramfs build, payload staging, operator-kit packaging and packaged runtime/SHA verification.

This remains build/package proof, not XG140 persistent hardware acceptance.

### Current XG140 hardware status

- Physical lab unit: Bell/Nokia XG-140G-MD / `XG140GMC2P5G` / AN7581DT / 512 MiB / SkyHigh 256-MiB NAND.
- Restore-grade backup exists locally and is not stored in Git.
- Current stock MAIN/slot1 payload is damaged; stock tcboot/UART remain alive.
- Next test is the FIT/initramfs UART bridge followed by device-derived persistent boot-area write/readback and cold boot.
- XG140 remains `HW_PENDING` until `BootROM -> native FIP -> UrsusBoot` and subsequent common StockBridge boot are observed on hardware.

### XG-040G-MD Vanilla TRANSITION

Implemented:

```text
ursusboot/configs/ursusboot-transition-handoff.cfg
ursusboot/scripts/build_md_transition1.sh
ursusboot/patches/190-md-transition1-handoff.patch
ursusflasher/src/stock_ab_transition.py
ursusflasher/src/stock_fit_wrapper.py
START_MD_TRANSITION.cmd / .sh
```

Current MD design:

```text
stock MAIN
 -> build stock-compatible TRANSITION image in nsb_slave
 -> full SLAVE readback
 -> change flag.active only 0 -> 1
 -> flagback untouched
 -> selector readback
 -> reboot via stock tcboot
 -> ARM64 Linux-image handoff shim
 -> UrsusBoot TRANSITION in RAM
```

Status:

```text
SOURCE/BUILD IMPLEMENTED
HOST SLOT/SELECTOR TRANSACTION IMPLEMENTED
HARDWARE TCBOOT -> TRANSITION ACCEPTANCE PENDING
FINAL VANILLA MIGRATION NOT YET ACCEPTED
```

The legacy MD transition workflow still has old branch coupling and should be moved into modular role/profile CI before final operator use.

### XG-040G-MF Vanilla TRANSITION

- MF already has AN7583 RAM/persistent UrsusBoot groundwork.
- A complete MF slot2 TRANSITION build/backend equivalent to MD does not yet exist.
- Do not copy the MD implementation wholesale.
- Next architecture is one common `transition` runtime role with MD and MF board policies.
- `stock_ab_transition.py` should be refactored from MD-specific MTD constants to board-profile-driven layout/HDR/slot policy.

Status:

```text
AN7583 URSUSBOOT GROUNDWORK PRESENT
MF TRANSITION ROLE/WRAPPER NOT YET COMPLETE
MF SLOT2 HW ACCEPTANCE NOT STARTED
```

### Vanilla final-state contract

Vanilla describes the final persistent state, not the temporary installer.

Allowed:

```text
official/OpenWrt build contract
+ required board hardware-enablement patches
+ Fudan/FMSH support where needed
+ zero Ursus-specific persistent code
```

After successful Vanilla migration, TRANSITION staging must not be part of the active boot chain and final U-Boot must not expose UrsusBoot runtime identity/WebFailsafe/API.

### Documentation refresh

- Updated `docs/UrsusBoot_UrsusFlasher_TZ_RU_v5.43_MODULAR_AIROHA.md` with multimodel runtime roles, minimum-gate EXPERT policy, XG140 FIT rescue path and current MD/MF TRANSITION status.
- Replaced stale XG140-only `docs/XG140_HANDOFF.md` with current multimodel active-development handoff.
- This dev changelog becomes the short source for new-session continuity; historical release changelog remains unchanged.

---

## Next engineering sequence

```text
1. HW-test XG140 tcboot -> rescue FIT -> RAM Linux -> persistent modular UrsusBoot.
2. Full mtd0 readback and cold-boot acceptance.
3. Prove XG140 common StockBridge boot.
4. Refactor MD TRANSITION into common modular transition role.
5. Make stock_ab_transition board-profile driven.
6. Produce MF transition role/wrapper from common code.
7. Hardware accept MD slot2 TRANSITION.
8. Hardware accept MF slot2 TRANSITION.
9. Only then enable final destructive Vanilla migration in normal ONE-KEY workflow.
```

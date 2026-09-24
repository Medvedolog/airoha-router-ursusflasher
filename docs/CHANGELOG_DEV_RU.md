# Development changelog — modular Airoha branch

**Branch:** `feature/ursusboot-modular-airoha`  
**Current baseline date:** 2026-09-16  
**Scope:** engineering changes not yet promoted to `main` or release.

Published/release history remains in `docs/CHANGELOG_RU.md`.

---

## 2026-09-24 — 0.2.67 / stock UID0 service bootstrap

- Исправлен install-flow на Nokia STOCK для обеих XG-040: MD и MF теперь явно разрешают штатному root-bootstrap включить FTP через Web UI до обязательного полного backup, если без сервисного UID0 аккаунта root недоступен.
- Порядок эскалации остаётся минимальным: сначала FTP/user_ftp, Samba/samba_anony только если FTP не помог.
- Read-only EXPERT backup сохраняет запрет на provisioning сервисов; повторное Telnet-подключение внутри backup_tftp теперь наследует исходный allow_service_provisioning вместо безусловного True.
- Добавлен regression selftest для MD и MF: install auto-enables FTP, read-only path не меняет service state.
- Host Python compatibility matrix: 3.12 / 3.13 / 3.14.

## 2026-09-16 — TRANSITION2 stabilization / MD hardware evidence

### TRANSITION identity dependency removed

TRANSITION recovery startup is explicitly independent from stock RI / factory network identity. Recovery must remain bootable on clean or damaged NAND; a local/random MAC is acceptable for WebFailsafe startup.

Removed stale embedded identity marker gate:

```text
7524a951f0fafd0c57fd91bc66c1b51e9bd8158e
transition: drop stale embedded identity marker gate
```

Factory/RI/serial/GPON data remain migration-preservation data, not prerequisites for starting TRANSITION.

### NETFIX2: sanitize Airoha datapath before WebFailsafe

Airoha FE/QDMA reset is now performed before lwIP/Web listener creation rather than underneath an already-live Web state.

```text
c22bcc3b0a272e1b566c7ca20cd801b545279f4d
net: sanitize Airoha datapath before TRANSITION WebFailsafe

8b1bbc948cf1146327c96482e94e383706b0d264
ci: assert TRANSITION pre-Web network sanitize
```

Runtime sequence:

```text
URSUS_TRANSITION_WEB_BEGIN
-> URSUS_TRANSITION_NET_SANITIZE_BEGIN
-> DMA stop / FEMEM_SEL=0
-> FE/PDMA/QDMA/XSI reset
-> switch/FE init
-> MAC restore / eth_init
-> URSUS_TRANSITION_NET_SANITIZE_DONE
-> WebFailsafe
```

Functional version remains `TRANSITION2`; `NETDBG1` and `NETFIX2` are engineering labels, not TRANSITION3.

### Confirmed meaning of Web-killing `-22`

Source and hardware traces established the lifecycle failure:

```text
UrsusWeb owns eth0
-> standard U-Boot ping
-> NetLoop()
-> eth_halt()
-> device is no longer ACTIVE
-> UrsusWeb eth_rx()
-> -EINVAL / -22
```

Therefore `-22` must not be described as RX ring/DMA/cache corruption evidence. Standard U-Boot `ping` is not a valid probe while Web owns the shared Ethernet device.

`-11 / EAGAIN` remains normal “no packet ready at this instant” behavior.

### Real MD boot evidence after NETFIX2

Real Nokia XG-040G-MD proved:

```text
PASS stock tcboot selected SLOT2
PASS stock FIT/hash verification
PASS ARM64 Linux Image shim started TRANSITION2
PASS Fudan NAND detection
PASS FEMEM access
PASS QDMA RX ring programming/readback
PASS pre-Web NETFIX2 execution
PASS WebFailsafe reached HTTP_LISTEN_OK port=80
PASS stock rollback path to untouched SLOT1
```

The real selector transition observed stock tcboot moving from requested `active=1` to `curimg=1`, then booting the second image.

### HTTP regression localized above basic Ethernet/TCP

In a manual `ursusnetreset` experiment after TRANSITION boot:

```text
PASS host ICMP ping
PASS TCP handshake to port 80
FAIL GET / -> curl (52) Empty reply from server
FAIL GET /api/status -> Empty reply
FAIL HTTP/1.0 /api/status -> Empty reply
```

This proves that the remaining known failure is not simply “Ethernet cannot pass packets”. Exact HTTP/lwIP callback root cause remains unproven.

Control-build direction: restore the persistent MD TEST61 Web implementation unchanged and keep only the minimal TRANSITION wrapper around it.

```text
5647308769e978b76ca13e84c63d8b6b088ae2dd
test: restore persistent TEST61 web in transition

1701ff32cd50390cbfe0a3cb1eedecae541301ce
ci: pin transition web to persistent TEST61 source

870cd49753c0b3e15508416b025f517a0a231014
ci: drop stale web-only binary markers
```

Hardware HTTP acceptance still requires actual response bytes from `/` and `/api/status`; listener markers and TCP connect alone are insufficient.

### EXPERT item 4: optional new backup, verified backup still mandatory

Repeated engineering staging no longer forces creation of a new full backup if a previously created full stock backup passes validation.

```text
2580ae1133b59bdf4f5dd16448ad202ac120d6b2
transition: optional backup reuse and bounded stock write retries

6edff79093a40644547d3da90088cf0608af374a
expert: enable optional transition backup and write retries
```

Policy:

```text
new full backup -> verify -> continue
OR
existing full stock backup -> verify -> continue
```

This is not a no-backup mode. Destructive staging still requires a verified full stock backup.

Long stock writes use bounded retry (max 3): reconnect, read target SHA first, continue without rewrite if already correct, otherwise retry the same write. No automatic writer/backend switch after destructive write starts.

### Fail-safe selector ordering confirmed by real transport failure

A real TCP/Telnet connection reset occurred while writing `nsb_slave`. Selector write had not yet been reached, so stock remained on SLOT1. This validates the transaction ordering:

```text
write nsb_slave
-> verify readback/SHA
-> only then write flag.active
```

Interrupted `nsb_slave` is treated as unknown until readback.

### Passive probe no longer blocks Vanilla transition

```text
ac4d15b8bf396bbd853b58f0a141375783e7a9f2
fix: do not gate transition on passive network probe
```

Advisory discovery may assist model selection, but backend stock/root/profile/geometry checks remain authoritative.

### `ursusstockslot` recovery selector added

TRANSITION now contains:

```text
ursusstockslot status
ursusstockslot master
ursusstockslot slave
```

The backend reads the full primary flag eraseblock to RAM, modifies only `active`, preserves `curimg/startok/count/reserved`, writes only the primary `flag`, and verifies readback. It does not manually write `flagback`.

Core commits:

```text
4e535688baa53defe2fabe5b5ceb48cea515d967
transition: add stock slot selector command

a1aeeb9ef30c22ef91221f263b8303455ff3f66b
ci: build and assert transition stock slot command

b0374ed2e2562825130875b89b4c251eb4225ba1
fix: repair transition stock slot patch
```

Host EXPERT UART integration:

```text
3dba8620a0c7f9a4b29b7ae0f0343dce28abfd64  expert: add UART stock slot selector
62da13604975b40b52f2271efd3b84d62df514b4  expert: expose UART stock slot switching
40072e5e3ad113b5000f8d8d8e1f8803c3c29121  fix: tolerate ANSI tail after recovery U-Boot prompt
59a67dae8971ab9a987e97eeb2cc3643539c7e9b  fix: install ANSI-tolerant recovery prompt detector
686fb0396bc6ee8a06fcb92fd02b8e26d6a1b2f4  uart stockslot: wake idle U-Boot prompt with Enter
```

Requested Web UI button for return to stock SLOT1 remains future work; UART/EXPERT support does not imply the Web control already exists.

### Operator rollup CI/package fixes

```text
8f81f18c01fbf2b707d3925a16f263f180744aee
ci: decouple operator rollup from fastscan BL2

5aad0e412908cd56ddff97e05c5d8ffe34316625
ci: locate nested baseline rollup root

53330b219072f109a593c1ae26838e6548b35864
ci: unpack baseline operator zip before overlay
```

Earlier missing packaged XG140 runtime helper/import was fixed by:

```text
703a987f2eda1e89cd31891affddb86d1f8b91ac
a01858d4febe38a57ac4799ad0c8e52ed85d13c7
```

Canonical launchers remain `START_ONECLICK.cmd/.sh` and `START_EXPERT.cmd/.sh`.

### CI evidence boundaries

Known successful earlier runs:

```text
35102324176 @ 8b1bbc948cf1146327c96482e94e383706b0d264
35107012785 @ 7cebcd83c8c1263c8e59f0eea820ddf1d8c91e23
```

These prove their exact build/package snapshots only. They are not proof that the current HEAD is green and are never hardware acceptance.

### MF status

XG-040G-MF remains a required target, but the current production transition policy is still MD-only. Do not claim MF production support until the staging backend becomes board-profile driven and passes separate hardware acceptance.

---

## 2026-09-15 — TRANSITION2 / EXPERT architecture baseline

### Vanilla Transition belongs in EXPERT

Production operator flow:

```text
START_EXPERT
-> item 4
-> Stock Nokia -> Vanilla OpenWrt (TRANSITION)
```

Standalone `START_MD_TRANSITION.cmd/.sh` is developer/HWTEST plumbing, not the final production UI.

Item 4 reuses common UrsusFlasher infrastructure:

```text
DeviceState / board profiles
stock Web authentication
Telnet credential discovery/enablement
root/su acquisition
full backup backend
proven transfer backends
transaction logging
common y/N
full readback/verification
```

### FIT wrapper correction

A real factory-reset XG-040G-MD showed `/images/kernel@1/compression = none`, while an early validator incorrectly hard-coded `lzma`.

Correct policy is structural validation, not firmware fingerprinting:

```text
validate FIP/HDR2/FIT structure
validate kernel type/arch/os and required load/entry/span
accept supported stock compression variants
inject TRANSITION payload with compression=none
recalculate hash
preserve bytes outside allowed fields
```

Corrective commit:

```text
9398c87fce8a32d4c9591bf92e96f96d7d32da2c
transition2: accept stock FIT none compression
```

### Mandatory-TFTP design rejected

A hardware attempt reached a valid SLAVE candidate but standalone TFTP transfer failed before flash write. The architectural decision is to use the common preflighted transport model rather than a `TFTP or die` transition path.

Transport may change before the destructive boundary if another proven mechanism is available. After write starts, writer/backend is frozen.

### Vanilla final target

For MD/MF:

```text
VANILLA -> canonical OpenWrt UBI only
```

No factory/non-UBI final option, no Nokia A/B final storage and no persistent UrsusBoot in the active final chain.

Persistent UrsusBoot remains a separate supported product with factory/non-UBI and initramfs recovery payload paths.

### XG140 remains independent

XG140 uses the device-derived native-hybrid persistent path and requires independent BootROM/UART recovery proof before first persistent destructive write.

---

## Current next engineering sequence

```text
1. Build current TRANSITION2 control image using persistent TEST61 Web implementation.
2. Verify exact CI run for the exact current SHA.
3. HW-test MD SLOT2 and external curl without issuing U-Boot ping while Web owns Ethernet.
4. If HTTP works, reintroduce TRANSITION Web metadata incrementally.
5. If HTTP still returns Empty reply, instrument the TEST61-compatible HTTP/lwIP callback path rather than reopening Ethernet without new evidence.
6. HW-verify ursusstockslot status/master plus EXPERT UART wrapper.
7. Add Web return-to-stock-SLOT1 control after backend HW acceptance.
8. After Web/API HW_PASS, implement and HW-test final MD Vanilla BL2/FIP/UBI migration.
9. Refactor staging to board-profile-driven MD/MF policy and HW-accept MF independently.
10. Continue persistent UrsusBoot and XG140 tracks without collapsing their boot policies into MD/MF Vanilla.
```

## Repository rules

- Do not change `main` without explicit instruction.
- Do not merge/tag/release without explicit instruction.
- Do not commit device backups, plaintext credentials, serial/GPON secrets or unique identity.
- One meaningful `y/N` after automatic preflight for a normal destructive transaction.
- A verified full stock backup must exist before destructive stock staging; it may be new or an existing validated backup.
- No automatic backend/writer switch after destructive write begins.
- Write selector only after verified secondary-slot readback.
- TRANSITION startup must not depend on stock RI/factory MAC identity.
- Do not use standard U-Boot `ping` while UrsusWeb owns network.
- Vanilla MD/MF final storage is canonical UBI only.
- MF is not production-ready until separately HW-accepted.
- `CI PASS != HW PASS`.
- Functional version remains `TRANSITION2`.
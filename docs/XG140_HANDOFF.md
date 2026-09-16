# UrsusBoot / UrsusFlasher — active development handoff

**Updated:** 2026-09-16  
**Repository:** `Medvedolog/airoha-router-ursusflasher`  
**Active branch:** `feature/ursusboot-modular-airoha`  
**Pre-doc code baseline:** `7524a951f0fafd0c57fd91bc66c1b51e9bd8158e`  
**Normative addendum:** `docs/UrsusBoot_UrsusFlasher_TZ_RU_v5.44_TRANSITION2_STABILIZATION.md`  
**Do not touch:** `main`, tags, releases unless explicitly requested.

This file is the current cross-model handoff despite the historical filename. Primary active target is Nokia XG-040G-MD TRANSITION2 stabilization. XG-040G-MF remains required but not production-ready. XG-140G-MD remains an independent persistent/native-hybrid track.

---

## 1. Architecture and product split

```text
common core
  -> SoC module
  -> board/DTS module
  -> storage/env policy
  -> boot/layout board policy
  -> boot-time runtime role
```

Boot-time roles are `persistent` and `ram-recovery`. `transition` is a payload/product lifecycle, not a third boot-time registry role.

Profiles:

```text
xg040-md  Nokia XG-040G-MD, AN7581/AN7581DT family
xg040-mf  Nokia XG-040G-MF, AN7583
xg140-md  Bell/Nokia XG-140G-MD, AN7581DT family
```

MD/MF Vanilla target:

```text
stock Nokia
-> temporary TRANSITION in RAM
-> canonical OpenWrt BL2/FIP/U-Boot
-> canonical OpenWrt UBI
-> OpenWrt
```

No persistent UrsusBoot, Nokia A/B or factory/non-UBI final layout in the MD/MF Vanilla target.

XG140 remains intentionally different:

```text
preserved native trusted envelope
-> persistent modular UrsusBoot as BL33
-> canonical OpenWrt UBI
-> OpenWrt
```

---

## 2. Current TRANSITION2 build baseline

Functional version stays:

```text
TRANSITION2
```

Engineering labels:

```text
TRANSITION2-NETDBG1
TRANSITION2-NETFIX2
```

Do not rename this work to TRANSITION3 merely because of diagnostic iterations.

TRANSITION source baseline:

```text
ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST61-source.tar.zst
```

Current build script:

```text
ursusboot/scripts/build_md_transition1.sh
```

Relevant patches:

```text
190  stock-tcboot-compatible transition handoff/dispatcher
200  UART fallback after WebFailsafe transport loss
210  NETDBG + ursusnetreset + NETFIX2 pre-Web sanitize
220  ursusstockslot selector command
```

Stock handoff parameters:

```text
kernel load = 0x80088000
U-Boot TEXT_BASE = 0x81e00000
ARM64 shim copies u-boot.bin to TEXT_BASE and branches
```

---

## 3. Critical identity rule

TRANSITION startup does **not** import board/network identity from stock RI and must not require it.

Reason: recovery may run with clean or damaged NAND. TRANSITION must still come up as a RAM recovery environment.

Therefore:

```text
stock RI import        NOT prerequisite
factory MAC import     NOT prerequisite
serial/GPON identity   NOT prerequisite for WebFailsafe startup
random/local MAC       acceptable for recovery network
```

Identity/factory data remains important for final migration preservation/restore, but not for booting TRANSITION.

Commit removing the stale embedded identity marker gate:

```text
7524a951f0fafd0c57fd91bc66c1b51e9bd8158e
transition: drop stale embedded identity marker gate
```

---

## 4. MD stock SLOT2 staging and fail-safe ordering

Known MD geometry/policy:

```text
flag        offset 0x05240000 size 0x00040000
flagback    offset 0x05280000
nsb_master  offset 0x000c0000
nsb_slave   offset 0x02940000
slot size   0x02880000
```

`flag` offset is NAND address space, not mapped RAM. Do not use direct `md.l 0x05240000` as selector read. Read the NAND eraseblock to RAM first.

Proven selector request rule on MD:

```text
change only active
active=0 -> MASTER/SLOT1
active=1 -> SLAVE/SLOT2
```

Do not manually mirror `flagback`. Preserve `curimg`, `startok`, `count` and reserved fields.

Safe staging order:

```text
candidate/preflight
-> write nsb_slave
-> readback/SHA verify nsb_slave
-> only then write primary flag selector
-> selector readback
-> reboot
```

A previous real write lost the TCP/Telnet session during `nsb_slave` write. Because selector write is last, `active` stayed on SLOT1 and stock booted safely. After any interrupted slot write, treat `nsb_slave` as unknown/possibly partial until readback.

---

## 5. Backup and retry policy

Before destructive stock staging a **verified full stock backup must exist**.

A new full backup is no longer forced on every engineering attempt. EXPERT item 4 supports:

```text
A. create new full backup -> verify
B. select existing full stock backup -> verify
```

Skip path still requires an existing verified full backup. This is not a zero-backup mode.

Current optional-backup/retry work:

```text
2580ae1133b59bdf4f5dd16448ad202ac120d6b2
transition: optional backup reuse and bounded stock write retries

6edff79093a40644547d3da90088cf0608af374a
expert: enable optional transition backup and write retries
```

Bounded write retry:

```text
max 3 attempts
reconnect
read target SHA first
if already expected -> continue without rewrite
else retry same write
```

No automatic writer/backend switching after destructive write begins.

---

## 6. EXPERT item 4 status

Vanilla Transition is an EXPERT operation, not ONE-CLICK.

Current operator path:

```text
START_EXPERT.cmd / START_EXPERT.sh
-> item 4: Vanilla transition / Stock Nokia -> Vanilla OpenWrt
```

Item 4 must keep reusing common UrsusFlasher auth/root/backup/transport/logging/readback infrastructure.

Passive network/device discovery is advisory and must not block item 4 by itself. Real backend geometry/profile/root checks remain authoritative.

Relevant commit:

```text
ac4d15b8bf396bbd853b58f0a141375783e7a9f2
fix: do not gate transition on passive network probe
```

MF production transition is **not ready** yet: current `stock_ab_transition` production policy is still MD-only. Do not claim MF support until board-profile-driven staging and HW acceptance exist.

---

## 7. Airoha network lifecycle: what is actually proven

The observed Web-killing `-22` mechanism is established:

```text
UrsusWeb owns eth0
-> UART standard ping
-> NetLoop()
-> eth_halt()
-> device no longer ACTIVE
-> UrsusWeb eth_rx()
-> eth-uclass returns -EINVAL (-22)
```

Therefore standard U-Boot `ping` must not be used while WebFailsafe owns network.

Interpretation:

```text
-11 / EAGAIN  packet not ready at that instant
-22 / EINVAL  device lifecycle/ownership invalid; in proven case eth was halted
```

Do not reinterpret `-22` as evidence of RX descriptor/ring/DMA/cache corruption.

Source-level basis: `airoha_eth_recv()` itself returns positive RX or `-EAGAIN`; inactive-device `-EINVAL` comes from Ethernet uclass.

---

## 8. NETFIX2

Commits:

```text
c22bcc3b0a272e1b566c7ca20cd801b545279f4d
net: sanitize Airoha datapath before TRANSITION WebFailsafe

8b1bbc948cf1146327c96482e94e383706b0d264
ci: assert TRANSITION pre-Web network sanitize
```

Startup order:

```text
URSUS_TRANSITION_WEB_BEGIN
-> URSUS_TRANSITION_NET_SANITIZE_BEGIN
-> stop DMA
-> force FEMEM_SEL=0
-> reset FE/PDMA/QDMA/XSI using existing Airoha init path
-> switch_init
-> fe_init
-> restore runtime MAC
-> eth_init
-> URSUS_TRANSITION_NET_SANITIZE_DONE
-> WebFailsafe/lwIP
```

This fixes the lifecycle mistake of resetting Ethernet underneath an already-running lwIP/Web state.

---

## 9. Latest real MD hardware evidence

Stock tcboot successfully selected second image:

```text
active = 1
curimg = 0
startok = 1
count = 15
...
new flag:
active = 1
curimg = 1
startok = 0
count = 15
...
bootflag==1 --> booting from second image
```

TRANSITION2 then reached:

```text
U-Boot 2026.07-UrsusBoot-0.1.0-alpha5-UBIUX1-TRANSITION2
URSUS_NETDBG_FEMEM_SEL ... value=0x00000000 verdict=ACCESS_EXPECTED
URSUS_NETDBG_RX_RING ... verdict=OK
random MAC assigned
URSUS_TRANSITION_NET_SANITIZE_BEGIN
URSUS_NETRESET_BEGIN build=TRANSITION2-NETFIX2 dev=airoha-gdm1
URSUS_NETRESET_DONE result=PASS next=START_URSUSWEB
URSUS_TRANSITION_NET_SANITIZE_DONE
URSUS_HTTP_HEADER_SELFTEST_PASS
URSUS_HTTP_LISTEN_OK port=80
URSUS_WEBFAILSAFE_READY
URSUS_NETDBG_FIRST_RX ret=-11 ...
```

Random MAC is acceptable by design.

Acceptance matrix:

```text
PASS  tcboot SLOT2 selection
PASS  stock FIT/hash
PASS  shim -> TRANSITION2
PASS  NAND detection
PASS  FEMEM accessibility
PASS  RX ring programming/readback
PASS  NETFIX2 pre-Web reset path
PASS  Web listener reaches port-80-ready marker
PASS  tcboot rollback path to untouched SLOT1
```

---

## 10. HTTP regression: current boundary

A separate manual `ursusnetreset` experiment proved after reset:

```text
PASS  host ping / ICMP
PASS  TCP connect to port 80
FAIL  GET / -> curl (52) Empty reply from server
FAIL  GET /api/status -> Empty reply
FAIL  HTTP/1.0 /api/status -> Empty reply
```

So the remaining known defect is currently above basic Ethernet/IP/TCP connectivity. Exact HTTP/lwIP callback root cause is not yet proven.

Current control strategy:

```text
persistent TEST61 Web
+ minimal TRANSITION wrapper
```

Commits:

```text
5647308769e978b76ca13e84c63d8b6b088ae2dd
test: restore persistent TEST61 web in transition

1701ff32cd50390cbfe0a3cb1eedecae541301ce
ci: pin transition web to persistent TEST61 source

870cd49753c0b3e15508416b025f517a0a231014
ci: drop stale web-only binary markers
```

Do not rewrite HTTP from scratch. First determine whether the unmodified persistent TEST61 `cmd/ursusweb.c` restores actual HTTP response bytes.

Hardware Web test from host:

```powershell
ping 192.168.1.1
curl.exe -v --max-time 5 http://192.168.1.1/
curl.exe -v --max-time 5 http://192.168.1.1/api/status
curl.exe -v --http1.0 --max-time 5 http://192.168.1.1/api/status
```

Do not execute U-Boot `ping` during Web ownership.

---

## 11. Stock-slot recovery command / host integration

TRANSITION command:

```text
ursusstockslot status
ursusstockslot master
ursusstockslot slave
```

Backend contract:

```text
read full primary flag eraseblock to RAM
report selector fields
modify active only
preserve curimg/startok/count/reserved
write primary flag only
readback and verify
never write flagback manually
```

Relevant commits:

```text
4e535688baa53defe2fabe5b5ceb48cea515d967  transition: add stock slot selector command
a1aeeb9ef30c22ef91221f263b8303455ff3f66b  ci: build and assert transition stock slot command
b0374ed2e2562825130875b89b4c251eb4225ba1  fix: repair transition stock slot patch
3dba8620a0c7f9a4b29b7ae0f0343dce28abfd64  expert: add UART stock slot selector
62da13604975b40b52f2271efd3b84d62df514b4  expert: expose UART stock slot switching
40072e5e3ad113b5000f8d8d8e1f8803c3c29121  fix: tolerate ANSI tail after recovery U-Boot prompt
59a67dae8971ab9a987e97eeb2cc3643539c7e9b  fix: install ANSI-tolerant recovery prompt detector
686fb0396bc6ee8a06fcb92fd02b8e26d6a1b2f4  uart stockslot: wake idle U-Boot prompt with Enter
```

The requested Web button for return to stock SLOT1 is still a follow-up. Do not claim it exists until it is implemented and tested.

---

## 12. Packaging status

Previously missing XG140 helper/import was fixed:

```text
703a987f2eda1e89cd31891affddb86d1f8b91ac
a01858d4febe38a57ac4799ad0c8e52ed85d13c7
```

Canonical launchers remain:

```text
START_ONECLICK.cmd
START_ONECLICK.sh
START_EXPERT.cmd
START_EXPERT.sh
```

Recent operator-rollup CI fixes:

```text
8f81f18c01fbf2b707d3925a16f263f180744aee  decouple operator rollup from fastscan BL2
5aad0e412908cd56ddff97e05c5d8ffe34316625  locate nested baseline rollup root
53330b219072f109a593c1ae26838e6548b35864  unpack baseline operator zip before overlay
```

Known prior successful CI evidence is not equivalent to the current branch HEAD and must not be presented as current-HW proof.

Known earlier successful runs:

```text
35102324176 @ 8b1bbc948cf1146327c96482e94e383706b0d264
35107012785 @ 7cebcd83c8c1263c8e59f0eea820ddf1d8c91e23
```

Always query exact current SHA/run before saying current CI is green.

---

## 13. XG140 independent track

XG140 remains device-derived native-hybrid persistent work.

Known boot area:

```text
mtd0 size        0x80000
native FIP start 0x800
vendor env       0x7c000..0x7ffff
```

Candidate policy:

```text
preserve BootROM prefix
preserve native trusted FIP entries
replace only approved NT_FW/BL33 span
preserve live vendor env
```

Before first persistent destructive write, prove an independent BootROM/UART recovery ingress on stock hardware. XG140 work must not be forced into the MD SLOT2 TRANSITION architecture without new hardware necessity.

---

## 14. Immediate next work

```text
1. Verify live branch HEAD before every write.
2. Build current TRANSITION2 control image with persistent TEST61 Web baseline.
3. Check exact CI run for that SHA; CI PASS is build/package proof only.
4. Boot it in MD SLOT2 and test external curl without U-Boot ping.
5. If HTTP works, reintroduce TRANSITION Web metadata only incrementally and retain the working callback path.
6. If HTTP is still Empty reply, instrument the TEST61-compatible HTTP/lwIP callback path rather than reopening ETH as the primary hypothesis without new evidence.
7. HW-verify ursusstockslot status/master and EXPERT UART wrapper, preserving active-only selector semantics.
8. Add Web return-to-SLOT1 control only after the common backend is hardware accepted.
9. After TRANSITION2 Web/API HW_PASS, implement MD final Vanilla BL2/FIP/UBI migration.
10. Then refactor staging for MF board policy and HW-accept MF independently.
```

---

## 15. Repository/operator rules

- Work on `feature/ursusboot-modular-airoha` only unless explicitly told otherwise.
- Never modify `main`, merge, tag or release without explicit instruction.
- Never commit device backups, plaintext credentials, serial/GPON secrets or unique device identity.
- Minimum operator ceremony: one meaningful `y/N` after automatic preflight for a normal destructive operation.
- Do not introduce policy gates where automatic geometry/boundary/readback checks suffice.
- A verified full stock backup must exist before stock destructive staging; it may be newly created or an existing validated backup.
- Selector is written only after verified `nsb_slave` readback.
- No automatic writer/backend switching after destructive write starts.
- TRANSITION does not depend on stock RI/factory MAC identity to start.
- Never use standard U-Boot `ping` while UrsusWeb owns network.
- Distinguish `CI PASS` from `HW PASS`.
- Functional label remains `TRANSITION2`.
# MD Vanilla handoff — pregnant initramfs / EXPERT item 4

**Дата:** 2026-09-17  
**Ветка:** `feature/ursusboot-modular-airoha`  
**HEAD перед этой редакцией handoff:** `a9e3036451ec778fb6567232dd0e26622645580b`  
**Нормативное ТЗ:** `docs/UrsusBoot_UrsusFlasher_TZ_RU_v5.45_VANILLA_INITRAMFS.md`

> **CURRENT OVERRIDE — 2026-09-23:** ownership of the persistent UrsusBoot source/build line is moved to `Medvedolog/airoha-ursusboot`. TEST63 must be built there from its source tree plus the proven UrsusFlasher-era changes that are deliberately ported into that repository. UrsusFlasher must consume an exact pinned `airoha-ursusboot` commit/artifact set when assembling the operator kit. See §21. Where older sections conflict with §21 on UrsusBoot source ownership/build provenance, §21 wins.

## 1. Главный архитектурный pivot

Vanilla item 4 больше не должен зависеть от исправления сетевого стека `UrsusBoot TRANSITION2`.

Новый production path:

```text
Nokia stock
  -> verified full backup
  -> подготовка stock-compatible SLOT2 payload
  -> одно meaningful y/N
  -> write/readback SLOT2
  -> selector -> SLOT2 + readback
  -> reboot
  -> OpenWrt pregnant initramfs
  -> autonomous migration stage2
  -> canonical OpenWrt UBI
  -> Vanilla BL31/U-Boot + sysupgrade + identity
  -> BL2 LAST
  -> full readback
  -> reboot
  -> Vanilla OpenWrt
```

`TRANSITION2` сохраняется как diagnostic/R&D линия, но не является обязательной install environment для Vanilla.

## 2. Что берём из MedveFlasher, а что нет

Берём правильную форму: transition Linux в SLOT2, который сам выполняет migration. Эта архитектура прошла серию успешных установок MedveFlasher.

Не переносим fatal topology defect MedveFlasher: fallback не должен одновременно быть write target. Старый MedveFlasher мог удалить recovery `fit` перед записью replacement и получить окно без bootable image.

В новом item 4 topology разделена:

```text
SLOT1 = stock fallback
SLOT2 = installer initramfs
UBI/FIP/BL2 = destructive production targets
BL2 = LAST
```

До destructive migration SLOT1 остаётся fallback, а SLOT2 — installer. Они не являются тем же target, куда stage2 пишет production layout.

## 3. Что доказал TRANSITION2 HW цикл

Для XG-040G-MD аппаратно доказано:

```text
PASS stock tcboot выбирает SLOT2
PASS stock FIT/hash -> Linux-compatible payload
PASS TRANSITION2 запускается
PASS Fudan FM25G02B виден
PASS fixed MAC установлен до Ethernet probe
PASS recovery IPv4 = 192.168.1.1/24
PASS RX LAN -> switch/GDM/QDMA -> CPU
PASS lwIP/U-Boot формирует TX frame
PASS QDMA потребляет TX descriptor, DONE=1
```

Host-visible ping/Web при этом не появился. Остаточная неисправность находится после QDMA TX consumption — GDM/switch egress либо иной inherited tcboot state. Для Vanilla это исследование замораживается: Linux initramfs использует штатный Linux networking/MTD/UBI stack.

Не возвращаться к switch dump/normalization как prerequisite Vanilla item 4 без прямого требования оператора.

## 4. Что переезжает из MedveFlasher

Источник proven mechanics: `Medvedolog/nokia-router-medveflasher`.

Адаптировать:

```text
stock -> Linux bootm handoff
self-contained transition bundle
RAM initramfs stage2/autoflash
canonical UBI repartition/migration mechanics
identity preservation/restore mechanics
SSH discovery + polling + reconnect
production reboot detection
transition recovery shell when stage2 fails
status/log model
```

Не переносить MedveFlasher UX ceremony:

```text
никаких codewords
никаких длинных typed confirmations
никаких повторных y/N между стадиями
никакого ручного продолжения каждой NAND операции
никакого выбора mtd/offsets пользователем в normal path
```

Механика — от MedveFlasher. UI и safety semantics — UrsusFlasher.

## 5. UrsusFlasher UI остаётся нашим

Использовать существующий `ursusflasher/src/console_ui.py`:

```text
ASCII bear
amber / amber2 / sand / ok / bad palette
[ШАГ] / [STEP]
[ГОТОВО] / [READY] / [PASS]
[ЖДУ] / [WAIT]
[ВНИМАНИЕ] / [WARNING]
[ОШИБКА] / [ERROR]
```

Новые stage2/SSH-monitoring сообщения проходят через этот UI layer.

## 6. Минимум gates

Normal Vanilla transaction имеет **одно meaningful `y/N`** после полного automatic preflight-summary.

Это `y` разрешает весь заранее показанный plan:

```text
SLOT2 write/readback
selector -> SLOT2/readback
reboot
pregnant initramfs autonomous stage2
UBI migration
FIP/sysupgrade/identity writes
BL2 LAST
verification
production reboot
```

После reboot дополнительных confirmations нет.

Запрещены:

```text
CONFIRM FORMAT AND FLASH
YES I UNDERSTAND
повторные y/N перед erase/write
отдельный confirm для rollback внутри уже подтверждённой transaction
```

Safety обеспечивается automatic validation/readback, а не ceremony.

## 7. Pregnant initramfs payload

В transition initramfs должны находиться заранее:

```text
OpenWrt kernel + initramfs
correct board DTB
Vanilla sysupgrade/production artifact
Vanilla BL31/U-Boot FIP
BL2/preloader if required
Fudan/FMSH support provenance
migration/autoflash scripts
prepared device identity data
manifest + hashes
Linux ursusstockslot helper
status service + journal
SSH
```

Критическая migration после boot не должна зависеть от скачивания production firmware по сети.

## 8. Stage1 на stock Nokia

До единственного `y/N`:

```text
board/profile resolve
verified full stock backup
identity extraction
stock A/B layout resolve
secondary SLOT2 resolve
pregnant bundle validation
embedded artifact provenance/hashes
candidate SLOT2 build
transport preflight
rollback availability proof
```

После `y`:

```text
write SLOT2
-> full SHA/readback
-> write selector only after SLOT2 PASS
-> selector readback
-> reboot
```

До этого момента SLOT1/master остаётся untouched.

## 9. Stage2 автономен, `/tmp` — только telemetry

Initramfs сам запускает migration service.

Нормальная state machine:

```text
BOOTED
PREFLIGHT
MIGRATION_OK
PROD_WRITING
PREPARING_UBI
WRITING_FIP
WRITING_SYSUPGRADE
RESTORING_IDENTITY
WRITING_BL2_LAST
VERIFYING_FINAL
PROD_VERIFIED
BOOT_CONFIRMED
FAILED
```

Live status contract:

```text
/tmp/ursus-install/status.json
/tmp/ursus-install/install.log
```

`/tmp` не переживает reboot/power loss и потому **никогда не является rollback authority**.

Рекомендуемые live fields:

```text
state
destructive_started
stock_master_intact
rollback_allowed
step
steps_total
progress
last_verified
error
```

Host не должен быть trigger каждой write-stage.

## 10. Migration state: до UBI и после UBI

На virgin stock OpenWrt `ubootenv`/`ubootenv2` как canonical UBI volumes ещё не существуют. Поэтому **pre-destructive stage не обязан иметь persistent OpenWrt marker** и не должен делать вид, что может записать `MIGRATION_OK` через `fw_setenv` до появления соответствующего environment.

До первой destructive NAND operation rollback safety определяется положительным доказательством pristine stock layout, описанным в разделе 13.

Нормативные persistent состояния после появления подходящего NAND-backed carrier:

```text
PROD_WRITING
PROD_VERIFIED
BOOT_CONFIRMED
```

`MIGRATION_OK` остаётся допустимым live/diagnostic состоянием preflight, но не является обязательным persistent marker на virgin stock.

После создания canonical UBI `ubootenv`/`ubootenv2` становятся штатным carrier для migration state. Запись каждого state должна иметь readback (`fw_setenv` + `fw_printenv`/эквивалент).

Критическое правило:

```text
marker says PROD_WRITING / PROD_VERIFIED / BOOT_CONFIRMED
    -> master rollback REFUSED безусловно

marker absent
    -> отсутствие само по себе ничего не доказывает
    -> решение принимает stock-evidence probe
```

Если marker отсутствует после того, как stock layout уже не pristine, rollback запрещён. Это покрывает power loss/reset во время первой destructive стадии ещё до появления нового UBI environment.

Нельзя выбирать pre-UBI marker location «по догадке» в stock NAND. Если позже будет введён отдельный carrier вне destructive span, он требует отдельного geometry/readback/HW acceptance.

## 11. SSH — monitor/recovery plane

После reboot UrsusFlasher:

```text
finds transition initramfs
connects SSH
polls live status
reads persistent migration state when available
streams/tails install.log
renders progress through console_ui
reconnects after transient loss
waits for production reboot
validates final board/layout/identity
```

Если SSH пропал:

```text
stage2 continues locally
host reconnects
host reads current state
host never blindly repeats a NAND write
```

Если migration `FAILED`, но initramfs остаётся жив, сохраняется SSH recovery shell.

## 12. Linux `ursusstockslot`

Перенести в initramfs operator contract:

```text
ursusstockslot status
ursusstockslot master
ursusstockslot slave
```

Семантика:

```text
status -> read-only selector decode
master -> active=0 only
slave  -> active=1 only
```

Инвариант сохраняется буквально:

```python
struct.pack_into("<I", out, 0, target)
if out[4:] != flag[4:]:
    raise RuntimeError("activation flag changed fields other than active")
```

MD profile сейчас знает:

```text
flag        expected mtd8,  size 0x00040000
flagback    expected mtd9
nsb_master  expected mtd14, size 0x02880000
nsb_slave   expected mtd15, size 0x02880000
erase size  0x00020000
```

Но Linux helper не должен использовать `mtd8` как универсальный API. Он resolve partition по имени/profile через `/proc/mtd` и сверяет geometry.

Write contract:

```text
read full primary flag eraseblock
modify only active
preserve all other bytes
write buffered block
read back full block
verify target active
verify every non-active byte unchanged
```

`flagback` вручную не менять; reconciliation принадлежит stock tcboot.

Success marker:

```text
URSUS_STOCKSLOT_DONE target=master active=0 readback=PASS next=RESET
```

После него в Linux:

```text
sync
reboot -f   # если обычный reboot недостаточен
```

### Guard находится в utility, не в UI

`ursusstockslot master` обязан сам вычислить rollback safety и отказать, если она не доказана. Недостаточно скрыть команду в UrsusFlasher.

Public normal path не имеет `--force` обхода guard.

## 13. No-UART rollback — трёхсостоянийное правило

`rollback_allowed` — derived result, а не trusted boolean из RAM.

### Rule 1: явный destructive marker

Если persistent state доступен и равен одному из:

```text
PROD_WRITING
PROD_VERIFIED
BOOT_CONFIRMED
```

то:

```text
rollback_allowed=false
ursusstockslot master -> REFUSED
```

Это unconditional veto независимо от остальных признаков.

### Rule 2: marker отсутствует, но stock положительно доказан pristine

Отсутствие marker допустимо на первом boot virgin stock, потому что canonical OpenWrt env ещё не существует.

В этом единственном классе случаев rollback разрешён только если NAND evidence **положительно** доказывает всё одновременно:

```text
expected stock partition/layout geometry matches
nsb_master matches verified stock backup/evidence
all critical stock regions that migration may touch match verified backup/evidence
stock UBI/rootfs/layout signatures match expected stock state
no canonical OpenWrt UBI/layout is present
no partially converted UBI/layout is present
no destructive-write evidence is present
```

Тогда:

```text
marker = absent
stock_evidence = PRISTINE
rollback_allowed=true
ursusstockslot master -> ALLOWED
```

Это не доверие отсутствию marker; authority здесь — положительный NAND proof.

### Rule 3: все остальные случаи

Если marker отсутствует/corrupt/unknown, но stock evidence не может доказать pristine state, либо evidence incomplete/mismatched:

```text
rollback_allowed=false
URSUS_STOCKSLOT_REFUSED target=master reason=ROLLBACK_UNSAFE
```

В частности, reset/power loss после начала `ubiformat` не сможет попасть в Rule 2: изменённые eraseblocks/UBI signatures/hashes ломают pristine proof даже если persistent marker ещё не успел появиться.

### Preflight failure escape hatch

Если pregnant initramfs загрузился на untouched stock и preflight упал до первой destructive operation, marker может никогда не существовать. При `stock_evidence=PRISTINE` automatic rollback должен работать:

```text
ursusstockslot status
ursusstockslot master
verify full selector readback PASS
sync
reboot
```

Повторного user confirmation не требуется: rollback является fail-safe частью уже подтверждённой transaction.

После начала destructive migration автоматический master rollback запрещён.

## 14. Acceptance для rollback contract

Обязательные отдельные HW tests:

```text
virgin stock -> SLOT2 initramfs -> forced preflight FAIL
persistent marker never existed
stock evidence = PRISTINE
ursusstockslot master -> ALLOWED
selector readback PASS
reboot -> untouched stock SLOT1 PASS

explicit PROD_WRITING present -> master REFUSED PASS

reset/power-loss injected during first destructive operation before marker exists
marker absent
stock evidence != PRISTINE
master REFUSED PASS

marker missing/corrupt after converted/partial layout -> master REFUSED PASS
stock evidence incomplete/mismatch -> master REFUSED PASS
```

Без первого теста no-UART escape hatch не считается доказанным.

## 15. Final Vanilla payload policy

Конечный MD Vanilla boot chain:

```text
official/pinned OpenWrt source/build contract
OpenWrt AN7581 Nokia XG-040G-MD target
OpenWrt BL2/BL31/U-Boot
+ only required Fudan/FMSH SPI-NAND hardware support patches
+ no Ursus-specific persistent code
```

В финальном U-Boot не должно быть:

```text
UrsusBoot product identity
TRANSITION/PERSISTENT mode
WebFailsafe Ursus runtime
Ursus API
ursusstockslot
ursusnetreset
custom Ursus writer/recovery policy
```

После production boot пользователь обновляет OpenWrt штатным `sysupgrade`.

## 16. Persistent UrsusBoot — отдельный продукт

Persistent TEST61 lineage остаётся отдельным recovery-first продуктом. Известный lifecycle defect стандартных U-Boot network commands против живого WebFailsafe (`netif_remove`/`eth_halt`) исправляется отдельно и больше не блокирует Vanilla item 4.

## 17. Следующая реализация

```text
1. Не тратить новые HW boots на TRANSITION2 switch egress ради Vanilla.
2. Вытащить из MedveFlasher минимальный autonomous stage2/autoflash contract.
3. Сделать stock-compatible installer FIT builder без старого ~3.7 MiB in-place ограничения.
4. Собрать pregnant OpenWrt initramfs с embedded final artifacts.
5. Реализовать Linux ursusstockslot + byte-preservation/readback invariants + internal guard.
6. Реализовать stock-evidence probe, способный доказать PRISTINE или вернуть UNKNOWN/CHANGED.
7. Не требовать pre-UBI persistent marker на virgin stock.
8. После появления canonical UBI реализовать PROD_WRITING/PROD_VERIFIED/BOOT_CONFIRMED с readback.
9. Подключить status.json/install.log + SSH monitoring/reconnect к item 4 через console_ui.
10. Оставить одно y/N.
11. HW-test virgin-stock preflight FAIL -> marker absent -> pristine proof -> master rollback -> stock boot.
12. HW-test reset/power-loss во время первой destructive стадии до marker -> pristine proof fails -> master REFUSED.
13. Только после этих HW PASS разрешить full destructive migration.
14. HW-test autonomous migration -> BL2 LAST -> Vanilla production boot.
15. После MD acceptance параметризовать для MF без копирования MD offsets.
```

## 18. Repo/operator invariants

```text
branch = feature/ursusboot-modular-airoha
main untouched
no merge/tag/release without explicit operator command
no device backups/credentials/serial/GPON identity in git
one meaningful y/N for normal destructive transaction
automatic readback > extra operator ceremony
/tmp telemetry never authorizes rollback
explicit destructive marker = rollback denied
marker absent + positive pristine-stock proof = rollback may be allowed
marker absent + anything else = rollback denied
ursusstockslot master enforces guard internally
CI PASS != HW PASS
```


---

## 19. Session update — 2026-09-18 / UnameOne production payload + full-build direction

Live branch HEAD observed before this documentation update:

`cf4837a41b9554855a09a8449b21fd11d41b0135` — `ci: fetch current Vanilla initramfs bases`.

Exact GitHub Actions run for that SHA:

`35325588999` / **Vanilla initramfs base fetch** — CI PASS. This proves only current MD/MF initramfs base retrieval; it is **not** a complete installer build and **not** HW PASS.

### Operator decision: no boot-only intermediate build

The operator has UART available and explicitly requested to stop spending iterations on a separate boot-only acceptance payload.

Next test kit must therefore be the **full pregnant migration variant**:

```text
stock Nokia
-> full backup/preflight
-> ONE meaningful y/N
-> stock-compatible SLOT2 pregnant Linux
-> selector/readback
-> reboot
-> autonomous stage2
-> canonical UBI migration
-> production UnameOne sysupgrade
-> Vanilla FIP
-> identity restore
-> BL2 LAST
-> final readback
-> reboot into production
```

Rollback/evidence guards from sections 10–14 remain mandatory. Removing the boot-only iteration does **not** remove automatic safety checks.

### UnameOne Edition 2026-09-16 is the production source-of-truth

The operator supplied four matching images. Their metadata is pinned in:

`config/UNAMEONE_2026-09-16_PAYLOADS.json`

Pinned metadata commit:

`83fc80a5ae4b3a7de42e22228d47b1a253676df4`

Production payload policy:

```text
EXPERT item 1
ONE-CLICK
EXPERT item 4 pregnant migration
        |
        +--> one common UnameOne 2026-09-16 production set
```

MD:
- plain stock-layout sysupgrade tar: SHA256 `1a0abfed83c52c55d60a3ef70c5df92c960fe3cc961bd2ca734e6d1749797a8d`
- UBI sysupgrade ITB used as the pregnant payload's production child: SHA256 `9b1f0899ca4ef610f6d87e8572d369adb420f104bda667556e8a0b5979f066dd`

MF:
- plain stock-layout sysupgrade tar: SHA256 `d988d6f47d69e7264bb7a0d81392c3fdc3bca163075066ee0e0b3f971abf8cbf`
- UBI sysupgrade ITB used as the pregnant payload's production child: SHA256 `21dcf4c6ca64ea0c5bc3d601e4a8f99a3f002371b873f399f622cbd9223fd1d1`

All four identify Linux 6.18.52 / matching MD or MF board profiles. The `.bin` inputs are OpenWrt sysupgrade tar images, **not factory images**.

The UBI ITB must be carried **byte-for-byte** in item 4 and verified by pinned SHA before the destructive boundary. Do not silently replace it with whatever snapshot happens to be current.

### Runtime vs child firmware

Keep these two concepts separate:

```text
pregnant runtime = current OpenWrt initramfs + Ursus/Medve stage2
production child = pinned UnameOne 2026-09-16 UBI sysupgrade
```

The current OpenWrt snapshot may be used as the transient Linux/initramfs base. It must not silently change the pinned production child.

### Build plumbing

The earlier ImageBuilder experiment proved that `make image` does not emit the required initramfs ITB for this path. Do not return to that approach.

Use the already proven MedveFlasher-style FIT/initramfs surgery:
- obtain current official MD/MF initramfs FIT;
- unpack kernel/LZMA + linked newc initramfs;
- inject Ursus stage2, `ursusstockslot`, SSH/status/log and required manifests/tools;
- rebuild newc without corrupting bytes outside the linked initramfs window;
- rebuild compressed kernel/FIT and hashes;
- create the stock-compatible SLOT2 wrapper;
- carry the pinned UnameOne UBI sysupgrade as the production child/bundle component rather than selecting a new production snapshot.

### MedveFlasher reuse boundary

Reuse proven mechanics, not the old failure topology:
- autonomous autoflash/stage2;
- UBI migration;
- identity preservation/restore;
- SSH monitoring/reconnect;
- status/log;
- production boot detection.

Do **not** recreate the old MedveFlasher condition where recovery image and production write target are the same object. SLOT1 remains the pre-destructive fallback, SLOT2 is installer, production writes target canonical OpenWrt layout.

### Immediate next work

1. Implement the full MD/MF pregnant builder using current initramfs bases.
2. Inject autonomous stage2 and guarded Linux `ursusstockslot`.
3. Embed/reference the exact pinned UnameOne UBI child for the selected profile and verify SHA before writes.
4. Reuse proven MedveFlasher UBI/identity mechanics, adapted to Ursus state/readback rules.
5. Preserve Fudan/FMSH-capable final MD boot-chain provenance.
6. Keep FIP/profile artifacts explicit; never infer MD/MF offsets from the other profile.
7. BL2/preloader is written LAST.
8. Produce a dedicated GitHub Actions workflow/artifact for the full MD+MF test kit.
9. Verify the **exact workflow run against the exact resulting SHA** before calling CI PASS.
10. Give the operator a direct ZIP link after success.
11. First full hardware run is still HW TEST; CI success must not be described as HW success.

TRANSITION2 U-Boot network/switch investigation remains frozen for Vanilla unless explicitly reopened by the operator.


---

## 20. Session update — 2026-09-22 / first real Fudan attempt + OEM FIT carrier fix

### Live development state before this documentation update

The code-bearing HEAD that produced the current FULL test kit is:

`42efabbeb433621c94c2c79f1a1a146a9668065e` — `test: cover OEM FIT trailing payload layout`.

Its two relevant corrective commits are:

```text
22499840065a067ca0eec02186b16ad2e115bea0
  fix: accept stock FIT with NT-FW trailing payload

42efabbeb433621c94c2c79f1a1a146a9668065e
  test: cover OEM FIT trailing payload layout
```

Exact CI for this code:

```text
workflow: Vanilla pregnant MD+MF build
run:      35625391866
head SHA: 42efabbeb433621c94c2c79f1a1a146a9668065e
result:   SUCCESS
artifact: 10652380364
name:     UrsusFlasher-VANILLA-PREGNANT-FULL-42efabbeb433621c94c2c79f1a1a146a9668065e
digest:   sha256:413d77e9fd4038e2e9474802386b70098db95e637f9ece8d8842083f5d9d74ec
```

This is **CI PASS only**. The full Vanilla migration is still awaiting a successful hardware run through destructive migration and final production boot.

The separate generic `Airoha multimodel public test` on the same SHA failed. It is not the item-4 acceptance workflow and must not be reported as item-4 HW/CI failure. XG140-specific automatic workflows remain paused/manual-only.

### What happened on the first real Fudan MD run

The operator ran EXPERT item 4 on stock Nokia XG-040G-MD/Fudan using the previous FULL kit `190022d...`.

Observed sequence:

```text
stock Web/Telnet/root access PASS
full mtd0..mtd16 backup PASS
restore-validator PASS
no NAND write started
candidate construction FAIL
```

Failure:

```text
stock FIT/NT-FW size mismatch:
fit=0x70d018
nt_payload=0x2058127
```

This failure happened after the complete backup and before `sat._write_partition()`; therefore:

```text
mtd15 was NOT written
mtd8 selector was NOT written
SLOT1 remained active
device remained stock/pristine
```

### Root cause

`stock_fit_wrapper.fit_props()` required:

```text
FIT totalsize == NT-FW payload size
```

That condition is not a tcboot safety invariant. It was an overfit to one observed OEM packing shape.

Real stock may legally contain:

```text
HDR2
  -> FIT metadata/tree
  -> external image data / carrier payload
  -> remaining NT-FW payload
```

Therefore `FIT totalsize < NT-FW payload` is valid when all referenced image ranges remain inside the NT-FW entry.

The old equality check was a **false gate** and must not be resurrected.

### Correct wrapper contract

For MD stock-compatible handoff, the contract is now:

```text
FIP entry range valid
HDR2 present
FIT header/tree structurally valid
FIT entirely inside NT-FW
required stock topology present:
  conf@1
  kernel@1
  fdt@1
  filesystem@1
kernel load/entry = expected MD values
kernel/fdt/filesystem data ranges inside NT-FW
data may be:
  inline data
  data-position
  data-offset
only allowed changes:
  kernel@1 payload
  kernel compression
  kernel hash
all other bytes preserved byte-for-byte
candidate full-partition readback after write
```

The wrapper now records `fit_trailing_payload_size` instead of rejecting it.

### Gate policy

Do **not** add a preflight merely because one known stock dump has a particular byte shape.

A gate is justified only if failure of the checked condition would make the pending operation unsafe or ambiguous, e.g.:

```text
wrong board/family/profile
wrong physical MTD geometry
target range outside the selected partition
missing/invalid boot envelope required by tcboot
identity/critical calibration evidence missing where the operation needs it
payload does not fit its proven writable span
unexpected modification outside explicitly writable spans
writer/readback mismatch
destructive-state ambiguity
```

Not acceptable as mandatory gates without an independent safety reason:

```text
FIT must occupy all remaining carrier bytes
a field must equal one sample dump even though the code replaces/ignores it safely
a cosmetic/version/string marker must exist when stronger structural identity exists
a historical layout habit that is not required by the reader/writer
```

Prefer range validation + preservation + readback over exact-shape assertions.

### Current item-4 architecture

MD path:

```text
stock tcboot
 -> selected stock SLOT2
 -> preserved Nokia FIP/HDR2/FIT topology
 -> kernel@1 ARM64 Linux Image handoff
 -> RAM-only pregnant UrsusBoot
 -> bootm pregnant runtime at 0x92000000
 -> OpenWrt initramfs
 -> autonomous stage2
 -> canonical UBI
 -> pinned UnameOne production FIT
 -> bosa/ri identity restoration
 -> Vanilla FIP
 -> BL2/preloader LAST
 -> final readback
 -> production OpenWrt
```

Pregnant UrsusBoot keeps LWIP compiled only because the inherited TEST61 command set links `ursusweb.o`; runtime Web/network is not entered. Dispatcher immediately runs `bootm 0x92000000`. If `bootm` returns/fails it executes `reset` to hand control back to stock tcboot A/B retry.

### No-UART rollback window

Until the first `ubiformat`:

```text
mtd14 / MASTER remains untouched
stock tcboot remains boot authority
selector active=1 points at pregnant SLOT2
failed transient handoff resets into tcboot
tcboot retry counter may eventually return to SLOT1
```

For a completely non-booting SLOT2, the documented emergency operator fallback is to let tcboot consume the stock retry counter by repeated boot attempts (approximately 6 s powered per attempt, up to the stock count of 15) and return to MASTER/SLOT1.

This is only valid before destructive migration starts.

At stage2:

```text
DESTRUCTIVE=0
preflight failure -> sync -> reboot -f -> stock tcboot
DESTRUCTIVE=1 immediately before first ubiformat
after that -> no automatic stock rollback loop
```

The exact tcboot counter decrement behavior remains hardware evidence, not a CI claim.

### Emergency/operator documentation added

README commit:

`16b0e26ad6f2458ba646206636258e03a71e3848` — `docs: add flashing emergency recovery playbook`.

It documents:

- how to enter persistent UrsusBoot Recovery with Reset;
- distinction between Reset-after-power and Reset-held-before-power/Airoha BootROM;
- pre-destructive SLOT2 retry/fallback without UART;
- one-shot initramfs boot from UrsusBoot Web without writing flash;
- SSH diagnostics from RAM OpenWrt;
- stock selector inspection/switching via root Telnet helper;
- UART/BootROM recovery boundaries.

### Immediate next hardware test

Use only the FULL artifact built from `42efabb...` or later.

Expected first hardware checkpoint:

```text
1. stock access PASS
2. complete stock backup restore-validator PASS
3. stock wrapper accepts the real OEM FIT carrier
4. item4 reaches the single y/N preflight summary
5. after y:
   mtd15 write + full SHA readback PASS
   mtd8 active-only selector write + full readback PASS
6. reboot
7. UART proves:
   stock tcboot selects SLOT2
   conf@1/kernel@1/fdt@1 accepted
   ARM64 handoff starts pregnant UrsusBoot
   pregnant bootm starts OpenWrt initramfs
8. stage2 preflight
9. only after this evidence allow observation of destructive UBI migration
10. final production OpenWrt + BOOT_CONFIRMED
```

If anything fails before the first `ubiformat`, preserve UART/logs and treat stock fallback as the expected safety path. Do not add a new arbitrary gate merely to reject the new observation; first decide whether the observation actually violates a safety invariant.

### Current repo rules remain

```text
branch = feature/ursusboot-modular-airoha
main untouched
no merge
no tag/release without explicit operator command
no backups/credentials/serial/GPON/device identity in git
one meaningful y/N after automatic preflight
CI PASS != HW PASS
exact run + exact SHA required for CI PASS
XG140 line paused unless operator explicitly reopens it
```
## 21. Session update — 2026-09-23 / `airoha-ursusboot` становится main line для TEST63

### Решение по ownership

Начиная с TEST63, source-of-truth для самого UrsusBoot переносится из монолитного `airoha-router-ursusflasher` в standalone repository:

`Medvedolog/airoha-ursusboot`.

Нормативное разделение ответственности:

```text
Medvedolog/airoha-ursusboot
  = UrsusBoot source-of-truth
  = MD/MF board profiles and policies
  = TEST63 identity and firmware source delta
  = persistent/RAM-recovery UrsusBoot build
  = UrsusBoot fast-BL2/preloader provenance
  = family-specific UrsusBoot artifacts + hashes

Medvedolog/airoha-router-ursusflasher
  = operator orchestration
  = stock/OpenWrt access, backup and restore validation
  = transports, diagnostics and readback
  = production OpenWrt payload manifests
  = exact pin to one airoha-ursusboot commit/artifact set
  = canonical ONECLICK/EXPERT kit packaging
```

UrsusFlasher must not remain a second independently evolving UrsusBoot source tree. TEST63 is not assembled by replaying an UrsusFlasher-local historical patch stack over a stale source bundle. The relevant proven firmware changes are ported into `airoha-ursusboot`, reviewed there, and TEST63 is built from that repository's actual source at an exact commit.

Host-only UrsusFlasher fixes remain host-only. In particular the `/api/status` polling/reconnect/fallback logic belongs to UrsusFlasher and is not a reason to duplicate host code into the bootloader repository.

### Standalone repository state at the time of this decision

Observed `Medvedolog/airoha-ursusboot` main HEAD when this handoff section was written:

`9427623e1974407f1eac12f147a077f848195843`.

Current standalone build contract is not yet sufficient for TEST63 release production:

- `xg040-md` / AN7581 has the complete persistent packaging path: `u-boot.TEST61.full.config`, a 512 KiB stock boot-area template and `reference/md/ursusboot-test61-update.fip`. `build.sh` can emit `u-boot.bin`, `u-boot.lzma`, repacked `ursusboot-update.fip`, `ursusboot-install-mtd0.bin` and per-build `SHA256SUMS`.
- `xg040-mf` / AN7583 has a real source/profile/config/template, but its registry entry still uses `an7583_nokia_xg-040g-mf_MF2_RAM_defconfig` and `reference_fip: null`. Therefore the current generic `build.sh` has only a raw `u-boot.bin` path for MF and does not yet have a complete persistent FIP/install lineage.
- `xg140-md` remains intentionally non-buildable/scaffolded and is outside this TEST63 work unless explicitly reopened.
- The source tree already contains the Fudan/FMSH `FM25G01B/FM25G02B` U-Boot support inherited from the FUDAN1 line. TEST63 must preserve it and add explicit binary assertions so this support cannot silently disappear.
- `src/u-boot/cmd/ursusubi.c` still contains the old MD HW-proven UBI preloader and 128 KiB BL2 SHA256 constants. A new fast preloader therefore requires an explicit build-time pin/generation mechanism before compiling TEST63.
- The fast NAND/UBI scan patch is an ATF/BL2 change, not a U-Boot BL33 change. The current standalone tree contains no `nandflash_read_range` fast-BL2 implementation/build path. That provenance/build responsibility must be moved into the standalone TEST63 line rather than left as an UrsusFlasher-only CI sidecar.
- `config/board-profiles.json` contains fragment and `board_policy_header` metadata, but today's top-level `build.sh` primarily consumes the resolved full config/template/reference FIP and runtime role; it does not currently drive the complete modular fragment/policy application pipeline. TEST63 work must make the actual build path and the declared profile contract agree rather than relying on metadata that is not consumed.

### Current standalone CI is QA-only

At `9427623e...`, `.github/workflows/qa.yml` contains one Ubuntu job which runs:

```text
bash ./scripts/qa.sh
```

That QA verifies repository structure and important source/packaging invariants, including board-template identity/size, profile registry paths, MD donor-FIP repack reproducibility, self-contained-repository policy, shared lwIP/network invariants, MAC/preboot and environment guards, and negative profile/role cases.

It deliberately does **not** cross-compile MD or MF, does not build ATF/BL2, does not produce target artifacts, and therefore cannot currently provide TEST63 BUILD PASS. This distinction must remain explicit:

```text
standalone QA PASS != target BUILD PASS != HW PASS
```

### TEST63 build contract in `airoha-ursusboot`

The target architecture is one reproducible family-aware pipeline per exact standalone commit.

For each supported XG-040G family:

```text
1. resolve board/profile from airoha-ursusboot
2. use pinned toolchain/OpenWrt/ATF provenance
3. build the family fast-scan BL2 with the NAND/UBI scan patch applied inside the real prepare/compile path
4. prove the compiled ATF source still contains the fast-scan code
5. wrap that raw BL2 into the exact UBI preloader/FIP presentation expected by UrsusBoot
6. compute the preloader SHA256 and complete 128 KiB BL2-candidate SHA256
7. compile TEST63 BL33 from airoha-ursusboot source with exactly those hashes pinned/generated into the runtime
8. prove old family/preloader hashes did not survive accidentally
9. prove Fudan FM25G01B/FM25G02B support remains in the resulting U-Boot binary where applicable
10. LZMA1EXT/no-EOPM pack the current BL33
11. repack the board-correct donor FIP with that exact current BL33
12. verify FIP boundaries/current BL33 identity
13. build board-correct persistent install image and RAM-recovery artifacts required by the supported recovery contract
14. publish artifacts, SHA256 and machine-readable provenance for that exact commit
```

The fast BL2 and TEST63 BL33 are a matched pair. A build which packages a preloader that the compiled UrsusBoot does not accept by SHA is invalid even if both pieces independently compile.

### MD and MF parity requirement

TEST63 is not considered a complete common-line candidate while MF remains an external side build.

For MF, the standalone repository must gain the missing persistent/recovery lineage needed by its own self-contained policy. Proven MF donor/recovery inputs currently sourced from MedveFlasher-era work must be imported with explicit provenance into `airoha-ursusboot` (or otherwise made a first-class pinned input owned by that repository) rather than cloned from MedveFlasher during an ordinary release build.

The end state is:

```text
xg040-md -> standalone persistent + recovery build PASS
xg040-mf -> standalone persistent + recovery build PASS
same airoha-ursusboot commit -> both families
```

Board-specific configs, FIP/container lineage and hashes remain separate. "Parity" means one ownership/build contract, not pretending AN7581 and AN7583 have identical boot artifacts.

### Required standalone CI before TEST63 can be pinned by UrsusFlasher

`airoha-ursusboot` CI must be extended beyond `scripts/qa.sh` to produce an exact build proof for the target families. Minimum acceptance:

- standalone QA job remains;
- target build job(s) compile MD and MF from the exact commit;
- toolchain/OpenWrt/ATF source identity is pinned and recorded;
- fast-BL2 patch persistence is verified after the actual compile preparation path;
- preloader/BL2 hashes compiled into each TEST63 binary are verified against the packaged family preloader;
- TEST63 build identity is checked in the raw binary and packaged FIP/runtime;
- Fudan markers/driver contract are explicitly asserted rather than inherited only by assumption;
- FIP/current-BL33 and boot-area boundaries are checked;
- artifacts and SHA256/provenance are uploaded per family;
- CI status remains BUILD/QA evidence only, never HW PASS.

### UrsusFlasher pin and kit contract

Once an exact `airoha-ursusboot` commit has passed the required standalone build CI, UrsusFlasher pins **that exact commit**, not `main`, `latest`, a branch tip, or "latest successful run".

The kit build must prove at least:

```text
pinned UrsusBoot repository = Medvedolog/airoha-ursusboot
pinned UrsusBoot commit     = exact full SHA
MD artifact provenance     = same exact SHA
MF artifact provenance     = same exact SHA
artifact hashes            = match standalone provenance
TEST63 identity            = present
family preloader pair      = accepted by that family's compiled TEST63
UrsusFlasher host/runtime  = current pinned flasher commit
production OpenWrt payload = pinned by existing firmware manifest
```

The resulting operator ZIP is built by UrsusFlasher, but the UrsusBoot bytes inside it originate from the pinned standalone commit. Rebuilding the same kit must never silently substitute another UrsusBoot commit.

### Relationship to Vanilla

This ownership change concerns the **UrsusBoot product line**. It does not redefine Vanilla U-Boot as UrsusBoot and does not move Ursus-specific Web/API code into the final Vanilla bootloader. Vanilla remains a separate final boot-chain product track unless a later explicit decision moves its own source/build ownership elsewhere.

UrsusFlasher may package both UrsusBoot recovery/install artifacts and separate Vanilla/OpenWrt production artifacts, but their provenance must remain distinct.

### Immediate engineering sequence

```text
1. Stop treating UrsusFlasher-local TEST62 build machinery as the future canonical UrsusBoot source line.
2. Port the proven TEST62/fast-BL2/MD+MF firmware work that belongs to the bootloader into Medvedolog/airoha-ursusboot.
3. Reconcile board-profiles.json with the build path actually used by build.sh/CI.
4. Promote MF from raw/MF2-RAM-only packaging to a self-contained persistent + recovery lineage with explicit provenance.
5. Move/add fast-BL2 build + preloader wrapping + exact hash pin/generation into the standalone TEST63 build contract.
6. Add MD/MF target-build CI in airoha-ursusboot; keep existing offline QA as a separate evidence level.
7. Build TEST63 from one exact standalone commit and publish per-family artifacts/provenance.
8. Add/update the UrsusFlasher manifest so the operator kit pins that exact standalone commit and exact artifact hashes.
9. Build/verify the canonical UrsusFlasher kit from that pin.
10. Only then perform the next full hardware run from Nokia STOCK; CI PASS must not be reported as HW PASS.
```

This section supersedes older handoff statements only where they imply that UrsusBoot firmware source/build ownership remains inside `airoha-router-ursusflasher`. Existing operator-safety, backup/readback, one meaningful `y/N`, identity-preservation and CI-vs-HW rules remain in force.


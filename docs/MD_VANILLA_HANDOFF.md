# MD Vanilla handoff — pregnant initramfs / EXPERT item 4

**Дата:** 2026-09-17  
**Ветка:** `feature/ursusboot-modular-airoha`  
**HEAD перед этой редакцией handoff:** `a9e3036451ec778fb6567232dd0e26622645580b`  
**Нормативное ТЗ:** `docs/UrsusBoot_UrsusFlasher_TZ_RU_v5.45_VANILLA_INITRAMFS.md`

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

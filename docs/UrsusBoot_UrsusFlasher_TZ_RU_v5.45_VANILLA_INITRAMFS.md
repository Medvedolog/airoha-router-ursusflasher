# UrsusBoot / UrsusFlasher — техническое задание
## Редакция 5.45 — Vanilla через автономный OpenWrt initramfs

**Дата редакции:** 2026-09-17  
**Ветка:** `feature/ursusboot-modular-airoha`  
**Базовый HEAD до этой редакции:** `48d1bc3e8a5e34a5b012acab4bca2df00a92a7b2`  
**Статус:** authoritative delta для Vanilla item 4. В части Vanilla transition/install path эта редакция имеет приоритет над v5.39 и v5.44. Определение Vanilla из v5.41 сохраняется. Persistent UrsusBoot, MF persistent и XG140 native/persistent требования не изменяются.

## 1. Архитектурное решение

Для режима **Vanilla OpenWrt** переходной UrsusBoot больше не является обязательной install-средой.

Нормативный путь:

```text
Nokia stock
  -> verified full backup
  -> stock SLOT2 / secondary staging
  -> stock tcboot bootm
  -> OpenWrt Linux initramfs installer
  -> автономная migration из RAM
  -> canonical OpenWrt UBI
  -> Vanilla BL2/BL31/U-Boot + OpenWrt
```

Переходной initramfs является одноразовым installer appliance. Он может содержать UrsusFlasher-specific scripts, manifest, status service и recovery helpers, но не остаётся в конечном persistent boot chain.

Конечный Vanilla U-Boot строится по официальному OpenWrt board contract и для XG-040G-MD может содержать только необходимые board/hardware patches, включая Fudan/FMSH SPI-NAND support. UrsusBoot WebFailsafe, Ursus API, TRANSITION/PERSISTENT identity и иная Ursus-specific persistent functionality в конечном U-Boot запрещены.

## 2. Почему Vanilla item 4 переносится в Linux initramfs

TRANSITION2 доказал полезные аппаратные факты, но также показал ненужную сложность использования U-Boot/lwIP как одноразовой migration среды после stock tcboot.

На XG-040G-MD аппаратно подтверждены:

```text
PASS stock tcboot -> SLOT2 -> Linux-compatible payload handoff
PASS fixed transition MAC before Ethernet probe
PASS RX LAN -> switch/GDM/QDMA -> CPU
PASS QDMA consumption/completion of TX descriptor
PASS Fudan FM25G02B detection
```

Host-visible U-Boot Web path не является blocker Vanilla. OpenWrt Linux используется как штатная среда для Ethernet, MTD/UBI, SSH, service supervision и migration scripts.

TRANSITION2 сохраняется как diagnostic/R&D линия, но дальнейшая switch/lwIP normalization не требуется для item 4.

## 3. Pregnant initramfs contract

Vanilla transition payload должен быть самодостаточным. В нём находятся:

```text
OpenWrt kernel + initramfs
board-specific DTB
canonical Vanilla sysupgrade artifact
Vanilla BL31/U-Boot FIP
BL2/preloader, если требуется final layout
Fudan/FMSH hardware support provenance
migration/autoflash scripts
identity restore data prepared from verified device backup
manifest + SHA256/size/provenance
ursusstockslot recovery helper
status/log service for UrsusFlasher monitoring
SSH
```

После загрузки initramfs для самой migration не требуется повторно передавать production firmware по сети.

Сеть после reboot является control/telemetry plane, а не частью critical write-path.

## 4. Частичный перенос MedveFlasher в EXPERT item 4

Из `Medvedolog/nokia-router-medveflasher` адаптировать:

```text
stock -> Linux bootm transition contract
самодостаточный transition bundle
автономный stage2/autoflash service
UBI repartition/migration mechanics
identity preservation/restore mechanics
SSH discovery/monitoring/reconnect
production reboot detection
transition recovery shell on failure
stage status/log semantics
```

Не переносить как обязательный UX:

```text
codewords
длинные подтверждающие фразы
несколько последовательных destructive confirmations
ручной запуск каждой стадии
ручной выбор mtd/offsets при normal path
```

UrsusFlasher сохраняет собственный `console_ui.py` contract:

```text
ASCII Ursus bear
amber/sand/ok/bad 24-bit ANSI palette
[ШАГ]/[STEP]
[ГОТОВО]/[READY]/[PASS]
[ЖДУ]/[WAIT]
[ВНИМАНИЕ]/[WARNING]
[ОШИБКА]/[ERROR]
```

MedveFlasher приносит proven mechanics; UrsusFlasher сохраняет свой интерфейс, terminology, board profiles, journal и readback standards.

## 5. Минимум gates — обязательный UX contract

Нормальный Vanilla install использует **одно meaningful `y/N`** после полного automatic preflight summary.

Это одно подтверждение разрешает всю заранее описанную transaction:

```text
write verified SLOT2 transition payload
-> readback
-> selector -> SLOT2
-> selector readback
-> reboot
-> autonomous initramfs stage2
-> canonical UBI migration
-> final artifacts write
-> BL2 LAST
-> final readback
-> production reboot
```

После reboot дополнительных confirmations нет.

Запрещены:

```text
CONFIRM FORMAT AND FLASH
YES I UNDERSTAND
повторное y/N перед каждым erase/write
отдельное подтверждение selector/rollback внутри уже подтверждённой transaction
```

Все остальные safety gates автоматические: board/profile, backup validity, geometry, hashes, stock slot readback, artifact provenance, NAND preflight, identity availability, rollback evidence и final readback.

## 6. Stage 1 — stock side

До единственного `y/N` UrsusFlasher обязан автоматически доказать:

```text
supported board/profile
verified full stock backup
required RI/BOSA/MAC/serial/GPON identity extraction where applicable
resolved stock A/B layout
resolved secondary staging span
pregnant initramfs structural validation
embedded production artifact SHA256/provenance
candidate SLOT2 construction
transport preflight
rollback path availability
```

После `y`:

```text
write SLOT2 candidate
-> full/readback SHA verification
-> only then selector -> SLOT2
-> selector readback
-> reboot
```

SLOT1/master остаётся untouched до начала destructive final migration в initramfs.

## 7. Stage 2 — автономная migration

Initramfs сам запускает migration service. Host не отправляет следующую destructive-команду на каждой стадии.

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

`/tmp` — только telemetry:

```text
/tmp/ursus-install/status.json
/tmp/ursus-install/install.log
```

Минимальные live fields:

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

Потеря SSH, закрытие UrsusFlasher или временная потеря Ethernet не останавливают уже начатый stage2 и не вызывают blind retry write.

## 8. Migration state и первый boot на virgin stock

Ключевое правило: на virgin stock до canonical OpenWrt UBI **может законно не существовать никакого persistent OpenWrt migration marker**.

Текущие MD `ubootenv`/`ubootenv2` являются UBI volumes. Следовательно, `fw_setenv` нельзя считать гарантированно доступным pre-UBI carrier на первом boot installer.

`MIGRATION_OK` допустим как live/preflight state, но **не является обязательным persistent marker** на untouched stock.

Persistent states после появления подходящего NAND-backed carrier:

```text
PROD_WRITING
PROD_VERIFIED
BOOT_CONFIRMED
```

После создания canonical UBI `ubootenv`/`ubootenv2` используются как штатный environment carrier; запись state требует readback через `fw_printenv`/эквивалент.

Не разрешается выбирать pre-UBI marker location в stock NAND по предположению. Если будет введён отдельный carrier вне destructive span, он требует отдельного geometry/readback/HW acceptance.

## 9. SSH contract

После reboot UrsusFlasher подключается к initramfs по SSH для:

```text
status polling
stream/tail install log
progress rendering
reconnect after transient link loss
pre-destructive recovery action when rollback доказан
final production detection/verification
```

SSH не является обязательным transport production image и не является trigger каждой NAND операции.

Если SSH исчезает:

```text
migration continues locally
host reconnects
host re-reads live status and persistent state when available
host never blindly repeats a write command
```

Если initramfs остаётся доступен после `FAILED`, recovery shell сохраняется.

## 10. `ursusstockslot` переносится в initramfs

В pregnant initramfs присутствует Linux-реализация:

```text
ursusstockslot status
ursusstockslot master
ursusstockslot slave
```

Семантика:

```text
status  -> read-only selector decode
master  -> active=0 only
slave   -> active=1 only
```

Инвариант изменения selector сохраняется буквально:

```python
struct.pack_into("<I", out, 0, target)
if out[4:] != flag[4:]:
    raise RuntimeError("activation flag changed fields other than active")
```

Utility обязана:

```text
resolve partition by stock name/profile, not hardcoded mtd number
verify size/erase geometry
read full primary flag eraseblock
modify only approved active field
preserve every other byte
write full buffered block
read back full block
verify target active
verify every non-active byte unchanged
```

`flagback` вручную не синхронизировать; reconciliation принадлежит stock tcboot.

Success marker:

```text
URSUS_STOCKSLOT_DONE target=master active=0 readback=PASS next=RESET
```

### Guard живёт внутри utility

`ursusstockslot master` сама вычисляет rollback safety. Caller/UI не является trust boundary.

Public/normal path не имеет `--force` обхода этого guard.

## 11. No-UART rollback — трёхсостоянийный контракт

`rollback_allowed` — derived result, не trusted boolean из `/tmp/status.json`.

### 11.1. Persistent marker явно говорит, что destructive phase началась

Если доступен marker:

```text
PROD_WRITING
PROD_VERIFIED
BOOT_CONFIRMED
```

то master rollback запрещён безусловно:

```text
rollback_allowed=false
ursusstockslot master -> REFUSED
```

### 11.2. Marker отсутствует, но stock layout положительно доказан pristine

Это нормальный first-boot case: installer загрузился из SLOT2, preflight упал, OpenWrt UBI environment ещё не существовал и persistent marker никогда не записывался.

Rollback разрешён только если NAND probe одновременно доказывает:

```text
expected stock partition/layout geometry matches
nsb_master matches verified stock backup/evidence
all critical stock regions migration могла бы затронуть match verified backup/evidence
stock UBI/rootfs/layout signatures match expected stock state
no canonical OpenWrt UBI/layout present
no partially converted UBI/layout present
no destructive-write evidence present
```

Тогда:

```text
marker = absent
stock_evidence = PRISTINE
rollback_allowed=true
ursusstockslot master -> ALLOWED
```

Authority здесь — не отсутствие marker, а положительный NAND proof.

### 11.3. Marker отсутствует/повреждён и pristine proof не проходит

При любом incomplete/mismatch/unknown:

```text
rollback_allowed=false
URSUS_STOCKSLOT_REFUSED target=master reason=ROLLBACK_UNSAFE
```

В частности, reset/power loss во время первой destructive operation до появления persistent marker должен оставить изменившиеся eraseblocks/UBI signatures/hashes, поэтому pristine proof обязан упасть и rollback должен быть REFUSED.

## 12. Preflight failure escape hatch

Если initramfs загрузился на untouched stock и preflight упал до первой destructive operation, marker может никогда не существовать.

Если `stock_evidence=PRISTINE`, preferred automatic recovery:

```text
ursusstockslot status
-> ursusstockslot master
-> full selector readback PASS
-> sync
-> reboot
-> stock Nokia SLOT1
```

Если auto rollback не сработал, UrsusFlasher через SSH выполняет тот же guarded contract.

Внутри уже подтверждённой Vanilla transaction второго user confirmation для fail-safe rollback не требуется.

После начала destructive migration автоматический master rollback запрещён.

## 13. Final Vanilla transaction

После успешного initramfs preflight migration выполняется без дополнительных prompts:

```text
first destructive operation begins
-> stock evidence stops being PRISTINE
-> prepare canonical OpenWrt layout
-> create/format canonical UBI
-> create/restore ubootenv/ubootenv2
-> persistent state -> PROD_WRITING + readback PASS
-> create required volumes
-> restore/preserve board identity
-> write Vanilla BL31/U-Boot FIP
-> write canonical OpenWrt production/sysupgrade content
-> verify critical data
-> write BL2/preloader LAST
-> final full/readback verification
-> persistent state -> PROD_VERIFIED
-> reboot
-> verify production boot
-> persistent state -> BOOT_CONFIRMED
```

Важно: окно между первой destructive operation и появлением нового environment защищается не отсутствующим marker, а тем, что stock evidence уже не может пройти как PRISTINE.

После начала final write запрещены automatic backend switching и blind retries другим writer implementation.

## 14. Hardware acceptance

Для XG-040G-MD acceptance включает отдельно:

```text
stock -> SLOT2 pregnant initramfs boot PASS
initramfs Ethernet + SSH PASS
status.json/log monitoring PASS

virgin stock -> forced preflight FAIL
persistent marker never existed
stock evidence = PRISTINE
ursusstockslot master -> ALLOWED
selector readback PASS
reboot -> untouched stock SLOT1 PASS

explicit PROD_WRITING present -> master REFUSED PASS

reset/power-loss during first destructive operation before marker exists
marker absent
stock evidence != PRISTINE
master REFUSED PASS

marker missing/corrupt after partial/converted layout -> master REFUSED PASS
stock evidence incomplete/mismatch -> master REFUSED PASS

autonomous stage2 without host commands PASS
canonical UBI migration PASS
identity restore PASS
Vanilla FIP/U-Boot PASS
Fudan/FM25G02B boot support PASS
BL2 LAST + readback PASS
PROD_VERIFIED/BOOT_CONFIRMED transitions PASS
cold boot to production OpenWrt PASS
subsequent normal OpenWrt sysupgrade PASS
Ursus-specific persistent code ABSENT
```

Без virgin-stock preflight-failure test no-UART escape hatch не считается доказанным.

CI/build PASS не заменяет HW acceptance.

## 15. Persistent UrsusBoot не меняется этим решением

Persistent UrsusBoot остаётся отдельным recovery-first продуктом с Web Recovery/UART/Ursus utilities.

Known CLI network ownership problem (`ping`/`wget`/`tftpboot`/`dhcp` против live WebFailsafe lwIP netif) исправляется отдельно и больше не блокирует Vanilla path.

## 16. Immediate engineering sequence

```text
1. Freeze TRANSITION2 network investigation for Vanilla.
2. Import minimal proven MedveFlasher autonomous stage2 mechanics.
3. Build stock-compatible pregnant OpenWrt initramfs/FIT.
4. Port Linux ursusstockslot with byte-preservation/readback invariants and internal guard.
5. Implement stock-evidence probe with PRISTINE / CHANGED / UNKNOWN result.
6. Do not require pre-UBI persistent marker on virgin stock.
7. After canonical UBI exists, implement PROD_WRITING/PROD_VERIFIED/BOOT_CONFIRMED with readback.
8. Add status.json/install.log + SSH monitoring/reconnect through existing console_ui.
9. Preserve one meaningful y/N; no codewords/repeated confirmations.
10. HW-test virgin-stock preflight failure -> marker absent -> PRISTINE -> master rollback -> stock boot.
11. HW-test reset/power-loss during first destructive operation before marker -> PRISTINE must fail -> master REFUSED.
12. Only after both rollback/refusal paths PASS enable full destructive migration.
13. HW-test autonomous migration -> BL2 LAST -> Vanilla production boot.
14. Generalize for MF without copying MD offsets blindly.
```

## 17. Repository/operator rules

- Work only in `feature/ursusboot-modular-airoha` until explicitly instructed otherwise.
- Do not modify `main`; no merge/tag/release without explicit operator command.
- Do not commit device backups, credentials, serial/GPON identity or other device secrets.
- Normal destructive transaction: one meaningful `y/N`, no codewords and no repeated confirmations.
- Prefer automatic evidence/readback over operator ceremony.
- `/tmp` telemetry never authorizes rollback.
- Explicit destructive marker always denies stock master rollback.
- Marker absent + positive PRISTINE stock proof may allow rollback.
- Marker absent + anything other than proven PRISTINE denies rollback.
- `ursusstockslot master` enforces guard internally.
- Never claim CI PASS as HW PASS.
- Preserve Fudan/FMSH hardware support in final MD Vanilla U-Boot provenance.

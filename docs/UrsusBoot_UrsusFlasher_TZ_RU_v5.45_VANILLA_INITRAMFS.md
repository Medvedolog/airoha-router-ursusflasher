# UrsusBoot / UrsusFlasher — техническое задание
## Редакция 5.45 — Vanilla через автономный OpenWrt initramfs

**Дата редакции:** 2026-09-17  
**Ветка:** `feature/ursusboot-modular-airoha`  
**Базовый HEAD до этой редакции:** `48d1bc3e8a5e34a5b012acab4bca2df00a92a7b2`  
**Статус:** authoritative delta для Vanilla item 4. В части Vanilla transition/install path эта редакция имеет приоритет над v5.39 и v5.44. Определение Vanilla из v5.41 сохраняется. Persistent UrsusBoot, MF persistent и XG140 native/persistent требования не изменяются.

> **CURRENT OVERRIDE — 2026-09-23:** для persistent UrsusBoot source/build authority переносится в `Medvedolog/airoha-ursusboot`. TEST63 обязан собираться из его исходников на exact pinned commit. UrsusFlasher остаётся host/orchestrator/kit builder и потребляет pinned TEST63 artifacts/provenance. Нормативные детали — §19. При конфликте по ownership/build provenance §19 имеет приоритет над более ранними разделами.

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


## 18. Payload provenance update — UnameOne Edition 2026-09-16

Для текущего полного Vanilla migration test нормативно разделяются:

```text
transition runtime
    = актуальный OpenWrt initramfs + Ursus/Medve autonomous stage2

production child
    = pinned UnameOne Edition 2026-09-16 UBI sysupgrade
```

Production child является единым source-of-truth для соответствующего профиля и должен переиспользоваться в EXPERT item 1, ONE-CLICK и EXPERT item 4. Метаданные и SHA закреплены в `config/UNAMEONE_2026-09-16_PAYLOADS.json`.

Для item 4 использовать UBI sysupgrade ITB **byte-for-byte**:
- XG-040G-MD: SHA256 `9b1f0899ca4ef610f6d87e8572d369adb420f104bda667556e8a0b5979f066dd`;
- XG-040G-MF: SHA256 `21dcf4c6ca64ea0c5bc3d601e4a8f99a3f002371b873f399f622cbd9223fd1d1`.

Обычные `.bin` из той же пары являются OpenWrt sysupgrade tar, а не factory images.

Автоматическое обновление transient initramfs base до более свежего snapshot не даёт права автоматически заменить production child. Смена pinned production payload требует явного обновления manifest/provenance.

Оператор решил не делать отдельный boot-only intermediate kit: следующий hardware test должен использовать полный autonomous migration path. Это не отменяет automatic preflight, rollback evidence/guard, readback, identity preservation и BL2-LAST contract.

Build implementation должна использовать proven MedveFlasher-style FIT/newc injection либо эквивалентно доказанный механизм. OpenWrt ImageBuilder `make image` не считается источником требуемого initramfs ITB, поскольку текущий CI эксперимент не получил такой artifact.

Первый успешный CI полного builder не является HW PASS. CI PASS объявляется только после проверки exact run exact SHA; hardware status присваивается отдельно по UART/board evidence.
## 19. Source ownership и TEST63 — standalone `airoha-ursusboot` становится main line

### 19.1. Нормативное решение

Для TEST63 и последующих persistent UrsusBoot сборок главным репозиторием является:

`Medvedolog/airoha-ursusboot`.

Нормативная цепочка:

```text
airoha-ursusboot exact commit
  -> MD/MF UrsusBoot source + board/profile policy
  -> family fast BL2/preloader provenance
  -> TEST63 BL33 built against that exact preloader
  -> family FIP/install/recovery artifacts + SHA/provenance

airoha-router-ursusflasher exact commit
  -> exact pin to the airoha-ursusboot commit/artifacts above
  -> operator flow / backup / transport / diagnostics / readback
  -> production OpenWrt payloads
  -> canonical ONECLICK/EXPERT kit
```

Запрещается иметь две независимые main-line реализации UrsusBoot, одну в standalone и вторую внутри UrsusFlasher. Код/фиксы, относящиеся к самому bootloader, переносятся в standalone source tree и становятся частью TEST63 там. UrsusFlasher не должен собирать TEST63 из собственной устаревающей копии исходников или из локального patch stack поверх исторического tarball.

Host-only fixes UrsusFlasher, включая устойчивый polling `/api/status`/fallback diagnostics, остаются в UrsusFlasher и не переносятся в firmware repository без firmware-side причины.

### 19.2. Зафиксированное состояние `airoha-ursusboot` перед TEST63

На момент принятия решения проверен `main`:

`9427623e1974407f1eac12f147a077f848195843`.

Текущий standalone repository уже self-contained для U-Boot source/config/templates/donor inputs, но его build/CI surface пока неполон для TEST63:

| Профиль | Текущее состояние standalone build |
|---|---|
| `xg040-md` / AN7581 | Полный persistent path: `u-boot.TEST61.full.config`, stock boot-area template, MD reference FIP; `build.sh` выдаёт raw BL33, LZMA, current-BL33 FIP, 512 KiB install image и SHA256SUMS. |
| `xg040-mf` / AN7583 | Реальный MF source/config/template присутствуют, но используется `an7583_nokia_xg-040g-mf_MF2_RAM_defconfig`, а `reference_fip=null`; generic `build.sh` имеет raw-build path, но не полный persistent FIP/install contract. |
| `xg140-md` | `config/template/reference_fip=null`; intentionally not buildable и не входит в TEST63 без отдельного решения. |

Дополнительные факты, обязательные для планирования TEST63:

- Fudan/FMSH support для `FM25G01B/FM25G02B` уже присутствует в standalone U-Boot source и должен быть сохранён.
- `cmd/ursusubi.c` в standalone baseline содержит старые MD preloader/128-KiB-BL2 hashes. Новый fast preloader без build-time pin/generation будет корректно отвергнут firmware preflight.
- fast NAND/UBI scan относится к ATF/BL2, а не к BL33. В текущем standalone repository нет complete fast-BL2 build path; он должен стать first-class TEST63 provenance/build input в standalone линии.
- `board-profiles.json` уже содержит fragments и `board_policy_header`, но текущий top-level `build.sh` в основном работает через full config/template/reference FIP/runtime role. Перед TEST63 декларативный profile contract и реально используемый build pipeline должны быть приведены к одному состоянию.

### 19.3. Текущий CI standalone недостаточен для TEST63 BUILD PASS

Текущий `.github/workflows/qa.yml` запускает только:

```text
bash ./scripts/qa.sh
```

Этот QA проверяет structural/source invariants, но **не cross-compile** целевые MD/MF binaries и **не build** ATF/BL2. Поэтому:

```text
QA PASS != BUILD PASS != HW PASS
```

Для TEST63 standalone CI обязан получить отдельный target build layer.

Минимальные требования к CI:

1. QA остаётся отдельным job/evidence layer.
2. MD и MF строятся из одного exact standalone commit.
3. Toolchain/OpenWrt/ATF provenance полностью pinned и записывается в artifact metadata.
4. Fast-scan BL2 patch применяется внутри реального prepare/compile path и его присутствие доказывается после compile.
5. Raw BL2 оборачивается в board-correct UBI preloader representation.
6. Перед компиляцией TEST63 вычисляются SHA256 packaged preloader и полного 128 KiB BL2 candidate; именно они pin/generate-ятся в соответствующий family runtime.
7. Готовый BL33 проверяется на наличие новых hashes и отсутствие superseded hashes.
8. Готовый BL33 проверяется на TEST63 identity, board/family identity и Fudan/FM25G01B/FM25G02B support там, где это часть поддерживаемой hardware line.
9. Current BL33 byte-for-byte проверяется внутри repacked FIP/runtime artifact.
10. FIP/boot-area boundary checks обязательны.
11. MD/MF artifacts, SHA256 и machine-readable provenance публикуются CI.
12. CI никогда не ставит HW PASS самостоятельно.

### 19.4. TEST63 build order

Для каждой семьи build order обязателен и не может быть переставлен так, чтобы BL33 собирался до неизвестного ему preloader:

```text
family profile
 -> pinned ATF/OpenWrt/toolchain inputs
 -> build patched fast BL2
 -> verify patch survived actual Build/Prepare + compile
 -> wrap BL2 as UBI preloader FIP/container
 -> compute preloader SHA256
 -> construct complete 128 KiB BL2 candidate and compute SHA256
 -> pin/generate both digests into UrsusBoot source/config for this family
 -> build TEST63 BL33 from airoha-ursusboot source
 -> binary contract checks
 -> LZMA1EXT/no-EOPM
 -> board-correct donor FIP repack
 -> install/recovery artifacts
 -> SHA256/provenance
```

Fast BL2 + TEST63 BL33 являются одной совместимой парой. Packaging пары, где TEST63 не принимает shipped preloader по своим compiled-in digests, является build failure до любого hardware test.

### 19.5. MF обязан стать first-class standalone target

Common TEST63 kit не должен зависеть от того, что MF runtime/recovery собирается как внешнее дополнение в UrsusFlasher CI.

До pinning TEST63 в UrsusFlasher standalone repository должен иметь для MF:

- persistent-capable profile/config;
- board-correct donor/reference FIP lineage;
- RAM/UART recovery lineage, если она входит в supported recovery contract;
- family fast BL2/preloader build;
- exact preloader/BL2 digest pin in MF TEST63;
- artifact/provenance output, сопоставимый по уровню доказательства с MD.

Проверенные MF donor/recovery inputs из MedveFlasher-era разработки должны быть перенесены/зафиксированы в standalone с provenance так, чтобы обычная TEST63 release build не зависела от live checkout MedveFlasher или UrsusFlasher. Это следует действующей standalone policy: normal build не должен получать bootloader source/templates/donors из другого проекта молча во время сборки.

MD и MF остаются разными hardware/container profiles; требование parity означает общий ownership/build/evidence contract, а не одинаковые bytes или offsets.

### 19.6. UrsusFlasher pin contract

UrsusFlasher может собрать canonical operator kit только после successful standalone target build exact TEST63 commit.

Pin должен однозначно задавать:

- repository `Medvedolog/airoha-ursusboot`;
- full commit SHA;
- exact MD artifact/provenance;
- exact MF artifact/provenance;
- hashes всех UrsusBoot/preloader/recovery payloads;
- при необходимости exact standalone CI run/artifact identity.

Floating inputs запрещены:

```text
main
latest
latest successful
branch tip
newest artifact
```

не являются допустимым release/test pin.

При сборке kit UrsusFlasher обязан доказать, что MD и MF payloads относятся к одному pinned standalone commit и совпадают по hash/provenance. Если artifact отсутствует, SHA не совпадает или family/runtime identity не соответствует pin — kit build должен завершиться fail-closed.

### 19.7. Граница с Vanilla

`airoha-ursusboot` становится main line для **UrsusBoot**, а не для final Vanilla U-Boot по определению.

Vanilla OpenWrt boot chain остаётся отдельным продуктом без persistent Ursus Web/API functionality. UrsusFlasher может упаковывать в одном operator kit:

- pinned standalone TEST63 recovery/install payloads;
- отдельно собранные Vanilla/OpenWrt production payloads;

но их source provenance и acceptance evidence не смешиваются.

### 19.8. Immediate sequence

```text
1. Принять standalone airoha-ursusboot как единственный future source-of-truth для UrsusBoot.
2. Перенести туда proven TEST62-era firmware changes, нужные TEST63, без сохранения UrsusFlasher как второй firmware source tree.
3. Перенести fast-BL2 build/provenance и exact preloader hash pinning в standalone TEST63 pipeline.
4. Свести declared board-profile contract с реально вызываемыми build steps.
5. Завершить MF persistent/recovery lineage внутри standalone.
6. Добавить standalone CI target builds MD+MF поверх существующего QA.
7. Собрать TEST63 из одного exact standalone commit и получить per-family artifacts/provenance.
8. В UrsusFlasher добавить exact commit/artifact pin на этот TEST63 build.
9. Собрать canonical ONECLICK/EXPERT kit и прогнать kit verifier.
10. Следующий meaningful hardware acceptance делать с Nokia STOCK с нуля; BUILD/CI PASS не выдавать за HW PASS.
```

Этот раздел изменяет ownership/build provenance persistent UrsusBoot и имеет приоритет над прежними формулировками, где его future main-line source предполагался внутри `airoha-router-ursusflasher`. Safety/readback/identity/one-y-N и HW-evidence требования настоящего ТЗ сохраняются.



## 20. UrsusFlasher как модульный Airoha orchestration layer

### 20.1. Назначение модульности UrsusFlasher

Модульность `airoha-router-ursusflasher` является отдельным слоем от firmware modularity `airoha-ursusboot`.

Нормативное разделение:

```text
airoha-ursusboot
  = common UrsusBoot firmware source
  = SoC/board fragments and board policy
  = family firmware build
  = TEST63+ artifacts/provenance

airoha-router-ursusflasher
  = common host/orchestration core
  = device identification
  = operation/capability resolution
  = transports and physical writers
  = backup/restore/readback
  = exact firmware pin and payload-role resolution
  = operator UI and canonical kit packaging
```

Цель: добавление следующего Airoha-устройства не должно требовать копирования всей host-логики или создания отдельной почти полной реализации UrsusFlasher.

### 20.2. Canonical board profile ID

Для одного физического профиля должен существовать один canonical profile ID, общий между firmware и host проектами, например:

```text
xg040-md
xg040-mf
xg140-md
```

Строки вида `md`, `mf`, marketing/model aliases, OpenWrt compatible и legacy filenames могут использоваться только как detection aliases/compatibility keys. После определения устройства внутренний dispatch должен опираться на canonical profile ID.

`BOARD_PROFILES.json` UrsusFlasher должен явно связывать host profile с `airoha-ursusboot` profile через поле уровня `ursusboot_profile` или его последующий schema-equivalent. Exact TEST63 pin обязан подтверждать совпадение profile identity в artifact provenance.

### 20.3. Profile-driven operation contract

High-level orchestration не должна выбирать реализацию по цепочкам вида:

```python
if family == "mf":
    ...
elif family == "md":
    ...
```

как постоянной архитектуре.

Нормативная модель:

```text
detected device
 -> canonical board profile
 -> requested operation
 -> capability/write-policy check
 -> backend resolution
 -> payload-role resolution
 -> automatic preflight
 -> one meaningful y/N if destructive
 -> backend execution
 -> required readback/evidence
```

Профиль должен уметь описать как минимум:

- model/SoC/compatible detection aliases;
- flash geometry и board-specific layout;
- доступные transports;
- supported operations;
- operation backend key;
- write authorization/policy;
- backup/preflight requirements;
- readback/verification requirements;
- payload roles;
- network/recovery characteristics;
- hardware/CI evidence state.

### 20.4. Operation/backend registry

Общие пользовательские действия должны иметь стабильные operation keys, не привязанные к названию платы, например:

```text
backup
validate_backup
install_ursusboot
recover_ursusboot
install_openwrt
stock_to_ubi
restore_stock
restore_factory_bootarea
switch_stock_slot
diagnostics
```

Для каждой операции профиль выбирает backend. Концептуально:

```json
"operations": {
  "install_ursusboot": {
    "backend": "airoha_stock_persistent_fip",
    "requires": ["verified_backup"],
    "readback": "full_boot_area"
  }
}
```

Формат schema может эволюционировать, но смысл обязателен: high-level menu/action code спрашивает у профиля, **какой backend выполнить**, а не содержит знание о каждой модели.

### 20.5. Где отдельный Python backend допустим

Data-driven архитектура не означает, что вся физическая механика обязана помещаться в JSON.

Отдельный backend/plugin является правильным решением, когда реально различаются:

- BootROM/UART transport;
- Nokia stock A/B selector format;
- boot-area/FIP container mechanics;
- raw MTD writer;
- UBI migration topology;
- identity/RI/BOSA preservation;
- device-derived candidate construction;
- recovery bootstrap;
- board-specific destructive transaction.

Запрещённый анти-паттерн — создавать для каждой новой модели полный набор дублирующих orchestration/UI/menu модулей только потому, что модель новая. Board-specific код должен быть локализован на границе backend/profile, а общий workflow оставаться общим.

### 20.6. Текущее состояние и migration debt

В UrsusFlasher уже существуют необходимые основы:

- `config/BOARD_PROFILES.json`;
- `ursusflasher/src/board_profiles.py`;
- `config/FIRMWARE_BUNDLES.json`;
- `config/FIRMWARE_CAPABILITIES.json`;
- общий `device_state.py`;
- multi-model dispatch в `one_key_multi` / `expert_multi.py`;
- profile-specific write policy/evidence.

Однако текущая реализация ещё содержит прямые MD/MF/XG140 ветвления и board-named orchestration modules. Это допустимый переходный долг, но не целевая архитектура.

После стабилизации TEST63 новые изменения должны по возможности двигать dispatch в сторону:

```text
profile -> capability -> backend -> payload role
```

а не увеличивать количество `if family == ...` в high-level orchestration.

### 20.7. Связь с exact TEST63 pin

UrsusFlasher не строит будущий UrsusBoot самостоятельно. Для операции, использующей UrsusBoot, profile/backend resolver должен получить payload из exact pinned `Medvedolog/airoha-ursusboot` artifact set.

Для каждого supported profile kit verifier обязан доказать:

```text
canonical profile ID matches
airoha-ursusboot repository matches
full pinned commit SHA matches
artifact provenance matches that SHA
payload role exists for this profile
payload SHA256/size match provenance
board/family identity matches
required recovery/persistent pair is internally consistent
```

Нельзя разрешать fallback на payload соседней семьи только потому, что SoC совпадает.

### 20.8. Требование к портированию новых Airoha устройств

Добавление нового Airoha router profile в нормальном случае должно состоять преимущественно из:

```text
identity/detection profile
SoC + flash/layout data
supported operation map
backend selections
payload roles and exact firmware provenance
board-specific safety/readback policy
hardware evidence state
```

Новый hardware profile не получает write-capable operation автоматически. Пока geometry, backend и evidence не доказаны, соответствующие destructive actions остаются fail-closed/read-only.

Совпадение SoC само по себе не является разрешением использовать offsets, FIP lineage, selector mechanics или destructive backend другой платы.

### 20.9. Immediate refactor direction

После получения первого standalone TEST63 BUILD PASS приоритетный рефактор UrsusFlasher:

```text
1. Нормализовать canonical profile IDs между airoha-ursusboot и UrsusFlasher.
2. Добавить operation/backend mapping в BOARD_PROFILES schema либо отдельный profile-owned registry.
3. Ввести общий backend resolver.
4. Перевести install/recover/restore/stock-to-UBI dispatch с family conditionals на backend keys.
5. Сохранить hardware-specific writer implementations отдельными backend modules без копирования UI/orchestration.
6. Перевести payload lookup на profile + semantic role + exact standalone provenance.
7. Добавить QA, запрещающий неизвестный backend, cross-family payload fallback и write action без явного profile authorization.
8. Новые Airoha boards добавлять через этот contract, а существующие MD/MF/XG140 переносить постепенно без рискованного big-bang rewrite.
```

Модульность не отменяет существующие safety contracts: automatic preflight, один meaningful `y/N`, BL2-LAST где требуется, полный readback, identity preservation и строгая граница `CI PASS != HW PASS` сохраняются.

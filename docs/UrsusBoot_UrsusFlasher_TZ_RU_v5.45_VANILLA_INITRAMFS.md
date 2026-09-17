# UrsusBoot / UrsusFlasher — техническое задание
## Редакция 5.45 — Vanilla через автономный OpenWrt initramfs

**Дата редакции:** 2026-09-17  
**Ветка:** `feature/ursusboot-modular-airoha`  
**Базовый HEAD до этого документа:** `6980d8da05595f46040a9bac2ba55b0bda09926a`  
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

При этом host-visible Web path остаётся зависимым от унаследованного после tcboot network/switch state. Это не требуется решать для Vanilla installation path, потому что OpenWrt Linux уже является штатной средой для Ethernet, MTD/UBI, SSH, service supervision и migration scripts.

TRANSITION2 сохраняется как исследовательская/diagnostic линия и не удаляется, но дальнейшая switch/lwIP normalization не является blocker для Vanilla item 4.

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
```

После загрузки initramfs для самой migration не требуется повторно передавать production firmware по сети.

Сеть после reboot является control/telemetry plane, а не частью critical write-path.

## 4. Частичный перенос MedveFlasher в EXPERT item 4

Из `Medvedolog/nokia-router-medveflasher` в Vanilla item 4 переносится проверенная модель перехода, но не копируется его пользовательская ceremony целиком.

Переиспользовать/адаптировать:

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
Ursus amber/sand/ok/bad 24-bit ANSI palette
[ШАГ]/[STEP]
[ГОТОВО]/[READY]/[PASS]
[ЖДУ]/[WAIT]
[ВНИМАНИЕ]/[WARNING]
[ОШИБКА]/[ERROR]
```

MedveFlasher приносит proven mechanics; UrsusFlasher сохраняет свой интерфейс, терминологию, board profiles, journal и safety/readback standards.

## 5. Минимум gates — обязательный UX contract

Нормальный Vanilla install использует **одно meaningful `y/N`** после полного automatic preflight summary.

Это одно подтверждение разрешает всю заранее описанную transaction:

```text
write verified SLOT2 transition payload
-> readback
-> switch selector to SLOT2
-> reboot
-> autonomous initramfs stage2
-> canonical UBI migration
-> final artifacts write
-> BL2 LAST
-> readback
-> reboot to production OpenWrt
```

После reboot не запрашиваются дополнительные confirmations.

Запрещены:

```text
CONFIRM FORMAT AND FLASH
YES I UNDERSTAND
повторное y/N перед каждым erase/write
отдельное подтверждение selector после уже подтверждённой transaction
```

Все остальные safety gates — автоматические: board identity, backup validity, geometry, hashes, stock slot readback, artifact provenance, NAND preflight, identity availability, persistent migration state, rollback evidence и final readback.

Если automatic preflight не проходит, операция останавливается с конкретной причиной без предложения оператору вручную «продавить» normal path.

## 6. Stage 1 — stock side

До единственного `y/N` UrsusFlasher обязан автоматически выполнить/доказать:

```text
supported board/profile
verified full stock backup
required RI/BOSA/MAC/serial/GPON identity extraction where applicable
resolved stock A/B layout
resolved secondary staging span
pregnant initramfs bundle structural validation
embedded production artifact SHA256/provenance
candidate SLOT2 construction
transport preflight
rollback path availability
```

После `y`:

```text
write SLOT2 candidate
-> full/readback SHA verification
-> only then switch primary selector to SLOT2
-> selector readback
-> reboot
```

SLOT1/master должен оставаться untouched и загрузочным до начала destructive final migration в initramfs.

## 7. Stage 2 — автономная migration

Initramfs сам запускает migration service. Host не должен отправлять по SSH следующую destructive-команду на каждой стадии.

Пример state machine:

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

`/tmp` state является только live telemetry и **не является источником истины для rollback safety**:

```text
/tmp/ursus-install/status.json
/tmp/ursus-install/install.log
```

Минимальные live status fields:

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

Критический migration state обязан иметь persistent NAND-backed representation, устанавливаемый **до первого destructive write**. Нормативные состояния:

```text
MIGRATION_OK
PROD_WRITING
PROD_VERIFIED
BOOT_CONFIRMED
```

Linux пишет persistent state через штатный environment interface (`fw_setenv`/эквивалент), а readback выполняется через `fw_printenv`/эквивалент до продолжения.

Текущие MD OpenWrt `ubootenv`/`ubootenv2` являются UBI volumes, поэтому они не могут быть единственным доказательством safety во время операции, которая сама может переформатировать UBI. Правило fail-safe:

```text
persistent marker missing/corrupt/inconsistent -> rollback_allowed=false
```

После создания нового canonical UBI environment volumes должны быть восстановлены/созданы и persistent marker должен быть записан туда повторно до перехода к последующим destructive стадиям. Никакое отсутствие marker после reset не трактуется как «migration ещё не началась».

Потеря SSH, закрытие UrsusFlasher на ПК или временная потеря Ethernet после `PROD_WRITING` не должны останавливать migration service и не должны вызывать повторный write после reconnect.

## 8. SSH contract

После reboot UrsusFlasher ищет initramfs и подключается по SSH для:

```text
status polling
stream/tail install log
progress rendering
reconnect after transient link loss
pre-destructive recovery action when доказан rollback contract
final production detection/verification
```

SSH не является обязательным транспортом production image во время normal autonomous stage2 и не является clock/trigger каждой NAND операции.

Если SSH исчезает:

```text
migration continues locally
host reconnects
host re-reads live status + persistent state
host never blindly repeats a write command
```

Если initramfs остаётся доступен после `FAILED`, recovery shell сохраняется для диагностики.

## 9. `ursusstockslot` переносится в initramfs

В pregnant initramfs должна присутствовать Linux-реализация командного контракта:

```text
ursusstockslot status
ursusstockslot master
ursusstockslot slave
```

Семантика сохраняется от hardware-proven U-Boot implementation:

```text
status  -> read-only decode current stock selector
master  -> set only active=0
slave   -> set only active=1
```

Инвариант изменения selector переносится буквально:

```python
struct.pack_into("<I", out, 0, target)
if out[4:] != flag[4:]:
    raise RuntimeError("activation flag changed fields other than active")
```

Утилита не должна считать `mtd8` универсальным API. Она обязана:

```text
resolve partition by expected stock name/profile
verify size/erase geometry
read the full primary flag eraseblock
preserve every byte except approved active field
write the full buffered block
read back the full block
verify active target
verify all non-active bytes unchanged
```

`flagback` вручную не синхронизировать; stock tcboot сохраняет ownership reconciliation.

Совместимый success marker:

```text
URSUS_STOCKSLOT_DONE target=master active=0 readback=PASS next=RESET
```

В Linux `next=RESET` означает следующий reboot; host выполняет `sync` и штатный/forced reboot (`reboot -f` при необходимости), а не U-Boot command `reset`.

### Guard обязан жить внутри утилиты

`ursusstockslot master` не просто скрывается UI при опасном состоянии — сама utility обязана отказать в selector write, если rollback safety не доказана.

Public/normal path не должен иметь `--force` bypass этого guard.

Перед `master` utility сама проверяет persistent migration state и фактическое состояние stock layout. Caller/UrsusFlasher не может отменить эту проверку своим локальным флагом.

## 10. No-UART rollback contract

`rollback_allowed` является **derived result**, а не доверенным boolean из `/tmp/status.json`.

Rollback на stock SLOT1 разрешён только если **одновременно** выполнены оба независимых условия:

```text
A. persistent migration state однозначно показывает pre-destructive состояние
   (например MIGRATION_OK, но не PROD_WRITING/PROD_VERIFIED/BOOT_CONFIRMED)

B. фактический NAND probe доказывает, что stock fallback всё ещё цел:
   expected stock partition/layout geometry matches
   nsb_master соответствует verified stock evidence
   critical stock regions, которые migration могла затронуть, соответствуют verified backup/evidence
   нет признаков partially converted UBI/layout
```

Если A и B расходятся, marker отсутствует, environment повреждён, probe неполон или состояние неоднозначно:

```text
rollback_allowed=false
ursusstockslot master -> REFUSED
```

Таким образом reset/power-loss после начала migration не может восстановить `/tmp` в «безопасное» состояние и вызвать опасный автоматический rollback.

До первого destructive write stage2 обязан выполнить и проверить:

```text
persistent state -> PROD_WRITING
readback -> PASS
sync
only then first destructive NAND operation
```

После final critical readback:

```text
persistent state -> PROD_VERIFIED
```

После доказанного production boot:

```text
persistent state -> BOOT_CONFIRMED
```

Если initramfs booted, но stage2 preflight не прошёл **до `PROD_WRITING`**, и оба rollback proofs PASS, предпочтительное автоматическое восстановление:

```text
ursusstockslot status
-> ursusstockslot master
-> full selector readback PASS
-> sync
-> reboot
-> stock Nokia SLOT1
```

Если автоматический rollback не отработал, UrsusFlasher через SSH выполняет тот же guarded contract. Это действие не требует второго подтверждения внутри уже подтверждённой Vanilla transaction.

Для отдельной ручной EXPERT-команды вне активной transaction selector write может иметь одно обычное `y/N`, но internal rollback guard всё равно обязателен.

После `PROD_WRITING` автоматический возврат на SLOT1 запрещён. Stock rootfs/layout уже может быть частично уничтожен. В этом состоянии recovery policy — остаться в initramfs, показать точную failed stage и выполнять только доказанную repair/retry strategy; UART/BootROM остаётся последним recovery path, но не должен вызываться раньше времени автоматическим переключением на потенциально невалидный stock slot.

## 11. Final Vanilla transaction

После успешного initramfs preflight migration выполняется без дополнительных prompts:

```text
persistent state -> PROD_WRITING + readback PASS
-> prepare canonical OpenWrt layout
-> create/format canonical UBI
-> recreate/preserve ubootenv/ubootenv2 and restore persistent state before later destructive stages
-> create required volumes
-> restore/preserve board identity in OpenWrt-expected locations
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

После начала final write запрещены automatic backend switching и blind retries другим writer implementation.

## 12. Final acceptance

Для XG-040G-MD Vanilla item 4 acceptance должен включать отдельно:

```text
stock -> SLOT2 pregnant initramfs boot PASS
initramfs Ethernet + SSH PASS
status.json/log monitoring PASS
persistent migration marker write/readback PASS
intentional pre-destructive preflight failure -> guarded master rollback PASS
selector master readback PASS
reboot to untouched stock SLOT1 PASS
power/reset simulation after PROD_WRITING -> master rollback REFUSED PASS
missing/corrupt marker -> master rollback REFUSED PASS
stock-layout evidence mismatch -> master rollback REFUSED PASS
autonomous stage2 without host commands PASS
canonical UBI migration PASS
identity restore PASS
Vanilla FIP/U-Boot PASS
Fudan/FM25G02B boot support PASS
BL2 LAST + readback PASS
PROD_VERIFIED/BOOT_CONFIRMED state transitions PASS
cold boot to production OpenWrt PASS
subsequent normal OpenWrt sysupgrade PASS
Ursus-specific persistent code ABSENT
```

CI/build PASS не заменяет hardware acceptance.

## 13. Persistent UrsusBoot не меняется этим решением

Persistent UrsusBoot остаётся отдельным продуктом с Web Recovery/UART/Ursus utilities.

Known CLI network ownership problem (`ping`/`wget`/`tftpboot`/`dhcp` versus live WebFailsafe lwIP netif) остаётся отдельным persistent lifecycle defect и должен быть исправлен до публичного persistent build. Он больше не блокирует Vanilla path.

## 14. Immediate engineering sequence

```text
1. Freeze current TRANSITION2 network investigation as completed diagnostic R&D for Vanilla needs.
2. Import MedveFlasher proven autonomous stage2 mechanics into UrsusFlasher item 4.
3. Build pregnant OpenWrt initramfs with embedded Vanilla artifacts and manifest.
4. Port ursusstockslot status/master/slave semantics into Linux initramfs with full readback and internal rollback guard.
5. Implement persistent migration state MIGRATION_OK/PROD_WRITING/PROD_VERIFIED/BOOT_CONFIRMED.
6. Treat /tmp/status.json as telemetry only; derive rollback from persistent state + NAND evidence.
7. Add install.log + SSH monitoring/reconnect to UrsusFlasher.
8. Keep one y/N before the complete Vanilla transaction; remove codewords/repeated confirms.
9. HW-test deliberate pre-destructive failure and automatic/host-assisted return to master SLOT1.
10. HW-test reset/power-loss semantics after PROD_WRITING: rollback must be refused.
11. Only after rollback/refusal guards PASS, enable final destructive UBI migration.
12. HW-test full autonomous Vanilla migration and production boot.
13. Then generalize board-profile implementation for MF without copying MD offsets blindly.
```

## 15. Repository/operator rules

- Work only in `feature/ursusboot-modular-airoha` until explicitly instructed otherwise.
- Do not modify `main`; no merge/tag/release without explicit operator command.
- Do not commit device backups, plaintext credentials, serial/GPON identity or other device secrets.
- Prefer automatic evidence/readback over operator ceremony.
- Normal destructive transaction: one meaningful `y/N`, no codewords and no repeated confirmations.
- `/tmp` telemetry never authorizes rollback.
- Missing/unknown persistent state is unsafe by default and must refuse stock master rollback.
- `ursusstockslot master` itself enforces the rollback guard; caller/UI is not the trust boundary.
- Never claim CI PASS as HW PASS.
- Do not auto-switch to stock master after final destructive migration has begun.
- Preserve Fudan/FMSH hardware support in final MD Vanilla U-Boot provenance.

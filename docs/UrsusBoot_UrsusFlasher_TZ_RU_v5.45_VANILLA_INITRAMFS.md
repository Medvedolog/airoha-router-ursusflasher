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

Все остальные safety gates — автоматические: board identity, backup validity, geometry, hashes, stock slot readback, artifact provenance, NAND preflight, identity availability и final readback.

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
READY_TO_MIGRATE
DESTRUCTIVE_STARTED
PREPARING_UBI
WRITING_FIP
WRITING_SYSUPGRADE
RESTORING_IDENTITY
WRITING_BL2_LAST
VERIFYING_FINAL
DONE
FAILED
```

Обязательный machine-readable status, например:

```text
/tmp/ursus-install/status.json
```

и human-readable journal, например:

```text
/tmp/ursus-install/install.log
```

Минимальные status fields:

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

Потеря SSH, закрытие UrsusFlasher на ПК или временная потеря Ethernet после `DESTRUCTIVE_STARTED` не должны останавливать migration service и не должны вызывать повторный write после reconnect.

## 8. SSH contract

После reboot UrsusFlasher ищет initramfs и подключается по SSH для:

```text
status polling
stream/tail install log
progress rendering
reconnect after transient link loss
pre-destructive recovery action when explicitly allowed by status
final production detection/verification
```

SSH не является обязательным транспортом production image во время normal autonomous stage2 и не является clock/trigger каждой NAND операции.

Если SSH исчезает:

```text
migration continues locally
host reconnects
host re-reads status.json
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

## 10. No-UART rollback contract

До начала final destructive migration:

```text
destructive_started=false
stock_master_intact=true
rollback_allowed=true
```

SLOT1/master является гарантированным no-UART escape path.

Если initramfs booted, но stage2 preflight не прошёл, предпочтительное автоматическое восстановление:

```text
ursusstockslot status
-> ursusstockslot master
-> full selector readback PASS
-> sync
-> reboot
-> stock Nokia SLOT1
```

Если автоматический rollback не отработал, UrsusFlasher через SSH выполняет тот же contract. Это действие не требует второго подтверждения, если оно выполняется как recovery внутри уже подтверждённой Vanilla transaction и `rollback_allowed=true`.

Для отдельной ручной EXPERT-команды вне активной transaction selector write может иметь одно обычное `y/N`.

После:

```text
destructive_started=true
```

автоматический возврат на SLOT1 запрещён. Stock rootfs/layout уже может быть частично уничтожен. В этом состоянии recovery policy — остаться в initramfs, показать точную failed stage и выполнять только доказанную repair/retry strategy; UART/BootROM остаётся последним recovery path, но не должен вызываться раньше времени автоматическим переключением на потенциально невалидный stock slot.

## 11. Final Vanilla transaction

После успешного initramfs preflight migration выполняется без дополнительных prompts:

```text
prepare canonical OpenWrt layout
-> create/format canonical UBI
-> create required volumes
-> restore/preserve board identity in OpenWrt-expected locations
-> write Vanilla BL31/U-Boot FIP
-> write canonical OpenWrt production/sysupgrade content
-> verify critical data
-> write BL2/preloader LAST
-> final full/readback verification
-> reboot
```

После начала final write запрещены automatic backend switching и blind retries другим writer implementation.

## 12. Final acceptance

Для XG-040G-MD Vanilla item 4 acceptance должен включать отдельно:

```text
stock -> SLOT2 pregnant initramfs boot PASS
initramfs Ethernet + SSH PASS
status.json/log monitoring PASS
intentional pre-destructive preflight failure -> master rollback PASS
selector master readback PASS
reboot to untouched stock SLOT1 PASS
autonomous stage2 without host commands PASS
canonical UBI migration PASS
identity restore PASS
Vanilla FIP/U-Boot PASS
Fudan/FM25G02B boot support PASS
BL2 LAST + readback PASS
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
4. Port ursusstockslot status/master/slave semantics into Linux initramfs with full readback.
5. Add status.json + install.log + SSH monitoring/reconnect to UrsusFlasher.
6. Keep one y/N before the complete Vanilla transaction; remove codewords/repeated confirms.
7. HW-test deliberate initramfs preflight failure and automatic/host-assisted return to master SLOT1.
8. Only after rollback PASS, enable final destructive UBI migration.
9. HW-test full autonomous Vanilla migration and production boot.
10. Then generalize board-profile implementation for MF without copying MD offsets blindly.
```

## 15. Repository/operator rules

- Work only in `feature/ursusboot-modular-airoha` until explicitly instructed otherwise.
- Do not modify `main`; no merge/tag/release without explicit operator command.
- Do not commit device backups, plaintext credentials, serial/GPON identity or other device secrets.
- Prefer automatic evidence/readback over operator ceremony.
- Normal destructive transaction: one meaningful `y/N`, no codewords and no repeated confirmations.
- Never claim CI PASS as HW PASS.
- Do not auto-switch to stock master after final destructive migration has begun.
- Preserve Fudan/FMSH hardware support in final MD Vanilla U-Boot provenance.

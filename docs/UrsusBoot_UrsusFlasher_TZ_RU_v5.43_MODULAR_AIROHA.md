# UrsusBoot / UrsusFlasher ТЗ v5.43 — модульная Airoha-архитектура

**Обновлено:** 2026-09-15  
**Статус:** engineering baseline / active development  
**Ветка:** `feature/ursusboot-modular-airoha`  
**Важно:** `main`, tags и releases не изменяются без отдельной команды оператора.

## 1. Цель

UrsusBoot развивается как единая многомодельная Airoha-платформа, а не набор независимых форков. Новая модель добавляется композиционным профилем и минимальным board-specific policy при сохранении общего WebFailsafe, network stack, dispatcher, StockBridge, update/recovery backend и host-side orchestration UrsusFlasher.

```text
common core
  -> SoC module
  -> board/DTS module
  -> storage/environment policy
  -> boot/layout board policy
  -> runtime role
```

UrsusFlasher является policy/orchestration layer. UrsusBoot является компактным execution/recovery backend.

## 2. Поддерживаемые профили

- `xg040-md`: Nokia XG-040G-MD, Airoha AN7581/AN7581DT family.
- `xg040-mf`: Nokia XG-040G-MF, Airoha AN7583.
- `xg140-md`: Bell/Nokia XG-140G-MD, AN7581DT family.

Board profile определяет только реальные различия: DTS, storage/env, stock slot layout, HDR/FIT policy, selector policy, write spans, SerDes, identity/restore regions и hardware hooks. Common runtime не копируется по моделям.

## 3. Runtime roles

### `persistent`

```text
bootcmd=ursusdispatch
```

Persistent UrsusBoot остаётся отдельным поддерживаемым продуктом. Он сохраняет:

```text
OpenWrt factory/non-UBI payload path
OpenWrt initramfs recovery/rescue payloads
OpenWrt sysupgrade/UBI payloads where supported
```

### `ram-recovery`

RAM-only WebFailsafe из той же кодовой базы. Initramfs OpenWrt images остаются штатными recovery payloads для UrsusBoot.

### `transition`

Одноразовая RAM-среда для Vanilla OpenWrt migration:

```text
Mode=TRANSITION
Persistence target=NONE
Final target=OFFICIAL_OPENWRT
ENV_IS_NOWHERE
```

TRANSITION не остаётся в конечном boot chain.

## 4. Product separation: Persistent vs Vanilla

### Shared OpenWrt firmware bundle

OpenWrt firmware artifacts хранятся один раз, если конкретный artifact действительно совместим с несколькими board profiles:

```text
factory/non-UBI image
initramfs recovery image
sysupgrade/UBI image
firmware manifest / provenance / SHA256
```

Нельзя механически создавать отдельные MD/MF копии идентичного OpenWrt firmware artifact.

### Board-specific transition/bootchain bundle

Отдельными остаются только реально различающиеся:

```text
stock-compatible TRANSITION wrapper/image
BL2/preloader
FIP/BL31/U-Boot
stock A/B/HDR/FIT policy
write spans/final layout policy
NAND-specific enablement/provenance
```

### Жёсткое правило Vanilla

Для `Vanilla Transition` существует только один конечный storage target:

```text
VANILLA -> canonical OpenWrt UBI layout
```

В Vanilla запрещены:

```text
factory/non-UBI final layout
factory-vs-UBI menu
fallback на factory layout
Nokia A/B как конечная OpenWrt storage layout
persistent UrsusBoot в конечной boot chain
```

Factory/non-UBI payload остаётся только для отдельного persistent UrsusBoot product/path.

## 5. Обязательный первый запуск на stock Nokia

Перед самым первым запуском UrsusFlasher на устройстве с Nokia stock firmware оператор обязан выполнить аппаратный factory reset:

```text
router powered on
-> hold Reset >= 30 seconds
-> release
-> wait for stock Nokia Web UI to boot fully
-> start UrsusFlasher
```

Аппаратное наблюдение 2026-09-15: более короткое удержание Reset может не дать полного stock factory reset. Это operator pre-step, а не дополнительный destructive confirmation gate.

## 6. Полный stock backup — обязательный контракт

До **любой** stock -> TRANSITION/destructive migration UrsusFlasher обязан использовать классический proven full-backup backend.

Backup означает **все разделы из живого `/proc/mtd`**, а не только затрагиваемые операцией.

Обязательный результат:

```text
/proc/mtd snapshot
mtd0..mtdN complete binary dumps
partition name
exact size
erase size
SHA256 каждого dump
DEVICE_IDENTITY / MAC / serial / RI / factory metadata where applicable
BACKUP_MANIFEST.json
```

Destructive staging запрещён, пока каждый текущий `/proc/mtd` entry не сохранён на ПК с подтверждёнными размером и SHA256.

MD и MF используют общий proven UrsusFlasher backup backend. Отдельный сокращённый backup внутри transition-stager запрещён как production design.

## 7. EXPERT — единственный пользовательский UI для Vanilla Transition

Vanilla Transition **не является ONE-CLICK operation** и не должен жить в отдельном пользовательском `START_MD_TRANSITION.cmd`.

Основной пользовательский путь:

```text
START_EXPERT.cmd / START_EXPERT.sh
-> UrsusFlasher EXPERT
-> item 4: Stock Nokia -> Vanilla OpenWrt (TRANSITION)
```

Пункт 4 выбран намеренно: в текущем EXPERT он исторически объединён с item 2, не отображается и сейчас лишь перенаправляет выбор `4` на установку UrsusBoot. Его следует освободить и переиспользовать под Vanilla Transition.

### EXPERT item 4 должен переиспользовать существующую инфраструктуру

Запрещено создавать второй параллельный mini-flasher со своей авторизацией, backup, transport и логированием.

Item 4 обязан использовать существующие:

```text
DeviceState / board profile detection
stock Web authentication
stock credentials/Telnet enablement
root/su acquisition
full_backup_readonly / proven backup backend
proven transfer backends
common transaction logging
common y/N UI
common readback/verification
board_profiles MD/MF
```

`START_MD_TRANSITION.cmd/.sh` после интеграции может оставаться только developer/HWTEST wrapper либо быть исключён из пользовательского ZIP.

## 8. Политика гейтов

Engineering EXPERT не должен заранее скрывать/блокировать операции из-за `HW_PENDING`, stale DeviceState, неполного network probe или частных признаков одного stock firmware build.

Hard-stop допустим только на технических инвариантах, напрямую защищающих flash transaction:

```text
target model/profile mismatch
NAND geometry / exact write span
candidate structural integrity
protected-region boundaries
payload does not fit target span
complete backup missing/invalid
upload SHA mismatch
post-write full readback mismatch
selector readback mismatch
```

Не являются hard-gates сами по себе:

```text
active/curimg/startok/count отличаются от ранее виденного значения
stock kernel compression = none вместо lzma
конкретный transport недоступен, если до destructive boundary доступен другой proven transport
advisory probe incomplete/HW_PENDING
```

После начала destructive write backend/writer автоматически не меняется.

Нормальный destructive flow имеет один осмысленный `y/N` после automatic preflight-summary.

## 9. Stock FIT wrapper contract — исправленная политика

`stock_fit_wrapper.py` появился в commit `db18eb3b99005d3a8916687c5da49cc43d578f6b` как structural safety contract для stock FIP/HDR2/FIT.

Его назначение сохраняется: доказать, что builder разбирает ожидаемую структуру и меняет только разрешённые FIT fields.

Аппаратный тест 2026-09-15 выявил ошибочное частное предположение:

```text
expected /images/kernel@1/compression = lzma
real XG-040G-MD stock after factory reset = none
```

Это значение не должно быть gate. Wrapper обязан:

```text
validate FIP/HDR2/FDT structure
validate kernel type/arch/os
validate load/entry and writable spans where board policy requires them
accept structurally valid stock compression values relevant to supported stock builds
replace injected TRANSITION kernel compression with none
recalculate kernel hash
preserve FIP/HDR2/FDT/filesystem outside explicitly allowed fields byte-for-byte
```

Structural safety остаётся; firmware-version fingerprinting как gate запрещён без доказанной необходимости.

## 10. Transport policy для stock -> TRANSITION

Аппаратный прогон 2026-09-15 выявил вторую регрессию standalone stager:

```text
SLAVE candidate built successfully
operator confirmed y
send_file_to_router_tftp(... port=1069, block_size=4096)
-> stock TFTP client returned ERROR
-> no flash write started
```

Production transition не должен иметь `TFTP or die` transport policy.

EXPERT item 4 обязан использовать proven transport selection. Transport выбирается и полностью preflight-проверяется **до destructive boundary**. Если один transport неработоспособен до начала записи, разрешён другой уже доказанный transport. После начала destructive write переключение backend запрещено.

TFTP остаётся одним из transport mechanisms, а не обязательным единственным путём.

## 11. MD Vanilla Transition

Целевая bootstrap цепочка:

```text
stock MAIN/SLOT1
-> mandatory full backup of ALL /proc/mtd
-> build stock-compatible secondary candidate
-> transfer candidate with proven preflighted transport
-> write/readback nsb_slave
-> change only board-policy-approved selector request (MD proven: flag.active -> 1)
-> selector readback
-> reboot
-> stock tcboot selects SLAVE
-> stock-compatible Linux Image handoff
-> UrsusBoot TRANSITION in RAM
-> EXPERT/host reconnects to TRANSITION Web/API
-> final Vanilla migration
```

Аппаратно подтверждено на XG-040G-MD/Fudan FM25G02B:

```text
tcboot selected SLOT2
stock FIT/hash verification passed
ARM64 Linux Image shim started UrsusBoot TRANSITION
Fudan NAND detected
stock retry counter decreased on failed SLOT2 boots
tcboot eventually returned automatically to untouched SLOT1
```

TRANSITION1 runtime был отвергнут, потому что после запуска уходил в stock boot path и создавал hybrid MASTER-kernel/SLAVE-rootfs boot failure.

TRANSITION2 должен оставаться в WebFailsafe/transition execution и не пытаться boot stock MASTER по default path.

## 12. MF Vanilla Transition

MF — обязательный production-equivalent target, не optional follow-up.

Архитектура:

```text
common transition runtime
  + xg040-md board policy
  + xg040-mf board policy
```

Для MF требуются:

```text
same full all-MTD backup contract
MF stock secondary-slot wrapper/HDR policy
MF selector policy
TRANSITION runtime in RAM
MF-specific BL2/FIP only where actually different
canonical OpenWrt UBI final layout
shared OpenWrt firmware bundle where artifact compatible
full readback/verification
```

MD MTD numbers, offsets и HDR assumptions не копируются в MF. `stock_ab_transition` должен быть board-profile driven.

## 13. Final Vanilla migration transaction — MD/MF

Все boot-critical payloads заранее входят в UrsusFlasher bundle. Live download из Internet во время destructive migration запрещён.

```text
TRANSITION running fully from RAM
-> receive shared OpenWrt firmware bundle + board-specific bootchain payloads
-> verify manifest/SHA/profile/NAND geometry/write spans
-> verify complete stock backup
-> one y/N
---------------- destructive boundary ----------------
-> write canonical OpenWrt BL2/preloader
-> full readback
-> write canonical OpenWrt FIP/BL31/U-Boot
-> full readback
-> canonical OpenWrt UBI repartition/format
-> deploy compatible OpenWrt UBI/sysupgrade payload
-> verify UBI attach/volumes/FIT/rootfs contract
-> sync
-> reboot
```

Финальная chain:

```text
BootROM
-> OpenWrt BL2/preloader
-> OpenWrt FIP/BL31
-> OpenWrt U-Boot
-> canonical OpenWrt UBI
-> OpenWrt
```

После успешной migration отсутствуют tcboot, Nokia A/B и UrsusBoot в active final boot target. Factory/identity/calibration regions, которые должны сохраняться для работы конкретной платы, не уничтожаются только ради формального «перезаписать всё».

## 14. XG140 persistent native-hybrid

XG140 остаётся отдельным persistent/recovery направлением.

Known physical boot area:

```text
mtd0 size          0x80000
native FIP start   0x800
vendor env         0x7c000..0x7ffff
```

Persistent candidate:

```text
live BootROM prefix       KEEP
native FIP                KEEP
non-NT_FW entries         KEEP
NT_FW / BL33              REPLACE with modular XG140 UrsusBoot
live vendor env           KEEP
```

Отвергнутый UART path:

```text
tcboot -> loadx raw u-boot.bin -> go 0x81e00000
```

Правильный emergency path:

```text
stock tcboot
-> XMODEM Linux FIT initramfs @0x85000000
-> bootm
-> rescue Linux in RAM
-> native-hybrid FIP reconstruction/write
-> full 0x80000 readback
-> reboot
-> persistent modular UrsusBoot
```

## 15. CI contract

CI проверяет:

- common/SoC/board/runtime layer boundaries;
- profile resolver consistency;
- source-level runtime role selection;
- board identity;
- environment ownership;
- payload manifests/SHA;
- no duplicate shared OpenWrt artifacts without reason;
- separate MD/MF board manifests where bootchain/layout actually differs;
- Vanilla permits only UBI final target;
- persistent bundle retains factory payload and initramfs recovery images;
- transition wrapper structural self-tests cover at least supported `compression=none` and `compression=lzma` stock FIT variants;
- EXPERT item 4 uses common/proven backup, auth, transport and logging infrastructure rather than standalone copies.

CI PASS не равен hardware acceptance.

## 16. Immediate engineering sequence

```text
1. Stop treating standalone START_MD_TRANSITION as production UI.
2. Add/reclaim EXPERT item 4: Stock Nokia -> Vanilla OpenWrt (TRANSITION).
3. Route item 4 through common DeviceState/board_profiles/stock Web/Telnet/root infrastructure.
4. Replace four-partition transition backup with proven full backup of every live /proc/mtd partition.
5. Replace mandatory standalone TFTP upload with common preflighted proven transport selection.
6. Keep stock FIT structural validation but remove firmware-version fingerprints as policy gates.
7. HW-accept MD stock -> TRANSITION2 Web/API without UART.
8. Implement MD TRANSITION -> vanilla BL2/FIP -> UBI -> OpenWrt.
9. Refactor common transition backend to board-profile-driven MD/MF policy.
10. Build and HW-accept MF secondary-slot TRANSITION.
11. HW-test MF final UBI-only Vanilla migration.
12. Keep persistent UrsusBoot + factory/non-UBI + initramfs recovery paths intact.
13. Continue XG140 persistent/recovery acceptance independently.
```

## 17. Repository / operator contract

- Не менять `main` без прямой команды оператора.
- Не merge/tag/release без прямой команды.
- Не коммитить device backups, plaintext credentials, serial/GPON secrets.
- Перед первым UrsusFlasher run на Nokia stock: Reset **30+ секунд**, затем дождаться stock Web.
- Stock -> transition всегда требует полного verified backup **всех** live `/proc/mtd` partitions.
- Vanilla Transition находится в **EXPERT**, не в ONE-CLICK.
- User-facing standalone MD transition launcher не является конечной архитектурой.
- EXPERT/HWTEST: minimum operator ceremony, без бессмысленных policy-gates.
- Один meaningful `y/N` после automatic preflight-summary.
- Structural geometry/boundary/readback checks выполняются автоматически.
- После начала destructive write backend/writer не меняется.
- Vanilla MD/MF final target — **UBI only**.
- Persistent UrsusBoot сохраняет factory/non-UBI OpenWrt support и initramfs recovery images.
- OpenWrt firmware artifacts shared между MD/MF, когда один artifact реально совместим; board-specific остаются только реально различающиеся transition/bootchain/layout payloads.

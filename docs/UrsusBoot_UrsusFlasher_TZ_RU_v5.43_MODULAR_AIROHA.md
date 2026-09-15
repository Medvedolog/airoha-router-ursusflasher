# UrsusBoot / UrsusFlasher ТЗ v5.43 — модульная Airoha-архитектура

**Обновлено:** 2026-09-15  
**Статус:** engineering baseline / active development  
**Ветка:** `feature/ursusboot-modular-airoha`  
**Важно:** `main`, tags и releases не изменяются без отдельной команды оператора.

## 1. Цель

UrsusBoot развивается как единая многомодельная Airoha-платформа, а не набор независимых форков под каждую Nokia/Bell плату. Новая модель должна добавляться композиционным профилем и минимальным board-specific policy, сохраняя общий WebFailsafe, network stack, dispatcher, StockBridge, update/recovery backend и host-side orchestration UrsusFlasher.

Базовая композиция:

```text
common core
  -> SoC module
  -> board/DTS module
  -> storage/environment policy
  -> boot/layout board policy
  -> runtime role
```

Архитектурная цель проекта — многомодельный Airoha flasher/recovery stack, в котором UrsusFlasher выбирает модель, transport и operation policy, а UrsusBoot предоставляет общий компактный execution backend.

## 2. Поддерживаемые профили

Текущие профили:

- `xg040-md`: Nokia XG-040G-MD, Airoha AN7581, native MD layout.
- `xg040-mf`: Nokia XG-040G-MF, Airoha AN7583, native MF layout.
- `xg140-md`: Bell/Nokia XG-140G-MD, AN7581DT/AN7581 family, MD-derived common core, XG140 native stock layout.

`xg040-md` и `xg140-md` используют общий `soc-an7581` слой. MF использует `soc-an7583`.

Board profile не должен копировать common runtime. Различия платы должны быть сведены к DTS, storage/env policy, boot/layout policy и минимальным hardware hooks.

## 3. Board policy

Модельные параметры не должны быть зашиты в common `ursusdispatch.c`, `ursusstock.c` или WebFailsafe HTML.

Board policy определяет как минимум:

- model / compatible / profile marker;
- stock MASTER/SLAVE base и slot size;
- vendor env base/size;
- HDR magic/size;
- root mapping;
- SerDes bootarg policy;
- UBI/factory probe permissions;
- FIT/oracle параметры, если они доказаны для платы;
- разрешённые stock/OpenWrt boot paths;
- board-specific identity/restore data locations.

WebFailsafe выводит модель через policy (`URSUS_BOARD_MODEL`); hard-coded `Nokia XG-040G-MD` в common UI запрещён CI-gate.

## 4. Runtime roles

Runtime role ортогонален board profile и выбирается до компиляции.

### `persistent`

```text
bootcmd=ursusdispatch
```

Нормальный persistent supervisor. Persistent UrsusBoot остаётся первым управляемым U-Boot runtime и может загружать stock Nokia Linux либо OpenWrt по board policy.

Persistent product сохраняет штатные OpenWrt firmware payload-классы проекта:

```text
OpenWrt factory/non-UBI image path
OpenWrt initramfs image for UrsusBoot recovery/rescue
OpenWrt sysupgrade/UBI image where required by the supported target
```

OpenWrt firmware payloads должны храниться как **shared firmware bundle**, если один и тот же artifact действительно совместим с несколькими board profiles. Нельзя механически дублировать идентичные `factory`, `initramfs`, `sysupgrade`/UBI images отдельно для MD и MF только из-за различия bootstrap/bootchain.

Они не являются частью board-specific TRANSITION bootstrap и не должны удаляться из общего UrsusFlasher bundle.

### `ram-recovery`

```text
bootcmd=ursusweb;true
```

RAM-only WebFailsafe role из той же кодовой базы. Пост-build byte patch готового `u-boot.bin` запрещён. Initramfs OpenWrt images должны оставаться доступными как recovery payload для загрузки через UrsusBoot.

### `transition`

Одноразовая RAM-среда для Vanilla OpenWrt migration:

```text
Mode=TRANSITION
Persistence target=NONE
Final target=OFFICIAL_OPENWRT
ENV_IS_NOWHERE
```

TRANSITION не должен оставаться в конечном boot chain. Его задача — безопасно выйти из stock Nokia boot chain, выполнить migration из независимой RAM-среды и закончить официальным/OpenWrt-compatible boot chain без Ursus-specific persistent code.

## 5. UrsusFlasher EXPERT / политика гейтов

Engineering/HWTEST UI не должен заранее скрывать или дизейблить операции только из-за неполного network probe, `HW_PENDING`, stale DeviceState либо отсутствия auto-detection.

Требования:

- все верхние EXPERT operations остаются выбираемыми;
- модель MD/MF/XG140 всегда можно выбрать вручную;
- Telnet и UART всегда можно выбрать вручную;
- ручной выбор оператора имеет приоритет над advisory network probe;
- несовпадение auto-probe с ручным выбором — warning, а не UI STOP;
- backend обязан попытаться выбранный transport и остановиться только на конкретной технической невозможности до destructive write.

Минимальные hard-gates сохраняются непосредственно около записи и являются машинными инвариантами, а не UI policy:

```text
target geometry / exact write span
candidate structural validity
protected-region boundaries
required device lineage/identity for выбранный writer
post-write full readback/compare
```

После начала destructive write запрещён автоматический fallback на второй writer/backend.

### Обязательный первый запуск на stock Nokia

Перед самым первым запуском UrsusFlasher на устройстве с заводским Nokia firmware оператор обязан выполнить аппаратный factory reset stock-конфигурации:

```text
при включённом роутере удерживать Reset не менее 30 секунд
```

Практический аппаратный тест показал, что более короткое удержание может не привести к полному сбросу stock Nokia. После reset необходимо дождаться нормальной загрузки stock Web и только затем запускать UrsusFlasher.

Это операторский pre-step, а не дополнительный destructive confirmation gate внутри UrsusFlasher.

## 6. XG140 persistent native-hybrid

XG140 не получает MD boot area целиком. Persistent image строится из собственного stock `mtd0` устройства:

```text
live BootROM prefix       KEEP
native Nokia/Bell FIP     KEEP
  native entries          KEEP
  NT_FW / BL33            REPLACE -> modular XG140 UrsusBoot
live vendor env           KEEP
```

Для подтверждённой XG140 разметки:

- boot area: `0x000000..0x07ffff`;
- FIP physical start: `0x000800`;
- protected vendor env: `0x07c000..0x07ffff`;
- physical mtd0 size: `0x80000`.

Repacker обязан структурно проверять FIP TOC и не пересекать protected env. Prefix и vendor env не принадлежат UrsusBoot и не должны изменяться штатным XG140 update path.

Persistent XG140 BL33 строится из MD-derived common core, но XG140 не наследует неподтверждённые MD assumptions:

- UBI autodetect: disabled by XG140 board policy;
- MD factory FIT probe: disabled;
- MD SerDes overrides: disabled;
- vendor env: preserved/read as vendor data.

## 7. XG140 normal boot target

Целевая production chain:

```text
Airoha BootROM
  -> XG140 native FIP / trusted firmware
  -> modular UrsusBoot BL33
  -> ursusdispatch
  -> common StockBridge / OpenWrt policy
  -> Nokia stock Linux или OpenWrt
```

Stock tcboot после установки persistent UrsusBoot не является обязательной частью normal boot chain.

Наличие stock slots и Nokia A/B selector не означает, что tcboot должен оставаться первым persistent BL33. Для XG140 UrsusBoot должен уметь загружать stock Nokia Linux напрямую тем же классом механизма, который уже используется на MD.

## 8. XG140 аварийный UART path

Аппаратно отвергнут старый путь:

```text
tcboot -> loadx raw u-boot.bin -> go 0x81e00000
```

На физическом XG140 он возвращает управление в tcboot с `Application terminated, rc=1`. Этот эксперимент не повторять как production/recovery design.

Правильный аварийный путь:

```text
stock tcboot
  -> XMODEM Linux FIT initramfs @ 0x85000000
  -> iminfo
  -> bootm
  -> rescue Linux полностью в RAM
  -> transfer device-derived native-hybrid FIP
  -> reconstruct 512-KiB mtd0 candidate
  -> write once
  -> full 512-KiB readback
  -> reboot
  -> persistent modular UrsusBoot
```

UrsusFlasher EXPERT routing для `XG140 -> UART` обязан использовать именно этот FIT/initramfs bridge, а не raw nested U-Boot `go`.

## 9. UrsusFlasher <-> UrsusBoot

UrsusFlasher остаётся policy/orchestration layer:

- полный backup/restore;
- model/family selection and detection;
- manifest/provenance;
- identity repair;
- Telnet/Web/TFTP/UART/BootROM transport selection;
- candidate building;
- sequencing;
- transaction logging.

UrsusBoot остаётся компактным execution/recovery backend:

- boot policy;
- WebFailsafe/API;
- network primitives;
- MTD/NAND writer;
- verification/readback;
- reboot;
- common StockBridge.

Глобальный UrsusFlasher board profile связывается с конкретным `ursusboot_profile`; два независимых каталога модельных magic names недопустимы.

## 10. Vanilla Transition для XG-040G-MD / MF

Vanilla Transition — отдельный optional final product и не заменяет persistent UrsusBoot path.

### Обязательный полный stock backup

До любой записи stock -> TRANSITION UrsusFlasher обязан через stock Web/Telnet снять и локально валидировать **все MTD-разделы, перечисленные текущим `/proc/mtd` устройства**, а не только `flag/flagback/nsb_master/nsb_slave`.

Backup contract:

```text
/proc/mtd snapshot
mtd0..mtdN — полный бинарный dump каждого раздела
partition name
exact size
erase size
SHA256 каждого dump
DEVICE_IDENTITY / MAC / serial / RI / factory metadata, где применимо
BACKUP_MANIFEST.json
```

Переход к destructive staging запрещён, если хотя бы один раздел из текущего `/proc/mtd` не скопирован полностью на ПК или его размер/SHA256 не подтверждён.

Полный backup должен использовать общий proven UrsusFlasher backup backend. MD/MF transition не должны иметь отдельный урезанный backup implementation.

### Целевая цепочка

```text
stock Nokia MAIN
  -> FULL verified backup of ALL /proc/mtd partitions
  -> TRANSITION payload в stock secondary/SLAVE staging
  -> selector request на SLAVE
  -> stock tcboot
  -> stock-compatible Linux-image handoff
  -> UrsusBoot TRANSITION в RAM
  -> vanilla OpenWrt boot-chain migration
  -> canonical OpenWrt UBI repartition/layout
  -> shared OpenWrt UBI/sysupgrade payload where compatible
  -> final verification
  -> vanilla OpenWrt, Ursus-specific persistent code ABSENT
```

### Жёсткое правило Vanilla layout

Для режима `Vanilla Transition` существует только один конечный storage target:

```text
VANILLA -> canonical OpenWrt UBI layout
```

Никакого `factory/non-UBI` варианта внутри Vanilla Transition быть не должно. Никакого меню выбора `factory vs UBI`, fallback на factory layout или сохранения Nokia A/B layout после начала финальной миграции не допускается.

Factory/non-UBI OpenWrt payload остаётся поддерживаемым **только для отдельного persistent UrsusBoot product/path** и должен оставаться в общем shared OpenWrt firmware bundle вместе с recovery initramfs images.

### Payload separation contract

UrsusFlasher bundle разделяется на два класса payloads:

```text
shared OpenWrt firmware bundle
  factory/non-UBI image
  initramfs recovery image
  sysupgrade/UBI image
  firmware manifest/provenance

board-specific transition/bootchain bundle
  stock-compatible TRANSITION wrapper/image
  BL2/preloader, если различается для board/SoC/NAND
  FIP/BL31/U-Boot, если различается для board/SoC
  board layout/write-span policy
  NAND enablement policy/patch provenance
```

Если один OpenWrt firmware artifact действительно совместим с MD и MF, он хранится **один раз** в shared bundle и используется обоими профилями. Разделение на `md/...` и `mf/...` допустимо только для реально различающихся artifacts, а не по имени платы.

Финальный Vanilla backend обязан:

```text
получить shared OpenWrt firmware bundle + board-specific transition/bootchain bundle
-> проверить manifest/SHA/profile/NAND geometry
-> один y/N
-> записать canonical OpenWrt BL2/preloader
-> full readback
-> записать canonical OpenWrt FIP/BL31/U-Boot
-> full readback
-> выполнить canonical UBI repartition/format
-> развернуть compatible OpenWrt UBI/sysupgrade image из shared firmware bundle
-> проверить UBI attach/volumes/FIT/rootfs contract
-> sync
-> reboot
```

Все payload должны быть заранее включены в UrsusFlasher bundle; live download из Internet во время destructive migration не допускается.

### MD status

Для XG-040G-MD существуют:

- `ursusboot/configs/ursusboot-transition-handoff.cfg`;
- stock-compatible ARM64 Linux Image handoff shim;
- `ursusflasher/src/stock_ab_transition.py`;
- `ursusflasher/src/stock_fit_wrapper.py`;
- staging в `nsb_slave` с сохранением stock FIP/HDR/FIT topology;
- изменение только `flag.active` для запроса SLAVE;
- `flagback` не зеркалируется вручную;
- readback slot и selector до reboot.

Аппаратно подтверждено на XG-040G-MD с Fudan FM25G02B:

```text
stock tcboot chooses SLAVE
-> stock-compatible FIT hash passes
-> Linux Image shim starts UrsusBoot TRANSITION
-> stock A/B retry counter decreases on failed secondary boot
-> tcboot eventually returns automatically to untouched stock SLOT1
```

Следующая обязательная MD acceptance — исправленный TRANSITION runtime должен остаться в Web/API без ухода в stock boot, после чего разрешается первый destructive Vanilla UBI migration test.

### MF status

XG-040G-MF обязан получить production-equivalent Vanilla Transition на той же общей архитектуре:

```text
common transition runtime
  + xg040-md board policy
  + xg040-mf board policy
```

MF transition должен включать тот же обязательный полный backup всех `/proc/mtd`, отдельный stock-compatible secondary-slot wrapper/HDR policy, MF selector/layout policy и конечный **только UBI** Vanilla target.

OpenWrt firmware images для MF должны браться из того же shared firmware bundle, если их compatible/target contract допускает использование того же artifact; отдельная MF-копия нужна только при фактическом различии firmware image.

`stock_ab_transition` должен стать board-profile driven; номера mtd/offsets/HDR2/HDR3 не должны быть универсально зашиты как MD constants.

## 11. Nokia A/B selector policy

Для доказанного stock selector contract:

- `active` — requested slot;
- `curimg` — фактически загруженный slot;
- `startok` — stock userspace success state;
- `count` — retry/state counter;
- `flagback` принадлежит stock tcboot reconciliation logic.

При запросе SLAVE меняется только `active=1`, если конкретный board profile подтвердил этот contract. Нельзя вручную зеркалировать `flagback` без доказанной необходимости.

На MD аппаратно подтверждено автоматическое возвращение tcboot к нетронутому SLOT1 после серии неуспешных загрузок SLOT2.

A/B selector является отдельным policy-модулем и не должен смешиваться с persistent boot-area write transaction.

## 12. Vanilla definition

Vanilla OpenWrt означает конечную persistent-систему, построенную по официальному/OpenWrt board-support build contract и не содержащую Ursus-specific persistent code.

Допустимы необходимые board/hardware-support patches, включая Fudan/FMSH SPI-NAND support для MD, если они являются частью OpenWrt hardware enablement и отражены в provenance.

Vanilla storage contract для MD/MF transition — **только canonical UBI layout**.

Недопустимы в конечном Vanilla boot chain:

- UrsusBoot WebFailsafe/API;
- `Mode=TRANSITION/PERSISTENT`;
- Ursus-specific boot policy/writers;
- зависимость от transition staging slot после завершения migration;
- Nokia A/B slot layout как финальный OpenWrt storage target;
- factory/non-UBI final layout.

TRANSITION используется только как временная RAM-среда и не ухудшает Vanilla status, если после migration он не участвует в boot chain.

## 13. CI contract

Для каждой поддерживаемой композиции CI должен проверять:

- layer boundaries common/SoC/board/storage/policy;
- profile resolver и связь с UrsusFlasher catalog;
- WebFailsafe board identity через policy;
- отсутствие чужой board identity в итоговом binary;
- source-level runtime role selection;
- правильный bootcmd/runtime dispatch для каждой role;
- требуемые SoC/network/MTD symbols;
- environment ownership policy;
- размер/сжатие BL33;
- XG140 native FIP repacker self-test;
- host-side imports/routes operator kit;
- packaged payload SHA checks;
- shared OpenWrt firmware bundle не дублирует идентичные MD/MF artifacts;
- MD и MF имеют отдельные board-specific transition/bootchain manifests там, где payloads/layout различаются;
- Vanilla manifests разрешают только UBI final target;
- persistent bundle продолжает содержать OpenWrt factory payload и initramfs recovery images.

Актуальная multimodel baseline:

```text
workflow run: 34900134319
head:         5993429874f7ec2287931a4a5bcba199de826fe2
conclusion:   SUCCESS
artifact:     UrsusFlasher-Airoha-Multimodel-HWTEST-5993429874f7ec2287931a4a5bcba199de826fe2
artifact id:  10371938945
digest:       sha256:8714a98ede51fb9d3615cff1ebbe0fec68cdced86f9d98f35152e8edaecfab4e
```

Эта baseline не равна hardware acceptance новых transition/vanilla путей.

## 14. Hardware acceptance XG140

CI PASS не равен hardware acceptance.

Порядок допуска:

1. native-hybrid candidate строится только из backup/live boot area текущего XG140;
2. до erase проверяются размер, FIP structure, protected-env boundary и lineage;
3. запись boot area завершается полным `0x80000` readback/compare;
4. cold boot подтверждает `BootROM -> native FIP -> UrsusBoot`;
5. `ursusdispatch -> ursusstockboot -> stock MASTER` подтверждается на железе;
6. затем отдельно принимается Nokia A/B selector/fallback policy;
7. только после этого XG140 persistent path перестаёт быть engineering-only.

## 15. Правило расширения

Новая Airoha-модель должна по возможности добавляться набором:

```text
existing/new SoC module
+ board DTS
+ storage policy
+ board boot/layout policy
+ runtime roles
+ profile entry
+ hardware acceptance tests
```

Новый форк common UrsusBoot, копия WebFailsafe или копия `ursusdispatch/ursusstock` допустимы только при доказанной архитектурной несовместимости.

## 16. Repository / operator contract

- Не менять `main` без прямой команды оператора.
- Не merge/tag/release без прямой команды.
- Не коммитить device backups, plaintext credentials, serial/GPON secrets.
- Перед первым запуском UrsusFlasher на stock Nokia выполнить аппаратный factory reset удержанием Reset **30+ секунд**, дождаться полной загрузки stock Web.
- Для stock -> transition обязателен полный verified backup **всех** разделов текущего `/proc/mtd`.
- EXPERT/HWTEST — минимальная operator ceremony; не добавлять бессмысленные policy-gates.
- Для штатной destructive операции достаточно одного осмысленного `y/N` после автоматического preflight-summary, если конкретный emergency flow не задан как unattended.
- Structural checks/readback выполняются автоматически и не требуют дополнительных подтверждений.
- После начала записи нельзя автоматически переключаться на другой writer/backend.
- Vanilla MD/MF migration имеет только UBI final target; factory/non-UBI относится только к persistent UrsusBoot product path.
- OpenWrt firmware payloads используются как shared bundle там, где один artifact реально совместим с несколькими board profiles; board-specific остаются только действительно различающиеся transition/bootchain/layout payloads.

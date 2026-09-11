# UrsusBoot / UrsusFlasher — техническое задание
## Редакция 5.39 — Vanilla Transition UrsusBoot / official OpenWrt handoff

**Дата редакции:** 2026-09-12  
**Целевые устройства:** Nokia XG-040G-MD / Nokia XG-040G-MF  
**SoC:** Airoha AN7581 / Airoha AN7583  
**Статус:** authoritative delta над v5.38. При конфликте требований v5.39 имеет приоритет только для нового Vanilla Transition path; persistent UrsusBoot path и frozen MD reference из v5.38 сохраняются без изменения.

---

## 1. Цель

Добавить в UrsusFlasher отдельный режим для пользователей, которым нужен **полностью штатный OpenWrt boot chain без persistent UrsusBoot**, но при этом нужен безопасный без-UART переход со stock Nokia.

Новый путь:

```text
Nokia stock
  -> Web/Telnet root
  -> полный verified backup
  -> временный transition payload в stock staging/secondary area
  -> device-derived patch stock U-Boot environment
  -> reboot
  -> UrsusBoot TRANSITION работает из RAM
  -> установка официального OpenWrt boot chain
  -> создание canonical OpenWrt UBI layout
  -> запись official/canonical OpenWrt UBI sysupgrade
  -> mandatory readback/verification
  -> transition UrsusBoot исчезает из persistent NAND
  -> следующий boot = vanilla OpenWrt
```

Нормальная установка не требует UART. UART/BootROM остаётся аварийным recovery path для уже повреждённого устройства или аппаратного тестирования новой transition-сборки.

---

## 2. Не изобретать новый stock bootstrap: использовать MedveFlasher contract

Stock -> transition handoff должен использовать доказанный на живых **MD и MF** механизм из `Medvedolog/nokia-router-medveflasher`, а не новый kexec/chainloader из stock Linux.

Нормативная основа MedveFlasher:

1. получить root через штатный stock Web/Telnet transport;
2. снять restore-grade backup до первой записи;
3. взять U-Boot environment из backup **этого же устройства**;
4. сохранить все bytes и все env variables кроме `bootcmd`;
5. изменить только `bootcmd`;
6. пересчитать CRC32 environment;
7. записать целиком соответствующий erase-block;
8. положить временный payload в проверенную transition staging area;
9. reboot, после которого stock tcboot сам загружает transition payload в RAM.

Проверенный MedveFlasher environment contract для текущих MD/MF:

```text
mtd0 / stock boot-area size     0x80000
env erase-block offset          0x60000
env erase-block size            0x20000
environment offset in block     0x1c000
environment absolute offset     0x7c000
environment size                0x4000
```

MedveFlasher reference boot command для Linux transition:

```text
flash read 0xc0000 0x900000 0x92000000; bootm 0x92000000
```

Этот exact Linux `bootm` payload contract **не объявляется автоматически подходящим для UrsusBoot**. Доказанным считается сам механизм: device-derived env patch + одна переменная `bootcmd` + stock NAND staging + tcboot handoff после reboot.

Для UrsusBoot TRANSITION разрешается board-specific команда загрузки/передачи управления (`bootm`, `go` либо другой валидированный tcboot primitive), но она должна менять только `bootcmd` и обязана пройти отдельный hardware acceptance на MD и MF до включения destructive OpenWrt install.

Номер `mtdX` не должен быть жёстко зашит как универсальный контракт. Staging region определяется по фактическому stock layout/board profile тем же способом, что и в proven MedveFlasher path. Если на текущей ревизии это соответствует secondary slot, UI показывает его имя, physical span и SHA256 до записи.

---

## 3. UrsusBoot TRANSITION — отдельный продуктовый режим

`UrsusBoot TRANSITION` не является persistent UrsusBoot и не должен оставаться конечным загрузчиком устройства.

Обязательная runtime identity:

```text
Product: UrsusBoot
Mode: TRANSITION
Persistence target: NONE
Final target: OFFICIAL_OPENWRT
Board: Nokia XG-040G-MD | Nokia XG-040G-MF
SoC: AN7581 | AN7583
```

Transition build должен:

- запускаться после stock tcboot handoff и полностью работать из RAM;
- иметь Ethernet + Web Recovery + Web console + operation log;
- видеть SPI-NAND и фактическую geometry;
- уметь читать/проверять stock backup, RI/BOSA/factory identity;
- валидировать официальный board-specific OpenWrt boot chain;
- валидировать canonical OpenWrt UBI sysupgrade;
- выполнять UBI migration без зависимости от stock rootfs;
- не иметь штатного режима установки самого себя persistent;
- не использовать stock boot как автоматический fallback после начала destructive final-write transaction;
- не требовать UART в пользовательском installation path.

После старта TRANSITION host обязан доказать по API/runtime identity, что запущен именно `Mode=TRANSITION`, правильная board family и разрешён `OFFICIAL_OPENWRT` target. Простого HTTP 200 недостаточно.

---

## 4. Vanilla install transaction

До destructive write обязательны:

```text
live board identity
-> verified full stock backup
-> verified device identity / RI / BOSA / MAC / serial where applicable
-> transition staging readback
-> patched env readback + CRC32 + changed-keys == [bootcmd]
-> reboot into UrsusBoot TRANSITION
-> transition runtime identity PASS
-> NAND geometry/bad-block preflight
-> official OpenWrt artifacts structural/hash validation
-> final operation summary
-> one meaningful y/N
```

После подтверждения выполняется одна конечная transaction:

```text
prepare official OpenWrt layout
-> create/format canonical UBI
-> create/write required OpenWrt boot/data volumes
-> restore/preserve board identity data in the locations expected by upstream OpenWrt
-> write canonical UBI sysupgrade
-> verify all written components
-> commit production BL2/preloader LAST
-> full readback / hash verification of every critical final component
```

Инвариант **BL2 LAST** сохраняется. До финального commit нельзя объявлять установку завершённой.

После начала final write запрещён автоматический fallback на другой writer/backend.

---

## 5. Что означает «самоудаление» Transition UrsusBoot

Самоудаление — это не отдельная рискованная команда «стереть себя», а **постусловие конечной OpenWrt migration**.

После успешной установки:

- stock patched environment больше не должен быть активным boot environment;
- transition staging bytes не должны оставаться используемым boot target;
- persistent UrsusBoot BL33/FIP не должен находиться в конечном OpenWrt boot chain;
- финальный BL33 должен идентифицироваться как официальный/pinned OpenWrt U-Boot для соответствующей платы;
- final NAND layout должен соответствовать canonical OpenWrt layout, а не промежуточному stock/transition layout.

Если final OpenWrt layout физически перекрывает transition staging region, отдельное erase «для красоты» не выполняется: transition payload исчезает естественно при migration.

Если конкретный board profile оставляет staging region вне final OpenWrt layout, его очистка допускается только **после** полного final verification и только если это не добавляет новый boot-risk. Функциональный критерий важнее косметического стирания неиспользуемых bytes.

После финального reboot `/api/status` UrsusBoot не должен быть доступен; нормальная загрузка должна идти через official OpenWrt boot chain.

---

## 6. Official / vanilla означает именно upstream-compatible artifacts

Vanilla mode не должен незаметно подменять официальный OpenWrt bootloader модифицированным UrsusBoot payload.

Для каждого board profile должны быть pinned:

- official/upstream-compatible BL2/preloader;
- official/upstream-compatible BL31/FIP/U-Boot components, где они требуются layout;
- canonical OpenWrt UBI sysupgrade image;
- expected sizes/hashes/build provenance.

UrsusFlasher может валидировать, транспортировать и устанавливать эти компоненты, но не должен сохранять UrsusBoot-specific code в конечном boot chain vanilla mode.

Любой локальный compatibility patch, если он временно необходим до попадания upstream, должен быть явно показан пользователю как `NOT FULLY VANILLA` и не может называться official vanilla target.

---

## 7. Board data / identity

Vanilla transition не имеет права терять индивидуальные данные устройства.

Перед UBI migration должны быть извлечены и верифицированы все необходимые board-specific данные, включая по фактическому layout:

- RI;
- BOSA;
- factory MAC;
- serial / GPON identity;
- иные calibration/factory data, используемые upstream OpenWrt для этой платы.

После migration они должны быть размещены именно там и в том формате, который ожидает canonical OpenWrt layout/DTS/UBI contract.

Нельзя считать сохранением identity факт наличия backup-файла на ПК: acceptance требует также доказать, что production OpenWrt после reboot видит правильные значения.

---

## 8. UI / режимы установки

ONE-KEY после определения поддерживаемой stock Nokia должен предлагать два разных конечных продукта:

```text
1. UrsusBoot + OpenWrt
   Persistent UrsusBoot с Web Recovery.

2. Vanilla OpenWrt
   Временный UrsusBoot TRANSITION используется только для установки.
   В конечном NAND остаётся официальный OpenWrt boot chain без UrsusBoot.
```

В `EXPERT` должны быть отдельно доступны диагностические стадии Vanilla Transition без запуска final write.

Пользователь не должен выбирать вручную `mtd4`, physical offsets или boot command. UI показывает resolved staging region и planned bootcmd как часть preflight, backend выбирает их по board profile и фактическому stock layout.

---

## 9. Hardware acceptance

Наличие proven MedveFlasher MD/MF transition **не является доказательством**, что новый UrsusBoot payload можно тем же tcboot command chainload-ить без проверки.

До разрешения vanilla destructive path отдельно для MD и MF должны пройти:

```text
stock boot
-> backup PASS
-> stage UrsusBoot TRANSITION
-> env patch/readback PASS
-> reboot without UART intervention
-> tcboot loads transition payload
-> UrsusBoot TRANSITION network/Web/API PASS
-> cold reboot repeatability PASS
```

И только после этого разрешается тестировать:

```text
TRANSITION
-> official OpenWrt boot chain write
-> UBI migration
-> sysupgrade
-> BL2 LAST
-> readback PASS
-> power cycle
-> official OpenWrt U-Boot boot PASS
-> OpenWrt userspace PASS
-> MAC/RI/BOSA/serial identity PASS
-> UrsusBoot persistent presence ABSENT
```

Первый hardware acceptance выполняется с UART logger подключённым **как наблюдателем**, но UART не должен использоваться для ввода команд или обязательного bootstrap. После доказательства путь считается normal no-UART installation path.

Power-loss tolerance должна описываться честно по стадиям. Наличие BL2-LAST уменьшает destructive window, но не даёт права обещать без-UART recovery после произвольного обрыва питания посреди NAND migration.

---

## 10. Что запрещено

Для Vanilla Transition path запрещено:

- форматировать production NAND прямо из живого stock rootfs как штатный путь;
- kexec/произвольный Linux chainloader вместо proven MedveFlasher stock handoff без отдельного решения ТЗ;
- менять более одной stock env variable без доказанной необходимости;
- использовать generic/factory mtd0 вместо device-derived environment источника;
- жёстко считать `mtd4` одинаковым staging target на всех ревизиях;
- ставить persistent UrsusBoot, а затем молча заменять его vanilla U-Boot как штатную реализацию этого режима;
- объявлять vanilla success до cold boot в official OpenWrt U-Boot + production OpenWrt;
- автоматически reboot-ить после финальной destructive операции, если текущий общий safety contract требует ручного краткого RESET.

---

## 11. Реализационный приоритет

Эта редакция добавляет **новый опциональный конечный режим**, но не меняет текущий приоритет доведения и аппаратной проверки persistent MF path.

Рекомендуемый порядок реализации:

```text
A. зафиксировать MedveFlasher transition contract как reusable backend
B. собрать UrsusBoot TRANSITION для MD/MF
C. доказать tcboot -> UrsusBoot handoff без destructive writes
D. добавить official OpenWrt boot-chain installer
E. добавить canonical UBI migration + board-data restore
F. полный MD hardware cycle
G. полный MF hardware cycle
H. только после обоих PASS включать Vanilla OpenWrt в ONE-KEY
```

Главный принцип:

> **Не ставить UrsusBoot навсегда там, где пользователь выбрал vanilla, но использовать UrsusBoot как одноразовую независимую RAM-среду, чтобы не переписывать NAND из работающего stock rootfs. Stock bootstrap при этом не изобретать заново — брать доказанный на MD/MF MedveFlasher mechanism.**

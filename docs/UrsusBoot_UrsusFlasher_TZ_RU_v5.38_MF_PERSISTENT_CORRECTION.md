# UrsusBoot / UrsusFlasher — техническое задание
## Редакция 5.38 — MF persistent correction / unified MD+MF architecture

**Дата редакции:** 2026-09-10  
**Целевые устройства:** Nokia XG-040G-MD / Nokia XG-040G-MF  
**SoC:** Airoha AN7581 / Airoha AN7583  
**Статус:** authoritative corrective delta над v5.37. При конфликте требования v5.38 имеют приоритет.

---

## 1. Цель текущего этапа

Текущий приоритет разработки — закончить **persistent UrsusBoot для Nokia XG-040G-MF / AN7583** на общей архитектуре MD/MF, не меняя доказанное аппаратно поведение Nokia XG-040G-MD.

В этой редакции:

1. аппаратно опровергнутый MF PERSIST2 path запрещается к дальнейшей прошивке;
2. persistent MF install переносится в штатный `UrsusFlasher -> EXPERT` transaction path;
3. MF candidate строится из фактического boot-area конкретного устройства, а не из отдельного OpenWrt-style двухкомпонентного FIP donor;
4. MD TEST61 фиксируется как reference line и не является площадкой для рефакторинга MF;
5. фиксируется общая модель сборки U-Boot `common + board + mode`;
6. будущая RAM Recovery-архитектура MD/MF описывается нормативно, но её расширение не блокирует завершение persistent MF.

---

## 2. MD TEST61 — frozen hardware reference

MD persistent path считается доказанным длительной аппаратной серией и должен сохраняться без функционального изменения при работах над MF.

Reference identity:

```text
UrsusBoot MD TEST61 persistent FIP
size    503808
sha256  3c922e4256b6047376a7d445006e6cb2a4485bb412747033a77defd15e42fcea

UrsusBoot MD TEST61 raw BL33
size    860808
sha256  43296d98686ada9e4e13c5a5a49430372abf45e9bd0fc8eae837920e8ba5224d

UrsusBoot MD TEST61 LZMA BL33
size    291160
sha256  bec245ab0b10e3fffcc2f0a482c2c3b97b03577b4a03c436857243cd68ff9d29
```

До отдельного осознанного MD release изменение любого из этих payload hashes является regression и должно останавливать MF merge/build acceptance.

Дополнительно сохраняются доказанные MD-инварианты:

- direct stock install использует device-derived `mtd0`;
- stock prefix и stock environment сохраняются;
- destructive operation подтверждается одним осмысленным `y/N` после preflight summary;
- после записи выполняется полный readback/verification;
- при STOCK -> UBI transition BL2 commit выполняется последним;
- отсутствие нового аппаратного MF-функционала не является основанием менять proven MD writer.

---

## 3. MF hardware evidence — фактическое состояние

### 3.1. Что доказано в RAM

Для Nokia XG-040G-MF / AN7583 аппаратно доказаны:

- BootROM UART/XMODEM bootstrap;
- запуск UrsusBoot в RAM;
- UART console;
- Ethernet/Web runtime;
- LAN2/LAN3/LAN4 hardware path;
- SPI-NAND detection/read path.

Последний живой MD/MF RAM payload не является доказательством persistent NAND boot, но является рабочей recovery/bring-up границей.

### 3.2. Что произошло при PERSIST2

После исправления FIP parser операция PERSIST2:

```text
candidate validation  PASS
NAND erase/write      PASS
byte-exact readback   PASS
cold boot             FAIL
```

Наблюдение после power-cycle:

```text
обычное включение питания -> UART silence / normal NAND boot отсутствует
Reset удерживается при включении -> Airoha BootROM жив, появляется "Press x"
```

Следовательно:

- SoC не повреждён;
- BootROM и UART recovery остаются доступны;
- сам факт успешного write/readback **не доказывает bootability**;
- аппаратная регрессия находится в persistent boot-chain/layout/candidate path до нормального U-Boot runtime.

### 3.3. Device stock boot-area evidence

Снятый до/для восстановления MF boot-area образ:

```text
size    0x80000 (524288 bytes)
sha256  144d63272049eeb7122a01f2f3a0192b874ca4c68c10a5b4726fa4c2e84ac1bf
FIP physical offset 0x800
stock FIP TOC entries: 9
stock environment: 0x7c000..0x7ffff, CRC valid
```

Это **evidence конкретного аппаратного экземпляра**, а не основание безусловно объявить все MF в мире byte-identical. Новый installer обязан получать boot-area с целевого устройства и анализировать его фактическую структуру.

---

## 4. Пойманные MF regression и исправление статусов v5.37

### 4.1. PERSIST1 validator regression

PERSIST1 искал runtime identity strings внутри compressed FIP и мог отвергать корректный compressed candidate до записи.

Статус: **FIXED AS VALIDATOR BUG / HISTORICAL**.

Нельзя использовать наличие plaintext identity внутри compressed payload как обязательный structural gate.

### 4.2. PERSIST2 compact-TOC parser regression

Первоначальный parser требовал `toc_end >= 0x400`, тогда как корректный compact 2-entry FIP имел TOC end около `0x88`.

FIPPARSE1 убрал ложное ограничение.

Статус: **PARSER FIXED, BUT DOES NOT VALIDATE PERSISTENT ARCHITECTURE**.

Исправленный parser доказал только структурную разбираемость candidate; он не доказал совместимость candidate со stock NAND boot chain.

### 4.3. PERSIST2 persistent boot regression

PERSIST2 builder использовал `nokia-xg-040g-mf-an7583-production-bl31-uboot.fip` и явно ожидал **2-entry BL31+BL33 FIP**. Затем этот FIP помещался в stock-style boot-area на physical `0x800`.

Аппаратный stock boot-area рассматриваемого MF содержит **9-entry FIP** с ранними boot/config/certificate entries, native BL31 и NT_FW/BL33.

OpenWrt upstream MF persistent layout, напротив, имеет отдельный `bl2` physical partition `0x0..0x1ffff` и UBI с `0x20000`, а `ubi-bl31-uboot.fip` является компонентом этой OpenWrt UBI boot architecture. Reference:

`https://git.openwrt.org/openwrt/openwrt/tree/package/boot/uboot-airoha/patches/402-add-nokia-xg-040g-mf.patch`

Следовательно, перенос двухкомпонентного OpenWrt-style FIP внутрь существующего stock-style boot-area без полного перехода boot architecture является недоказанным и на текущем железе **фактически завершился cold-boot failure**.

Статус PERSIST2: **HW_REJECTED — DO NOT FLASH**.

Нельзя утверждать, что единственной причиной является конкретно BL31 или конкретная отсутствующая TOC entry: silicon-level root cause не локализован до одной записи. Доказано достаточное для инженерного решения: **PERSIST2 candidate/writer architecture непригодна для продолжения**.

---

## 5. Явная отмена устаревших указаний v5.37

Следующие требования/инструкции v5.37 отменяются:

- PERSIST2 не является текущим разрешённым MF persistent path;
- `MF3_PERSIST2_FLASH_THIS_FIP.fip` не является следующим файлом для аппаратной прошивки;
- успешный validator/readback PERSIST2 не считается достаточным acceptance;
- повторная прошивка PERSIST2/FIPPARSE1 после этой редакции запрещена как штатный тест;
- отдельный `CMD + Python + device-side PERSIST writer` не является целевой архитектурой установки persistent UrsusBoot.

Legacy PERSIST1/PERSIST2 scripts/workflows могут сохраняться только для forensic/reproducibility и должны быть явно помечены `REJECTED / NOT FOR FLASH`.

---

## 6. Новый MF persistent install contract

### 6.1. Штатная точка входа

Persistent установка MF выполняется только через:

```text
UrsusFlasher
  -> EXPERT
  -> Установить / обновить UrsusBoot
  -> MF board backend
```

Отдельный experimental writer не должен быть пользовательским installation path.

### 6.2. Device-derived candidate

Для stock-layout MF:

```text
read actual device boot-area / mtd0
-> save original backup
-> parse actual stock FIP
-> candidate = byte copy of device boot-area
-> preserve stock prefix
-> preserve every non-BL33 FIP entry and native early-boot lineage
-> preserve native BL31
-> replace only NT_FW/BL33 with UrsusBoot-MF BL33
-> preserve stock environment and unknown device-specific bytes
-> validate candidate
-> one y/N
-> erase/write once
-> full readback/hash
-> manual cold boot
```

При необходимости изменения TOC из-за нового BL33 size разрешено менять только поля, неизбежно связанные с NT_FW/BL33 размером/end-of-FIP. Все не относящиеся к BL33 payload bytes и metadata должны проверяться на сохранение.

### 6.3. Не переносить MD writer буквально

MD и MF используют общий transaction framework, но MF backend не должен слепо наследовать:

- MD exact prefix hashes;
- MD BL2 identity assumptions;
- MD whole-FIP replacement strategy;
- MD tcboot-specific layout logic.

Общими должны быть orchestration/preflight/backup/confirmation/write/readback/journal, а geometry/FIP patch rules — board-specific.

### 6.4. Первый persistent MF hardware acceptance

Первый новый MF persistent candidate должен минимизировать одновременно меняемые переменные:

- native stock early stages сохраняются;
- native stock BL31 сохраняется;
- меняется только BL33 на MF UrsusBoot runtime candidate;
- после записи обязателен cold power-cycle без удержания Reset;
- только после доказанного NAND boot разрешается расширять MF self-update/UBI migration path.

---

## 7. Unified UrsusBoot build architecture

Целевая конфигурация:

```text
seed/reference
  + ursusboot-common.cfg
  + ursusboot-board-md.cfg | ursusboot-board-mf.cfg
  + ursusboot-runtime.cfg | ursusboot-recovery.cfg
  -> olddefconfig
  -> resolved-config contract check
```

`common` содержит только board-independent capabilities. `board-*` содержит SoC/DTS/PCS/pinctrl/board-specific environment and hardware rules. `mode` содержит runtime/recovery policy.

До завершения миграции старые full configs остаются seed/reference. Их наличие допустимо; они не являются местом дальнейшего копирования общих опций.

MD TEST61 build должен оставаться отдельным regression job и проверять frozen payload hashes.

---

## 8. Naming и build identity

`MD` и `MF` — model/board IDs, а не номера стадий разработки.

Публичные artifact names не должны кодировать `MF2`, `MF3`, `MD3`, `PERSIST1`, `PERSIST2` как будто это версии модели.

Допустимая dev identity:

```text
UrsusBoot 0.1.0-TEST61
Board: Nokia XG-040G-MD / AN7581
```

или

```text
UrsusBoot 0.1.0-TEST61
Board: Nokia XG-040G-MF / AN7583
```

`TEST61` временно допустим как dev/build suffix.

Версия UrsusBoot является обязательной runtime identity и должна выводиться:

1. в UART startup banner;
2. в Web status/header;
3. в UrsusFlasher operation/diagnostic log при первом успешном контакте.

Источник версии должен быть единым; Web/UART/host не должны содержать независимо захардкоженные несовпадающие версии.

---

## 9. Recovery RAM — последующий общий MD/MF этап

Расширение Recovery **не является блокером текущего MF persistent acceptance**, но архитектура фиксируется заранее.

Recovery UrsusBoot — отдельная RAM-only сборка, вход только через Airoha BootROM/UART bootstrap. Она не ограничена persistent boot-area `0x80000`; размер ограничивается реальной RAM/bootstrap geometry и проверяется CI.

Обязательные возможности для обеих моделей:

- Web UI;
- Web console;
- live Web operation log;
- UART console/log;
- TFTP client и TFTP server;
- XMODEM bootstrap;
- raw MTD read/erase/write;
- bad-block diagnostics;
- backup/restore отдельных MTD и полного NAND;
- recovery из собственного или явно выбранного совместимого foreign backup;
- возможность operator-assisted RI/MAC/serial repair при необходимости;
- UBI attach/format/rebuild/create volumes/write/read;
- восстановление OpenWrt/sysupgrade при полностью отсутствующей или повреждённой UBI/layout;
- FIT/FIP inspect, hash/readback, bootm.

Recovery policy не должен требовать существования исправной partition map/UBI/FIP как условия самого recovery. В explicit raw recovery отсутствие/неизвестность layout является warning, а не blanket blocker.

Hard gates сохраняются только для механической корректности операции:

- flash обнаружена;
- geometry/bounds/alignment пригодны;
- RAM buffers безопасны;
- bad-block semantics учитываются;
- destructive high-level operation имеет один `y/N` после summary;
- после записи выполняется readback/hash.

Recovery использует `ENV_IS_NOWHERE` и не выполняет persistent write автоматически при старте.

USB storage **не входит в текущий scope**. Для тяжёлых transfer после UART bootstrap используется TFTP/Web.

---

## 10. MF persistent Definition of Done

MF persistent этап считается завершённым только если одновременно выполнено:

1. старый PERSIST2 path недоступен как рекомендуемый/случайно запускаемый flash route;
2. MF persistent candidate создаётся host-side из actual device boot-area;
3. parser принимает реальную stock 9-entry FIP geometry без hardcoded fictitious TOC minimum;
4. NT_FW/BL33 определяется структурно по FIP UUID, а не поиском plaintext marker в compressed payload;
5. prefix сохраняется byte-exact;
6. все non-BL33 FIP payloads сохраняются byte-exact;
7. native BL31 сохраняется byte-exact;
8. stock ENV сохраняется byte-exact;
9. candidate FIP physical end не пересекает ENV/другие protected areas;
10. перед write автоматически создаётся backup фактического device boot-area;
11. destructive write требует ровно один осмысленный `y/N`;
12. write выполняется одним transactional path и завершается полным readback/hash;
13. cold power-cycle без Reset загружает UrsusBoot-MF из NAND;
14. UART startup печатает версию/board/SoC;
15. Web/Ethernet runtime после persistent boot аппаратно подтверждён;
16. аварийный BootROM UART path остаётся доступен;
17. MD TEST61 frozen hashes остаются неизменными;
18. отдельные MF changes не меняют proven MD install semantics.

До выполнения пункта 13 `persistent_write_enabled` для MF в board profile остаётся `false`, а новый backend имеет статус `PENDING_HW_ACCEPTANCE`.

---

## 11. Приоритет исполнения после этой редакции

```text
A. сохранить/восстановить текущий MF через RAM recovery и stock boot-area backup
B. построить MF runtime UrsusBoot на unified common+board config
C. реализовать host-side device-derived MF mtd0/FIP BL33 patcher
D. добавить synthetic + real-backup offline validation
E. провести один контролируемый MF persistent write/readback
F. выполнить cold-boot acceptance
G. только после PASS открыть MF persistent install в EXPERT
H. затем вернуться к расширению unified MD/MF RAM Recovery
```

Ни один шаг B-G не должен требовать изменения frozen MD TEST61 payload.
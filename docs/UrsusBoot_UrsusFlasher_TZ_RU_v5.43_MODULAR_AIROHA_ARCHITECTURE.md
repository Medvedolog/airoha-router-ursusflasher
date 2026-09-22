# UrsusBoot / UrsusFlasher — техническое задание
## Редакция 5.43 — модульная многомодельная архитектура Airoha

**Дата редакции:** 2026-09-14  
**Статус:** архитектурная delta над v5.38–v5.42.  
**Цель:** одна кодовая база UrsusBoot для нескольких Airoha-моделей без копирования загрузчика под каждую плату.

---

## 1. Основной принцип

UrsusBoot является общим boot/recovery supervisor для поддерживаемых Airoha SoC и плат.

Новая модель не должна приводить к появлению отдельного независимого форка `cmd/ursusdispatch.c`, `cmd/ursusstock.c`, WebFailsafe или сетевого стека.

Композиция сборки:

```text
common core
  -> SoC capability
  -> board identity / DTS
  -> storage/environment policy
  -> board boot/layout policy
  -> optional model-specific hardware delta
```

UrsusFlasher остаётся внешним high-level orchestrator:

```text
backup / restore / manifests / compatibility / identity repair / operator UX
                       |
                       v
              HTTP/TFTP/UrsusBoot API
                       |
                       v
              UrsusBoot low-level backend
```

WebFailsafe не превращается во второй UrsusFlasher и не получает россыпь отдельных кнопок для каждого вида полного восстановления.

---

## 2. Базовые профили

### XG-040G-MD

```text
profile:      xg040-md
SoC:          AN7581
derivation:   native-md
environment:  UBI redundant
```

Это базовая hardware-proven AN7581 реализация для общего dispatcher/StockBridge/WebFailsafe кода.

### XG-040G-MF

```text
profile:      xg040-mf
SoC:          AN7583
derivation:   native-mf
environment:  UBI redundant
```

MF использует тот же common core, но отдельный SoC layer, board layer и board policy.

### XG-140G-MD

```text
profile:      xg140-md
SoC:          AN7581
derivation:   md-derived
environment:  vendor env preserved / ENV_IS_NOWHERE
```

XG140 рассматривается как MD-derived AN7581 board, а не как независимый новый загрузчик.

---

## 3. Разделение configuration layers

### `ursusboot-common.cfg`

Только model-independent возможности:

- FIT / bootm infrastructure;
- LWIP/network;
- TFTP/WGET;
- generic MTD/SPI-NAND;
- logging/console;
- GPIO/LED framework;
- Airoha Ethernet framework;
- crypto/hash primitives.

Запрещено помещать сюда:

- конкретный `CONFIG_TARGET_AN758x`;
- конкретный DTS;
- layout одной модели;
- persistent env конкретной модели.

### SoC layer

Примеры:

```text
ursusboot-soc-an7581.cfg
ursusboot-soc-an7583.cfg
```

Содержит только SoC-specific target/PCS/pinctrl selections.

### Board layer

Примеры:

```text
ursusboot-board-md.cfg
ursusboot-board-mf.cfg
ursusboot-board-xg140.cfg
```

Содержит identity/DTS/FDT платы. Не содержит SoC selection и storage policy.

### Storage/environment layer

Примеры:

```text
ursusboot-storage-ubi-redundant.cfg
ursusboot-storage-env-nowhere.cfg
```

XG140 использует `ENV_IS_NOWHERE`, потому что `0x7c000..0x7ffff` принадлежит stock Nokia environment и не является UrsusBoot persistent env.

---

## 4. Board policy module

Board-specific boot/layout ABI задаётся одним policy header, выбранным профилем.

Базовые реализации:

```text
ursusboot/board-policies/xg040-md.h
ursusboot/board-policies/xg040-mf.h
ursusboot/board-policies/xg140-md.h
```

Policy определяет как минимум:

- MASTER/SLAVE physical bases;
- slot size;
- vendor env location;
- stock image header (`HDR2`/`HDR3`);
- FIT limit;
- stock root mapping;
- SerDes tcboot/Linux arguments;
- допустимость UBI autodetect;
- допустимость legacy direct factory FIT probe;
- optional stock oracle values.

Common `ursusdispatch.c` и `ursusstock.c` не должны содержать разбросанные model-specific offsets и magic values.

---

## 5. XG140 как MD-derived board

XG140 наследует от MD общий алгоритм:

```text
BootROM / native trusted firmware
        -> UrsusBoot BL33
        -> ursusdispatch
        -> StockBridge / OpenWrt path
```

При этом XG140 не должен автоматически наследовать недоказанные MD assumptions.

Текущая XG140 policy:

```text
SoC                         AN7581
MASTER                      0x000c0000
SLAVE                       0x02940000
slot size                   0x02880000
vendor env                  0x0007c000 + 0x4000
stock header                HDR2 (до HW acceptance считается profile assumption)
UBI autodetect              disabled
legacy factory-FIT probe    disabled
MD SerDes overrides         disabled
SerDes source               vendor environment
```

MD-derived означает повторное использование доказанного алгоритма, а не безусловное копирование всех MD-констант.

---

## 6. XG140 persistent mtd0

XG140 не получает XG-040 donor FIP.

Источник:

```text
mtd0_bootloader.bin(.gz) конкретного XG140
```

Реконструкция:

```text
0x000000..0x0007ff   live/native prefix, сохранить
0x000800..FIP_END    native XG140 FIP
                       все native entries сохранить
                       NT_FW/BL33 заменить на XG140 profile UrsusBoot
...
0x07c000..0x07ffff   live stock env, сохранить byte-for-byte
```

Текущий реальный donor подтверждает возможность укладки persistent BL33 в native FIP с запасом до protected env.

Сырой `u-boot.bin` через stock tcboot `go` не является production install path и аппаратно отвергнут XG140 тестом (`Application terminated, rc=1`).

---

## 7. Stock Linux

Stock Nokia Linux должен грузиться persistent UrsusBoot через общий StockBridge, как это уже работает на MD.

Целевая схема XG140:

```text
BootROM
  -> native XG140 FIP
  -> UrsusBoot
  -> ursusdispatch
       |-> OpenWrt
       `-> Nokia stock MASTER/SLAVE
```

Полный возврат к stock tcboot не является обязательным условием загрузки stock Linux.

---

## 8. A/B selector как отдельный модуль

Текущий common StockBridge умеет валидировать и загружать MASTER/SLAVE, но исторический `ursusdispatch` вызывает MASTER по умолчанию.

Следующая архитектурная capability — отдельный stock A/B selector policy.

Из reverse engineering Nokia уже известна 20-byte state structure:

```text
active
curimg
startok
count
reserved
```

Целевой selector:

```text
read flag
  -> requested = active
  -> validate requested slot
  -> if valid: boot requested
  -> otherwise validate alternate
  -> alternate valid: boot alternate
  -> both invalid: WebFailsafe
```

`flagback` не зеркалируется UrsusBoot автоматически: его роль остаётся частью vendor boot-time rollback state machine до отдельного доказательства.

---

## 9. UrsusFlasher boundary

UrsusBoot предоставляет primitives и deterministic state machines.

UrsusFlasher отвечает за:

- выбор board profile;
- backup discovery;
- manifests;
- donor compatibility;
- full restore order;
- identity preservation/repair;
- HTTP/TFTP transfer orchestration;
- destructive-operation UX;
- journaling.

Таким образом добавление новой Airoha-модели должно в нормальном случае требовать:

```text
1 SoC layer (если SoC ещё неизвестен)
1 board DTS/overlay
1 board policy
1 profile registry entry
model-specific validation/tests
```

а не копирование UrsusBoot целиком.

---

## 10. Hardware acceptance boundary

Модульная архитектура и успешная CI-сборка не равны аппаратной приемке.

Для XG140 отдельно должны быть доказаны:

1. cold boot reconstructed native-hybrid mtd0;
2. persistent UrsusBoot network/WebFailsafe;
3. stock `nsb_master` boot через common StockBridge;
4. stock `nsb_slave` boot;
5. selector/fallback behavior;
6. OpenWrt path;
7. recovery/readback after an interrupted non-boot-area operation.

До этого XG140 profile остаётся engineering/pre-HW-acceptance.

---

## 11. Delta 2026-09-22 — Vanilla pregnant migration, fallback и политика safety-gates

Эта delta дополняет модульную архитектуру требованиями, выявленными при реализации EXPERT item 4 `Stock Nokia -> Vanilla OpenWrt`.

### 11.1. Целевая цепочка Vanilla item 4

Для MD используется промежуточная RAM-only цепочка без постоянного UrsusBoot в конечной системе:

```text
stock tcboot
 -> stock-compatible SLOT2
 -> preserved Nokia FIP/HDR2/FIT envelope
 -> kernel@1 ARM64 handoff
 -> RAM-only pregnant UrsusBoot
 -> bootm OpenWrt pregnant initramfs
 -> autonomous stage2
 -> canonical OpenWrt UBI layout
 -> pinned production OpenWrt
 -> Vanilla FIP
 -> BL2/preloader LAST
```

Persistent UrsusBoot и WebFailsafe являются отдельным продуктом и не должны оставаться в финальной Vanilla boot-chain.

### 11.2. Stock A/B rollback должен сохраняться до физически последней безопасной границы

До первой destructive операции: MASTER/SLOT1 не изменяется; stock tcboot остаётся boot authority; переключается только selector `active -> SLOT2`; `flagback` не переписывается; при transient `bootm` failure выполняется `reset` обратно в tcboot.

Stage2 обязан держать `DESTRUCTIVE=0` и переключать `DESTRUCTIVE=1` только непосредственно перед первым `ubiformat`. До этой границы preflight failure должен автоматически возвращаться через stock tcboot. После начала разрушения stock layout автоматический rollback запрещён.

### 11.3. Stock-compatible wrapper: диапазоны и preservation вместо формы одного dump

Реальный Fudan MD показал `FIT totalsize = 0x70d018` при `NT-FW payload = 0x2058127`. Требование `FIT totalsize == весь NT-FW payload` не является валидным Nokia contract и запрещено как mandatory gate.

Допустимая OEM упаковка может содержать external/trailing data за пределами FIT metadata tree. Wrapper обязан поддерживать inline `/images/*/data`, `data-position`, а также `data-offset + data-size`, если фактические ranges находятся внутри выбранного NT-FW entry.

Для MD handoff разрешено менять только `kernel@1` payload, compression и hash. Все остальные байты stock SLOT2, включая HDR2, FDT, filesystem, external carrier payload и данные за разрешёнными spans, должны сохраняться byte-for-byte.

### 11.4. Политика preflight/gates

> Gate существует только тогда, когда он доказывает safety, applicability или однозначность записи. Частное совпадение с одним известным dump не является основанием для gate.

Допустимые mandatory gates: board/profile/family identity, если от неё зависит target; MTD/UBI geometry и writable bounds; требуемый boot envelope/parser contract; candidate capacity; critical identity/calibration evidence, если операция переносит эти данные; отсутствие изменений вне разрешённых spans; destructive-state ambiguity; post-write readback/compare.

Не должны становиться mandatory gates без отдельного safety rationale: точный размер container при допустимых trailing/external data; cosmetic/version markers при наличии более сильной structural identity; конкретное значение поля, которое операция безопасно заменяет; exact byte shape одного stock sample; историческая implementation detail, не влияющая на target range или rollback.

Если проверка не меняет решение «можно ли безопасно писать этот range этим payload», она должна быть diagnostic/telemetry, а не blocker.

### 11.5. Operator ceremony

Для полной destructive transaction остаётся ровно одно meaningful `[y/N]` после automatic preflight summary. Запрещены codewords, повторные подтверждения, отдельные подтверждения каждого writer и подтверждение rollback, если rollback является частью уже авторизованной fail-safe state machine.

Safety достигается автоматическими checks, preservation invariants и readback, а не дополнительной operator ceremony.

### 11.6. CI и HW acceptance

Текущий code checkpoint: `42efabbeb433621c94c2c79f1a1a146a9668065e`.

Exact workflow `Vanilla pregnant MD+MF build`, run `35625391866` — `SUCCESS`; artifact `10652380364`; digest `sha256:413d77e9fd4038e2e9474802386b70098db95e637f9ece8d8842083f5d9d74ec`.

Это только **CI PASS**. Hardware acceptance требует минимум: реальный stock wrapper build на Fudan/SkyHigh; SLOT2 write/readback; selector active-only write/readback; tcboot acceptance stock envelope; ARM64 handoff; pregnant initramfs boot; pre-destructive failure rollback test; destructive migration до canonical UBI; pinned production verification; Vanilla FIP + BL2 LAST; production boot + durable confirmation.

До этого item 4 не объявляется HW PASS.

### 11.7. XG140 boundary

XG140-specific automatic workflows остаются manual-only/paused до прямой команды оператора. Изменения Vanilla MD/MF не должны автоматически будить XG140 acceptance jobs.

Common Airoha/multimodel QA может существовать отдельно, но его failure/success не подменяет profile-specific item-4 acceptance.

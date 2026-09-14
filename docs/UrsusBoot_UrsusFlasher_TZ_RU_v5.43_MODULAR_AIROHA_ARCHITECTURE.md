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

# UrsusBoot / UrsusFlasher ТЗ v5.43 — модульная Airoha-архитектура

Статус: engineering baseline. Ветка `feature/ursusboot-modular-airoha`. `main` не затрагивается.

## 1. Цель

UrsusBoot развивается как единая многомодельная Airoha-платформа, а не набор независимых форков под каждую Nokia/Bell плату. Новая модель должна добавляться композиционным профилем и минимальным board-specific policy, сохраняя общий WebFailsafe, network stack, dispatcher, StockBridge и update/recovery backend.

Базовая композиция:

```text
common core
  -> SoC module
  -> board/DTS module
  -> storage/environment policy
  -> boot/layout board policy
  -> runtime role
```

## 2. Текущие профили

- `xg040-md`: Airoha AN7581, native MD, UBI redundant env.
- `xg040-mf`: Airoha AN7583, native MF, UBI redundant env.
- `xg140-md`: Bell/Nokia XG-140G-MD, AN7581 family, MD-derived common core, XG140 native stock layout, vendor env preserved.

`xg040-md` и `xg140-md` обязаны использовать общий `soc-an7581` слой. MF использует `soc-an7583`.

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
- FIT/oracle параметры, если они доказаны для платы.

WebFailsafe выводит модель через `URSUS_BOARD_MODEL`; hard-coded `Nokia XG-040G-MD` в common UI запрещён CI-gate.

## 4. Runtime roles

Runtime role ортогонален board profile и выбирается до компиляции.

### `persistent`

```text
bootcmd=ursusdispatch
```

Нормальный persistent supervisor. Для XG140 этот BL33 вставляется в NT_FW родного native FIP.

### `ram-recovery`

```text
bootcmd=ursusweb;true
```

RAM-only WebFailsafe role из той же кодовой базы. Пост-build byte patch бинарника запрещён.

Важно: наличие `ram-recovery` role не означает, что любой stock bootloader способен запустить raw `u-boot.bin`. На XG140 аппаратно доказано, что `tcboot -> loadx -> go raw-u-boot` возвращается в tcboot с `Application terminated, rc=1`; этот путь не является допустимым XG140 handoff.

## 5. XG140 persistent native-hybrid

XG140 не получает MD boot area целиком. Persistent image строится из собственного stock `mtd0` устройства:

```text
live BootROM prefix       KEEP
native Nokia/Bell FIP     KEEP
  native entries          KEEP
  NT_FW / BL33            REPLACE -> modular XG140 UrsusBoot
live vendor env           KEEP
```

Для известной XG140 разметки:

- boot area: `0x000000..0x07ffff`;
- FIP physical start: `0x000800`;
- protected vendor env: `0x07c000..0x07ffff`.

Repacker обязан структурно проверять FIP TOC и не пересекать protected env. Prefix и vendor env не принадлежат UrsusBoot и не должны изменяться штатным XG140 update path.

## 6. XG140 normal boot target

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

XG140 не должен неявно наследовать непроверенные MD assumptions:

- UBI autodetect: disabled by XG140 board policy;
- MD factory FIT probe: disabled;
- MD SerDes overrides: disabled;
- vendor env: preserved/read as vendor data.

## 7. UrsusFlasher <-> UrsusBoot

UrsusFlasher остаётся policy/orchestration layer: backup, restore, board detection, manifest, identity repair, network transport, sequencing.

UrsusBoot остаётся компактным execution/recovery backend: boot policy, WebFailsafe/API, network primitives, MTD/NAND writer, verification/readback, reboot.

Глобальный UrsusFlasher board profile связывается с конкретным `ursusboot_profile`; два независимых каталога модельных magic names недопустимы.

## 8. CI contract

Для каждой поддерживаемой композиции CI должен проверять:

- layer boundaries common/SoC/board/storage/policy;
- profile resolver и связь с UrsusFlasher catalog;
- WebFailsafe board identity через policy;
- отсутствие чужой board identity в итоговом binary;
- source-level runtime role selection;
- правильный bootcmd для каждой role;
- требуемые SoC/network/MTD symbols;
- environment ownership policy;
- размер/сжатие BL33;
- XG140 native FIP repacker self-test.

Для XG140 CI собирает независимо:

```text
ursusboot-xg140-persistent-<sha>
ursusboot-xg140-ram-recovery-<sha>
```

## 9. Hardware acceptance gates XG140

CI PASS не равен hardware acceptance.

Порядок аппаратного допуска:

1. native-hybrid candidate строится только из backup текущего XG140;
2. до erase проверяются размер, FIP structure, protected-env boundary и lineage;
3. запись boot area завершается полным `0x80000` readback/compare;
4. cold boot подтверждает `BootROM -> native FIP -> UrsusBoot`;
5. `ursusdispatch -> ursusstockboot -> stock MASTER` подтверждается на железе;
6. только после этого отдельно подключается/принимается Nokia A/B selector по `flag.active` и fallback policy.

До выполнения этих шагов XG140 остаётся `HW_PENDING` / engineering-only.

## 10. Правило расширения

Новая Airoha-модель должна по возможности добавляться набором:

```text
existing/new SoC module
+ board DTS
+ storage policy
+ board boot/layout policy
+ profile entry
+ hardware acceptance tests
```

Новый форк common UrsusBoot, копия WebFailsafe или копия `ursusdispatch/ursusstock` допустимы только при доказанной архитектурной несовместимости, а не как обычный способ портирования.

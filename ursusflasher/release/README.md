# UrsusFlasher 0.2.51 — Nokia XG-040G-MD

Готовый комплект для установки OpenWrt, резервного копирования и восстановления Nokia XG-040G-MD на Airoha AN7581.

## Запуск

Windows:

```text
START_ONECLICK.cmd
```

или ручное меню:

```text
START_EXPERT.cmd
```

Linux/macOS:

```bash
./START_ONECLICK.sh
./START_EXPERT.sh
```

## Ethernet

Для прошивки рекомендуется использовать **LAN2 или LAN3**.

- LAN1 подключён к отдельному PHY Airoha EN8811H.
- LAN4 после загрузки комплектной OpenWrt-сборки работает как WAN.

## Основные рабочие пути

| Исходное состояние | Управление | Передача файлов |
|---|---|---|
| Nokia STOCK | HTTP/Web + Telnet | TFTP |
| установленная OpenWrt | SSH | SCP |
| OpenWrt/initramfs в RAM | SSH | SCP |
| UrsusBoot Recovery | HTTP API | HTTP по частям; TFTP для резервной передачи FIP |
| Airoha BootROM | USB-UART 3,3 В | XMODEM |

## ONE-CLICK с Nokia STOCK

```text
определение Nokia STOCK
  -> root Telnet
  -> полная копия mtd0..mtd16
  -> проверка резервной копии
  -> подготовка mtd0 с сохранением ROM prefix и tcboot env
  -> запись UrsusBoot
  -> полное обратное чтение mtd0 и SHA256
  -> UrsusBoot Recovery
  -> проверка и запись OpenWrt
```

## ONE-CLICK с OpenWrt

```text
root SSH
  -> определение PERSISTENT_ROOT или RAM_ROOT
  -> передача UrsusBoot по SCP
  -> обновление UBI fip или подтверждённого boot block
  -> полное обратное чтение и SHA256
  -> UrsusBoot Recovery
  -> проверка и обновление OpenWrt
```

## Проверки

До записи проверяются применимые к текущему пути сведения: модель/SoC, система и разметка, загрузчик, root-доступ, среда выполнения OpenWrt, целевой MTD/UBI-объект, размер и SHA256 файлов, а также резервная копия, когда она обязательна.

После записи загрузочные объекты считываются обратно полностью. Несовпадение блокирует дальнейший автоматический переход и не вызывает повторную запись другим способом.

## Полная резервная копия

Пункт 7 EXPERT выполняется в режиме чтения. Для Nokia STOCK сохраняются `mtd0..mtd16` и метаданные устройства. Если безопасный live-read путь недоступен, используется Airoha BootROM и среда в RAM.

## Комплект OpenWrt

```text
OpenWrt  r36009+75-6c315233aa
Kernel   6.18.44
```

В комплекте находятся отдельные sysupgrade-образы для заводской и UBI-разметки Nokia XG-040G-MD.

## UrsusBoot

Текущий комплект содержит UrsusBoot `0.1.0-alpha4-FUDAN1`.

```text
BL33 SHA256  a41a81a011e19d1498d5ff0773dfd6bf9bd4c56beb3e7a46ce4622a643a30703
FIP  SHA256  ce43b56d86321ccb7657d2e9b7ddf58e811efc73927855bbb75e896c83b18600
```

Статус FUDAN1: **HW_TEST_REQUIRED**.

## Документация

В каталоге `doc/` находятся эксплуатационная инструкция, аварийная UART/BootROM инструкция и changelog.

Перед использованием можно проверить весь комплект через EXPERT пункт 12.

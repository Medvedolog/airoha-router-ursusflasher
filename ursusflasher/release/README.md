# UrsusFlasher 0.2.56 — Nokia XG-040G-MD

Готовый комплект для установки OpenWrt, резервного копирования и восстановления Nokia XG-040G-MD на Airoha AN7581.

## Обязательно перед началом

**Сбросьте Nokia на заводские настройки перед каждой итерацией** — и перед первой установкой, и перед любым повтором после неудачной попытки.

Сброс выполняется на стоковой прошивке: зажать кнопку Reset и удерживать **не менее 20 секунд**, отпустить и дождаться полной перезагрузки.

Без сброса состояние стоковой системы неизвестно: остаются изменённые настройки, включённые или отключённые службы и следы прошлых попыток, из-за которых определение устройства и штатный доступ могут повести себя иначе.

## Что нового в 0.2.56

- пункт 2 различает OpenWrt и Nokia STOCK только по положительному доказательству среды; открытый Telnet больше не переводит OpenWrt в stock-сценарий;
- UrsusBoot Recovery разрешает `OPENWRT_STOCK_LAYOUT → OPENWRT_UBI` с тем же Recovery-only migration backend, что Nokia STOCK → UBI;
- UBI update имеет выбор сохранения настроек; отдельная кнопка Recovery и UART-команда `ursussettings reset` очищают только OpenWrt `rootfs_data`;
- чистая UBI-установка/сброс создаёт `rootfs_data` по политике MAX−16 PEB и сохраняет `rootfs_data_max`, чтобы последующий штатный OpenWrt `sysupgrade` сохранял тот же размер overlay.


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
| установленная OpenWrt | SSH | SSH-stream/SCP; штатный sysupgrade |
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

Пункт 7 EXPERT выполняется в режиме чтения. Если для определения текущей OpenWrt/разметки нужен пароль `root`, его интерактивно запрашивает системный OpenSSH; пароль не сохраняется и ключ на роутер не устанавливается. Для Nokia STOCK сохраняются `mtd0..mtd16`. Для OpenWrt UBI путь Airoha BootROM → RAM сохраняет точный 256-МиБ `mtd0_all_flash.bin.gz`, SHA256 и производные `mtd1_bl2`/`mtd2_ubi`.

## Комплект OpenWrt

```text
OpenWrt  r36009+75-6c315233aa
Kernel   6.18.44
```

В комплекте находятся отдельные sysupgrade-образы для заводской и UBI-разметки Nokia XG-040G-MD.

## UrsusBoot

Текущий комплект содержит UrsusBoot `0.1.0-alpha5-UBIUX1`.

```text
BL33 SHA256  06397f68ba876e01ba6a07ebbdbbcfac1e5341b9d82926fd6b4a54ae1bf7e552
FIP  SHA256  ce43b56d86321ccb7657d2e9b7ddf58e811efc73927855bbb75e896c83b18600
```

Статус alpha5-UBIUX1: **SOURCE/BUILD/PACKAGE_QA_PROVEN; HW_REGRESSION_REQUIRED**.

## Документация

В каталоге `doc/` находятся эксплуатационная инструкция, аварийная UART/BootROM инструкция и changelog.

Перед использованием можно проверить весь комплект через EXPERT пункт 12.

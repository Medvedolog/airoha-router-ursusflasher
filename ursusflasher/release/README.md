# UrsusFlasher 0.2.61 PUBLIC TEST — TEST61 SAFETYREG1 — Nokia XG-040G-MD

Готовый комплект для установки OpenWrt, резервного копирования и восстановления Nokia XG-040G-MD на Airoha AN7581.

## Обязательно перед началом

**Сбросьте Nokia на заводские настройки перед каждой итерацией** — и перед первой установкой, и перед любым повтором после неудачной попытки.

Сброс выполняется на стоковой прошивке: зажать кнопку Reset и удерживать **не менее 20 секунд**, отпустить и дождаться полной перезагрузки.

Без сброса состояние стоковой системы неизвестно: остаются изменённые настройки, включённые или отключённые службы и следы прошлых попыток, из-за которых определение устройства и штатный доступ могут повести себя иначе.

## Что нового в 0.2.61 PUBLIC TEST

- TEST59/60 **отозваны для аппаратного использования**. Их split identity позволял ONE-CLICK принять реально установленный TEST59/60 за TEST57 и запустить лишнюю повторную запись FIP.
- **IDENTITY1:** native `version` и Web/API имеют одну identity TEST61.
- **NOAUTOFIP1:** ONE-CLICK не обновляет уже установленный UrsusBoot автоматически. Обновление загрузчика после первичной stock-установки — только отдельное ручное действие WebFailsafe/EXPERT.
- **UBIATTACH2:** explicit FIP self-update не делает `ubi detach` для уже активного ожидаемого UBI.
- **UPLOADRETRY1/UPLOADABORT2:** после обрыва Ethernet действует увеличенный reconnect grace; новый полный upload запускается только после `[y/N]`; до operation endpoint persistent transaction остаётся `NOT_STARTED`.
- После failed upload/validation/precheck интерфейс снова готов к следующей попытке, если persistent writer не запускался.
- ONE-CLICK всегда спрашивает один `[y/N]` непосредственно перед direct `mtd0` write. EXPERT пункт 1 может пропустить полный backup только для текущего запуска.
- После успешного UBI sysupgrade с сохранением настроек предлагается необязательный reset OpenWrt settings.
- CONFIGTRIM1 сохранён. TEST61: BL33 860808 байт, LZMA 291160 байт, FIP 503808 байт, NT_FW margin 36520 байт.

Статус: **SOURCE/BUILD QA PASS; HARDWARE SAFETY REGRESSION REQUIRED**. Исторический полный stock→OpenWrt HW PASS относится к TEST57/SkyHigh.

## Что нового в 0.2.60 PUBLIC TEST

- **CONFIGTRIM1:** отключены `CONFIG_CMD_UBIFS`, `CONFIG_CMD_PXE`, `CONFIG_BOOTMETH_EXTLINUX`, `CONFIG_BOOTMETH_EXTLINUX_PXE`, `CONFIG_PXE_UTILS`.
- `CONFIG_CMD_UBI`, `CONFIG_MTD_UBI`, `CONFIG_CMD_TFTPBOOT` и `CONFIG_CMD_WGET` сохранены.
- Сброс настроек OpenWrt по-прежнему удаляет/создаёт UBI volume `rootfs_data`; UBIFS создаётся уже Linux/OpenWrt при следующей загрузке.
- Размер BL33: 860176 байт raw / 291237 байт LZMA; запас до первого сертификата FIP: 36443 байт.
- Наследуются UBIOPT1, WEBREBOOT2, UARTASCII1, UBIHEADROOM2 и все предыдущие исправления.

`0.2.60` — историческая/forensic линия, **отозвана для новых HW-прогонов**. CONFIGTRIM1 перенесён в TEST61.

## Что нового в 0.2.59 PUBLIC TEST

- **UBIOPT1:** при обычном обновлении OpenWrt UBI снова виден выбор «Сохранить настройки OpenWrt»; история предыдущей операции больше не скрывает controls следующей.
- **WEBREBOOT2:** кнопка перезагрузки работает после обычного UBI-update, а HTTP reject больше не игнорируется Web UI.
- **UARTASCII1:** проектные machine/UART сообщения снова только English/printable ASCII; русский остаётся в Web/host UI.
- **UBIHEADROOM2:** direct Recovery-safe update оценивает прогноз свободных LEB; меньший FIT разрешён, если он сохраняет или улучшает существующий headroom.
- Наследуются DIAGCAP2, REBOOTWAIT1, WAITUI1, BUILDDATE1 и исправления TEST57.

`0.2.59` — историческая/forensic линия, **отозвана для новых HW-прогонов**.

## Что нового в 0.2.58 PUBLIC TEST

- `DIAGCAP2`: полный diagnostic bundle создаётся для каждой операции записи, и при успехе, и при ошибке: `status-before.json`, `status-after.json`, `operation-log.txt`, `web-log.txt`, `console.txt`, `operation.json`. Raw JSON и device logs также пишутся в `session-*.log`.
- `REBOOTWAIT1`: после записи UrsusBoot ONE-CLICK ждёт именно Recovery до 90 секунд; старый ответ stock Web больше не принимается за новую загрузку.
- `WAITUI1`: таймер ожидания больше не показывает отрицательные секунды.
- `BUILDDATE1`: TEST58 собран с фиксированным release epoch `2026-09-08 09:38:00 UTC`, поэтому UART/Web/API показывают актуальную дату сборки без потери воспроизводимости.
- Наследуются `RESETSET1`, `UPLOADRETRY1` и `WEBTX1` из 0.2.57.
- Известная особенность: ранний BL2 сканирует почти весь UBI до запуска U-Boot и может занимать до ~12 секунд. В TEST58 это пока не оптимизируется.

Статус: **PUBLIC TEST**. Основной ONE-CLICK `stock → UrsusBoot → OpenWrt UBI` успешно пройден на реальном SkyHigh S35ML02G300 в 0.2.57/TEST57; для TEST58 нужен короткий регрессионный прогон новых изменений.

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
| UrsusBoot Recovery | HTTP API | HTTP по частям с retry/reconcile; TFTP только отдельным ручным recovery-путём |
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
  -> переход в UrsusBoot Recovery при необходимости обновить OpenWrt
  -> проверка и обновление OpenWrt

Обновление уже установленного UrsusBoot не является частью ONE-CLICK и запускается только отдельным ручным действием.
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

Текущий public-test комплект содержит UrsusBoot `0.1.0-alpha5-UBIUX1-TEST61`.

```text
BL33 SHA256  43296d98686ada9e4e13c5a5a49430372abf45e9bd0fc8eae837920e8ba5224d
FIP  SHA256  3c922e4256b6047376a7d445006e6cb2a4485bb412747033a77defd15e42fcea
```

Статус TEST61: **SOURCE/BUILD QA PASS; HARDWARE SAFETY REGRESSION REQUIRED**.

## Документация

В каталоге `doc/` находятся эксплуатационная инструкция, аварийная UART/BootROM инструкция и changelog.

Перед использованием можно проверить весь комплект через EXPERT пункт 12.

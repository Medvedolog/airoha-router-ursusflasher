# 0.2.61 PUBLIC TEST — TEST61 / SAFETYREG1

- TEST59/60 отозваны для новых аппаратных прогонов: доказан split identity между `.scmversion` и `URSUS_VERSION`, из-за которого ONE-CLICK мог запустить лишнюю повторную запись FIP после уже доказанной direct mtd0 write/readback.
- IDENTITY1: TEST61 единообразно виден в native `version`, Web/API и build metadata.
- NOAUTOFIP1: ONE-CLICK больше не обновляет уже установленный UrsusBoot автоматически; self-update остаётся только отдельной операторской операцией WebFailsafe/EXPERT.
- UBIATTACH2: при explicit FIP self-update уже прикреплённый ожидаемый UBI используется без `ubi detach`; mismatch завершается до writer.
- UPLOADRETRY1/UPLOADABORT2: reconnect grace увеличен до 75 с; новый полный transfer cycle начинается только после `[y/N]`; failure до operation POST явно фиксируется `transaction_state=NOT_STARTED`.
- SESSIONRECOVERY1: upload/validation/precheck failure без writer не блокирует следующую попытку.
- Direct stock mtd0 write всегда имеет один `[y/N]` после backup/preflight. EXPERT пункт 1 может явно пропустить полный backup для текущего запуска; live mtd0 capture остаётся.
- POSTSYSRESET1: после успешного UBI update с `keep_settings=1` предлагается optional reset OpenWrt settings.
- DIAGSTATE1: stock self-update больше не помечает успешный этап ложным `UBI_VERIFY`.
- EMERGENCYMETA1: production TEST61 FIP и аварийный BootROM alpha3 используют раздельные manifest/hash поля; обновление production target больше не может сломать валидацию аварийного payload.
- REPROZIP1: PUBLIC TEST ZIP собирается с фиксированным `SOURCE_DATE_EPOCH`; две независимые упаковки обязаны иметь одинаковый SHA256.
- ROUTE1 integration: положительный fingerprint `nokia_stock` теперь действительно запускает authenticated read-only stock probe; generic HTTP остаётся неопределённым состоянием.
- Исправлен запуск прямо из Git checkout, поиск `config/UI_TERMS.json`, GitHub-safe состав SDK и эталон payload-манифеста с TEST61. Порядок файлов в манифестах и ZIP канонизирован между Windows и Linux.
- CONFIGTRIM1 сохранён. TEST61: raw BL33 860808 B, LZMA 291160 B, FIP 503808 B, NT_FW margin 36520 B.
- Статус: source/build QA; обязательный hardware safety regression.

# 0.2.60 PUBLIC TEST — TEST60 / CONFIGTRIM1

- UrsusBoot: `0.1.0-alpha5-UBIUX1-TEST60`.
- Отключены неиспользуемые U-Boot UBIFS filesystem commands: `CONFIG_CMD_UBIFS=n`. UBI layer и все `ubi ...` операции сохранены.
- Отключён неиспользуемый PXE/extlinux boot path: `CONFIG_CMD_PXE=n`, `CONFIG_BOOTMETH_EXTLINUX=n`, `CONFIG_BOOTMETH_EXTLINUX_PXE=n`, `CONFIG_PXE_UTILS=n`.
- TFTP/WGET и UBI сохранены; нормальный boot path остаётся `bootcmd=ursusdispatch`.
- Raw BL33: 956088 → 860176 байт (-95912); LZMA: 327650 → 291237 байт (-36413).
- Запас NT_FW перед первым сертификатом: 30 → 36443 байт. FIP физически заканчивается на `0x7b800`, env начинается с `0x7c000`.
- Runtime WebFailsafe/update/reset logic не менялась относительно TEST59.
- Статус: source/build/package QA; focused HW regression требуется для CONFIGTRIM1.

# CHANGELOG — RU

## 0.2.59 PUBLIC TEST — TEST59 / UBIOPT1 / WEBREBOOT2 / UARTASCII1 / UBIHEADROOM2

- UBIOPT1: выбор сохранения/сброса настроек OpenWrt снова виден для новой UBI-операции после предыдущего COMPLETE/FAILED; backend по-прежнему получает `X-Ursus-Keep-Settings: 1/0`.
- WEBREBOOT2: `/api/reboot` разрешён после `ursus_ubi_update_complete()` наряду с migration/self-update; Web UI проверяет HTTP status и показывает reject вместо молчаливого игнорирования.
- UARTASCII1: удалены русские runtime-строки из `cmd/ursus*.c`; machine/UART log — English printable ASCII.
- UBIHEADROOM2: direct Recovery-safe update больше не требует искусственно восстановить абсолютные 16 свободных LEB, если до операции их уже меньше. Политика сохраняет существующий headroom и учитывает `projected_free`; кейс `free=7, current_fit=82, candidate=76` даёт `projected_free=13` и допускается.
- FIP safety gate сохранён: TEST59 NT_FW заканчивается за 30 байт до первого certificate block; physical FIP end `0x7b800`, protected env начинается `0x7c000`.
- Build identity: `UrsusBoot 0.1.0-alpha5-UBIUX1-TEST59`, `SOURCE_DATE_EPOCH=1788864300`, `2026-09-08 10:45:00 UTC`.
- Основной аппаратный ONE-CLICK stock→UrsusBoot→OpenWrt UBI ранее пройден на TEST57/SkyHigh S35ML02G300; TEST59 требует focused regression только новых corrective paths.

# Журнал изменений

## 0.2.58 PUBLIC TEST — TEST58 / DIAGCAP2 / REBOOTWAIT1 / BUILDDATE1 / WAITUI1

- DIAGCAP2: каждая write-capable операция создаёт `work/diagnostics/<timestamp>-<operation>/` с `status-before.json`, `status-after.json`, `/api/operation-log`, Web log, безопасным console snapshot и `operation.json`; raw JSON/log/snapshot также попадают в полный `session-*.log`.
- REBOOTWAIT1: после записи UrsusBoot ONE-CLICK сам ждёт именно Recovery до 90 секунд; старый stock HTTP больше не принимается за завершившуюся новую загрузку; двойное внутреннее/внешнее ожидание убрано.
- WAITUI1: оставшееся время ожидания не может стать отрицательным.
- BUILDDATE1: TEST58 собирается с новым фиксированным release epoch, поэтому дата U-Boot/Web/API/BUILD_INFO соответствует сборке 08.09.2026, а воспроизводимость сохраняется.
- Наследуются RESETSET1, UPLOADRETRY1 и WEBTX1 из .57. Основной аппаратный ONE-CLICK stock→UrsusBoot→OpenWrt UBI на .57/TEST57 пройден на SkyHigh S35ML02G300; TEST58 требует короткого регрессионного прогона новых изменений.

# Changelog UrsusFlasher

## 0.2.57 PUBLIC TEST — TEST57 / DIAGCAP1 / UPLOADRETRY1 / RESETSET1 / WEBTX1

- UrsusBoot public-test: `0.1.0-alpha5-UBIUX1-TEST57`, база alpha5-UBIUX1 + WEBREBOOT1.
- Исправлен off-by-one в маршруте `/api/reset-openwrt-settings`; HTTP route prefixes сопоставляются по `sizeof(literal)-1`.
- API v200 расширен геометрией NAND и структурированными полями failure/transaction state; добавлен `/api/operation-log`.
- UrsusFlasher сохраняет failure diagnostic bundle и полный status snapshot.
- HTTP upload получил bounded retry/reconcile по generation/received/total, включая потерянный ACK.
- Удалён generic automatic TFTP fallback после Web-ошибки; доказанный успех записи остаётся успехом независимо от последующей ошибки UI.
- Аппаратно зафиксирован pre-U-Boot UBI scan `0x20000..0x10000000` до ~12 с; BL2UBISCAN1 оставлен отдельной performance-задачей без изменения layout в TEST57.

Статус TEST57: `HW_REGRESSION_REQUIRED`.

## 0.2.56 — alpha5-UBIUX1 / ROUTE1 / ROOTFSENV1

- Текущий постоянный UrsusBoot обновлён до `0.1.0-alpha5-UBIUX1`; Fudan/SkyHigh NAND-драйверная линия унаследована без изменений от alpha4-FUDAN1.
- В UrsusBoot Recovery разрешён `OPENWRT_STOCK_LAYOUT → OPENWRT_UBI` через тот же физический migration backend, что и `NOKIA_STOCK → OPENWRT_UBI`; BOSA/RI/FIP сохраняются, полный BL2 записывается последним.
- Web Recovery получил флаг «Сохранить настройки OpenWrt» для UBI-обновления и отдельную кнопку «Сбросить настройки OpenWrt». UART/U-Boot получил `ursussettings reset`.
- Чистый/сброшенный `rootfs_data` создаётся как MAX−16 PEB; фактический размер сохраняется в `rootfs_data_max`, чтобы обычный OpenWrt `sysupgrade` создавал overlay того же размера. Существующий пользовательский `rootfs_data` при сохранении настроек не уменьшается.
- ROUTE1: Telnet/порт 23 больше не считается доказательством Nokia STOCK. OpenWrt → SSH только после положительного подтверждения; Nokia STOCK → Web/Telnet только после положительного vendor fingerprint. Неопределённая среда останавливается без stock fallback.
- Путь `web-fit` на UBI теперь спрашивает, сохранять ли текущие настройки.

# История изменений UrsusFlasher

Документ перечисляет опубликованные изменения рабочих версий без описания незавершённых разработческих задач.

## 0.2.55 — STATEUI8 / DIAGAUTH1 / BACKUPRAW1

- Пункты 7, 10 и 11 при неполной фоновой диагностике могут выполнить интерактивную read-only проверку root SSH: пароль запрашивает системный OpenSSH, UrsusFlasher его не сохраняет и временный ключ на роутер не устанавливает.
- Пункт 7 больше не вызывает унаследованный глобальный `verify_kit()` и не требует отсутствующие `transition-bundle.bin`/MedveFlasher payloads.
- Для пункта 7 возвращены только три точно закреплённых RAM-компонента MD: общий preloader, RC18 RECOVERY_SAFE FIP и recovery initramfs; каждый проверяется по размеру и SHA256 до UART/XMODEM.
- Для OpenWrt UBI точная резервная копия создаётся как полный физический 256-МиБ `mtd0_all_flash.bin.gz` через BootROM → RAM → read-only `/dev/mtd0` → TFTP, с повторным чтением каждого блока и итоговым SHA256.
- Для UBI дополнительно формируются `mtd1_bl2.bin.gz`, `mtd2_ubi.bin.gz`, `RAW_BACKUP.json` и `SHA256SUMS.txt`; пункт 8 умеет проверять этот формат.
- Старый stock-backup `mtd0..mtd16` сохранён для Nokia STOCK. FUDAN1 и комплектные OpenWrt-образы не изменены.

## 0.2.54 — STATEUI7 / MENUOPS1

- Пункты установки и обновления UrsusBoot объединены в пункт 2 «Установить или обновить UrsusBoot»; прежний пункт 4 скрыт и остаётся совместимым псевдонимом пункта 2.
- Под каждым пунктом EXPERT добавлена короткая строка, объясняющая действие и используемый транспорт.
- Пункт 3 доступен из установленной OpenWrt: образ передаётся по SSH, проверяется штатным `sysupgrade -T` и записывается через `sysupgrade -v -n`; `-F` не используется.
- Из UrsusBoot Recovery пункт 3 продолжает использовать HTTP API Recovery.
- Для передачи пользовательского sysupgrade добавлен бинарный SSH-stream без зависимости от `scp`, `sftp` или `base64` на роутере.
- FUDAN1 и комплектные образы OpenWrt не изменены.

## 0.2.53 — ERRORUI1 / SSHBIN1

- При ошибке EXPERT и ONE-CLICK теперь показывают короткую строку `[ПРИЧИНА] ...` непосредственно в интерфейсе; полный объект исключения по-прежнему сохраняется в журнале сеанса.
- Установка UrsusBoot из OpenWrt больше не требует утилиту `base64` на роутере для чтения `fip`/boot block. Бинарное обратное чтение выполняется напрямую через stdout системного OpenSSH, а stderr остаётся отдельным каналом.
- Исправлен обнаруженный на китайской OpenWrt отказ `ash: line 0: base64: not found` до начала записи FIP.
- FUDAN1 и образы OpenWrt не изменены.

## 0.2.52 — STATEUI6 / ACTIONPREFLIGHT1

- Пассивный `DeviceState` больше не является глобальным запретом для операций записи.
- Пункты 1, 2 и 5 остаются доступными при неполной фоновой диагностике; окончательное разрешение выполняет preflight самой операции.
- Для OpenWrt пароль SSH запрашивается при выборе операции, если автоматическая проверка без пароля не смогла подтвердить root.
- Блок состояния устройства удалён из шапки EXPERT и перенесён в информационный пункт 10.
- Из заголовка EXPERT удалено описание изменений сборки; оно остаётся в changelog.
- Исправлено чтение UTF-8 в `selftest_rootfsmax2.py` на русской Windows.
- Репозиторий сделан устойчивым к Windows `core.autocrlf`: текстовые файлы нормализуются в LF, `.cmd` — в CRLF; воспроизводимые `.log` явно не игнорируются.
- Унаследованный USB-backup agent больше не считается обязательной частью текущего комплекта; поддерживаемые пути резервного копирования — TFTP и BootROM/RAM.

## 0.2.51 — STATEUI5

- Уточнена русская терминология пользовательского интерфейса.
- Пункт 2 переименован в «Установить или переустановить загрузчик».
- Пункт 3: «Записать пользовательскую прошивку OpenWrt».
- Пункт 6: «Восстановить заводскую прошивку Nokia».
- Пункт 7: «Создать полную копию flash-памяти».
- Пункт 10: «Доступные операции для устройства».
- Сетевая подсказка использует формулировку «рекомендуется использовать порты LAN2 или LAN3».
- Прошивочные образы и механизмы записи не изменены относительно 0.2.50.

## 0.2.50 — STATEUI4

- В `DeviceState` добавлено отдельное состояние среды выполнения OpenWrt: `PERSISTENT_ROOT`, `RAM_ROOT`, `UNKNOWN`.
- Среда определяется по фактической топологии корневой файловой системы.
- Пункт 2 показывает конкретный способ установки загрузчика: Telnet из Nokia STOCK, SSH из установленной OpenWrt или SSH из OpenWrt, запущенной в RAM.
- Пункт 10 отображает распознанную среду выполнения.

## 0.2.49 — PAYLOADREFRESH1

- Два рабочих образа OpenWrt для Nokia XG-040G-MD заменены на сборку UnameOne от 06.09.2026.
- OpenWrt: `r36009+75-6c315233aa`, Linux 6.18.44.
- Добавлена рекомендация использовать LAN2/LAN3.
- LAN4 сохранён в конфигурации автора сборки и после загрузки OpenWrt работает как WAN.
- Служебные initramfs UrsusFlasher не заменялись.

## 0.2.48 — STATEUI3

- `human()` прекращает работу на неизвестном машинном значении вместо тихой подстановки `UNKNOWN`.
- Добавлена автоматическая проверка полного покрытия UI-переводами.
- Исправлены подписи `TCBOOT`, `FOUND` и `CLEAN`.

## 0.2.47 — STATEUI2

- `probe_status` сделан монотонным в пределах одного опроса: `COMPLETE -> PARTIAL -> FAILED`.
- Значения `DeviceState` и причины опроса переводятся только на границе пользовательского интерфейса.
- Для доступных пунктов информационная подсказка отделена от причины блокировки.

## 0.2.46 — STATEUI1

- Добавлен единый read-only `DeviceState` для EXPERT и проверки применимости операций.
- Добавлена полная резервная копия flash-памяти в режиме чтения.
- Добавлен устойчивый к прерыванию журнал операций на стороне ПК.
- EXPERT переведён на стабильное меню 1–12.

## 0.2.45 — FUDAN1 / SSH1

- UrsusBoot FUDAN1 получил поддержку Fudan FM25G01B и FM25G02B.
- Добавлена установка/переустановка UrsusBoot из OpenWrt по root SSH.
- При наличии UBI-тома `fip` обновляется именно этот том.
- Для физического boot block используется отдельный AArch64 helper `ursus-mtd-raw` и обязательное полное обратное чтение.

## 0.2.44–0.2.41

- Уточнён пользовательский интерфейс UrsusBoot и диагностические подписи.
- Реализовано увеличение `rootfs_data` после свежего перехода STOCK -> UBI.
- Прямая установка UrsusBoot из Nokia STOCK переведена на запись подготовленного `mtd0` с сохранением ROM prefix и tcboot env.
- Сохранена обязательная полная резервная копия перед первой записью NAND.

## Ранние версии

Ранние выпуски сформировали текущую аварийную BootROM/UART-инфраструктуру, раздельную диагностику и восстановление, проверку загрузочных объектов после записи, русскую консоль и единые launchers ONE-CLICK/EXPERT.

# Состав репозитория UrsusFlasher 0.2.55

Этот файл описывает назначение основных каталогов и файлов текущего GitHub-снимка.

## Запуск

```text
START_ONECLICK.cmd / .sh   автоматическая установка
START_EXPERT.cmd / .sh     ручное меню обслуживания
VERSION                    версия комплекта
README.md                   рабочие сценарии, транспорты и проверки
```

## Исполняемый код

```text
ursusflasher/src/           код UrsusFlasher
ursusflasher/tools/         автоматические самопроверки
config/                     манифесты, возможности, UI-словарь и сведения об образах
```

Ключевые модули:

```text
one_key.py                  автоматический сценарий ONE-CLICK
expert.py                   меню EXPERT; пункт 2 объединяет установку/обновление UrsusBoot, пункт 3 выбирает SSH/sysupgrade или Recovery HTTP
proven_backend.py           работа с Nokia STOCK, backup, BootROM и низкоуровневыми путями
device_state.py             read-only определение состояния устройства
ursusboot_install.py        установка/переустановка UrsusBoot через Telnet или SSH
ursus_web_client.py         HTTP API UrsusBoot Recovery
ursusboot_update.py         обновление и аварийные UART/BootROM операции
network_guidance.py         рекомендация LAN2/LAN3
operation_journal.py        журнал операций на стороне ПК
```

## Рабочие образы OpenWrt

```text
fw/openwrt-airoha-an7581-nokia_xg-040g-md-squashfs-sysupgrade.bin
fw/openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb
```

Оба файла относятся к сборке UnameOne от 06.09.2026.

Сведения о сборке:

```text
openwrt/payload-2026-09-06/config.buildinfo
openwrt/payload-2026-09-06/feeds.buildinfo
openwrt/payload-2026-09-06/README.md
```

## Служебные компоненты

Каталог `payloads/` содержит рабочие и аварийные компоненты UrsusBoot, preloader, RAM installer и служебные recovery-образы. `payloads/md/bootrom-backup/` содержит закреплённые FIP/initramfs только для read-only пункта 7; они проверяются по точным размеру и SHA256 и не зависят от старых `transition-bundle.bin`.

Контрольные суммы служебного набора формируются в `PAYLOAD_SHA256SUMS.txt` экспортируемого релиза.

## Исходники и воспроизводимая сборка UrsusBoot

```text
ursusboot/source/           снимок исходников U-Boot
ursusboot/configs/          конфигурации
ursusboot/artifacts/        воспроизводимые результаты сборки
ursusboot/scripts/          сценарий пересборки
openwrt/source/             исходная база OpenWrt, использованная для FUDAN1
openwrt/patches/            сохранённые внешние патчи
toolchains/                 SDK/GCC, разбитые на GitHub-safe части
```

Эти каталоги нужны репозиторию и воспроизводимой проверке UrsusBoot, но не включаются в PUBLIC-TEST ZIP.

## GitHub Actions и проверка

```text
.github/workflows/ci.yml                  проверка push/PR
.github/workflows/public-test-release.yml ручная публикация тестового prerelease
scripts/verify_repo.py                    полная проверка репозитория
scripts/verify_boot_chain.py              проверка загрузочных артефактов
scripts/build_release.py                  сборка полного пользовательского комплекта
scripts/build_public_release.py           сборка PUBLIC-TEST ZIP
scripts/verify_release.py                 проверка полного пользовательского ZIP
scripts/verify_public_release.py          проверка PUBLIC-TEST ZIP
```

## Пользовательская документация

```text
docs/INSTRUCTIONS_RU.md             эксплуатационная инструкция
docs/INSTRUCTIONS_EN.md             operating instructions
docs/EMERGENCY_URSUSBOOT_RU.md      аварийная UART/BootROM инструкция
docs/CHANGELOG_RU.md                история опубликованных изменений
docs/CHANGELOG_EN.md                released change log
```

## Контроль целостности репозитория

`SHA256SUMS` в корне охватывает файлы текущего GitHub-снимка. Перед публикацией проверка выполняется через:

```bash
python3 scripts/verify_repo.py
```

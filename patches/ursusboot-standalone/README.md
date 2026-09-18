# Патчи для репозитория airoha-ursusboot

Эти патчи предназначены **не для этого репозитория**, а для
[Medvedolog/airoha-ursusboot](https://github.com/Medvedolog/airoha-ursusboot).
Они лежат здесь только потому, что в тот репозиторий нет доступа на запись.

Базовый коммит: `59053d41` («Update README.md»).

## Файлы

```text
0000-all.patch                                       всё сразу (код + README)
0001-data-driven-build-fip-packing-and-qa-guards.patch  только сборка и QA
0002-readme.patch                                     только README
ursusboot-README.md                                   готовый README.md целиком
```

## Применение

```bash
cd /path/to/airoha-ursusboot
git apply /path/to/0000-all.patch
bash scripts/qa.sh
```

Проверено: патч применяется чисто на `59053d41`, `qa.sh` после него проходит.

## Что меняется

**`build.sh`** — убран хардкод имён бордов и починен мёртвый второй аргумент:
`ROLE` принимался, документировался и никогда не применялся. Борд, конфиг,
шаблон boot-области и reference-FIP теперь берутся из
`config/board-profiles.json`, роль реально применяется через
`scripts/apply_runtime_role.py`.

**Собранный U-Boot теперь реально попадает в образ.** Раньше `build.sh`
компилировал `u-boot.bin`, а в `ursusboot-install-mtd0.bin` клал **reference-FIP**
— то есть чужой, заранее собранный загрузчик. Звенья цепочки
(`lzma1ext_noeopm` → `repack_persistent_fip.py`) лежали в дереве, но не
вызывались ниоткуда. Теперь сборка пакует свежий BL33 в FIP через donor-контейнер
и падает с внятной ошибкой, если `liblzma` недоступна, вместо тихой подмены.

**`config/board-profiles.json`** — добавлены поля `config`,
`boot_area_template`, `reference_fip`. У `xg140-md` они `null`: борд описан,
но не собирается, и это теперь явное состояние с внятной ошибкой.

**`scripts/resolve_board_profile.py`** — новые поля доступны через `--field`.

**`scripts/qa.sh`** — регрессионные проверки: объявленные профилями пути
обязаны существовать, `default_role` обязан быть валидным, `build.sh` не имеет
права хардкодить имена бордов и обязан вызывать три своих скрипта.

**`README.md`** — добавлен раздел **«Flashing the built image to mtd0»**: как
прошить собранный 512 КиБ образ через сток-телнет root (проверки `/proc/mtd`,
bad_blocks, обязательный бэкап с проверкой на ПК, четыре варианта writer'а,
обязательный readback по SHA256) и через XMODEM/UART — как с живой консоли
U-Boot (`loadx` + `mtd erase`/`mtd write`), так и с кирпича через двухстадийный
Airoha BootROM. Плюс разделы про структуру репозитория, host-скрипты,
семь встроенных команд, env-скрипты, структуру веб-интерфейса, таблицу всех
кнопок (endpoint → подтверждение → предусловия → эффект), конвейер
подготовки/прошивки и HTTP API. Плюс раздел «What UrsusBoot actually is»:
это обычный U-Boot 2026.07 с патчами OpenWrt/Airoha, где сохранены 65 стоковых
команд (+7 своих), а отключены 95 групп, не нужных NAND-роутеру.

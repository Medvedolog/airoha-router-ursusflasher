# Патчи для репозитория airoha-ursusboot

Патчи предназначены **не для этого репозитория**, а для
[Medvedolog/airoha-ursusboot](https://github.com/Medvedolog/airoha-ursusboot).
Лежат здесь только потому, что в тот репозиторий нет доступа на запись.

Вмерджено ранее и удалено отсюда: data-driven `build.sh`, упаковка FIP,
QA-стражи, README (в `43fca746`); фикс `borrowed` netif в `ping.c` (в составе
MAC-ветки, сторожится `qa.sh:53-54`).

## Открытый патч

```text
0004-mf-env-overwrite-and-mac-boot-order-docs.patch   база: ef171bc5
```

Проверено: применяется чисто на `ef171bc5`, `qa.sh` проходит, негативный тест
нового стража срабатывает.

## Что он делает

### 1. `CONFIG_ENV_OVERWRITE=y` для MF — реальный баг

В `config/u-boot.TEST61.full.config:779` эта опция есть, в
`an7583_nokia_xg-040g-mf_MF2_RAM_defconfig` её не было, а в `env/Kconfig`
у неё нет `default` → она равна `n`.

По `include/env_flags.h:50-58` это переключает флаг переменной с `ethaddr:ma`
(перезаписываемая) на `ethaddr:mo` — **write-once**. Последствие на MF: как
только `ethaddr` однажды сохранён, `env readmem -b ethaddr` отвергается,
`ethaddr_factory` уходит в ветку `else` и печатает
`WARN: URSUS_MAC_RI_READ_FAIL fallback=persisted` на **каждой** загрузке, хотя
`ri` читается нормально. MAC при этом остаётся стабильным, поэтому HW-тест
формально «пройдёт», но диагностика будет врать, а однажды залипший неверный
адрес нельзя будет исправить иначе как через `reset_factory`.

Патч добавляет опцию в MF-defconfig и страж в `qa.sh` на оба конфига.

### 2. Документирование порядка загрузки

`eth_post_probe()` отрабатывает **раньше** `preboot`:

```text
board_r.c  INITCALL(initr_net)      -> eth probe -> eth_post_probe()
board_r.c  INITCALL(run_main_loop)  -> main_loop() -> preboot -> ethaddr_factory
```

Если в env нет `ethaddr` (свежее устройство либо первая загрузка после того,
как `reset_factory` обнулил env), `net/eth-uclass.c:628-633` генерирует
случайный MAC, **пишет его в env и программирует в контроллер**, печатая
`Warning: … using random MAC address`. И только потом `ethaddr_factory`
исправляет env из `ri`.

Без этого в README строка `Warning: … using random MAC address` в логе
HW-прогона читается как «фикс не сработал», хотя означает лишь, что в тот
момент env был пуст. Ключевой признак успеха — идущая следом строка
`URSUS_MAC_SOURCE=RI ethaddr=…`. Сгенерированный адрес всегда локально
администрируемый (`net_random_ethaddr()` в `include/net-common.h:376-377`
ставит бит `0x02`), то есть отличается от заводского с одного взгляда.

## Чего патч намеренно НЕ делает

Ранее предлагалось убрать `CONFIG_NET_RANDOM_ETHADDR`. После разбора
`net/eth-uclass.c:626-638` это предложение **отозвано**: без него устройство с
повреждённым томом `ri` получает `Error: No valid MAC address found`, остаётся
вообще без сети и теряет WebFailsafe — ровно в том сценарии расшивки, ради
которого он существует. Случайный MAC как последний рубеж оставлен осознанно,
и `WARN:`-строки `ethaddr_factory` называют, какой именно fallback сработал.

## Применение

```bash
cd /path/to/airoha-ursusboot
git apply /path/to/0004-mf-env-overwrite-and-mac-boot-order-docs.patch
bash scripts/qa.sh
```

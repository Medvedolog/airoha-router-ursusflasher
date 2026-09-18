# Патчи для репозитория airoha-ursusboot

Патчи предназначены **не для этого репозитория**, а для
[Medvedolog/airoha-ursusboot](https://github.com/Medvedolog/airoha-ursusboot).
Лежат здесь только потому, что в тот репозиторий нет доступа на запись.

Вмерджено ранее и удалено отсюда: data-driven `build.sh`, упаковка FIP,
QA-стражи и README (`43fca746`); `borrowed`-фикс в `ping.c`; `CONFIG_ENV_OVERWRITE=y`
для MF и раздел «Recovery MAC identity» (`e5ae5747`).

## Открытый патч

```text
0005-docs-hw-test-mac.patch   база: e5ae5747
```

Проверено: применяется чисто на `e5ae5747`, `qa.sh` после применения проходит.

## Что в нём

Новый файл `docs/HW_TEST_MAC.md` — стендовая процедура проверки стабильности
recovery-MAC. Тест A/B/C из обсуждения, оформленный так, чтобы им можно было
пользоваться у железа: таблицы для заполнения, явные критерии PASS и — главное —
таблица чтения UART-лога.

Последнее существеннее всего: строка `Warning: … using random MAC address` сама
по себе **не** означает провал. Ethernet-проба отрабатывает раньше `preboot`,
поэтому на загрузке с пустым env случайный MAC успевает попасть в env и в
контроллер до того, как `ethaddr_factory` прочитает `ri`. Признак успеха —
идущая следом строка `URSUS_MAC_SOURCE=RI ethaddr=…`. Без этого пояснения
нормальная первая загрузка после `reset_factory` читается как FAIL.

Тест C отдельно ловит расхождение env и MAC-фильтра контроллера — то самое
следствие порядка инициализации, которое нельзя увидеть ни в CI, ни по
`printenv`.

## Применение

```bash
cd /path/to/airoha-ursusboot
git apply /path/to/0005-docs-hw-test-mac.patch
bash scripts/qa.sh
```

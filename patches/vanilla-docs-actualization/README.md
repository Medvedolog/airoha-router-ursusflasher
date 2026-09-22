# Актуализация Vanilla-документации под прямой item 4

Патч для ветки `feature/ursusboot-modular-airoha` — этой ветки нет в моём
рабочем дереве, поэтому изменение лежит здесь, а не коммитом.

## Что внутри

`0001-docs-actualize-item4-for-the-direct-ursusboot-stock-to-ubi-path.patch`

Правит два документа, которые всё ещё объявляли нормативным снятый
pregnant/SLOT2 путь:

| Файл | Что добавлено |
|---|---|
| `docs/MD_VANILLA_HANDOFF.md` | баннер статуса в шапке + раздел 21 |
| `docs/UrsusBoot_UrsusFlasher_TZ_RU_v5.45_VANILLA_INITRAMFS.md` | баннер статуса в шапке + раздел 19 |

Старые разделы не удалены: они остаются историей решений, источником
доказанных аппаратных фактов и обоснованием negative-проверок в
`selftest_item4_direct_ubi.py`. Баннер и таблицы в новых разделах говорят
построчно, что из них больше не применяется к item 4, а что остаётся в силе.

## База

Патч собран поверх `4ff3a42bd6a3161d2d156354f651043b4ec57d33`
(`ci: reuse bundle path resolver for direct item4`).

## Применение

```sh
git checkout feature/ursusboot-modular-airoha
git am patches/vanilla-docs-actualization/0001-docs-actualize-item4-for-the-direct-ursusboot-stock-to-ubi-path.patch
```

Если ветка ушла вперёд и `git am` не ложится, конфликтов по существу быть не
должно: патч добавляет текст в конец обоих файлов и одну вставку в шапку.

## Источники утверждений

Всё в новых разделах взято из кода на `4ff3a42`, а не из переписки:

```text
ursusflasher/src/ursusboot_pregnant.py          run_expert: путь и гейты
ursusflasher/src/ursus_web_client.py:488        update_firmware: upload/эндпоинты/заголовки
ursusflasher/src/expert.py                      формулировки пункта 4 меню
ursusflasher/tools/selftest_item4_direct_ubi.py negative-проверки контракта
.github/workflows/md-item4-direct-ubi.yml       состав MD test kit
```

и из репозитория UrsusBoot:

```text
src/u-boot/cmd/ursusweb.c:2194                  POST /api/install-ubi, отказы 409
src/u-boot/cmd/ursusubi.c                       стадии миграции, семь томов, BL2 LAST
```

## Побочный эффект

Оба файла перечислены в `paths:` воркфлоу
`.github/workflows/vanilla-initramfs-item4-test.yml`, поэтому применение
патча запустит эту 120-минутную сборку. Содержимое документов она не
проверяет — триггер только по пути.

## Связанное изменение

`docs/HW_TEST_ITEM4_RU.md` в этой ветке переписан под новые контрольные точки
отдельным коммитом: старая версия ожидала `SLOT2 selected`, загрузку pregnant
runtime и откат через `ursusstockslot master`.

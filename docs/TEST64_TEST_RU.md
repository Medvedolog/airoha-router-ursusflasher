# TEST64 — аппаратный тест MD и MF: Nokia STOCK → OpenWrt UBI → Vanilla U-Boot

UrsusBoot `0.1.0-alpha5-UBIUX1-TEST64` собран в `Medvedolog/airoha-ursusboot` на
закреплённом коммите (см. `data/URSUSBOOT_RELEASE.json`). В комплекте:

- быстрый BL2: при загрузке он сканирует UBI сразу, без полного прохода по NAND;
- закреплённый Vanilla OpenWrt U-Boot FIP для каждой платы
  (`data/payloads/<md|mf>/vanilla/`). Это тот же донорский FIP, что и у UrsusBoot,
  но с другим BL33: OpenWrt U-Boot 2026.07 с поддержкой Fudan. UrsusBoot примет
  только этот FIP.

MD (AN7581) и MF (AN7583) тестируются одинаково: каждый начиная от **Nokia STOCK**.

## Перед началом

1. Сбросьте Nokia на заводские настройки: Reset, **не меньше 20 секунд** (как в INSTRUCTIONS_RU.md).
2. Подключитесь в **LAN2 или LAN3**.
3. Подключите USB-UART 3,3 В (TX, RX, GND; **VCC не подключать**) и пишите лог с
   момента включения. После перехода на Vanilla WebFailsafe UrsusBoot больше нет:
   если что-то пойдёт не так, восстановление возможно только через UART
   (пункты 5 и 9).
4. Выпишите хэши своей платы из `data/URSUSBOOT_RELEASE.json`:
   `ubi_preloader_sha256`, `ubi_bl2_image_sha256`, `vanilla_fip_sha256`.

## Прогон

`START_EXPERT` → пункт **4** (Stock Nokia → OpenWrt UBI → Vanilla U-Boot):

1. Ставится UrsusBoot TEST64 (MD — в mtd0, MF — постоянный runtime). Перед этим
   снимается полный бэкап, либо используется уже готовый.
2. UrsusBoot Recovery выполняет переход STOCK→UBI с быстрым BL2 (подтверждение y/N).
3. Отдельное подтверждение y/N: UrsusBoot заменяется закреплённым Vanilla U-Boot.
   Запись идёт в UBI `fip`; UrsusBoot остаётся в `fip.old`.
4. Роутер перезагружается. UrsusFlasher ждёт OpenWrt и по SSH сверяет хэш тома `fip`.

Не выключайте питание во время записи.

## Что проверить

| # | Проверка | Ожидается |
|---|---|---|
| 1 | Лог перехода | `URSUS_UBI_PRELOADER_VALID ... sha256=` = `ubi_preloader_sha256` |
| 2 | Лог перехода | `URSUS_UBI_MIGRATION_BL2_VERIFIED ... sha256=` = `ubi_bl2_image_sha256` |
| 3 | Лог Vanilla | `URSUS_UBI_INSTALLED_BL2 OK`, `URSUS_UPDATE_ARMED kind=VANILLA layout=UBI` |
| 4 | Лог Vanilla | `URSUS_UPDATE_COMMIT_OK layout=UBI kind=VANILLA backup=fip.old` и `URSUS_VANILLA_REPLACE_COMPLETE` |
| 5 | UART после перезагрузки | быстрый BL2, затем `U-Boot 2026.07` **без** `UrsusBoot` |
| 6 | Загрузка | OpenWrt стартует с UBI без вмешательства; время загрузки (засеките) |
| 7 | UrsusFlasher | `OpenWrt booted through Vanilla U-Boot; UBI fip = the pinned Vanilla FIP` |
| 8 | OpenWrt, по желанию | `sha256sum` тома `fip` = `vanilla_fip_sha256`; том `fip.old` существует |
| 9 | Только MF | MAC совпадает с заводским (RI) |

Если на шаге 3 ответить «нет», OpenWrt остаётся установленным, а UrsusBoot остаётся
загрузчиком-Recovery. Это тоже корректный результат: вернуться к пункту 4 или
сделать замену из WebFailsafe («Заменить UrsusBoot на Vanilla U-Boot») можно позже.

## Что прислать

Модель (MD/MF), ревизию платы, если известна, `URSUSFLASHER_COMMIT.txt` из
артефакта, SHA256 ZIP, UART-лог, лог UrsusFlasher из `work/`, наблюдаемый MAC,
состояние NAND/bad-блоков и какие пункты таблицы прошли или не прошли.

Не публикуйте серийные номера, GPON-учётные данные и полные бэкапы flash.

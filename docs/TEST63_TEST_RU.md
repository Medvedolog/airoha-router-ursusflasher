# TEST63 — аппаратный тест MD и MF

UrsusBoot `0.1.0-alpha5-UBIUX1-TEST63` собран в `Medvedolog/airoha-ursusboot` на
закреплённом коммите (см. `data/URSUSBOOT_RELEASE.json`). Вместе с ним в комплекте
быстрый BL2: при загрузке он сканирует UBI сразу, без полного прохода по NAND.

MD (AN7581) и MF (AN7583) тестируются одинаково: каждый от **Nokia STOCK**.

## Перед началом

1. Сбросьте Nokia на заводские настройки: Reset, **не меньше 20 секунд**.
2. Подключитесь в **LAN2 или LAN3**.
3. По возможности подключите USB-UART 3,3 В (TX, RX, GND; **VCC не подключать**) и
   пишите лог с момента включения.
4. Выпишите хэши своей платы из `data/URSUSBOOT_RELEASE.json`:
   `boards.<md|mf>.ubi_preloader_sha256` и `boards.<md|mf>.ubi_bl2_image_sha256`.

## Прогон

`START_EXPERT` → пункт **4** (Stock Nokia → OpenWrt UBI с UrsusBoot Recovery).

- MD: ставится UrsusBoot TEST63, затем Recovery выполняет переход STOCK→UBI.
- MF: ставится MF runtime TEST63 с полным бэкапом (готовый бэкап можно
  переиспользовать), затем Recovery выполняет переход STOCK→UBI.

Не выключайте питание во время записи.

## Что проверить

| # | Проверка | Ожидается |
|---|---|---|
| 1 | Лог перехода | `URSUS_UBI_PRELOADER_VALID ... sha256=` = `ubi_preloader_sha256` |
| 2 | Лог перехода | `URSUS_UBI_MIGRATION_BL2_VERIFIED ... sha256=` = `ubi_bl2_image_sha256` |
| 3 | Readback BL2 после записи | тот же хэш 128 KiB, что в п. 2 |
| 4 | Перезагрузка | OpenWrt грузится с UBI **без** Recovery |
| 5 | UART | в логе BL2 виден быстрый путь сканирования |
| 6 | Время загрузки | заметно меньше, чем с прежним preloader (засеките) |
| 7 | WebFailsafe `/api/status` | версия `0.1.0-alpha5-UBIUX1-TEST63` |
| 8 | Только MF | при загрузке `URSUS_MAC_SOURCE=RI`, MAC совпадает с заводским |

## Что прислать

Модель (MD/MF), ревизию платы, если известна, `URSUSFLASHER_COMMIT.txt` из
артефакта, SHA256 ZIP, UART-лог, лог UrsusFlasher из `work/`, наблюдаемый MAC,
состояние NAND/bad-блоков и какие пункты таблицы прошли или не прошли.

Не публикуйте серийные номера, GPON-учётные данные и полные бэкапы flash.

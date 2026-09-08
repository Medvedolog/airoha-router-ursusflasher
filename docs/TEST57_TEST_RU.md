# TEST57 — минимальный аппаратный прогон

UrsusFlasher 0.2.57 PUBLIC TEST / UrsusBoot `0.1.0-alpha5-UBIUX1-TEST57`.

Цель — проверить только то, что нельзя доказать selftest/CI. Длинные циклы перезаписей не требуются.

1. Один раз загрузить TEST57 и войти в Recovery удержанием Reset. Должны появиться `URSUS_WEBFAILSAFE_READY` и Web `192.168.1.1`.
2. На существующей OpenWrt нажать «Сбросить настройки OpenWrt». UART должен показать обработку `/api/reset-openwrt-settings` и итог `URSUS_OPENWRT_SETTINGS_RESET_OK` либо точную структурированную ошибку; простая «Ошибка сброса» без причины — FAIL.
3. Один штатный self-update FIP через EXPERT пункт 2. После 100%/COMPLETION не должно быть автоматического перехода на TFTP.
4. Один сетевой fault-test во время upload: кратко разорвать Ethernet/дать TCP reset до начала flash-write. Передача должна восстановиться ограниченными retry/reconcile либо завершиться как transport failure с явным `flash write not started`; второй writer автоматически не запускается.
5. При искусственном/реальном PRECHECK failure проверить `work/diagnostics/<timestamp>-*/`: `status.json`, operation/web log и read-only console snapshots.
6. Сверить `/api/status`: NAND vendor/model/id, page/OOB/erase size, bad-block count и UBI layout должны соответствовать UART. На известном SkyHigh ожидается `S35ML02G300`, ID `0125`, 256 MiB.

Отдельное наблюдение, не блокирующее TEST57: BL2 до U-Boot выполняет полный UBI scan `0x20000..0x10000000`, на текущем железе до ~12 секунд. Оптимизация — BL2UBISCAN1.

# TEST59 — короткий аппаратный regression

Цель: проверить только corrective-изменения поверх уже пройденного основного ONE-CLICK.

1. Загрузить UBI sysupgrade в UrsusBoot Recovery после предыдущей COMPLETE/FAILED операции. Убедиться, что видна галочка **«Сохранить настройки OpenWrt»**.
2. Один update выполнить с галочкой; UART должен показать `keep_settings=1`.
3. При удобном тестовом цикле снять галочку; UART должен показать `keep_settings=0`, а reset/recreate `rootfs_data` должен завершиться успешно.
4. После успешного обычного UBI update нажать **«Перезагрузить в OpenWrt»**. Ожидаются `URSUS_WEBREBOOT_RESPONSE_QUEUED` и reset после grace period.
5. Проверить UART: проектные machine-log строки только English/printable ASCII; кириллица в UART считается FAIL.
6. Headroom regression: для состояния `free=7`, `current_fit=82`, candidate `76 LEB` PRECHECK должен разрешить direct Recovery-safe replacement и показать `projected_free=13`; запись и readback должны завершиться COMPLETE.

Не требуется заново доказывать весь stock ONE-CLICK, если эти проверки выполняются на уже рабочем TEST59 устройстве.

# TEST58 — короткий аппаратный регрессионный прогон

UrsusFlasher 0.2.58 PUBLIC TEST / UrsusBoot `0.1.0-alpha5-UBIUX1-TEST58`.

Основной ONE-CLICK stock→OpenWrt уже доказан на .57/TEST57. Для .58 нужны только новые регрессии:

1. После записи UrsusBoot ONE-CLICK должен ждать Recovery до 90 секунд и не принимать старый stock Web за новую загрузку; отрицательных секунд в UI быть не должно.
2. В UART/Web/API дата сборки TEST58 должна быть 08.09.2026, версия — TEST58.
3. После любой write-capable операции должен появиться каталог `work/diagnostics/...` с `status-before.json`, `status-after.json`, `operation-log.txt`, `web-log.txt`, `console.txt`, `operation.json`.
4. Полный `session-*.log` должен содержать `[URSUS_STATUS_BEFORE]`, `[URSUS_STATUS_FULL]`, `[URSUS_STATUS_AFTER]`, `[URSUS_OPERATION_LOG]`, `[URSUS_CONSOLE_SNAPSHOT]`, `[DIAGCAP2_END]`.
5. `LATEST.log` остаётся читаемым и содержит только строку с путём к полному diagnostic bundle, а не большие JSON-блоки.

BL2 full-UBI scan до ~12 секунд остаётся отдельной performance-задачей BL2UBISCAN1 и в TEST58 не оптимизируется.

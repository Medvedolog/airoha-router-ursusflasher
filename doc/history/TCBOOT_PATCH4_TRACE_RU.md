# tcboot MD patch4 TRACE — аппаратный LAB

## Причина исправления

Первый HW upload patch1 принял официальный MD sysupgrade.itb и прошёл FIT/iminfo, затем остановился на намеренной негативной boundary-проверке `mtd read ubi ... 0xff00000`: U-Boot корректно вернул `-22`, но HTTP upgrade трактовал это как failure. `mtd erase ubi` не запускался.

patch4 полностью удаляет проверки, которые должны специально завершаться ошибкой.

## Новый state probe

- `U:FIT_CHECK_BEGIN` / `U:FIT_CHECK_OK`
- `U:UBI_PROBE_BEGIN`
- чтение `ubi` offset 0 должно успешно выполниться
- UBI magic `0x23494255` -> существующий UBI, attach обязан пройти
- magic отсутствует -> stock-to-UBI migration

## UART destructive trace

- `U:UBI_MIGRATION_BEGIN`
- `U:CAL_SAVE_BEGIN` / `U:CAL_SAVE_OK`
- `U:UBI_FORMAT_BEGIN` / `U:UBI_FORMAT_DONE`
- `U:UBI_ATTACH_BEGIN` / `U:UBI_ATTACH_OK`
- `U:UBI_CORE_CREATE_BEGIN` / `U:UBI_MIGRATION_OK`
- `U:CAL_BOSA_RESTORE_BEGIN/OK`
- `U:CAL_RI_RESTORE_BEGIN/OK`
- `U:FIT_VOLUME_CREATE_BEGIN`
- `U:FIT_WRITE_BEGIN/DONE`
- `U:FIT_READBACK_BEGIN/OK`
- `U:ROOTFS_DATA_CREATE_BEGIN`
- `U:VOLUMES_READY`
- `U:ENV_SAVE_BEGIN/OK`
- `U:FLASH_COMPLETE_RESET`
- `U:BOOT_OPENWRT_BEGIN`

Отсутствие парного `*_DONE`/`*_OK` показывает точную стадию failure.

# TEST61 — аппаратный safety regression

TEST59 и TEST60 для новых аппаратных прогонов не использовать. TEST61 проверяет прежде всего отсутствие лишних/необоснованных persistent write и восстановление после сетевых сбоев.

## A. Identity и direct stock path

1. На Nokia STOCK запустить обычный ONE-CLICK с полным backup.
2. После успешного backup/preflight убедиться, что перед первой записью `mtd0` есть ровно один вопрос `Начать запись mtd0? [y/N]`.
3. После `y` должна быть ровно одна direct запись `mtd0` и полный readback/SHA256 PASS.
4. После reboot в Recovery сравнить native `version` и `/api/status`: оба должны показывать `0.1.0-alpha5-UBIUX1-TEST61`.
5. ONE-CLICK не должен автоматически загружать/записывать FIP второй раз. Если доступна другая версия UrsusBoot, допускается только информационное сообщение о ручном обновлении.

Для повторных лабораторных прогонов EXPERT пункт 1 может по отдельному `[y/N]` пропустить полный backup. Это не отменяет отдельный `[y/N]` перед direct `mtd0` write.

## B. Explicit UrsusBoot self-update / UBIATTACH2

На уже работающем `OPENWRT_UBI` выполнить обновление UrsusBoot только вручную через WebFailsafe/EXPERT.

PASS:
- текущий `ubi0` уже прикреплён к ожидаемому `ursus-ubi-full` и используется как есть;
- в UART нет `ubi detach` перед FIP writer;
- виден `URSUS_UPDATE_UBI_REUSE ... action=NO_DETACH`;
- write/readback завершаются успешно.

Если attachment не соответствует ожидаемому MTD, операция должна остановиться до writer с `UBI_ATTACHMENT_MISMATCH` / `transaction=NOT_STARTED`.

## C. Ethernet fault injection

Отдельно для FIP и FIT upload выдернуть Ethernet примерно на 20%, 50% и 90% передачи.

Для каждого случая:
- клиент ждёт восстановление текущей upload-session до 75 секунд;
- если сессия потеряна, новый полный transfer cycle не начинается автоматически;
- оператору предлагается `Повторить передачу файла с начала? [y/N]`;
- до вызова operation endpoint `transaction_state=NOT_STARTED`;
- `operation.json` фиксирует `NOT_STARTED`;
- persistent FIP SHA до/после оборванной передачи совпадает;
- после power-cycle UrsusBoot загружается с тем же persistent FIP.

После `N` интерфейс должен оставаться пригодным для новой ручной попытки. После `y` начинается один новый полный upload.

## D. Session recovery

Спровоцировать по одному failure на upload, validation и precheck до persistent writer.

PASS: WebFailsafe сохраняет diagnostics/history, но позволяет сразу начать новую upload/operation; reboot не требуется только ради очистки старого FAILED. `WRITE_STATE_UNKNOWN` по-прежнему запрещает автоматический новый writer.

## E. OpenWrt UBI update

1. `keep_settings=1`: update/readback COMPLETE; затем UrsusFlasher предлагает необязательный reset OpenWrt settings перед reboot.
2. `keep_settings=0`: update/readback COMPLETE; `rootfs_data` пересоздан; повторный reset не предлагается.
3. После любого upload/validation/precheck failure до writer новая попытка доступна без stale UI lock.

## F. CONFIGTRIM1 smoke regression

- normal boot: `bootcmd=ursusdispatch`;
- Recovery WebFailsafe доступен;
- `ubi`, `tftpboot`, `wget` доступны;
- `ubifsmount`, `ubifsload`, `ubifsls`, `ubifsumount`, `pxe` отсутствуют;
- reset OpenWrt settings создаёт новый `rootfs_data`, Linux затем создаёт/mount UBIFS;
- никаких неожиданных persistent-layout изменений вне выбранной операции.

При любом write failure сохранить DIAGCAP2 bundle до следующей попытки.

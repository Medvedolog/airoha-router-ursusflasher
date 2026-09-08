# TEST60 — короткий аппаратный regression CONFIGTRIM1

Цель: доказать, что удаление UBIFS filesystem commands и PXE/extlinux boot path не затронуло рабочие сценарии UrsusBoot.

## Что изменено

```text
CONFIG_CMD_UBIFS=n
CONFIG_CMD_PXE=n
CONFIG_BOOTMETH_EXTLINUX=n
CONFIG_BOOTMETH_EXTLINUX_PXE=n
CONFIG_PXE_UTILS=n
```

Сохранено:

```text
CONFIG_CMD_UBI=y
CONFIG_MTD_UBI=y
CONFIG_CMD_TFTPBOOT=y
CONFIG_CMD_WGET=y
bootcmd=ursusdispatch
```

## Минимальный HW regression

1. Загрузить TEST60 обычным self-update UrsusBoot и выполнить readback.
2. Холодная загрузка OpenWrt без Reset.
3. Вход в UrsusBoot Recovery по Reset; WebFailsafe должен открыться.
4. Проверить диагностику NAND/UBI и наличие `fip`, `fit`, `rootfs_data`.
5. Выполнить standalone «Сбросить настройки OpenWrt»; после reboot Linux должен создать/смонтировать новый UBIFS на пустом `rootfs_data`.
6. Обновить OpenWrt с `keep_settings=1`, затем отдельным прогоном с `keep_settings=0`; оба пути должны завершиться readback/COMPLETE.
7. Проверить кнопку «Перезагрузить в OpenWrt» после обычного UBI update.
8. Проверить self-update UrsusBoot и reboot после него.
9. В U-Boot help не должны присутствовать `ubifsmount`, `ubifsload`, `ubifsls`, `ubifsumount`, `pxe`; `ubi`, `tftpboot`, `wget` должны присутствовать.

## Acceptance

PASS, если все пункты выше выполнены без изменения persistent layout/данных сверх выбранной операции и без новых ошибок PRECHECK/WRITE/VERIFY.

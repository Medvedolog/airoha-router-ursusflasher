# tcboot MD patch6 BOOTFIX — LAB

## Основание

Аппаратный patch5 уже корректно мигрирует stock layout в UBI, создаёт `fit` по полному HTTP upload size, пишет и полностью читает его обратно, сохраняет env и после reboot повторно проходит FIT hashes. Отказ происходит после успешной загрузки/relocation FDT: `subcommand failed (err=-1)`.

## Изменение

Удалены `bootm cmdline` и `bootm bdt`. tcboot сохраняется. Boot chain:

```text
U:BOOT_OPENWRT_BEGIN
U:BOOT_START_BEGIN -> bootm start -> U:BOOT_START_OK
U:LOADOS_BEGIN -> bootm loados -> U:LOADOS_OK
U:RAMDISK_BEGIN -> bootm ramdisk -> U:RAMDISK_OK
U:FDT_LOAD_BEGIN -> bootm fdt -> U:FDT_LOAD_OK
U:FDT_PATCH_BEGIN -> patch UBI reg in relocated FDT -> U:FDT_PATCH_OK
U:PREP_BEGIN -> bootm prep -> U:PREP_OK
U:KERNEL_GO -> bootm go
```

## Recovery invariant

`0x000000..0x07ffff` tcboot и `0x080000..0x0fffff` tcboot env не входят в UBI erase range. После успешного OpenWrt tcboot WebFailsafe должен по-прежнему запускаться power-cycle + Reset сразу после включения 10 секунд (HW VERIFIED).

Status: `LAB_WRITE_BOOTFIX`.

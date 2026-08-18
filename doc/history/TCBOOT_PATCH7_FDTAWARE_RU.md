# tcboot patch7 FDT-AWARE — HW VERIFIED

## Результат аппаратного теста

На реальном Nokia XG-040G-MD patch7 прошёл целевой gate полностью:

```text
U:FDT_LOAD_OK
U:FDT_PATCH_BEGIN
U:FDT_PATH=/soc/spi@1fa10000/nand@0/partitions/partition@20000
reg = <0x00100000 0x0ff00000>
U:FDT_PATCH_OK
U:PREP_OK
U:KERNEL_GO
Starting kernel ...
Linux 6.18.44
Machine model: Nokia XG-040G-MD (UBI)
ubi0 attached
UBIFS rootfs_data mounted
mount_root: switching to ubifs overlay
procd: - init -
Please press Enter to activate this console.
```

Таким образом, динамический поиск `label="ubi"`, `fdt set $up reg`, relocation через `bootm prep`, UBI attach и production rootfs подтверждены на железе. Старый raw-memory `cp.b` path окончательно запрещён.

## Постоянный WebFailsafe

После работающего OpenWrt tcboot остаётся в первых 0x80000 NAND. Аппаратно проверенный вход:

```text
power OFF
power ON
сразу нажать Reset
держать 10 секунд
отпустить
```

Reset до подачи питания не удерживать: это BootROM `Press x`.

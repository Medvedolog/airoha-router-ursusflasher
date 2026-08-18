# tcboot patch7 FDT-AWARE — HW VERIFIED

## Hardware result

On a real Nokia XG-040G-MD patch7 passed the complete target gate:

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

Dynamic `label="ubi"` discovery, `fdt set $up reg`, relocation through `bootm prep`, UBI attach, and production rootfs are therefore hardware-confirmed. The old raw-memory `cp.b` path remains forbidden.

## Persistent WebFailsafe

After OpenWrt boots, tcboot remains in the first 0x80000 NAND. Hardware-verified entry gesture:

```text
power OFF
power ON
immediately press Reset
hold for 10 seconds
release
```

Do not hold Reset before applying power; that is the BootROM `Press x` path.

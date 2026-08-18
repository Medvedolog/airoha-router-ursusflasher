# tcboot MD patch6 BOOTFIX — LAB

## Basis

The patch5 hardware run already performs stock-to-UBI migration correctly, creates `fit` using the complete HTTP upload size, writes and reads it back in full, saves the environment, and verifies all FIT hashes after reset. The failure occurs after successful FDT load/relocation with `subcommand failed (err=-1)`.

## Change

`bootm cmdline` and `bootm bdt` are removed while tcboot is retained. Boot chain:

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

`0x000000..0x07ffff` tcboot and `0x080000..0x0fffff` tcboot environment remain outside the UBI erase range. After a successful OpenWrt boot, tcboot WebFailsafe must still be reachable by power-cycling and holding Reset immediately after power-on for 10 seconds (HW VERIFIED).

Status: `LAB_WRITE_BOOTFIX`.

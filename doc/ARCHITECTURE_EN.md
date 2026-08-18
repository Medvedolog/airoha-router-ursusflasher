# UrsusFlasher MD: architecture and tcboot know-how

**Release:** 0.1.0-md-lab1fix10  
**Target:** Nokia XG-040G-MD / Airoha AN7581 / 256 MiB SPI-NAND  
**Status:** the main tcboot → OpenWrt path and tcboot persistence across a repeated Web sysupgrade are hardware verified.

## 1. Architecture decision

UrsusFlasher does not replace tcboot with the OpenWrt U-Boot. tcboot remains the permanent independent recovery loader while production OpenWrt lives in UBI.

```text
Airoha early boot stages
        |
        v
+-----------------------------+
| tcboot                      |  NAND 0x00000000..0x0007ffff
| U-Boot 2025.01 + WebFailsafe|
+-----------------------------+
        |
        | persistent env          NAND 0x00080000..0x000fffff
        |
        v
+-----------------------------+
| UBI                         |  NAND 0x00100000..0x0fffffff
|  ubootenv                   |
|  ubootenv2                  |
|  bosa                       |
|  ri                         |
|  fip (compat placeholder)   |
|  fit  <- OpenWrt sysupgrade |
|  rootfs_data                |
+-----------------------------+
        |
        v
OpenWrt Linux
```

The key invariant is: **tcboot Web sysupgrade operations are confined to the UBI region starting at 0x00100000. The first 1 MiB of NAND is outside the erase/update range.**

## 2. Why the official OpenWrt ITB cannot simply be booted unchanged at the DT level

The official `nokia_xg-040g-md-ubi` DTB describes the upstream/OpenWrt layout where UBI starts at `0x00020000`. Ursus reserves the first 1 MiB for tcboot plus its environment.

For the bundled ITB:

```text
official DTB:
reg = <0x00020000 0x0ffe0000>

Ursus/tcboot runtime:
reg = <0x00100000 0x0ff00000>
```

Passing the official DTB to Linux without adjustment makes MTD/UBI use the wrong physical region. Ursus therefore performs a runtime FDT fixup without rewriting the official ITB on disk.

## 3. Host-side FIT/FDT preflight

`data/fit_fdt.py` parses the selected sysupgrade before any destructive action:

```text
FIT header
 -> /configurations/default
 -> actual kernel / fdt / loadables names
 -> image CRC/SHA verification
 -> nested DTB extraction
 -> recursive search for exactly one node label="ubi"
 -> #address-cells / #size-cells
 -> original reg
 -> geometry gate
```

This removes dependency on `config-1`, `fdt-1`, a fixed DT node path, or a particular OpenWrt snapshot.

After preflight, `data/tcboot_builder.py` personalizes only what is required by the actual DTB: the discovered UBI node path and the cell-compatible `fdt set ... reg` command are embedded into tcboot environment logic.

## 4. Core tcboot know-how: FDT-aware boot

Early prototypes copied eight raw bytes into the discovered `reg` property from a fixed RAM address. That was version/relocation-sensitive and produced a corrupted MTD range on hardware.

The current path contains no fixed working-FDT RAM address and does not use raw `cp.b` to patch the DT property.

Boot sequence:

```text
ubi part ubi
ubi read $loadaddr fit
iminfo $loadaddr

bootm start $loadaddr
bootm loados
bootm ramdisk
bootm fdt

fdt set $up reg <0x00100000 0x0ff00000>
fdt print $up reg

bootm prep
bootm go
```

`$up` is the node path discovered on the PC from the actual DTB in the selected sysupgrade. tcboot may relocate the working FDT; this no longer matters because the U-Boot `fdt` command operates on the current FDT object.

Hardware verification reached:

```text
U:FDT_PATCH_BEGIN
reg = <0x00100000 0x0ff00000>
U:FDT_PATCH_OK
U:PREP_OK
U:KERNEL_GO
Starting kernel ...
```

Linux 6.18.44 then sees the correct UBI region, attaches `ubi0`, creates ubiblock for `fit`, mounts UBIFS `rootfs_data`, switches overlay, and starts `procd`.

## 5. WebFailsafe as a permanent recovery layer

Hardware-verified entry sequence:

```text
power OFF
power ON
IMMEDIATELY press Reset
hold for 10 seconds
release
```

Do not hold Reset before power-on; that enters the separate early BootROM `Press x` recovery path.

WebFailsafe exposes `/flashing.html`. Ursus can upload the ITB using a built-in uploader:

```text
HTTP/1.0
multipart/form-data
field = firmware
Content-Length = exact
Connection: close
no chunked
no Expect: 100-continue
```

## 6. How tcboot accepts sysupgrade

The upload handler snapshots the original `$filesize/$fileaddr` into dedicated variables because later UBI commands may overwrite global `$filesize`.

```text
setenv us $filesize
setenv ua $fileaddr
```

This fixes a hardware-discovered failure class where a calibration `ubi read` changed `$filesize` and caused `fit` to be created at only 256 KiB.

The FIT gate validates:

- upload size within the accepted range;
- `iminfo` and FIT hashes;
- `/configurations/default`;
- profile `OpenWrt nokia_xg-040g-md-ubi`;
- kernel/FDT/loadables references.

## 7. First migration from stock UBI

If the UBI start does not contain UBI magic, tcboot enters migration mode:

1. read stock BOSA and RI using raw MTD reads before erase;
2. only after both reads succeed, run `mtd erase ubi`;
3. attach UBI;
4. create `ubootenv`, `ubootenv2`, `bosa`, `ri`, and `fip`;
5. restore BOSA/RI and verify them with UBI readback + `cmp.b`;
6. create `fit` and `rootfs_data`.

A failed calibration read stops the chain before erase.

## 8. Repeated Web sysupgrade and why tcboot survives

When UBI already exists, the handler detects UBI magic and uses the update path:

```text
attach existing ubi
verify ubootenv / ubootenv2 / bosa / ri / fip
remove old fit
remove old rootfs_data
create new fit with exact upload size
write full ITB
read full ITB back
cmp.b full ITB
create new rootfs_data
saveenv
reset
```

**This path never erases the first 1 MiB and never writes mtd0.** tcboot and its environment therefore remain physically intact.

A repeated Web sysupgrade after an already booted OpenWrt installation has been hardware verified: the new OpenWrt installs, tcboot remains the loader, and WebFailsafe is still reachable using the 10-second Reset gesture.

This is the main operational advantage of the architecture: if production OpenWrt is damaged or a new release fails, the recovery UI does not depend on the Linux root filesystem.

### Important limitation

The current update path removes and recreates `rootfs_data`. tcboot WebFailsafe sysupgrade is therefore a **recovery-style reinstall**, not an OpenWrt upgrade that preserves overlay/configuration.

## 9. Why the `fip` volume exists but tcboot does not depend on it

The upstream OpenWrt layout expects an OpenWrt FIP/U-Boot. In the Ursus boot chain, the current `fip` UBI volume is retained as a layout-compatible placeholder, while production boot goes directly from tcboot to UBI `fit`.

```text
tcboot -> UBI fit -> FIT hashes -> kernel/FDT/rootfs -> runtime FDT fixup -> Linux
```

An OpenWrt FIP is therefore not a boot requirement in the current MD architecture.

## 10. Safety invariants

Before tcboot write, Ursus requires:

- model `Nokia XG-040G-MD`;
- SoC `Airoha AN7581`;
- proven UID0;
- `/dev/mtd0` geometry 0x80000 / erase 0x20000 / writesize 2048;
- exact personalized tcboot size 524288 + SHA256;
- write target restricted to `/dev/mtd0`;
- complete 0x80000 readback + byte comparison;
- FIT/FDT compatibility gate before the destructive path.

Unknown state means stop, not guess.

## 11. HW-verified state in fix10

Exact tcboot patch8 bytes:

```text
data/payloads/md/tcboot/tcboot-MD-direct-sysupgrade-patch8-FDTAWARE-BEAR-WRITE.bin
size   524288
SHA256 7c202a9c35dfcc10b85a1ad7f3d8cf34dbabfcb23287f26d9b5376f582772766
```

Verified:

```text
tcboot NAND boot
WebFailsafe + bear branding
10-second Reset entry
FIT upload
first UBI migration
full FIT readback
FDT-aware boot
Linux/UBI/UBIFS/procd
repeat tcboot Web sysupgrade
tcboot persistence after sysupgrade
```

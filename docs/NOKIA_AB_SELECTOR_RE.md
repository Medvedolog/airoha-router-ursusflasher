# Nokia/Airoha stock A/B selector — reverse-engineering notes

Status: stock userspace activation contract proven from MD stock firmware; device writer remains intentionally disabled until TRANSITION slot hardware acceptance.

## Hardware layout

For the examined Nokia XG-040G-MD stock image:

- `mtd8` = `flag`, eraseblock size `0x40000`
- `mtd9` = `flagback`, eraseblock size `0x40000`
- `mtd14` = `nsb_master`, size `0x2880000`
- `mtd15` = `nsb_slave`, size `0x2880000`

The supplied MD `nsb_master` and `nsb_slave` images were byte-identical.

## State record

Stock `libupgrade.so` functions `read_flag()` and `write_flag()` operate on exactly 20 bytes, not 16.

The record is:

```c
struct stock_ab_state {
    uint32_t active;    /* requested image for next boot */
    uint32_t curimg;    /* currently booted image */
    uint32_t startok;   /* userspace boot-success marker */
    uint32_t count;     /* tcboot retry/health counter */
    uint32_t reserved;  /* observed as 0xffffffff */
};
```

Observed MD post-success state:

```text
flag:     active=0 curimg=0 startok=1 count=15 reserved=ffffffff
flagback: active=0 curimg=0 startok=0 count=15 reserved=ffffffff
```

Everything after byte 20 is erased `0xff`.

## `active` vs `curimg`

This distinction is proven from stock code.

`swdl_get_cur_image()` returns field `curimg` at offset `+4`.

`swdl_active(image, task)`:

1. accepts image `0` or `1`;
2. reads `mtd8` with `read_flag(..., 20)`;
3. compares requested image with `curimg`;
4. if they already match, returns without writing;
5. otherwise writes requested image to field `active` at offset `+0`;
6. calls `write_flag("mtd8", record)`.

Therefore `curimg` must not be patched to request a bank switch. The stock request mechanism is `active`.

## Inactive-bank upgrade flow

Stock `batch_upgrade` proves the intended use:

```text
current = swdl_get_cur_image()
target  = (current == 1) ? 0 : 1
swdl_write_image(target, ...)
swdl_active(target, ...)
reboot
```

Its strings include `same image, needn't upgrade, activate it only.` and `active img: %d`.

Stock `upgrade_kernelrootfs()` independently shows the same contract:

- if `curimg == 0`, write the B/SLAVE bank, then set `active = 1` and `write_flag(mtd8)`;
- if `curimg == 1`, write the A/MASTER bank, then set `active = 0` and `write_flag(mtd8)`.

## Boot-success commit

Stock `image_done` reads `mtd8`, logs the four state fields, changes only:

```text
startok = 1
```

and writes `mtd8` back.

This proves that successful Linux userspace acknowledges a boot by setting `startok=1` in the primary flag record.

## `write_flag()` contract

Stock `write_flag()`:

1. opens the named MTD device;
2. obtains MTD geometry;
3. erases one complete eraseblock at offset zero;
4. writes exactly 20 bytes of the state record;
5. leaves the rest of the eraseblock erased.

No checksum/CRC is stored in the flag eraseblock.

## `flagback`

The examined stock userspace activation and success paths write only `mtd8` (`flag`). They do not write `mtd9` (`flagback`).

Therefore UrsusFlasher must not mirror a new selector state into `flagback`. Reconciliation/rollback of `flagback` belongs to tcboot's boot-time state machine.

The exact tcboot repair/rollback threshold of `count` remains a separate hardware/reverse-engineering topic, but it is not required to reproduce the stock userspace request for the next image.

## Stock-compatible activation request

For the observed MD state:

```text
old mtd8 first 20 bytes:
00000000 00000000 01000000 0f000000 ffffffff
```

The stock-compatible request to boot SLAVE is:

```text
new mtd8 first 20 bytes:
01000000 00000000 01000000 0f000000 ffffffff
```

Only `active` changes `0 -> 1`.

`curimg`, `startok`, `count`, and `reserved` are preserved. `mtd9` is untouched.

## UrsusFlasher policy

Current implementation intentionally provides only:

- read-only parser/report;
- offline activation planner reproducing the stock `swdl_active()` state mutation.

The physical selector writer remains disabled until:

1. an MD stock-compatible `UrsusBoot TRANSITION` image exists;
2. it is written and fully read back from the inactive `nsb_slave`;
3. structural/FIT validation passes;
4. only then is the proven stock-compatible `active=1` request committed to `mtd8`;
5. UART is used only as a passive logger for first hardware acceptance.

`mtd0` and stock `bootcmd` remain untouched in this A/B primary path.

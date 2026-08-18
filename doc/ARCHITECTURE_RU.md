# UrsusFlasher MD: архитектура и tcboot know-how

**Release:** 0.1.0-md-lab1fix10  
**Target:** Nokia XG-040G-MD / Airoha AN7581 / SPI-NAND 256 MiB  
**Status:** основной tcboot → OpenWrt path и persistence tcboot через повторный Web sysupgrade подтверждены на реальном железе.

## 1. Архитектурное решение

UrsusFlasher не заменяет tcboot на OpenWrt U-Boot. tcboot остаётся постоянным независимым recovery-loader, а production OpenWrt хранится в UBI.

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

Ключевой инвариант: **операции Web sysupgrade tcboot работают только внутри UBI region, начинающегося с 0x00100000. Первые 1 MiB NAND не входят в erase/update range.**

## 2. Почему официальный OpenWrt ITB нельзя просто bootm без адаптации

Официальный `nokia_xg-040g-md-ubi` DTB описывает upstream/OpenWrt layout, где UBI начинается с `0x00020000`. В Ursus первые 1 MiB зарезервированы под tcboot + environment.

Для комплектного ITB:

```text
official DTB:
reg = <0x00020000 0x0ffe0000>

Ursus/tcboot runtime:
reg = <0x00100000 0x0ff00000>
```

Если передать официальный DTB Linux без исправления, MTD/UBI видит неправильный physical region. Поэтому Ursus делает runtime FDT fixup, не изменяя официальный ITB на диске.

## 3. Host-side FIT/FDT preflight

`data/fit_fdt.py` разбирает выбранный sysupgrade до любых destructive действий:

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

Это убирает привязку к `config-1`, `fdt-1`, жёсткому DT node path и конкретной версии OpenWrt.

После preflight `data/tcboot_builder.py` персонализирует tcboot только тем, что необходимо для фактического DTB: в environment сохраняется найденный UBI node path и cell-compatible `fdt set ... reg`.

## 4. Главное tcboot know-how: FDT-aware boot

Старые эксперименты копировали 8 raw bytes в найденный `reg` по фиксированному RAM address. Это оказалось version/relocation-sensitive и аппаратно дало повреждённый MTD range.

Текущий путь не содержит fixed working-FDT RAM address и не использует raw `cp.b` для DT property.

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

`$up` — node path, найденный на ПК из фактического DTB выбранного sysupgrade. Сам working FDT tcboot может relocat'ить; это больше не важно, потому что U-Boot `fdt` command работает с текущим FDT object.

Аппаратно подтверждено:

```text
U:FDT_PATCH_BEGIN
reg = <0x00100000 0x0ff00000>
U:FDT_PATCH_OK
U:PREP_OK
U:KERNEL_GO
Starting kernel ...
```

После этого Linux 6.18.44 видит корректный UBI, подключает `ubi0`, создаёт ubiblock для `fit`, монтирует UBIFS `rootfs_data`, переключает overlay и запускает `procd`.

## 5. WebFailsafe как постоянный recovery layer

Вход аппаратно подтверждён:

```text
power OFF
power ON
СРАЗУ нажать Reset
держать 10 секунд
отпустить
```

Reset нельзя удерживать до подачи питания — это ранний BootROM `Press x`, отдельный recovery path.

WebFailsafe предоставляет `/flashing.html`. Ursus может отправлять ITB встроенным uploader'ом:

```text
HTTP/1.0
multipart/form-data
field = firmware
Content-Length = exact
Connection: close
no chunked
no Expect: 100-continue
```

## 6. Как tcboot принимает sysupgrade

Upload handler фиксирует исходные `$filesize/$fileaddr` в собственных переменных, потому что последующие UBI commands могут менять глобальный `$filesize`.

```text
setenv us $filesize
setenv ua $fileaddr
```

Это исправляет аппаратно найденный класс ошибки, при котором `ubi read` calibration volume менял `$filesize`, а `fit` создавался ошибочно размером 256 KiB.

FIT gate проверяет:

- upload size в допустимом диапазоне;
- `iminfo` и FIT hashes;
- `/configurations/default`;
- профиль `OpenWrt nokia_xg-040g-md-ubi`;
- наличие kernel/FDT/loadables references.

## 7. Первая миграция stock UBI

Если начало UBI ещё не содержит UBI magic, tcboot работает в migration mode:

1. читает stock BOSA и RI raw MTD reads до erase;
2. только после обоих успешных reads выполняет `mtd erase ubi`;
3. attach UBI;
4. создаёт `ubootenv`, `ubootenv2`, `bosa`, `ri`, `fip`;
5. восстанавливает BOSA/RI и делает UBI readback + `cmp.b`;
6. создаёт `fit` и `rootfs_data`.

Erase не продолжится при failed calibration read: chain fail-closed.

## 8. Повторный Web sysupgrade и почему tcboot выживает

Когда UBI уже существует, handler обнаруживает UBI magic и переходит в update path:

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

**Ни `mtd erase` первых 1 MiB, ни запись mtd0 в этом path не выполняются.** Поэтому tcboot и его environment физически остаются на месте.

Аппаратно подтверждено повторным Web sysupgrade после уже загруженного OpenWrt: новый OpenWrt устанавливается, tcboot остаётся загрузчиком, и WebFailsafe снова доступен через Reset 10 секунд.

Это и есть основное эксплуатационное преимущество схемы: если production OpenWrt повреждён или новая версия не работает, recovery UI не зависит от Linux rootfs.

### Важное ограничение

Текущий update path удаляет и пересоздаёт `rootfs_data`. Поэтому tcboot WebFailsafe sysupgrade сейчас является **recovery-style reinstall**, а не OpenWrt upgrade с сохранением overlay/configuration.

## 9. Почему `fip` volume существует, но tcboot не зависит от него

OpenWrt upstream layout предусматривает OpenWrt FIP/U-Boot. В Ursus boot chain текущий `fip` UBI volume оставлен как layout-compatible placeholder, но production boot идёт напрямую из tcboot в UBI `fit`.

```text
tcboot -> UBI fit -> FIT hashes -> kernel/FDT/rootfs -> runtime FDT fixup -> Linux
```

То есть OpenWrt FIP не является условием загрузки в текущей MD architecture.

## 10. Safety invariants

До записи tcboot обязательны:

- model `Nokia XG-040G-MD`;
- SoC `Airoha AN7581`;
- доказанный UID0;
- `/dev/mtd0` geometry 0x80000 / erase 0x20000 / writesize 2048;
- exact personalized tcboot size 524288 + SHA256;
- write only `/dev/mtd0`;
- полный 0x80000 readback + byte compare;
- FIT/FDT compatibility gate до destructive path.

Unknown state означает stop, а не guess.

## 11. HW-verified state на fix10

Exact tcboot patch8 bytes:

```text
data/payloads/md/tcboot/tcboot-MD-direct-sysupgrade-patch8-FDTAWARE-BEAR-WRITE.bin
size   524288
SHA256 7c202a9c35dfcc10b85a1ad7f3d8cf34dbabfcb23287f26d9b5376f582772766
```

Подтверждены:

```text
tcboot NAND boot
WebFailsafe + bear branding
Reset 10 s entry
FIT upload
first UBI migration
full FIT readback
FDT-aware boot
Linux/UBI/UBIFS/procd
repeat tcboot Web sysupgrade
tcboot persistence after sysupgrade
```

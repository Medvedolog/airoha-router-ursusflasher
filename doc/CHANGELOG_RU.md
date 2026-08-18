# CHANGELOG

## 0.1.0-md-lab1fix10 — 2026-08-18

- Очищен release-root: оставлены один короткий `README.md`, launchers, version/checksums и runtime-каталоги.
- `README_RU.md` / `README_EN.md` перенесены и переработаны в `doc/INSTRUCTIONS_RU.md` / `doc/INSTRUCTIONS_EN.md`.
- Исторические patch notes перенесены в `doc/history/`; каталог `docs/` переименован в `doc/`.
- `doc/ARCHITECTURE_RU.md` и `doc/ARCHITECTURE_EN.md` полностью переписаны как каноническое описание архитектуры и tcboot know-how.
- Exact patch8 bear WebFailsafe bytes повышены до статуса HW VERIFIED.
- HW VERIFIED: повторный tcboot Web sysupgrade после уже загруженного OpenWrt сохраняет tcboot и WebFailsafe.
- Зафиксирована семантика текущего update path: `fit` и `rootfs_data` пересоздаются; tcboot сохраняется, overlay/configuration не сохраняется.
- Инструкция Reset остаётся аппаратно зафиксированной: power ON -> сразу Reset -> держать 10 секунд -> отпустить.

## 0.1.0-md-lab1fix9 — 2026-08-18

- Patch7 FDT-AWARE аппаратно подтверждён end-to-end до OpenWrt: `reg=<0x00100000 0x0ff00000>`, Linux 6.18.44, корректный UBI attach, UBIFS `rootfs_data`, overlay и `procd` console.
- Вход в tcboot WebFailsafe стандартизирован по аппаратному тесту: power ON -> сразу нажать Reset -> держать **10 секунд** -> отпустить.
- Patch8 сохраняет HW-verified FDT/UBI/boot core и меняет только tcboot Web branding: `🐻 OPENWRT`, `🐻 UPDATING`, `🐻 UrsusFlasher WebFailsafe`, marker `UrsusITB FDT p8`.
- Default patch8 SHA256: `7c202a9c35dfcc10b85a1ad7f3d8cf34dbabfcb23287f26d9b5376f582772766`.
- Exact patch8 bytes: static/rebuild QA PASS; короткий HW Web regression pending.

## 0.1.0-md-lab1fix8 — 2026-08-18

- Hardware patch6 дошёл до `Starting kernel`, Linux 6.18.44 и `Machine model: Nokia XG-040G-MD (UBI)`; отказ локализован в malformed runtime `ubi reg`, созданном старым raw-memory `cp.b`.
- Добавлен stdlib FIT/FDT preflight: `/configurations/default`, динамические kernel/FDT/loadables names, проверка image hashes, рекурсивный поиск ровно одного `label=ubi`, decode `#address-cells/#size-cells` и geometry gate.
- Удалены hardcoded working-FDT RAM address и `cp.b`; patch7 использует `fdt set $up reg <generated cells>` и `fdt print $up reg`.
- tcboot теперь детерминированно персонализируется под фактический UBI node path выбранного sysupgrade до NAND-write; router-side SHA и полный mtd0 byte readback используют фактический generated tcboot.
- Добавлен выбор `.itb`; точный hardware-tested sysupgrade размером 10 518 808 байт помещён в `fw/` как default.
- Добавлен встроенный tcboot HTTP/1.0 multipart uploader с полем `firmware`, точным Content-Length, без chunked/Expect.
- tcboot FIT gate больше не прибит к `config-1/kernel-1/fdt-1/rootfs-1`; profile description остаётся model safety gate.
- Status: `PATCH7_FDTAWARE_LAB_WRITE_NOT_YET_HW_VERIFIED`.

## 0.1.0-md-lab1fix7 — 2026-08-18

- Patch5 hardware run подтвердил полный FIT write/readback: `fit` = 10 518 808 bytes, hashes kernel/FDT/rootfs проходят после reboot.
- Отказ локализован после `bootm fdt`: FDT relocated, затем `subcommand failed (err=-1)`.
- Patch6 BOOTFIX сохраняет tcboot/WebFailsafe и удаляет отдельные `bootm cmdline` и `bootm bdt`.
- ARM64 boot chain теперь `start -> loados -> ramdisk -> fdt -> runtime UBI-reg patch -> prep -> go`.
- Добавлены UART markers начала/успеха каждой bootm стадии и `U:KERNEL_GO`.
- tcboot остаётся постоянным recovery loader для повторной установки OpenWrt через WebFailsafe.
- Patch6 status: `LAB_WRITE_BOOTFIX`; следующий HW gate — `Starting kernel` + Linux boot + Reset WebFailsafe после power-cycle.

## 0.1.0-md-lab1fix6 — 2026-08-18

- Исправлен destructive confirmation race: перед prompt очищается накопленный консольный ввод.
- Пустой Enter больше не отменяет операцию и никогда не разрешает NAND write.
- Отмена destructive шага только явная: `0`, `CANCEL` или `ОТМЕНА`.
- Неверная фраза подтверждения повторно запрашивается; до точного подтверждения NAND не изменяется.
- tcboot payload остаётся patch5 без изменений.


## 0.1.0-md-lab1fix5 — 2026-08-18

- Аппаратный patch4 дошёл до полного UBI migration, volume creation, environment save и reset, но создал `fit` размером только 256 KiB: промежуточный `ubi read ... ri 0x40000` изменил глобальный U-Boot `$filesize`. После reset FIT header читался, но kernel hash падал.
- Patch5 сохраняет размер и адрес HTTP upload сразу как `us`/`ua` и использует только эти pinned значения для `ubi create fit`, `ubi write`, полного readback и `cmp.b`.
- Исправлено сохранение stock `bosa`/`ri`: отсутствующий в tcboot `flash read` заменён на raw `mtd read ubi` по относительным offset `0x50c0000` и `0x5100000` до `mtd erase ubi`.
- CAL_SAVE теперь fail-closed: erase не начинается, если оба calibration dump не прочитаны успешно.
- Patch5 остаётся `LAB_WRITE` до нового аппаратного прогона stock → tcboot → full sysupgrade → OpenWrt → power-cycle → Reset Web recovery.


## 0.1.0-md-lab1fix4 — 2026-08-18

- Исправлен первый HW direct-sysupgrade failure: удалена негативная boundary-проверка `mtd read ubi ... 0xff00000`, которая намеренно возвращала `-22` и тем самым останавливала HTTP upgrade до `mtd erase ubi`.
- Состояние UBI теперь определяется без ожидаемых ошибок: успешное чтение offset 0 + UBI magic; при magic attach обязан пройти, без magic выполняется stock→UBI migration.
- UART trace расширен маркерами `U:UBI_PROBE_BEGIN`, `U:UBI_EXISTING_MAGIC`, `U:UBI_ATTACH_BEGIN/OK`, `U:ERROR_*`; форматирование имеет явные BEGIN/DONE.
- Первый неудачный HW upload подтверждён как pre-erase failure: UBI не форматировался.
- Сохранены ручной MD power-cycle + Reset 10 s prompt, HTTP/1.0 tcboot detection, stdlib-only runtime и expert backup policy.


## 0.1.0-md-lab1fix2 — 2026-08-18

- Добавлен expert backup policy: чужой/непривязанный backup, ручные дампы MTD или работа без backup по явной ответственности оператора.
- Safe path сохранён: новый STOCKSET или существующий Ursus/MedveFlasher STOCKSET с restore-validator + DEVICE_MAC match.
- Исправлен MD tcboot readback: используется `/dev/mtd0`, а не `/dev/mtd0ro`.
- После tcboot write выполняется полный `mtd_debug read` и побайтный `cmp`; лишний readback SHA удалён.
- Повторный pre-write SHA live `mtd0` остаётся удалённым.

## 0.1.0-md-lab1fix1 — 2026-08-18

- Удалён ошибочный pre-write SHA текущего `mtd0` против STOCKSET, остановивший первый hardware run с `router=missing`.
- Live destructive gate оставлен геометрическим; content proof выполняется после write полным readback tcboot.
- Readback переведён на проверенный stock `mtd_debug read /dev/mtd0ro`, затем один SHA256 compare.
- В `Install OpenWrt` добавлен подвариант использования существующего STOCKSET без повторного TFTP backup.
- Существующий backup полностью revalidate-ится через `verify_stock_restore_backup()` и обязательно сверяется с текущей Nokia по `DEVICE_MAC.txt`.
- Главное beginner-меню остаётся трёхпунктовым.

## 0.1.0-md-lab1 — 2026-08-18

- Создан первый независимый UrsusFlasher MD LAB runtime.
- Первый экран: выбор Русский / English.
- Основное меню приведено к 3 beginner actions.
- Перенесён stock Web AES/RSA/login backend MedveFlasher.
- Перенесены проверенные Telnet login, UID0 discovery и FTP provisioning semantics.
- Перенесён hardware-tested TFTP STOCKSET `mtd0..mtd16` с retries/completion markers/validator.
- Добавлена pinned tcboot patch1 запись только в `mtd0` с live geometry gate и полным readback SHA256.
- Добавлено обнаружение tcboot `/flashing.html` после reboot.
- Direct sysupgrade patch1 включён в release, но не запускается автоматически в первом gate.
- UFNAND1 отложен и не блокирует LAB1; обязательный backup gate — STOCKSET.
- Удалена обязательная runtime-зависимость MedveFlasher от vendored Rich; Ursus LAB1 импортируется только на stdlib.
- Добавлены offline TFTP PUT/GET selftests и stock Web crypto/parser selftest.
## 0.1.0-md-lab1fix3 — 2026-08-18

- Hardware finding: tcboot mtd0 write/readback passed; MD WebFailsafe requires power-cycle and Reset immediately after power-on for 10 s.
- Removed automatic post-write software reboot expectation; wizard now prompts the proven hardware gesture.
- tcboot detection now uses a minimal HTTP/1.0 socket probe for `/flashing.html` plus a 404 control route.
- Added ANSI UI: dim-gray timestamps, colored menu choices and OK/ERROR/WARNING/INFO/WAIT classes, no third-party libraries.
- Added patch3 TRACE UART stage markers for FIT validation, UBI format begin/end, volume creation, calibration restore, FIT write/readback, environment save and reset.
- Current patched Web firmware route explicitly does not claim stock Nokia restore support; stock restore remains UART/BootROM recovery.

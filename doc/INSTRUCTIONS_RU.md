# UrsusFlasher 0.1.0-md-lab1fix10 — инструкция

## Назначение

UrsusFlasher устанавливает OpenWrt на Nokia XG-040G-MD / Airoha AN7581 и оставляет tcboot постоянным recovery-loader. Runtime использует только Python 3 standard library; `pip` и runtime-зависимость от MedveFlasher не требуются.

## Запуск

Windows:

```text
START.cmd
```

Linux:

```text
./START.sh
```

Первый экран всегда предлагает язык, затем beginner menu.

## Комплектный OpenWrt sysupgrade

По умолчанию используется:

```text
fw/openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb
size   10518808
SHA256 b0556660c1939a9dc1ebbce5b4a3b3c8318c76eacae04de53ce047b43af8d867
```

Можно указать другой `.itb`. До любых destructive действий Ursus разбирает FIT/FDT, читает `/configurations/default`, проверяет image hashes, находит UBI partition по `label="ubi"`, читает `#address-cells/#size-cells` и фактический `reg`. Неожиданная структура блокируется fail-closed.

Официальный ITB на ПК не переписывается. tcboot меняет только working FDT в RAM перед запуском ядра.

## Backup policy

```text
1. Рекомендуется: снять новый STOCKSET и продолжить
2. Использовать ранее снятый РОДНОЙ Ursus/MedveFlasher STOCKSET
3. ЭКСПЕРТ: продолжить с чужим/непривязанным backup
4. ЭКСПЕРТ: продолжить с ручными дампами разделов MTD
5. ЭКСПЕРТ: продолжить БЕЗ backup
0. Назад
```

Safe path 1–2 требует валидный restore-validator и binding текущего устройства. Expert override не отключает model/SoC gate, UID0, mtd0 geometry, tcboot SHA/readback и FIT/FDT validation.

## Запись tcboot

Перед destructive write требуется точная фраза:

```text
FLASH TCBOOT MD
```

До marker `__URSUS_ERASE_BEGIN__` NAND не стирается. После записи выполняется полный readback `/dev/mtd0` 0x80000 и byte-for-byte compare.

## Вход в tcboot WebFailsafe — HW VERIFIED

Для Web recovery на MD используется только эта последовательность:

```text
1. Выключить питание Nokia.
2. Включить питание.
3. СРАЗУ после включения нажать Reset.
4. Держать Reset 10 секунд.
5. Отпустить Reset.
6. Открыть http://192.168.1.1/.
```

**Не держать Reset до подачи питания.** Это другой путь — ранний Airoha BootROM `Press x`.

## Установка/обновление OpenWrt через tcboot

После обнаружения WebFailsafe мастер может сам отправить выбранный ITB на `/flashing.html` через HTTP/1.0 multipart uploader.

На стороне tcboot:

1. проверяется FIT и профиль Nokia XG-040G-MD UBI;
2. при первой миграции сохраняются stock calibration BOSA/RI, форматируется только UBI region и создаются core UBI volumes;
3. при уже существующей Ursus UBI-разметке tcboot проверяет core volumes и не трогает mtd0/tcboot;
4. старые `fit` и `rootfs_data` удаляются;
5. новый `fit` создаётся по точному upload size, записывается и полностью считывается обратно с `cmp.b`;
6. `rootfs_data` создаётся заново;
7. bootcmd сохраняется и устройство перезагружается.

Важно: текущий WebFailsafe update является **recovery-style reinstall**. tcboot переживает sysupgrade, но `rootfs_data` намеренно пересоздаётся, поэтому это не config-preserving OpenWrt sysupgrade.

## Подтверждённый статус MD

На реальном XG-040G-MD подтверждено:

- tcboot mtd0 write + полный readback;
- WebFailsafe по `power ON -> сразу Reset -> 10 секунд`;
- upload официального OpenWrt UBI sysupgrade;
- full FIT write/readback;
- runtime FDT fixup UBI partition;
- Linux 6.18.44 boot;
- UBI attach, UBIFS `rootfs_data`, overlay и `procd`;
- повторный tcboot Web sysupgrade после уже установленного OpenWrt;
- tcboot остаётся в NAND и WebFailsafe остаётся доступен после sysupgrade.

## Разметка

```text
0x00000000..0x0007ffff  tcboot
0x00080000..0x000fffff  tcboot environment
0x00100000..0x0fffffff  UBI / OpenWrt
```

Именно физическое разделение первых 1 MiB и UBI обеспечивает persistence tcboot при Web sysupgrade.

Подробности реализации: `doc/ARCHITECTURE_RU.md`.

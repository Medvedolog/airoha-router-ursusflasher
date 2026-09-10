# UrsusFlasher 0.2.62 TEST — Nokia XG-040G-MD + XG-040G-MF

Hardware-test комплект для:

```text
Nokia XG-040G-MD -> Airoha AN7581 -> UrsusBoot-MD TEST61
Nokia XG-040G-MF -> Airoha AN7583 -> UrsusBoot-MF TEST61
```

Python 3.12+; сторонние Python-пакеты не требуются. Это тестовый комплект, не release: `main`, tag и GitHub Release автоматически не изменяются.

## Запуск

Windows:

```text
START_ONECLICK.cmd
START_EXPERT.cmd
START_UART_RESTORE.cmd
```

Linux/macOS:

```text
./START_ONECLICK.sh
./START_EXPERT.sh
./START_UART_RESTORE.sh
```

## 0.2.62

- ONE-CLICK и EXPERT определяют MD/MF по model/SoC и выбирают board-specific path.
- MD остаётся frozen `0.1.0-alpha5-UBIUX1-TEST61`; CI пересобирает FIP и сравнивает его byte-for-byte с эталоном.
- MF persistent runtime основан на TEST61, использует `bootcmd=ursusdispatch` и persistent redundant UBI environment.
- MF bootloader устанавливается device-derived способом: читается фактический FIP/boot-area конкретного устройства, сохраняются native ранние FIP entries и factory environment, заменяется NT_FW/BL33, затем выполняется полный readback.
- MF RAM Recovery остаётся отдельным BootROM/UART образом.
- MF LAN2/LAN3/LAN4 используют аппаратно проверенный HWTEST8 native Clause-45 LED path.
- Factory identity для MF читается из RI; runtime `eth0` MAC не считается factory MAC.
- Перед destructive write остаётся одно обычное `y/N`. EXPERT позволяет пропустить полный restore-grade backup; локальная копия изменяемого boot-object и readback остаются обязательными.
- После начала записи автоматического fallback на другой writer нет.

## Canonical OpenWrt firmware

`fw/` содержит ровно восемь актуальных UnameOne images: четыре для MD и четыре для MF. Старый MF production sysupgrade из MedveFlasher больше не подменяет firmware во время CI.

MD / AN7581:

```text
openwrt-airoha-an7581-nokia_xg-040g-md-squashfs-sysupgrade.bin
openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb
openwrt-airoha-an7581-nokia_xg-040g-md-initramfs-uImage.itb
openwrt-airoha-an7581-nokia_xg-040g-md-ubi-initramfs-recovery.itb
```

MF / AN7583:

```text
openwrt-airoha-an7583-nokia_xg-040g-mf-squashfs-sysupgrade.bin
openwrt-airoha-an7583-nokia_xg-040g-mf-ubi-squashfs-sysupgrade.itb
openwrt-airoha-an7583-nokia_xg-040g-mf-initramfs-uImage.itb
openwrt-airoha-an7583-nokia_xg-040g-mf-ubi-initramfs-recovery.itb
```

ONE-CLICK uses the matching `*-ubi-squashfs-sysupgrade.itb` for the normal STOCK/Factory -> UBI transition. The non-UBI sysupgrade remains available for factory-layout OpenWrt operations. Initramfs images are included for recovery/manual use.

Authoritative size/SHA256 values are in `data/FIRMWARE_BUNDLES.json` and every package file is covered by root `SHA256SUMS`.

## ONE-CLICK MF path

```text
Nokia STOCK / installed OpenWrt
        -> prove XG-040G-MF / AN7583
        -> validate board-specific payload and firmware
        -> build device-derived UrsusBoot candidate
        -> one y/N
        -> one selected writer
        -> full readback
        -> reboot + Reset -> UrsusBoot Recovery
        -> verify MF identity again
        -> install canonical UnameOne UBI sysupgrade
        -> board-specific BL2/preloader committed last where migration requires it
        -> operation complete
        -> reboot OpenWrt
```

## Payload cleanup

The test ZIP does not carry historical HWFIX/UIFIX/TEST57-TEST60 engineering payloads, build-only donors, source-only helper files, developer selftests, or duplicate large recovery-source payloads. It contains only runtime payloads required by MD/MF ONE-CLICK, EXPERT and UART recovery. Pinned transition/recovery resources remain under `data/` because the proven backend uses them directly.

## Recovery

MF Recovery keeps two separate concepts:

1. current UrsusBoot-MF TEST61 RAM Recovery for diagnostics/debrick;
2. pinned BootROM/XMODEM rescue baseline used by the host backend.

Reset held before power-on enters Airoha BootROM. Normal UrsusBoot Recovery is requested after ordinary boot/reboot by holding Reset through the configured red LED sequence.

## Integrity

```text
SHA256SUMS
PAYLOAD_SHA256SUMS.txt
VERSION
```

CI verifies frozen MD TEST61, MF RAM Recovery, MF persistent runtime, canonical eight-file UnameOne firmware set, pinned transition/recovery resources, host Python compilation, package payload allowlist and final ZIP contents.

# Первый HW gate

Обязательно записать полный UART 115200 8N1.

До Web upload подтвердить:

```text
tcboot banner
SPI-NAND SkyHigh ML02G300WHI00
256 MiB / erase 128 KiB / page 2048
eth0
httpd 192.168.1.1
UrsusITB WRITE patch1 marker
```

Во время upload зафиксировать весь вывод начиная с `Ursus MD direct sysupgrade WRITE`.

После reboot нужны:

```text
UrsusITB boot
Read ... from volume fit
iminfo hashes OK
bootm start/loados/ramdisk/fdt
successful fdt get/cp fixup (absence of command error)
bootm prep/go
Linux Machine model: Nokia XG-040G-MD (UBI)
/proc/mtd: UBI physical span starts at 0x100000 equivalent
ubi0 volumes 0..6
rootfs_data mounts
LAN link
```

При первой ошибке не выполнять второй destructive experiment вслепую; сохранить UART log и точную стадию.

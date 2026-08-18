# tcboot patch8 BEAR UI

Patch8 — минимальный branding regression поверх HW-verified patch7 FDT-AWARE core. Destructive FIT/UBI logic, calibration handling, dynamic FDT path и bootm state machine не менялись.

Изменения WebFailsafe:

```text
🐻 OPENWRT
🐻 UPDATING
🐻 UrsusFlasher WebFailsafe
UrsusITB FDT p8
```

Default binary:

```text
data/payloads/md/tcboot/tcboot-MD-direct-sysupgrade-patch8-FDTAWARE-BEAR-WRITE.bin
size   524288
SHA256 7c202a9c35dfcc10b85a1ad7f3d8cf34dbabfcb23287f26d9b5376f582772766
```

Статус exact patch8 bytes: STATIC/REBUILD QA PASS, короткий HW Web regression pending. Базовый patch7 boot/rootfs path уже HW VERIFIED.

Recovery entry: power ON -> сразу нажать Reset -> держать 10 секунд -> отпустить. HW VERIFIED.

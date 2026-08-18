# tcboot patch8 BEAR UI

Patch8 is a minimal branding regression over the HW-verified patch7 FDT-AWARE core. Destructive FIT/UBI logic, calibration handling, dynamic FDT path, and bootm state machine are unchanged.

WebFailsafe changes:

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

Exact patch8 bytes status: STATIC/REBUILD QA PASS, short HW Web regression pending. The underlying patch7 boot/rootfs path is already HW VERIFIED.

Recovery entry: power ON -> immediately press Reset -> hold for 10 seconds -> release. HW VERIFIED.

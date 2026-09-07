# OpenWrt payload 06.09.2026 — provenance

Production firmware in `fw/` is the UnameOne build supplied on 06.09.2026.

```text
OpenWrt revision  r36009+75-6c315233aa
kernel            6.18.44
vermagic          bed7e2dec73efb4c3050bc8a8373af30
```

Files:

```text
nokia_xg-040g-md-squashfs-sysupgrade.bin
SHA256 23ad06174184f71c9a845734571752f62930ba1cfac45f4ad8deadd9d8965820

nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb
SHA256 47ea7c6f1e22a4aae9482e653a4fc6e87524f7e27847aaaed7fb75349cae7f3d
```

The author's network default is retained: LAN4 becomes WAN.

The supplied reference initramfs were inspected but are not used to replace UrsusFlasher service/recovery payloads:

```text
ubi-initramfs-recovery.itb
SHA256 3ce8726e38f6dcdbdb6f25859e269ad32fe04201c5b57b064b11da7e469864fb

initramfs-uImage.itb
SHA256 6696c96ef824defc56163f9fe4f2846fd4ab61cdbc5679415939d658071dca63
```

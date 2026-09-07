# BootROM read-only backup payloads — Nokia XG-040G-MD

Runtime-only RAM recovery payloads used by EXPERT item 7 for an exact full-NAND backup.
They are loaded through Airoha BootROM/UART and TFTP into RAM; the backup path does not erase or write NAND.

Pinned payloads:

- `openwrt-airoha-an7581-nokia_xg-040g-md-ubi-bl31-uboot-ethfix.fip`
  - size: 308154 bytes
  - SHA256: `2ebcbf3981e3e56b6389521fc2caa3320cf259c08f173b660b29366b9290bcc1`
- `nokia-xg040gmd-stock-recovery-initramfs.itb`
  - size: 11285480 bytes
  - SHA256: `c40c87354566eb44fc933c1ce6c0cd9c81227b525243c67c9932b80a656d01c6`

The preloader is shared with `payloads/md/ursusboot/openwrt-airoha-an7581-nokia_xg-040g-md-ubi-preloader.bin` and is verified separately.

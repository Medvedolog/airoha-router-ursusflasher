- `ursusboot-md-0.1.0-alpha4-UIFIX1-update.fip` — current production target, HWFIX3 baseline with Web NAND label `BadBlocks`; SHA256 `a6d1977eed9eb08bb9960b6621322fdd20babe07fb36fdb178b61dedc09a8ad4`, CRC32 `470b3b69`.
- `ursusboot-md-0.1.0-alpha4-UIFIX1-u-boot.bin` — raw BL33, SHA256 `921d53f396bec54613c792e6a31388e5a12a481fdcf963875dda2fad86499a67`.
- `ursusboot-md-0.1.0-alpha4-UIFIX1-u-boot.lzma` — LZMA1EXT/no-EOPM BL33, SHA256 `380464993b5c326282c0ee6f2efd8c1d16a516f76f999e3169ad1ac7b5f16df6`.
## HWFIX3 payload set used by 0.2.40 accept3

- `ursusboot-md-0.1.0-alpha4-HWFIX3-update.fip` — HWFIX3 active-FIP candidate, SHA256 `e8809b69712b5c3e57d3230a9bcd86048f1e02a58106229c06a7be45a35b97a7`, CRC32 `86fdebcc`.
- `ursusboot-md-0.1.0-alpha4-HWFIX3-u-boot.bin` — raw BL33, SHA256 `fe150f81b98a9ad02dbba6764722383652d5982056c429faad4c427ef8373548`.
- `ursusboot-md-0.1.0-alpha4-HWFIX3-u-boot.lzma` — LZMA1EXT/no-EOPM BL33, SHA256 `682a4a4a8e02325da626605b4b91deba19b094fd714387d30549657ce6b68f79`.
- Install baseline: active `fip` hardware-proven HWFIX2 `1917ed23`; rollback returns only active `fip` to HWFIX2. Exact alpha3 BL2 `9f7bf316` and `fip.old` `82263464` are not written.

# UrsusBoot payloads — MD / AN7581

Emergency baseline is exact hardware-working UrsusBoot 0.1.0-alpha3; ordinary production and direct-stock ONE-CLICK target is HWFIX3.

- `ursusboot-md-0.1.0-alpha3-update.fip` — persistent FIP, SHA256 `597071e178470bfda23aab9738ad7ddb0b25e9b21ef336fd3eceb39c39f983ce`.
- `ursusboot-md-0.1.0-alpha3-ram-installer.fip` — exact alpha3 RAM installer for Airoha BootROM/XMODEM, SHA256 `dc08ed0be1b1d68f6bc247ae45293e6ab0ca9df7695541b664e4060a145228c8`.
- `openwrt-airoha-an7581-nokia_xg-040g-md-ubi-preloader.bin` — exact alpha3 UBI/BL2 preloader, SHA256 `6c3b2339d036340396730a13adfe35c0d2a4dddedeffb6f9965a24e0c7908808`.
- `ursusboot-md-0.1.0-alpha3-bl2.bin` — canonical 128-KiB BL2 image: `0xff[0x800] + preloader + 0xff padding`, SHA256 `6f9c928bad500de0339bbfdfa354c17a7ac044f96c913f3a01301971d6cd659d`.
- `ursusboot-md-0.1.0-alpha3-u-boot.bin` / `.lzma` — engineering references for production BL33 validation.

Legacy fixed-ID4 full recovery remains blocked on layouts where ID4 is occupied by another volume. Read-only BootROM diagnostics and the proven alpha3 RAM installer remain the recovery foundation; the HWFIX1/HWFIX2 tests do not create, remove or rename UBI volumes and do not write BL2.

## alpha4 hardware-proven rollback baseline

The three `alpha4-lzmafix1-*` files are now the **hardware-proven alpha4 rollback baseline**. With exact alpha3 BL2 (`SHA256 6f9c928b...`, `CRC32 9f7bf316`) this FIP reached BL31, U-Boot alpha4, verified FIT and started Linux. ONE-CLICK writes HWFIX3 directly from stock. Exact alpha3 is retained only for the hardware-proven BootROM emergency lineage and is not an ordinary ONE-CLICK intermediate.


## 0.2.36 alpha4-HWFIX2 test payloads

- `ursusboot-md-0.1.0-alpha4-HWFIX2-update.fip` — HWFIX2 active-FIP candidate, SHA256 `f164ff4ac0f272550151c4f0d89cd154bd7b0d6eb9165c44c469caec9fc0138f`, CRC32 `1917ed23`.
- `ursusboot-md-0.1.0-alpha4-HWFIX2-u-boot.bin` — raw BL33, SHA256 `0162039ee8ed06c41f2aa8c1462c7e551f043ff0e6a7080fde3f12fccafab96d`.
- `ursusboot-md-0.1.0-alpha4-HWFIX2-u-boot.lzma` — LZMA1EXT/no-EOPM BL33, SHA256 `f25f0d3f25a324ab50f20bb4b3991021018d59fb8be314ee3a07360116a57454`.
- Install baseline: active `fip` HWFIX1 `dd0843dd`; rollback returns only active `fip` to HWFIX1. Exact alpha3 BL2 `9f7bf316` and `fip.old` `82263464` are not written.

## 0.2.35 alpha4-HWFIX1 test payloads

- `ursusboot-md-0.1.0-alpha4-HWFIX1-update.fip` — HWFIX1 active-FIP candidate, SHA256 `f07245f705227e981260984a63572f9ddee7bc0a8f482c353e2e278ff2bfb04f`, CRC32 `dd0843dd`.
- `ursusboot-md-0.1.0-alpha4-HWFIX1-u-boot.bin` — raw BL33, SHA256 `947e44618a19f6c4d0e2c3b1148500c294a5a472a3c58e68ffbc2abc3237a038`.
- `ursusboot-md-0.1.0-alpha4-HWFIX1-u-boot.lzma` — Airoha LZMA1EXT/no-EOPM NT_FW, SHA256 `46c8cfc3e1d7a0070a1a9266f2389c7bd9f21ee9fe87dc96b55bab49ae57648b`.
- `ursusboot-md-0.1.0-alpha4-HWFIX1-BUILD_INFO.txt` — build/policy provenance.

EXPERT item 13 requires `fip.old=82263464`, active `fip=b1b313a5`, BL2=`9f7bf316` and changes only active `fip`. Item 14 restores only active `fip` to `b1b313a5`. There is one ordinary `[y/N]` next to the actual write and no codeword.

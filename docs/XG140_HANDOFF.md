# XG-140G-MD development handoff

**Updated:** 2026-09-14  
**Repository:** `Medvedolog/airoha-router-ursusflasher`  
**Branch:** `feature/xg140-ursusboot-ram-recovery`  
**Baseline before this documentation update:** `4fb0dc93a044e1b87d92ad0f80f545ffdcfa9bce`  
**Status:** CI PASS / persistent hardware write pending

This file is the working engineering handoff for the XG-140G-MD port. It does not change the production MD/MF contract on `main`.

---

## 1. Device confirmed on hardware

```text
Model family        Nokia/Bell XG-140G-MD
Board ID            XG140GMC2P5G
SoC                 Airoha AN7581DT
DRAM                512 MiB DDR4-2666
SPI-NAND            SkyHigh S35ML02G3, 256 MiB
Erase/page/OOB      128 KiB / 2048 B / 128 B
Stock tcboot        Sep 07 2024 - 11:26:37
```

The board has an RJ11/voice section with a populated MaxLinear device. Exact SLIC identity is still TBD.

Device-unique serial, GPON, MAC and recovered plaintext credentials are deliberately not stored in this public handoff.

---

## 2. Why recovery is currently required

An XG-040G-MD image was accidentally written to the physical XG140. Early boot remains alive, but stock slot payload validation fails.

Observed tcboot failures include:

```text
FDT_MAGIC or IH_MAGIC check fail. Parse main image fail.
verify kernel:0xc0000 error
Verify image fail
Bad FIT kernel image format
```

DRAM training, NAND detection and tcboot remain functional. UART plus Airoha BootROM `CCCC` recovery is available.

Do not ask tcboot to boot an ordinary OpenWrt sysupgrade image.

---

## 3. Stock layout

```text
bootloader   0x00000000..0x00080000
romfile      0x00080000..0x000c0000
nsb_master   0x000c0000..0x02940000
nsb_slave    0x02940000..0x051c0000
bosa         0x051c0000..0x05200000
ri           0x05200000..0x05240000
flag         0x05240000..0x05280000
flagback     0x05280000..0x052c0000
config       0x052c0000..0x05cc0000
data         0x05cc0000..0x0dda0000
oopsfs       0x0dda0000..0x0e1a0000
log          0x0e1a0000..0x0eba0000
```

OpenWrt split of the physical bootloader area:

```text
mtd0 bootloader 0x80000
mtd1 u-boot     0x7c000
mtd2 u-boot-env 0x02000
```

---

## 4. Backup status

A complete restore-grade XG140 backup was already captured before the current native persistent work. It includes partition dumps, `/proc/mtd`, board information, dmesg, checksums and UART log.

The backup itself is intentionally not committed to the public repository.

Important bootloader forensic facts from the native backup:

```text
mtd0 size                  0x80000
BootROM prefix             0x00000..0x007ff
prefix SHA256              82830140f4f8842702d0569065c27071b7cc24e0876e6c487cb4d9d81c294dd7
FIP physical offset        0x800
FIP magic                  010064aa78563412
stock env                  0x7c000..0x7ffff
stock env CRC              valid
TB_FW SHA256               07c9e1542a3de845055faa2244bbd07adc8c5a136811a61a0d678ec8fff5ee5e
NT_FW UUID                 d6d0eea7fcead54b97829934f234b6e4
```

The critical prefix/TB_FW lineage matches the proven direct-stock MD framework, but XG140 field installation now uses the unit's own native FIP as donor rather than an XG040 donor.

---

## 5. OpenWrt hardware checkpoint

RAM OpenWrt initramfs has successfully booted on the physical XG140.

Observed runtime:

```text
board_name     bell,xg-140g-md
target         airoha/an7581
Linux          6.18.36
```

Confirmed:

- EN8811H Ethernet works at MDIO `0x0f`, 2500base-x;
- USB xHCI works;
- NAND map is visible as expected;
- attaching the future OpenWrt UBI area fails while it still contains stock data, which is expected.

Pending:

- production stock MAC/factory identity extraction for OpenWrt;
- voice/SLIC driver/support;
- cpufreq deferred-probe cleanup.

Reuse the already built XG140 OpenWrt bundle unless source changes require a new build. Do not rebuild only to refresh timestamps.

---

## 6. Current UrsusBoot architecture

Target flow:

```text
stock tcboot
  -> UART/XMODEM one time
  -> XG140 UrsusBoot in RAM
  -> WebFailsafe
  -> build native-hybrid FIP on host from this unit's mtd0 backup
  -> STOCK bootloader updater
  -> full readback
  -> reboot
  -> persistent XG140 UrsusBoot
  -> WebFailsafe
  -> correct XG140 sysupgrade
```

RAM boot target:

```text
loadx 0x81e00000
go 0x81e00000
```

Current build identity:

```text
0.1.0-xg140-native1
```

`CONFIG_ENV_IS_NOWHERE=y`; no `saveenv` is part of the XG140 contract.

---

## 7. Native persistent implementation

Primary host helper:

```text
ursusflasher/src/xg140_native_persistent_install.py
```

It currently:

1. accepts `mtd0_bootloader.bin` or `.bin.gz`;
2. requires exact `0x80000` size;
3. validates BootROM prefix hash;
4. validates stock env CRC;
5. requires Airoha FIP at `0x800`;
6. requires exactly one native TB_FW and one NT_FW;
7. requires the proven TB_FW SHA256;
8. extracts the native XG140 FIP;
9. invokes the common `repack_persistent_fip.py` with XG140 `u-boot.lzma`;
10. requires all FIP entries except NT_FW/checksum to remain byte-for-byte identical;
11. requires the rebuilt FIP to end before protected env;
12. requires XG140 runtime identity from `/api/status` before write.

CI does not need or ship an XG-040 donor for the field FIP construction.

---

## 8. Current CI artifact

GitHub Actions run:

```text
run            34786299472
workflow       Build XG140 UrsusBoot Native Persistent Recovery
head           4fb0dc93a044e1b87d92ad0f80f545ffdcfa9bce
conclusion     success
artifact id    10327140405
artifact       ursusboot-xg140-native1-4fb0dc93a044e1b87d92ad0f80f545ffdcfa9bce
artifact size  3567807 bytes
artifact digest sha256:49a17e1de24ab55ac82547e2946a9ac2d45d84758a320e2371efd18a49d5de47
```

This proves build/package QA only. It is not persistent hardware acceptance.

---

## 9. Stock Web/Telnet reverse engineering

The current XG140 config database was analyzed deeply enough to identify the service bootstrap structure.

`confignew_encryption.cfg` contains compressed XML data model state. Secret values are encrypted and must remain local; do not put recovered plaintext credentials in Git, logs, diagnostics or command lines.

Relevant objects:

```text
TeleComAccount
  privileged Web account

ServiceManage
  TelnetEnable
  FactoryTelnetEnable
  TelnetUserName / TelnetPassword
  SSHUserName / SSHPassword
  SuPassword
  VtyshUserName / VtyshPassword
```

`system.cgi` static analysis:

```text
request: flag, au, ap
  -> compare au/ap with TeleComAccount (OID 59)
  -> load ServiceManage (OID 74)
  -> toggle FactoryTelnetEnable
```

The normal hidden page `/system.cgi?telnet` is also present.

A locally recovered `SuPassword` was independently checked against the active root entry in `/configs/etc/shadow`. This strongly supports a direct XG140 root path after Telnet, without forcing the XG040 FTP -> `user_ftp` procedure.

Planned stock bootstrap:

```text
privileged Web authentication
-> verified factory Telnet enable endpoint
-> TCP/23 proof
-> ordinary Telnet login
-> /etc/passwd UID0 enumeration
-> su candidate proof
-> id -u == 0
-> ROOT_READY
```

Factory reset is a fallback experiment, not the first action, because it can overwrite useful runtime config state.

---

## 10. A/B stock flags

The XG140 stock selector uses `flag` and `flagback`.

For a slave request while `curimg=0`, change only `active=1`. Do not manually mirror `flagback`; tcboot owns reconciliation.

Do not mix A/B flag experiments into the persistent UrsusBoot write transaction.

---

## 11. Mandatory blockers before first persistent write

### B1 — duplicate confirmation

Current helper asks:

```text
Write native-hybrid UrsusBoot to XG140 bootloader area? [y/N]
```

and then calls:

```python
uw.update_bootloader(..., confirm=True)
```

which asks a second `[y/N]`.

This violates the project operator contract. Fix to exactly one meaningful confirmation immediately before the destructive operation. Preferred options: keep the helper-level summary/confirmation and call `confirm=False`, or remove the helper prompt and let `update_bootloader()` own the single confirmation.

### B2 — device-side STOCK updater audit

Before field write, inspect `/api/update-ursusboot` implementation and prove there is no XG040-only board/hash allowlist that would reject or mis-handle the XG140 native-hybrid FIP.

Required result:

```text
preserve 0x0..0x7ff
write FIP from 0x800 only within allowed window
preserve 0x7c000..0x7ffff byte-for-byte
full readback before reboot
```

### B3 — sysupgrade gate

`xg140_ursusboot_web_recovery.py` must require persistent XG140 UrsusBoot identity/version before allowing firmware write. Generic `XG140 + STOCK layout` is not enough.

### B4 — stock-layout geometry

Prove XG140 sysupgrade writer uses XG140 geometry and does not inherit XG040-specific constants.

### B5 — UrsusBoot network hardware test

Linux has proven EN8811H/GDM4. Initial U-Boot XG140 DTS currently keeps GDM1 as the first recovery path. Verify physical WebFailsafe networking; if it fails, add XG140 EN8811H/GDM4 support before persistent testing.

---

## 12. First destructive hardware acceptance

Only after B1-B5:

```text
RAM UrsusBoot PASS
native donor PASS
native-hybrid lineage PASS
one y/N
persistent write
full mtd0 readback PASS
env unchanged PASS
reboot/power-cycle
persistent XG140 identity PASS
Web/API PASS
```

Then test final XG140 OpenWrt sysupgrade from persistent UrsusBoot.

UART and BootROM `CCCC` remain connected for the first acceptance run as recovery/observation, not as an excuse to bypass validation.

---

## 13. Repository rules for this branch

- Do not merge to `main` without explicit operator request.
- Do not create a tag/release from this branch without explicit request.
- Do not commit device backups or plaintext credentials.
- Do not introduce XG040 UBI preloader/BL2 into XG140.
- Do not change the protected stock environment as part of XG140 persistent install.
- Keep write-capable operations behind structural identity checks, one `[y/N]`, and readback.

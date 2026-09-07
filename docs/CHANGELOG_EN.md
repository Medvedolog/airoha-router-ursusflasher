# UrsusFlasher change log

This file lists released behavior only.

## 0.2.51 — STATEUI5

- Refined Russian operator terminology.
- Renamed the normal bootloader action to distinguish it from emergency recovery.
- Firmware payloads and writer backends are unchanged from 0.2.50.

## 0.2.50 — STATEUI4

- Added `PERSISTENT_ROOT`, `RAM_ROOT` and `UNKNOWN` execution-environment classification.
- Bootloader installation now reports the resolved Telnet/SSH method.

## 0.2.49 — PAYLOADREFRESH1

- Replaced the two production Nokia XG-040G-MD sysupgrade images with the UnameOne build dated 2026-09-06.
- Kept the existing service/recovery initramfs assets.
- Added the LAN2/LAN3 flashing recommendation and documented LAN4-as-WAN behavior.

## 0.2.48 — STATEUI3

- Machine values without a registered UI translation now fail closed.
- Added complete enum translation coverage tests.

## 0.2.47 — STATEUI2

- Made `probe_status` monotonic within one probe run.
- Routed DeviceState values and probe reasons through the UI translation layer.

## 0.2.46 — STATEUI1

- Added the common read-only `DeviceState`.
- Added full read-only flash backup and the durable host operation journal.
- Introduced the stable EXPERT 1–12 task menu.

## 0.2.45 — FUDAN1 / SSH1

- Added Fudan FM25G01B/FM25G02B support to UrsusBoot.
- Added persistent UrsusBoot installation from OpenWrt over root SSH.
- Added full readback verification for UBI FIP and raw boot-block writes.

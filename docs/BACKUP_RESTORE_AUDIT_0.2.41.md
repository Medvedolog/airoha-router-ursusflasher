# Backup/restore safety baseline

This file documents the safety properties used by the current backup validator.

## Full Nokia STOCK backup

A complete factory backup contains `mtd0..mtd16`, device metadata, sizes and integrity hashes. The restore validator checks the complete set before a stock-install path is allowed to treat the backup as recovery-grade input.

## Read-only capture

EXPERT item 7 must not modify NAND while creating a full copy. If an already-available Nokia read path cannot satisfy that requirement, the flasher uses the Airoha BootROM/RAM capture path.

## OpenWrt live state

A dump taken from a writable running OpenWrt system is not labelled as an exact full-restore image. Exact capture uses the quiescent BootROM/RAM path.

## Write verification

Bootloader and recovery writes require explicit target resolution and post-write readback. A failed readback does not trigger an automatic retry with another writer.

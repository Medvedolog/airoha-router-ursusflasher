# UrsusBoot / UrsusFlasher — ТЗ RU v5.42

## XG-140G-MD native FIP correction

Дата: 2026-09-14

Статус: обязательная корректировка v5.40 для Bell/Nokia XG-140G-MD (`XG140GMC2P5G`, AN7581DT).

v5.41 остаётся действующей для определения Vanilla. Настоящий документ изменяет только правила построения persistent native-hybrid FIP XG140.

## 1. Причина корректировки

Аппаратно снятый `mtd0_bootloader.bin` XG140 успешно проходит проверки размера boot area, native BootROM prefix, CRC stock env, FIP header, TB_FW UUID/SHA и NT_FW UUID, но native Nokia FIP не обязан содержать checksum entry UUID, применявшийся в другой FIP lineage.

Следовательно, правило v5.40 «NT_FW/checksum -> recalc checksum» было слишком сильным. Отсутствие такого checksum entry само по себе не является ошибкой native Nokia/Airoha FIP.

## 2. Главное правило

Persistent XG140 candidate строится только из FIP точного stock `mtd0` данного устройства.

Для checksum-free native Nokia lineage:

```text
exact device mtd0
  -> validate prefix/env/native FIP/TB_FW/NT_FW
  -> preserve every native non-NT_FW entry byte-for-byte
  -> preserve entry order, offsets, sizes and flags for every non-NT_FW entry
  -> replace only final NT_FW/BL33 payload and NT_FW size
  -> update only FIP terminator declared end
  -> do NOT synthesize foreign checksum metadata
  -> require final physical FIP end < stock env 0x7c000
```

## 3. Checksum policy

Checksum/integrity metadata is lineage-specific and optional unless its presence and semantics are proven for the concrete donor.

If the native donor does not contain a recognized checksum entry:

- absence is accepted;
- no checksum entry may be invented;
- no UUID from MD/MF/Routerich/other FIP lineage may be inserted;
- preservation proof is based on exact non-NT_FW byte identity plus structural FIP validation.

If a future XG140 donor contains a recognized checksum entry, the current checksum-free repacker must fail closed. Support for that donor requires a separate, proven lineage-specific validator/rebuilder; guessing checksum semantics is forbidden.

## 4. NT_FW placement gate

Current native repacker is allowed to operate only when NT_FW is the final payload in the FIP.

Reason: this permits BL33 growth without relocating any native TB/certificate/unknown payload.

If any native entry begins at or after NT_FW, the repacker must reject the donor. Relocation requires separate proof and is not part of this acceptance path.

## 5. Size and environment boundary

Known physical boundaries:

- FIP physical start: `0x800`;
- stock env start: `0x7c000`;
- stock env end: `0x80000`;
- boot area size: `0x80000`.

The rebuilt FIP end is aligned to `0x400` and must satisfy:

```text
0x800 + rebuilt_fip_size < 0x7c000
```

The stock env is not rebuilt and must remain byte-for-byte unchanged by the device-side writer.

## 6. Device-side write transaction

Host-side FIP construction does not authorize a write by itself.

Before the single operator `y/N`, preflight must show at minimum:

- confirmed XG140 UrsusBoot identity;
- donor `mtd0` validation PASS;
- native FIP TOC;
- TB_FW validation PASS;
- NT_FW final-payload gate PASS;
- rebuilt FIP boundary PASS;
- non-NT_FW lineage preservation PASS.

After the one `y/N`, the STOCK writer transaction remains:

```text
read/backup complete 0x80000 boot area
-> reconstruct candidate preserving live prefix + live stock env
-> erase boot area once
-> write complete 0x80000 candidate
-> full 0x80000 readback
-> exact comparison
-> report PASS
-> manual reboot only after PASS
```

No second confirmation is permitted inside the transport helper.

## 7. Failure policy

All failures before erase are `NOT_STARTED`: no persistent write occurred.

After erase begins, any failure must be reported as an indeterminate/potentially incomplete write state and must not be silently retried through another backend.

## 8. Acceptance status

Host-side checksum-free native repacker and its synthetic 9-entry regression test are software-implemented.

Persistent XG140 boot remains `PRE-HW-ACCEPTANCE` until the complete device-derived candidate is written/read back and cold-booted on XG140 hardware.

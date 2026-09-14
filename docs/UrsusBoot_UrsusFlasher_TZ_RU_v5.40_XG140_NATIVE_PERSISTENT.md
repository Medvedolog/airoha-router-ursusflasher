# UrsusBoot / UrsusFlasher — техническое задание
## Редакция 5.40 — XG-140G-MD native persistent recovery

**Дата редакции:** 2026-09-14  
**Целевое устройство:** Nokia/Bell XG-140G-MD  
**Board ID:** `XG140GMC2P5G`  
**SoC:** Airoha AN7581DT  
**Статус:** authoritative delta над v5.39 только для XG-140G-MD. Требования v5.38/v5.39 для XG-040G-MD/MF не изменяются.

---

## 1. Цель

Добавить отдельный, аппаратно проверяемый путь восстановления и установки OpenWrt на XG-140G-MD без переноса XG-040G-MD boot-chain assumptions туда, где они не доказаны.

Текущий целевой путь:

```text
stock tcboot жив, stock slots могут быть повреждены
  -> UART/XMODEM один раз
  -> XG140 UrsusBoot в RAM
  -> WebFailsafe / NAND preflight
  -> native-hybrid FIP из mtd0 backup ЭТОГО устройства
  -> persistent STOCK bootloader update + full readback
  -> reboot
  -> persistent XG140 UrsusBoot
  -> WebFailsafe
  -> корректный Bell XG-140G-MD OpenWrt sysupgrade
```

Обычный OpenWrt sysupgrade **не должен** передаваться stock tcboot как прямой boot payload.

---

## 2. Аппаратная база XG-140G-MD

Подтверждено на физическом устройстве:

```text
SoC                 AN7581DT
DRAM                512 MiB
DRAM type/rate      PCDDR4 / 2666 MT/s
SPI-NAND            SkyHigh S35ML02G3, 256 MiB
erase block         128 KiB
page                2048 B
OOB                 128 B
stock tcboot        Sep 07 2024 - 11:26:37
board id             XG140GMC2P5G
```

На плате также присутствует RJ11 и заселённая voice/SLIC-секция MaxLinear; точная модель SLIC пока не считается установленной.

Индивидуальные GPON/MAC/serial значения являются приватными данными конкретного устройства и в публичный репозиторий не заносятся.

---

## 3. Заводская физическая разметка

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

OpenWrt представляет boot area как:

```text
mtd0 bootloader   0x80000
mtd1 u-boot       0x7c000
mtd2 u-boot-env   0x02000
```

Это отражает физический контракт: ранняя boot/FIP-область `0x00000..0x7bfff`, stock environment `0x7c000..0x7ffff`.

---

## 4. Native-donor persistent FIP — обязательная политика

Для XG140 запрещено собирать field-install FIP из XG-040 donor, если доступен валидный backup собственного `mtd0` устройства.

Источник истины:

```text
mtd0_bootloader.bin(.gz) текущего XG140
```

Preflight обязан подтвердить:

```text
mtd0 size                         0x80000
BootROM prefix                    0x00000..0x007ff
BootROM prefix SHA256             82830140f4f8842702d0569065c27071b7cc24e0876e6c487cb4d9d81c294dd7
Airoha FIP physical offset        0x800
Airoha FIP magic                  010064aa78563412
protected stock env               0x7c000..0x7ffff
env CRC32                         valid
TB_FW UUID                        5ff9ec0b4d223e4da544c39d81c73f0a
TB_FW SHA256                      07c9e1542a3de845055faa2244bbd07adc8c5a136811a61a0d678ec8fff5ee5e
NT_FW UUID                        d6d0eea7fcead54b97829934f234b6e4
```

Сборка native-hybrid FIP:

```text
native XG140 FIP
  -> сохранить TOC entry set
  -> сохранить metadata всех entry кроме NT_FW/checksum
  -> сохранить payload всех entry кроме NT_FW/checksum byte-for-byte
  -> заменить только NT_FW / BL33 на XG140 UrsusBoot
  -> пересчитать checksum
  -> проверить FIP_END < 0x7c000 - 0x800
```

Финальный persistent write не имеет права изменять stock environment.

---

## 5. Persistent mtd0 contract

Device-side STOCK updater должен реализовывать именно следующий контракт:

```text
0x000000..0x0007ff   preserve live/native prefix
0x000800..FIP_END    native-hybrid XG140 FIP
FIP_END..0x07bfff    deterministic/preserved according to proven updater contract
0x07c000..0x07ffff   preserve stock env byte-for-byte
```

До reboot обязательно:

- точная XG140 board identity;
- layout `STOCK`;
- geometry `mtd0=0x80000`;
- prefix/lineage checks;
- FIP structural validation;
- один осмысленный `[y/N]` непосредственно перед первой persistent write;
- полное обратное чтение критической boot area;
- readback/hash verification;
- отсутствие `saveenv` и любых записей в `0x7c000..0x7ffff`.

Airoha BootROM `CCCC`/UART остаётся аварийным recovery path, но не заменяет preflight.

---

## 6. RAM и persistent UrsusBoot identity

XG140 build обязан иметь отдельную identity и не маскироваться под XG-040G-MD:

```text
Product: UrsusBoot
Board: Bell XG-140G-MD
Compatible: bell,xg-140g-md
SoC: AN7581
Build family: xg140-native
Environment backend: NOWHERE
```

Текущая development identity: `0.1.0-xg140-native1`.

RAM start из stock tcboot:

```text
loadx 0x81e00000
go 0x81e00000
```

Это hardware-test command, а не обещание универсальной совместимости tcboot всех ревизий.

---

## 7. OpenWrt XG140 status и final firmware policy

На физическом XG140 уже подтверждён RAM boot OpenWrt initramfs:

```text
board_name    bell,xg-140g-md
target        airoha/an7581
Linux         6.18.36
```

Подтверждены Ethernet через EN8811H/2500base-x и USB xHCI. Stock MAC extraction ещё не интегрирован, поэтому random MAC в RAM-initramfs не считается production acceptance.

Для final install разрешён только образ, структурно идентифицированный как Bell XG-140G-MD. XG-040G-MD factory/sysupgrade/preloader/BL2 запрещены как substitute.

Уже собранный XG140 sysupgrade bundle следует переиспользовать; новый OpenWrt build не запускается без необходимости.

---

## 8. Stock Web / Telnet bootstrap — XG140-specific

Статический разбор stock firmware показал отдельный XG140 service-management path.

`confignew_encryption.cfg` содержит текущий data model; секретные значения представлены шифрованными полями. Для публичного репозитория действует правило:

> plaintext Web/Telnet/SSH/su/service passwords и device-unique credentials не коммитить, не логировать и не помещать в diagnostics. Они могут существовать только локально/in-memory.

Установленная структура:

```text
TeleComAccount
  -> privileged Web AdminName/AdminPassword

ServiceManage
  -> TelnetEnable
  -> FactoryTelnetEnable
  -> TelnetUserName/TelnetPassword
  -> SSHUserName/SSHPassword
  -> SuPassword
  -> VtyshUserName/VtyshPassword
```

Статический разбор `system.cgi` показывает credential-gated factory Telnet path:

```text
request flag/au/ap
  -> verify against TeleComAccount (OID 59)
  -> ServiceManage (OID 74)
  -> toggle FactoryTelnetEnable
```

Нормальная hidden page `/system.cgi?telnet` также существует.

Целевой автоматизированный bootstrap после восстановления stock:

```text
privileged Web auth
  -> enable Factory Telnet through verified stock endpoint
  -> require TCP/23 open
  -> login ordinary Telnet account
  -> enumerate /etc/passwd
  -> prove su root (or another actual UID0 account)
  -> require id -u == 0
  -> ROOT_READY
```

FTP/Samba escalation, используемый на некоторых XG-040 builds, для XG140 является только fallback после доказанного отсутствия прямого UID0 path. Factory reset не является первым bootstrap-шагом: он может перезаписать полезное текущее состояние config DB.

---

## 9. A/B flags

XG140 использует `flag`/`flagback` и два stock slots.

Из reverse engineering:

```text
flag active      request slot
flag curimg      current image index
flag startok     successful-start state
flag count       retry counter
```

Для запроса slave при `curimg=0` изменяется только `active=1`; `flagback` вручную не зеркалируется. Это отдельный recovery mechanism и не должно смешиваться с persistent UrsusBoot installation transaction.

---

## 10. Текущий CI checkpoint

GitHub Actions run `34786299472`:

```text
workflow     Build XG140 UrsusBoot Native Persistent Recovery
head         4fb0dc93a044e1b87d92ad0f80f545ffdcfa9bce
result       SUCCESS
artifact     ursusboot-xg140-native1-4fb0dc93a044e1b87d92ad0f80f545ffdcfa9bce
artifact sha sha256:49a17e1de24ab55ac82547e2946a9ac2d45d84758a320e2371efd18a49d5de47
```

CI success означает build/package validation, **не** hardware acceptance persistent write.

---

## 11. Блокеры перед первой persistent hardware write

До destructive XG140 acceptance необходимо закрыть:

1. `xg140_native_persistent_install.py` сейчас имеет локальный `[y/N]`, а затем вызывает `update_bootloader(confirm=True)`, который задаёт второй `[y/N]`. Оставить ровно одно подтверждение.
2. Проверить device-side `/api/update-ursusboot` STOCK writer на отсутствие XG-040-only board/hash hardcoding и на точное соблюдение XG140 mtd0 contract.
3. Доказать full readback `mtd0` и неизменность env после write.
4. `xg140_ursusboot_web_recovery.py` должен разрешать final sysupgrade только после доказанной persistent XG140 UrsusBoot identity, а не только по generic XG140/layout.
5. Проверить XG140 stock-layout sysupgrade geometry: два slot по `0x2880000`, kernel virtual window `0x880000` и остаток под UBI; исключить XG040-specific offsets.
6. Аппаратно проверить сеть UrsusBoot: Linux уже доказал EN8811H/GDM4, но текущий initial U-Boot DTS ещё использует GDM1 как первый recovery path.

До закрытия этих пунктов статус: **CI PASS / PERSISTENT HW WRITE PENDING**.

---

## 12. Acceptance

Минимальный hardware acceptance XG140:

```text
stock tcboot UART
-> loadx/go XG140 RAM UrsusBoot
-> UART identity PASS
-> Ethernet/Web/API PASS
-> native mtd0 donor validation PASS
-> native-hybrid FIP offline lineage PASS
-> one y/N
-> STOCK bootloader write
-> full readback PASS
-> env byte-for-byte unchanged
-> power cycle
-> persistent UrsusBoot identity PASS
-> WebFailsafe PASS
-> Bell XG-140G-MD sysupgrade structural validation PASS
-> OpenWrt install/readback PASS
-> power cycle
-> OpenWrt board identity PASS
-> Ethernet PASS
-> individual board identity/MAC/GPON data PASS
```

Повторяемость нескольких циклов является допуском к продолжению работ, а не доказательством отсутствия всех failure modes.

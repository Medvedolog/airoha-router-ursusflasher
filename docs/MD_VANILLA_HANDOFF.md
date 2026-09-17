# MD Vanilla handoff — pregnant initramfs / EXPERT item 4

**Дата:** 2026-09-17  
**Ветка:** `feature/ursusboot-modular-airoha`  
**HEAD перед этой редакцией handoff:** `cee74310eb4699a8184482f3c6896d3a0bbc6a1d`  
**Нормативное ТЗ:** `docs/UrsusBoot_UrsusFlasher_TZ_RU_v5.45_VANILLA_INITRAMFS.md`

## 1. Главный архитектурный pivot

Vanilla item 4 больше не должен зависеть от исправления сетевого стека `UrsusBoot TRANSITION2`.

Новый production path:

```text
Nokia stock
  -> verified full backup
  -> подготовка stock-compatible SLOT2 payload
  -> одно meaningful y/N
  -> write/readback SLOT2
  -> selector -> SLOT2 + readback
  -> reboot
  -> OpenWrt pregnant initramfs
  -> autonomous migration stage2
  -> canonical OpenWrt UBI
  -> Vanilla BL31/U-Boot + sysupgrade + identity
  -> BL2 LAST
  -> full readback
  -> reboot
  -> Vanilla OpenWrt
```

`TRANSITION2` сохраняется как diagnostic/R&D ветка и доказательство отдельных механизмов, но не является обязательной install environment для Vanilla.

## 2. Что именно берём из MedveFlasher, а что нет

Берём правильную форму: transition Linux в SLOT2, который сам выполняет migration. Именно эта архитектура прошла множество успешных установок MedveFlasher.

Не переносим его fatal topology defect: fallback не должен одновременно быть write target. Старый MedveFlasher мог удалить recovery `fit` перед записью replacement и получить окно без bootable image.

В новом item 4 topology разделена:

```text
SLOT1 = stock fallback
SLOT2 = installer initramfs
UBI/FIP/BL2 = destructive production targets
BL2 = LAST
```

До финального destructive boundary stock chain остаётся доступной. SLOT1 и SLOT2 не являются теми же регионами, куда stage2 пишет production UBI/FIP/BL2.

## 3. Что доказал последний TRANSITION2 HW цикл

Для XG-040G-MD аппаратно доказано:

```text
PASS stock tcboot выбирает SLOT2
PASS stock FIT/hash -> Linux-compatible payload
PASS TRANSITION2 запускается
PASS Fudan FM25G02B виден
PASS fixed MAC установлен до Ethernet probe
PASS recovery IPv4 = 192.168.1.1/24
PASS RX LAN -> switch/GDM/QDMA -> CPU
PASS lwIP/U-Boot формирует TX frame
PASS QDMA потребляет TX descriptor, DONE=1
```

Host-visible ping/Web при этом не появился. Остаточная неисправность находится после QDMA TX consumption — GDM/switch egress либо иной inherited tcboot state. Для Vanilla это исследование замораживается: Linux initramfs использует штатный Linux networking/MTD/UBI stack и не требует нормализации U-Boot/lwIP после tcboot.

Не возвращаться к switch dump/normalization как prerequisite Vanilla item 4 без нового прямого требования оператора.

## 4. Что переезжает из MedveFlasher

Источник proven mechanics: `Medvedolog/nokia-router-medveflasher`.

В UrsusFlasher item 4 адаптировать:

```text
stock -> Linux bootm handoff
self-contained transition bundle
RAM initramfs stage2/autoflash
canonical UBI repartition/migration mechanics
identity preservation/restore mechanics
SSH discovery + polling + reconnect
production reboot detection
transition recovery shell when stage2 fails
status/log model
```

Не переносить MedveFlasher UX ceremony как обязательный contract:

```text
никаких codewords
никаких длинных typed confirmations
никаких повторных y/N между стадиями
никакого ручного продолжения каждой NAND операции
никакого выбора mtd/offsets пользователем в normal path
```

Механика — от MedveFlasher. UI и safety semantics — UrsusFlasher.

## 5. UrsusFlasher UI остаётся нашим

Использовать существующий `ursusflasher/src/console_ui.py`:

```text
ASCII bear
amber / amber2 / sand / ok / bad palette
[ШАГ] / [STEP]
[ГОТОВО] / [READY] / [PASS]
[ЖДУ] / [WAIT]
[ВНИМАНИЕ] / [WARNING]
[ОШИБКА] / [ERROR]
```

Новые stage2/SSH-monitoring сообщения должны проходить через тот же UI layer, а не приносить второй style system из MedveFlasher.

## 6. Минимум gates

Normal Vanilla transaction имеет **одно meaningful `y/N`** после полного automatic preflight-summary.

Это `y` сразу разрешает весь заранее показанный plan:

```text
SLOT2 write/readback
selector -> SLOT2/readback
reboot
pregnant initramfs autonomous stage2
UBI migration
FIP/sysupgrade/identity writes
BL2 LAST
verification
production reboot
```

После reboot дополнительных подтверждений нет.

Никаких:

```text
CONFIRM FORMAT AND FLASH
YES I UNDERSTAND
повторных y/N перед erase/write
отдельного confirm для rollback внутри уже подтверждённой transaction
```

Safety обеспечивается automatic validation/readback, а не ceremony.

## 7. Pregnant initramfs payload

В transition initramfs должны находиться заранее:

```text
OpenWrt kernel + initramfs
correct board DTB
Vanilla sysupgrade/production artifact
Vanilla BL31/U-Boot FIP
BL2/preloader if required
Fudan/FMSH support provenance
migration/autoflash scripts
prepared device identity data
manifest + hashes
Linux ursusstockslot helper
status service + journal
SSH
```

Критическая migration после boot не должна зависеть от скачивания production firmware по сети.

## 8. Stage1 на stock Nokia

До единственного `y/N`:

```text
board/profile resolve
verified full stock backup
identity extraction
stock A/B layout resolve
secondary SLOT2 resolve
pregnant bundle validation
embedded artifact provenance/hashes
candidate SLOT2 build
transport preflight
rollback availability proof
```

После `y`:

```text
write SLOT2
-> full SHA/readback
-> write selector only after SLOT2 PASS
-> selector readback
-> reboot
```

До этого момента SLOT1/master остаётся untouched.

## 9. Stage2 автономен, `/tmp` — только telemetry

Initramfs сам запускает migration service.

Нормальная state machine:

```text
BOOTED
PREFLIGHT
MIGRATION_OK
PROD_WRITING
PREPARING_UBI
WRITING_FIP
WRITING_SYSUPGRADE
RESTORING_IDENTITY
WRITING_BL2_LAST
VERIFYING_FINAL
PROD_VERIFIED
BOOT_CONFIRMED
FAILED
```

Live status contract:

```text
/tmp/ursus-install/status.json
/tmp/ursus-install/install.log
```

`/tmp` не переживает reboot/power loss и потому **никогда не является rollback authority**.

Рекомендуемые live fields:

```text
state
destructive_started
stock_master_intact
rollback_allowed
step
steps_total
progress
last_verified
error
```

Host не должен быть trigger каждой write-stage.

## 10. Persistent migration state

До первого destructive write stage2 обязан записать NAND-backed marker и доказать readback.

Нормативные состояния:

```text
MIGRATION_OK
PROD_WRITING
PROD_VERIFIED
BOOT_CONFIRMED
```

Базовый interface:

```text
fw_setenv <migration-state-key> PROD_WRITING
fw_printenv <migration-state-key>
sync
```

Только после verified `PROD_WRITING` разрешается первая destructive NAND operation.

Важная оговорка по текущему MD layout: `ubootenv` и `ubootenv2` находятся внутри UBI. Поэтому они полезны как persistent state carrier, но **не могут быть единственным доказательством rollback safety во время ubiformat/repartition**.

Fail-safe правило:

```text
marker missing
marker corrupt
redundant copies disagree
state unknown
    => rollback_allowed=false
```

После recreation canonical UBI `ubootenv`/`ubootenv2` должны быть созданы/восстановлены и marker должен быть восстановлен туда до дальнейших destructive стадий.

## 11. SSH — monitor/recovery plane

После reboot UrsusFlasher:

```text
finds transition initramfs
connects SSH
polls live status
reads persistent migration state
streams/tails install.log
renders progress through console_ui
reconnects after transient loss
waits for production reboot
validates final board/layout/identity
```

Если SSH пропал:

```text
stage2 continues locally
host reconnects
host reads current state
host never blindly repeats a NAND write
```

Если migration `FAILED`, но initramfs остаётся жив, сохраняется SSH recovery shell.

## 12. Linux `ursusstockslot`

Перенести в initramfs operator contract:

```text
ursusstockslot status
ursusstockslot master
ursusstockslot slave
```

Семантика:

```text
status -> read-only selector decode
master -> active=0 only
slave  -> active=1 only
```

Инвариант из proven host-side implementation сохраняется буквально:

```python
struct.pack_into("<I", out, 0, target)
if out[4:] != flag[4:]:
    raise RuntimeError("activation flag changed fields other than active")
```

MD profile сейчас знает:

```text
flag        expected mtd8,  size 0x00040000
flagback    expected mtd9
nsb_master  expected mtd14, size 0x02880000
nsb_slave   expected mtd15, size 0x02880000
erase size  0x00020000
```

Но Linux helper не должен использовать `mtd8` как универсальный API. Он должен resolve partition по имени/profile через `/proc/mtd`, затем сверить geometry.

Write contract:

```text
read full primary flag eraseblock
modify only active
preserve all other bytes
write buffered block
read back full block
verify target active
verify every non-active byte unchanged
```

`flagback` вручную не менять; reconciliation принадлежит stock tcboot.

Совместимый success marker:

```text
URSUS_STOCKSLOT_DONE target=master active=0 readback=PASS next=RESET
```

После него в Linux:

```text
sync
reboot -f   # если обычный reboot недостаточен
```

### Guard находится в utility, не в UI

`ursusstockslot master` обязан сам отказать, если rollback не доказан. Недостаточно скрыть/не вызвать команду в UrsusFlasher.

Public normal path не имеет `--force` обхода guard.

## 13. No-UART rollback — два независимых доказательства

`rollback_allowed` вычисляется, а не читается как доверенный boolean из RAM.

Для возврата на master одновременно нужны:

```text
A. persistent state показывает pre-destructive состояние
   и НЕ равен PROD_WRITING / PROD_VERIFIED / BOOT_CONFIRMED

B. NAND evidence доказывает, что stock fallback реально цел:
   stock partition/layout geometry matches
   nsb_master matches verified stock evidence
   critical regions потенциально затрагиваемые migration совпадают с verified backup/evidence
   нет partially converted UBI/layout
```

Только `A && B` разрешает `ursusstockslot master`.

При любом unknown/mismatch:

```text
URSUS_STOCKSLOT_REFUSED target=master reason=ROLLBACK_UNSAFE
```

После reset/power loss исчезновение `/tmp/status.json` не может сделать rollback «безопасным».

Если pregnant initramfs загрузился, но preflight/autoflash не смог безопасно начать migration, и `A && B` PASS:

```text
ursusstockslot status
ursusstockslot master
verify readback PASS
sync
reboot
```

Предпочтительно это делает сам initramfs автоматически.

Если auto rollback не сработал, UrsusFlasher по SSH выполняет тот же guarded contract. Повторного user confirmation не требуется: rollback является fail-safe частью уже подтверждённой transaction.

После `PROD_WRITING` **никогда автоматически не переключать selector на master**. Оставаться в initramfs и использовать только доказанную repair/retry strategy; UART/BootROM — last resort.

## 14. Final Vanilla payload policy

Конечный MD Vanilla boot chain:

```text
official/pinned OpenWrt source/build contract
OpenWrt AN7581 Nokia XG-040G-MD target
OpenWrt BL2/BL31/U-Boot
+ only required Fudan/FMSH SPI-NAND hardware support patches
+ no Ursus-specific persistent code
```

В финальном U-Boot не должно быть:

```text
UrsusBoot product identity
TRANSITION/PERSISTENT mode
WebFailsafe Ursus runtime
Ursus API
ursusstockslot
ursusnetreset
custom Ursus writer/recovery policy
```

После production boot пользователь обновляет OpenWrt обычным штатным `sysupgrade` на подходящий snapshot/release.

## 15. Persistent UrsusBoot — отдельный продукт

Не смешивать этот pivot с persistent line.

Persistent TEST61 lineage остаётся отдельным recovery-first продуктом. Известный lifecycle defect стандартных U-Boot network commands против живого WebFailsafe (`netif_remove`/`eth_halt`) должен быть исправлен отдельно перед public persistent build.

Он больше не блокирует Vanilla item 4.

## 16. Следующая реализация

Приоритетный порядок работ:

```text
1. Не тратить новые HW boots на TRANSITION2 switch egress ради Vanilla.
2. Вытащить из MedveFlasher минимально необходимый autonomous stage2/autoflash contract.
3. Сделать новый stock-compatible installer FIT builder, который не ограничен старым in-place kernel@1 размером ~3.7 MiB.
4. Собрать pregnant OpenWrt initramfs с embedded final artifacts.
5. Реализовать Linux ursusstockslot + byte-preservation/readback invariants + internal rollback guard.
6. Реализовать persistent migration state MIGRATION_OK/PROD_WRITING/PROD_VERIFIED/BOOT_CONFIRMED.
7. Реализовать NAND evidence probe и derive rollback_allowed как A && B.
8. Подключить status.json/install.log + SSH monitoring/reconnect к EXPERT item 4 с нашим console_ui.
9. Удалить лишние codeword/repeated confirmation gates: оставить одно y/N.
10. HW-test deliberate pre-destructive failure -> guarded master rollback -> stock boot.
11. HW-test reset/power-loss after PROD_WRITING -> master command must refuse.
12. Только после rollback/refusal HW PASS разрешить destructive UBI migration.
13. HW-test autonomous migration -> BL2 LAST -> PROD_VERIFIED -> Vanilla production boot -> BOOT_CONFIRMED.
14. После MD acceptance параметризовать тот же подход для MF без копирования MD offsets.
```

## 17. Repo/operator invariants

```text
branch = feature/ursusboot-modular-airoha
main untouched
no merge/tag/release without explicit operator command
no device backups/credentials/serial/GPON identity in git
one meaningful y/N for normal destructive transaction
automatic readback > extra operator ceremony
/tmp telemetry never authorizes rollback
missing/unknown persistent state = rollback denied
ursusstockslot master enforces guard internally
CI PASS != HW PASS
```

# UrsusBoot / UrsusFlasher ТЗ v5.44 — TRANSITION2 stabilization addendum

**Обновлено:** 2026-09-16  
**Статус:** normative engineering addendum к `v5.43_MODULAR_AIROHA`  
**Ветка:** `feature/ursusboot-modular-airoha`  
**Базовый кодовый HEAD до этого документа:** `7524a951f0fafd0c57fd91bc66c1b51e9bd8158e`  
**Важно:** `main`, tags и releases не изменяются без отдельной команды оператора.

Этот документ дополняет `docs/UrsusBoot_UrsusFlasher_TZ_RU_v5.43_MODULAR_AIROHA.md` и имеет приоритет там, где факты аппаратных прогонов 2026-09-16 уточняют более ранние требования.

## 1. Назначение текущего этапа

Текущая задача для XG-040G-MD — стабилизировать уже аппаратно загружающийся `TRANSITION2` до состояния, при котором переходной UrsusBoot уверенно доступен по Web/API без UART и может безопасно перейти к финальной Vanilla migration.

Функциональное имя остаётся:

```text
TRANSITION2
```

Диагностические/инженерные labels:

```text
TRANSITION2-NETDBG1
TRANSITION2-NETFIX2
```

Не переименовывать эту работу в `TRANSITION3` только из-за диагностических итераций.

## 2. TRANSITION не зависит от stock RI / board identity

TRANSITION является аварийным RAM runtime и обязан стартовать даже на чистом NAND, если ранняя boot chain уже доставила payload в RAM.

Поэтому для старта TRANSITION не являются обязательными:

```text
stock RI import
factory MAC import
serial import
GPON identity import
иные stock identity markers
```

Допустим локально сгенерированный/random MAC для recovery network. Identity/factory data имеют значение для сохранения и восстановления устройства при финальной миграции, но не являются prerequisite запуска WebFailsafe.

Stale embedded identity marker не должен быть hard-gate. Соответствующий gate удалён кодом 2026-09-16.

## 3. Контрольная база TRANSITION2 для Web

Пока HTTP regression не локализован, переходной образ строится максимально близко к аппаратно известной persistent MD TEST61 базе.

Источник:

```text
ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST61-source.tar.zst
```

Контрольный принцип:

```text
persistent TEST61 Web implementation
+ минимальный TRANSITION wrapper
```

В контрольной сборке `cmd/ursusweb.c` сохраняется как в persistent TEST61. TRANSITION-specific расширения `/api/status` не добавляются до аппаратного подтверждения нормального HTTP response path.

TRANSITION-specific части, которые сохраняются:

```text
stock-tcboot-compatible Linux Image handoff shim
ENV_IS_NOWHERE
TRANSITION dispatcher -> WebFailsafe path
NETFIX2 before WebFailsafe/lwIP listener creation
UART fallback after transport loss
ursusstockslot recovery command
```

## 4. Stock SLOT2 construction contract

Для MD staging используется stock `nsb_slave` конкретного устройства как structural envelope. Не создаётся «с нуля» альтернативная Nokia slot image.

Builder обязан:

```text
preserve stock FIP/HDR2/FIT/filesystem wrapper outside allowed fields
replace only approved kernel payload/metadata
inject TRANSITION Linux Image with compression=none
recalculate required FIT hash
preserve stock load/entry contract required by tcboot
validate exact slot size/write span
```

Текущий handoff:

```text
stock tcboot kernel load = 0x80088000
TRANSITION U-Boot TEXT_BASE = 0x81e00000
ARM64 shim copies u-boot.bin to TEXT_BASE and branches
```

Аппаратно подтверждено: tcboot выбирает SLOT2, stock FIT/hash validation проходит, shim запускает `U-Boot 2026.07-UrsusBoot-0.1.0-alpha5-UBIUX1-TRANSITION2`.

## 5. Backup contract — уточнение 2026-09-16

Перед destructive stock -> TRANSITION staging должен существовать **verified full stock backup** всех live `/proc/mtd` partitions.

При этом новый полный backup не обязан выполняться повторно при каждом тестовом прогоне, если оператор указывает уже существующий полный backup, который проходит штатную restore/backup validation.

Допустимы два пути:

```text
A. create new full backup -> verify -> continue
B. reuse existing full stock backup -> verify -> continue
```

Недопустимо:

```text
continue without any verified full stock backup
accept partial four-partition backup as production-equivalent full backup
skip size/SHA/manifest validation for reused backup
```

Текущий EXPERT item 4 реализует positive-default prompt создания нового backup; при отказе требует существующий verified full stock backup.

## 6. EXPERT item 4 retry/fail-safe transaction contract

Порядок staging обязан оставаться fail-safe:

```text
candidate build + structural validation
-> transfer/preflight
-> one meaningful destructive y/N
-> write nsb_slave
-> full/readback SHA verification of nsb_slave
-> only then write primary selector flag
-> selector readback
-> reboot
```

Если transport/session падает во время `nsb_slave` write, selector не должен переключаться. `nsb_slave` после такого события считается unknown/possibly partial до readback.

Bounded retry policy для long stock writes:

```text
max 3 attempts
reconnect to same stock target
before rewrite read target SHA
if target already equals expected SHA -> continue without rewriting
otherwise retry the same write
```

После destructive boundary автоматически не переключать writer/backend/transport на иной механизм.

## 7. Selector policy и возврат к stock SLOT1

Известные MD offsets:

```text
flag        0x05240000 size 0x00040000
flagback    0x05280000
nsb_master  0x000c0000
nsb_slave   0x02940000
```

`flag` находится в NAND и не является memory-mapped RAM. UART операции должны читать NAND block во временный RAM buffer, изменять его и писать обратно. Прямой `md.l 0x05240000` не является корректным чтением selector.

Для MD proven selector request меняется только:

```text
active=0 -> MASTER/SLOT1
active=1 -> SLAVE/SLOT2
```

Нельзя вручную синхронизировать `flagback`; tcboot владеет reconciliation. `curimg`, `startok`, `count` и остальные поля сохраняются без ручной нормализации.

TRANSITION command contract:

```text
ursusstockslot status
ursusstockslot master
ursusstockslot slave
```

Команда должна читать полный primary flag eraseblock, изменять только `active`, erase/write полный buffered block, делать readback и проверять сохранность остальных selector fields. Для destructive selector write требуется один meaningful confirmation.

Host-side EXPERT UART integration должна уметь разбудить idle U-Boot prompt переводом строки и корректно распознавать prompt с ANSI tail.

Web-кнопка возврата в stock SLOT1 остаётся отдельным UI follow-up; наличие UART/EXPERT команды не считается доказательством готовой Web-кнопки.

## 8. Airoha Ethernet lifecycle: установленный механизм `-22`

`-22` в наблюдаемом сценарии не является доказательством RX descriptor/DMA/cache corruption.

Установленный механизм:

```text
UrsusWeb owns eth0
-> operator runs standard U-Boot ping
-> ping uses NetLoop()
-> NetLoop exit calls eth_halt()
-> U-Boot eth device becomes not ACTIVE
-> UrsusWeb next eth_rx()
-> eth-uclass returns -EINVAL (-22)
```

Следовательно, пока WebFailsafe владеет network device, стандартный U-Boot `ping` не использовать как probe.

Диагностическая семантика:

```text
-EAGAIN / -11  = packet not ready / no RX packet at that instant
-EINVAL / -22  = device lifecycle/ownership state invalid, в подтверждённом случае device halted
```

## 9. NETFIX2 — reset до создания lwIP/Web state

Проблема старой ручной схемы `ursusnetreset` состояла в reset Ethernet при уже живом логическом состоянии UrsusWeb/lwIP.

NETFIX2 переносит полный Airoha datapath sanitize/reinit до запуска WebFailsafe:

```text
URSUS_TRANSITION_WEB_BEGIN
-> URSUS_TRANSITION_NET_SANITIZE_BEGIN
-> stop DMA
-> FEMEM_SEL=0
-> FE/PDMA/QDMA/XSI reset
-> switch_init
-> fe_init
-> restore runtime MAC
-> eth_init
-> URSUS_TRANSITION_NET_SANITIZE_DONE
-> WebFailsafe/lwIP listener
```

Обязательные markers:

```text
URSUS_TRANSITION_NET_SANITIZE_BEGIN
URSUS_TRANSITION_NET_SANITIZE_RESULT
URSUS_TRANSITION_NET_SANITIZE_DONE
URSUS_NETRESET_BEGIN build=TRANSITION2-NETFIX2
```

Цель — Web/lwIP создаются уже поверх заново инициализированного datapath, а не переживают аппаратный reset под собой.

## 10. Аппаратный acceptance status XG-040G-MD

На реальном XG-040G-MD подтверждено:

```text
PASS  stock tcboot -> SLOT2 selection
PASS  stock FIT/hash verification
PASS  ARM64 shim -> TRANSITION2 U-Boot
PASS  Fudan NAND detection
PASS  QDMA RX ring programming/readback
PASS  FEMEM access with FEMEM_SEL=0
PASS  NETFIX2 pre-Web sanitize path executes
PASS  WebFailsafe reaches HTTP listen marker on port 80
PASS  stock tcboot rollback to untouched SLOT1 on failed attempts
```

В отдельном ручном NETRESET эксперименте дополнительно подтверждено:

```text
PASS  host ARP/IP/ICMP after reset
PASS  TCP port 80 handshake after reset
FAIL  HTTP GET / -> curl (52) Empty reply from server
FAIL  HTTP GET /api/status -> Empty reply
FAIL  HTTP/1.0 /api/status -> Empty reply
```

Это локализует оставшийся дефект выше базового Ethernet/TCP connectivity, но не доказывает конкретный callback root cause.

Текущий контрольный эксперимент — TEST61 Web implementation без TRANSITION-specific `ursusweb.c` изменений. HTTP считается исправленным только после аппаратного ответа с HTTP bytes на `/` и `/api/status`.

## 11. Hardware test protocol для текущей итерации

После загрузки TRANSITION2 не выполнять U-Boot `ping`, пока Web владеет Ethernet.

С host PC проверять:

```powershell
ping 192.168.1.1
curl.exe -v --max-time 5 http://192.168.1.1/
curl.exe -v --max-time 5 http://192.168.1.1/api/status
curl.exe -v --http1.0 --max-time 5 http://192.168.1.1/api/status
```

Acceptance Web/API:

```text
TCP connect alone != PASS
HTTP listener marker alone != PASS
HTTP response bytes + valid status/body = PASS
```

## 12. Packaging/CI contract

Operator rollup строится поверх проверенного baseline package с overlay актуальных TRANSITION/EXPERT файлов. CI обязан корректно находить nested baseline root и сначала распаковывать baseline ZIP перед overlay.

Fastscan BL2 artifact не должен быть искусственным prerequisite сборки operator transition rollup.

CI проверяет как минимум:

```text
TRANSITION2 source/patch application
persistent TEST61 Web baseline remains intact in control build
NETFIX2 markers present
ursusstockslot command present
required EXPERT runtime helpers packaged
no stale web-only/identity gates
operator launchers/runtimes import successfully
```

CI PASS доказывает build/package contract, но не HTTP hardware acceptance и не безопасный финальный NAND migration.

## 13. MF scope

`xg040-mf` остаётся обязательной целью архитектуры, но текущий production `stock_ab_transition` policy ещё не является MF-ready. Нельзя объявлять MF production support, пока staging не станет board-profile driven и не пройдёт отдельный HW acceptance.

MD offsets/MTD indices/HDR assumptions не копируются в MF.

## 14. Immediate engineering sequence

```text
1. Build current TRANSITION2 control image from persistent TEST61 Web baseline.
2. HW-test SLOT2 boot with NETFIX2 and external curl, without U-Boot ping during Web ownership.
3. If HTTP response is restored, localize regression to removed TRANSITION-specific Web delta and reintroduce metadata only incrementally.
4. If HTTP remains Empty reply, instrument persistent TEST61-compatible HTTP/lwIP callback path; do not reopen Ethernet as primary hypothesis without new evidence.
5. Verify ursusstockslot status/master on the current TRANSITION2 build and EXPERT UART path; preserve only-active selector semantics.
6. Add Web UI return-to-stock-SLOT1 control only after backend selector operation is hardware accepted.
7. After TRANSITION2 Web/API HW_PASS, proceed to MD final Vanilla BL2/FIP/UBI migration implementation and acceptance.
8. Refactor staging to board-profile-driven MD/MF policy and then HW-accept MF independently.
9. Preserve persistent UrsusBoot and XG140 native-hybrid tracks; do not collapse their final boot policy into MD/MF Vanilla rules.
```

## 15. Repository / operator contract

- Работать только в `feature/ursusboot-modular-airoha`, пока оператор не сказал иначе.
- Не менять `main`, не merge, не tag, не release без прямой команды.
- Не коммитить backups, credentials, serial/GPON identity или иные device secrets.
- Не превращать advisory probes/firmware fingerprints в destructive hard-gates.
- Один meaningful `y/N` после automatic preflight-summary на обычную destructive transaction.
- До stock destructive staging должен существовать verified full stock backup; новый backup можно не повторять, если существующий успешно валидирован.
- Selector пишется только после verified `nsb_slave` readback.
- После начала destructive write writer/backend автоматически не меняется.
- TRANSITION startup не зависит от stock RI/MAC/serial identity.
- Не использовать стандартный U-Boot `ping`, пока UrsusWeb владеет network device.
- `CI PASS != HW PASS`.
- Functional version остаётся `TRANSITION2` до отдельного архитектурного решения.
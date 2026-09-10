# UrsusFlasher 0.2.62 TEST — Nokia XG-040G-MD + XG-040G-MF

Готовый тестовый комплект UrsusFlasher для двух аппаратных семейств:

```text
Nokia XG-040G-MD -> Airoha AN7581 -> UrsusBoot-MD TEST61
Nokia XG-040G-MF -> Airoha AN7583 -> UrsusBoot-MF TEST61
```

Для запуска нужен Python 3.12+; сторонние Python-пакеты не требуются.

Это **hardware-test kit**, а не релиз. Ветка разработки и main не объединяются автоматически, tag/release этим комплектом не создаются.

## Запуск

Windows:

```text
START_ONECLICK.cmd
START_EXPERT.cmd
```

Linux/macOS:

```text
./START_ONECLICK.sh
./START_EXPERT.sh
```

Аварийное восстановление через UART/BootROM:

```text
START_UART_RESTORE.cmd
START_UART_RESTORE.sh
```

## Что изменилось в 0.2.62

- ONE-CLICK и EXPERT определяют MD/MF по model/SoC и используют board-specific профиль.
- MD остаётся на frozen `0.1.0-alpha5-UBIUX1-TEST61`; его FIP при сборке 0.2.62 пересобирается и byte-for-byte сравнивается с эталоном.
- MF получил отдельный persistent runtime на базе TEST61: `bootcmd=ursusdispatch`, redundant environment в UBI `ubootenv`/`ubootenv2`, normal WebFailsafe/UBI install/update path.
- MF RAM Recovery остаётся отдельным образом с `ENV_IS_NOWHERE`; его нельзя путать с persistent runtime.
- MF persistent bootloader не прошивается универсальным FIP. Host читает фактический FIP/boot-area данного устройства, заменяет только NT_FW/BL33, сохраняет native ранние FIP-компоненты и factory environment, затем делает полный SHA256 readback.
- Для MF LAN2/LAN3/LAN4 используется аппаратно проверенный HWTEST8 native Clause-45 LED path; AN7581 raw-MMIO LED backend в MF не используется.
- Общий RI parser использует factory identity из RI, а не временный runtime `eth0` MAC.
- После destructive preflight остаётся одно обычное `y/N`. EXPERT позволяет явно пропустить полный restore-grade backup для stock bootloader-install; readback целевого boot-object всё равно обязателен.
- Автоматический alternate writer после начала записи запрещён: ошибка/неоднозначный readback останавливает дальнейший переход.

## ONE-CLICK: MD

Путь MD сохраняет TEST61 behavior:

```text
Nokia STOCK / установленная OpenWrt
        -> определить MD / AN7581
        -> проверить нужные payload
        -> установить/использовать UrsusBoot-MD TEST61
        -> полная проверка boot-object после записи
        -> UrsusBoot Recovery
        -> проверить OpenWrt
        -> STOCK/Factory -> UBI или UBI -> UBI
        -> readback / operation complete
        -> reboot OpenWrt
```

Уже установленный UrsusBoot не перепрошивается вторым автоматическим writer только из-за отличия отображаемой версии.

## ONE-CLICK: MF

Основной MF путь:

```text
Nokia STOCK / установленная OpenWrt
        -> доказать Nokia XG-040G-MF / AN7583
        -> проверить board-specific payload по size + SHA256
        -> прочитать фактический MF FIP/boot-area
        -> построить device-derived candidate
             native ранние FIP entries сохранены
             stock prefix сохранён
             stock environment сохранён
             заменён только NT_FW/BL33 UrsusBoot-MF
        -> одно y/N перед destructive write
        -> один выбранный writer
        -> полный SHA256 readback
        -> reboot + Reset -> UrsusBoot Recovery
        -> проверить MF identity заново
        -> загрузить UBI sysupgrade
        -> при stock/factory layout проверить MF BL2/preloader candidate
        -> UBI migration / update
        -> BL2 LAST там, где этого требует migration transaction
        -> operation complete
        -> reboot OpenWrt
```

MF bootloader self-update через универсальный Web FIP endpoint намеренно не используется: обновление загрузчика остаётся **device-derived host operation** из Nokia STOCK или работающей OpenWrt.

## MF OpenWrt payload

0.2.62 уже содержит hardware-proven MF UBI production payload из pinned MedveFlasher lineage:

```text
source commit
342cac4cb99a924f3d83eb8e4b5259490377704e

MF UBI sysupgrade
size    9191705
SHA256  db881b8053cdfbdf49dd6c2336dee3ddfa489966456a3e75556c5a0f6cc7663b

MF production preloader
size    118333
SHA256  778d10a65276085b70bec005248fc87ec208b43b0239502f15ade20fe528301e
```

Поэтому **для обычного MF ONE-CLICK отдельный OpenWrt-файл от пользователя не нужен**.

Отдельный MF non-UBI/factory-layout sysupgrade в 0.2.62 не включён. Он нужен только если требуется симметричный MD режим «установить/обновить OpenWrt, оставаясь в заводской физической разметке». Основной MF путь переводит stock/factory layout в UBI.

## MF Recovery / BootROM

В комплекте сохранены две разные сущности:

1. UrsusBoot-MF RAM Recovery `0.1.0-TEST61` — современный read-only/debrick runtime для диагностики, backup и RAM-операций.
2. Pinned BootROM/XMODEM rescue baseline — доказанные preloader/FIP bytes для аварийного входа и восстановления.

Reset до подачи питания относится к Airoha BootROM. Обычный UrsusBoot Recovery вызывается после старта/reboot удержанием Reset до последовательности 2 коротких + 3 длинных красных миганий и постоянного красного света.

## Проверки перед записью

Применимые проверки выполняются автоматически: family/model/SoC, текущая система, layout, MTD/UBI target, размер и SHA256 payload, доступность writer, сохранность device-derived FIP structure, transfer SHA256. Для миграции проверяется board-specific preloader/BL2 candidate.

После записи bootloader/boot-area/FIP считывается обратно. Несовпадение означает STOP: второй writer автоматически не запускается.

## Резервные копии

ONE-CLICK с Nokia STOCK по умолчанию снимает restore-grade backup перед первичной destructive операцией. EXPERT позволяет осознанно отказаться от полного backup для текущего запуска; это не отменяет локальную копию изменяемого boot-object и обязательный readback после записи.

Полный backup и восстановление остаются family-aware. MD и MF не используют backup другого семейства как штатный автоматический источник.

## Ethernet

Для Recovery предпочтительны:

```text
MD: LAN2 / LAN3
MF: LAN2 / LAN3 / LAN4
```

MF LAN1 — отдельный EN8811H 2.5G PHY и не является обязательным recovery port.

## Контроль целостности

В корне распакованного комплекта:

```text
SHA256SUMS
PAYLOAD_SHA256SUMS.txt
VERSION
```

Сборочный CI дополнительно проверяет frozen MD TEST61, MF RAM Recovery, MF persistent runtime, pinned Medve payload hashes, host Python compilation, board-aware manifest и окончательное содержимое ZIP.

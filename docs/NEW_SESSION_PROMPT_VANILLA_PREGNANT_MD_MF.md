# NEW SESSION PROMPT — UrsusFlasher Vanilla pregnant migration MD/MF

Продолжаем разработку UrsusBoot/UrsusFlasher.

Репозиторий:
`Medvedolog/airoha-router-ursusflasher`

Рабочая ветка:
`feature/ursusboot-modular-airoha`

СНАЧАЛА обязательно проверь live HEAD ветки. На момент этого handoff ожидаемый HEAD:
`117d44ac16f27658a4f8e50e987a3df358b803cc`

ВАЖНО:
- работать только в `feature/ursusboot-modular-airoha`;
- `main` НЕ трогать;
- не merge;
- не создавать tag/release без моей прямой команды;
- не коммитить backups, credentials, serial/GPON/device identity;
- при понятной задаче не спрашивать лишнего: делать и коммитить;
- после каждой записи указывать точный commit SHA;
- CI PASS не выдавать за HW PASS;
- CI считать PASS только после проверки exact run exact SHA;
- после успешной сборки всегда давать прямую ссылку на ZIP/artifact в чате;
- операторская ceremony минимальная: ОДНО meaningful `y/N` после automatic preflight, никаких codewords и повторных confirmations.

Перед работой прочитай:
1. `docs/MD_VANILLA_HANDOFF.md`
2. `docs/UrsusBoot_UrsusFlasher_TZ_RU_v5.45_VANILLA_INITRAMFS.md`
3. `config/UNAMEONE_2026-09-16_PAYLOADS.json`

## Текущий архитектурный pivot

Vanilla больше НЕ блокируется сетью UrsusBoot TRANSITION2. U-Boot transition network/switch R&D заморожен.

Целевой item 4:

```text
Nokia stock
-> verified full backup/preflight
-> build stock-compatible SLOT2 pregnant OpenWrt initramfs
-> ONE y/N
-> write/readback SLOT2
-> selector -> SLOT2 + readback
-> reboot
-> autonomous Linux stage2
-> canonical OpenWrt UBI migration
-> production UnameOne UBI sysupgrade
-> identity restore
-> Vanilla FIP
-> BL2/preloader LAST
-> final readback
-> reboot
-> Vanilla OpenWrt
```

Оператор имеет UART и прямо решил НЕ тратить итерацию на отдельный boot-only payload. Следующий test kit должен быть полным migration build.

## Что использовать как payload

Разделять runtime и production child.

Transient runtime:
- свежий/current official OpenWrt initramfs для нужного board;
- внутрь инъецировать Ursus/Medve stage2, SSH, status/log, guarded `ursusstockslot`, manifest/tools.

Production child:
**UnameOne Edition 16.09.2026**, pinned, не случайный current snapshot.

MD UBI sysupgrade:
`openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb`
SHA256:
`9b1f0899ca4ef610f6d87e8572d369adb420f104bda667556e8a0b5979f066dd`

MF UBI sysupgrade:
`openwrt-airoha-an7583-nokia_xg-040g-mf-ubi-squashfs-sysupgrade.itb`
SHA256:
`21dcf4c6ca64ea0c5bc3d601e4a8f99a3f002371b873f399f622cbd9223fd1d1`

Те же UnameOne production sets должны стать source-of-truth для item 1 и One-Click.

Присланные plain `.bin` — sysupgrade tar, НЕ factory:
MD SHA `1a0abfed83c52c55d60a3ef70c5df92c960fe3cc961bd2ca734e6d1749797a8d`
MF SHA `d988d6f47d69e7264bb7a0d81392c3fdc3bca163075066ee0e0b3f971abf8cbf`.

## Build status

Commit `cf4837a41b9554855a09a8449b21fd11d41b0135` добавил CI для получения current Vanilla initramfs bases.

Exact Actions run:
`35325588999`
для exact SHA `cf4837a41b9554855a09a8449b21fd11d41b0135`
завершился SUCCESS.

Это означает только CI PASS получения MD/MF initramfs bases. Это НЕ полный installer build и НЕ HW PASS.

Предыдущий ImageBuilder путь не годится: `make image` не выдал требуемый initramfs ITB.

Следующий builder должен использовать proven MedveFlasher-style FIT/newc surgery:
- current official initramfs FIT;
- unpack kernel/LZMA + linked newc;
- inject stage2/SSH/status/ursusstockslot;
- rebuild without corrupting bytes outside initramfs window;
- rebuild FIT/hashes;
- stock-compatible SLOT2 wrapper;
- carry exact pinned UnameOne UBI sysupgrade byte-for-byte as production child.

## Что взять из MedveFlasher

Репозиторий:
`Medvedolog/nokia-router-medveflasher`

Переиспользовать proven mechanics:
- autonomous stage2/autoflash;
- UBI repartition/migration;
- identity preservation/restore;
- SSH monitoring/reconnect;
- status/log;
- production boot detection.

НЕ переносить старый fatal topology defect: recovery image не может одновременно быть production write target.

НЕ переносить лишнюю ceremony.

## Safety contract

До destructive phase SLOT1 — fallback, SLOT2 — installer.

Linux helper:
```
ursusstockslot status
ursusstockslot master
ursusstockslot slave
```

Selector invariant:
```python
struct.pack_into("<I", out, 0, target)
if out[4:] != flag[4:]:
    raise RuntimeError("activation flag changed fields other than active")
```

`ursusstockslot master` guard обязан жить В САМОЙ utility.

Rollback:
- explicit `PROD_WRITING/PROD_VERIFIED/BOOT_CONFIRMED` -> REFUSED;
- marker absent + positive PRISTINE stock evidence + no OpenWrt/partial layout -> ALLOWED;
- marker absent/corrupt + anything other than proven PRISTINE -> REFUSED.

`/tmp/status.json` только telemetry, не rollback authority.

На virgin stock pre-UBI persistent OpenWrt marker может законно отсутствовать.

После появления canonical UBI persistent states хранятся/readback-проверяются через подходящий NAND-backed environment.

BL2/preloader — LAST.

Для MD не потерять Fudan/FMSH support в конечном Vanilla boot chain.

MF реализовать отдельным profile contract; не копировать MD offsets вслепую.

## Что делать прямо сейчас

1. Проверить live HEAD.
2. Прочитать handoff/TZ/manifest.
3. Реализовать полный pregnant builder MD+MF.
4. Реализовать autonomous stage2 с UBI migration, identity restore, FIP, UnameOne production child, BL2 LAST.
5. Подключить item 4 к новому backend; один y/N.
6. По возможности перевести item 1/One-Click на тот же UnameOne payload resolver, не создавая три источника firmware.
7. Создать/обновить dedicated CI полного build.
8. Коммитить в dev-ветку.
9. Проверить exact Actions run exact resulting SHA.
10. Если CI PASS — дать мне ZIP/artifact ссылку для UART HW-теста.
11. Не объявлять HW PASS до моего лога с железа.

Не возвращайся к починке TRANSITION2 Ethernet как prerequisite Vanilla.

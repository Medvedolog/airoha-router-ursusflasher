# UrsusBoot / UrsusFlasher — техническое задание
## Редакция 5.41 — уточнение определения Vanilla OpenWrt

**Дата редакции:** 2026-09-14  
**Целевые устройства:** Nokia XG-040G-MD / Nokia XG-040G-MF  
**Статус:** authoritative delta над v5.40 только в части определения `Vanilla OpenWrt` и provenance конечного OpenWrt boot chain. Требования v5.38/v5.39 по persistent/TRANSITION path и v5.40 по XG-140G-MD сохраняются, кроме прямо заменённой ниже формулировки v5.39 §6.

---

## 1. Нормативное определение Vanilla

Для UrsusFlasher термин **Vanilla OpenWrt** означает конечную persistent-систему, построенную по официальному OpenWrt build contract для поддерживаемой платы и **не содержащую UrsusBoot/Ursus-specific code в конечном boot chain**.

Критерий Vanilla определяется не отсутствием любых патчей относительно standalone upstream U-Boot, а происхождением и назначением изменений в конечном OpenWrt boot chain.

Совместимы со статусом Vanilla:

- официальный OpenWrt source tree / pinned официальный OpenWrt commit;
- U-Boot, собираемый как часть OpenWrt board-support/build path;
- board-support и hardware-enablement patches, необходимые OpenWrt для конкретной платы, SPI-NAND, PHY или другого штатного железа;
- патч поддержки Fudan/FMSH SPI-NAND для XG-040G-MD, даже если соответствующее изменение ещё не принято непосредственно в upstream U-Boot, при условии что патч используется только как hardware-support слой и не добавляет Ursus-specific functionality.

Не совместимы со статусом Vanilla:

- UrsusBoot WebFailsafe/Web Recovery runtime;
- Ursus API и Ursus-specific operation policy в конечном U-Boot;
- `Product: UrsusBoot`, `Mode: TRANSITION/PERSISTENT` или иная Ursus runtime identity в конечном загрузчике;
- Ursus-specific persistent recovery commands, boot policy или writer logic;
- произвольные локальные функциональные изменения, не являющиеся необходимым board/hardware support и не относящиеся к официальному OpenWrt build contract.

Иными словами:

```text
official OpenWrt build tree
+ штатный OpenWrt U-Boot integration
+ необходимый board/hardware support patch, включая Fudan/FMSH SPI-NAND
+ ZERO Ursus-specific persistent code
= Vanilla OpenWrt
```

---

## 2. XG-040G-MD: Fudan/FMSH SPI-NAND

Для Nokia XG-040G-MD конечный Vanilla U-Boot разрешено собирать с рабочим Fudan/FMSH SPI-NAND patch, используемым для поддержки фактической NAND устройства.

Сам факт того, что этот patch ещё не принят в standalone upstream U-Boot, **не переводит конечную систему в `NOT FULLY VANILLA`**.

Hardware-support patch должен оставаться минимальным и отделённым от UrsusBoot functionality. Финальный U-Boot не должен содержать TRANSITION/PERSISTENT identity, Ursus WebFailsafe, Ursus API или иной код, существующий только ради UrsusBoot.

---

## 3. Provenance обязателен

Для каждого Vanilla artifact UrsusFlasher должен уметь показать и/или проверить provenance:

```text
OpenWrt source: <official commit/tag>
OpenWrt target/board: <target/subtarget/device>
U-Boot source: <version/commit used by OpenWrt build>
Board/hardware patches: <ordered list + hashes/origin>
Fudan/FMSH SPI-NAND support: PRESENT | NOT_REQUIRED
Ursus-specific persistent patches: NONE
Final product identity: OpenWrt/U-Boot, not UrsusBoot
```

Наличие Fudan/FMSH patch должно быть прозрачно отражено в provenance, но не является предупреждением `NOT FULLY VANILLA` само по себе.

---

## 4. Замена требования v5.39 §6

Фраза v5.39:

> «Любой локальный compatibility patch, если он временно необходим до попадания upstream, должен быть явно показан пользователю как `NOT FULLY VANILLA` и не может называться official vanilla target.»

заменяется следующим нормативным правилом:

> **Vanilla status определяется принадлежностью конечного boot chain официальному OpenWrt build contract и отсутствием Ursus-specific persistent code. Board/hardware support patches, необходимые для штатной работы поддерживаемой платы, совместимы со статусом Vanilla, даже если соответствующее изменение ещё не принято непосредственно в upstream U-Boot. Такие patches обязаны быть отражены в provenance. `NOT FULLY VANILLA` применяется только к конечным custom modifications, выходящим за этот hardware-support/OpenWrt contract.**

---

## 5. TRANSITION не влияет на конечный Vanilla status

Одноразовый UrsusBoot TRANSITION может использоваться как временная RAM-среда миграции из stock Nokia.

Его наличие во время установки не делает конечную систему не-Vanilla при выполнении всех условий:

- TRANSITION не остаётся persistent boot target;
- конечный boot chain не содержит Ursus-specific code;
- финальный U-Boot и OpenWrt artifacts проходят provenance validation;
- после migration штатная загрузка не зависит от TRANSITION staging area, patched stock selector или Ursus API.

Таким образом, `Vanilla` описывает **конечное persistent состояние устройства**, а не временный инструмент, использованный для безопасной миграции.

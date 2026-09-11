#!/usr/bin/env python3
from __future__ import annotations

# Importing this layer fixes the legacy MD-only fixed-RI branch for MF stock
# backups. It is family-gated and does not change MD behavior.
import mf_backup_compat  # noqa: F401
import ui_terms as terms


def show() -> None:
    """Operator-facing install prerequisites; no probing and no device writes."""
    print()
    print(terms.tr(
        "╔══════════════════════════════════════════════════════════════════════════════╗\n"
        "║  ОБЯЗАТЕЛЬНО ДЛЯ NOKIA STOCK MD/MF                                         ║\n"
        "║  Перед установкой сбросьте роутер к заводским настройкам:                  ║\n"
        "║  на ВКЛЮЧЁННОМ устройстве удерживайте RESET не менее 20 секунд,             ║\n"
        "║  затем дождитесь полной загрузки заводской прошивки Nokia.                  ║\n"
        "╚══════════════════════════════════════════════════════════════════════════════╝",
        "╔══════════════════════════════════════════════════════════════════════════════╗\n"
        "║  REQUIRED FOR NOKIA STOCK MD/MF                                             ║\n"
        "║  Factory-reset the router before installation:                              ║\n"
        "║  with the device POWERED ON, hold RESET for at least 20 seconds,             ║\n"
        "║  then wait for the Nokia stock firmware to boot completely.                 ║\n"
        "╚══════════════════════════════════════════════════════════════════════════════╝",
    ))
    print()
    print(terms.tr(
        "[СЕТЬ] Для прошивки рекомендуется использовать порты LAN2 или LAN3. "
        "LAN1 — отдельный 2.5G-порт на PHY Airoha EN8811H; для него уже требовались отдельные исправления инициализации, "
        "поэтому использовать его при переходе между прошивками и аварийном восстановлении не рекомендуется. "
        "LAN4 в комплектной сборке OpenWrt от 06.09.2026 после загрузки назначается WAN, "
        "поэтому при прошивке через LAN4 после первой загрузки системы возможна потеря доступа к 192.168.1.1.",
        "[NETWORK] Prefer LAN2 or LAN3 for flashing. "
        "LAN1 is a separate 2.5G port on the Airoha EN8811H PHY; it has required separate initialization fixes, "
        "so it is not recommended for transition/recovery. "
        "LAN4 becomes WAN after booting the bundled 2026-09-06 OpenWrt build, "
        "so flashing through LAN4 can cause management access to 192.168.1.1 to be lost after first boot.",
    ))

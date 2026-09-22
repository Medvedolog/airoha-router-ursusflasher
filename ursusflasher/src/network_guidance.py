#!/usr/bin/env python3
from __future__ import annotations

import ipaddress
# Compatibility layers are family-gated: they restore the proven MF fixed-RI
# identity path and route MF UART RAM recovery to the current TEST62 payloads.
import mf_backup_compat  # noqa: F401
import mf_uart_test62_compat  # noqa: F401
import ui_terms as terms


def choose_router_host(default: str = "192.168.1.1") -> str:
    raw = input(terms.tr(
        f"IP-адрес Nokia [Enter — {default}]: ",
        f"Nokia IP address [Enter — {default}]: ",
    )).strip()
    host = raw or default
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as exc:
        raise RuntimeError(terms.tr(
            f"Некорректный IP-адрес Nokia: {host}",
            f"Invalid Nokia IP address: {host}",
        )) from exc
    if ip.version != 4:
        raise RuntimeError(terms.tr(
            "Для локальной прошивки сейчас поддерживается IPv4-адрес Nokia.",
            "Local flashing currently expects an IPv4 Nokia address.",
        ))
    return host


def show(host: str = "192.168.1.1") -> None:
    """Operator-facing install prerequisites; no probing and no device writes."""
    print()
    print(terms.tr(
        "+------------------------------------------------------------------------------+\n"
        "|  ОБЯЗАТЕЛЬНО ПЕРЕД ПРОШИВКОЙ NOKIA STOCK MD/MF                              |\n"
        f"|  Nokia по умолчанию 192.168.1.1; выбранный IP: {host:<27.27}|\n"
        "|  ПК: статический IPv4 в той же /24, например 192.168.1.254; DHCP выключить.  |\n"
        "|  Подключить ПК напрямую кабелем в LAN2/LAN3 роутера.                         |\n"
        "|  На время прошивки отключить Wi-Fi, VPN и прочие адаптеры/туннели.           |\n"
        "|  Перед установкой: RESET >=30 сек на включённом роутере, дождаться stock.    |\n"
        "+------------------------------------------------------------------------------+",
        "+------------------------------------------------------------------------------+\n"
        "|  REQUIRED BEFORE FLASHING NOKIA STOCK MD/MF                                  |\n"
        f"|  Default Nokia IP 192.168.1.1; selected IP: {host:<30.30}|\n"
        "|  PC: static IPv4 in the same /24, e.g. 192.168.1.254; disable DHCP.           |\n"
        "|  Connect the PC directly by cable to router LAN2/LAN3.                        |\n"
        "|  Disable Wi-Fi, VPN and other adapters/tunnels while flashing.                |\n"
        "|  Before install: hold RESET >=30 s while powered on; wait for stock boot.      |\n"
        "+------------------------------------------------------------------------------+",
    ))
    print()
    print(terms.tr(
        "[СЕТЬ] Для прошивки рекомендуется использовать порты LAN2 или LAN3. "
        "LAN1 — отдельный 2.5G-порт на PHY Airoha EN8811H; для него уже требовались отдельные исправления инициализации, "
        "поэтому использовать его при переходе между прошивками и аварийном восстановлении не рекомендуется. "
        "LAN4 в комплектной сборке OpenWrt от 06.09.2026 после загрузки назначается WAN, "
        f"поэтому при прошивке через LAN4 после первой загрузки системы возможна потеря доступа к {host}.",
        "[NETWORK] Prefer LAN2 or LAN3 for flashing. "
        "LAN1 is a separate 2.5G port on the Airoha EN8811H PHY; it has required separate initialization fixes, "
        "so it is not recommended for transition/recovery. "
        "LAN4 becomes WAN after booting the bundled 2026-09-06 OpenWrt build, "
        f"so flashing through LAN4 can cause management access to {host} to be lost after first boot.",
    ))

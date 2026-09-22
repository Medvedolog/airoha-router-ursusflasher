#!/usr/bin/env python3
from __future__ import annotations

import ipaddress
# Compatibility layers are family-gated: they restore the proven MF fixed-RI
# identity path and route MF UART RAM recovery to the current TEST62 payloads.
import mf_backup_compat  # noqa: F401
import mf_uart_test62_compat  # noqa: F401
import ui_terms as terms


def choose_router_host(default: str = "192.168.1.1") -> str:
    """Ask for the Nokia IPv4 address; a typo asks again instead of aborting."""
    while True:
        try:
            raw = input(terms.tr(
                f"IP-адрес Nokia [Enter — {default}]: ",
                f"Nokia IP address [Enter — {default}]: ",
            )).strip()
        except EOFError:
            raw = ""
        host = raw or default
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            print(terms.tr(
                f"Некорректный IP-адрес: {host}. Пример: 192.168.1.1",
                f"Invalid IP address: {host}. Example: 192.168.1.1",
            ))
            if not raw:
                raise RuntimeError(terms.tr(f"Некорректный IP по умолчанию: {host}", f"Invalid default IP: {host}"))
            continue
        if ip.version != 4:
            print(terms.tr(
                "Нужен IPv4-адрес Nokia, например 192.168.1.1.",
                "An IPv4 Nokia address is required, for example 192.168.1.1.",
            ))
            continue
        return host


def show(host: str = "192.168.1.1") -> None:
    """Operator-facing install prerequisites; no probing and no device writes."""
    print()
    rows = (
        ("ОБЯЗАТЕЛЬНО ПЕРЕД ПРОШИВКОЙ NOKIA STOCK MD/MF", "REQUIRED BEFORE FLASHING NOKIA STOCK MD/MF"),
        (f"Nokia по умолчанию 192.168.1.1; выбранный IP: {host}", f"Default Nokia IP 192.168.1.1; selected IP: {host}"),
        ("ПК: статический IPv4 в той же /24, например 192.168.1.254; DHCP выключить.",
         "PC: static IPv4 in the same /24, e.g. 192.168.1.254; disable DHCP."),
        ("Подключить ПК напрямую кабелем в LAN2/LAN3 роутера.", "Connect the PC directly by cable to router LAN2/LAN3."),
        ("На время прошивки отключить Wi-Fi, VPN и прочие адаптеры/туннели.",
         "Disable Wi-Fi, VPN and other adapters/tunnels while flashing."),
        ("Перед установкой: Reset не меньше 20 сек на включённом роутере, дождаться stock.",
         "Before install: hold Reset at least 20 s while powered on; wait for stock boot."),
    )
    width = max(78, max(len(terms.tr(ru, en)) + 4 for ru, en in rows))
    border = "+" + "-" * width + "+"
    print("\n".join([border] + ["|  " + terms.tr(ru, en).ljust(width - 2) + "|" for ru, en in rows] + [border]))
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

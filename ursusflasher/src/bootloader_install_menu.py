#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import board_profiles as bp
import console_ui as ui
import device_state as ds
import mf_runtime_install
import ursusboot_install
import ursusboot_update



def _xg140_module(name: str):
    """XG140 modules need the repack tool that only the XG140 kit ships."""
    try:
        return __import__(name)
    except ModuleNotFoundError as exc:
        raise RuntimeError(tr(
            "XG-140G-MD не входит в этот комплект (MD/MF). Используйте комплект XG140.",
            "XG-140G-MD is not part of this (MD/MF) kit. Use the XG140 kit.",
        )) from exc

def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def family_from_state(state: ds.DeviceState) -> str | None:
    key = str(state.evidence.get("board_profile") or "")
    if key.startswith("xg140"):
        return "xg140"
    if key.startswith("mf"):
        return "mf"
    if key.startswith("md"):
        return "md"
    match = bp.match_profile(model=state.model, soc=state.soc)
    return match[0] if match else None


def _ask_choice(prompt: str, valid: set[str]) -> str:
    while True:
        value = ui.prompt(prompt).strip()
        if value in valid:
            return value
        ui.status(tr("СТОП", "STOP"), tr("Нет такого пункта.", "No such item."))


def choose_family(state: ds.DeviceState) -> str | None:
    detected = family_from_state(state)
    labels = {
        "md": "Nokia XG-040G-MD / AN7581",
        "mf": "Nokia XG-040G-MF / AN7583",
        "xg140": "Bell/Nokia XG-140G-MD / AN7581DT",
    }
    while True:
        ui.section(tr("Модель UrsusBoot", "UrsusBoot target"), style="amber2")
        if detected:
            ui.menu_item(1, tr("Авто: определённая модель", "Auto: detected model"), labels[detected], tone="safe")
        else:
            ui.menu_item(1, tr("Авто: попробовать определить модель", "Auto: try model detection"), tr("Если сеть недоступна — выберите модель вручную", "If networking is unavailable, select the model manually"))
        ui.menu_item(2, labels["md"])
        ui.menu_item(3, labels["mf"])
        ui.menu_item(4, labels["xg140"])
        ui.menu_item(0, tr("Назад", "Back"))
        c = _ask_choice(tr("Модель: ", "Model: "), {"0", "1", "2", "3", "4"})
        if c == "0":
            return None
        if c == "1":
            if detected:
                return detected
            ui.status(tr("ИНФО", "INFO"), tr(
                "Автоопределение по сети сейчас ничего не дало. Выберите модель вручную.",
                "Network auto-detection returned no model. Select the model manually.",
            ))
            continue
        return {"2": "md", "3": "mf", "4": "xg140"}[c]


def choose_transport(family: str, state: ds.DeviceState) -> str | None:
    # EXPERT/HWTEST deliberately does not grey transports out from a probe result.
    # The selected backend will attempt the requested path and stop only on a
    # concrete transport/target failure before destructive write.
    ui.section(tr("Транспорт", "Transport"), style="amber2")
    ui.menu_item(
        1,
        tr("Telnet / заводская Nokia", "Telnet / Nokia stock"),
        tr("Пробовать stock Web/Telnet/TFTP; backend сам проверит доступ",
           "Try stock Web/Telnet/TFTP; the backend checks actual access"),
    )
    uart_detail = tr(
        "UART / tcboot / BootROM; для XG140 используется FIT initramfs bridge, не raw U-Boot go",
        "UART / tcboot / BootROM; XG140 uses the FIT initramfs bridge, not raw U-Boot go",
    ) if family == "xg140" else tr(
        "RAM recovery → persistent UrsusBoot writer",
        "RAM recovery → persistent UrsusBoot writer",
    )
    ui.menu_item(2, tr("UART / Airoha BootROM", "UART / Airoha BootROM"), uart_detail)
    ui.menu_item(0, tr("Назад", "Back"))
    c = _ask_choice(tr("Транспорт: ", "Transport: "), {"0", "1", "2"})
    if c == "0":
        return None
    return "telnet" if c == "1" else "uart"


def _confirm_selected_family(family: str, state: ds.DeviceState, *, transport: str) -> None:
    # Selector is routing, not authorization. Do not block an emergency UART
    # operation because network DeviceState is absent or stale. Backends retain
    # target geometry/candidate/readback invariants immediately around writes.
    detected = family_from_state(state)
    if detected and detected != family:
        ui.status(tr("ВНИМАНИЕ", "WARNING"), tr(
            f"Сетевой probe видел {detected.upper()}, вручную выбрано {family.upper()}; продолжаю по ручному выбору.",
            f"Network probe saw {detected.upper()}, manual selection is {family.upper()}; continuing with the manual selection.",
        ))


def _ask_skip_full_backup() -> bool:
    answer = ui.prompt(tr(
        "Пропустить полный restore-grade backup для этого запуска? [y/N]: ",
        "Skip the full restore-grade backup for this run? [y/N]: ",
    )).strip().lower()
    return answer in ("y", "yes", "д", "да")


def _run_uart(family: str, state: ds.DeviceState) -> None:
    if family == "md":
        ursusboot_update.uart_bootrom_recover()
        return
    if family == "mf":
        # Import lazily to avoid an import cycle with the EXPERT composition layer.
        import expert_multi
        expert_multi._run_ursus_recovery(state)
        return
    if family == "xg140":
        rc = _xg140_module("xg140_emergency_initramfs").main()
        if rc:
            raise RuntimeError(f"XG140 UART/initramfs installer returned rc={rc}")
        return
    raise RuntimeError(f"unsupported UrsusBoot family: {family}")


def _run_telnet(family: str, host: str) -> None:
    if family == "md":
        skip = _ask_skip_full_backup()
        rc = ursusboot_install.run_install(host=host, route="stock", skip_full_backup=skip)
    elif family == "mf":
        skip = _ask_skip_full_backup()
        rc = mf_runtime_install.run_install(
            host=host, route="stock", unattended=False,
            skip_full_backup=skip, recovery_after=False,
        )
    elif family == "xg140":
        rc = _xg140_module("xg140_runtime_install").install_from_stock(host=host)
    else:
        raise RuntimeError(f"unsupported UrsusBoot family: {family}")
    if rc:
        raise RuntimeError(f"{family.upper()} UrsusBoot installer returned rc={rc}")


def run(host: str, state: ds.DeviceState) -> None:
    """Compact item-2 selector: model first, transport second.

    EXPERT/HWTEST keeps choices visible and selectable even when DeviceState is
    incomplete. Authorization is deliberately local to the backend immediately
    around the actual target write, not a front-end policy gate.
    """
    family = choose_family(state)
    if family is None:
        return
    transport = choose_transport(family, state)
    if transport is None:
        return
    _confirm_selected_family(family, state, transport=transport)

    ui.rule(tr("URSUSBOOT INSTALL", "URSUSBOOT INSTALL"), style="amber2")
    ui.status("TARGET", family.upper())
    ui.status("TRANSPORT", transport.upper())
    if transport == "telnet":
        _run_telnet(family, host)
    else:
        _run_uart(family, state)

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
import xg140_runtime_install


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
    ui.section(tr("Модель UrsusBoot", "UrsusBoot target"), style="amber2")
    if detected:
        ui.menu_item(1, tr("Авто: определённая модель", "Auto: detected model"), labels[detected], tone="safe")
    else:
        ui.menu_item(1, tr("Авто: модель не определена", "Auto: model not detected"), tr("Выберите модель явно ниже", "Select the model explicitly below"), enabled=False)
    ui.menu_item(2, labels["md"])
    ui.menu_item(3, labels["mf"])
    ui.menu_item(4, labels["xg140"])
    ui.menu_item(0, tr("Назад", "Back"))
    c = _ask_choice(tr("Модель: ", "Model: "), {"0", "1", "2", "3", "4"})
    if c == "0":
        return None
    if c == "1":
        if not detected:
            raise RuntimeError(tr("Автоопределение модели не удалось.", "Model auto-detection failed."))
        return detected
    return {"2": "md", "3": "mf", "4": "xg140"}[c]


def choose_transport(family: str, state: ds.DeviceState) -> str | None:
    ui.section(tr("Транспорт", "Transport"), style="amber2")
    telnet_ok = state.current_system == "NOKIA_STOCK"
    ui.menu_item(
        1,
        tr("Telnet / заводская Nokia", "Telnet / Nokia stock"),
        tr("Stock Web → root Telnet → device-derived candidate → write → full readback",
           "Stock Web → root Telnet → device-derived candidate → write → full readback"),
        enabled=telnet_ok,
        reason="" if telnet_ok else tr("Нужна загруженная заводская прошивка Nokia/Bell", "Running Nokia/Bell stock firmware is required"),
    )

    if family == "xg140":
        uart_enabled = False
        uart_reason = tr(
            "XG140 UART persistent handoff пока HW-disabled: tcboot → go raw u-boot аппаратно отклонён; используйте Telnet",
            "XG140 UART persistent handoff is HW-disabled: tcboot → go raw u-boot was rejected on hardware; use Telnet",
        )
    else:
        uart_enabled = True
        uart_reason = ""
    ui.menu_item(
        2,
        tr("UART / Airoha BootROM", "UART / Airoha BootROM"),
        tr("RAM recovery → persistent UrsusBoot writer", "RAM recovery → persistent UrsusBoot writer"),
        enabled=uart_enabled,
        reason=uart_reason,
    )
    ui.menu_item(0, tr("Назад", "Back"))
    c = _ask_choice(tr("Транспорт: ", "Transport: "), {"0", "1", "2"})
    if c == "0":
        return None
    if c == "1" and not telnet_ok:
        raise RuntimeError(tr("Telnet-путь сейчас недоступен: stock Linux не определён.", "Telnet path is unavailable because stock Linux was not detected."))
    if c == "2" and not uart_enabled:
        raise RuntimeError(uart_reason)
    return "telnet" if c == "1" else "uart"


def _confirm_selected_family(family: str, state: ds.DeviceState, *, transport: str) -> None:
    detected = family_from_state(state)
    if detected and detected != family:
        raise RuntimeError(tr(
            f"Выбрана модель {family.upper()}, но устройство определено как {detected.upper()}; операция остановлена до записи.",
            f"Selected {family.upper()}, but the device was detected as {detected.upper()}; stopped before writing.",
        ))
    if transport == "telnet" and not detected:
        raise RuntimeError(tr(
            "Для Telnet-пути модель должна быть подтверждена живым DeviceState/stock Web.",
            "The Telnet path requires the model to be confirmed by live DeviceState/stock Web.",
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
    raise RuntimeError(tr(
        "XG140 UART persistent installer пока не прошёл hardware acceptance; используйте Telnet.",
        "The XG140 UART persistent installer has not passed hardware acceptance yet; use Telnet.",
    ))


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
        rc = xg140_runtime_install.install_from_stock(host=host)
    else:
        raise RuntimeError(f"unsupported UrsusBoot family: {family}")
    if rc:
        raise RuntimeError(f"{family.upper()} UrsusBoot installer returned rc={rc}")


def run(host: str, state: ds.DeviceState) -> None:
    """Compact item-2 selector: model first, then Telnet or UART.

    The top-level EXPERT menu remains model-neutral. Every backend re-reads its
    own hardware identity before a destructive write; this selector is routing,
    not authorization.
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

#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import board_profiles as bp
import device_state as ds
import expert as base
import mf_runtime_install
import one_key_multi
import runtime_kit
import stock_bootarea_restore
import uart_bootarea_restore
import ursusboot_install
import ursusboot_update

# Keep the mature EXPERT helpers/state machine. Replace only board-sensitive
# entrypoints and the menu dispatcher. The canonical action registry lives in
# device_state.py; this module may specialize applicability but must not mutate
# ACTION_KEYS or replace device_state.action_applicability globally.
base.one_key = one_key_multi
runtime_kit.install()


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def _family(state: ds.DeviceState) -> str | None:
    key = str(state.evidence.get("board_profile") or "")
    if key.startswith("mf"):
        return "mf"
    if key.startswith("md"):
        return "md"
    match = bp.match_profile(model=state.model, soc=state.soc)
    return match[0] if match else None


def _family_or_prompt(state: ds.DeviceState) -> str:
    family = _family(state)
    if family in ("md", "mf"):
        return family
    return uart_bootarea_restore.choose_family()


def _ask_skip_full_backup() -> bool:
    answer = base.ui.prompt(tr(
        "EXPERT: пропустить полный restore-grade backup для этого запуска? [y/N]: ",
        "EXPERT: skip the full restore-grade backup for this run? [y/N]: ",
    )).strip().lower()
    return answer in ("y", "yes", "д", "да")


def run_bootloader_install_or_update(host: str, state: ds.DeviceState) -> None:
    family = _family(state)
    if family == "mf":
        if state.current_system == "RECOVERY":
            raise RuntimeError(tr(
                "MF runtime не использует универсальный Web FIP-writer. Для device-derived обновления загрузите обычную OpenWrt или заводскую Nokia и повторите EXPERT → 2; Recovery остаётся доступен для OpenWrt/recovery-операций.",
                "MF runtime does not use a universal Web FIP writer. Boot normal OpenWrt or Nokia stock and run EXPERT -> 2 again for a device-derived update; Recovery remains available for OpenWrt/recovery operations.",
            ))
        skip = _ask_skip_full_backup() if state.current_system == "NOKIA_STOCK" else True
        route = "stock" if state.current_system == "NOKIA_STOCK" else "openwrt"
        rc = mf_runtime_install.run_install(
            host=host, route=route, unattended=False,
            skip_full_backup=skip, recovery_after=False,
        )
        if rc:
            raise RuntimeError(f"MF bootloader installer returned rc={rc}")
        return

    if family == "md" and state.current_system == "NOKIA_STOCK":
        skip = _ask_skip_full_backup()
        rc = ursusboot_install.run_install(host=host, route="stock", skip_full_backup=skip)
        if rc:
            raise RuntimeError(f"MD bootloader installer returned rc={rc}")
        return

    return _original_bootloader(host, state)


_original_bootloader = base.run_bootloader_install_or_update
base.run_bootloader_install_or_update = run_bootloader_install_or_update


_original_applicability = base.ds.action_applicability


def action_applicability(state: ds.DeviceState):
    out = _original_applicability(state)

    # Item 4 is UART-only raw boot-area restore and is intentionally available
    # even when the router has no usable network identity. Model is resolved
    # from the proven probe when possible, otherwise explicitly selected before
    # any BootROM transfer. The destructive y/N remains inside the restore flow.
    old4 = out[4]
    out[4] = ds.ActionApplicability(
        old4.number, ds.ACTION_KEYS[4], True, "", "",
        True, "UART_BOOTAREA_FACTORY_RESTORE",
    )

    if _family(state) == "mf" and state.current_system == "RECOVERY":
        old = out[2]
        out[2] = ds.ActionApplicability(
            old.number, old.key, False,
            tr(
                "Установка UrsusBoot на MF выполняется из заводской Nokia или из OpenWrt, не из режима восстановления",
                "MF UrsusBoot installation is device-derived and runs from Nokia stock or OpenWrt, not from Recovery",
            ),
            "", old.write_capable, "MF_DEVICE_DERIVED_HOST_ONLY",
        )
    return out


def _show_action(number: int, app: dict[int, ds.ActionApplicability], detail_ru: str = "", detail_en: str = "") -> None:
    """Do not repeat an unavailable action's reason as a second detail line."""
    if not app[number].enabled:
        detail_ru = ""
        detail_en = ""
    base._show_action(number, app, detail_ru, detail_en)


def _menu_detail(number: int, state: ds.DeviceState, app: dict[int, ds.ActionApplicability]) -> tuple[str, str]:
    family = _family(state)

    if number == 4:
        return (
            "Через USB-UART. Вернёт заводскую загрузочную область с полной проверкой.",
            "Via USB-UART. Restores the factory boot area with full verification.",
        )
    if number == 5:
        if family == "mf":
            return (
                "Для модели MF. Через USB-UART, с загрузкой в память. Образы от модели MD не используются.",
                "For the MF model. Via USB-UART, booting into RAM. MD images are not used.",
            )
        if family == "md":
            return (
                "Для модели MD. Через USB-UART, с загрузкой в память. Образы от модели MF не используются.",
                "For the MD model. Via USB-UART, booting into RAM. MF images are not used.",
            )
        return (
            "Через USB-UART. Сначала выбирается модель MD или MF, затем используется только её образ.",
            "Via USB-UART. Select MD or MF first; only the matching model image is then used.",
        )
    return base._menu_detail(number, state, app)


def _run_factory_bootarea_restore(state: ds.DeviceState) -> None:
    family = _family_or_prompt(state)
    stock_bootarea_restore.restore_factory_bootarea(family)


def _run_ursus_recovery(state: ds.DeviceState) -> None:
    family = _family_or_prompt(state)
    if family == "md":
        ursusboot_update.uart_bootrom_recover()
        return

    # The legacy uart_bootrom_recover() is MD-only and must never be called for
    # AN7583. Until a device-derived MF persistent writer is wired into the UART
    # recovery path, boot only the canonical MF TEST61 RAM recovery and stop
    # before NAND writes rather than silently sending AN7581/alpha3 payloads.
    profile = uart_bootarea_restore.family_profile("mf")
    base.ui.rule(tr("MF: BOOTROM → RAM URSUSBOOT", "MF: BOOTROM → RAM URSUSBOOT"), style="amber2")
    base.ui.status("TARGET", f"{profile['model']} / {profile['soc']}")
    base.ui.note(tr(
        "Будет запущена аварийная среда UrsusBoot для MF из оперативной памяти. NAND в этом пункте пока не изменяется.",
        "The MF UrsusBoot rescue environment will be booted from RAM. This item does not modify NAND yet.",
    ))
    sp, log, log_path = uart_bootarea_restore.boot_ram(profile)
    try:
        base.ui.status(tr("ГОТОВО", "READY"), tr(
            f"Аварийная среда UrsusBoot для MF запущена из памяти. Лог: {log_path}",
            f"The MF UrsusBoot rescue environment is running from RAM. Log: {log_path}",
        ))
    finally:
        try:
            sp.close()
        finally:
            log.close()


def main() -> int:
    base.proven.start_session_logging()
    base.ui.enable()
    base.one_key.choose_language()

    root = HERE.parent
    version = base.ui.package_version(root)
    host = os.environ.get("NOKIA_ROUTER_IP", "192.168.1.1").strip() or "192.168.1.1"
    while True:
        state = ds.probe_device_state(host)
        app = action_applicability(state)

        base.ui.banner("UrsusFlasher EXPERT", version=version)

        base.ui.section(tr("Установить", "Install"))
        for number in (1, 2, 3):
            detail_ru, detail_en = _menu_detail(number, state, app)
            _show_action(number, app, detail_ru, detail_en)

        base.ui.section(tr("Если роутер не загружается", "If the router does not boot"), style="amber2")
        _show_action(4, app, *_menu_detail(4, state, app))
        _show_action(5, app, *_menu_detail(5, state, app))
        _show_action(6, app, *base._menu_detail(6, state, app))

        base.ui.section(tr("Резервные копии", "Backups"), style="ok")
        for number in (7, 8, 9):
            detail_ru, detail_en = base._menu_detail(number, state, app)
            _show_action(number, app, detail_ru, detail_en)

        base.ui.section(tr("Посмотреть", "Inspect"), style="amber2")
        for number in (10, 11, 12):
            detail_ru, detail_en = base._menu_detail(number, state, app)
            _show_action(number, app, detail_ru, detail_en)

        print()
        base.ui.menu_item(0, tr("Выход", "Exit"))
        base.ui.note(tr("! — операция может выполнять запись во flash-память (NAND)", "! — operation may modify flash/NAND"))
        base.ui.rule(style="amber")

        c = base.ask_menu(12)
        if c == "0":
            return 0
        number = int(c)
        selected = app[number]
        if not selected.enabled:
            print()
            base.ui.status(tr("СТОП", "STOP"), selected.reason or tr("Действие сейчас неприменимо.", "This action is not currently applicable."))
            base.ui.prompt(tr("Нажмите Enter, чтобы вернуться в меню EXPERT...", "Press Enter to return to the EXPERT menu..."))
            continue

        if number == 1:
            skip_backup = False
            if state.current_system == "NOKIA_STOCK":
                ans = base.ui.prompt(tr(
                    "EXPERT: пропустить полный backup mtd0..mtd16 для этого запуска? [y/N]: ",
                    "EXPERT: skip the full mtd0..mtd16 backup for this run? [y/N]: ",
                )).strip().lower()
                skip_backup = ans in ("y", "yes", "д", "да")
            base.run_action(lambda: base.one_key.main(skip_full_backup=skip_backup), write_may_happen=True)
        elif number == 2:
            base.network_guidance.show()
            fresh_state = base._interactive_diagnostic_state(ds.probe_device_state(host))
            fresh_action = action_applicability(fresh_state)[2]
            if not fresh_action.enabled:
                base.ui.status(tr("СТОП", "STOP"), fresh_action.reason or tr("Действие сейчас неприменимо.", "This action is not currently applicable."))
                base.ui.prompt(tr("Нажмите Enter, чтобы вернуться в меню EXPERT...", "Press Enter to return to the EXPERT menu..."))
                continue
            base.ui.section(tr("Разрешённое действие", "Resolved action"), style="amber2")
            print("  " + tr("Действие: установить или обновить UrsusBoot", "Action: install or update UrsusBoot"))
            print("  " + tr("Метод: ", "Method: ") + base._bootloader_menu_detail(fresh_state, fresh_action))
            base.run_action(lambda: run_bootloader_install_or_update(host, fresh_state), write_may_happen=True)
        elif number == 3:
            base.network_guidance.show()
            fresh_state = ds.probe_device_state(host)
            fresh_action = action_applicability(fresh_state)[3]
            if not fresh_action.enabled:
                base.ui.status(tr("СТОП", "STOP"), fresh_action.reason or tr("Действие сейчас неприменимо.", "This action is not currently applicable."))
                base.ui.prompt(tr("Нажмите Enter, чтобы вернуться в меню EXPERT...", "Press Enter to return to the EXPERT menu..."))
                continue
            base.run_action(lambda: base.run_custom_openwrt(host, fresh_state, fresh_action), write_may_happen=True)
        elif number == 4:
            base.network_guidance.show()
            # Informational preflight only. uart_bootarea_restore.restore() owns
            # the single destructive y/N at the latest safe point, after the
            # board-specific RAM environment and NAND geometry are verified.
            base.ui.rule(tr("ВОССТАНОВЛЕНИЕ ЗАВОДСКОГО ЗАГРУЗЧИКА NOKIA",
                            "RESTORE NOKIA FACTORY BOOTLOADER"), style="bad")
            base.ui.status(tr("ВНИМАНИЕ", "WARNING"), tr(
                "Будет восстановлена заводская загрузочная область Nokia для выбранной модели.",
                "The Nokia factory boot area for the selected model will be restored.",
            ))
            base.ui.note(tr(
                "Нужен USB-UART 3.3 V. VCC не подключать. Подтверждение записи будет запрошено один раз после автоматического preflight.",
                "A 3.3 V USB-UART adapter is required. Do not connect VCC. Flashing will be confirmed once after automatic preflight.",
            ))
            base.run_action(lambda: _run_factory_bootarea_restore(state), write_may_happen=True)
        elif number == 5:
            base.network_guidance.show()
            if base.confirm_uart_recovery(
                "Airoha BootROM запустит подходящую для выбранной модели аварийную среду UrsusBoot из памяти. Образы MD и MF не смешиваются.",
                "Airoha BootROM will start the rescue UrsusBoot environment for the selected model from RAM. MD and MF images are never mixed.",
            ):
                base.run_action(lambda: _run_ursus_recovery(state), write_may_happen=True)
        elif number == 6:
            base.network_guidance.show()
            base.run_action(lambda: base.stock_restore.restore_nokia(base._interactive_diagnostic_state(state)), write_may_happen=True)
        elif number == 7:
            base.run_action(lambda: base.full_backup_readonly(base._interactive_diagnostic_state(state)))
        elif number == 8:
            base.run_action(base.validate_backup)
        elif number == 10:
            base.run_action(lambda: base.capability_report(base._interactive_diagnostic_state(state)))
        elif number == 11:
            try:
                base.flash_diagnostics(base._interactive_diagnostic_state(state))
            except Exception as exc:
                print(); base.ui.status(tr("ОШИБКА", "ERROR"), str(exc))
            finally:
                print(); base.ui.prompt(tr("Нажмите Enter, чтобы вернуться в меню EXPERT...", "Press Enter to return to the EXPERT menu..."))
        elif number == 12:
            base.run_action(ursusboot_update.show_info)


if __name__ == "__main__":
    raise SystemExit(main())
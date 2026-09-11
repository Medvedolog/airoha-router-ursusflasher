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

# Keep the mature EXPERT helpers/state machine. Replace only the board-sensitive
# entrypoints and the menu dispatcher where item 4 is now a real factory
# boot-area restore instead of the historical alias to item 2.
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
        old4.number, "restore_factory_bootarea", True, "", "",
        True, "UART_BOOTAREA_FACTORY_RESTORE",
    )

    if _family(state) == "mf" and state.current_system == "RECOVERY":
        old = out[2]
        out[2] = ds.ActionApplicability(
            old.number, old.key, False,
            tr(
                "MF bootloader update is device-derived and runs from Nokia stock or OpenWrt, not from Recovery",
                "MF bootloader update is device-derived and runs from Nokia stock or OpenWrt, not from Recovery",
            ),
            "", old.write_capable, "MF_DEVICE_DERIVED_HOST_ONLY",
        )
    return out


base.ds.action_applicability = action_applicability


def _menu_detail(number: int, state: ds.DeviceState, app: dict[int, ds.ActionApplicability]) -> tuple[str, str]:
    family = _family(state)
    suffix = ""
    if family == "md":
        suffix = "Nokia XG-040G-MD / AN7581"
    elif family == "mf":
        suffix = "Nokia XG-040G-MF / AN7583"

    if number == 4:
        ru = "USB-UART → Airoha BootROM → RAM Recovery → заводской boot-area/mtd0 0x80000 → полный readback"
        en = "USB-UART → Airoha BootROM → RAM Recovery → factory boot-area/mtd0 0x80000 → full readback"
        if suffix:
            ru += f"; цель: {suffix}"
            en += f"; target: {suffix}"
        return ru, en
    if number == 5:
        if family == "mf":
            return (
                "MF: USB-UART → AN7583 preloader → UrsusBoot TEST61 RAM Recovery; MD/AN7581 alpha3 payload запрещён",
                "MF: USB-UART → AN7583 preloader → UrsusBoot TEST61 RAM Recovery; MD/AN7581 alpha3 payload is forbidden",
            )
        if family == "md":
            return (
                "MD: USB-UART → AN7581 preloader → UrsusBoot alpha3 RAM installer → восстановление proven UrsusBoot",
                "MD: USB-UART → AN7581 preloader → UrsusBoot alpha3 RAM installer → recover proven UrsusBoot",
            )
        return (
            "USB-UART → выбор MD/MF → board-specific preloader + RAM Recovery; чужой payload не используется",
            "USB-UART → choose MD/MF → board-specific preloader + RAM Recovery; cross-family payloads are never used",
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
        "Будут переданы только MF/AN7583 preloader и UrsusBoot TEST61 RAM FIP. Persistent MF recovery writer пока не вызывается из этого пункта; NAND не изменяется.",
        "Only the MF/AN7583 preloader and UrsusBoot TEST61 RAM FIP will be sent. The persistent MF recovery writer is not yet invoked from this item; NAND is not modified.",
    ))
    sp, log, log_path = uart_bootarea_restore.boot_ram(profile)
    try:
        base.ui.status(tr("ГОТОВО", "READY"), tr(
            f"MF UrsusBoot TEST61 запущен из RAM. Лог: {log_path}",
            f"MF UrsusBoot TEST61 is running from RAM. Log: {log_path}",
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
        app = ds.action_applicability(state)

        base.ui.banner("UrsusFlasher EXPERT", version=version)

        base.ui.section(tr("Установить", "Install"))
        for number in (1, 2, 3):
            detail_ru, detail_en = _menu_detail(number, state, app)
            base._show_action(number, app, detail_ru, detail_en)

        base.ui.section(tr("Если роутер не загружается", "If the router does not boot"), style="amber2")
        base._show_action(4, app, *_menu_detail(4, state, app))
        base._show_action(5, app, *_menu_detail(5, state, app))
        base._show_action(6, app, *base._menu_detail(6, state, app))

        base.ui.section(tr("Резервные копии", "Backups"), style="ok")
        for number in (7, 8, 9):
            detail_ru, detail_en = base._menu_detail(number, state, app)
            base._show_action(number, app, detail_ru, detail_en)

        base.ui.section(tr("Посмотреть", "Inspect"), style="amber2")
        for number in (10, 11, 12):
            detail_ru, detail_en = base._menu_detail(number, state, app)
            base._show_action(number, app, detail_ru, detail_en)

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
            fresh_action = ds.action_applicability(fresh_state)[2]
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
            fresh_action = ds.action_applicability(fresh_state)[3]
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
                "Будет восстановлен заводской Nokia boot-area/mtd0 для выбранной модели.",
                "The Nokia factory boot-area/mtd0 for the selected model will be restored.",
            ))
            base.ui.note(tr(
                "Нужен USB-UART 3.3 V. VCC не подключать. Подтверждение записи будет запрошено один раз после автоматического preflight.",
                "A 3.3 V USB-UART adapter is required. Do not connect VCC. Flashing will be confirmed once after automatic preflight.",
            ))
            base.run_action(lambda: _run_factory_bootarea_restore(state), write_may_happen=True)
        elif number == 5:
            base.network_guidance.show()
            if base.confirm_uart_recovery(
                "Airoha BootROM запустит board-specific UrsusBoot Recovery из RAM. MD и MF используют разные preloader/FIP; cross-family payload запрещён.",
                "Airoha BootROM will start the board-specific UrsusBoot Recovery from RAM. MD and MF use different preloader/FIP payloads; cross-family payloads are forbidden.",
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

#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import board_profiles as bp
import device_state as ds
import expert as base
import mf_backup_compat
import mf_persistent
import mf_runtime_install
import one_key_multi
import runtime_kit
import stock_bootarea_restore
import uart_bootarea_restore
import ursus_web_client as uw
import ursusboot_install
import ursusboot_update

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


def _project_root() -> Path:
    repo = HERE.parent.parent
    return repo if (repo / "config").is_dir() else HERE.parent


def _mf_backup_candidate() -> Path:
    root = _project_root()
    latest = mf_backup_compat.latest_mtd0_backup(root / "work" / "backups")
    default = str(latest) if latest else ""
    prompt = tr(
        f"mtd0 backup этого MF [Enter={default}]: " if default else "Путь к mtd0 backup этого MF (512 КиБ, raw или .gz): ",
        f"This MF mtd0 backup [Enter={default}]: " if default else "Path to this MF mtd0 backup (512 KiB, raw or .gz): ",
    )
    raw_path = base.ui.prompt(prompt).strip().strip('"') or default
    if not raw_path:
        raise RuntimeError(tr("mtd0 backup не выбран.", "No mtd0 backup was selected."))
    source = mf_backup_compat.read_mtd0_backup(Path(raw_path))
    bl33_path = mf_runtime_install.require_bl33()
    candidate_boot, report = mf_persistent.build_stock_derived_candidate(source, bl33_path.read_bytes())
    fip = candidate_boot[mf_persistent.FIP_PHYS_OFF:mf_persistent.FIP_PHYS_OFF + report.candidate_fip_end]
    outdir = root / "work" / "private" / "mf-runtime-install"
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / time.strftime("mf-device-derived-TEST62-%Y%m%d-%H%M%S.fip")
    out.write_bytes(fip)
    base.ui.rule(tr("КАНДИДАТ URSUSBOOT", "URSUSBOOT CANDIDATE"), style="amber2")
    base.ui.status("TARGET", f"Nokia XG-040G-MF / Airoha AN7583 / UrsusBoot {one_key_multi.MF_TARGET}")
    base.ui.status("SOURCE mtd0", f"SHA256 {hashlib.sha256(source).hexdigest()}")
    base.ui.status("BL33", f"{bl33_path.name} · SHA256 {hashlib.sha256(bl33_path.read_bytes()).hexdigest()}")
    base.ui.status("FIP", f"{out.name} · {len(fip)} bytes · SHA256 {hashlib.sha256(fip).hexdigest()}")
    base.ui.note(tr(
        "Кандидат собран из mtd0 этого устройства: native ранние FIP-компоненты сохранены, заменён только NT_FW/BL33. Запись запросит один y/N.",
        "The candidate is derived from this device's mtd0: native early FIP components are preserved and only NT_FW/BL33 is replaced. One y/N will be requested before writing.",
    ))
    return out


def _mf_update_from_recovery(host: str) -> None:
    st = uw.status(host)
    board = str(st.get("board") or st.get("target") or "")
    soc = str(st.get("soc") or "")
    if "XG-040G-MF" not in board or "AN7583" not in soc:
        raise RuntimeError(f"Recovery is not positively identified as MF/AN7583: board={board!r} soc={soc!r}")
    candidate = _mf_backup_candidate()
    result = uw.update_bootloader(host, candidate, confirm=True)
    if not result.get("bootloader_update_complete"):
        raise RuntimeError("UrsusBoot did not report a completed bootloader update")
    base.ui.status(tr("ГОТОВО", "READY"), tr(
        f"UrsusBoot {one_key_multi.MF_TARGET} записан и проверен. Перезагрузка остаётся ручной.",
        f"UrsusBoot {one_key_multi.MF_TARGET} was written and verified. Reboot remains manual.",
    ))


def run_bootloader_install_or_update(host: str, state: ds.DeviceState) -> None:
    family = _family(state)
    if family == "mf":
        if state.current_system == "RECOVERY":
            _mf_update_from_recovery(host)
            return
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
    old4 = out[4]
    out[4] = ds.ActionApplicability(
        old4.number, ds.ACTION_KEYS[4], True, "", "",
        True, "UART_BOOTAREA_FACTORY_RESTORE",
    )
    if _family(state) == "mf" and state.current_system == "RECOVERY":
        old = out[2]
        out[2] = ds.ActionApplicability(
            old.number, old.key, True, "", "",
            True, "MF_RECOVERY_DEVICE_DERIVED_FIP_UPDATE",
        )
    return out


def _show_action(number: int, app: dict[int, ds.ActionApplicability], detail_ru: str = "", detail_en: str = "") -> None:
    if not app[number].enabled:
        detail_ru = ""
        detail_en = ""
    base._show_action(number, app, detail_ru, detail_en)


def _menu_detail(number: int, state: ds.DeviceState, app: dict[int, ds.ActionApplicability]) -> tuple[str, str]:
    family = _family(state)
    if number == 2 and family == "mf" and state.current_system == "RECOVERY":
        return (
            "Через запущенный UrsusBoot Recovery; device-derived FIP собирается из вашего mtd0 backup и записывается штатным updater с readback.",
            "Through the running UrsusBoot Recovery; a device-derived FIP is built from your mtd0 backup and written by the native updater with readback.",
        )
    if number == 4:
        return (
            "Через USB-UART. Вернёт заводскую загрузочную область с полной проверкой.",
            "Via USB-UART. Restores the factory boot area with full verification.",
        )
    if number == 5:
        if family == "mf":
            return (
                "MF: BootROM/USB-UART → UrsusBoot TEST62 в RAM → при наличии mtd0 backup можно сразу починить persistent UrsusBoot.",
                "MF: BootROM/USB-UART -> UrsusBoot TEST62 in RAM -> with an mtd0 backup the persistent UrsusBoot can be repaired immediately.",
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
    if number == 7 and state.current_system == "NOKIA_STOCK":
        return (
            "Заводская Nokia: Web/Telnet/TFTP → mtd0..mtd16 → копия на ПК; OpenWrt и UrsusBoot не устанавливаются, flash не изменяется.",
            "Nokia stock: Web/Telnet/TFTP -> mtd0..mtd16 -> PC backup; OpenWrt/UrsusBoot are not installed and flash is not modified.",
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

    profile = uart_bootarea_restore.family_profile("mf")
    base.ui.rule(tr("MF: BOOTROM → RAM URSUSBOOT", "MF: BOOTROM -> RAM URSUSBOOT"), style="amber2")
    base.ui.status("TARGET", f"{profile['model']} / {profile['soc']} / {one_key_multi.MF_TARGET}")
    base.ui.note(tr(
        "Сначала UrsusBoot запускается из RAM без записи NAND. После запуска можно восстановить persistent UrsusBoot из device-derived кандидата по вашему mtd0 backup.",
        "UrsusBoot is first started from RAM without writing NAND. Once running, the persistent UrsusBoot can be repaired using a device-derived candidate from your mtd0 backup.",
    ))
    sp, log, log_path = uart_bootarea_restore.boot_ram(profile)
    try:
        base.ui.status(tr("ГОТОВО", "READY"), tr(
            f"MF UrsusBoot запущен из RAM. Лог: {log_path}",
            f"MF UrsusBoot is running from RAM. Log: {log_path}",
        ))
        answer = base.ui.prompt(tr(
            "Починить persistent UrsusBoot сейчас из mtd0 backup? [y/N]: ",
            "Repair persistent UrsusBoot now from an mtd0 backup? [y/N]: ",
        )).strip().lower()
        if answer in ("y", "yes", "д", "да"):
            # Network remains served by the RAM UrsusBoot while UART stays open.
            _mf_update_from_recovery(os.environ.get("NOKIA_ROUTER_IP", "192.168.1.1"))
    finally:
        try:
            sp.close()
        finally:
            log.close()


def _run_backup(state: ds.DeviceState) -> None:
    fresh = base._interactive_diagnostic_state(state)
    with mf_backup_compat.stock_backup_compat(compact_progress=True):
        base.full_backup_readonly(fresh)


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
            detail_ru, detail_en = _menu_detail(number, state, app)
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
            print("  " + tr("Метод: ", "Method: ") + _menu_detail(2, fresh_state, {2: fresh_action})[0 if os.environ.get("NOKIA_LANG") != "en" else 1])
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
            base.ui.rule(tr("ВОССТАНОВЛЕНИЕ ЗАВОДСКОГО ЗАГРУЗЧИКА NOKIA", "RESTORE NOKIA FACTORY BOOTLOADER"), style="bad")
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
            base.run_action(lambda: _run_ursus_recovery(state), write_may_happen=True)
        elif number == 6:
            base.network_guidance.show()
            base.run_action(lambda: base.stock_restore.restore_nokia(base._interactive_diagnostic_state(state)), write_may_happen=True)
        elif number == 7:
            base.run_action(lambda: _run_backup(state))
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

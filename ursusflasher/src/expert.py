#!/usr/bin/env python3
from __future__ import annotations

import getpass
import json
import os
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import console_ui as ui
import device_state as ds
import one_key
import proven_backend as proven
import stock_web
import ui_terms as terms
import network_guidance
import ursus_web_client as uw
import ursusboot_install
import ursusboot_update


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def ask_menu(max_item: int) -> str:
    while True:
        value = input(tr("Пункт: ", "Item: ")).strip()
        if value.isdigit() and 0 <= int(value) <= max_item:
            return value
        print(tr(f"Нет такого пункта. Введите число от 0 до {max_item}.",
                 f"No such item. Enter a number from 0 to {max_item}."))


def confirm_uart_recovery(kind_ru: str, kind_en: str, *, title_ru: str = "АВАРИЙНОЕ ВОССТАНОВЛЕНИЕ", title_en: str = "EMERGENCY RECOVERY", style: str = "bad") -> bool:
    print()
    ui.rule(tr(title_ru, title_en), style=style)
    ui.status(tr("ВНИМАНИЕ", "WARNING"), tr(kind_ru, kind_en))
    ui.note(tr("Нужен USB-UART 3.3 V, подключённый к плате роутера. VCC не подключать.",
               "A 3.3 V USB-UART adapter connected to the router board is required. Do not connect VCC."))
    ans = ui.prompt(tr("Продолжить? [д/Н]: ", "Continue? [y/N]: ")).strip().lower()
    return ans in ("д", "да", "y", "yes")


def update_bootloader_network() -> None:
    try:
        ursusboot_update.web_fip_update()
    except Exception as first:
        print(tr(
            f"[ВНИМАНИЕ] Передача через веб-интерфейс не завершилась: {first}",
            f"[WARNING] WebFailsafe upload did not complete: {first}",
        ))
        print(tr(
            "Пробую запасной способ передачи через TFTP и ту же консоль UrsusBoot.",
            "Trying TFTP as the fallback transport through the same UrsusBoot console.",
        ))
        ursusboot_update.tftp_update_automated()


def _tcp_open(host: str, port: int, timeout: float = 1.0) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def _readonly_stock_access(host: str) -> proven.StockAccess:
    """Authenticate to stock Web without enabling Telnet/FTP/Samba or changing settings."""
    client = stock_web.StockWeb(host)
    user = stock_web.DEFAULT_WEB_USER
    password = stock_web.DEFAULT_WEB_PASSWORD
    proven._register_log_secret(password)
    try:
        try:
            client.login(user, password, allow_plain=False)
        except Exception:
            # A manually changed Web password may still be used; this remains read-only.
            entered = getpass.getpass(tr(
                "Стандартный пароль stock Web не принят. Пароль Web UI [Enter — перейти к BootROM backup]: ",
                "The standard stock Web password was not accepted. Web UI password [Enter — use BootROM backup]: ",
            ))
            if not entered:
                raise
            password = entered
            proven._register_log_secret(password)
            client = stock_web.StockWeb(host)
            client.login(user, password, allow_plain=False)
        setup = stock_web.StockSetup(client)
        info = setup.require_model(("XG-040G-MD",))
        credentials = setup.read_credentials()
        telnet_port = int(credentials["telnet_port"])
        if not bool(credentials.get("telnet_enabled")) or not _tcp_open(host, telnet_port):
            raise RuntimeError(tr(
                "Telnet сейчас выключен. Read-only backup не будет включать его автоматически.",
                "Telnet is currently disabled. Read-only backup will not enable it automatically.",
            ))
        return proven.StockAccess(
            host=host,
            user=str(credentials["telnet_user"]),
            password=str(credentials["telnet_password"]),
            su_user="auto",
            su_password=None,
            telnet_port=telnet_port,
            ftp_user=str(credentials.get("ftp_user") or ""),
            ftp_password=str(credentials.get("ftp_password") or ""),
            ftp_port=int(credentials.get("ftp_port") or 21),
            ftp_enabled=bool(credentials.get("ftp_enabled")),
            model_verified=True,
            model_verification_source="stock-web-device_status.cgi-readonly",
            family="md",
            model_name=str(info.get("model") or "XG-040G-MD"),
            chipset=str(info.get("chipset") or "AN7581"),
            web_client=client,
            web_setup=setup,
            web_module=stock_web,
        )
    except Exception:
        try:
            client.logout()
        except Exception:
            pass
        raise


def backup_stock_readonly(host: str) -> None:
    access = None
    try:
        access = _readonly_stock_access(host)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        default_dest = Path(proven.WORK) / "backups" / f"stock-full-readonly-{stamp}"
        raw = input(tr(f"Каталог для полной копии [{default_dest}]: ",
                       f"Full backup directory [{default_dest}]: ")).strip().strip('"')
        destination = Path(raw).expanduser() if raw else default_dest
        print(tr(
            "[ШАГ] Снимаю mtd0..mtd16. Службы Telnet/FTP/Samba не включаются, NAND не изменяется.",
            "[STEP] Capturing mtd0..mtd16. Service provisioning is forbidden: Telnet/FTP/Samba are not enabled and NAND is not modified.",
        ))
        proven.backup_tftp(
            access, access.host, destination, expected_family="md",
            allow_service_provisioning=False,
        )
        print(tr(f"[ГОТОВО] Полная копия сохранена: {destination}",
                 f"[READY] Complete backup saved: {destination}"))
    finally:
        if access:
            access.close_web(announce=False)


def full_backup_readonly(state: ds.DeviceState) -> None:
    if state.current_system == "NOKIA_STOCK" and state.probe_status == ds.PROBE_COMPLETE:
        try:
            backup_stock_readonly(state.host)
            return
        except Exception as exc:
            proven._write_session_only("[READONLY-STOCK-BACKUP] " + repr(exc))
            print(tr(
                f"[ИНФО] Создание полной копии в режиме только чтения из запущенной заводской прошивки Nokia недоступно: {exc}",
                f"[INFO] Strict read-only backup from running Nokia is unavailable: {exc}",
            ))
            print(tr(
                "Перехожу к созданию полной копии через BootROM из среды, запущенной в оперативной памяти. Службы не включаются, NAND не изменяется.",
                "Falling back to the universal BootROM/RAM capture. It does not enable services or write NAND.",
            ))
    elif state.current_system.startswith("OPENWRT"):
        print(tr(
            "[ИНФО] Копия, созданная из запущенной OpenWrt с доступной записью, не считается пригодной для точного восстановления. Для точного копирования используется среда восстановления, запущенная в оперативной памяти.",
            "[INFO] A live writable OpenWrt dump is not marked restore-grade. Exact capture uses the quiescent BootROM/RAM path.",
        ))
    proven.bootrom_backup_wizard()


def validate_backup() -> None:
    default_root = Path(proven.WORK) / "backups"
    raw = input(tr(f"Путь к backup [{default_root}]: ", f"Backup path [{default_root}]: ")).strip().strip('"')
    path = Path(raw).expanduser() if raw else default_root
    if path == default_root:
        candidates = sorted([p for p in default_root.glob("*") if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise RuntimeError(tr("Локальные backup не найдены.", "No local backups were found."))
        path = candidates[0]
        print(tr(f"Проверяю последнюю копию: {path}", f"Validating latest backup: {path}"))
    result = proven.verify_stock_restore_backup(path)
    print(tr("[ГОТОВО] BACKUP_STATUS=RESTORE_READY", "[READY] BACKUP_STATUS=RESTORE_READY"))
    print(f"family={result.get('stock_family')} variant={result.get('stock_variant')}")
    stock = result.get("stock_restore", {})
    if stock:
        print(f"all_flash_sha256={stock.get('all_flash_sha256')}")


def print_state_header(state: ds.DeviceState) -> None:
    ui.section(tr("Состояние устройства", "Device state"), style="amber2")
    for line in ds.state_summary_lines(state, english=(os.environ.get("NOKIA_LANG") == "en")):
        print("  " + line)
    if state.probe_reasons:
        for reason_code in state.probe_reasons:
            ui.note(tr("Причина: ", "Reason: ") + terms.human(reason_code, "probe_reason"))


def capability_report(state: ds.DeviceState) -> None:
    app = ds.action_applicability(state)
    print_state_header(state)
    print()
    print(tr("Доступность действий:", "Action availability:"))
    for number in range(1, 13):
        a = app[number]
        title = terms.action_title(a.key)
        yes = tr("ДА", "YES") if a.enabled else tr("НЕТ", "NO")
        extra = f" — {a.reason}" if (not a.enabled and a.reason) else ""
        marker = "!" if a.write_capable else " "
        print(f" {marker} {number:2d}  {title:<42} {yes}{extra}")
        if number == 2 and a.enabled:
            print("       " + tr("Метод: ", "Method: ") + terms.human(a.resolved_backend, "method"))
        if a.enabled and a.note:
            print(f"       {a.note}")
    print()
    ui.note(tr(
        "! означает только: операция может выполнять запись во flash-память (NAND). Это не общий значок опасности.",
        "! means only that the operation may perform a persistent write. It is not a generic danger marker.",
    ))


def flash_diagnostics(state: ds.DeviceState) -> bool:
    print_state_header(state)
    print()
    # Raw machine state belongs in the session log, not in the operator UI.
    proven._write_session_only("[DEVICESTATE-RAW]\n" + json.dumps(state.to_dict(), ensure_ascii=False, indent=2))
    layout = terms.human(state.current_layout, "layout")
    nand_parts = [terms.human(state.nand_vendor, "identity"), terms.human(state.nand_model, "identity")]
    nand_text = " / ".join(x for x in nand_parts if x != terms.human("UNKNOWN", "identity")) or terms.human("UNKNOWN", "identity")
    if state.nand_capacity:
        nand_text += f" · {state.nand_capacity // (1024 * 1024)} MiB"
    if state.nand_erase_size:
        nand_text += f" · erase {state.nand_erase_size // 1024} KiB"
    print(tr("Разметка: ", "Layout: ") + layout)
    print(tr("Flash-память: ", "Flash memory: ") + nand_text)
    ui.note(tr("Машинные значения DeviceState записаны в лог сеанса.", "Raw DeviceState values were written to the session log."))
    if state.probe_status != ds.PROBE_COMPLETE:
        print(tr(
            "\nСетевая проверка состояния неполна. Для не загружающегося роутера можно отдельно проверить UBI/BL2 через USB-UART только для чтения; NAND/UBI не изменяются.",
            "\nNetwork state check is incomplete. For a brick, a separate read-only UBI/BL2 check can be run over USB-UART; NAND/UBI are not modified.",
        ))
        ans = input(tr("Запустить проверку через USB-UART только для чтения? [y/N]: ", "Run the read-only UART check? [y/N]: ")).strip().lower()
        if ans in ("y", "yes", "д", "да"):
            ursusboot_update.uart_bootrom_forensics()
            return True
    return False


def run_action(fn, *, write_may_happen: bool = False) -> None:
    try:
        fn()
    except KeyboardInterrupt:
        print(); ui.status(tr("СТОП", "STOP"), tr("Остановлено пользователем.", "Stopped by user."))
        if write_may_happen:
            ui.status(tr("ВНИМАНИЕ", "WARNING"), tr("Если запись уже началась — не выключайте роутер. Сохраните окно и лог.",
                     "If a write has already started, do not power the router off. Save the window and log."))
    except Exception as exc:
        print(); ui.status(tr("ОШИБКА", "ERROR"), tr("Операция не завершена.", "The operation did not complete."), stream=sys.stderr)
        if write_may_happen:
            ui.status(tr("ВНИМАНИЕ", "WARNING"), tr("Если запись уже началась — не выключайте питание до уточнения состояния.",
                     "If writing has already started, do not remove power until the state is known."), stream=sys.stderr)
        proven._write_session_only("[TECH] " + repr(exc))
        ui.note(tr("Технические подробности записаны в лог сеанса.", "Technical details were written to the session log."))
    finally:
        print()
        ui.prompt(tr("Нажмите Enter, чтобы вернуться в меню EXPERT...", "Press Enter to return to the EXPERT menu..."))


def _show_action(number: int, app: dict[int, ds.ActionApplicability], detail_ru: str = "", detail_en: str = "") -> None:
    a = app[number]
    detail = tr(detail_ru, detail_en) if detail_ru or detail_en else ""
    if a.enabled and a.note:
        detail = (detail + " — " if detail else "") + a.note
    ui.menu_item(
        number, terms.action_title(a.key), detail or None,
        write_capable=a.write_capable, enabled=a.enabled,
        reason=a.reason if not a.enabled else "",
    )


def main() -> int:
    proven.start_session_logging()
    ui.enable()
    one_key.choose_language()

    root = HERE.parent
    version = ui.package_version(root)
    host = os.environ.get("NOKIA_ROUTER_IP", "192.168.1.1").strip() or "192.168.1.1"
    while True:
        state = ds.probe_device_state(host)
        app = ds.action_applicability(state)

        ui.banner("UrsusFlasher EXPERT", version=version)

        ui.section(tr("Установить", "Install"))
        _show_action(1, app, "полный сценарий: резервная копия → UrsusBoot → OpenWrt",
                     "full production workflow: backup → UrsusBoot → OpenWrt")
        _show_action(2, app, terms.human(app[2].resolved_backend, "method"),
                     terms.human(app[2].resolved_backend, "method"))
        _show_action(3, app)
        _show_action(4, app)

        ui.section(tr("Если роутер не загружается", "If the router does not boot"), style="amber2")
        _show_action(5, app, "понадобится USB-UART", "USB-UART is required")
        _show_action(6, app)

        ui.section(tr("Резервные копии", "Backups"), style="ok")
        _show_action(7, app, "только чтение; точная копия OpenWrt создаётся из среды восстановления в оперативной памяти",
                     "read-only; exact OpenWrt backup uses quiescent RAM/BootROM")
        _show_action(8, app)
        _show_action(9, app)

        ui.section(tr("Посмотреть", "Inspect"), style="amber2")
        _show_action(10, app)
        _show_action(11, app)
        _show_action(12, app)

        print()
        ui.menu_item(0, tr("Выход", "Exit"))
        ui.note(tr("! — операция может выполнять запись во flash-память (NAND)", "! — operation may modify flash/NAND"))
        ui.rule(style="amber")

        c = ask_menu(12)
        if c == "0":
            return 0
        number = int(c)
        selected = app[number]
        if not selected.enabled:
            print()
            ui.status(tr("СТОП", "STOP"), selected.reason or tr("Действие сейчас неприменимо.", "This action is not currently applicable."))
            ui.prompt(tr("Нажмите Enter, чтобы вернуться в меню EXPERT...", "Press Enter to return to the EXPERT menu..."))
            continue

        if number == 1:
            run_action(one_key.main, write_may_happen=True)
        elif number == 2:
            network_guidance.show()
            fresh_state = ds.probe_device_state(host)
            fresh_action = ds.action_applicability(fresh_state)[2]
            if not fresh_action.enabled:
                ui.status(tr("СТОП", "STOP"), fresh_action.reason or tr("Действие сейчас неприменимо.", "This action is not currently applicable."))
                ui.prompt(tr("Нажмите Enter, чтобы вернуться в меню EXPERT...", "Press Enter to return to the EXPERT menu..."))
                continue
            ui.section(tr("Разрешённое действие", "Resolved action"), style="amber2")
            print("  " + tr("Действие: Установить или переустановить загрузчик", "Action: Install or repair the bootloader"))
            print("  " + tr("Метод: ", "Method: ") + terms.human(fresh_action.resolved_backend, "method"))
            if fresh_state.current_system.startswith("OPENWRT"):
                print("  " + tr("Среда выполнения: ", "Execution root: ") + terms.human(fresh_state.execution_environment, "execution_environment"))
            run_action(lambda: ursusboot_install.run_install(host=host), write_may_happen=True)
        elif number == 3:
            network_guidance.show()
            run_action(ursusboot_update.web_fit_update, write_may_happen=True)
        elif number == 4:
            network_guidance.show()
            run_action(update_bootloader_network, write_may_happen=True)
        elif number == 5:
            network_guidance.show()
            if confirm_uart_recovery(
                "Airoha BootROM запустит среду восстановления из оперативной памяти; механизм записи остаётся прежним до отдельной переработки транзакционной модели.",
                "Airoha BootROM will start recovery from RAM; the destructive backend remains unchanged until the transaction refactor.",
            ):
                run_action(ursusboot_update.uart_bootrom_recover, write_may_happen=True)
        elif number == 7:
            run_action(lambda: full_backup_readonly(state))
        elif number == 8:
            run_action(validate_backup)
        elif number == 10:
            run_action(lambda: capability_report(state))
        elif number == 11:
            try:
                flash_diagnostics(state)
            except Exception as exc:
                print(); ui.status(tr("ОШИБКА", "ERROR"), str(exc))
            finally:
                print(); ui.prompt(tr("Нажмите Enter, чтобы вернуться в меню EXPERT...", "Press Enter to return to the EXPERT menu..."))
        elif number == 12:
            run_action(ursusboot_update.show_info)


if __name__ == "__main__":
    raise SystemExit(main())

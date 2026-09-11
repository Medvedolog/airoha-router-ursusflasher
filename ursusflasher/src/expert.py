#!/usr/bin/env python3
from __future__ import annotations

import getpass
import json
import os
import shlex
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import board_profiles as bp
import console_ui as ui
import device_state as ds
import one_key
import proven_backend as proven
import stock_web
import ui_terms as terms
import network_guidance
import stock_restore
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
    # Never launch a second writer merely because a UI/transport exception was
    # raised after a flash transaction.  HTTP upload has its own bounded retry
    # logic; TFTP remains an explicit recovery transport only.
    ursusboot_update.web_fip_update()


def _bootloader_menu_detail(state: ds.DeviceState, action: ds.ActionApplicability) -> str:
    if state.current_system == "RECOVERY":
        return tr(
            "UrsusBoot Recovery: HTTP → обновление FIP с сетевыми ретраями; TFTP только отдельным ручным recovery-путём",
            "UrsusBoot Recovery: HTTP → FIP update with network retries; TFTP is a separate explicit recovery path",
        )
    if state.current_system.startswith("OPENWRT"):
        return tr(
            "OpenWrt: SSH → резервная копия FIP/boot block → запись → обратная проверка",
            "OpenWrt: SSH → FIP/boot-block backup → write → readback verification",
        )
    if state.current_system == "NOKIA_STOCK":
        return tr(
            "Nokia STOCK: Web/Telnet → установка UrsusBoot → проверка записи",
            "Nokia STOCK: Web/Telnet → UrsusBoot install → write verification",
        )
    return tr(
        "Текущая среда проверяется при запуске; подходящий транспорт выбирается автоматически",
        "The current environment is checked on start; the transport is selected automatically",
    )


def _custom_openwrt_menu_detail(state: ds.DeviceState, action: ds.ActionApplicability) -> str:
    if action.resolved_backend == "SSH_PERSISTENT_OPENWRT_SYSUPGRADE":
        return tr(
            "Установленная OpenWrt: SSH → передача образа → sysupgrade -T → sysupgrade",
            "Installed OpenWrt: SSH → image upload → sysupgrade -T → sysupgrade",
        )
    if action.resolved_backend == "URSUSBOOT_RECOVERY_CUSTOM_IMAGE":
        return tr(
            "UrsusBoot Recovery: HTTP → проверка образа → запись OpenWrt",
            "UrsusBoot Recovery: HTTP → image validation → OpenWrt flash",
        )
    return tr(
        "Доступно из установленной OpenWrt или UrsusBoot Recovery",
        "Available from installed OpenWrt or UrsusBoot Recovery",
    )


def _choose_sysupgrade_any() -> Path:
    prompt = tr(
        "Путь к пользовательскому sysupgrade (.bin/.itb); Enter — открыть окно выбора: ",
        "Path to custom sysupgrade (.bin/.itb); press Enter to open file picker: ",
    )
    raw = input(prompt).strip().strip('"')
    if not raw:
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk(); root.withdraw(); root.update()
            raw = filedialog.askopenfilename(
                title=tr("Выберите sysupgrade OpenWrt", "Select OpenWrt sysupgrade image"),
                filetypes=[("OpenWrt sysupgrade", "*.bin *.itb"), ("All files", "*.*")],
            )
            root.destroy()
        except Exception:
            raw = input(tr("Введите путь к sysupgrade: ", "Enter sysupgrade path: ")).strip().strip('"')
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError(tr(f"Файл sysupgrade не найден: {path}", f"Sysupgrade image not found: {path}"))
    size = path.stat().st_size
    if size < 1024 * 1024 or size > 128 * 1024 * 1024:
        raise RuntimeError(tr(f"Неожиданный размер sysupgrade: {size} байт", f"Unexpected sysupgrade size: {size} bytes"))
    return path


def custom_openwrt_running(host: str) -> None:
    proven.ensure_root_ssh_session(host)
    image = _choose_sysupgrade_any()
    digest = proven.sha_file(image)
    remote = "/tmp/ursus-custom-sysupgrade"
    print(tr(
        f"[ОБРАЗ] {image.name} · {image.stat().st_size / 1048576:.1f} MiB · SHA256 {digest}",
        f"[IMAGE] {image.name} · {image.stat().st_size / 1048576:.1f} MiB · SHA256 {digest}",
    ))
    proven.ssh_write_binary(host, image, remote, timeout=1800)
    quoted = shlex.quote(remote)
    rc, out = proven.ssh_run(
        host,
        f"command -v sysupgrade >/dev/null 2>&1 || exit 40; "
        f"[ \"$(sha256sum {quoted} | awk '{{print $1}}')\" = {shlex.quote(digest)} ] || exit 41; "
        f"sysupgrade -T {quoted}",
        timeout=300, quiet=False, batch_mode=True,
    )
    if rc != 0:
        raise RuntimeError(tr("sysupgrade -T отклонил образ", "sysupgrade -T rejected the image"))
    print(tr(
        "[ГОТОВО] Образ принят штатной проверкой sysupgrade -T. Запись ещё не начиналась.",
        "[READY] The image passed the native sysupgrade -T check. Writing has not started yet.",
    ))
    ui.rule(tr("РАЗРЕШЁННОЕ ДЕЙСТВИЕ", "RESOLVED ACTION"), style="amber2")
    print("  " + tr("Действие: записать пользовательскую прошивку OpenWrt", "Action: flash a custom OpenWrt image"))
    print("  " + tr("Метод: SSH → /tmp → sysupgrade -T → sysupgrade -v -n", "Method: SSH → /tmp → sysupgrade -T → sysupgrade -v -n"))
    print("  " + tr("Настройки текущей прошивки не переносятся.", "Current firmware settings will not be preserved."))
    ans = ui.prompt(tr("Начать запись? [д/Н]: ", "Start flashing? [y/N]: ")).strip().lower()
    if ans not in ("д", "да", "y", "yes"):
        ui.status(tr("СТОП", "STOP"), tr("Запись отменена; flash-память не изменялась.", "Flashing cancelled; flash memory was not modified."))
        return
    rc, out = proven.ssh_run(
        host,
        f"echo __URSUS_SYSUPGRADE_START__; sync; exec sysupgrade -v -n {quoted}",
        timeout=900, allow_disconnect=True, quiet=False, batch_mode=True,
    )
    if "__URSUS_SYSUPGRADE_START__" not in out:
        raise RuntimeError(tr("Не получен маркер запуска sysupgrade", "Sysupgrade start marker was not received"))
    print(tr(
        "[ГОТОВО] sysupgrade запущен. Соединение SSH может оборваться во время перезагрузки — это нормально.",
        "[READY] sysupgrade started. SSH may disconnect during reboot; this is expected.",
    ))


def run_bootloader_install_or_update(host: str, state: ds.DeviceState) -> None:
    """Route item 2 only from positively identified current state.

    Telnet availability is not evidence of Nokia STOCK: third-party OpenWrt
    builds may expose both SSH and Telnet.  EXPERT therefore passes an explicit
    route to the installer after its interactive read-only preflight.
    """
    if state.current_system == "RECOVERY":
        update_bootloader_network()
        return
    if state.current_system.startswith("OPENWRT"):
        ursusboot_install.run_install(host=host, route="openwrt")
        return
    if state.current_system == "NOKIA_STOCK":
        ursusboot_install.run_install(host=host, route="stock")
        return
    raise RuntimeError(tr(
        "Не удалось однозначно определить текущую систему; установка UrsusBoot остановлена без попытки stock Web/Telnet.",
        "The current system could not be identified unambiguously; UrsusBoot installation stopped without trying stock Web/Telnet.",
    ))


def run_custom_openwrt(host: str, state: ds.DeviceState, action: ds.ActionApplicability) -> None:
    if action.resolved_backend == "SSH_PERSISTENT_OPENWRT_SYSUPGRADE":
        custom_openwrt_running(host)
        return
    if action.resolved_backend == "URSUSBOOT_RECOVERY_CUSTOM_IMAGE":
        ursusboot_update.web_fit_update()
        return
    raise RuntimeError(tr(
        "Не удалось определить безопасный способ записи пользовательской OpenWrt.",
        "No safe custom OpenWrt flashing method could be resolved.",
    ))


def _tcp_open(host: str, port: int, timeout: float = 1.0) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def _readonly_stock_access(host: str, *, expected_family: str | None = None) -> proven.StockAccess:
    """Authenticate to stock Web without enabling services or changing settings.

    The family is re-read from device_status.cgi and resolved through the same
    BOARD_PROFILES catalog as DeviceState.  This deliberately reuses the
    MedveFlasher-derived family-aware backup backend instead of authorizing a
    writer from the passive menu probe.
    """
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
        info = setup.read_device_info()
        match = bp.match_profile(
            model=str(info.get("model") or ""),
            soc=str(info.get("chipset") or ""),
        )
        if not match:
            raise stock_web.UnsupportedModel(
                tr(
                    f"неподдерживаемая или противоречивая пара model/SoC: {info.get('model') or 'unknown'} / {info.get('chipset') or 'unknown'}",
                    f"unsupported or conflicting model/SoC pair: {info.get('model') or 'unknown'} / {info.get('chipset') or 'unknown'}",
                )
            )
        family, profile = match
        if expected_family and family != expected_family:
            raise stock_web.UnsupportedModel(
                tr(
                    f"семья устройства изменилась между preflight и backup: ожидалась {expected_family.upper()}, получена {family.upper()}",
                    f"device family changed between preflight and backup: expected {expected_family.upper()}, got {family.upper()}",
                )
            )
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
            model_verification_source="stock-web-device_status.cgi-readonly-board-profile",
            family=family,
            model_name=str(profile.get("model") or info.get("model") or "UNKNOWN"),
            chipset=str(profile.get("soc") or info.get("chipset") or "UNKNOWN"),
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


def backup_stock_readonly(host: str, *, expected_family: str | None = None) -> None:
    access = None
    try:
        access = _readonly_stock_access(host, expected_family=expected_family)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        default_dest = Path(proven.WORK) / "backups" / f"stock-{access.family}-full-readonly-{stamp}"
        raw = input(tr(f"Каталог для полной копии [{default_dest}]: ",
                       f"Full backup directory [{default_dest}]: ")).strip().strip('"')
        destination = Path(raw).expanduser() if raw else default_dest
        print(tr(
            f"[ШАГ] Снимаю mtd0..mtd16 для {access.family.upper()}. Службы Telnet/FTP/Samba не включаются, NAND не изменяется.",
            f"[STEP] Capturing mtd0..mtd16 for {access.family.upper()}. Service provisioning is forbidden: Telnet/FTP/Samba are not enabled and NAND is not modified.",
        ))
        proven.backup_tftp(
            access, access.host, destination, expected_family=access.family,
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
            match = bp.match_profile(model=state.model, soc=state.soc)
            if not match:
                raise RuntimeError(tr(
                    "DeviceState не содержит подтверждённый board profile для stock backup.",
                    "DeviceState does not contain a confirmed board profile for stock backup.",
                ))
            backup_stock_readonly(state.host, expected_family=match[0])
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
    proven.bootrom_backup_wizard(
        source_system=state.current_system,
        source_layout=state.current_layout,
    )


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
    raw_meta = path / "RAW_BACKUP.json"
    if raw_meta.is_file():
        result = proven.verify_raw_bootrom_backup(path)
        print(tr("[ГОТОВО] BACKUP_STATUS=VERIFIED_EXACT_RAW", "[READY] BACKUP_STATUS=VERIFIED_EXACT_RAW"))
        print(f"layout={result.get('source_layout')} all_flash_sha256={result.get('all_flash_sha256')}")
        return
    result = proven.verify_stock_restore_backup(path)
    print(tr("[ГОТОВО] BACKUP_STATUS=RESTORE_READY", "[READY] BACKUP_STATUS=RESTORE_READY"))
    print(f"family={result.get('stock_family')} variant={result.get('stock_variant')}")
    stock = result.get("stock_restore", {})
    if stock:
        print(f"all_flash_sha256={stock.get('all_flash_sha256')}")


def _interactive_diagnostic_state(state: ds.DeviceState) -> ds.DeviceState:
    """Upgrade an operator-requested diagnostic probe without changing the router.

    The menu probe is deliberately non-interactive.  Once the operator selects
    diagnostics/backup, a single system-OpenSSH command may ask for the root
    password and read board/layout information.  No temporary key is installed
    and no router file is modified.
    """
    if state.probe_status == ds.PROBE_COMPLETE:
        return state
    if not state.access.get("ssh"):
        return state
    ui.status(tr("ДИАГНОСТИКА", "DIAGNOSTICS"), tr(
        "Для полной проверки сейчас будет выполнен read-only вход root по SSH. Если задан пароль, его запросит системный OpenSSH; UrsusFlasher пароль не сохраняет.",
        "A read-only root SSH login will now be used to complete diagnostics. If a password is set, system OpenSSH will ask for it; UrsusFlasher does not store it.",
    ))
    fresh = ds.probe_device_state(state.host, interactive_ssh=True)
    if fresh.access.get("root") is True:
        ui.status(tr("ГОТОВО", "READY"), tr(
            "Root SSH подтверждён; сведения о системе и разметке обновлены.",
            "Root SSH confirmed; system and layout information was refreshed.",
        ))
    else:
        proven._write_session_only("[INTERACTIVE-DIAGNOSTIC] root SSH was not confirmed")
    return fresh


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
    for number in ds.visible_action_numbers():
        a = app[number]
        title = terms.action_title(a.key)
        yes = tr("ДА", "YES") if a.enabled else tr("НЕТ", "NO")
        marker = "!" if a.write_capable else " "
        print(f" {marker} {number:2d}  {title:<42} {yes}")
        detail_ru, detail_en = _menu_detail(number, state, app)
        detail = tr(detail_ru, detail_en)
        if detail:
            print(f"       {detail}")
        if not a.enabled and a.reason:
            print(f"       {a.reason}")
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


def _operator_error_cause(exc: Exception) -> str:
    """Return one short operator-useful cause line without replacing the full log."""
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    if not lines:
        return exc.__class__.__name__
    skip_exact = {"Последний вывод SSH:", "Last SSH output:"}
    for line in reversed(lines):
        if line in skip_exact:
            continue
        if line.startswith("SSH-команда завершилась с кодом "):
            continue
        if line.startswith("бинарная SSH-команда завершилась с кодом "):
            continue
        if len(line) > 500:
            line = line[-500:]
        return line
    return lines[-1][-500:]


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
        cause = _operator_error_cause(exc)
        ui.status(tr("ПРИЧИНА", "CAUSE"), cause, stream=sys.stderr)
        ui.note(tr("Полные технические подробности записаны в лог сеанса.", "Full technical details were written to the session log."))
    finally:
        print()
        ui.prompt(tr("Нажмите Enter, чтобы вернуться в меню EXPERT...", "Press Enter to return to the EXPERT menu..."))


def _show_action(number: int, app: dict[int, ds.ActionApplicability], detail_ru: str = "", detail_en: str = "") -> None:
    a = app[number]
    detail = tr(detail_ru, detail_en) if detail_ru or detail_en else ""
    ui.menu_item(
        number, terms.action_title(a.key), detail or None,
        write_capable=a.write_capable, enabled=a.enabled,
        reason=a.reason if not a.enabled else "",
    )
    if a.enabled and a.note:
        print(f"       {ui.paint(a.note, 'dim')}")


def _menu_detail(number: int, state: ds.DeviceState, app: dict[int, ds.ActionApplicability]) -> tuple[str, str]:
    if number in app and not app[number].enabled:
        return "", ""
    if number == 1:
        return (
            "Полный переход: резервная копия → UrsusBoot → комплектная OpenWrt; транспорт выбирается по текущей системе",
            "Full workflow: backup → UrsusBoot → bundled OpenWrt; transport follows the current system",
        )
    if number == 2:
        text = _bootloader_menu_detail(state, app[2])
        return text, text
    if number == 3:
        text = _custom_openwrt_menu_detail(state, app[3])
        return text, text
    if number == 5:
        return (
            "USB-UART → Airoha BootROM → UrsusBoot из RAM → запись и проверка загрузчика",
            "USB-UART → Airoha BootROM → UrsusBoot from RAM → bootloader write and verification",
        )
    if number == 6:
        return (
            "Проверенный stock backup: автоматически без UART через U-Boot+RAM initramfs при доступной OpenWrt/recovery; иначе BootROM/XMODEM",
            "Validated stock backup: automatically without UART through U-Boot+RAM initramfs when OpenWrt/recovery is available; otherwise BootROM/XMODEM",
        )
    if number == 7:
        return (
            "BootROM/USB-UART → среда в RAM → чтение NAND → копия на ПК; flash не изменяется",
            "BootROM/USB-UART → RAM environment → NAND read → PC backup; flash is not modified",
        )
    if number == 8:
        return (
            "Проверка на ПК: структура, размеры и SHA256; роутер не изменяется",
            "PC-side validation: structure, sizes and SHA256; the router is not modified",
        )
    if number == 9:
        return (
            "Сборка аварийного комплекта из проверенной резервной копии; пока не реализовано",
            "Build a rescue kit from a validated backup; not implemented yet",
        )
    if number == 10:
        return (
            "Пассивная диагностика Web/SSH: система, разметка, загрузчик и применимые операции",
            "Passive Web/SSH diagnostics: system, layout, bootloader and applicable actions",
        )
    if number == 11:
        return (
            "Web/SSH, при необходимости USB-UART: разметка, NAND и bad blocks; только чтение",
            "Web/SSH, USB-UART when needed: layout, NAND and bad blocks; read-only",
        )
    if number == 12:
        return (
            "Локальная проверка SHA256 и состава файлов публичного комплекта",
            "Local SHA256 and package-content verification",
        )
    return "", ""


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
        for number in (1, 2, 3):
            detail_ru, detail_en = _menu_detail(number, state, app)
            _show_action(number, app, detail_ru, detail_en)

        ui.section(tr("Если роутер не загружается", "If the router does not boot"), style="amber2")
        for number in (5, 6):
            detail_ru, detail_en = _menu_detail(number, state, app)
            _show_action(number, app, detail_ru, detail_en)

        ui.section(tr("Резервные копии", "Backups"), style="ok")
        for number in (7, 8, 9):
            detail_ru, detail_en = _menu_detail(number, state, app)
            _show_action(number, app, detail_ru, detail_en)

        ui.section(tr("Посмотреть", "Inspect"), style="amber2")
        for number in (10, 11, 12):
            detail_ru, detail_en = _menu_detail(number, state, app)
            _show_action(number, app, detail_ru, detail_en)

        print()
        ui.menu_item(0, tr("Выход", "Exit"))
        ui.note(tr("! — операция может выполнять запись во flash-память (NAND)", "! — operation may modify flash/NAND"))
        ui.rule(style="amber")

        c = ask_menu(12)
        if c == "0":
            return 0
        number = int(c)
        if number == 4:
            ui.note(tr(
                "Пункт 4 объединён с пунктом 2: установка и обновление UrsusBoot теперь используют один автоматический сценарий.",
                "Item 4 was merged into item 2: UrsusBoot install and update now use one automatic workflow.",
            ))
            number = 2
        selected = app[number]
        if not selected.enabled:
            print()
            ui.status(tr("СТОП", "STOP"), selected.reason or tr("Действие сейчас неприменимо.", "This action is not currently applicable."))
            ui.prompt(tr("Нажмите Enter, чтобы вернуться в меню EXPERT...", "Press Enter to return to the EXPERT menu..."))
            continue

        if number == 1:
            skip_backup = False
            if state.current_system == "NOKIA_STOCK":
                ans = ui.prompt(tr(
                    "EXPERT: пропустить полный backup mtd0..mtd16 для этого запуска? [y/N]: ",
                    "EXPERT: skip the full mtd0..mtd16 backup for this run? [y/N]: ",
                )).strip().lower()
                skip_backup = ans in ("y", "yes", "д", "да")
            run_action(lambda: one_key.main(skip_full_backup=skip_backup), write_may_happen=True)
        elif number == 2:
            network_guidance.show()
            # Item 2 is an explicit operator request, so raise the passive menu
            # probe to an interactive read-only SSH preflight when needed.
            # This may ask for the root password, but does not write the router.
            fresh_state = _interactive_diagnostic_state(ds.probe_device_state(host))
            fresh_action = ds.action_applicability(fresh_state)[2]
            if not fresh_action.enabled:
                ui.status(tr("СТОП", "STOP"), fresh_action.reason or tr("Действие сейчас неприменимо.", "This action is not currently applicable."))
                ui.prompt(tr("Нажмите Enter, чтобы вернуться в меню EXPERT...", "Press Enter to return to the EXPERT menu..."))
                continue
            ui.section(tr("Разрешённое действие", "Resolved action"), style="amber2")
            print("  " + tr("Действие: установить или обновить UrsusBoot", "Action: install or update UrsusBoot"))
            print("  " + tr("Метод: ", "Method: ") + _bootloader_menu_detail(fresh_state, fresh_action))
            if fresh_state.current_system.startswith("OPENWRT"):
                print("  " + tr("Среда выполнения: ", "Execution root: ") + terms.human(fresh_state.execution_environment, "execution_environment"))
            run_action(lambda: run_bootloader_install_or_update(host, fresh_state), write_may_happen=True)
        elif number == 3:
            network_guidance.show()
            fresh_state = ds.probe_device_state(host)
            fresh_action = ds.action_applicability(fresh_state)[3]
            if not fresh_action.enabled:
                ui.status(tr("СТОП", "STOP"), fresh_action.reason or tr("Действие сейчас неприменимо.", "This action is not currently applicable."))
                ui.prompt(tr("Нажмите Enter, чтобы вернуться в меню EXPERT...", "Press Enter to return to the EXPERT menu..."))
                continue
            run_action(lambda: run_custom_openwrt(host, fresh_state, fresh_action), write_may_happen=True)
        elif number == 5:
            network_guidance.show()
            if confirm_uart_recovery(
                "Airoha BootROM запустит среду восстановления из оперативной памяти; механизм записи остаётся прежним до отдельной переработки транзакционной модели.",
                "Airoha BootROM will start recovery from RAM; the destructive backend remains unchanged until the transaction refactor.",
            ):
                run_action(ursusboot_update.uart_bootrom_recover, write_may_happen=True)
        elif number == 6:
            network_guidance.show()
            # Restore owns its single destructive y/N at the latest safe point:
            # before one-shot persistent bootcmd on the no-UART route, or after
            # RECOVERY_SAFE + geometry + TFTP preflight on the UART route.
            run_action(lambda: stock_restore.restore_nokia(_interactive_diagnostic_state(state)), write_may_happen=True)
        elif number == 7:
            run_action(lambda: full_backup_readonly(_interactive_diagnostic_state(state)))
        elif number == 8:
            run_action(validate_backup)
        elif number == 10:
            run_action(lambda: capability_report(_interactive_diagnostic_state(state)))
        elif number == 11:
            try:
                flash_diagnostics(_interactive_diagnostic_state(state))
            except Exception as exc:
                print(); ui.status(tr("ОШИБКА", "ERROR"), str(exc))
            finally:
                print(); ui.prompt(tr("Нажмите Enter, чтобы вернуться в меню EXPERT...", "Press Enter to return to the EXPERT menu..."))
        elif number == 12:
            run_action(ursusboot_update.show_info)


if __name__ == "__main__":
    raise SystemExit(main())

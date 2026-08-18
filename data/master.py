#!/usr/bin/env python3
from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import socket
import sys
import time
from pathlib import Path

import proven_backend as proven
import stock_web
from fit_fdt import FdtError, SysupgradeInfo, analyze_sysupgrade
from tcboot_builder import EXPECTED_ORIG as TCBOOT_ORIGINAL_SHA256, TCBOOT_SIZE, build_tcboot

APP_VERSION = "0.1.0-md-lab1fix10"
BUILD_TAG = "ursusflasher-0.1.0-md-lab1fix10"
KIT = Path(__file__).resolve().parent.parent
DATA = KIT / "data"
WORK = KIT / "work"
TCBOOT_PAYLOAD_DIR = DATA / "payloads" / "md" / "tcboot"
TCBOOT_ORIGINAL = TCBOOT_PAYLOAD_DIR / "tcboot-original.bin"
DEFAULT_SYSUPGRADE = KIT / "fw" / "openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb"
DEFAULT_HOST = "192.168.1.1"

_LANG = "ru"

_RAW_PRINT = print
_RAW_INPUT = input
_UI_COLOR = False


def _ui_init_color() -> None:
    global _UI_COLOR
    try:
        proven._enable_windows_ansi()
    except Exception:
        pass
    _UI_COLOR = bool(getattr(sys.stdout, "isatty", lambda: False)()) and not os.environ.get("NO_COLOR")
    try:
        proven._COLOR_ENABLED = _UI_COLOR
    except Exception:
        pass


def _ansi(text: str, code: str) -> str:
    if not _UI_COLOR or not text:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def _ui_colorize(line: str) -> str:
    if not _UI_COLOR or "\x1b[" in line:
        return line
    stripped = line.lstrip()
    lead = line[:len(line)-len(stripped)]
    upper = stripped.upper()
    status_codes = (
        ("[ERROR]", "1;31"), ("[FAIL]", "1;31"), ("[СТОП]", "1;31"),
        ("[WARNING]", "1;33"), ("[ПРЕДУПРЕЖДЕНИЕ]", "1;33"),
        ("[OK]", "1;32"), ("[SUCCESS]", "1;32"),
        ("[WAIT]", "1;34"), ("[INFO]", "1;36"),
        ("[BUILD]", "1;36"), ("[RUNTIME]", "36"), ("[LOG]", "36"),
    )
    for prefix, code in status_codes:
        if upper.startswith(prefix):
            return lead + _ansi(stripped, code)
    m = re.match(r"^(\d+)(\.\s+)(.*)$", stripped)
    if m:
        number, sep, text = m.groups()
        text_code = "1;35" if ("ЭКСПЕРТ" in text.upper() or "EXPERT" in text.upper()) else "1;36"
        return lead + _ansi(number, "1;33") + _ansi(sep, "2;37") + _ansi(text, text_code)
    if stripped.startswith("0. "):
        return lead + _ansi("0", "1;33") + _ansi(stripped[1:], "2;37")
    if stripped.startswith("==="):
        return lead + _ansi(stripped, "1;36")
    return line


def print(*args, **kwargs):
    target = kwargs.get("file")
    if target is not None and target not in (sys.stdout, sys.stderr):
        return _RAW_PRINT(*args, **kwargs)
    sep = kwargs.pop("sep", " ")
    end = kwargs.pop("end", "\n")
    sep = " " if sep is None else sep
    end = "\n" if end is None else end
    rendered = sep.join(str(arg) for arg in args)
    lines = rendered.split("\n")
    rendered = "\n".join(_ui_colorize(line) for line in lines)
    return _RAW_PRINT(rendered, end=end, **kwargs)


def input(prompt: str = "") -> str:
    if prompt == "> ":
        prompt = _ansi("> ", "1;35")
    elif prompt:
        prompt = _ansi(prompt, "1;35")
    return _RAW_INPUT(prompt)


def _flush_pending_console_input() -> None:
    """Discard keystrokes queued before a safety-critical prompt.

    This is deliberately limited to an interactive TTY/console.  It prevents a
    stale Enter pressed during a long network operation from being consumed by
    the later destructive confirmation prompt.
    """
    try:
        if not getattr(sys.stdin, "isatty", lambda: False)():
            return
        if os.name == "nt":
            import msvcrt
            while msvcrt.kbhit():
                msvcrt.getwch()
            return
        import termios
        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except Exception:
        # Failure to flush must never authorize nor cancel a destructive step.
        pass


def _confirm_tcboot_write(expert: bool) -> None:
    phrase = "EXPERT FLASH TCBOOT MD" if expert else "FLASH TCBOOT MD"
    _flush_pending_console_input()
    while True:
        entered = input(tr(
            f"Введите точно {phrase} (0 = отмена): ",
            f"Type exactly {phrase} (0 = cancel): ",
        )).strip()
        if entered == phrase:
            return
        if entered.upper() in {"0", "CANCEL", "ОТМЕНА"}:
            raise UrsusError(tr("Операция отменена оператором.", "Operation cancelled by the operator."))
        if entered == "":
            print(tr(
                "[INFO] Пустой ввод проигнорирован; NAND не изменён. Введите подтверждение или 0 для отмены.",
                "[INFO] Empty input ignored; NAND is unchanged. Enter the confirmation or 0 to cancel.",
            ))
            continue
        print(tr(
            "[WARNING] Подтверждение не совпало; NAND не изменён. Повторите ввод или введите 0 для отмены.",
            "[WARNING] Confirmation did not match; NAND is unchanged. Try again or enter 0 to cancel.",
        ))


class UrsusError(RuntimeError):
    pass


def choose_language() -> str:
    global _LANG
    print("UrsusFlasher")
    print()
    print("1. Русский")
    print("2. English")
    while True:
        value = input("> ").strip().lower()
        if value in ("1", "ru", "rus", "рус", "русский"):
            _LANG = "ru"
            break
        if value in ("2", "en", "eng", "english"):
            _LANG = "en"
            break
        print("Неверный выбор / Invalid selection")
    os.environ["NOKIA_LANG"] = _LANG
    proven._LANG = _LANG
    return _LANG


def tr(ru: str, en: str) -> str:
    return en if _LANG == "en" else ru


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_tcboot_inputs() -> None:
    if not TCBOOT_ORIGINAL.is_file():
        raise UrsusError(tr("Не найден базовый tcboot-original.bin.", "Base tcboot-original.bin is missing."))
    size = TCBOOT_ORIGINAL.stat().st_size
    digest = sha256_file(TCBOOT_ORIGINAL)
    if size != TCBOOT_SIZE or digest != TCBOOT_ORIGINAL_SHA256:
        raise UrsusError(tr(
            f"Базовый tcboot не прошёл pin-check: size={size}, sha256={digest}",
            f"Base tcboot failed the pin check: size={size}, sha256={digest}",
        ))
    if not DEFAULT_SYSUPGRADE.is_file():
        raise UrsusError(tr(
            f"Комплектный sysupgrade отсутствует: {DEFAULT_SYSUPGRADE}",
            f"Bundled sysupgrade is missing: {DEFAULT_SYSUPGRADE}",
        ))


def _select_sysupgrade() -> tuple[SysupgradeInfo, Path, str]:
    print()
    print(tr("=== Выбор OpenWrt sysupgrade ===", "=== Select OpenWrt sysupgrade ==="))
    print(tr(
        f"Комплектный файл: {DEFAULT_SYSUPGRADE.relative_to(KIT)}",
        f"Bundled image: {DEFAULT_SYSUPGRADE.relative_to(KIT)}",
    ))
    raw = input(tr(
        "Путь к .itb [Enter = комплектный fw/]: ",
        "Path to .itb [Enter = bundled fw/ image]: ",
    )).strip().strip('"')
    image = Path(raw).expanduser() if raw else DEFAULT_SYSUPGRADE
    if not image.is_absolute():
        image = (Path.cwd() / image).resolve()
    try:
        info = analyze_sysupgrade(image)
    except (OSError, FdtError, ValueError) as exc:
        raise UrsusError(tr(f"sysupgrade/FDT preflight отклонён: {exc}", f"sysupgrade/FDT preflight rejected: {exc}")) from exc

    print(tr(f"[OK] FIT profile: {info.description}", f"[OK] FIT profile: {info.description}"))
    print(tr(
        f"[OK] default={info.config_name}; kernel={info.kernel_name}; fdt={info.fdt_name}; rootfs={info.rootfs_name}",
        f"[OK] default={info.config_name}; kernel={info.kernel_name}; fdt={info.fdt_name}; rootfs={info.rootfs_name}",
    ))
    print(tr(f"[OK] Все FIT image hashes проверены: {', '.join(info.verified_hashes)}",
             f"[OK] All FIT image hashes verified: {', '.join(info.verified_hashes)}"))
    print(tr(f"[OK] UBI найден по label=ubi: {info.ubi_path}", f"[OK] UBI located by label=ubi: {info.ubi_path}"))
    print(tr(
        f"[INFO] FDT reg исходный: start=0x{info.original_ubi_start:08x}, size=0x{info.original_ubi_size:08x}",
        f"[INFO] Original FDT reg: start=0x{info.original_ubi_start:08x}, size=0x{info.original_ubi_size:08x}",
    ))
    print(tr(
        f"[INFO] tcboot runtime reg: start=0x{info.replacement_ubi_start:08x}, size=0x{info.replacement_ubi_size:08x}; cells {info.address_cells}+{info.size_cells}",
        f"[INFO] tcboot runtime reg: start=0x{info.replacement_ubi_start:08x}, size=0x{info.replacement_ubi_size:08x}; cells {info.address_cells}+{info.size_cells}",
    ))
    print(f"[INFO] sysupgrade SHA256: {info.sha256}")

    WORK.mkdir(parents=True, exist_ok=True)
    output = WORK / f"tcboot-personalized-{info.sha256[:12]}.bin"
    try:
        output, tcboot_sha, _bl33_sha = build_tcboot(TCBOOT_PAYLOAD_DIR, info, output)
    except Exception as exc:
        raise UrsusError(tr(f"Не удалось собрать FDT-aware tcboot: {exc}", f"Failed to build FDT-aware tcboot: {exc}")) from exc
    if output.stat().st_size != TCBOOT_SIZE:
        raise UrsusError("personalized tcboot size mismatch")
    print(tr(f"[OK] FDT-aware tcboot собран под выбранный DT path; SHA256={tcboot_sha}",
             f"[OK] FDT-aware tcboot built for the selected DT path; SHA256={tcboot_sha}"))
    return info, output, tcboot_sha


def _stock_bootstrap_md(host: str):
    """Stock Web -> verified MD/AN7581 -> Telnet -> FTP, before UID0 discovery.

    This is Ursus-native orchestration around the hardware-tested stock_web module.
    Model AND SoC are proven before the first settings POST.
    """
    user = input(tr("Пользователь stock Web [CMCCAdmin]: ", "Stock Web user [CMCCAdmin]: " )).strip() or stock_web.DEFAULT_WEB_USER
    entered = getpass.getpass(tr("Пароль stock Web [стандартный — Enter]: ", "Stock Web password [standard — Enter]: "))
    password = entered or stock_web.DEFAULT_WEB_PASSWORD
    if not password:
        raise UrsusError(tr("Web password не указан.", "Web password was not provided."))
    proven._register_log_secret(password)
    client = stock_web.StockWeb(host)
    try:
        try:
            mode = client.login(user, password, allow_plain=False)
        except stock_web.LoginError as first:
            print(tr(
                f"[WARNING] Encrypted Web login не принят: {first}",
                f"[WARNING] Encrypted Web login was not accepted: {first}",
            ))
            choice = input(tr("Повторить один раз через plain HTTP? [y/N]: ", "Retry once over plain HTTP? [y/N]: " )).strip().lower()
            if choice not in ("y", "yes", "д", "да"):
                raise
            try:
                client.logout()
            except Exception:
                pass
            client = stock_web.StockWeb(host)
            mode = client.login(user, password, allow_plain=True)

        setup = stock_web.StockSetup(client)
        info = setup.read_device_info()
        model = str(info.get("model") or "").strip()
        chipset = str(info.get("chipset") or "").strip()
        combined = (model + " " + chipset).lower()
        if "xg-040g-md" not in model.lower() or "7581" not in combined:
            raise UrsusError(tr(
                f"[СТОП] До первой Web-мутации требуется XG-040G-MD / AN7581; обнаружено {model} / {chipset or 'unknown'}.",
                f"[STOP] XG-040G-MD / AN7581 is required before the first Web mutation; detected {model} / {chipset or 'unknown'}.",
            ))
        print(tr(f"[OK] До Web-мутаций подтверждено: {model} / {chipset}.", f"[OK] Proven before Web mutations: {model} / {chipset}."))

        creds = setup.read_credentials()
        proven._register_log_secret(creds.get("telnet_password"))
        proven._register_log_secret(creds.get("ftp_password"))
        telnet_port = int(creds.get("telnet_port") or 23)
        if not stock_web.port_open(host, telnet_port):
            print(tr("[WAIT] Включаю Telnet через проверенный stock Web handler.", "[WAIT] Enabling Telnet through the proven stock Web handler."))
            setup.enable_telnet(port=telnet_port)
        if not stock_web.port_open(host, telnet_port):
            raise UrsusError(tr("Telnet port не открылся.", "The Telnet port did not open."))
        print(tr(f"[OK] Telnet {telnet_port} открыт.", f"[OK] Telnet {telnet_port} is open."))

        # Project contract: FTP provisioning precedes final UID0 discovery.
        ftp_enabled = bool(creds.get("ftp_enabled"))
        if not ftp_enabled:
            print(tr("[WAIT] Включаю FTP перед финальным UID0 discovery.", "[WAIT] Enabling FTP before final UID0 discovery."))
            setup.enable_ftp()
        creds = setup.read_credentials()
        if not bool(creds.get("ftp_enabled")):
            raise UrsusError(tr("FTP state не подтвердился после Web re-read.", "FTP state was not confirmed by the Web re-read."))
        proven._register_log_secret(creds.get("telnet_password"))
        proven._register_log_secret(creds.get("ftp_password"))
        print(tr("[OK] FTP state подтверждён; credentials перечитаны.", "[OK] FTP state confirmed; credentials re-read."))
        if mode == "plain":
            print(tr("[WARNING] Использован plain HTTP login.", "[WARNING] Plain HTTP login was used."))

        return proven.StockAccess(
            host=host,
            user=str(creds.get("telnet_user") or ""),
            password=str(creds.get("telnet_password") or ""),
            su_user="auto",
            telnet_port=int(creds.get("telnet_port") or 23),
            ftp_user=str(creds.get("ftp_user") or ""),
            ftp_password=str(creds.get("ftp_password") or ""),
            ftp_port=int(creds.get("ftp_port") or 21),
            ftp_enabled=True,
            model_verified=True,
            model_verification_source="stock-web-device_status.cgi-before-mutation",
            family="md",
            model_name=model,
            chipset=chipset,
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
    finally:
        password = None
        entered = None


def _require_md_identity(access) -> dict[str, str]:
    setup = access.web_setup
    if setup is None:
        raise UrsusError(tr("Потеряна stock Web session.", "The stock Web session was lost."))
    info = setup.read_device_info()
    model = str(info.get("model") or "").strip()
    chipset = str(info.get("chipset") or "").strip()
    combined = (model + " " + chipset).lower()
    if "xg-040g-md" not in model.lower() or "7581" not in combined:
        raise UrsusError(
            tr(
                f"[СТОП] Требуется XG-040G-MD / AN7581, обнаружено: {model} / {chipset or 'unknown'}",
                f"[STOP] XG-040G-MD / AN7581 is required; detected: {model} / {chipset or 'unknown'}",
            )
        )
    access.family = "md"
    access.model_name = model
    access.chipset = chipset
    access.model_verified = True
    access.model_verification_source = "stock-web-device_status.cgi"
    return {"model": model, "chipset": chipset}


def _verify_uid0(access) -> None:
    telnet = None
    try:
        telnet = proven.login_root_family(access, "md", sessions=3, allow_service_provisioning=True)
        uid = proven._telnet_probe_uid(telnet)
        if uid != 0:
            raise UrsusError(tr("UID 0 не подтверждён.", "UID 0 was not confirmed."))
        print(tr("[OK] Администратор: UID 0 подтверждён.", "[OK] Administrator: UID 0 confirmed."))
    finally:
        if telnet is not None:
            telnet.close()


def _stock_backup(access, host: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    destination = WORK / "backups" / f"{stamp}-XG-040G-MD-STOCKSET"
    print(tr("[WAIT] Создаю STOCKSET mtd0..mtd16 через проверенный TFTP backend MedveFlasher.",
             "[WAIT] Creating STOCKSET mtd0..mtd16 with the hardware-tested MedveFlasher TFTP backend."))
    result = proven.backup_tftp(access, host, destination, expected_family="md")
    validation = proven.verify_stock_restore_backup(result)
    if str(validation.get("stock_family") or "") != "md":
        raise UrsusError(tr("Backup validator не подтвердил family=md.", "The backup validator did not confirm family=md."))
    print(tr(f"[OK] STOCKSET проверен: {result}", f"[OK] STOCKSET verified: {result}"))
    return result


def _router_geometry_gate(telnet) -> None:
    # No repeated live-stock content hash here. The selected STOCKSET has already
    # passed the restore-grade validator. This gate authorizes only the exact
    # MD bootloader geometry; write success is proven afterwards by full readback.
    command = (
        "printf '__URSUS_GEO_BEGIN__\n'; "
        "cat /proc/mtd; "
        "printf '__URSUS_SYSFS__'; "
        "cat /sys/class/mtd/mtd0/size /sys/class/mtd/mtd0/erasesize /sys/class/mtd/mtd0/writesize 2>/dev/null | tr '\n' ','; "
        "printf '__\n'; "
        "printf '__URSUS_GEO_END__\n'"
    )
    rc, out = telnet.command_clean(command, timeout=60)
    if rc:
        raise UrsusError(tr("Не удалось проверить mtd0 geometry.", "Failed to verify mtd0 geometry."))
    proc = proven.parse_proc_mtd_text(out)
    if 0 not in proc:
        raise UrsusError(tr("mtd0 отсутствует в /proc/mtd.", "mtd0 is missing from /proc/mtd."))
    size, erase, _name = proc[0]
    if size != 0x80000 or erase != 0x20000:
        raise UrsusError(tr(f"mtd0 geometry неожиданна: size=0x{size:x}, erase=0x{erase:x}",
                            f"Unexpected mtd0 geometry: size=0x{size:x}, erase=0x{erase:x}"))
    m = re.search(r"__URSUS_SYSFS__([0-9]+),([0-9]+),([0-9]+),__", out)
    if not m:
        raise UrsusError(tr("Не удалось прочитать sysfs geometry mtd0.", "Could not read mtd0 sysfs geometry."))
    sys_size, sys_erase, sys_write = map(int, m.groups())
    if (sys_size, sys_erase, sys_write) != (0x80000, 0x20000, 2048):
        raise UrsusError(tr(
            f"sysfs mtd0 geometry не совпала: {sys_size}/{sys_erase}/{sys_write}",
            f"mtd0 sysfs geometry mismatch: {sys_size}/{sys_erase}/{sys_write}",
        ))


def _validate_existing_stockset_local(raw_path: str) -> Path:
    backup = Path(raw_path.strip().strip('"')).expanduser()
    if not backup.is_absolute():
        backup = backup.resolve()
    if not backup.is_dir():
        raise UrsusError(tr(f"Каталог backup не найден: {backup}", f"Backup directory not found: {backup}"))
    validation = proven.verify_stock_restore_backup(backup)
    if str(validation.get("stock_family") or "").lower() != "md":
        raise UrsusError(tr("Выбранный backup не подтверждён как stock MD.", "The selected backup was not validated as stock MD."))
    if proven._read_backup_device_mac(backup / "DEVICE_MAC.txt") is None:
        raise UrsusError(tr(
            "У выбранного backup нет валидной DEVICE_MAC-привязки. Для LAB write нужен backup с DEVICE_MAC.txt.",
            "The selected backup has no valid DEVICE_MAC binding. LAB write requires a backup with DEVICE_MAC.txt.",
        ))
    print(tr(f"[OK] Существующий STOCKSET прошёл restore-validator: {backup}",
             f"[OK] Existing STOCKSET passed the restore validator: {backup}"))
    return backup


def _verify_existing_stockset_binding(access, backup: Path) -> None:
    saved = proven._read_backup_device_mac(backup / "DEVICE_MAC.txt")
    if saved is None:
        raise UrsusError(tr("Не удалось прочитать DEVICE_MAC.txt.", "Could not read DEVICE_MAC.txt."))
    telnet = None
    try:
        telnet = proven.login_root_family(access, "md", sessions=3, allow_service_provisioning=True)
        if proven._telnet_probe_uid(telnet) != 0:
            raise UrsusError(tr("UID 0 не подтверждён при проверке привязки backup.", "UID 0 was not confirmed while checking backup binding."))
        live = proven._backup_primary_mac(proven._stock_interface_macs(telnet))
    finally:
        if telnet is not None:
            telnet.close()
    if live[1] == "UNKNOWN":
        raise UrsusError(tr("Не удалось определить MAC текущей stock Nokia.", "Could not determine the current stock Nokia MAC."))
    if saved[1].lower() != live[1].lower():
        raise UrsusError(tr(
            f"Backup принадлежит другой Nokia: backup MAC={saved[1]}, current MAC={live[1]}",
            f"Backup belongs to another Nokia: backup MAC={saved[1]}, current MAC={live[1]}",
        ))
    print(tr(f"[OK] Backup привязан к этой Nokia: {live[1]}", f"[OK] Backup is bound to this Nokia: {live[1]}"))



def _scan_partition_evidence(directory: Path) -> dict:
    found: dict[int, list[str]] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        m = re.match(r"mtd(\d+)(?:[_\-.].*)?$", path.name, re.IGNORECASE)
        if m:
            found.setdefault(int(m.group(1)), []).append(path.name)
    return {
        "present": sorted(found),
        "missing_0_16": [n for n in range(17) if n not in found],
        "files": {str(k): v for k, v in sorted(found.items())},
    }


def _assess_expert_backup(raw_path: str, *, manual: bool = False) -> tuple[Path, dict]:
    directory = Path(raw_path.strip().strip('"')).expanduser()
    if not directory.is_absolute():
        directory = directory.resolve()
    if not directory.is_dir():
        raise UrsusError(tr(f"Каталог backup/дампов не найден: {directory}", f"Backup/dump directory not found: {directory}"))
    evidence = {
        "path": str(directory),
        "kind": "manual_partition_dumps" if manual else "untrusted_or_foreign_backup",
        "restore_validator": "not_validated",
        "stock_family": "unknown",
        "device_binding": "not_proven",
        "inventory": _scan_partition_evidence(directory),
    }
    try:
        validation = proven.verify_stock_restore_backup(directory)
    except Exception as exc:
        evidence["restore_validator"] = "failed"
        evidence["validator_error"] = str(exc)
        print(tr(
            f"[WARNING] Backup не прошёл полный restore-validator: {exc}",
            f"[WARNING] Backup did not pass the full restore validator: {exc}",
        ))
    else:
        family = str(validation.get("stock_family") or "unknown").lower()
        evidence["restore_validator"] = "passed"
        evidence["stock_family"] = family
        print(tr(
            f"[INFO] Содержимое backup прошло restore-validator; family={family}. Привязка к текущей Nokia ещё НЕ доказана.",
            f"[INFO] Backup contents passed the restore validator; family={family}. Binding to the current Nokia is still NOT proven.",
        ))
    saved = proven._read_backup_device_mac(directory / "DEVICE_MAC.txt")
    if saved is not None:
        evidence["saved_mac"] = saved[1]
    inv = evidence["inventory"]
    print(tr(
        f"[INFO] Найдены дампы MTD: {', '.join('mtd'+str(n) for n in inv['present']) or 'нет'}.",
        f"[INFO] MTD dumps found: {', '.join('mtd'+str(n) for n in inv['present']) or 'none'}.",
    ))
    if inv["missing_0_16"]:
        print(tr(
            "[WARNING] Нет полного набора mtd0..mtd16: " + ", ".join("mtd" + str(n) for n in inv["missing_0_16"]),
            "[WARNING] Complete mtd0..mtd16 set is absent: " + ", ".join("mtd" + str(n) for n in inv["missing_0_16"]),
        ))
    return directory, evidence


def _live_stock_mac(access) -> str:
    telnet = None
    try:
        telnet = proven.login_root_family(access, "md", sessions=3, allow_service_provisioning=True)
        if proven._telnet_probe_uid(telnet) != 0:
            return "UNKNOWN"
        return proven._backup_primary_mac(proven._stock_interface_macs(telnet))[1]
    finally:
        if telnet is not None:
            telnet.close()


def _expert_binding_note(access, evidence: dict) -> None:
    live = _live_stock_mac(access)
    evidence["current_mac"] = live
    saved = str(evidence.get("saved_mac") or "UNKNOWN")
    if live != "UNKNOWN" and saved != "UNKNOWN":
        if live.lower() == saved.lower():
            evidence["device_binding"] = "mac_matches"
            print(tr(f"[INFO] Backup MAC совпадает с текущей Nokia: {live}", f"[INFO] Backup MAC matches the current Nokia: {live}"))
        else:
            evidence["device_binding"] = "foreign_mac"
            print(tr(
                f"[WARNING] Backup явно от другой Nokia: backup MAC={saved}, current MAC={live}.",
                f"[WARNING] Backup is explicitly from another Nokia: backup MAC={saved}, current MAC={live}.",
            ))
    else:
        print(tr(
            "[WARNING] Привязка backup к текущей Nokia не доказана.",
            "[WARNING] Backup binding to the current Nokia is not proven.",
        ))


def _expert_risk_summary(mode: str, evidence: dict | None) -> None:
    print()
    print(tr("=== ЭКСПЕРТНЫЙ РЕЖИМ: recovery backup НЕ является safety gate ===",
             "=== EXPERT MODE: recovery backup is NOT a safety gate ==="))
    if mode == "expert_none":
        print(tr("[WARNING] Продолжение вообще без stock backup.", "[WARNING] Continuing with no stock backup at all."))
    elif mode == "expert_manual":
        print(tr("[WARNING] Ручные дампы разделов могут быть неполными, несогласованными или непригодными для автоматического restore.",
                 "[WARNING] Manual partition dumps may be incomplete, inconsistent, or unsuitable for automated restore."))
    else:
        print(tr("[WARNING] Выбранный backup может быть чужим или не иметь доказанной привязки к этому устройству.",
                 "[WARNING] The selected backup may belong to another device or may not be proven to belong to this device."))
    print(tr("[WARNING] После замены mtd0 и перехода на OpenWrt возврат к точному заводскому состоянию может потребовать UART/BootROM и может быть невозможен без родных данных.",
             "[WARNING] After replacing mtd0 and migrating to OpenWrt, exact factory restoration may require UART/BootROM and may be impossible without device-specific stock data."))
    print(tr("[WARNING] Ursus проверит модель/SoC, UID0, геометрию mtd0, pinned tcboot и полный readback записи; происхождение recovery backup оператор принимает на себя.",
             "[WARNING] Ursus will still verify model/SoC, UID0, mtd0 geometry, pinned tcboot, and full write readback; recovery-backup provenance is accepted by the operator."))


def _upload_and_write_tcboot(access, host: str, backup_status: str, tcboot: Path, tcboot_sha256: str, expert: bool = False) -> None:
    telnet = None
    try:
        telnet = proven.login_root_family(access, "md", sessions=3, allow_service_provisioning=True)
        if proven._telnet_probe_uid(telnet) != 0:
            raise UrsusError(tr("Перед tcboot write UID 0 потерян.", "UID 0 was lost before the tcboot write."))
        _router_geometry_gate(telnet)
        print(tr("[WAIT] Передаю pinned tcboot во временную RAM/filesystem область через встроенный TFTP.",
                 "[WAIT] Sending the pinned tcboot into temporary RAM/filesystem storage over built-in TFTP."))
        proven.send_file_to_router_tftp(telnet, host, tcboot, "/tmp/ursus-tcboot.bin")
        script = f'''#!/bin/sh\nset -u\nPAY=/tmp/ursus-tcboot.bin\nEXPECT={tcboot_sha256}\nSIZE={TCBOOT_SIZE}\nMTD="$(command -v mtd_debug 2>/dev/null || true)"\n[ -n "$MTD" ] || {{ echo __URSUS_FAIL_NO_MTD_DEBUG__; exit 11; }}\n[ "$(id -u)" = 0 ] || {{ echo __URSUS_FAIL_NOT_ROOT__; exit 12; }}\n[ -c /dev/mtd0 ] || {{ echo __URSUS_FAIL_MTD_DEV__; exit 13; }}\n[ "$(cat /sys/class/mtd/mtd0/size)" = 524288 ] || {{ echo __URSUS_FAIL_SIZE__; exit 14; }}\n[ "$(cat /sys/class/mtd/mtd0/erasesize)" = 131072 ] || {{ echo __URSUS_FAIL_ERASE__; exit 15; }}\n[ "$(cat /sys/class/mtd/mtd0/writesize)" = 2048 ] || {{ echo __URSUS_FAIL_WRITE__; exit 16; }}\ncommand -v cmp >/dev/null 2>&1 || {{ echo __URSUS_FAIL_NO_CMP__; exit 17; }}\npsha="$(sha256sum "$PAY" | awk '{{print $1}}')"\n[ "$psha" = "$EXPECT" ] || {{ echo __URSUS_FAIL_PAYLOAD_SHA__; exit 18; }}\nsync\necho __URSUS_ERASE_BEGIN__\n"$MTD" erase /dev/mtd0 0 "$SIZE" || {{ echo __URSUS_FAIL_ERASE_OP__; exit 21; }}\necho __URSUS_WRITE_BEGIN__\n"$MTD" write /dev/mtd0 0 "$SIZE" "$PAY" || {{ echo __URSUS_FAIL_WRITE_OP__; exit 22; }}\nsync\necho __URSUS_READBACK_BEGIN__\nrm -f /tmp/ursus-tcboot-readback.bin\n"$MTD" read /dev/mtd0 0 "$SIZE" /tmp/ursus-tcboot-readback.bin || {{ echo __URSUS_FAIL_READBACK_OP__; exit 23; }}\ncmp -s "$PAY" /tmp/ursus-tcboot-readback.bin || {{ echo __URSUS_FAIL_READBACK_CMP__; exit 24; }}\necho __URSUS_TCBOOT_READBACK_OK__\nexit 0\n'''
        telnet.upload_text("/tmp/ursus-tcboot-install.sh", script)
        print()
        print(tr("Готово к первому необратимому NAND write:", "Ready for the first irreversible NAND write:"))
        print(tr("  Устройство: Nokia XG-040G-MD / AN7581", "  Device: Nokia XG-040G-MD / AN7581"))
        print(tr(f"  Recovery backup: {backup_status}", f"  Recovery backup: {backup_status}"))
        print(f"  tcboot SHA256:    {tcboot_sha256}")
        print(tr("  Запись: только mtd0, 0x000000..0x07ffff", "  Write target: mtd0 only, 0x000000..0x07ffff"))
        _confirm_tcboot_write(expert)
        telnet.send_line("sh /tmp/ursus-tcboot-install.sh")
        out = telnet.wait_regex(r"__URSUS_(?:TCBOOT_READBACK_OK__|FAIL_[A-Z0-9_]+[^\r\n]*)", 240, echo=True)
        if "__URSUS_TCBOOT_READBACK_OK__" not in out:
            raise UrsusError(tr(
                "tcboot write/readback не завершился подтверждённым полным byte-compare. НЕ ПЕРЕЗАГРУЖАЙТЕ устройство вслепую; сохраните лог.",
                "tcboot write/readback did not finish with a confirmed full byte-compare. DO NOT power-cycle blindly; preserve the log.",
            ))
        print(tr("[OK] tcboot полностью прочитан обратно и побайтно совпал.",
                 "[OK] tcboot full readback matched byte-for-byte."))
        print(tr("[INFO] На MD программный reboot НЕ используется для входа в tcboot Web recovery.",
                 "[INFO] On MD, a software reboot is NOT used to enter tcboot Web recovery."))
        telnet.send_line("sync; echo __URSUS_READY_FOR_POWER_CYCLE__")
        try:
            telnet.wait_regex(r"__URSUS_READY_FOR_POWER_CYCLE__", 20, echo=False)
        except Exception:
            pass
    finally:
        if telnet is not None:
            telnet.close()


def _http10_get(host: str, path: str, timeout: float = 3.0, limit: int = 192 * 1024) -> tuple[int, bytes, str]:
    request = (
        f"GET {path} HTTP/1.0\r\n"
        f"Host: {host}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    data = bytearray()
    with socket.create_connection((host, 80), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(request)
        while len(data) < limit:
            try:
                chunk = sock.recv(min(16384, limit - len(data)))
            except socket.timeout:
                break
            if not chunk:
                break
            data.extend(chunk)
    head, sep, body = bytes(data).partition(b"\r\n\r\n")
    if not sep:
        head, sep, body = bytes(data).partition(b"\n\n")
    first = head.splitlines()[0].decode("latin-1", "replace") if head else ""
    m = re.match(r"HTTP/\d(?:\.\d)?\s+(\d{3})", first)
    status = int(m.group(1)) if m else 0
    return status, body, first


def _tcboot_http_probe(host: str) -> tuple[bool, str]:
    try:
        status, body, first = _http10_get(host, "/flashing.html")
    except OSError as exc:
        return False, str(exc)
    low = body.lower()
    exact = any(marker in low for marker in (
        b'name="firmware"', b"openwrt  update", b"ursusitb", b"update firmware"
    ))
    if status == 200 and exact:
        return True, f"HTTP/1.0 200 /flashing.html; tcboot marker"
    if status == 200:
        # tcboot's tiny HTTP server can close before Python receives the whole body.
        # Prove that /flashing.html is a real route rather than accepting any HTTP 200.
        try:
            missing_status, _missing_body, _missing_first = _http10_get(host, "/__ursus_not_found__.html")
        except OSError:
            missing_status = 0
        if missing_status == 404:
            return True, "HTTP/1.0 200 /flashing.html + 404 control route"
    return False, f"{first or 'no HTTP status'}; body={len(body)} bytes"


def _prompt_md_tcboot_recovery(host: str) -> None:
    print()
    print(tr("=== Вход в tcboot Web recovery — MD ===", "=== Enter tcboot Web recovery — MD ==="))
    print(tr("[INFO] tcboot уже записан и проверен readback. Повторно NAND НЕ пишем.",
             "[INFO] tcboot has already been written and read back. NAND will NOT be written again."))
    print(tr("1. Выключите питание Nokia.", "1. Power the Nokia OFF."))
    print(tr("2. Включите питание.", "2. Power it ON."))
    print(tr("3. СРАЗУ ПОСЛЕ включения нажмите Reset.", "3. IMMEDIATELY AFTER power-on, press Reset."))
    print(tr("4. Удерживайте Reset 10 секунд, затем отпустите. Проверено на реальном MD.", "4. Hold Reset for 10 seconds, then release it. Hardware-verified on MD."))
    print(tr("[WARNING] Не держите Reset ДО подачи питания: это ранний BootROM Press x, а не tcboot Web recovery.",
             "[WARNING] Do not hold Reset BEFORE applying power: that enters the early BootROM Press x path, not tcboot Web recovery."))
    input(tr("После отпускания Reset нажмите Enter; Ursus проверит Web tcboot: ",
             "After releasing Reset press Enter; Ursus will verify tcboot Web: "))
    _wait_tcboot(host, timeout=75)


def _wait_tcboot(host: str, timeout: int = 75) -> None:
    print(tr("[WAIT] Проверяю tcboot Web recovery через минимальный HTTP/1.0 probe...",
             "[WAIT] Probing tcboot Web recovery with the minimal HTTP/1.0 client..."))
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        ok, detail = _tcboot_http_probe(host)
        last = detail
        if ok:
            print(tr(f"[OK] tcboot Web recovery обнаружен: {detail}",
                     f"[OK] tcboot Web recovery detected: {detail}"))
            return
        time.sleep(2)
    raise UrsusError(tr(
        f"tcboot Web recovery не подтверждён за {timeout} с ({last}). Если страница уже открывается в браузере, сохраните session log: повторный NAND write НЕ нужен.",
        f"tcboot Web recovery was not confirmed within {timeout}s ({last}). If the page is already open in a browser, preserve the session log: another NAND write is NOT needed.",
    ))


def _confirm_sysupgrade_upload(info: SysupgradeInfo, expert: bool) -> bool:
    print()
    print(tr("=== Direct sysupgrade через tcboot ===", "=== Direct sysupgrade through tcboot ==="))
    print(tr(f"[INFO] Файл: {info.path}", f"[INFO] Image: {info.path}"))
    print(f"[INFO] SHA256: {info.sha256}")
    print(tr(
        f"[INFO] FDT gate: label=ubi → {info.ubi_path}; runtime reg={info.uboot_reg_literal}",
        f"[INFO] FDT gate: label=ubi → {info.ubi_path}; runtime reg={info.uboot_reg_literal}",
    ))
    print(tr("[WARNING] После полной отправки файла tcboot начнёт изменение UBI. Питание не отключать.",
             "[WARNING] After the complete upload tcboot will start modifying UBI. Do not remove power."))
    if expert:
        print(tr("[WARNING] ЭКСПЕРТНЫЙ режим: родной recovery backup мог не быть подтверждён.",
                 "[WARNING] EXPERT mode: an own recovery backup may not have been proven."))
    _flush_pending_console_input()
    while True:
        print(tr("1. Загрузить выбранный sysupgrade в tcboot", "1. Upload the selected sysupgrade to tcboot"))
        print(tr("0. Остановиться на рабочем tcboot Web recovery", "0. Stop with working tcboot Web recovery"))
        choice = input("> ").strip()
        if choice == "1":
            return True
        if choice == "0":
            return False
        if not choice:
            print(tr("[INFO] Пустой ввод проигнорирован.", "[INFO] Empty input ignored."))
        else:
            print(tr("Неверный выбор.", "Invalid selection."))


def _tcboot_http_upload(host: str, image: Path, timeout: float = 180.0, port: int = 80) -> str:
    image = Path(image)
    size = image.stat().st_size
    boundary = "----UrsusFlasherMD" + hashlib.sha256((str(size) + image.name).encode("utf-8")).hexdigest()[:20]
    filename = image.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
    pre = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"firmware\"; filename=\"{filename}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("ascii")
    content_length = len(pre) + size + len(tail)
    headers = (
        "POST /flashing.html HTTP/1.0\r\n"
        f"Host: {host}\r\n"
        f"Content-Type: multipart/form-data; boundary={boundary}\r\n"
        f"Content-Length: {content_length}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    sent_file = 0
    last_report = -1
    print(tr(f"[TRANSFER] tcboot HTTP upload: 0/{size} bytes", f"[TRANSFER] tcboot HTTP upload: 0/{size} bytes"))
    with socket.create_connection((host, port), timeout=8.0) as sock:
        sock.settimeout(timeout)
        sock.sendall(headers)
        sock.sendall(pre)
        with image.open("rb") as fh:
            while True:
                chunk = fh.read(64 * 1024)
                if not chunk:
                    break
                sock.sendall(chunk)
                sent_file += len(chunk)
                mib = sent_file // (1024 * 1024)
                if mib != last_report or sent_file == size:
                    last_report = mib
                    print(tr(
                        f"[TRANSFER] sysupgrade: {sent_file}/{size} bytes ({sent_file * 100 // size}%)",
                        f"[TRANSFER] sysupgrade: {sent_file}/{size} bytes ({sent_file * 100 // size}%)",
                    ))
        sock.sendall(tail)
        if sent_file != size:
            raise UrsusError(tr("HTTP upload отправил неполный файл.", "HTTP upload sent an incomplete file."))
        print(tr("[OK] Весь sysupgrade передан tcboot. Теперь tcboot выполняет FIT/UBI transaction; смотрите UART U: markers.",
                 "[OK] The complete sysupgrade was sent to tcboot. tcboot is now running the FIT/UBI transaction; watch UART U: markers."))
        # The tcboot page is known to keep the browser spinner alive. Do not make
        # the CLI wait minutes for an HTML response after the complete body is sent.
        sock.settimeout(min(timeout, 10.0))
        response = bytearray()
        try:
            while len(response) < 128 * 1024:
                chunk = sock.recv(min(16384, 128 * 1024 - len(response)))
                if not chunk:
                    break
                response.extend(chunk)
        except (socket.timeout, ConnectionResetError, BrokenPipeError, OSError):
            # A successful tcboot transaction ends with reset, so losing this HTTP
            # connection after the complete body was sent is expected.
            pass
    first = bytes(response).splitlines()[0].decode("latin-1", "replace") if response else "connection closed/reset after complete upload"
    print(tr(f"[INFO] tcboot HTTP result: {first}", f"[INFO] tcboot HTTP result: {first}"))
    return first


def install_openwrt_lab1(mode: str = "new") -> None:
    print()
    print(tr("=== Установить OpenWrt — MD LAB1fix9 ===", "=== Install OpenWrt — MD LAB1fix9 ==="))
    print(tr(
        "LAB1fix9 выбирает sysupgrade, разбирает FIT/FDT, собирает FDT-aware tcboot с WebFailsafe 🐻-брендингом, затем может сам загрузить тот же ITB через tcboot Web.",
        "LAB1fix9 selects a sysupgrade, parses FIT/FDT, builds an FDT-aware tcboot with bear WebFailsafe branding, then can upload the same ITB through tcboot Web.",
    ))
    sysinfo, tcboot_path, tcboot_sha256 = _select_sysupgrade()
    host = input(tr(f"IP Nokia [{DEFAULT_HOST}]: ", f"Nokia IP [{DEFAULT_HOST}]: ")).strip() or DEFAULT_HOST
    backup: Path | None = None
    evidence: dict | None = None
    expert = mode.startswith("expert_")

    if mode == "existing_bound":
        raw = input(tr("Путь к существующему Ursus/MedveFlasher STOCKSET backup: ", "Path to existing Ursus/MedveFlasher STOCKSET backup: ")).strip()
        if not raw:
            raise UrsusError(tr("Путь к backup не указан.", "Backup path was not provided."))
        backup = _validate_existing_stockset_local(raw)
    elif mode in ("expert_untrusted", "expert_manual"):
        raw = input(tr("Путь к backup/каталогу дампов: ", "Path to backup/dump directory: ")).strip()
        if not raw:
            raise UrsusError(tr("Путь не указан.", "Path was not provided."))
        backup, evidence = _assess_expert_backup(raw, manual=(mode == "expert_manual"))

    access = None
    try:
        print(tr("[WAIT] Stock Web bootstrap...", "[WAIT] Stock Web bootstrap..."))
        access = _stock_bootstrap_md(host)
        info = _require_md_identity(access)
        print(tr(f"[OK] Device: {info['model']} / {info['chipset']}", f"[OK] Device: {info['model']} / {info['chipset']}"))
        _verify_uid0(access)

        if mode == "new":
            backup = _stock_backup(access, host)
            backup_status = "NEW DEVICE-BOUND STOCKSET VERIFIED"
            evidence = {"path": str(backup), "device_binding": "created_from_current_device", "restore_validator": "passed"}
        elif mode == "existing_bound":
            assert backup is not None
            _verify_existing_stockset_binding(access, backup)
            print(tr("[OK] Новый backup не снимается: используется проверенный существующий STOCKSET.",
                     "[OK] A new backup will not be created: the validated existing STOCKSET is being used."))
            backup_status = "EXISTING DEVICE-BOUND STOCKSET VERIFIED"
            evidence = {"path": str(backup), "device_binding": "mac_matches", "restore_validator": "passed"}
        elif mode in ("expert_untrusted", "expert_manual"):
            assert evidence is not None
            _expert_binding_note(access, evidence)
            _expert_risk_summary(mode, evidence)
            backup_status = "EXPERT EVIDENCE ONLY - NOT DEVICE-BOUND"
        elif mode == "expert_none":
            evidence = {"path": None, "device_binding": "none", "restore_validator": "not_available"}
            _expert_risk_summary(mode, evidence)
            backup_status = "NONE - OPERATOR ACCEPTS RECOVERY RISK"
        else:
            raise UrsusError(f"unknown install mode: {mode}")

        _upload_and_write_tcboot(access, host, backup_status, tcboot_path, tcboot_sha256, expert=expert)
        if access is not None:
            access.close_web(announce=False)
        _prompt_md_tcboot_recovery(host)
        submitted = False
        http_result = None
        if _confirm_sysupgrade_upload(sysinfo, expert):
            http_result = _tcboot_http_upload(host, sysinfo.path)
            submitted = True
        report = {
            "version": APP_VERSION,
            "result": "TCBOOT_WEB_GATE_PASS",
            "device": "Nokia XG-040G-MD",
            "soc": "AN7581",
            "backup": str(backup) if backup is not None else None,
            "backup_mode": mode,
            "backup_evidence": evidence,
            "expert_override": expert,
            "tcboot_sha256": tcboot_sha256,
            "tcboot_readback": "full_byte_compare_passed",
            "sysupgrade_file": str(sysinfo.path),
            "sysupgrade_sha256": sysinfo.sha256,
            "sysupgrade_fdt_ubi_path": sysinfo.ubi_path,
            "sysupgrade_original_ubi_reg": [sysinfo.original_ubi_start, sysinfo.original_ubi_size],
            "tcboot_runtime_ubi_reg": [sysinfo.replacement_ubi_start, sysinfo.replacement_ubi_size],
            "direct_sysupgrade": "PATCH8_FDTAWARE_BEAR_SUBMITTED" if submitted else "PATCH8_FDTAWARE_BEAR_NOT_SUBMITTED",
            "tcboot_http_result": http_result,
            "recovery_entry": "manual_power_cycle_then_immediate_reset_hold_10s_hw_verified",
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        report_path = WORK / "LAB1_RESULT.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print()
        if submitted:
            print(tr("[SUCCESS] Sysupgrade полностью передан tcboot; дальнейший результат определяется UART/Linux boot log.",
                     "[SUCCESS] Sysupgrade was fully submitted to tcboot; the final result is determined by the UART/Linux boot log."))
        else:
            print(tr("[SUCCESS] MD gate остановлен на рабочем tcboot Web recovery без запуска sysupgrade.",
                     "[SUCCESS] MD gate stopped at working tcboot Web recovery without starting sysupgrade."))
    finally:
        if access is not None:
            try:
                access.close_web(announce=False)
            except Exception:
                pass


def install_menu() -> None:
    while True:
        print()
        print(tr("Установка OpenWrt — MD LAB", "OpenWrt installation — MD LAB"))
        print()
        print(tr("1. Рекомендуется: снять новый STOCKSET и продолжить", "1. Recommended: create a new STOCKSET and continue"))
        print(tr("2. Использовать ранее снятый РОДНОЙ Ursus/MedveFlasher STOCKSET", "2. Use an existing OWN Ursus/MedveFlasher STOCKSET"))
        print(tr("3. ЭКСПЕРТ: продолжить с чужим/непривязанным backup", "3. EXPERT: continue with a foreign/unbound backup"))
        print(tr("4. ЭКСПЕРТ: продолжить с ручными дампами разделов MTD", "4. EXPERT: continue with manually dumped MTD partitions"))
        print(tr("5. ЭКСПЕРТ: продолжить БЕЗ backup", "5. EXPERT: continue WITHOUT a backup"))
        print(tr("0. Назад", "0. Back"))
        choice = input("> ").strip()
        mapping = {
            "1": "new",
            "2": "existing_bound",
            "3": "expert_untrusted",
            "4": "expert_manual",
            "5": "expert_none",
        }
        if choice in mapping:
            install_openwrt_lab1(mapping[choice])
            return
        if choice == "0":
            return
        print(tr("Неверный выбор.", "Invalid selection."))


def restore_factory() -> None:
    print(tr(
        "LAB1: автоматический Restore factory Nokia пока BLOCKED в новом Ursus UI. Проверенный MedveFlasher recovery backend сохранён в data/proven_backend.py для последующего подключения без переписывания транспорта.",
        "LAB1: automatic Restore factory Nokia is currently BLOCKED in the new Ursus UI. The proven MedveFlasher recovery backend is preserved in data/proven_backend.py for later wiring without rewriting transports.",
    ))


def diagnostics() -> None:
    host = input(tr(f"IP Nokia [{DEFAULT_HOST}]: ", f"Nokia IP [{DEFAULT_HOST}]: ")).strip() or DEFAULT_HOST
    print(tr("Диагностика LAB1 read-only:", "LAB1 read-only diagnostics:"))
    for port, label in ((80, "HTTP"), (23, "Telnet"), (21, "FTP")):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        try:
            rc = s.connect_ex((host, port))
        finally:
            s.close()
        print(f"  {label:<7} {'OPEN' if rc == 0 else 'closed'}")
    ok, detail = _tcboot_http_probe(host)
    print(f"  tcboot  {'YES' if ok else 'no'} ({detail})")


def menu() -> None:
    while True:
        print()
        print("UrsusFlasher — Nokia XG-040G")
        print()
        print(tr("1. Установить OpenWrt", "1. Install OpenWrt"))
        print(tr("2. Восстановить заводскую Nokia", "2. Restore factory Nokia"))
        print(tr("3. Диагностика", "3. Diagnostics"))
        print(tr("0. Выход", "0. Exit"))
        choice = input("> ").strip()
        try:
            if choice == "1":
                install_menu()
            elif choice == "2":
                restore_factory()
            elif choice == "3":
                diagnostics()
            elif choice == "0":
                return
            else:
                print(tr("Неверный выбор.", "Invalid selection."))
        except KeyboardInterrupt:
            print(tr("\n[WARNING] Остановлено пользователем.", "\n[WARNING] Stopped by user."))
        except Exception as exc:
            print(tr(f"\n[ERROR] {exc}", f"\n[ERROR] {exc}"), file=sys.stderr)


def main() -> int:
    _ui_init_color()
    choose_language()
    proven.start_session_logging()
    _ui_init_color()
    validate_tcboot_inputs()
    print(f"[BUILD] {BUILD_TAG}")
    print(tr("[RUNTIME] Python stdlib only; pip не требуется.", "[RUNTIME] Python stdlib only; pip is not required."))
    menu()
    print()
    print(f"[LOG] {proven.SESSION_LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

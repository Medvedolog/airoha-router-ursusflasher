#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
_REPO_ROOT = HERE.parent.parent
REPO_MODE = (_REPO_ROOT / "fw").is_dir() and (_REPO_ROOT / "payloads").is_dir() and (_REPO_ROOT / "config").is_dir()
ROOT = _REPO_ROOT if REPO_MODE else HERE.parent
sys.path.insert(0, str(HERE))

import proven_backend as proven
import ursus_web_client as uw
import ursusboot_install
import ursusboot_update
import console_ui as ui
import ui_terms as terms
import network_guidance

TARGET_URSUS = "0.1.0-alpha4-FUDAN1"
RECOVERY_HOST = os.environ.get("URSUS_RECOVERY_HOST", "192.168.1.1")
DEFAULT_STOCK_HOST = os.environ.get("NOKIA_HOST", "192.168.1.1")

def _host_version() -> str:
    try:
        raw = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        return raw.split("-md-", 1)[0] or "dev"
    except Exception:
        return "dev"

HOST_VERSION = _host_version()

STOCK_IMAGE_NAME = "openwrt-airoha-an7581-nokia_xg-040g-md-squashfs-sysupgrade.bin"
STOCK_IMAGE_BUNDLED = ROOT / "fw" / STOCK_IMAGE_NAME
FIRMWARE_BUNDLE_MANIFEST = (ROOT / "config" / "FIRMWARE_BUNDLE.json") if REPO_MODE else (HERE / "FIRMWARE_BUNDLE.json")


_LANG = "ru"
_STAGE_NO = 0


def say(msg: str = "") -> None:
    if not msg:
        print(flush=True)
        return
    for label in ("ГОТОВО", "ИНФО", "ЖДУ", "СДЕЛАЙТЕ", "ВНИМАНИЕ", "СТОП", "ОШИБКА", "ШАГ",
                  "READY", "INFO", "WAIT", "ACTION", "WARNING", "STOP", "ERROR", "STEP"):
        prefix = f"[{label}] "
        if msg.startswith(prefix):
            ui.status(label, msg[len(prefix):])
            return
    if msg.startswith("=== ") and msg.endswith(" ==="):
        ui.rule(msg[4:-4], style="cyan")
        return
    print(msg, flush=True)


def tr(ru: str, en: str) -> str:
    return en if _LANG == "en" else ru


def choose_language() -> str:
    global _LANG
    ui.enable()
    ui.startup_bear()
    env = os.environ.get("NOKIA_LANG", "").strip().lower()
    if env in ("ru", "rus", "1"):
        _LANG = "ru"
    elif env in ("en", "eng", "2"):
        _LANG = "en"
    else:
        say("Выберите язык / Select language:")
        say("  1 — Русский")
        say("  2 — English")
        while True:
            value = input("Ваш выбор [1]: ").strip().lower()
            if value in ("", "1", "ru", "rus", "рус", "русский"):
                _LANG = "ru"
                break
            if value in ("2", "en", "eng", "english"):
                _LANG = "en"
                break
            say("Введите 1 или 2 / Enter 1 or 2")
    os.environ["NOKIA_LANG"] = _LANG
    proven._LANG = _LANG
    return _LANG


def choose_stock_ip() -> str:
    default = DEFAULT_STOCK_HOST
    while True:
        raw = input(tr(
            f"IP-адрес роутера с родной прошивкой Nokia [{default}]: ",
            f"Router IP address with Nokia factory firmware [{default}]: ",
        )).strip()
        value = raw or default
        try:
            addr = ipaddress.ip_address(value)
            if addr.version != 4:
                raise ValueError
            return str(addr)
        except ValueError:
            say(tr("Это не похоже на IP-адрес. Нужны четыре числа через точку, например 192.168.1.1.", "This does not look like an IP address. Enter four numbers separated by dots, for example 192.168.1.1."))


def stage(title_ru: str, title_en: str, now_ru: str, now_en: str,
          next_ru: str | None = None, next_en: str | None = None) -> None:
    global _STAGE_NO
    _STAGE_NO += 1
    say()
    say(f"=== [{_STAGE_NO}] " + tr(title_ru, title_en) + " ===")
    say(tr("Сейчас: ", "Now: ") + tr(now_ru, now_en))
    if next_ru is not None and next_en is not None:
        say(tr("Дальше: ", "Next: ") + tr(next_ru, next_en))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _bundle_path(relpath: str) -> Path:
    rel = Path(relpath)
    if REPO_MODE and rel.parts[:2] == ("data", "payloads"):
        return ROOT / "payloads" / Path(*rel.parts[2:])
    return ROOT / rel


def _verify_bundle_file(relpath: str, expected: str) -> Path:
    path = _bundle_path(relpath)
    if not path.is_file():
        raise RuntimeError(tr(f"Комплектный файл отсутствует: {relpath}",
                              f"Bundled file is missing: {relpath}"))
    got = sha256(path)
    if got != expected:
        raise RuntimeError(tr(f"Контрольная сумма комплектного файла не совпадает: {relpath}: {got} != {expected}",
                              f"Bundled file SHA256 mismatch: {relpath}: {got} != {expected}"))
    return path


def verify_firmware_bundle() -> dict:
    try:
        info = json.loads(FIRMWARE_BUNDLE_MANIFEST.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(tr("Не читается data/FIRMWARE_BUNDLE.json; запись запрещена.",
                              "data/FIRMWARE_BUNDLE.json cannot be read; flashing is forbidden.")) from exc
    for item in info.get("files", []):
        if item.get("required"):
            _verify_bundle_file(str(item["path"]), str(item["sha256"]))
    kernel = info.get("kernel") or info.get("kernel_version") or "unknown"
    say(tr(
        f"[ИНФО] Комплект файлов проверен. OpenWrt {info.get('openwrt_revision','unknown')}, ядро {kernel}.",
        f"[INFO] The bundled files were verified. OpenWrt {info.get('openwrt_revision','unknown')}, kernel {kernel}.",
    ))
    return info


def require_bundle_role(role: str) -> Path:
    """Verify only the bundled file needed by the selected state transition."""
    try:
        info = json.loads(FIRMWARE_BUNDLE_MANIFEST.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(tr(
            "Не читается manifest комплекта прошивки.",
            "The firmware bundle manifest cannot be read.",
        )) from exc
    for item in info.get("files", []):
        if item.get("role") == role:
            return _verify_bundle_file(str(item["path"]), str(item["sha256"]))
    raise RuntimeError(tr(f"В bundle manifest нет {role}.", f"Bundle manifest has no {role}."))


def ensure_stock_layout_image() -> Path:
    return require_bundle_role("OPENWRT_NONUBI_SYSUPGRADE")


def ursus_status(host: str = RECOVERY_HOST) -> dict | None:
    try:
        return uw.status(host)
    except Exception:
        return None


def wait_ursus(host: str = RECOVERY_HOST, seconds: int = 120) -> dict | None:
    deadline = time.time() + seconds
    last_notice = -1
    while time.time() < deadline:
        st = ursus_status(host)
        if st:
            return st
        remain = int(deadline - time.time())
        bucket = remain // 10
        if bucket != last_notice:
            say(tr(f"[ЖДУ] Роутер ещё не ответил. Подожду ещё примерно {remain} секунд.",
                   f"[WAIT] The router has not responded yet. I will wait about {remain} more seconds."))
            last_notice = bucket
        time.sleep(1)
    return None


def probe_http_identity(host: str) -> str:
    """Read-only fingerprint: openwrt, http, or none. UrsusBoot is probed via /api/status."""
    try:
        conn = http.client.HTTPConnection(host, 80, timeout=2.5)
        try:
            conn.request("GET", "/", headers={"Connection": "close"})
            resp = conn.getresponse()
            body = resp.read(65536)
            headers = "\n".join(f"{k}: {v}" for k, v in resp.getheaders()).encode("utf-8", "replace")
        finally:
            conn.close()
    except OSError:
        return "none"
    low = (headers + b"\n" + body).lower()
    if b"openwrt" in low or b"luci" in low or b"/cgi-bin/luci" in low:
        return "openwrt"
    return "http"


def wait_for_manual_recovery() -> dict:
    stage(
        "Вход в режим восстановления UrsusBoot",
        "Entering UrsusBoot Recovery",
        "Загрузчик уже записан. На этом шаге постоянную память не меняю.",
        "The bootloader is already written. This step does not modify persistent storage.",
        "Если автоматический вход после reboot не получился: выключите питание Nokia, включите снова, примерно через 1 секунду зажмите Reset и держите 5-10 секунд — до 2 коротких + 3 длинных красных миганий и постоянного красного света. Затем отпустите Reset. До подачи питания Reset не зажимайте: это Airoha BootROM.",
        "If automatic Recovery after reboot was missed: power Nokia off, power it on again, wait about 1 second, then hold Reset for 5-10 seconds until 2 short + 3 long red flashes and steady red. Then release Reset. Do not hold Reset before applying power because that enters Airoha BootROM.",
    )
    while True:
        input(tr(
            "Выполните вход в Recovery и нажмите Enter, когда красный индикатор горит постоянно. Программа проверит 192.168.1.1: ",
            "Enter Recovery, then press Enter when the red status LED is solid. The program will check 192.168.1.1: ",
        ))
        st = wait_ursus(RECOVERY_HOST, 20)
        if st:
            say(tr("[ГОТОВО] Режим восстановления UrsusBoot найден.",
                   "[READY] UrsusBoot Recovery is responding."))
            return st
        say(tr("[ВНИМАНИЕ] Recovery пока не отвечает. Запись загрузчика повторять не нужно.",
               "[WARNING] Recovery is not responding yet. Do not rewrite the bootloader."))
        again = input(tr(
            "Повторите вход в Recovery и нажмите Enter для новой проверки; 0 — остановить ONE-CLICK без новых записей: ",
            "Retry Recovery and press Enter to check again; 0 — stop ONE-CLICK without further writes: ",
        )).strip()
        if again == "0":
            raise RuntimeError(tr("Остановлено пользователем после успешной записи загрузчика.",
                                  "Stopped by the user after the bootloader write had already passed readback."))

def ensure_target_ursus(st: dict) -> dict:
    version = str(st.get("version") or "")
    if version == TARGET_URSUS:
        say(tr(f"[ГОТОВО] UrsusBoot {version} уже запущен.",
               f"[OK] UrsusBoot {version} is already running."))
        return st

    stage(
        "Обновление UrsusBoot",
        "Updating UrsusBoot",
        f"Сейчас в RAM работает {version or 'неизвестная версия'}. Целевая постоянная версия — {TARGET_URSUS}.",
        f"The current RAM runtime is {version or 'unknown'}. The persistent target is {TARGET_URSUS}.",
        "Загружаю FUDAN1, UrsusBoot сам проверит FIP, запишет его и считает обратно. Перезагрузка между обновлением загрузчика и записью OpenWrt не нужна: текущая Recovery-сессия остаётся в RAM, а при STOCK→UBI миграции уже записанный FUDAN1 FIP копируется в новый UBI volume fip.",
        "FUDAN1 is uploaded, validated, committed and read back by UrsusBoot. No intermediate reboot is required: the current Recovery runtime stays in RAM, and STOCK-to-UBI migration copies the already committed FUDAN1 FIP into the new UBI fip volume.",
    )
    ursusboot_update.require_fip_payload()
    st2 = uw.update_bootloader(RECOVERY_HOST, ursusboot_update.PRODUCTION_PAYLOAD, confirm=False)
    st2["_persistent_ursus_target"] = TARGET_URSUS
    st2["_runtime_ursus_version"] = version
    say(tr(f"[ГОТОВО] Постоянный UrsusBoot {TARGET_URSUS} записан и считан обратно. Текущая RAM-сессия {version or 'старой версии'} продолжит операцию до финальной перезагрузки.",
           f"[READY] Persistent UrsusBoot {TARGET_URSUS} is written and read back. The current RAM runtime {version or 'from the previous version'} will continue until the final reboot."))
    return st2


def install_ursus_from_openwrt(host: str) -> dict:
    stage(
        "OpenWrt: установка / восстановление UrsusBoot",
        "OpenWrt: install / recover UrsusBoot",
        f"Подключаюсь к root SSH на {host}. Если установлен пароль root, его штатно запросит системный OpenSSH.",
        f"Connecting to root SSH at {host}. If root has a password, the system OpenSSH client will ask for it normally.",
        "Исправная UBI не обязательна: при наличии UBI обновляется только volume fip; иначе допускается только однозначно найденный и проверенный по содержимому physical boot block.",
        "Healthy UBI is not required: an existing fip volume is updated directly; otherwise only an unambiguous content-proven physical boot block is accepted.",
    )
    rc = ursusboot_install.run_install(
        unattended=True,
        host=host,
        recovery_after=True,
        recovery_host=RECOVERY_HOST,
    )
    if rc:
        raise RuntimeError(f"OpenWrt SSH UrsusBoot install returned rc={rc}")
    st = wait_ursus(RECOVERY_HOST, 20)
    if not st:
        say(tr(
            "[ИНФО] FUDAN1 записан и сверен, но Recovery не пойман автоматически. Повторять запись не нужно.",
            "[INFO] FUDAN1 was written and verified, but Recovery was not caught automatically. Do not repeat the write.",
        ))
        st = wait_for_manual_recovery()
    return st

def install_or_update_openwrt(st: dict) -> dict:
    layout = str(st.get("current_layout") or "UNKNOWN")

    if layout == "STOCK":
        # Lazy gates: this transition alone needs UBI sysupgrade + preloader.
        ubi_image = require_bundle_role("OPENWRT_UBI_SYSUPGRADE")
        preloader = require_bundle_role("STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE")
        stage(
            "Переход с заводской прошивки Nokia на OpenWrt",
            "Nokia factory firmware -> OpenWrt",
            "Передаю служебный загрузочный компонент и файл OpenWrt. Оба файла проверяются до начала записи.",
            "ONE-KEY uploads the service boot component and the OpenWrt image. Both files are validated before writing starts.",
            "Проверю память и доступное место, затем запишу систему в безопасном порядке.",
            "The storage geometry and available space are checked first, then the system is written in the safe order.",
        )
        result = uw.update_firmware(RECOVERY_HOST, ubi_image, confirm=False, preloader=preloader)
        # ROOTFSMAX2 is valid only here: migration completed in this same RAM
        # Recovery session and OpenWrt has not booted/mounted rootfs_data yet.
        resize = uw.maximize_fresh_migration_rootfs_data(RECOVERY_HOST, result)
        proven._write_session_only(
            f"[ROOTFSMAX2] rootfs_data_lebs={resize['rootfs_data_lebs']} "
            f"rootfs_data_bytes={resize['rootfs_data_bytes']} free_pebs={resize['free_pebs']} "
            f"leb_size={resize['leb_size']}"
        )
        return result

    if layout == "OPENWRT_UBI":
        ubi_image = require_bundle_role("OPENWRT_UBI_SYSUPGRADE")
        stage(
            "Обновление OpenWrt",
            "Updating OpenWrt UBI",
            "OpenWrt уже установлен. Проверяю файл обновления в оперативной памяти и обновляю систему без изменения разметки.",
            "The device already uses UBI. ONE-KEY will validate the bundled sysupgrade.itb in RAM and update the existing FIT without repartitioning.",
            "После записи считаю всё обратно и сверю. Потом роутер перезагрузится сам.",
            "A full readback/validation follows the write, then the router reboots automatically.",
        )
        return uw.update_firmware(RECOVERY_HOST, ubi_image, confirm=False)

    if layout == "OPENWRT_STOCK_LAYOUT":
        image = ensure_stock_layout_image()
        stage(
            "Обновление OpenWrt",
            "Updating OpenWrt stock-layout",
            "Использую файл обновления, подходящий для текущей разметки.",
            "ONE-KEY uses only OPENWRT_NONUBI_SYSUPGRADE and the stock-layout backend.",
            "Сначала записываю и проверяю основную систему, загрузочную часть — последней. Разметку не меняю.",
            "Rootfs is written and verified first, kernel last. The partition layout is unchanged; migration to UBI is forbidden by policy.",
        )
        return uw.update_firmware(RECOVERY_HOST, image, confirm=False)

    proven._write_session_only(f"[TECH] unsupported layout enum: {layout}")
    raise RuntimeError(tr("Не удалось определить поддерживаемую разметку. Ничего не записываю.",
                          "The supported layout could not be determined. Nothing will be written."))


def main() -> int:
    global _STAGE_NO
    _STAGE_NO = 0
    choose_language()
    proven.start_session_logging()

    say()
    say(tr(f"UrsusFlasher ONE-KEY {HOST_VERSION} — Nokia XG-040G-MD, UrsusBoot {TARGET_URSUS}",
           f"UrsusFlasher ONE-KEY {HOST_VERSION} — Nokia XG-040G-MD, UrsusBoot {TARGET_URSUS}"))
    network_guidance.show()
    say(tr("Прошивка уже в комплекте, интернет не нужен. Всё остальное определю сам.",
           "Firmware is bundled; Internet is not required. Everything else is detected automatically."))

    stage(
        "Смотрю, что сейчас на роутере",
        "Detecting the current router state",
        f"Проверяю {RECOVERY_HOST} — родная прошивка Nokia, OpenWrt или уже UrsusBoot.",
        f"Checking {RECOVERY_HOST} — Nokia factory firmware, OpenWrt or UrsusBoot.",
        "Пока только определяю состояние. Нужные файлы проверю тогда, когда станет понятно, какой путь действительно нужен.",
        "This stage only detects the state. Payloads are checked lazily once the required path is known.",
    )

    st = ursus_status(RECOVERY_HOST)
    if st:
        say(tr(f"[ИНФО] Роутер в режиме восстановления UrsusBoot {st.get('version')}. Система: {terms.layout_label(st.get('current_layout'))}.",
               f"[INFO] Router is in UrsusBoot recovery mode {st.get('version')}. System: {terms.layout_label(st.get('current_layout'))}."))
    else:
        identity = probe_http_identity(RECOVERY_HOST)
        if identity == "openwrt":
            st = install_ursus_from_openwrt(RECOVERY_HOST)
        else:
            stock_host = choose_stock_ip()
            identity = probe_http_identity(stock_host)
            if identity == "none":
                raise RuntimeError(tr(
                    "Роутер не отвечает на 192.168.1.1. Записывать вслепую не буду. Проверьте питание, подключение через LAN2/LAN3 и IP-адрес компьютера. Если в UART видно LZMA: res 1 или PANIC — запустите EXPERT и выберите " + terms.action_ref("recover_bootloader") + ".",
                    "The router does not respond at 192.168.1.1. Nothing will be written blindly. Check power, the LAN2/LAN3 connection and the PC IP address. If UART shows LZMA: res 1 or PANIC, run EXPERT and choose " + terms.action_ref("recover_bootloader") + ".",
                ))
            if identity == "openwrt":
                st = install_ursus_from_openwrt(stock_host)
            else:
                stage(
                    "Заводская прошивка Nokia: установка UrsusBoot",
                    "Nokia factory firmware: installing UrsusBoot",
                    f"Пробую штатный Nokia Web на {stock_host}. Универсальные Web-реквизиты используются автоматически; индивидуальный Telnet-пароль читается из самого роутера.",
                    f"Trying the stock Nokia Web UI at {stock_host}. Universal Web credentials are used automatically; the device-specific Telnet password is read from the router itself.",
                    "Сначала проверяю модель и доступ, затем сохраняю и валидирую полную резервную копию. После этого FUDAN1 напрямую записывается в mtd0 с сохранением заводского BootROM prefix и tcboot env, полностью считывается обратно и проверяется. Промежуточная alpha3 больше не используется.",
                    "After model/root confirmation, a complete backup is captured and validated. FUDAN1 is then written directly to mtd0 while preserving the factory BootROM prefix and tcboot environment, followed by a full readback. No intermediate alpha3 bootstrap is used.",
                )
                rc = ursusboot_install.run_install(
                    unattended=True,
                    host=stock_host,
                    recovery_after=True,
                    recovery_host=RECOVERY_HOST,
                )
                if rc:
                    say(tr("[ОШИБКА] Не удалось напрямую установить FUDAN1 со stock. Дальнейшая запись не начнётся.",
                           "[STOP] Direct FUDAN1 stock installation did not complete. No dangerous stage will be continued automatically."))
                    return rc
                st = wait_ursus(RECOVERY_HOST, 10)
                if not st:
                    say(tr("[ИНФО] FUDAN1 напрямую записан в mtd0 и сверен. Recovery не пойман с первого раза; повторять запись mtd0 не нужно.",
                           "[INFO] FUDAN1 was written directly to mtd0 and verified. Recovery was missed on the first attempt; do not rewrite mtd0."))
                    st = wait_for_manual_recovery()
                say(tr(f"[ИНФО] Роутер в режиме восстановления UrsusBoot {st.get('version')}. Система: {terms.layout_label(st.get('current_layout'))}.",
                       f"[INFO] Router is in UrsusBoot recovery mode {st.get('version')}. System: {terms.layout_label(st.get('current_layout'))}."))

    st = ensure_target_ursus(st)
    say(tr(
        "[ИНФО] Режим восстановления UrsusBoot доступен на http://192.168.1.1. Продолжаю автоматически, браузер открывать не нужно.",
        "[INFO] UrsusBoot Recovery is now active at http://192.168.1.1. ONE-KEY continues through the same API automatically; opening a browser is optional.",
    ))
    if str(st.get("version") or "") != TARGET_URSUS and st.get("_persistent_ursus_target") != TARGET_URSUS:
        raise RuntimeError(tr(
            f"Не подтверждена целевая версия UrsusBoot {TARGET_URSUS}; runtime={st.get('version')}",
            f"Target UrsusBoot {TARGET_URSUS} was not confirmed; runtime={st.get('version')}",
        ))

    st = install_or_update_openwrt(st)

    say(tr("[ГОТОВО] OpenWrt записан и сверен.",
           "[READY] sysupgrade was written and verified."))
    stage(
        "Готово",
        "Done",
        "Перезагружаю роутер. От вас больше ничего не требуется.",
        "ONE-KEY is issuing the reboot command. No further user action is required.",
        "После загрузки откройте http://192.168.1.1. Если IP-адрес компьютера меняли вручную — верните обычные настройки сети. Для Recovery: после reboot дождитесь общего мигания индикаторов и сразу зажмите Reset до 2 коротких + 3 длинных красных миганий и постоянного красного. Если момент пропущен: питание OFF -> ON, через примерно 1 секунду зажмите Reset на 5-10 секунд до красной последовательности.",
        "Wait for the installed system to boot. For advanced service later, hold Reset at UrsusBoot entry until the red LED pattern completes, then open http://192.168.1.1. If the PC network was configured manually, restore its normal settings afterwards.",
    )
    try:
        uw.reboot(RECOVERY_HOST)
    except Exception:
        pass
    say(tr("[ГОТОВО] Установка завершена.", "[READY] Installation completed."))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(tr("\n[СТОП] Остановлено пользователем.", "\n[STOP] Stopped by user."))
        raise SystemExit(130)
    except Exception as exc:
        print(tr("\n[ОШИБКА] Операция не завершена.", "\n[ERROR] Operation did not complete."), file=sys.stderr)
        proven._write_session_only("[TECH] " + repr(exc))
        print(tr("Технические подробности записаны в лог сеанса.", "Technical details were written to the session log."), file=sys.stderr)
        raise SystemExit(1)

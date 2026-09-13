#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import console_ui as ui
import proven_backend as proven
import uart_bootarea_restore as uart

BAUD = 115200
LOADADDR = 0x85000000
EXPECTED_BOARD = "XG140GMC2P5G"
EXPECTED_USER = "telecomadmin"
EXPECTED_PASSWORD = "nE7jA%5m"
FIT_MAGIC = bytes.fromhex("d00dfeed")


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def choose_image() -> Path:
    raw = ui.prompt(tr(
        "Путь к XG-140G-MD initramfs-uImage.itb (можно перетащить файл сюда): ",
        "Path to the XG-140G-MD initramfs-uImage.itb (drag/drop is OK): ",
    )).strip().strip('"')
    if not raw:
        raise proven.Error(tr("Файл не выбран.", "No file was selected."))
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise proven.Error(tr(f"Файл не найден: {path}", f"File not found: {path}"))
    data = path.read_bytes()[:4]
    if data != FIT_MAGIC:
        raise proven.Error(tr(
            f"Файл не похож на FIT/uImage.itb: magic={data.hex() or '<empty>'}, нужен d00dfeed.",
            f"The file is not a FIT/uImage.itb: magic={data.hex() or '<empty>'}, expected d00dfeed.",
        ))
    size = path.stat().st_size
    if size < 1024 * 1024 or size > 64 * 1024 * 1024:
        raise proven.Error(tr(
            f"Неправдоподобный размер initramfs: {size} bytes.",
            f"Implausible initramfs size: {size} bytes.",
        ))
    return path


def _send_line(sp: proven.RecoverySerial, text: str = "") -> None:
    sp.write(text.encode("ascii", "strict") + b"\r")


def _print_and_log(log, data: bytes) -> str:
    if not data:
        return ""
    log.write(data)
    log.flush()
    text = data.decode("utf-8", "replace")
    print(text, end="", flush=True)
    return text


def acquire_stock_tcboot(sp: proven.RecoverySerial, log, timeout: float = 90.0) -> str:
    ui.status("UART", tr(
        "Закройте MobaXterm/другие программы, использующие COM. Выключите и включите ONU. Скрипт сам остановит autoboot и войдёт в tcboot.",
        "Close MobaXterm/other programs using the COM port. Power-cycle the ONU. The script will stop autoboot and log into tcboot automatically.",
    ))
    deadline = time.time() + timeout
    transcript = ""
    sent_break = False
    sent_user = False
    sent_password = False
    last_cr = 0.0

    while time.time() < deadline:
        data = sp.read(4096, 0.20)
        text = _print_and_log(log, data)
        if text:
            transcript = (transcript + text)[-32768:]

        low = transcript.lower()
        if "starting kernel" in low or "booting linux on physical cpu" in low:
            raise proven.Error(tr(
                "Autoboot не был остановлен. Перезапустите тест и снова выключите/включите ONU.",
                "Autoboot was not stopped. Restart the test and power-cycle the ONU again.",
            ))

        if "hit any key to stop autoboot" in low and not sent_break:
            sp.write(b"\r")
            sent_break = True
            last_cr = time.time()
            continue

        # Some tcboot builds expose the auth prompt only after an extra CR.
        if sent_break and not sent_user and "username:" not in low and time.time() - last_cr > 0.8:
            sp.write(b"\r")
            last_cr = time.time()

        if "username:" in low and not sent_user:
            _send_line(sp, EXPECTED_USER)
            sent_user = True
            transcript = ""
            continue

        if "password:" in low and sent_user and not sent_password:
            _send_line(sp, EXPECTED_PASSWORD)
            sent_password = True
            transcript = ""
            continue

        if "ecnt>" in low:
            return transcript

    raise proven.Error(tr(
        "Не удалось получить ECNT> за 90 секунд. Проверьте TX/RX/GND, 115200 8N1 и что COM-порт не занят.",
        "ECNT> was not obtained within 90 seconds. Check TX/RX/GND, 115200 8N1 and that the COM port is free.",
    ))


def command(sp: proven.RecoverySerial, log, cmd: str, timeout: float = 30.0) -> str:
    print(f"\n[tcboot] {cmd}")
    sp.reset_input()
    _send_line(sp, cmd)
    deadline = time.time() + timeout
    buf = ""
    while time.time() < deadline:
        data = sp.read(4096, 0.20)
        text = _print_and_log(log, data)
        if text:
            buf += text
            if "ECNT>" in buf:
                return buf
    raise proven.Error(tr(
        f"tcboot не вернул ECNT> после команды: {cmd}",
        f"tcboot did not return ECNT> after command: {cmd}",
    ))


def verify_board_from_boot(log_path: Path) -> None:
    text = log_path.read_bytes().decode("utf-8", "replace")
    if f"boardid:{EXPECTED_BOARD}" not in text and f"RI_boardid:{EXPECTED_BOARD}" not in text:
        raise proven.Error(tr(
            f"Не подтверждён boardid {EXPECTED_BOARD}. RAM boot остановлен без записи NAND.",
            f"boardid {EXPECTED_BOARD} was not confirmed. RAM boot stopped without writing NAND.",
        ))
    if "dram_type = PCDDR4" not in text or "DRAM:  512 MiB" not in text:
        raise proven.Error(tr(
            "Не подтверждён ожидаемый XG140 fingerprint: PCDDR4 + 512 MiB. RAM boot остановлен.",
            "Expected XG140 fingerprint PCDDR4 + 512 MiB was not confirmed. RAM boot stopped.",
        ))


def stream_boot(sp: proven.RecoverySerial, log, timeout: float = 180.0) -> None:
    ui.status("RAM", tr(
        "Запускаю initramfs командой bootm. Flash/NAND не изменяется.",
        "Booting initramfs with bootm. Flash/NAND is not modified.",
    ))
    sp.reset_input()
    _send_line(sp, f"bootm 0x{LOADADDR:x}")
    deadline = time.time() + timeout
    seen_linux = False
    while time.time() < deadline:
        data = sp.read(4096, 0.25)
        text = _print_and_log(log, data)
        low = text.lower()
        if "starting kernel" in low or "linux version" in low:
            seen_linux = True
        if "please press enter to activate this console" in low:
            sp.write(b"\r")
        if "root@openwrt" in low or "openwrt login:" in low:
            ui.status("OPENWRT", tr("Initramfs загрузился из RAM.", "Initramfs booted from RAM."))
            return
    if seen_linux:
        ui.status("OPENWRT", tr(
            "Linux стартовал; автоматический детектор приглашения не сработал. Смотрите UART-лог.",
            "Linux started; the automatic prompt detector did not fire. Check the UART log.",
        ))
        return
    raise proven.Error(tr(
        "После bootm не увиден старт Linux за 180 секунд. NAND не изменялась.",
        "Linux start was not observed within 180 seconds after bootm. NAND was not modified.",
    ))


def main() -> int:
    ui.enable()
    ui.banner("UrsusFlasher XG-140G-MD RAM TEST")
    ui.rule(tr("ТОЛЬКО RAM / БЕЗ ЗАПИСИ NAND", "RAM ONLY / NO NAND WRITES"), style="amber2")
    print(f"  Model: Nokia/Bell XG-140G-MD")
    print(f"  Board ID gate: {EXPECTED_BOARD}")
    print(f"  UART: {BAUD} 8N1")
    print(f"  Load address: 0x{LOADADDR:x}")
    ui.note(tr(
        "Скрипт не вызывает flash write/erase, nand scrub/markbad, saveenv, bootflag swap, swimg или chpart.",
        "The script never calls flash write/erase, nand scrub/markbad, saveenv, bootflag swap, swimg or chpart.",
    ))

    image = choose_image()
    image_sha = sha256(image)
    ui.status("IMAGE", f"{image.name} · {image.stat().st_size} bytes")
    ui.status("SHA256", image_sha)

    port = uart.choose_port()
    if not port:
        raise proven.Error(tr("UART-порт не выбран.", "No UART port selected."))
    proven.probe_serial_port(port)

    results = HERE.parent / "results"
    results.mkdir(parents=True, exist_ok=True)
    log_path = results / time.strftime("xg140-initramfs-uart-%Y%m%d-%H%M%S.log")
    log = log_path.open("ab", buffering=0)
    sp = proven.RecoverySerial(port)
    try:
        acquire_stock_tcboot(sp, log)
        verify_board_from_boot(log_path)

        env = command(sp, log, "printenv", timeout=25)
        required = (
            "bootcmd=flash imgread c0000 2048;bootm",
            "dram_limit=512M",
            "username=telecomadmin",
            "soc=en7523",
        )
        missing = [item for item in required if item not in env]
        if missing:
            raise proven.Error(tr(
                "Stock tcboot fingerprint неполный: " + ", ".join(missing),
                "Stock tcboot fingerprint is incomplete: " + ", ".join(missing),
            ))
        command(sp, log, "bootflag read", timeout=15)

        ui.status("TRANSFER", tr(
            f"XMODEM -> RAM 0x{LOADADDR:x}. Для ~7-8 MiB это может занять несколько минут.",
            f"XMODEM -> RAM 0x{LOADADDR:x}. A ~7-8 MiB image may take several minutes.",
        ))
        proven._uboot_wait_quiet(sp, log, quiet=0.15, timeout=1.0)
        sp.reset_input()
        proven._uboot_send_line(sp, f"loadx 0x{LOADADDR:x}")
        time.sleep(0.35)
        proven.xmodem_send(sp, image, image.name, log)
        proven._uboot_read_until_prompt(sp, log, 900, f"loadx {image.name}")

        info = command(sp, log, f"iminfo 0x{LOADADDR:x}", timeout=30)
        gates = ("FIT image found", "Architecture: AArch64", "OS:           Linux")
        missing = [gate for gate in gates if gate not in info]
        if missing:
            raise proven.Error(tr(
                "iminfo не подтвердил ожидаемый AArch64 Linux FIT: " + ", ".join(missing),
                "iminfo did not confirm the expected AArch64 Linux FIT: " + ", ".join(missing),
            ))

        ui.status("VERIFIED", tr(
            "FIT принят tcboot. Следующий шаг — bootm из RAM; persistent flash остаётся нетронутой.",
            "tcboot accepted the FIT. Next step is bootm from RAM; persistent flash remains untouched.",
        ))
        stream_boot(sp, log)
        print()
        ui.status("LOG", str(log_path))
        ui.note(tr(
            "Для возврата к stock достаточно перезагрузить/выключить питание: initramfs находился только в RAM.",
            "To return to stock, reboot or power-cycle the device: the initramfs existed only in RAM.",
        ))
        return 0
    finally:
        try:
            sp.close()
        finally:
            log.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise SystemExit(130)
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

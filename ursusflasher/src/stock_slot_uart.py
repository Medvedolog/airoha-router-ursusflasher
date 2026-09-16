#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import console_ui as ui
import proven_backend as proven

FLAG_OFFSET = 0x05240000
FLAG_SIZE = 0x00040000
RAM_EXPECTED = 0x90000000
RAM_ORIGINAL = 0x90040000
RAM_READBACK = 0x90080000


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def _choose_port() -> str:
    ports = proven.list_serial_ports()
    if ports:
        print(tr("Обнаруженные UART-порты:", "Detected UART ports:"))
        for index, item in enumerate(ports, 1):
            print(f"  {index}. {item}")
    else:
        print(tr("UART-порты автоматически не обнаружены.", "No UART ports were detected automatically."))
    entered = ui.prompt(tr(
        "UART-порт или номер в списке: ",
        "UART port or list number: ",
    )).strip()
    if entered.isdigit() and ports and 1 <= int(entered) <= len(ports):
        port = ports[int(entered) - 1]
    else:
        port = entered.upper() if os.name == "nt" else entered
    if not port:
        raise proven.Error(tr("UART-порт не указан", "UART port was not specified"))
    proven.probe_serial_port(port)
    print(tr(f"[OK] {port}: 115200 8N1.", f"[OK] {port}: 115200 8N1."))
    return port


def _console_write(data: bytes, log) -> None:
    if not data:
        return
    log.write(data)
    try:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    except Exception:
        print(data.decode("utf-8", errors="replace"), end="", flush=True)


def _acquire_uboot_prompt(serial_port: proven.RecoverySerial, log, timeout: float = 120.0) -> None:
    """Acquire an interactive stock/Ursus/OpenWrt U-Boot prompt.

    An already stopped U-Boot/tcboot shell is often silent until it receives CR,
    so first do a short passive read: if no boot-menu text is visible, send one
    empty line (Enter) to make the prompt appear. If a boot menu/autoboot banner
    is visible, never press Enter because it may select the highlighted item;
    use the proven Ctrl-C/ESC break sequence instead.
    """
    print(tr(
        "[READY] Ловлю U-Boot по UART. Если shell уже остановлен и молчит, UrsusFlasher сам пошлёт Enter; если идёт boot menu — перехватит его без выбора пункта.",
        "[READY] Waiting for U-Boot over UART. If an already-stopped shell is silent, UrsusFlasher will send Enter itself; if a boot menu is active it will intercept it without selecting an item.",
    ))
    try:
        serial_port.reset_input()
    except Exception:
        pass

    # First inspect the line briefly. A stopped shell may have printed its prompt
    # before we opened COM and therefore gives us no bytes until CR is sent.
    initial = bytearray()
    passive_deadline = time.time() + 0.45
    while time.time() < passive_deadline:
        data = serial_port.read(4096, 0.10)
        if data:
            _console_write(data, log)
            initial.extend(data)
    low_initial = bytes(initial).lower()
    menu_visible = (
        b"u-boot boot menu" in low_initial
        or b"press up/down" in low_initial
        or b"hit any key to stop autoboot" in low_initial
    )
    if proven._uboot_prompt_present(bytes(initial)):
        print(tr("\n[OK] U-Boot prompt уже виден.", "\n[OK] U-Boot prompt is already visible."))
        return
    if not menu_visible:
        print(tr("[UART] Посылаю Enter, чтобы проявить молчащий U-Boot prompt.", "[UART] Sending Enter to reveal a silent U-Boot prompt."))
        proven._uboot_send_line(serial_port, "")
    else:
        proven._uboot_send_break(serial_port, menu_visible=True)

    deadline = time.time() + timeout
    tail = bytearray(initial)
    uboot_seen = bool(menu_visible or b"u-boot" in low_initial)
    last_break = 0.0
    last_wake = time.time()
    while time.time() < deadline:
        data = serial_port.read(4096, 0.20)
        if data:
            _console_write(data, log)
            tail.extend(data)
            if len(tail) > 16384:
                del tail[:-16384]
            low = bytes(tail).lower()
            if proven._uboot_prompt_present(bytes(tail)):
                try:
                    proven._uboot_wait_quiet(serial_port, log, quiet=0.35, timeout=3.0)
                except Exception:
                    pass
                try:
                    serial_port.reset_input()
                except Exception:
                    pass
                print(tr("\n[OK] Устойчивый U-Boot prompt получен.", "\n[OK] Stable U-Boot prompt acquired."))
                return
            if (b"u-boot" in low or b"hit any key to stop autoboot" in low or
                    b"u-boot boot menu" in low or b"press up/down" in low):
                uboot_seen = True
                menu_visible = (
                    b"u-boot boot menu" in low
                    or b"press up/down" in low
                    or b"hit any key to stop autoboot" in low
                )
        now = time.time()
        if uboot_seen and menu_visible and now - last_break >= 0.20:
            proven._uboot_send_break(serial_port, menu_visible=True)
            last_break = now
        elif not menu_visible and now - last_wake >= 2.0:
            # A stopped shell can remain silent after opening COM. Re-issuing an
            # empty line is non-destructive at the command prompt and makes it
            # print the prompt again.
            proven._uboot_send_line(serial_port, "")
            last_wake = now
    raise proven.Error(tr(
        "U-Boot prompt не получен. Проверьте UART и повторите с перезагрузкой роутера.",
        "U-Boot prompt was not acquired. Check UART and retry while resetting the router.",
    ))


def _parse_words(transcript: bytes, address: int) -> tuple[int, int, int, int]:
    text = transcript.decode("utf-8", errors="ignore")
    addr = f"{address:08x}"
    match = re.search(
        rf"(?im)^\s*(?:0x)?{addr}\s*:\s*([0-9a-f]{{8}})\s+([0-9a-f]{{8}})\s+([0-9a-f]{{8}})\s+([0-9a-f]{{8}})",
        text,
    )
    if not match:
        raise proven.Error(tr(
            "не удалось разобрать первые 16 байт stock selector flag",
            "could not parse the first 16 bytes of the stock selector flag",
        ))
    return tuple(int(x, 16) for x in match.groups())  # type: ignore[return-value]


def _validate_flag(words: tuple[int, int, int, int]) -> None:
    active, curimg, startok, count = words
    if active not in (0, 1) or curimg not in (0, 1) or startok not in (0, 1):
        raise proven.Error(tr(
            f"selector не похож на Nokia stock flag: active={active} curimg={curimg} startok={startok}",
            f"selector does not look like a Nokia stock flag: active={active} curimg={curimg} startok={startok}",
        ))
    if count > 0xFFFF:
        raise proven.Error(tr(
            f"selector count вне ожидаемого диапазона: {count}",
            f"selector count is outside the expected range: {count}",
        ))


def _read_flag(serial_port: proven.RecoverySerial, log, ram: int) -> tuple[int, int, int, int]:
    proven.uboot_command(
        serial_port, log,
        f"mtd read spi-nand0 0x{ram:08x} 0x{FLAG_OFFSET:08x} 0x{FLAG_SIZE:08x}",
        timeout=60,
    )
    transcript = proven.uboot_command(serial_port, log, f"md.l 0x{ram:08x} 4", timeout=15)
    words = _parse_words(transcript, ram)
    _validate_flag(words)
    return words


def _print_state(words: tuple[int, int, int, int], prefix: str = "CURRENT") -> None:
    active, curimg, startok, count = words
    slot = "MASTER/SLOT1" if active == 0 else "SLAVE/SLOT2"
    print(f"  {prefix}: active={active} ({slot}) curimg={curimg} startok={startok} count={count}")


def _switch(serial_port: proven.RecoverySerial, log, target_active: int) -> None:
    current = _read_flag(serial_port, log, RAM_EXPECTED)
    active, curimg, startok, count = current
    target_name = "MASTER/SLOT1" if target_active == 0 else "SLAVE/SLOT2"

    ui.rule(tr("STOCK SLOT UART PREFLIGHT", "STOCK SLOT UART PREFLIGHT"), style="amber2")
    _print_state(current)
    print(f"  TARGET : active={target_active} ({target_name})")
    print(tr(
        "  CHANGE : только active; curimg/startok/count и остальные байты flag сохраняются",
        "  CHANGE : active only; curimg/startok/count and all remaining flag bytes are preserved",
    ))
    print(tr(
        "  WRITE  : flag/mtd8 @ 0x05240000, 0x40000; flagback/mtd9 и оба NSB-слота НЕ записываются",
        "  WRITE  : flag/mtd8 @ 0x05240000, 0x40000; flagback/mtd9 and both NSB slots are NOT written",
    ))

    if active == target_active:
        ui.status(tr("ГОТОВО", "READY"), tr(
            f"Уже выбран {target_name}; NAND не изменялся.",
            f"{target_name} is already selected; NAND was not modified.",
        ))
        return

    proven.uboot_command(serial_port, log, f"cp.b 0x{RAM_EXPECTED:08x} 0x{RAM_ORIGINAL:08x} 0x{FLAG_SIZE:08x}", timeout=20)
    proven.uboot_command(serial_port, log, f"mw.l 0x{RAM_EXPECTED:08x} 0x{target_active:08x} 1", timeout=15)
    proven.uboot_command(
        serial_port, log,
        f"cmp.b 0x{RAM_EXPECTED + 4:08x} 0x{RAM_ORIGINAL + 4:08x} 0x{FLAG_SIZE - 4:08x}",
        timeout=30,
    )
    staged = proven.uboot_command(serial_port, log, f"md.l 0x{RAM_EXPECTED:08x} 4", timeout=15)
    staged_words = _parse_words(staged, RAM_EXPECTED)
    if staged_words != (target_active, curimg, startok, count):
        raise proven.Error(tr("RAM selector staging не прошёл проверку", "RAM selector staging verification failed"))

    answer = ui.prompt(tr(
        f"Записать только selector flag и переключить на {target_name}? [y/N]: ",
        f"Write only the selector flag and switch to {target_name}? [y/N]: ",
    )).strip().lower()
    if answer not in ("y", "yes", "д", "да"):
        ui.status(tr("СТОП", "STOP"), tr("NAND не изменялся.", "NAND was not modified."))
        return

    print(tr("[WRITE] erase+write selector flag одним U-Boot transaction command...", "[WRITE] erase+write selector flag in one U-Boot transaction command..."))
    proven.uboot_command(
        serial_port, log,
        f"mtd erase spi-nand0 0x{FLAG_OFFSET:08x} 0x{FLAG_SIZE:08x} && "
        f"mtd write spi-nand0 0x{RAM_EXPECTED:08x} 0x{FLAG_OFFSET:08x} 0x{FLAG_SIZE:08x}",
        timeout=120,
    )

    readback = _read_flag(serial_port, log, RAM_READBACK)
    proven.uboot_command(
        serial_port, log,
        f"cmp.b 0x{RAM_EXPECTED:08x} 0x{RAM_READBACK:08x} 0x{FLAG_SIZE:08x}",
        timeout=30,
    )
    expected_words = (target_active, curimg, startok, count)
    if readback != expected_words:
        raise proven.Error(tr(
            f"selector readback не совпал: {readback} != {expected_words}",
            f"selector readback mismatch: {readback} != {expected_words}",
        ))

    ui.status(tr("ГОТОВО", "READY"), tr(
        f"Selector записан и полностью проверен: {target_name}. Перезагружаю роутер.",
        f"Selector was written and fully verified: {target_name}. Rebooting the router.",
    ))
    print(f"URSUS_STOCKSLOT_UART_DONE target={'master' if target_active == 0 else 'slave'} active={target_active} readback=PASS next=RESET")
    proven._uboot_send_line(serial_port, "reset")


def run() -> None:
    ui.rule(tr("ПЕРЕКЛЮЧЕНИЕ STOCK SLOT ЧЕРЕЗ UART", "SWITCH STOCK SLOT OVER UART"), style="amber2")
    ui.note(tr(
        "Работает без Web/SSH. Нужен USB-UART 3.3 V (GND/TX/RX, VCC не подключать) и доступный U-Boot/tcboot shell.",
        "Works without Web/SSH. Requires a 3.3 V USB-UART (GND/TX/RX; do not connect VCC) and an accessible U-Boot/tcboot shell.",
    ))
    print(tr("  1 — MASTER / SLOT1", "  1 — MASTER / SLOT1"))
    print(tr("  2 — SLAVE / SLOT2", "  2 — SLAVE / SLOT2"))
    print(tr("  3 — Только показать selector", "  3 — Show selector only"))
    print(tr("  0 — Отмена", "  0 — Cancel"))
    choice = ui.prompt(tr("Выбор: ", "Choice: ")).strip()
    if choice == "0":
        return
    if choice not in ("1", "2", "3"):
        raise proven.Error(tr("неверный выбор", "invalid choice"))

    port = _choose_port()
    log_dir = Path(proven.WORK) / "uart-stockslot"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / time.strftime("stockslot-%Y%m%d-%H%M%S.log")
    serial_port = proven.RecoverySerial(port)
    try:
        with log_path.open("ab", buffering=0) as log:
            _acquire_uboot_prompt(serial_port, log)
            if choice == "3":
                words = _read_flag(serial_port, log, RAM_EXPECTED)
                ui.rule(tr("STOCK SELECTOR", "STOCK SELECTOR"), style="ok")
                _print_state(words)
                print(tr(f"Лог: {log_path}", f"Log: {log_path}"))
                return
            _switch(serial_port, log, 0 if choice == "1" else 1)
            print(tr(f"Лог: {log_path}", f"Log: {log_path}"))
    finally:
        serial_port.close()

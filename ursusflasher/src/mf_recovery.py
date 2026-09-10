#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import console_ui as ui
import proven_backend as proven
import ui_terms as terms

BOARD = "Nokia XG-040G-MF"
SOC = "Airoha AN7583"
MTD = "spi-nand0"
BOOT_AREA_SIZE = 0x80000
ERASE_SIZE = 0x20000
PAGE_SIZE = 0x800
LOADADDR = 0x90000000
READBACK_ADDR = 0x91000000
EXPECTED_PRELOADER_SIZE = 118322
EXPECTED_PRELOADER_SHA256 = "c2ac1c183b18bc34632c958dfe0bd1dfdfb607f090e39c41126956641893362f"


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def choose_port() -> str:
    ports = proven.list_serial_ports()
    if ports:
        print(tr("\nUART-порты:", "\nUART ports:"))
        for i, port in enumerate(ports, 1):
            print(f"  {i}. {port}")
    raw = input(tr("UART-порт или номер: ", "UART port or list number: ")).strip()
    if raw.isdigit() and ports and 1 <= int(raw) <= len(ports):
        return ports[int(raw) - 1]
    return raw.upper() if os.name == "nt" else raw


def _one(directory: Path, pattern: str, label: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise proven.Error(f"{label}: expected exactly one {pattern} in {directory}, got {[p.name for p in matches]}")
    return matches[0]


def resolve_payloads(artifact_dir: Path | None, preloader: Path | None, fip: Path | None) -> tuple[Path, Path]:
    if preloader and fip:
        return preloader.resolve(), fip.resolve()
    candidates: list[Path] = []
    if artifact_dir:
        candidates.append(artifact_dir.resolve())
    repo_root = HERE.parent.parent
    candidates.extend([
        repo_root / "work" / "mf-ramboot" / "out",
        repo_root / "payloads" / "mf" / "ursusboot",
        HERE / "payloads" / "mf" / "ursusboot",
    ])
    for directory in candidates:
        if not directory.is_dir():
            continue
        try:
            return (
                preloader.resolve() if preloader else _one(directory, "*uart-preloader.bin", "MF UART preloader"),
                fip.resolve() if fip else _one(directory, "*ram.fip", "MF RAM FIP"),
            )
        except proven.Error:
            continue
    raise proven.Error(tr(
        "Не найдены RAM payloads. Укажите --artifact-dir либо --preloader и --fip.",
        "RAM payloads were not found. Supply --artifact-dir or both --preloader and --fip.",
    ))


def verify_payloads(preloader: Path, fip: Path) -> None:
    if not preloader.is_file() or not fip.is_file():
        raise proven.Error("RAM payload file missing")
    if preloader.stat().st_size != EXPECTED_PRELOADER_SIZE:
        raise proven.Error(f"MF preloader size mismatch: {preloader.stat().st_size}")
    pre_sha = sha256(preloader)
    if pre_sha != EXPECTED_PRELOADER_SHA256:
        raise proven.Error(f"MF preloader SHA256 mismatch: {pre_sha}")
    data = fip.read_bytes()
    if len(data) < 0x10000 or len(data) >= BOOT_AREA_SIZE:
        raise proven.Error(f"MF RAM FIP size is implausible: 0x{len(data):x}")
    if data[:8] != bytes.fromhex("010064aa78563412"):
        raise proven.Error("MF RAM FIP header is invalid")
    ui.status("PAYLOAD", f"{preloader.name} · SHA256 {pre_sha}")
    ui.status("PAYLOAD", f"{fip.name} · {len(data)} bytes · SHA256 {sha256(fip)}")


def validate_boot_area(image: Path) -> dict:
    image = image.resolve()
    if not image.is_file():
        raise proven.Error(tr(f"Файл не найден: {image}", f"File not found: {image}"))
    size = image.stat().st_size
    if size != BOOT_AREA_SIZE:
        raise proven.Error(f"boot-area image must be exactly 0x{BOOT_AREA_SIZE:x} bytes, got 0x{size:x}")
    with image.open("rb") as fh:
        fh.seek(0x800)
        fip_magic = fh.read(8)
    digest = sha256(image)
    return {
        "path": image,
        "size": size,
        "sha256": digest,
        "stock_fip_magic": fip_magic == bytes.fromhex("010064aa78563412"),
    }


def _decode(data: bytes) -> str:
    return data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")


def _run(sp: proven.RecoverySerial, log, command: str, timeout: int = 30) -> bytes:
    print(f"[U-Boot] {command}")
    return proven.uboot_command(sp, log, command, timeout=timeout)


def _loadx(sp: proven.RecoverySerial, log, image: Path, addr: int) -> None:
    proven._uboot_wait_quiet(sp, log, quiet=0.15, timeout=1.0)
    sp.reset_input()
    proven._uboot_send_line(sp, f"loadx 0x{addr:x}")
    time.sleep(0.35)
    proven.xmodem_send(sp, image, image.name, log)
    proven._uboot_read_until_prompt(sp, log, 90, f"loadx {image.name}")


def _bad_blocks_in_boot_area(text: str) -> list[int]:
    offsets = []
    for line in text.splitlines():
        line = line.strip()
        if re.fullmatch(r"0x[0-9a-fA-F]+", line):
            value = int(line, 16)
            if value < BOOT_AREA_SIZE:
                offsets.append(value)
    return offsets


def boot_ram(preloader: Path, fip: Path, port: str | None = None) -> tuple[proven.RecoverySerial, object, Path]:
    verify_payloads(preloader, fip)
    port = port or choose_port()
    if not port:
        raise proven.Error(tr("UART-порт не указан", "UART port was not specified"))
    proven.probe_serial_port(port)
    results = HERE.parent / "results"
    results.mkdir(parents=True, exist_ok=True)
    log_path = results / time.strftime("mf-ram-recovery-%Y%m%d-%H%M%S-uart.log")
    log = log_path.open("ab", buffering=0)
    sp = proven.RecoverySerial(port)
    try:
        ui.status("UART", tr(
            "Удерживайте Reset ДО включения питания и продолжайте держать до Press x / C.",
            "Hold Reset BEFORE power-on and keep it held until Press x / C.",
        ))
        proven.wait_bootrom_xmodem(sp, log, "AN7583 preloader", discard_stale=False)
        proven.xmodem_send(sp, preloader, "UrsusBoot MF UART preloader", log)
        proven.wait_bootrom_xmodem(sp, log, "UrsusBoot MF RAM FIP")
        proven.xmodem_send(sp, fip, "UrsusBoot MF RAM FIP", log)
        if proven.wait_uboot_prompt(sp, log) != "prompt":
            raise proven.Error(tr(
                "Консоль UrsusBoot из RAM не перехвачена; NAND не изменялась.",
                "The RAM UrsusBoot console was not captured; NAND was not modified.",
            ))
        version = _run(sp, log, "version", timeout=20)
        print(_decode(version))
        return sp, log, log_path
    except Exception:
        sp.close()
        log.close()
        raise


def restore_boot_area(image: Path, preloader: Path, fip: Path, port: str | None = None) -> None:
    meta = validate_boot_area(image)
    ui.rule(tr("MF: АВАРИЙНОЕ ВОССТАНОВЛЕНИЕ BOOT AREA", "MF: EMERGENCY BOOT-AREA RESTORE"), style="red")
    ui.status("TARGET", f"{BOARD} / {SOC}")
    ui.status("SOURCE", f"{meta['path'].name} · 0x{meta['size']:x} · SHA256 {meta['sha256']}")
    if meta["stock_fip_magic"]:
        ui.note(tr("В образе найден stock-style Airoha FIP на 0x800.", "A stock-style Airoha FIP was found at 0x800."))
    else:
        ui.note(tr("FIP на 0x800 не распознан. Для аварийного raw restore это предупреждение, а не запрет.",
                   "No FIP was recognized at 0x800. For emergency raw restore this is a warning, not a blocker."))

    sp, log, log_path = boot_ram(preloader, fip, port)
    try:
        mtd_list = _decode(_run(sp, log, "mtd list", timeout=30))
        print(mtd_list)
        if MTD not in mtd_list:
            raise proven.Error(f"{MTD} is not present in U-Boot MTD list")
        if "block size: 0x20000" not in mtd_list.lower() or "min i/o: 0x800" not in mtd_list.lower():
            raise proven.Error(tr(
                "Геометрия SPI-NAND не совпала с ожидаемой 0x20000/0x800; запись не начиналась.",
                "SPI-NAND geometry does not match expected 0x20000/0x800; no write was started.",
            ))

        bad_text = _decode(_run(sp, log, f"mtd bad {MTD}", timeout=60))
        print(bad_text)
        boot_bad = _bad_blocks_in_boot_area(bad_text)
        if boot_bad:
            raise proven.Error(tr(
                "В первых 0x80000 есть factory/runtime bad block: " + ", ".join(f"0x{x:x}" for x in boot_bad) + ". Автоматический raw restore остановлен.",
                "A factory/runtime bad block exists in the first 0x80000: " + ", ".join(f"0x{x:x}" for x in boot_bad) + ". Automatic raw restore stopped.",
            ))

        ui.status("RAM", tr("Передаю boot-area в RAM через XMODEM; flash пока не изменяется.",
                            "Transferring boot-area to RAM with XMODEM; flash is still unchanged."))
        _loadx(sp, log, meta["path"], LOADADDR)

        print()
        ui.rule(tr("ПЕРЕД ЗАПИСЬЮ", "BEFORE WRITE"), style="red")
        print(f"  {tr('Устройство', 'Device')}: {BOARD} / {SOC}")
        print(f"  NAND: {MTD}, erase=0x{ERASE_SIZE:x}, page=0x{PAGE_SIZE:x}")
        print(f"  {tr('Источник', 'Source')}: {meta['path']}")
        print(f"  SHA256: {meta['sha256']}")
        print(f"  {tr('Назначение', 'Destination')}: physical NAND 0x000000..0x07ffff")
        print("  " + tr("Будут стерты и полностью перезаписаны первые 512 KiB NAND.",
                         "The first 512 KiB of NAND will be erased and completely rewritten."))
        ans = ui.prompt(tr("Начать восстановление? [д/Н]: ", "Start restore? [y/N]: ")).strip().lower()
        if ans not in ("д", "да", "y", "yes"):
            ui.status("STOP", tr("Запись отменена; NAND не изменялась.", "Restore cancelled; NAND was not modified."))
            return

        _run(sp, log, f"mtd erase {MTD} 0 0x{BOOT_AREA_SIZE:x}", timeout=120)
        _run(sp, log, f"mtd write {MTD} 0x{LOADADDR:x} 0 0x{BOOT_AREA_SIZE:x}", timeout=180)
        _run(sp, log, f"mtd read {MTD} 0x{READBACK_ADDR:x} 0 0x{BOOT_AREA_SIZE:x}", timeout=180)
        _run(sp, log, f"cmp.b 0x{LOADADDR:x} 0x{READBACK_ADDR:x} 0x{BOOT_AREA_SIZE:x}", timeout=60)
        hash_out = _decode(_run(sp, log, f"hash sha256 0x{READBACK_ADDR:x} 0x{BOOT_AREA_SIZE:x}", timeout=60))
        print(hash_out)
        hashes = [x.lower() for x in re.findall(r"\b[0-9a-fA-F]{64}\b", hash_out)]
        if hashes and meta["sha256"].lower() not in hashes:
            raise proven.Error(f"readback SHA256 mismatch: expected {meta['sha256']}, U-Boot reported {hashes[-1]}")

        ui.status("ГОТОВО", tr("Boot-area записана и совпала с RAM-источником byte-for-byte.",
                               "Boot-area was written and matches the RAM source byte-for-byte."))
        ui.status("SHA256", meta["sha256"])
        ui.note(tr(
            "Не используйте reset-команду для проверки. Полностью выключите питание, отпустите Reset и включите Nokia обычным способом; смотрите UART.",
            "Do not use the reset command for the acceptance check. Power the Nokia fully off, release Reset, then power it on normally and watch UART.",
        ))
    finally:
        sp.close()
        log.close()
        ui.status("LOG", str(log_path))


def main() -> int:
    parser = argparse.ArgumentParser(description="UrsusBoot MF UART RAM recovery")
    parser.add_argument("--artifact-dir", type=Path, help="directory containing *uart-preloader.bin and *ram.fip")
    parser.add_argument("--preloader", type=Path)
    parser.add_argument("--fip", type=Path)
    parser.add_argument("--restore-boot-area", type=Path, metavar="MTD0_BIN")
    parser.add_argument("--port", help="UART port, e.g. COM5 or /dev/ttyUSB0")
    args = parser.parse_args()

    proven.start_session_logging()
    ui.enable()
    preloader, fip = resolve_payloads(args.artifact_dir, args.preloader, args.fip)
    if args.restore_boot_area:
        restore_boot_area(args.restore_boot_area, preloader, fip, args.port)
        return 0

    sp, log, log_path = boot_ram(preloader, fip, args.port)
    ui.status("READY", tr(
        "UrsusBoot работает из RAM. NAND не изменялась. Для raw restore используйте --restore-boot-area.",
        "UrsusBoot is running from RAM. NAND was not modified. Use --restore-boot-area for raw restore.",
    ))
    ui.status("LOG", str(log_path))
    # Leave the UART session open interactively only when launched from a terminal.
    try:
        while True:
            data = sp.read(4096, 0.2)
            if data:
                print(data.decode("utf-8", "replace"), end="", flush=True)
            if not sys.stdin.isatty():
                break
    except KeyboardInterrupt:
        pass
    finally:
        sp.close(); log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

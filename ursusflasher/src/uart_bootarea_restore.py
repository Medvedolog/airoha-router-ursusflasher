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

BOOT_AREA_SIZE = 0x80000
ERASE_SIZE = 0x20000
PAGE_SIZE = 0x800
MTD = "spi-nand0"
LOADADDR = 0x90000000
READBACK_ADDR = 0x91000000
FIP_MAGIC = bytes.fromhex("010064aa78563412")

MD_PRELOADER_SHA = "6c3b2339d036340396730a13adfe35c0d2a4dddedeffb6f9965a24e0c7908808"
MD_RAM_FIP_SHA = "dc08ed0be1b1d68f6bc247ae45293e6ab0ca9df7695541b664e4060a145228c8"
MF_PRELOADER_SHA = "c2ac1c183b18bc34632c958dfe0bd1dfdfb607f090e39c41126956641893362f"
MF_RAM_FIP_SHA = "ef10bb7f712f4eb0313e7886ac744a6592c35cc1be126ef7196be31909c7f374"


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _runtime_payload_root() -> Path:
    repo_root = HERE.parent.parent
    if (repo_root / "payloads").is_dir():
        return repo_root / "payloads"
    return HERE / "payloads"


def _first_existing(candidates: list[Path], label: str) -> Path:
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise proven.Error(tr(
        f"Не найден {label}. Проверены: " + ", ".join(str(x) for x in candidates),
        f"Missing {label}. Checked: " + ", ".join(str(x) for x in candidates),
    ))


def family_profile(family: str) -> dict:
    family = family.strip().lower()
    payloads = _runtime_payload_root()
    if family == "md":
        preloader = _first_existing([
            payloads / "md" / "ursusboot" / "openwrt-airoha-an7581-nokia_xg-040g-md-ubi-preloader.bin",
            HERE / "recovery" / "openwrt-airoha-an7581-nokia_xg-040g-md-ubi-preloader.bin",
        ], "MD UART preloader")
        fip = _first_existing([
            payloads / "md" / "ursusboot" / "ursusboot-md-0.1.0-alpha3-ram-installer.fip",
        ], "MD RAM UrsusBoot FIP")
        return {
            "family": "md", "model": "Nokia XG-040G-MD", "soc": "Airoha AN7581",
            "preloader": preloader, "fip": fip,
            "preloader_sha": MD_PRELOADER_SHA, "fip_sha": MD_RAM_FIP_SHA,
        }
    if family == "mf":
        preloader = _first_existing([
            payloads / "mf" / "recovery" / "ursusboot-mf-0.1.0-TEST61-uart-preloader.bin",
            payloads / "mf" / "ursusboot" / "ursusboot-mf-0.1.0-TEST61-uart-preloader.bin",
            HERE.parent / "work" / "mf-ramboot" / "out" / "ursusboot-mf-0.1.0-TEST61-uart-preloader.bin",
        ], "MF UART preloader")
        fip = _first_existing([
            payloads / "mf" / "recovery" / "ursusboot-mf-0.1.0-TEST61-ram.fip",
            payloads / "mf" / "ursusboot" / "ursusboot-mf-0.1.0-TEST61-ram.fip",
            HERE.parent / "work" / "mf-ramboot" / "out" / "ursusboot-mf-0.1.0-TEST61-ram.fip",
        ], "MF RAM UrsusBoot FIP")
        return {
            "family": "mf", "model": "Nokia XG-040G-MF", "soc": "Airoha AN7583",
            "preloader": preloader, "fip": fip,
            "preloader_sha": MF_PRELOADER_SHA, "fip_sha": MF_RAM_FIP_SHA,
        }
    raise proven.Error(tr("Выберите MD или MF.", "Choose MD or MF."))


def verify_profile(profile: dict) -> None:
    preloader = Path(profile["preloader"])
    fip = Path(profile["fip"])
    got = sha256(preloader)
    if got != profile["preloader_sha"]:
        raise proven.Error(f"{profile['family'].upper()} preloader SHA256 mismatch: {got}")
    got = sha256(fip)
    if got != profile["fip_sha"]:
        raise proven.Error(f"{profile['family'].upper()} RAM FIP SHA256 mismatch: {got}")
    data = fip.read_bytes()
    if len(data) < 0x10000 or len(data) > 0x100000:
        raise proven.Error(f"{profile['family'].upper()} RAM FIP size is implausible: 0x{len(data):x}")
    if data[:8] != FIP_MAGIC:
        raise proven.Error(f"{profile['family'].upper()} RAM FIP header is invalid")
    ui.status("RAM", f"{profile['model']} / {profile['soc']}")
    ui.status("PAYLOAD", f"{preloader.name} · SHA256 {profile['preloader_sha']}")
    ui.status("PAYLOAD", f"{fip.name} · SHA256 {profile['fip_sha']}")


def validate_image(path: Path) -> dict:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise proven.Error(tr(f"Файл не найден: {path}", f"File not found: {path}"))
    size = path.stat().st_size
    if size != BOOT_AREA_SIZE:
        raise proven.Error(tr(
            f"Для этого пункта нужен boot-area ровно 0x80000 (512 КиБ), получено 0x{size:x}.",
            f"This action requires an exact 0x80000-byte (512 KiB) boot-area image, got 0x{size:x}.",
        ))
    with path.open("rb") as fh:
        fh.seek(0x800)
        magic = fh.read(8)
    return {"path": path, "size": size, "sha256": sha256(path), "fip_magic": magic == FIP_MAGIC}


def choose_family() -> str:
    print()
    ui.rule(tr("МОДЕЛЬ NOKIA", "NOKIA MODEL"), style="amber2")
    print("  1. Nokia XG-040G-MD / AN7581")
    print("  2. Nokia XG-040G-MF / AN7583")
    while True:
        raw = ui.prompt(tr("Модель [1/2]: ", "Model [1/2]: ")).strip().lower()
        if raw in ("1", "md"):
            return "md"
        if raw in ("2", "mf"):
            return "mf"
        print(tr("Введите 1 (MD) или 2 (MF).", "Enter 1 (MD) or 2 (MF)."))


def choose_image() -> Path:
    raw = ui.prompt(tr(
        "Путь к рабочему boot-area/mtd0 backup (ровно 512 КиБ): ",
        "Path to a working boot-area/mtd0 backup (exactly 512 KiB): ",
    )).strip().strip('"')
    if not raw:
        raise proven.Error(tr("Файл не выбран.", "No image was selected."))
    return Path(raw)


def choose_port() -> str:
    ports = proven.list_serial_ports()
    if ports:
        print(tr("\nUART-порты:", "\nUART ports:"))
        for i, port in enumerate(ports, 1):
            print(f"  {i}. {port}")
    raw = ui.prompt(tr("UART-порт или номер: ", "UART port or list number: ")).strip()
    if raw.isdigit() and ports and 1 <= int(raw) <= len(ports):
        return ports[int(raw) - 1]
    return raw.upper() if os.name == "nt" else raw


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
    proven._uboot_read_until_prompt(sp, log, 120, f"loadx {image.name}")


def _bad_blocks_in_boot_area(text: str) -> list[int]:
    offsets: list[int] = []
    for line in text.splitlines():
        line = line.strip()
        if re.fullmatch(r"0x[0-9a-fA-F]+", line):
            value = int(line, 16)
            if value < BOOT_AREA_SIZE:
                offsets.append(value)
    return offsets


def boot_ram(profile: dict, port: str | None = None):
    verify_profile(profile)
    port = port or choose_port()
    if not port:
        raise proven.Error(tr("UART-порт не указан.", "UART port was not specified."))
    proven.probe_serial_port(port)
    results = HERE.parent / "results"
    results.mkdir(parents=True, exist_ok=True)
    log_path = results / time.strftime(f"{profile['family']}-uart-bootarea-restore-%Y%m%d-%H%M%S.log")
    log = log_path.open("ab", buffering=0)
    sp = proven.RecoverySerial(port)
    try:
        ui.status("UART", tr(
            "Зажмите Reset ДО включения питания и держите до Press x / C.",
            "Hold Reset BEFORE power-on and keep it held until Press x / C.",
        ))
        proven.wait_bootrom_xmodem(sp, log, f"{profile['soc']} preloader", discard_stale=False)
        proven.xmodem_send(sp, Path(profile["preloader"]), f"{profile['family'].upper()} UART preloader", log)
        proven.wait_bootrom_xmodem(sp, log, f"{profile['family'].upper()} RAM UrsusBoot FIP")
        proven.xmodem_send(sp, Path(profile["fip"]), f"{profile['family'].upper()} RAM UrsusBoot FIP", log)
        if proven.wait_uboot_prompt(sp, log) != "prompt":
            raise proven.Error(tr("RAM U-Boot prompt не перехвачен; NAND не изменялась.", "RAM U-Boot prompt was not captured; NAND was not modified."))
        version = _run(sp, log, "version", timeout=20)
        print(_decode(version))
        return sp, log, log_path
    except Exception:
        sp.close(); log.close()
        raise


def restore(family: str, image: Path, port: str | None = None) -> None:
    profile = family_profile(family)
    meta = validate_image(image)
    ui.rule(tr("UART-ONLY: ВОССТАНОВЛЕНИЕ BOOT-AREA", "UART-ONLY: BOOT-AREA RESTORE"), style="red")
    ui.status("TARGET", f"{profile['model']} / {profile['soc']}")
    ui.status("SOURCE", f"{meta['path'].name} · 0x{meta['size']:x} · SHA256 {meta['sha256']}")
    if meta["fip_magic"]:
        ui.note(tr("На 0x800 найден Airoha FIP. Это диагностический факт, не gate.", "An Airoha FIP was found at 0x800. This is diagnostic only, not a gate."))
    else:
        ui.note(tr("FIP на 0x800 не распознан. Для raw recovery это предупреждение, не запрет.", "No FIP was recognized at 0x800. For raw recovery this is a warning, not a blocker."))
    ui.note(tr(
        "Это аварийный режим: существующая разметка NAND/UBI не используется как источник доверия.",
        "This is an emergency mode: the existing NAND/UBI layout is not used as a trust source.",
    ))

    sp, log, log_path = boot_ram(profile, port)
    try:
        listing = _decode(_run(sp, log, "mtd list", timeout=30))
        print(listing)
        low = listing.lower()
        if MTD not in low:
            raise proven.Error(f"{MTD} is not present in U-Boot MTD list")
        if "block size: 0x20000" not in low or "min i/o: 0x800" not in low:
            raise proven.Error(tr(
                "Физическая геометрия NAND не 0x20000/0x800; raw write остановлен.",
                "Physical NAND geometry is not 0x20000/0x800; raw write stopped.",
            ))

        bad_text = _decode(_run(sp, log, f"mtd bad {MTD}", timeout=60))
        print(bad_text)
        boot_bad = _bad_blocks_in_boot_area(bad_text)
        if boot_bad:
            raise proven.Error(tr(
                "В первых 0x80000 есть bad eraseblock: " + ", ".join(f"0x{x:x}" for x in boot_bad) + ". Нужен ручной recovery с учётом bad-block map.",
                "A bad eraseblock exists in the first 0x80000: " + ", ".join(f"0x{x:x}" for x in boot_bad) + ". Manual recovery with explicit bad-block handling is required.",
            ))

        ui.status("RAM", tr("Передаю выбранный boot-area через XMODEM; NAND пока не изменяется.", "Transferring the selected boot-area through XMODEM; NAND is still unchanged."))
        _loadx(sp, log, meta["path"], LOADADDR)

        print()
        ui.rule(tr("ПЕРЕД ЗАПИСЬЮ", "BEFORE WRITE"), style="red")
        print(f"  {tr('Модель', 'Model')}: {profile['model']} / {profile['soc']}")
        print(f"  NAND: {MTD}, erase=0x{ERASE_SIZE:x}, page=0x{PAGE_SIZE:x}")
        print(f"  {tr('Файл', 'File')}: {meta['path']}")
        print(f"  SHA256: {meta['sha256']}")
        print(f"  {tr('Диапазон', 'Range')}: physical NAND 0x000000..0x07ffff")
        ui.note(tr(
            "Будут стёрты и полностью перезаписаны только первые 512 КиБ NAND. Остальная NAND не затрагивается.",
            "Only the first 512 KiB of NAND will be erased and rewritten. The rest of NAND is untouched.",
        ))
        ans = ui.prompt(tr("Начать восстановление? [д/Н]: ", "Start restore? [y/N]: ")).strip().lower()
        if ans not in ("д", "да", "y", "yes"):
            ui.status("STOP", tr("Запись отменена; NAND не изменялась.", "Restore cancelled; NAND was not modified."))
            return

        _run(sp, log, f"mtd erase {MTD} 0 0x{BOOT_AREA_SIZE:x}", timeout=120)
        _run(sp, log, f"mtd write {MTD} 0x{LOADADDR:x} 0 0x{BOOT_AREA_SIZE:x}", timeout=180)
        _run(sp, log, f"mtd read {MTD} 0x{READBACK_ADDR:x} 0 0x{BOOT_AREA_SIZE:x}", timeout=180)
        cmp_out = _decode(_run(sp, log, f"cmp.b 0x{LOADADDR:x} 0x{READBACK_ADDR:x} 0x{BOOT_AREA_SIZE:x}", timeout=90))
        print(cmp_out)
        if "differ" in cmp_out.lower() or "error" in cmp_out.lower():
            raise proven.Error(tr("Readback отличается от RAM source; питание не выключать, сохранить UART-log.", "Readback differs from the RAM source; keep power on and save the UART log."))
        crc_out = _decode(_run(sp, log, f"crc32 0x{READBACK_ADDR:x} 0x{BOOT_AREA_SIZE:x}", timeout=60))
        print(crc_out)

        ui.status("ГОТОВО", tr("Boot-area записана и проверена чтением обратно.", "Boot-area was written and verified by readback."))
        ui.status("SOURCE SHA256", meta["sha256"])
        ui.note(tr(
            "Для проверки полностью выключите питание, отпустите Reset и включите Nokia обычным способом. Не используйте reset из RAM U-Boot.",
            "For acceptance, power the Nokia fully off, release Reset, and power it on normally. Do not use reset from RAM U-Boot.",
        ))
    finally:
        sp.close(); log.close()
        ui.status("LOG", str(log_path))


def interactive() -> None:
    family = choose_family()
    image = choose_image()
    restore(family, image)


def main() -> int:
    parser = argparse.ArgumentParser(description="UART-only MD/MF boot-area restore")
    parser.add_argument("--family", choices=("md", "mf"))
    parser.add_argument("--image", type=Path, metavar="MTD0_BIN")
    parser.add_argument("--port", help="UART port, e.g. COM5 or /dev/ttyUSB0")
    args = parser.parse_args()
    proven.start_session_logging(); ui.enable()
    family = args.family or choose_family()
    image = args.image or choose_image()
    restore(family, image, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shlex

import console_ui as ui
import proven_backend as proven
import stock_ab_transition as transition
import ursusboot_install as ubi


REMOTE_FLAG = "/tmp/ursus-stock-slot-flag.bin"


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def _parse_words(text: str) -> tuple[int, int, int, int]:
    words = re.findall(r"\b([0-9a-fA-F]{8})\b", text)
    if len(words) < 4:
        raise RuntimeError(tr(
            "не удалось разобрать первые 16 байт stock selector flag",
            "could not parse the first 16 bytes of the stock selector flag",
        ))
    out = tuple(int(x, 16) for x in words[-4:])
    active, curimg, startok, count = out
    if active not in (0, 1) or curimg not in (0, 1) or startok not in (0, 1) or count > 0xFFFF:
        raise RuntimeError(tr(
            f"selector не похож на Nokia stock flag: active={active} curimg={curimg} startok={startok} count={count}",
            f"selector does not look like a Nokia stock flag: active={active} curimg={curimg} startok={startok} count={count}",
        ))
    return out  # type: ignore[return-value]


def _read_words(telnet, dev: str) -> tuple[int, int, int, int]:
    rc, text = telnet.command_clean(
        f"od -An -tx4 -N16 {shlex.quote(dev)} 2>/dev/null",
        timeout=20,
    )
    if rc:
        raise RuntimeError(tr("не удалось прочитать selector flag", "failed to read the selector flag"))
    return _parse_words(text)


def _print_state(words: tuple[int, int, int, int], prefix: str = "CURRENT") -> None:
    active, curimg, startok, count = words
    slot = "MASTER/SLOT1" if active == 0 else "SLAVE/SLOT2"
    print(f"  {prefix}: active={active} ({slot}) curimg={curimg} startok={startok} count={count}")


def _tail_sha(telnet, path: str) -> str:
    rc, text = telnet.command_clean(
        f"dd if={shlex.quote(path)} bs=1 skip=4 2>/dev/null | sha256sum",
        timeout=30,
    )
    if rc:
        raise RuntimeError(f"tail SHA failed: {path}")
    hashes = re.findall(r"\b([0-9a-fA-F]{64})\b", text)
    if not hashes:
        raise RuntimeError(f"tail SHA missing: {path}")
    return hashes[-1].lower()


def _file_sha(telnet, path: str) -> str:
    rc, text = telnet.command_clean(f"sha256sum {shlex.quote(path)}", timeout=30)
    if rc:
        raise RuntimeError(f"SHA failed: {path}")
    hashes = re.findall(r"\b([0-9a-fA-F]{64})\b", text)
    if not hashes:
        raise RuntimeError(f"SHA missing: {path}")
    return hashes[-1].lower()


def _stage_flag(telnet, dev: str, target_active: int, policy) -> str:
    qremote = shlex.quote(REMOTE_FLAG)
    qdev = shlex.quote(dev)
    cmd = (
        f"rm -f {qremote}; "
        f"dd if={qdev} of={qremote} bs={policy.erase_size} count={policy.flag_size // policy.erase_size} 2>/dev/null && "
        f"printf '\\{target_active:03o}\\000\\000\\000' | dd of={qremote} bs=1 seek=0 conv=notrunc 2>/dev/null && "
        f"sync"
    )
    rc, text = telnet.command_clean(cmd, timeout=40)
    if rc:
        raise RuntimeError(tr("не удалось собрать selector-кандидат в /tmp", "failed to stage selector candidate in /tmp"))

    current_tail = _tail_sha(telnet, dev)
    staged_tail = _tail_sha(telnet, REMOTE_FLAG)
    if current_tail != staged_tail:
        raise RuntimeError(tr(
            "selector staging изменил байты кроме active; запись запрещена",
            "selector staging changed bytes other than active; refusing to write",
        ))
    staged_words = _read_words(telnet, REMOTE_FLAG)
    if staged_words[0] != target_active:
        raise RuntimeError(tr("selector staging active не совпал", "staged selector active value mismatch"))
    return _file_sha(telnet, REMOTE_FLAG)


def run(*, host: str = "192.168.1.1") -> None:
    ui.rule(tr("ПЕРЕКЛЮЧЕНИЕ STOCK SLOT ЧЕРЕЗ ROOT TELNET", "SWITCH STOCK SLOT OVER ROOT TELNET"), style="amber2")
    ui.note(tr(
        "Для Nokia XG-040G-MD: Web/Telnet используется только для получения root и записи flag/mtd8. Меняется только active; flagback и NSB-слоты не записываются.",
        "For Nokia XG-040G-MD: Web/Telnet is used only to obtain root access and write flag/mtd8. Only active is changed; flagback and NSB slots are not written.",
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

    policy = transition.MD_POLICY
    access = telnet = None
    try:
        access, telnet = ubi.open_root_auto(host)
        reported_family = str(getattr(access, "family", "") or "").strip().lower()
        if reported_family not in ("", "unknown", "md"):
            raise RuntimeError(f"board family mismatch: expected md, got {reported_family}")
        transition._require_stock_geometry(telnet, policy)
        dev = f"/dev/mtd{policy.flag_mtd}"
        current = _read_words(telnet, dev)
        ui.rule(tr("STOCK SELECTOR", "STOCK SELECTOR"), style="ok")
        _print_state(current)
        if choice == "3":
            return

        target_active = 0 if choice == "1" else 1
        target_name = "MASTER/SLOT1" if target_active == 0 else "SLAVE/SLOT2"
        if current[0] == target_active:
            ui.status(tr("ГОТОВО", "READY"), tr(
                f"Уже выбран {target_name}; NAND не изменялся.",
                f"{target_name} is already selected; NAND was not modified.",
            ))
            return

        writer = transition._mtd_writer_preflight(telnet)
        candidate_sha = _stage_flag(telnet, dev, target_active, policy)
        staged = _read_words(telnet, REMOTE_FLAG)
        expected_words = (target_active, current[1], current[2], current[3])
        if staged != expected_words:
            raise RuntimeError(f"staged selector mismatch: {staged} != {expected_words}")

        ui.rule(tr("STOCK SLOT TELNET PREFLIGHT", "STOCK SLOT TELNET PREFLIGHT"), style="amber2")
        _print_state(current)
        print(f"  TARGET : active={target_active} ({target_name})")
        print(f"  WRITER : {writer}")
        print(f"  SHA256 : {candidate_sha}")
        print(tr(
            "  WRITE  : только flag/mtd8; flagback/mtd9, nsb_master и nsb_slave НЕ записываются",
            "  WRITE  : flag/mtd8 only; flagback/mtd9, nsb_master and nsb_slave are NOT written",
        ))
        answer = ui.prompt(tr(
            f"Записать selector и переключить на {target_name}? [y/N]: ",
            f"Write the selector and switch to {target_name}? [y/N]: ",
        )).strip().lower()
        if answer not in ("y", "yes", "д", "да"):
            ui.status(tr("СТОП", "STOP"), tr("NAND не изменялся.", "NAND was not modified."))
            return

        transition._write_partition(
            telnet,
            REMOTE_FLAG,
            "flag",
            dev,
            policy.flag_size,
            writer,
            policy.erase_size,
            timeout=120,
        )
        got = transition._remote_partition_sha(telnet, dev, timeout=120)
        if got != candidate_sha:
            raise RuntimeError(f"flag readback mismatch: {got} != {candidate_sha}")
        readback = _read_words(telnet, dev)
        if readback != expected_words:
            raise RuntimeError(f"selector readback mismatch: {readback} != {expected_words}")

        ui.status(tr("ГОТОВО", "READY"), tr(
            f"Selector записан и полностью проверен: {target_name}. Перезагружаю роутер.",
            f"Selector was written and fully verified: {target_name}. Rebooting the router.",
        ))
        print(f"URSUS_STOCKSLOT_TELNET_DONE target={'master' if target_active == 0 else 'slave'} active={target_active} readback=PASS next=REBOOT")
        try:
            telnet.send_line("sync; reboot")
        except Exception:
            pass
    finally:
        if telnet:
            try:
                telnet.close()
            except Exception:
                pass
        if access:
            try:
                access.close_web(announce=False)
            except Exception:
                pass

#!/usr/bin/env python3
from __future__ import annotations

import builtins
import gzip
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

import proven_backend as pb


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def _rewrite_family(path: Path) -> None:
    if not path.is_file():
        return
    if path.suffix == ".json":
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            obj["family"] = "mf"
            path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return
        except Exception:
            pass
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"(?m)^family=md$", "family=mf", text)
    text = text.replace("identity_policy=md-factory-ri-v1", "identity_policy=fixed-factory-ri-v1")
    path.write_text(text, encoding="utf-8")


def _mf_mac_writer(original):
    def wrapped(destination: Path, telnet, model_name: str, family: str):
        if family != "mf":
            return original(destination, telnet, model_name, family)
        # Hardware evidence for both MD and MF uses the same fixed RI identity
        # contract: MAC @0x3e, serial @0x1a, G.984 suffix @0x58. Reuse the
        # already-hardened fixed-offset path rather than stock eth0 placeholders.
        result = original(destination, telnet, model_name, "md")
        _rewrite_family(destination / "DEVICE_MAC.txt")
        return result
    wrapped._ursus_mf_fixed_ri = True
    return wrapped


def _mf_identity_writer(original):
    def wrapped(destination: Path, telnet, model_name: str, family: str):
        if family != "mf":
            return original(destination, telnet, model_name, family)
        result = original(destination, telnet, model_name, "md")
        result["family"] = "mf"
        for name in ("DEVICE_IDENTITY.txt", "DEVICE_IDENTITY.json"):
            _rewrite_family(destination / name)
        return result
    wrapped._ursus_mf_fixed_ri = True
    return wrapped


def install_fixed_ri_compat() -> None:
    """Make the proven fixed RI parser family-neutral for the process."""
    if not getattr(pb._write_backup_device_mac, "_ursus_mf_fixed_ri", False):
        pb._write_backup_device_mac = _mf_mac_writer(pb._write_backup_device_mac)
    if not getattr(pb._write_backup_device_identity, "_ursus_mf_fixed_ri", False):
        pb._write_backup_device_identity = _mf_identity_writer(pb._write_backup_device_identity)


# Any caller importing this compatibility layer gets the corrected family-
# neutral identity behavior. It changes only family=mf; MD remains untouched.
install_fixed_ri_compat()


@contextmanager
def stock_backup_compat(*, compact_progress: bool = True):
    """Keep long live-TFTP backups readable without changing transport logic."""
    had_print = "print" in pb.__dict__
    old_print = pb.__dict__.get("print")
    last_progress: dict[str, float] = {}

    def filtered_print(*args, **kwargs):
        text = " ".join(str(x) for x in args)
        m = re.search(r"\[(?:ЖДУ|WAIT)\]\s+(mtd\d+):\s+(?:принято|received)", text, re.I)
        if compact_progress and m:
            key = m.group(1).lower()
            now = time.monotonic()
            if now - last_progress.get(key, 0.0) < 20.0:
                return
            last_progress[key] = now
        builtins.print(*args, **kwargs)

    pb.print = filtered_print
    try:
        yield
    finally:
        if had_print:
            pb.print = old_print
        else:
            pb.__dict__.pop("print", None)


def read_mtd0_backup(path: Path) -> bytes:
    path = path.expanduser().resolve()
    if path.is_dir():
        candidates = list(path.glob("mtd0_*.bin")) + list(path.glob("mtd0_*.bin.gz"))
        if len(candidates) != 1:
            raise RuntimeError(tr(
                f"В backup-каталоге найдено {len(candidates)} файлов mtd0; нужен ровно один.",
                f"The backup directory contains {len(candidates)} mtd0 files; exactly one is required.",
            ))
        path = candidates[0]
    if not path.is_file():
        raise RuntimeError(tr(f"Файл mtd0 не найден: {path}", f"mtd0 file not found: {path}"))
    raw = gzip.open(path, "rb").read() if path.suffix.lower() == ".gz" else path.read_bytes()
    if len(raw) != 0x80000:
        raise RuntimeError(tr(
            f"mtd0 должен быть ровно 512 КиБ, получено {len(raw)} байт.",
            f"mtd0 must be exactly 512 KiB, got {len(raw)} bytes.",
        ))
    return raw


def latest_mtd0_backup(root: Path) -> Path | None:
    candidates: list[Path] = []
    if root.is_dir():
        for pattern in ("**/mtd0_bootloader.bin.gz", "**/mtd0_bootloader.bin", "**/mf-mtd0-before-*.bin"):
            candidates.extend(p for p in root.glob(pattern) if p.is_file())
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)

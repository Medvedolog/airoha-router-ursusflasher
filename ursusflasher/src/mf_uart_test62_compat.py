#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path

import uart_bootarea_restore as ubr

_ORIGINAL = ubr.family_profile


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _first(paths: list[Path], label: str) -> Path:
    for path in paths:
        if path.is_file():
            return path.resolve()
    raise ubr.proven.Error(f"Missing {label}: " + ", ".join(str(p) for p in paths))


def family_profile(family: str) -> dict:
    if family.strip().lower() != "mf":
        return _ORIGINAL(family)
    payloads = ubr._runtime_payload_root()
    preloader = _first([
        payloads / "mf" / "recovery" / "ursusboot-mf-0.1.0-TEST62-uart-preloader.bin",
        payloads / "mf" / "ursusboot" / "ursusboot-mf-0.1.0-TEST62-uart-preloader.bin",
        ubr.HERE.parent / "work" / "mf-runtime" / "out" / "ursusboot-mf-0.1.0-TEST62-uart-preloader.bin",
    ], "MF TEST62 UART preloader")
    fip = _first([
        payloads / "mf" / "recovery" / "ursusboot-mf-0.1.0-TEST62-runtime-ram.fip",
        payloads / "mf" / "ursusboot" / "ursusboot-mf-0.1.0-TEST62-runtime-ram.fip",
        ubr.HERE.parent / "work" / "mf-runtime" / "out" / "ursusboot-mf-0.1.0-TEST62-runtime-ram.fip",
    ], "MF TEST62 RAM FIP")
    return {
        "family": "mf",
        "model": "Nokia XG-040G-MF",
        "soc": "Airoha AN7583",
        "preloader": preloader,
        "fip": fip,
        "preloader_sha": _sha(preloader),
        "fip_sha": _sha(fip),
    }


if not getattr(ubr.family_profile, "_ursus_test62", False):
    family_profile._ursus_test62 = True
    ubr.family_profile = family_profile

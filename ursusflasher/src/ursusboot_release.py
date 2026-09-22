#!/usr/bin/env python3
"""The UrsusBoot release bundled with this kit.

UrsusBoot firmware is built in Medvedolog/airoha-ursusboot at an exact commit
(config/URSUSBOOT_PIN.json). scripts/apply_ursusboot_release.py writes
data/URSUSBOOT_RELEASE.json into the kit; every host path (ONE-CLICK, EXPERT,
web/TFTP/XMODEM FIP update, MF UART recovery) takes the UrsusBoot version and
files from it instead of hard-coding its own. Without a descriptor (older kits,
repository mode) callers keep their historical defaults.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
_REPO_ROOT = HERE.parent.parent
REPO_MODE = (_REPO_ROOT / "fw").is_dir() and (_REPO_ROOT / "payloads").is_dir() and (_REPO_ROOT / "config").is_dir()
ROOT = _REPO_ROOT if REPO_MODE else HERE.parent
DESCRIPTOR = (ROOT / "config" / "URSUSBOOT_RELEASE.json") if REPO_MODE else (HERE / "URSUSBOOT_RELEASE.json")


def load() -> dict | None:
    try:
        data = json.loads(DESCRIPTOR.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("schema") != 1 or not isinstance(data.get("boards"), dict):
        return None
    return data


RELEASE = load()


def board(name: str) -> dict | None:
    return (RELEASE or {}).get("boards", {}).get(name)


def version(name: str, default: str) -> str:
    b = board(name)
    return str(b["version"]) if b and b.get("version") else default


def path(name: str, role: str) -> Path | None:
    """Kit path of a released file for `name` (md/mf) and `role`, or None."""
    b = board(name)
    rel = (b or {}).get("files", {}).get(role, {}).get("path")
    return (ROOT / rel) if rel else None


def sha256(name: str, role: str) -> str | None:
    b = board(name)
    return (b or {}).get("files", {}).get(role, {}).get("sha256")

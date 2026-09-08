#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
_REPO_CONFIG = HERE.parent.parent / "config" / "UI_TERMS.json"
_DATA_PATH = _REPO_CONFIG if _REPO_CONFIG.is_file() else HERE / "UI_TERMS.json"
_DATA = json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def is_en() -> bool:
    return os.environ.get("NOKIA_LANG", "ru").strip().lower() == "en"


def tr(ru: str, en: str) -> str:
    return en if is_en() else ru


def _pick(item: dict) -> str:
    return str(item["en"] if is_en() else item["ru"])


def _normalize_tri_bool(value: Any) -> str:
    if value is True:
        return "TRUE"
    if value is False:
        return "FALSE"
    raw = str(value or "UNKNOWN").strip().upper()
    if raw in ("TRUE", "YES", "1"):
        return "TRUE"
    if raw in ("FALSE", "NO", "0"):
        return "FALSE"
    return "UNKNOWN"


def human(value: Any, kind: str) -> str:
    """Convert machine/state values to operator-facing text.

    DeviceState enum/bool values must cross this boundary before display.  Kinds
    that intentionally carry free-form identity/address data still localize the
    UNKNOWN sentinel instead of exposing it.
    """
    kind = str(kind or "").strip().lower()
    raw = str(value if value is not None else "UNKNOWN").strip()
    if kind in ("identity", "address", "version"):
        if not raw or raw.upper() == "UNKNOWN":
            return _pick(_DATA["generic_values"]["UNKNOWN"])
        return raw
    if kind in ("bool", "tri_bool", "access"):
        key = _normalize_tri_bool(value)
        return _pick(_DATA["tri_bools"][key])
    table_name = {
        "system": "systems",
        "layout": "layouts",
        "bootloader": "bootloaders",
        "backup": "backup_states",
        "backup_state": "backup_states",
        "probe": "probe_states",
        "probe_status": "probe_states",
        "write": "write_states",
        "write_state": "write_states",
        "probe_reason": "probe_reasons",
        "execution_environment": "execution_environments",
        "environment": "execution_environments",
        "method": "methods",
    }.get(kind)
    if table_name is None:
        raise KeyError(f"unknown UI humanization kind: {kind}")
    table = _DATA[table_name]
    item = table.get(raw) or table.get(raw.upper())
    if item is None:
        # Enum/state values are fail-closed at the UI boundary.  UNKNOWN is a
        # legitimate explicit machine value, but an unregistered new enum must
        # never be silently rendered as UNKNOWN.
        raise KeyError(f"no UI term for kind={kind!r} value={raw!r}")
    return _pick(item)


def layout_label(value: object) -> str:
    return human(value, "layout")


def action_title(key: str) -> str:
    return _pick(_DATA["expert_actions"][key])


def action_number(key: str) -> int:
    return int(_DATA["expert_actions"][key]["number"])


def action_ref(key: str) -> str:
    item = _DATA["expert_actions"][key]
    title = _pick(item)
    number = int(item["number"])
    if is_en():
        return f'"{title}" (item {number})'
    return f'«{title}» (пункт {number})'


def max_action_number() -> int:
    return max(int(item["number"]) for item in _DATA["expert_actions"].values())

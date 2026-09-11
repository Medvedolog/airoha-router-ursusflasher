#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
_REPO_CONFIG = HERE.parent.parent / "config" / "UI_TERMS.json"
_DATA_PATH = _REPO_CONFIG if _REPO_CONFIG.is_file() else HERE / "UI_TERMS.json"
_DATA = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
_LOG = logging.getLogger("ursusflasher.ui_terms")


def is_en() -> bool:
    return os.environ.get("NOKIA_LANG", "ru").strip().lower() == "en"


def tr(ru: str, en: str) -> str:
    return en if is_en() else ru


def _pick(item: dict) -> str:
    return str(item["en"] if is_en() else item["ru"])


def _warn_ui_term(message: str) -> None:
    """Record a non-fatal UI dictionary problem without creating import cycles."""
    try:
        proven = sys.modules.get("proven_backend")
        writer = getattr(proven, "_write_session_only", None) if proven is not None else None
        if callable(writer):
            writer("[UI_TERMS WARNING] " + message)
            return
    except Exception:
        pass
    _LOG.warning(message)


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

    Registry completeness is enforced by build QA. At runtime an unregistered
    value is shown verbatim and logged instead of crashing a recovery menu.
    Authorization never depends on this presentation fallback.
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
        _warn_ui_term(f"missing UI term: kind={kind!r} value={raw!r}")
        return raw
    return _pick(item)


def layout_label(value: object) -> str:
    return human(value, "layout")


def action_title(key: str) -> str:
    """Return an EXPERT action title without allowing a label bug to kill menu UI."""
    raw = str(key)
    item = _DATA.get("expert_actions", {}).get(raw)
    if not isinstance(item, dict):
        _warn_ui_term(f"missing expert action title: key={raw!r}")
        return raw
    try:
        return _pick(item)
    except Exception as exc:
        _warn_ui_term(f"malformed expert action title: key={raw!r}: {type(exc).__name__}: {exc}")
        return raw


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

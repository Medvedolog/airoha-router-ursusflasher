#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
KIT = HERE.parent.parent if (HERE.parent.parent / "config").is_dir() else HERE.parent


def _catalog_path() -> Path:
    candidates = [
        KIT / "config" / "BOARD_PROFILES.json",
        HERE / "BOARD_PROFILES.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("BOARD_PROFILES.json not found")


def load_catalog() -> dict[str, Any]:
    data = json.loads(_catalog_path().read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not isinstance(data.get("profiles"), dict):
        raise ValueError("unsupported BOARD_PROFILES.json schema")
    return data


def get_profile(key: str) -> dict[str, Any]:
    profiles = load_catalog()["profiles"]
    try:
        profile = profiles[key]
    except KeyError as exc:
        raise KeyError(f"unknown board profile: {key}") from exc
    if not isinstance(profile, dict):
        raise ValueError(f"invalid board profile: {key}")
    return profile


def _matches_any(value: str, tokens: list[str]) -> bool:
    low = str(value or "").lower()
    return any(str(token).lower() in low for token in tokens)


def match_profile(*, model: str = "", soc: str = "", board: str = "") -> tuple[str, dict[str, Any]] | None:
    """Return a profile only when available identity evidence is non-conflicting.

    A model/board token can identify the family.  If SoC evidence is also present,
    it must match the same profile.  This is deliberately read-only identity
    classification; write authorization belongs to the selected backend.
    """
    profiles = load_catalog()["profiles"]
    for key, profile in profiles.items():
        model_tokens = list(profile.get("model_tokens") or [])
        board_tokens = list(profile.get("openwrt_board_tokens") or [])
        soc_tokens = list(profile.get("soc_tokens") or [])
        family_hit = _matches_any(model, model_tokens) or _matches_any(board, model_tokens + board_tokens)
        if not family_hit:
            continue
        if soc and soc_tokens and not _matches_any(soc, soc_tokens):
            continue
        return key, profile
    return None


def canonical_identity(*, model: str = "", soc: str = "", board: str = "") -> tuple[str, str, str] | None:
    match = match_profile(model=model, soc=soc, board=board)
    if not match:
        return None
    key, profile = match
    return key, str(profile["model"]), str(profile["soc"])


def persistent_writes_enabled(profile: dict[str, Any]) -> bool:
    return bool((profile.get("write_policy") or {}).get("persistent_write_enabled", False))

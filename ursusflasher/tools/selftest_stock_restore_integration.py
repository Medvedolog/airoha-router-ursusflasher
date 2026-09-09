#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
ROOT = HERE.parents[1]
sys.path.insert(0, str(SRC))

import board_profiles as bp  # noqa: E402
import stock_restore as sr  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit("SELFTEST FAIL: " + message)


def main() -> int:
    md = bp.get_profile("md")
    mf = bp.get_profile("mf")
    require(bp.write_action_enabled(md, "restore_nokia"), "MD restore_nokia should be allowed")
    require(bp.write_action_enabled(mf, "restore_nokia"), "MF restore_nokia explicit recovery writer missing")
    require(not bp.persistent_writes_enabled(mf), "MF broad persistent writes must remain disabled")
    for key in ("install_openwrt", "install_or_repair_bootloader", "custom_openwrt", "recover_bootloader"):
        require(not bp.write_action_enabled(mf, key), f"MF unexpectedly authorizes {key}")

    source = (SRC / "stock_restore.py").read_text(encoding="utf-8")
    required_tokens = (
        "proven.recovery_profile_for_family(family)",
        "expected_board = f\"nokia,xg-040g-{family}-ubi\"",
        "bootfile = f\"ursus-stock-recovery-{family}.itb\"",
        "Automatic retry is forbidden",
        "_legacy_restore_confirmation_adapter(already_confirmed=True)",
        "_legacy_restore_confirmation_adapter(already_confirmed=False)",
        "proven.stock_recovery_wizard()",
    )
    for token in required_tokens:
        require(token in source, f"missing restore coordinator invariant: {token}")
    require("proven.boot_recovery_from_production_openwrt(" not in source,
            "family-unsafe legacy no-UART helper must not be called")

    # The retained backend still contains its old codeword for Medve lineage;
    # UrsusFlasher must translate it to one ordinary y/N at the adapter boundary.
    original_prompt = sr.ui.prompt
    original_log = sr.proven._write_session_only
    try:
        sr.ui.prompt = lambda _prompt: "y"
        sr.proven._write_session_only = lambda _text: None
        with sr._legacy_restore_confirmation_adapter(already_confirmed=False):
            value = sr.proven.input("Type exactly RESTORE STOCK BACKUP: ")
            require(value == "RESTORE STOCK BACKUP", "y/N adapter did not satisfy retained backend token")
            try:
                sr.proven.input("Type exactly RESTORE STOCK BACKUP: ")
            except sr.proven.Error:
                pass
            else:
                raise SystemExit("SELFTEST FAIL: duplicate destructive confirmation was accepted")
    finally:
        sr.ui.prompt = original_prompt
        sr.proven._write_session_only = original_log

    try:
        sr._require_family("unknown")
    except sr.proven.Error:
        pass
    else:
        raise SystemExit("SELFTEST FAIL: unknown restore family was accepted")

    catalog = json.loads((ROOT / "config/BOARD_PROFILES.json").read_text(encoding="utf-8"))
    require(catalog["profiles"]["mf"]["write_policy"]["allowed_write_actions"] == ["restore_nokia"],
            "MF profile recovery allowlist drifted")

    print("STOCK_RESTORE_INTEGRATION_SELFTEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

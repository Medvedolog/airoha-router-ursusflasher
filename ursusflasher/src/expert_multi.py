#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import board_profiles as bp
import device_state as ds
import expert as base
import mf_runtime_install
import one_key_multi
import ursusboot_install

# Keep the mature EXPERT UI/state machine. Only replace the board-sensitive
# entrypoints; this avoids forking the menu and preserves MD TEST61 behavior.
base.one_key = one_key_multi


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def _family(state: ds.DeviceState) -> str | None:
    key = str(state.evidence.get("board_profile") or "")
    if key.startswith("mf"):
        return "mf"
    if key.startswith("md"):
        return "md"
    match = bp.match_profile(model=state.model, soc=state.soc)
    return match[0] if match else None


def _ask_skip_full_backup() -> bool:
    answer = base.ui.prompt(tr(
        "EXPERT: пропустить полный restore-grade backup для этого запуска? [y/N]: ",
        "EXPERT: skip the full restore-grade backup for this run? [y/N]: ",
    )).strip().lower()
    return answer in ("y", "yes", "д", "да")


def run_bootloader_install_or_update(host: str, state: ds.DeviceState) -> None:
    family = _family(state)
    if family == "mf":
        if state.current_system == "RECOVERY":
            raise RuntimeError(tr(
                "MF runtime не использует универсальный Web FIP-writer. Для device-derived обновления загрузите обычную OpenWrt или заводскую Nokia и повторите EXPERT → 2; Recovery остаётся доступен для OpenWrt/recovery-операций.",
                "MF runtime does not use a universal Web FIP writer. Boot normal OpenWrt or Nokia stock and run EXPERT -> 2 again for a device-derived update; Recovery remains available for OpenWrt/recovery operations.",
            ))
        skip = _ask_skip_full_backup() if state.current_system == "NOKIA_STOCK" else True
        route = "stock" if state.current_system == "NOKIA_STOCK" else "openwrt"
        rc = mf_runtime_install.run_install(
            host=host, route=route, unattended=False,
            skip_full_backup=skip, recovery_after=False,
        )
        if rc:
            raise RuntimeError(f"MF bootloader installer returned rc={rc}")
        return

    if family == "md" and state.current_system == "NOKIA_STOCK":
        skip = _ask_skip_full_backup()
        rc = ursusboot_install.run_install(host=host, route="stock", skip_full_backup=skip)
        if rc:
            raise RuntimeError(f"MD bootloader installer returned rc={rc}")
        return

    # Frozen MD Recovery/OpenWrt behavior remains byte/flow compatible.
    return _original_bootloader(host, state)


_original_bootloader = base.run_bootloader_install_or_update
base.run_bootloader_install_or_update = run_bootloader_install_or_update


# In MF Recovery action 2 is intentionally unavailable because the rejected
# universal FIP writer stays blocked. Express this in applicability instead of
# letting the operator discover it after selecting the menu item.
_original_applicability = base.ds.action_applicability


def action_applicability(state: ds.DeviceState):
    out = _original_applicability(state)
    if _family(state) == "mf" and state.current_system == "RECOVERY":
        old = out[2]
        out[2] = ds.ActionApplicability(
            old.number, old.key, False,
            tr(
                "MF bootloader update is device-derived and runs from Nokia stock or OpenWrt, not from Recovery",
                "MF bootloader update is device-derived and runs from Nokia stock or OpenWrt, not from Recovery",
            ),
            "", old.write_capable, "MF_DEVICE_DERIVED_HOST_ONLY",
        )
        if 4 in out:
            a = out[4]
            out[4] = ds.ActionApplicability(a.number, a.key, False, out[2].reason, "", a.write_capable, "ALIAS_TO_ACTION_2")
    return out


base.ds.action_applicability = action_applicability


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())

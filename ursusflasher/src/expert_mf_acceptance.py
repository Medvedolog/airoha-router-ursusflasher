#!/usr/bin/env python3
from __future__ import annotations

"""Feature-branch EXPERT entrypoint for MF persistent hardware acceptance.

The production MD implementation remains untouched. This wrapper narrows one
specific action for a positively identified Nokia XG-040G-MF running stock:
EXPERT item 2 may invoke the stock-derived mtd0/NT_FW hardware-acceptance path.
Every other state delegates to the normal EXPERT policy and dispatcher.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import board_profiles as bp
import device_state as ds
import expert
import mf_persistent_install
import proven_backend as proven

MF_ACCEPTANCE_BACKEND = "MF_STOCK_DERIVED_MTD0_HW_ACCEPTANCE"

_original_action_applicability = ds.action_applicability
_original_bootloader_dispatch = expert.run_bootloader_install_or_update
_original_bootloader_menu_detail = expert._bootloader_menu_detail


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def _family(state: ds.DeviceState) -> str | None:
    match = bp.match_profile(model=state.model, soc=state.soc)
    return match[0] if match else None


def acceptance_action_applicability(state: ds.DeviceState) -> dict[int, ds.ActionApplicability]:
    """Expose exactly one MF writer only for complete, positively identified STOCK MF.

    The board profile deliberately keeps the broad production write switch off.
    This feature-branch entrypoint is the sole exception used to obtain the first
    cold-boot hardware acceptance of the device-derived persistent candidate.
    """
    out = _original_action_applicability(state)
    if _family(state) != "mf":
        return out

    current = out[2]
    if state.current_system == "NOKIA_STOCK" and state.probe_status == ds.PROBE_COMPLETE:
        out[2] = ds.ActionApplicability(
            number=current.number,
            key=current.key,
            enabled=True,
            reason="",
            note=tr(
                "Только HW acceptance: candidate строится из фактического MF mtd0; auto reboot отключён.",
                "HW acceptance only: candidate is derived from the actual MF mtd0; automatic reboot is disabled.",
            ),
            write_capable=True,
            resolved_backend=MF_ACCEPTANCE_BACKEND,
        )
        return out

    out[2] = ds.ActionApplicability(
        number=current.number,
        key=current.key,
        enabled=False,
        reason=tr(
            "MF persistent HW acceptance разрешён только для полностью подтверждённой Nokia STOCK MF; из Recovery/OpenWrt запись закрыта",
            "MF persistent HW acceptance is allowed only for a fully confirmed Nokia STOCK MF; writes from Recovery/OpenWrt remain blocked",
        ),
        note="",
        write_capable=True,
        resolved_backend="BOARD_PROFILE_WRITE_DISABLED",
    )
    return out


def acceptance_bootloader_menu_detail(state: ds.DeviceState, action: ds.ActionApplicability) -> str:
    if _family(state) == "mf" and action.resolved_backend == MF_ACCEPTANCE_BACKEND:
        return tr(
            "MF STOCK HW acceptance: полный backup → фактический mtd0 → замена только NT_FW/BL33 → запись → полный readback; без auto reboot",
            "MF STOCK HW acceptance: full backup → actual mtd0 → NT_FW/BL33-only replacement → write → full readback; no automatic reboot",
        )
    return _original_bootloader_menu_detail(state, action)


def acceptance_bootloader_dispatch(host: str, state: ds.DeviceState) -> None:
    family = _family(state)
    if family != "mf":
        _original_bootloader_dispatch(host, state)
        return

    if state.current_system != "NOKIA_STOCK" or state.probe_status != ds.PROBE_COMPLETE:
        raise RuntimeError(tr(
            "MF persistent HW acceptance остановлен: требуется полностью подтверждённая Nokia STOCK MF.",
            "MF persistent HW acceptance stopped: a fully confirmed Nokia STOCK MF is required.",
        ))

    access = None
    bootstrap_telnet = None
    try:
        # Reuse the existing MedveFlasher-derived MF install access gate. It
        # re-detects MF through live stock Web; a manual model choice is never
        # accepted as write authorization. Closed Telnet still fails visibly.
        access = proven._install_access(proven.MF_INSTALL_PROFILE)
        if getattr(access, "family", "") != "mf":
            raise RuntimeError(tr(
                "Повторная проверка stock Web не подтвердила семейство MF; запись запрещена.",
                "The repeated stock Web check did not confirm the MF family; writing is forbidden.",
            ))

        # The explicit write flow may provision a stock service used to obtain
        # a UID-0 account. This is a stock-settings state change, not a NAND
        # firmware writer; read-only flows continue to pass False here.
        bootstrap_telnet = proven.login_root_family(
            access,
            "mf",
            allow_service_provisioning=True,
        )
        proven.require_supported_model_over_telnet(access, bootstrap_telnet)
        bootstrap_telnet.close()
        bootstrap_telnet = None

        rc = mf_persistent_install.run_stock_acceptance(access)
        if rc not in (0, 2):
            raise RuntimeError(f"MF persistent acceptance returned rc={rc}")
    finally:
        if bootstrap_telnet is not None:
            try:
                bootstrap_telnet.close()
            except Exception:
                pass
        if access is not None:
            access.close_web(announce=False)


def install_hooks() -> None:
    ds.action_applicability = acceptance_action_applicability
    expert.run_bootloader_install_or_update = acceptance_bootloader_dispatch
    expert._bootloader_menu_detail = acceptance_bootloader_menu_detail


def main() -> int:
    install_hooks()
    return expert.main()


if __name__ == "__main__":
    raise SystemExit(main())

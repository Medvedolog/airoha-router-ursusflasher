#!/usr/bin/env python3
from __future__ import annotations

import os

import expert_multi as base
import bootloader_install_menu as bootmenu
import backup_progress
import device_state as ds


_original_applicability = base.action_applicability
_original_transition_profile = base.base._transition_profile


def action_applicability(state: ds.DeviceState):
    """Engineering UI: never grey an action out from a probe/policy result.

    Menu applicability is advisory only in this HWTEST composition. Concrete
    backends still enforce their immediate write invariants (target geometry,
    candidate structure and post-write readback), but stale/absent network state,
    HW_PENDING profile flags and transport heuristics do not hide operations.
    """
    out = _original_applicability(state)
    forced = {}
    for number, old in out.items():
        note = old.note
        if not old.enabled and old.reason:
            note = (note + " · " if note else "") + "EXPERT: " + old.reason
        forced[number] = ds.ActionApplicability(
            old.number,
            old.key,
            True,
            "",
            note,
            old.write_capable,
            old.resolved_backend,
        )
    return forced


def _show_transition_action_unconditionally(_state: ds.DeviceState) -> None:
    base.base.ui.menu_item(
        4,
        base.tr("Stock Nokia → Vanilla OpenWrt (TRANSITION)", "Stock Nokia → Vanilla OpenWrt (TRANSITION)"),
        base.tr(
            "полный all-MTD backup → stock-compatible SLOT2 → TRANSITION в RAM; профиль проверяется после выбора",
            "full all-MTD backup → stock-compatible SLOT2 → TRANSITION in RAM; profile is checked after selection",
        ),
        write_capable=True,
        enabled=True,
        reason="",
    )


def _transition_profile_after_selection(_menu_state: ds.DeviceState) -> str | None:
    host = os.environ.get("NOKIA_ROUTER_IP", "192.168.1.1").strip() or "192.168.1.1"
    fresh_state = ds.probe_device_state(host)
    return _original_transition_profile(fresh_state)


base.action_applicability = action_applicability
base.run_bootloader_install_or_update = bootmenu.run
base.base._show_transition_action = _show_transition_action_unconditionally
base.base._transition_profile = _transition_profile_after_selection
backup_progress.install(base.base.proven)


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())

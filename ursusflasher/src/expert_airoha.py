#!/usr/bin/env python3
from __future__ import annotations

import os

import expert_multi as base
import bootloader_install_menu as bootmenu
import backup_progress
import transition_trace
import transition_fastpath
import device_state as ds


_original_applicability = base.action_applicability
_original_transition_profile = base.base._transition_profile
_original_menu_detail = base.base._menu_detail


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
            "Vanilla переход → OpenWrt без постоянного UrsusBoot. В mtd0 «подмигивающего медведя» после миграции нет.",
            "Vanilla transition → OpenWrt without persistent UrsusBoot. No persistent WebFailsafe bear remains in mtd0 after migration.",
        ),
        write_capable=True,
        enabled=True,
        reason="",
    )


def _transition_profile_after_selection(_menu_state: ds.DeviceState) -> str | None:
    """Do not authorize or block item 4 from the passive menu probe.

    The passive probe is allowed to fail completely (for example vendor Web may
    not answer the lightweight fingerprint yet).  If it positively identifies
    MD/MF, keep that result.  Otherwise enter the currently implemented MD
    TRANSITION backend and let its own stock login + exact /proc/mtd geometry
    checks prove the target before any NAND write.  A wrong/non-MD target stops
    there, before the destructive boundary.
    """
    host = os.environ.get("NOKIA_ROUTER_IP", "192.168.1.1").strip() or "192.168.1.1"
    fresh_state = ds.probe_device_state(host)
    detected = _original_transition_profile(fresh_state)
    if detected in ("xg040-md", "xg040-mf"):
        return detected
    base.base.ui.status(
        base.tr("INFO", "INFO"),
        base.tr(
            "Пассивная диагностика не определила профиль; запускаю MD TRANSITION preflight. Stock Web/root и точная MTD-геометрия будут проверены самим backend до записи.",
            "Passive diagnostics did not identify the profile; starting MD TRANSITION preflight. Stock Web/root and exact MTD geometry are verified by the backend before any write.",
        ),
    )
    return "xg040-md"


def _menu_detail(number: int, state: ds.DeviceState, app: dict[int, ds.ActionApplicability]) -> tuple[str, str]:
    if number == 1:
        return (
            "Полный переход → постоянный UrsusBoot + OpenWrt. В mtd0 остаётся аварийный «подмигивающий медведь» WebFailsafe.",
            "Full transition → persistent UrsusBoot + OpenWrt. An emergency WebFailsafe remains in mtd0.",
        )
    if number == 4:
        return (
            "Vanilla переход → OpenWrt без постоянного UrsusBoot. В mtd0 «подмигивающего медведя» после миграции нет.",
            "Vanilla transition → OpenWrt without persistent UrsusBoot. No persistent WebFailsafe remains in mtd0 after migration.",
        )
    return _original_menu_detail(number, state, app)


base.action_applicability = action_applicability
base.run_bootloader_install_or_update = bootmenu.run
base.base._show_transition_action = _show_transition_action_unconditionally
base.base._transition_profile = _transition_profile_after_selection
base.base._menu_detail = _menu_detail
backup_progress.install(base.base.proven)
transition_trace.install(base.stock_ab_transition)
transition_fastpath.install(base.stock_ab_transition)


def main() -> int:
    # EXPERT is an interactive operator UI: always ask the language on entry.
    # NOKIA_LANG is set again by choose_language() for the selected session.
    os.environ.pop("NOKIA_LANG", None)
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())

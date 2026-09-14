#!/usr/bin/env python3
from __future__ import annotations

import expert_multi as base
import bootloader_install_menu as bootmenu
import device_state as ds


_original_applicability = base.action_applicability


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


base.action_applicability = action_applicability
base.run_bootloader_install_or_update = bootmenu.run


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())

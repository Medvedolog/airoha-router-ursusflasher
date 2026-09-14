#!/usr/bin/env python3
from __future__ import annotations

import expert_multi as base
import bootloader_install_menu as bootmenu
import device_state as ds


_original_applicability = base.action_applicability


def action_applicability(state: ds.DeviceState):
    out = _original_applicability(state)
    family = bootmenu.family_from_state(state)
    # XG140 persistent write remains engineering-only in BOARD_PROFILES until
    # this hardware cycle passes. Item 2 is nevertheless exposed here because
    # the selected Telnet backend performs its own live identity, geometry,
    # candidate and full-readback gates before the single destructive y/N.
    if family == "xg140" and state.current_system == "NOKIA_STOCK":
        old = out[2]
        out[2] = ds.ActionApplicability(
            old.number, old.key, True, "",
            "XG140 engineering: native device-derived mtd0; full readback mandatory",
            True, "XG140_NATIVE_TELNET_ENGINEERING",
        )
    return out


base.action_applicability = action_applicability
base.run_bootloader_install_or_update = bootmenu.run


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import os

import expert_multi as base
import bootloader_install_menu as bootmenu
import backup_progress
import transition_trace
import transition_fastpath
import uart_prompt_fix
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
        enabled = ds.ActionApplicability(old.number, old.key, True, "", note, old.write_capable, old.resolved_backend)
        # Show the policy reason once, and only when it adds something to what the menu already says.
        shown = (note or "").lower()
        if number == 3:
            shown += " " + base.base._custom_openwrt_menu_detail(state, enabled).lower()
        if not old.enabled and old.reason and old.reason.strip().lower() not in shown:
            note = (note + " · " if note else "") + "EXPERT: " + old.reason
            enabled = ds.ActionApplicability(old.number, old.key, True, "", note, old.write_capable, old.resolved_backend)
        forced[number] = enabled
    return forced


def _show_transition_action_unconditionally(_state: ds.DeviceState) -> None:
    base.base.ui.menu_item(
        4,
        base.tr("Stock Nokia → OpenWrt UBI с UrsusBoot Recovery", "Stock Nokia → OpenWrt UBI with UrsusBoot Recovery"),
        base.tr(
            "Ставит UrsusBoot (MD — в mtd0, MF — постоянный runtime), затем его Recovery переводит заводскую прошивку на OpenWrt UBI с быстрым BL2. UrsusBoot остаётся загрузчиком Recovery.",
            "Installs UrsusBoot (MD: in mtd0, MF: persistent runtime), then its Recovery migrates the factory firmware to OpenWrt UBI with the fast BL2. UrsusBoot stays as the Recovery bootloader.",
        ),
        write_capable=True,
        enabled=True,
        reason="",
    )


def _transition_profile_after_selection(_menu_state: ds.DeviceState) -> str | None:
    """Do not authorize or block item 4 from the passive menu probe.

    The passive probe is allowed to fail completely (for example vendor Web may
    not answer the lightweight fingerprint yet).  If it positively identifies
    MD/MF, keep that result.  Otherwise the operator names the model; the
    backend's own stock login, chipset and /proc/mtd checks still prove the
    target before any NAND write, and a mismatch stops there.
    """
    host = os.environ.get("NOKIA_ROUTER_IP", "192.168.1.1").strip() or "192.168.1.1"
    fresh_state = ds.probe_device_state(host)
    detected = _original_transition_profile(fresh_state)
    if detected in ("xg040-md", "xg040-mf"):
        return detected
    base.base.ui.status(
        base.tr("INFO", "INFO"),
        base.tr(
            "Модель не определилась по сети. Выберите её сами; до любой записи backend ещё раз проверит вход в stock, чип и разметку MTD и остановится, если модель не совпала.",
            "The model was not identified over the network. Choose it; before any write the backend re-checks the stock login, chipset and MTD layout and stops on a mismatch.",
        ),
    )
    base.base.ui.menu_item(1, "Nokia XG-040G-MD / AN7581")
    base.base.ui.menu_item(2, "Nokia XG-040G-MF / AN7583")
    base.base.ui.menu_item(0, base.tr("Назад", "Back"))
    choice = base.base.ui.prompt(base.tr("Модель [1/2/0]: ", "Model [1/2/0]: ")).strip()
    return {"1": "xg040-md", "2": "xg040-mf"}.get(choice)


def _menu_detail(number: int, state: ds.DeviceState, app: dict[int, ds.ActionApplicability]) -> tuple[str, str]:
    if number == 1:
        return (
            "Nokia stock MD/MF → полный backup (в EXPERT можно пропустить) → UrsusBoot → комплектная OpenWrt. Аварийный WebFailsafe UrsusBoot остаётся в загрузчике.",
            "Nokia stock MD/MF → full backup (EXPERT may skip it) → UrsusBoot → bundled OpenWrt. The UrsusBoot emergency WebFailsafe stays in the bootloader.",
        )
    if number == 4:
        return (
            "Ставит UrsusBoot (MD — в mtd0, MF — постоянный runtime), затем его Recovery переводит заводскую прошивку на OpenWrt UBI с быстрым BL2. UrsusBoot остаётся загрузчиком Recovery.",
            "Installs UrsusBoot (MD: in mtd0, MF: persistent runtime), then its Recovery migrates the factory firmware to OpenWrt UBI with the fast BL2. UrsusBoot stays as the Recovery bootloader.",
        )
    if number == 7 and state.current_system != "NOKIA_STOCK":
        return (
            "Nokia stock — по сети (Web/Telnet/TFTP); иначе (OpenWrt, Recovery, не загружается) — BootROM/USB-UART → среда в RAM → чтение NAND. Копия на ПК; flash не изменяется.",
            "Nokia stock over the network (Web/Telnet/TFTP); otherwise (OpenWrt, Recovery, no boot) BootROM/USB-UART → RAM environment → NAND read. Saved on the PC; flash is not modified.",
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
uart_prompt_fix.install(base.base.proven)


def main() -> int:
    # EXPERT is an interactive operator UI: always ask the language on entry.
    # NOKIA_LANG is set again by choose_language() for the selected session.
    os.environ.pop("NOKIA_LANG", None)
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())

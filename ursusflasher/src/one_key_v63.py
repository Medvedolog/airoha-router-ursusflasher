#!/usr/bin/env python3
from __future__ import annotations

import sys
import time

import one_key_multi as base


def mf_runtime_mode(st: dict) -> str:
    """Classify MF UrsusBoot by explicit write capability, never by version alone."""
    persistent = st.get("persistent_write_enabled")
    ram_ro = st.get("ram_read_only")
    if persistent is True and ram_ro is False:
        return "PERSISTENT_RUNTIME"
    if persistent is False or ram_ro is True:
        return "RAM_ONLY"
    # Legacy MF Recovery without the capability fields is conservative/read-only.
    return "LEGACY_RAM_ONLY"


def _require_mf_persistent_runtime(st: dict) -> None:
    mode = mf_runtime_mode(st)
    base.ui.status(base.tr("РЕЖИМ", "MODE"), f"MF UrsusBoot: {mode}")
    if mode != "PERSISTENT_RUNTIME":
        raise RuntimeError(base.tr(
            "Обнаружен MF RAM-only/legacy Recovery, а не persistent UrsusBoot. ONE-KEY остановлен ДО записи OpenWrt. Не обходите HTTP 403: верните/загрузите Nokia stock и запустите ONE-KEY снова; тогда сначала будет установлен device-derived persistent UrsusBoot-MF.",
            "MF RAM-only/legacy Recovery was detected instead of persistent UrsusBoot. ONE-KEY stopped BEFORE any OpenWrt write. Do not bypass HTTP 403: boot/restore Nokia stock and run ONE-KEY again; it will install the device-derived persistent UrsusBoot-MF first.",
        ))


def main(*, skip_full_backup: bool = False) -> int:
    base.pb.start_session_logging()
    base.ui.enable()
    base.choose_language()
    root = base._root()
    version = base.ui.package_version(root)
    base.ui.banner("UrsusFlasher ONE-KEY", version=version)
    base.network_guidance.show()

    state = base._probe(interactive_ssh=False)
    if state.current_system.startswith("OPENWRT") and state.probe_status != base.ds.PROBE_COMPLETE:
        state = base._probe(interactive_ssh=True)
    family = base._family(state)
    base.verify_family_payloads(family)
    base.ui.status(base.tr("УСТРОЙСТВО", "DEVICE"), f"{state.model} / {state.soc} / {family.upper()}")

    already_authorized = False
    if state.current_system == "RECOVERY":
        st = base.uw.status(base.HOST)
        family = base._family_from_ursus(st)
        base.verify_family_payloads(family)
        if family == "mf":
            _require_mf_persistent_runtime(st)
    elif state.current_system in ("NOKIA_STOCK", "OPENWRT_UBI", "OPENWRT_FACTORY", "OPENWRT_STOCK_LAYOUT"):
        st = base._install_bootloader(state, family, skip_full_backup)
        already_authorized = True
        # The post-install Recovery must prove that MF persistent writes are enabled.
        if family == "mf":
            _require_mf_persistent_runtime(st)
    else:
        raise RuntimeError(base.tr(
            f"ONE-KEY не может безопасно продолжить из состояния {state.current_system}.",
            f"ONE-KEY cannot safely continue from state {state.current_system}.",
        ))

    recovery_family = base._family_from_ursus(st)
    if recovery_family != family:
        raise RuntimeError(f"family changed across reboot: {family} -> {recovery_family}")
    base._report_runtime(st, family)

    result = base._install_openwrt(st, family, already_authorized=already_authorized)
    base.ui.status(base.tr("ГОТОВО", "READY"), base.tr(
        f"Операция OpenWrt для {family.upper()} завершена и проверена.",
        f"The OpenWrt operation for {family.upper()} completed and was verified.",
    ))
    base.ui.note(base.tr(
        "Сейчас UrsusBoot перезагрузит устройство в установленную OpenWrt.",
        "UrsusBoot will now reboot the device into the installed OpenWrt.",
    ))
    time.sleep(1)
    base.uw.reboot(base.HOST)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        base.ui.status(base.tr("СТОП", "STOP"), base.tr("Остановлено пользователем.", "Stopped by user."))
        raise SystemExit(130)
    except Exception as exc:
        print()
        base.ui.status(base.tr("ОШИБКА", "ERROR"), str(exc), stream=sys.stderr)
        raise SystemExit(1)

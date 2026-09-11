#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import board_profiles as bp
import console_ui as ui
import device_state as ds
import mf_runtime_install
import network_guidance
import one_key as md_one_key
import proven_backend as pb
import ursus_web_client as uw

choose_language = md_one_key.choose_language
tr = md_one_key.tr
say = md_one_key.say
stage = md_one_key.stage
probe_http_identity = md_one_key.probe_http_identity

HOST = os.environ.get("NOKIA_ROUTER_IP", "192.168.1.1").strip() or "192.168.1.1"
MD_TARGET = "0.1.0-alpha5-UBIUX1-TEST61"
MF_TARGET = "0.1.0-TEST61"


def _root() -> Path:
    repo = HERE.parent.parent
    return repo if (repo / "config").is_dir() else HERE.parent


def _manifest() -> dict:
    root = _root()
    path = (root / "config" / "FIRMWARE_BUNDLES.json") if (root / "config").is_dir() else (root / "data" / "FIRMWARE_BUNDLES.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not isinstance(data.get("profiles"), dict):
        raise RuntimeError("unsupported FIRMWARE_BUNDLES.json")
    return data


def _family(state: ds.DeviceState) -> str:
    key = str(state.evidence.get("board_profile") or "")
    if key.startswith("md"):
        return "md"
    if key.startswith("mf"):
        return "mf"
    match = bp.match_profile(model=state.model, soc=state.soc)
    if match:
        return match[0]
    raise RuntimeError(tr(
        f"Не удалось однозначно определить MD/MF: model={state.model}, soc={state.soc}.",
        f"Could not unambiguously identify MD/MF: model={state.model}, soc={state.soc}.",
    ))


def _resolve_item(item: dict) -> Path:
    root = _root()
    rel = str(item.get("repo_path") if (root / "config").is_dir() and item.get("repo_path") else item.get("path") or "")
    path = root / rel
    if not path.is_file():
        raise RuntimeError(tr(f"В комплекте нет обязательного файла: {rel}", f"Required bundled file is missing: {rel}"))
    expected_size = int(item.get("size") or 0)
    if expected_size and path.stat().st_size != expected_size:
        raise RuntimeError(f"bundle size mismatch for {rel}: {path.stat().st_size} != {expected_size}")
    expected_sha = str(item.get("sha256") or "").lower()
    if expected_sha:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != expected_sha:
            raise RuntimeError(f"bundle SHA256 mismatch for {rel}: {h.hexdigest()} != {expected_sha}")
    return path


def require_role(family: str, role: str) -> Path:
    profile = _manifest()["profiles"].get(family)
    if not isinstance(profile, dict):
        raise RuntimeError(f"firmware profile is missing: {family}")
    hits = [x for x in profile.get("files", []) if x.get("role") == role]
    if len(hits) != 1:
        raise RuntimeError(f"firmware role {role} for {family} has {len(hits)} candidates")
    return _resolve_item(hits[0])


def verify_family_payloads(family: str) -> None:
    profile = _manifest()["profiles"][family]
    for item in profile.get("files", []):
        if item.get("required", True):
            _resolve_item(item)
    ui.status(tr("ГОТОВО", "READY"), tr(
        f"Комплект прошивок для {family.upper()} проверен по размеру и SHA256.",
        f"The {family.upper()} firmware bundle passed size and SHA256 verification.",
    ))


def _probe(*, interactive_ssh: bool = False) -> ds.DeviceState:
    state = ds.probe_device_state(HOST, interactive_ssh=interactive_ssh)
    if state.probe_status == ds.PROBE_FAILED:
        raise RuntimeError(tr("Роутер не найден по сети.", "The router was not found on the network."))
    return state


def _wait_recovery() -> dict:
    st = md_one_key.wait_ursus(HOST, 75)
    if st:
        return st
    return md_one_key.wait_for_manual_recovery()


def _family_from_ursus(st: dict) -> str:
    board = " ".join(str(st.get(k) or "") for k in ("target", "board", "board_name", "boot_fdt_compatible", "fdt_model"))
    soc = str(st.get("soc") or st.get("soc_name") or "")
    match = bp.match_profile(board=board, model=board, soc=soc)
    if not match:
        raise RuntimeError(tr(
            f"UrsusBoot Recovery не дал однозначную MD/MF identity: board={board!r}, soc={soc!r}",
            f"UrsusBoot Recovery did not provide unambiguous MD/MF identity: board={board!r}, soc={soc!r}",
        ))
    return match[0]


def _install_bootloader(state: ds.DeviceState, family: str, skip_full_backup: bool) -> dict:
    if family == "md":
        if state.current_system == "NOKIA_STOCK":
            md_one_key.install_ursus_from_stock(HOST, skip_full_backup=skip_full_backup)
        elif state.current_system.startswith("OPENWRT"):
            md_one_key.install_ursus_from_openwrt(HOST)
        else:
            raise RuntimeError(f"MD bootloader install is not applicable from {state.current_system}")
    else:
        # MF is never installed from a universal prebuilt FIP. The runtime BL33
        # is patched into this device's own FIP/boot area and the result is read
        # back in full before reboot. Interactive mode retains the single y/N.
        route = "stock" if state.current_system == "NOKIA_STOCK" else "openwrt"
        ui.note(tr(
            "MF: используется фактический FIP этого устройства; native ранние компоненты и factory identity сохраняются. После подтверждённой записи ONE-KEY продолжит переход на OpenWrt UBI без второго destructive-confirm.",
            "MF: the candidate is derived from this device's actual FIP; native early components and factory identity are preserved. After the verified write, ONE-KEY continues to OpenWrt UBI without a second destructive confirmation.",
        ))
        rc = mf_runtime_install.run_install(
            host=HOST, route=route, unattended=False,
            skip_full_backup=skip_full_backup, recovery_after=True,
        )
        if rc:
            raise RuntimeError(f"MF UrsusBoot install returned rc={rc}")
    return _wait_recovery()


def mf_runtime_mode(st: dict) -> str:
    """Classify MF UrsusBoot by explicit write capability, never by version alone."""
    persistent = st.get("persistent_write_enabled")
    ram_ro = st.get("ram_read_only")
    if persistent is True and ram_ro is False:
        return "PERSISTENT_RUNTIME"
    if persistent is False or ram_ro is True:
        return "RAM_ONLY"
    # Legacy MF Recovery without capability fields is conservative/read-only.
    return "LEGACY_RAM_ONLY"


def _require_mf_persistent_runtime(st: dict) -> None:
    mode = mf_runtime_mode(st)
    ui.status(tr("РЕЖИМ", "MODE"), f"MF UrsusBoot: {mode}")
    if mode != "PERSISTENT_RUNTIME":
        raise RuntimeError(tr(
            "Обнаружен MF RAM-only/legacy Recovery, а не persistent UrsusBoot. ONE-KEY остановлен ДО записи OpenWrt. Не обходите HTTP 403: верните/загрузите Nokia stock и запустите ONE-KEY снова; тогда сначала будет установлен device-derived persistent UrsusBoot-MF.",
            "MF RAM-only/legacy Recovery was detected instead of persistent UrsusBoot. ONE-KEY stopped BEFORE any OpenWrt write. Do not bypass HTTP 403: boot/restore Nokia stock and run ONE-KEY again; it will install the device-derived persistent UrsusBoot-MF first.",
        ))


def _report_runtime(st: dict, family: str) -> None:
    version = str(st.get("version") or "UNKNOWN")
    target = MD_TARGET if family == "md" else MF_TARGET
    if version == target:
        ui.status(tr("ГОТОВО", "READY"), f"UrsusBoot {version} ({family.upper()})")
    else:
        ui.status(tr("ИНФО", "INFO"), tr(
            f"Запущен UrsusBoot {version}; целевая линия {family.upper()} — {target}. Автоматического второго обновления загрузчика нет.",
            f"Running UrsusBoot is {version}; the target {family.upper()} line is {target}. No automatic second bootloader update will be attempted.",
        ))


def _install_openwrt(st: dict, family: str, *, already_authorized: bool) -> dict:
    image = require_role(family, "OPENWRT_UBI_SYSUPGRADE")
    layout = str(st.get("current_layout") or "UNKNOWN")
    preloader = None
    if layout in ("STOCK", "OPENWRT_STOCK_LAYOUT"):
        preloader = require_role(family, "STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE")

    keep = True
    if layout == "OPENWRT_UBI":
        answer = ui.prompt(tr(
            "Сохранить текущие настройки OpenWrt? [Y/n]: ",
            "Keep the current OpenWrt settings? [Y/n]: ",
        )).strip().lower()
        keep = answer not in ("n", "no", "н", "нет")

    stage(
        "OpenWrt",
        "OpenWrt",
        f"Проверяю и загружаю {image.name}; layout={layout}.",
        f"Validating and staging {image.name}; layout={layout}.",
        "Для STOCK/Factory переход выполняется в UBI с board-specific BL2 последним. Для UBI обновляется только OpenWrt.",
        "For STOCK/Factory the migration goes to UBI with the board-specific BL2 committed last. For UBI only OpenWrt is updated.",
    )
    result = uw.update_firmware(
        HOST, image, preloader=preloader, keep_settings=keep,
        confirm=not already_authorized,
    )
    if not result.get("operation_complete"):
        raise RuntimeError("UrsusBoot did not report a completed OpenWrt operation")
    return result


def main(*, skip_full_backup: bool = False) -> int:
    pb.start_session_logging()
    ui.enable()
    choose_language()
    root = _root()
    version = ui.package_version(root)
    ui.banner("UrsusFlasher ONE-KEY", version=version)
    network_guidance.show()

    state = _probe(interactive_ssh=False)
    if state.current_system.startswith("OPENWRT") and state.probe_status != ds.PROBE_COMPLETE:
        state = _probe(interactive_ssh=True)
    family = _family(state)
    verify_family_payloads(family)
    ui.status(tr("УСТРОЙСТВО", "DEVICE"), f"{state.model} / {state.soc} / {family.upper()}")

    already_authorized = False
    if state.current_system == "RECOVERY":
        st = uw.status(HOST)
        family = _family_from_ursus(st)
        verify_family_payloads(family)
        if family == "mf":
            _require_mf_persistent_runtime(st)
    elif state.current_system in ("NOKIA_STOCK", "OPENWRT_UBI", "OPENWRT_FACTORY", "OPENWRT_STOCK_LAYOUT"):
        st = _install_bootloader(state, family, skip_full_backup)
        already_authorized = True
        # A newly installed MF runtime must prove persistent write capability
        # before ONE-KEY is allowed to enter the OpenWrt writer.
        if family == "mf":
            _require_mf_persistent_runtime(st)
    else:
        raise RuntimeError(tr(
            f"ONE-KEY не может безопасно продолжить из состояния {state.current_system}.",
            f"ONE-KEY cannot safely continue from state {state.current_system}.",
        ))

    recovery_family = _family_from_ursus(st)
    if recovery_family != family:
        raise RuntimeError(f"family changed across reboot: {family} -> {recovery_family}")
    _report_runtime(st, family)

    result = _install_openwrt(st, family, already_authorized=already_authorized)
    ui.status(tr("ГОТОВО", "READY"), tr(
        f"Операция OpenWrt для {family.upper()} завершена и проверена.",
        f"The OpenWrt operation for {family.upper()} completed and was verified.",
    ))
    ui.note(tr(
        "Сейчас UrsusBoot перезагрузит устройство в установленную OpenWrt.",
        "UrsusBoot will now reboot the device into the installed OpenWrt.",
    ))
    time.sleep(1)
    uw.reboot(HOST)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        ui.status(tr("СТОП", "STOP"), tr("Остановлено пользователем.", "Stopped by user."))
        raise SystemExit(130)
    except Exception as exc:
        print()
        ui.status(tr("ОШИБКА", "ERROR"), str(exc), stream=sys.stderr)
        raise SystemExit(1)

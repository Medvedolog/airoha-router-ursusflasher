#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import ui_terms as terms

HERE = Path(__file__).resolve().parent
KIT = HERE.parent.parent if (HERE.parent.parent / "config").is_dir() else HERE.parent
DATA = HERE if not (KIT / "config").is_dir() else KIT / "config"
WORK = (HERE.parent if not (KIT / "config").is_dir() else KIT) / "work"

PROBE_COMPLETE = "COMPLETE"
PROBE_PARTIAL = "PARTIAL"
PROBE_FAILED = "FAILED"

EXEC_PERSISTENT_ROOT = "PERSISTENT_ROOT"
EXEC_RAM_ROOT = "RAM_ROOT"
EXEC_UNKNOWN = "UNKNOWN"

# Every machine enum that can cross into production UI is declared here.
# selftest_stateui3_enum_coverage.py requires an explicit UI_TERMS entry for
# every value; adding an enum without a translation is therefore a build error.
HUMAN_ENUM_VALUES = {
    "system": (
        "NOKIA_STOCK", "OPENWRT_UBI", "OPENWRT_FACTORY", "RECOVERY",
        "STOCK", "OPENWRT_STOCK_LAYOUT", "BROKEN_TRANSITION", "UNKNOWN",
    ),
    "layout": (
        "NOKIA_STOCK", "OPENWRT_UBI", "OPENWRT_FACTORY",
        "STOCK", "OPENWRT_STOCK_LAYOUT", "BROKEN_TRANSITION", "UNKNOWN",
    ),
    "bootloader": ("URSUSBOOT", "TCBOOT", "STOCK_TCBOOT", "UNKNOWN"),
    "backup_state": (
        "NOT_FOUND", "FOUND", "FOUND_UNVERIFIED", "VERIFIED",
        "RESTORE_READY", "UNKNOWN",
    ),
    "probe_status": (PROBE_COMPLETE, PROBE_PARTIAL, PROBE_FAILED, "UNKNOWN"),
    "write_state": ("CLEAN", "WRITE_STATE_UNKNOWN", "LEGACY_UNTRACKED", "UNKNOWN"),
    "execution_environment": (EXEC_PERSISTENT_ROOT, EXEC_RAM_ROOT, EXEC_UNKNOWN),
    "method": ("AUTO_BOOTLOADER_INSTALL_REPAIR", "SSH_PERSISTENT_OPENWRT", "SSH_RAM_OPENWRT", "TELNET_NOKIA_STOCK"),
    "probe_reason": (
        "URSUS_MODEL_UNCONFIRMED",
        "STOCK_MODEL_SOC_MISMATCH",
        "OPENWRT_BOARD_LAYOUT_UNCONFIRMED",
        "OPENWRT_ROOT_SSH_UNAVAILABLE",
        "NO_NETWORK_ENDPOINT",
        "NETWORK_IDENTITY_AMBIGUOUS",
        "EXECUTION_ENVIRONMENT_UNCONFIRMED",
        "BOARD_PROFILE_WRITE_DISABLED",
        "UNKNOWN",
    ),
}


@dataclass
class DeviceState:
    host: str = "192.168.1.1"
    probe_status: str = PROBE_FAILED
    probe_reasons: list[str] = field(default_factory=list)
    model: str = "UNKNOWN"
    soc: str = "UNKNOWN"
    nand_vendor: str = "UNKNOWN"
    nand_model: str = "UNKNOWN"
    nand_capacity: int | None = None
    nand_erase_size: int | None = None
    current_system: str = "UNKNOWN"
    current_layout: str = "UNKNOWN"
    execution_environment: str = EXEC_UNKNOWN
    bootloader: str = "UNKNOWN"
    bootloader_version: str = "UNKNOWN"
    access: dict[str, Any] = field(default_factory=dict)
    backup_state: str = "NOT_FOUND"
    write_state: str = "LEGACY_UNTRACKED"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionApplicability:
    number: int
    key: str
    enabled: bool
    reason: str
    note: str
    write_capable: bool
    resolved_backend: str


_PROBE_RANK = {PROBE_COMPLETE: 0, PROBE_PARTIAL: 1, PROBE_FAILED: 2}


def degrade_probe_status(state: DeviceState, status: str, reason_code: str | None = None) -> None:
    """Monotonically reduce DeviceState completeness; never promote it."""
    if status not in _PROBE_RANK:
        raise ValueError(f"unknown probe status: {status}")
    current = state.probe_status if state.probe_status in _PROBE_RANK else PROBE_FAILED
    if _PROBE_RANK[status] > _PROBE_RANK[current]:
        state.probe_status = status
    if reason_code and reason_code not in state.probe_reasons:
        state.probe_reasons.append(reason_code)


ACTION_KEYS = {
    1: "install_openwrt",
    2: "install_or_repair_bootloader",
    3: "custom_openwrt",
    4: "update_bootloader",
    5: "recover_bootloader",
    6: "restore_nokia",
    7: "full_backup",
    8: "validate_backup",
    9: "disaster_kit",
    10: "capabilities",
    11: "flash_diagnostics",
    12: "package_files",
}


def _tcp_open(host: str, port: int, timeout: float = 0.65) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def _load_capabilities() -> dict[str, Any]:
    candidates = [
        KIT / "config" / "FIRMWARE_CAPABILITIES.json",
        HERE / "FIRMWARE_CAPABILITIES.json",
    ]
    for path in candidates:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _backup_state() -> str:
    roots = [WORK / "backups"]
    found = False
    verified = False
    for root in roots:
        if not root.is_dir():
            continue
        for item in root.iterdir():
            if not item.is_dir():
                continue
            if any(item.glob("mtd16_*.bin.gz")) or (item / "BOOTROM_BACKUP.json").is_file():
                found = True
            if (item / "BACKUP_COMPLETE").is_file() and (item / "SHA256SUMS.txt").is_file():
                verified = True
    if verified:
        return "VERIFIED"
    return "FOUND_UNVERIFIED" if found else "NOT_FOUND"


def _normalize_layout(value: Any) -> str:
    raw = str(value or "UNKNOWN").upper()
    if raw == "STOCK":
        return "NOKIA_STOCK"
    if raw == "OPENWRT_STOCK_LAYOUT":
        return "OPENWRT_FACTORY"
    return raw


def _canonicalize_profile_identity(
    state: DeviceState,
    *,
    model: str = "",
    soc: str = "",
    board: str = "",
    require_soc: bool = False,
) -> str | None:
    """Apply canonical MD/MF identity from BOARD_PROFILES without authorizing writes."""
    if require_soc and not str(soc or "").strip():
        return None
    try:
        import board_profiles as bp
        identity = bp.canonical_identity(model=model, soc=soc, board=board)
    except Exception as exc:
        state.evidence["board_profile_error"] = f"{type(exc).__name__}: {exc}"
        return None
    if not identity:
        return None
    key, canonical_model, canonical_soc = identity
    state.model = canonical_model
    state.soc = canonical_soc
    state.evidence["board_profile"] = key
    return key


def _profile_for_state(state: DeviceState) -> tuple[str, dict[str, Any]] | None:
    try:
        import board_profiles as bp
        return bp.match_profile(model=state.model, soc=state.soc)
    except Exception as exc:
        state.evidence["board_profile_error"] = f"{type(exc).__name__}: {exc}"
        return None


def _extract_nand_from_ursus(st: dict[str, Any], state: DeviceState) -> None:
    for key in ("nand_model", "spinand_model", "nand_name", "flash_model"):
        value = st.get(key)
        if value:
            state.nand_model = str(value)
            break
    for key in ("nand_vendor", "spinand_vendor", "flash_vendor"):
        value = st.get(key)
        if value:
            state.nand_vendor = str(value)
            break
    for key in ("nand_size", "nand_capacity", "flash_size"):
        value = st.get(key)
        try:
            if value is not None:
                state.nand_capacity = int(value)
                break
        except (TypeError, ValueError):
            pass
    for key in ("erase_size", "nand_erase_size", "mtd_erasesize"):
        value = st.get(key)
        try:
            if value is not None:
                state.nand_erase_size = int(value)
                break
        except (TypeError, ValueError):
            pass


def _probe_ursus(host: str, state: DeviceState) -> bool:
    try:
        import ursus_web_client as uw
        st = uw.status(host)
    except Exception as exc:
        state.evidence["ursus_error"] = f"{type(exc).__name__}: {exc}"
        return False
    state.evidence["ursus_status"] = st
    state.current_system = "RECOVERY"
    state.current_layout = _normalize_layout(st.get("current_layout"))
    version = str(st.get("version") or "UNKNOWN")
    state.bootloader = "URSUSBOOT"
    state.bootloader_version = version
    board = str(st.get("board") or st.get("board_name") or st.get("fdt_model") or "")
    soc = str(st.get("soc") or st.get("soc_name") or "")
    if not _canonicalize_profile_identity(state, board=board, soc=soc):
        if board:
            state.model = board
            state.soc = soc or "UNKNOWN"
        elif state.current_layout in ("NOKIA_STOCK", "OPENWRT_UBI", "OPENWRT_FACTORY"):
            # Legacy fallback applies only to the shipped MD-only UrsusBoot lineage.
            state.model = "Nokia XG-040G-MD"
            state.soc = soc or "Airoha AN7581"
            state.evidence["board_profile"] = "md-legacy-fallback"
    _extract_nand_from_ursus(st, state)
    if state.model == "UNKNOWN":
        degrade_probe_status(state, PROBE_PARTIAL, "URSUS_MODEL_UNCONFIRMED")
    return True


def _probe_stock_web(host: str, state: DeviceState) -> bool:
    try:
        import stock_web
        client = stock_web.StockWeb(host)
        try:
            client.login(stock_web.DEFAULT_WEB_USER, stock_web.DEFAULT_WEB_PASSWORD, allow_plain=False)
            setup = stock_web.StockSetup(client)
            info = setup.read_device_info()
        finally:
            client.logout()
    except Exception as exc:
        state.evidence["stock_web_error"] = f"{type(exc).__name__}: {exc}"
        return False
    state.current_system = "NOKIA_STOCK"
    state.current_layout = "NOKIA_STOCK"
    state.model = str(info.get("model") or "UNKNOWN")
    state.soc = str(info.get("chipset") or "UNKNOWN")
    # A running vendor OS proves the OS, not necessarily which persistent first stage booted it.
    state.bootloader = "UNKNOWN"
    state.bootloader_version = "UNKNOWN"
    state.evidence["stock_device_info"] = info
    if not _canonicalize_profile_identity(
        state,
        model=str(info.get("model") or ""),
        soc=str(info.get("chipset") or ""),
        require_soc=True,
    ):
        degrade_probe_status(state, PROBE_PARTIAL, "STOCK_MODEL_SOC_MISMATCH")
    return True


def _parse_mount_record(raw: str) -> tuple[str, str, str]:
    parts = str(raw or "").strip().split("|", 2)
    while len(parts) < 3:
        parts.append("")
    return parts[0], parts[1].lower(), parts[2]


def classify_openwrt_execution_environment(root_mount: str, rom_mount: str = "", overlay_mount: str = "") -> str:
    """Classify the executing OpenWrt root from actual mount topology."""
    root_src, root_fs, _ = _parse_mount_record(root_mount)
    rom_src, rom_fs, _ = _parse_mount_record(rom_mount)
    ov_src, ov_fs, _ = _parse_mount_record(overlay_mount)
    persistent_fs = {"squashfs", "ubifs", "jffs2", "f2fs", "ext4", "erofs"}
    ram_fs = {"rootfs", "tmpfs", "ramfs"}

    def persistent_source(src: str) -> bool:
        low = src.lower()
        return low.startswith("/dev/") or "ubi" in low or "mtd" in low or "ubiblock" in low

    # The current root mount is authoritative for the execution environment.
    # A RAM root may still mount persistent flash elsewhere for inspection; that
    # does not turn the executing root into a persistent one.
    if root_fs in ram_fs:
        return EXEC_RAM_ROOT
    if root_fs in persistent_fs or persistent_source(root_src):
        return EXEC_PERSISTENT_ROOT
    if root_fs == "overlay" or root_src.startswith("overlayfs:"):
        # Production OpenWrt normally has flash-backed /rom and/or /overlay.
        if rom_fs in persistent_fs or persistent_source(rom_src):
            return EXEC_PERSISTENT_ROOT
        if ov_fs in persistent_fs or persistent_source(ov_src):
            return EXEC_PERSISTENT_ROOT
        return EXEC_UNKNOWN
    return EXEC_UNKNOWN


def _probe_openwrt_ssh(host: str, state: DeviceState, *, interactive: bool = False) -> bool:
    try:
        import proven_backend as pb
        command = (
            "echo __URSUS_STATE__; "
            "printf 'BOARD='; cat /tmp/sysinfo/board_name 2>/dev/null; echo; "
            "printf 'MODEL='; cat /tmp/sysinfo/model 2>/dev/null; echo; "
            "printf 'MACHINE='; cat /proc/device-tree/model 2>/dev/null | tr '\\000' ' '; echo; "
            "printf 'MTD='; cat /proc/mtd 2>/dev/null | tr '\\n' ';'; echo; "
            "printf 'FIPVOL='; ubinfo -a 2>/dev/null | awk '$1==\"Name:\" && $2==\"fip\" {print $2}' | head -n1; echo; "
            "printf 'ROOTMOUNT='; awk '$2==\"/\" {print $1 \"|\" $3 \"|\" $4; exit}' /proc/mounts 2>/dev/null; echo; "
            "printf 'ROMMOUNT='; awk '$2==\"/rom\" {print $1 \"|\" $3 \"|\" $4; exit}' /proc/mounts 2>/dev/null; echo; "
            "printf 'OVERLAYMOUNT='; awk '$2==\"/overlay\" {print $1 \"|\" $3 \"|\" $4; exit}' /proc/mounts 2>/dev/null; echo; "
            "printf 'RELEASE='; . /etc/openwrt_release 2>/dev/null; printf '%s/%s' \"$DISTRIB_RELEASE\" \"$DISTRIB_REVISION\"; echo"
        )
        if interactive:
            _, out = pb.ssh_run(
                host, command, timeout=90, quiet=False, batch_mode=False, password_prompts=3
            )
        else:
            _, out = pb.ssh_run(host, command, timeout=25, quiet=True, batch_mode=True)
    except Exception as exc:
        state.evidence["openwrt_ssh_error"] = f"{type(exc).__name__}: {exc}"
        return False
    state.evidence["openwrt_probe"] = out[-12000:]

    def val(name: str) -> str:
        m = re.search(rf"(?:^|\n){re.escape(name)}=([^\r\n]*)", out)
        return m.group(1).strip() if m else ""

    board = val("BOARD")
    model = val("MODEL") or val("MACHINE")
    mtd = val("MTD")
    fip = val("FIPVOL")
    root_mount = val("ROOTMOUNT")
    rom_mount = val("ROMMOUNT")
    overlay_mount = val("OVERLAYMOUNT")
    state.execution_environment = classify_openwrt_execution_environment(root_mount, rom_mount, overlay_mount)
    state.evidence["root_mount"] = root_mount
    state.evidence["rom_mount"] = rom_mount
    state.evidence["overlay_mount"] = overlay_mount

    profile_key = _canonicalize_profile_identity(state, model=model, board=board)
    if fip == "fip":
        state.current_system = "OPENWRT_UBI"
        state.current_layout = "OPENWRT_UBI"
    elif profile_key:
        state.current_system = "OPENWRT_FACTORY"
        state.current_layout = "OPENWRT_FACTORY"
    else:
        state.current_system = "UNKNOWN"

    if fip == "fip":
        state.bootloader = "URSUSBOOT"
        state.bootloader_version = "UNKNOWN"
    else:
        state.bootloader = "UNKNOWN"

    # Physical capacity/erase geometry can often be inferred from /proc/mtd without vendor guessing.
    rows = re.findall(r"mtd\d+:\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+\"([^\"]+)\"", mtd)
    if rows:
        try:
            state.nand_erase_size = int(rows[0][1], 16)
            largest = max(int(size, 16) for size, _, _ in rows)
            if largest == 0x10000000:
                state.nand_capacity = largest
        except ValueError:
            pass
    if state.model == "UNKNOWN" or state.current_system == "UNKNOWN":
        degrade_probe_status(state, PROBE_PARTIAL, "OPENWRT_BOARD_LAYOUT_UNCONFIRMED")
    if state.current_system.startswith("OPENWRT") and state.execution_environment == EXEC_UNKNOWN:
        degrade_probe_status(state, PROBE_PARTIAL, "EXECUTION_ENVIRONMENT_UNCONFIRMED")
    return True


def probe_device_state(host: str = "192.168.1.1", *, interactive_ssh: bool = False) -> DeviceState:
    # Probe aggregation starts optimistically and may only degrade.
    state = DeviceState(host=host, probe_status=PROBE_COMPLETE)
    ports = {p: _tcp_open(host, p) for p in (22, 23, 80, 443)}
    state.access = {
        "ip_reachable": any(ports.values()),
        "http": ports[80],
        "https": ports[443],
        "ssh": ports[22],
        "telnet": ports[23],
        "root": "UNKNOWN",
    }
    state.backup_state = _backup_state()
    state.evidence["tcp_ports"] = ports
    if not any(ports.values()):
        degrade_probe_status(state, PROBE_FAILED, "NO_NETWORK_ENDPOINT")
        return state

    if ports[80] and _probe_ursus(host, state):
        return state

    http_kind = "none"
    try:
        import one_key
        http_kind = one_key.probe_http_identity(host)
    except Exception as exc:
        state.evidence["http_fingerprint_error"] = f"{type(exc).__name__}: {exc}"
    state.evidence["http_kind"] = http_kind

    if http_kind == "openwrt":
        state.access["root"] = "UNKNOWN"
        if ports[22] and _probe_openwrt_ssh(host, state, interactive=interactive_ssh):
            state.access["root"] = True
            return state
        state.current_system = "UNKNOWN"
        degrade_probe_status(state, PROBE_PARTIAL, "OPENWRT_ROOT_SSH_UNAVAILABLE")
        return state

    # The lightweight HTTP fingerprint returns ``nokia_stock`` only after
    # matching multiple vendor-login markers.  A generic ``http`` response is
    # deliberately insufficient evidence for entering the stock Web flow.
    if http_kind == "nokia_stock" and _probe_stock_web(host, state):
        return state

    degrade_probe_status(state, PROBE_PARTIAL, "NETWORK_IDENTITY_AMBIGUOUS")
    return state


def _action_specs() -> dict[str, dict[str, Any]]:
    caps = _load_capabilities()
    specs = caps.get("ui_actions")
    return specs if isinstance(specs, dict) else {}


def _spec_text(spec: dict[str, Any], base: str, default_ru: str, default_en: str) -> str:
    if terms.is_en():
        return str(spec.get(base + "_en") or default_en)
    return str(spec.get(base + "_ru") or default_ru)


def action_applicability(state: DeviceState) -> dict[int, ActionApplicability]:
    specs = _action_specs()
    out: dict[int, ActionApplicability] = {}
    board_match = _profile_for_state(state)
    board_profile = board_match[1] if board_match else None
    board_key = board_match[0] if board_match else None
    for number, key in ACTION_KEYS.items():
        spec = specs.get(key, {}) if isinstance(specs, dict) else {}
        write_capable = bool(spec.get("write_capable", number in (1, 2, 3, 4, 5, 6)))
        implemented = bool(spec.get("implemented", number not in (6, 9)))
        enabled = implemented
        reason = ""
        note = ""
        backend = str(spec.get("backend") or "NONE")
        if not implemented:
            enabled = False
            reason = _spec_text(spec, "unavailable_reason", "не реализовано в этой версии", "not implemented in this version")
        elif key == "install_or_repair_bootloader":
            if state.current_system == "RECOVERY":
                backend = "URSUSBOOT_RECOVERY_SELFUPDATE"
            elif state.current_system.startswith("OPENWRT") and state.execution_environment == EXEC_RAM_ROOT:
                backend = "SSH_RAM_OPENWRT"
            elif state.current_system.startswith("OPENWRT") and state.execution_environment == EXEC_PERSISTENT_ROOT:
                backend = "SSH_PERSISTENT_OPENWRT"
            elif state.current_system == "NOKIA_STOCK":
                backend = "TELNET_NOKIA_STOCK"
        elif key == "update_bootloader":
            # Hidden compatibility alias for historical EXPERT item 4.
            backend = "ALIAS_TO_ACTION_2"
            enabled = out.get(2, ActionApplicability(2, "install_or_repair_bootloader", True, "", "", True, "AUTO_URSUSBOOT_INSTALL_UPDATE")).enabled
            reason = out.get(2, ActionApplicability(2, "install_or_repair_bootloader", True, "", "", True, "AUTO_URSUSBOOT_INSTALL_UPDATE")).reason
        elif key == "custom_openwrt":
            if state.current_system == "RECOVERY":
                backend = "URSUSBOOT_RECOVERY_CUSTOM_IMAGE"
            elif state.current_system.startswith("OPENWRT") and state.execution_environment == EXEC_PERSISTENT_ROOT:
                backend = "SSH_PERSISTENT_OPENWRT_SYSUPGRADE"
            else:
                enabled = False
                reason = terms.tr(
                    "доступно из установленной OpenWrt или UrsusBoot Recovery",
                    "available from installed OpenWrt or UrsusBoot Recovery",
                )
        elif key == "full_backup":
            if state.current_system == "NOKIA_STOCK" and state.probe_status == PROBE_COMPLETE:
                backend = "STOCK_READONLY_TFTP_OR_BOOTROM"
            else:
                backend = "BOOTROM_RAM_READONLY"
        elif key == "validate_backup" and state.backup_state == "NOT_FOUND":
            # The action remains enabled: an external path can be entered manually.
            note = terms.tr(
                "Локальная копия не найдена. Можно указать путь вручную.",
                "No local backup was found. A path can be entered manually.",
            )

        # MF1 contract: recognition and read-only operations are enabled, but a
        # board profile may explicitly withhold every persistent writer.  This
        # is a profile-level safety gate, not a backend-specific pile of `if mf`.
        if enabled and write_capable and board_profile is not None:
            try:
                import board_profiles as bp
                writes_enabled = bp.persistent_writes_enabled(board_profile)
            except Exception:
                writes_enabled = False
            if not writes_enabled:
                enabled = False
                backend = str((board_profile.get("write_policy") or {}).get("backend") or "BOARD_PROFILE_WRITE_DISABLED")
                reason = terms.tr(
                    f"профиль {board_key.upper()} подключён только для чтения; persistent write будет включён после аппаратной приёмки",
                    f"{board_key.upper()} profile is read-only; persistent writes stay disabled until hardware acceptance",
                )

        # Contract: reason describes disabled state only; enabled actions use note.
        if enabled:
            reason = ""
        out[number] = ActionApplicability(number, key, enabled, reason, note, write_capable, backend)
    return out


def state_summary_lines(state: DeviceState, *, english: bool = False) -> list[str]:
    # Keep the compatibility argument, but localization is centralized in UI_TERMS.
    old_lang = os.environ.get("NOKIA_LANG")
    if english:
        os.environ["NOKIA_LANG"] = "en"
    try:
        model = terms.human(state.model, "identity")
        soc = terms.human(state.soc, "identity")
        system = terms.human(state.current_system, "system")
        bootloader = terms.human(state.bootloader, "bootloader")
        if state.bootloader_version != "UNKNOWN":
            bootloader += " " + terms.human(state.bootloader_version, "version")
        host = terms.human(state.host, "address")
        web = terms.human(state.access.get("http"), "tri_bool")
        ssh = terms.human(state.access.get("ssh"), "tri_bool")
        root = terms.human(state.access.get("root"), "tri_bool")
        backup = terms.human(state.backup_state, "backup_state")
        probe = terms.human(state.probe_status, "probe_status")
        write = terms.human(state.write_state, "write_state")
        environment = terms.human(state.execution_environment, "execution_environment")
        if terms.is_en():
            lines = [f"{model} · {soc}", f"System:          {system}"]
            if state.current_system.startswith("OPENWRT"):
                lines.append(f"Execution root:  {environment}")
            lines.extend([
                f"Bootloader:      {bootloader}",
                f"Access:          {host} · Web {web} · SSH {ssh} · root {root}",
                f"Backup:          {backup}",
                f"State check:     {probe}",
                f"Write tracking:  {write}",
            ])
            return lines
        lines = [f"{model} · {soc}", f"Система:          {system}"]
        if state.current_system.startswith("OPENWRT"):
            lines.append(f"Среда выполнения: {environment}")
        lines.extend([
            f"Загрузчик:        {bootloader}",
            f"Доступ:           {host} · Web {web} · SSH {ssh} · root {root}",
            f"Резервная копия:  {backup}",
            f"Проверка состояния: {probe}",
            f"Состояние записи: {write}",
        ])
        return lines
    finally:
        if english:
            if old_lang is None:
                os.environ.pop("NOKIA_LANG", None)
            else:
                os.environ["NOKIA_LANG"] = old_lang

#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import proven_backend as proven

_INSTALLED = False


def _mf_write_mac(destination: Path, telnet, model_name: str, family: str):
    macs = proven._stock_interface_macs(telnet)
    mac = proven._stock_md_factory_mac(telnet)
    if mac == "UNKNOWN":
        # Do not turn an identity improvement into a new backup gate on an
        # unknown future RI revision. Fall back to the old runtime-MAC path.
        return _ORIG_MAC(destination, telnet, model_name, family)

    interface = "factory-ri"
    existing = proven._read_backup_device_mac(destination / "DEVICE_MAC.txt")
    if existing is not None and existing[1] != mac:
        raise proven.Error(proven.tr(
            f"backup-каталог уже привязан к другому MAC: {existing[1]} != {mac}",
            f"backup directory is already bound to a different MAC: {existing[1]} != {mac}",
        ))

    lines = [
        f"model={model_name}",
        "family=mf",
        f"captured_at_local={time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"captured_at_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "source=stock-factory-ri",
        "primary_interface=factory-ri",
        f"primary_mac={mac}",
        "primary_mac_source=ri@0x3e",
        "identity_policy=mf-factory-ri-v1",
    ]
    for name, value in macs.items():
        lines.append(f"interface_{name}={value}")
    proven.write_text(destination / "DEVICE_MAC.txt", "\n".join(lines) + "\n")
    runtime_eth0 = macs.get("eth0", "UNKNOWN")
    print(proven.tr(
        f"[OK] Backup factory MAC: {mac} (ri@0x3e); stock eth0={runtime_eth0} сохранён только как диагностика.",
        f"[OK] Backup factory MAC: {mac} (ri@0x3e); stock eth0={runtime_eth0} is recorded as diagnostics only.",
    ))
    return interface, mac


def _clean(value: str) -> str:
    return proven._clean_ri_identity_value(value)


def _mf_write_identity(destination: Path, telnet, model_name: str, family: str):
    mac_fields = proven._read_backup_device_mac_fields(destination / "DEVICE_MAC.txt")
    identity: dict[str, str] = {
        "model": model_name,
        "family": "mf",
        "primary_mac": mac_fields.get("primary_mac", "UNKNOWN"),
        "primary_mac_source": mac_fields.get("primary_mac_source", mac_fields.get("primary_interface", "unknown")),
    }

    # MF hardware shows the same non-secret fixed RI identity layout as MD:
    # serial ASCII @0x1a, factory LAN MAC @0x3e, G.984 suffix @0x58.
    # Use the already-proven bounded readers; never dump surrounding RI data.
    ri = proven._stock_ri_identity(telnet)
    fixed = proven._stock_md_fixed_identity(telnet)
    if fixed:
        ri.update(fixed)

    yp = _clean(ri.get("YPSerialNum", ""))
    g984 = _clean(ri.get("G984Serial", ""))
    mfr = _clean(ri.get("MfrID", ""))
    serial = yp
    source = _clean(ri.get("_SerialSource", "")) or "ri/ritool:YPSerialNum"
    if not serial and mfr and g984:
        serial = (mfr + g984).upper()
        source = "ri/ritool:MfrID+G984Serial"
    if not serial:
        serial = "UNKNOWN"
        source = "unavailable"

    primary = identity.get("primary_mac", "").lower()
    identity.update({
        "serial_number": serial,
        "serial_source": source,
        "g984_serial": g984 or "UNKNOWN",
        "mfr_id": mfr or "UNKNOWN",
        "part_number": _clean(ri.get("PartNumber", "")) or "UNKNOWN",
        "hardware_version": _clean(ri.get("HardwareVersion", "")) or "UNKNOWN",
        "mnemonic": _clean(ri.get("Mnemonic", "")) or "UNKNOWN",
        "program_date": _clean(ri.get("ProgDate", "")) or "UNKNOWN",
        "ri_mac": primary if re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", primary) else (_clean(ri.get("MACAddress", "")).lower() or "UNKNOWN"),
    })
    lines = [
        f"model={identity['model']}",
        "family=mf",
        f"serial_number={identity['serial_number']}",
        f"serial_source={identity['serial_source']}",
        f"g984_serial={identity['g984_serial']}",
        f"mfr_id={identity['mfr_id']}",
        f"part_number={identity['part_number']}",
        f"hardware_version={identity['hardware_version']}",
        f"mnemonic={identity['mnemonic']}",
        f"program_date={identity['program_date']}",
        f"primary_mac={identity['primary_mac']}",
        f"primary_mac_source={identity['primary_mac_source']}",
        f"ri_mac={identity['ri_mac']}",
        "identity_origin=stock_ri_read_only",
        "identity_policy=mf-factory-ri-v1",
    ]
    proven.write_text(destination / "DEVICE_IDENTITY.txt", "\n".join(lines) + "\n")
    proven.write_text(destination / "DEVICE_IDENTITY.json", json.dumps(identity, ensure_ascii=False, indent=2) + "\n")
    if serial == "UNKNOWN":
        print(proven.tr(
            "[ВНИМАНИЕ] MF fixed RI identity не распознана; backup продолжается без нового запрета.",
            "[WARNING] MF fixed RI identity was not recognized; backup continues without a new gate.",
        ))
    else:
        print(proven.tr(
            f"[ГОТОВО] Заводской серийный номер: {serial} ({source}); factory MAC={identity['primary_mac']}.",
            f"[PASS] Factory serial: {serial} ({source}); factory MAC={identity['primary_mac']}.",
        ))
    return identity


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    proven._write_backup_device_mac = lambda destination, telnet, model_name, family: (
        _mf_write_mac(destination, telnet, model_name, family)
        if str(family).lower() == "mf"
        else _ORIG_MAC(destination, telnet, model_name, family)
    )
    proven._write_backup_device_identity = lambda destination, telnet, model_name, family: (
        _mf_write_identity(destination, telnet, model_name, family)
        if str(family).lower() == "mf"
        else _ORIG_ID(destination, telnet, model_name, family)
    )
    _INSTALLED = True


_ORIG_MAC = proven._write_backup_device_mac
_ORIG_ID = proven._write_backup_device_identity

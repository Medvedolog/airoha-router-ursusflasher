#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys
from pathlib import Path

D = Path(__file__).resolve().parents[1]
DATA = D / "data" if (D / "data").is_dir() else D / "src"
ROOT = D.parent if (D / "src").is_dir() else D
os.environ.setdefault("NOKIA_LANG", "en")
sys.path.insert(0, str(DATA))

import device_state as ds

manifest_path = D / "data/MANIFEST.json" if (D / "data/MANIFEST.json").is_file() else ROOT / "config/MANIFEST.json"
caps_path = D / "data/FIRMWARE_CAPABILITIES.json" if (D / "data/FIRMWARE_CAPABILITIES.json").is_file() else ROOT / "config/FIRMWARE_CAPABILITIES.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
caps = json.loads(caps_path.read_text(encoding="utf-8"))

policy = manifest["ursusboot"]["layout_policy"]
assert policy["STOCK->OPENWRT_STOCK_LAYOUT"].startswith("DENY")
assert policy["OPENWRT_STOCK_LAYOUT->OPENWRT_STOCK_LAYOUT"].startswith("DENY")
assert policy["STOCK->OPENWRT_UBI"] == "ALLOW"
assert policy["OPENWRT_STOCK_LAYOUT->OPENWRT_UBI"] == "ALLOW_RECOVERY_ONLY"
assert policy["OPENWRT_UBI->OPENWRT_UBI"] == "ALLOW"
assert caps["md"]["OPENWRT_STOCK_LAYOUT_UPDATE"].startswith("RETIRED_T80")

client = (DATA / "ursus_web_client.py").read_text(encoding="utf-8")
assert "OPENWRT_NONUBI_SYSUPGRADE" in client
assert "stock-layout OpenWrt target retired on Nokia MD/MF" in client
assert "/api/install-openwrt-stock-layout" not in client
assert "INSTALL-OPENWRT-STOCK-LAYOUT" not in client
assert "/api/install-ubi" in client
assert "OPENWRT_STOCK_LAYOUT" in client

stock_layout = ds.DeviceState(
    probe_status=ds.PROBE_COMPLETE,
    model="Nokia XG-040G-MD",
    soc="Airoha AN7581",
    current_system="OPENWRT_FACTORY",
    current_layout="OPENWRT_FACTORY",
    execution_environment=ds.EXEC_PERSISTENT_ROOT,
    bootloader="URSUSBOOT",
)
a = ds.action_applicability(stock_layout)
assert not a[3].enabled
assert a[3].resolved_backend == "MIGRATION_TO_UBI_ONLY"
assert "migration" in a[3].reason.lower()

ubi = ds.DeviceState(
    probe_status=ds.PROBE_COMPLETE,
    model="Nokia XG-040G-MD",
    soc="Airoha AN7581",
    current_system="OPENWRT_UBI",
    current_layout="OPENWRT_UBI",
    execution_environment=ds.EXEC_PERSISTENT_ROOT,
    bootloader="URSUSBOOT",
)
assert ds.action_applicability(ubi)[3].resolved_backend == "SSH_PERSISTENT_OPENWRT_SYSUPGRADE"

onekey = (DATA / "one_key_multi.py").read_text(encoding="utf-8")
assert 'require_role(family, "OPENWRT_UBI_SYSUPGRADE")' in onekey
assert 'if layout in ("STOCK", "OPENWRT_STOCK_LAYOUT"):' in onekey
assert 'require_role(family, "STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE")' in onekey

print("T80_STOCK_LAYOUT_RETIREMENT_QA=PASS")

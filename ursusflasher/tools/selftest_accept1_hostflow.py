#!/usr/bin/env python3
from __future__ import annotations
import hashlib, inspect, os, sys
from pathlib import Path
D=Path(__file__).resolve().parents[1]
os.environ.setdefault("NOKIA_LANG","ru")
sys.path.insert(0,str(D/"data"))
import one_key as ok
import ursusboot_update as u
import expert

assert ok.TARGET_URSUS == '0.1.0-alpha5-UBIUX1-TEST61'
assert u.PRODUCTION_PAYLOAD.name == "ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip"
assert hashlib.sha256(u.PRODUCTION_PAYLOAD.read_bytes()).hexdigest() == '3c922e4256b6047376a7d445006e6cb2a4485bb412747033a77defd15e42fcea'
assert u.EMERGENCY_PAYLOAD.name == "ursusboot-md-0.1.0-alpha3-update.fip"
assert hashlib.sha256(u.EMERGENCY_PAYLOAD.read_bytes()).hexdigest() == "597071e178470bfda23aab9738ad7ddb0b25e9b21ef336fd3eceb39c39f983ce"
u.require_fip_payload()

one_src=(D/"data/one_key.py").read_text(encoding="utf-8")
assert not hasattr(ok, "ensure_target_ursus")
assert "ensure_target_ursus" not in one_src
assert "update_bootloader(" not in one_src
assert "manual" in inspect.getsource(ok.report_ursus_version).lower() or "вручную" in inspect.getsource(ok.report_ursus_version).lower()

install_src=inspect.getsource(ok.install_ursus_from_openwrt)+inspect.getsource(ok.install_ursus_from_stock)
assert "recovery_after=True" in install_src
assert "wait_for_manual_recovery()" in install_src
assert "5 секунд" not in one_src
assert "at least 5 seconds" not in one_src

# Ordinary explicit update and emergency recovery remain separate.
assert "PRODUCTION_PAYLOAD" in inspect.getsource(u.web_fip_update)
assert "PRODUCTION_PAYLOAD" in inspect.getsource(u.tftp_update_automated)
assert "EMERGENCY_PAYLOAD" in inspect.getsource(u.require_emergency_payloads)
assert "require_fip_payload" not in inspect.getsource(u.require_emergency_payloads)

assert "Нажмите Enter, чтобы вернуться в меню EXPERT" in inspect.getsource(expert.run_action)
assert not (D/"START.cmd").exists() and not (D/"START.sh").exists()
assert "target_already_exact" in (D/"data/ursusboot_install.py").read_text(encoding="utf-8")
assert {p.name for p in D.glob("START*.cmd")} == {"START_ONECLICK.cmd","START_EXPERT.cmd"}
launcher=(D/"START_ONECLICK.cmd").read_text(encoding="utf-8")
assert "pause >nul" in launcher and "data\\one_key.py" in launcher

print("TEST61_ACCEPT1_HOSTFLOW_QA=PASS")
print("INSTALLED_URSUSBOOT_AUTOUPDATE=FORBIDDEN")
print("EXPLICIT_UPDATE_AND_EMERGENCY_SPLIT=PASS")

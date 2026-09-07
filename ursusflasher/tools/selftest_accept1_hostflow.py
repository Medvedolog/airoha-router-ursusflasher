#!/usr/bin/env python3
from __future__ import annotations
import hashlib, inspect, os, sys
from pathlib import Path
D=Path(__file__).resolve().parents[1]
os.environ.setdefault('NOKIA_LANG','ru')
sys.path.insert(0,str(D/'data'))
import one_key as ok
import ursusboot_update as u
import expert

assert ok.TARGET_URSUS == '0.1.0-alpha4-FUDAN1'
assert u.PRODUCTION_PAYLOAD.name == 'ursusboot-md-0.1.0-alpha4-FUDAN1-update.fip'
assert hashlib.sha256(u.PRODUCTION_PAYLOAD.read_bytes()).hexdigest() == 'ce43b56d86321ccb7657d2e9b7ddf58e811efc73927855bbb75e896c83b18600'
assert u.EMERGENCY_PAYLOAD.name == 'ursusboot-md-0.1.0-alpha3-update.fip'
assert hashlib.sha256(u.EMERGENCY_PAYLOAD.read_bytes()).hexdigest() == '597071e178470bfda23aab9738ad7ddb0b25e9b21ef336fd3eceb39c39f983ce'
u.require_fip_payload()

# HWFIX3 promotion must not force an intermediate reboot. The old runtime can
# finish the current safe Recovery transaction; final reboot activates HWFIX3.
seen={}
old_req=u.require_fip_payload
old_update=ok.uw.update_bootloader
try:
    u.require_fip_payload=lambda: seen.setdefault('gate',True)
    def fake_update(host, path, confirm=False):
        seen['host']=host; seen['path']=Path(path); seen['confirm']=confirm
        return {'version':'0.1.0-alpha3','current_layout':'STOCK','bootloader_update_layout':'STOCK'}
    ok.uw.update_bootloader=fake_update
    st=ok.ensure_target_ursus({'version':'0.1.0-alpha3','current_layout':'STOCK'})
finally:
    u.require_fip_payload=old_req
    ok.uw.update_bootloader=old_update
assert seen['gate'] and seen['path']==u.PRODUCTION_PAYLOAD and seen['confirm'] is False
assert st['_persistent_ursus_target']==ok.TARGET_URSUS
assert st['_runtime_ursus_version']=='0.1.0-alpha3'
assert not hasattr(ok,'physical_reboot_to_recovery')

src=inspect.getsource(ok.main)
assert 'recovery_after=True' in src
assert 'No intermediate alpha3 bootstrap is used.' in (D/'data/one_key.py').read_text(encoding='utf-8')
assert 'wait_for_manual_recovery()' in src
assert '_persistent_ursus_target' in src
assert '5 секунд' not in (D/'data/one_key.py').read_text(encoding='utf-8')
assert 'at least 5 seconds' not in (D/'data/one_key.py').read_text(encoding='utf-8')

# Ordinary update and emergency recovery are deliberately split.
assert 'PRODUCTION_PAYLOAD' in inspect.getsource(u.web_fip_update)
assert 'PRODUCTION_PAYLOAD' in inspect.getsource(u.tftp_update_automated)
assert 'EMERGENCY_PAYLOAD' in inspect.getsource(u.require_emergency_payloads)
assert 'require_fip_payload' not in inspect.getsource(u.require_emergency_payloads)
assert 'EMERGENCY_PAYLOAD' in inspect.getsource(u.require_fipold_experiment_payloads)

# UI return/close contract.
assert 'Нажмите Enter, чтобы вернуться в меню EXPERT' in inspect.getsource(expert.run_action)
assert not (D/'START.cmd').exists() and not (D/'START.sh').exists()
assert 'target_already_exact' in (D/'data/ursusboot_install.py').read_text(encoding='utf-8')
assert {p.name for p in D.glob('START*.cmd')} == {'START_ONECLICK.cmd','START_EXPERT.cmd'}
one=(D/'START_ONECLICK.cmd').read_text(encoding='utf-8')
assert 'pause >nul' in one and 'data\\one_key.py' in one

print('HWFIX3_ACCEPT1_HOSTFLOW_QA=PASS')
print('ONECLICK_TARGET=FUDAN1')
print('STOCK_BOOTSTRAP=REMOVED_FROM_ONECLICK')
print('INTERMEDIATE_REBOOT_AFTER_FUDAN1_UPDATE=NO')
print('EXPERT_ACTION_RETURN=ENTER_GATED')
print('DUPLICATE_START_LAUNCHER=REMOVED')

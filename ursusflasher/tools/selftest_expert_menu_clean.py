#!/usr/bin/env python3
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
expert=(ROOT/'data/expert.py').read_text(encoding='utf-8')
terms=json.loads((ROOT/'data/UI_TERMS.json').read_text(encoding='utf-8'))
a=terms['expert_actions']
expected={
 'install_openwrt':1,'install_or_repair_bootloader':2,'custom_openwrt':3,'update_bootloader':4,
 'recover_bootloader':5,'restore_nokia':6,'full_backup':7,'validate_backup':8,'disaster_kit':9,
 'capabilities':10,'flash_diagnostics':11,'package_files':12,
}
assert {k:int(v['number']) for k,v in a.items()}==expected
assert sorted(int(v['number']) for v in a.values())==list(range(1,13))
assert a['install_or_repair_bootloader']['ru']=='Установить или переустановить загрузчик'
assert '/' not in a['install_or_repair_bootloader']['ru']
assert a['restore_nokia']['ru']=='Восстановить заводскую прошивку Nokia'
assert 'device_state as ds' in expert
assert 'write_capable=a.write_capable' in expert
assert 'enabled=a.enabled' in expert
assert 'reason=a.reason' in expert
assert 'probe_status = ds.PROBE_COMPLETE' not in expert  # no forensic shortcut may fake completeness
for historical in ('bootrom_bl2_experiment','alpha4_ab_install','alpha4_ab_rollback','restore_mtd0','stock_access'):
    assert historical not in a
assert 'import alpha4_hwfix_test' not in expert
print('EXPERT_MENU_V529_QA=PASS')
print('VISIBLE_ACTIONS=1..12_CONTIGUOUS')
print('WRITE_MARKER=STRUCTURED_WRITE_CAPABLE_ONLY')

assert 'json.dumps(state.to_dict()' in expert  # raw state is still logged for diagnostics
assert 'proven._write_session_only("[DEVICESTATE-RAW]' in expert
assert 'print(json.dumps(state.to_dict()' not in expert  # never dump machine enums to operator UI
print('STATEUI2_RAW_DEVICESTATE_UI_LEAK=NONE')

from pathlib import Path
import os, sys
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data' if (ROOT/'data').is_dir() else ROOT/'src'
sys.path.insert(0,str(DATA))
import device_state as ds

# Incomplete passive state must not globally disable actions that own their own preflight.
s=ds.DeviceState(host='192.168.1.1', probe_status=ds.PROBE_PARTIAL)
s.access={'http':True,'ssh':True,'root':'UNKNOWN'}
s.current_system='UNKNOWN'; s.execution_environment=ds.EXEC_UNKNOWN
app=ds.action_applicability(s)
assert app[1].enabled, app[1]
assert app[2].enabled, app[2]
assert app[5].enabled, app[5]
# Action-specific gates remain action-specific.
assert not app[3].enabled and 'openwrt' in app[3].reason.lower(), app[3]
# Item 4 is now a real canonical action, not the historical alias to item 2.
assert ds.ACTION_KEYS[4] == 'restore_factory_bootarea', ds.ACTION_KEYS
assert app[4].key == 'restore_factory_bootarea', app[4]
assert app[4].write_capable, app[4]
# Informational/read-only actions stay reachable.
assert app[7].enabled and app[10].enabled and app[11].enabled and app[12].enabled

expert=(DATA/'expert.py').read_text(encoding='utf-8')
assert 'print_state_header(state)\n\n        ui.section' not in expert
assert 'subtitle=tr(' not in expert
terms=(DATA/'UI_TERMS.json').read_text(encoding='utf-8') if (DATA/'UI_TERMS.json').is_file() else (ROOT.parent/'config'/'UI_TERMS.json').read_text(encoding='utf-8')
assert 'Что этот роутер позволяет сделать' in terms
assert 'Состояние устройства и доступные операции' not in terms
print('STATEUI6_ACTION_PREFLIGHT_QA=PASS')

from pathlib import Path
import importlib.util, os, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'data'))
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
assert app[4].enabled and app[4].resolved_backend == 'ALIAS_TO_ACTION_2', app[4]
# Informational/read-only actions stay reachable.
assert app[7].enabled and app[10].enabled and app[11].enabled and app[12].enabled

expert=(ROOT/'data/expert.py').read_text(encoding='utf-8')
assert 'print_state_header(state)\n\n        ui.section' not in expert
assert 'subtitle=tr(' not in expert
terms=(ROOT/'data/UI_TERMS.json').read_text(encoding='utf-8')
assert 'Состояние устройства и доступные операции' in terms
print('STATEUI6_ACTION_PREFLIGHT_QA=PASS')

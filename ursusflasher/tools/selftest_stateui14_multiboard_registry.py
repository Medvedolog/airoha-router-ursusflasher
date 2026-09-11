#!/usr/bin/env python3
from __future__ import annotations
import os, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data' if (ROOT/'data').is_dir() else ROOT/'src'
sys.path.insert(0,str(DATA))
os.environ['NOKIA_LANG']='ru'

import device_state as ds
import ui_terms as terms
import expert_multi as multi

assert ds.ACTION_KEYS[4] == 'restore_factory_bootarea', ds.ACTION_KEYS

states=[
    ds.DeviceState(),
    ds.DeviceState(current_system='RECOVERY', current_layout='OPENWRT_UBI', bootloader='URSUSBOOT', evidence={'board_profile':'mf'}),
    ds.DeviceState(current_system='NOKIA_STOCK', current_layout='NOKIA_STOCK', model='Nokia XG-040G-MF', soc='Airoha AN7583', evidence={'board_profile':'mf'}),
    ds.DeviceState(current_system='NOKIA_STOCK', current_layout='NOKIA_STOCK', model='Nokia XG-040G-MD', soc='Airoha AN7581', evidence={'board_profile':'md'}),
]
for state in states:
    app=multi.action_applicability(state)
    assert set(app) == set(ds.ACTION_KEYS), (set(app),set(ds.ACTION_KEYS))
    for number,a in app.items():
        assert a.key == ds.ACTION_KEYS[number], (number,a.key,ds.ACTION_KEYS[number])
        assert a.key in terms._DATA['expert_actions'], (number,a.key,'missing expert_actions translation')
        title=terms.action_title(a.key)
        assert title and title != a.key, (number,a.key,title)

unknown_app=multi.action_applicability(ds.DeviceState())
assert unknown_app[4].resolved_backend == 'UART_BOOTAREA_FACTORY_RESTORE'
assert 'UART_BOOTAREA_FACTORY_RESTORE' in terms._DATA['methods']
assert terms.human('UART_BOOTAREA_FACTORY_RESTORE','method').startswith('Через USB-UART')

mf_recovery=states[1]
mf_app=multi.action_applicability(mf_recovery)
assert mf_app[2].enabled
assert mf_app[2].resolved_backend == 'MF_RECOVERY_DEVICE_DERIVED_FIP_UPDATE'
assert 'MF_RECOVERY_DEVICE_DERIVED_FIP_UPDATE' in terms._DATA['methods']
assert terms.human('MF_RECOVERY_DEVICE_DERIVED_FIP_UPDATE','method') != 'MF_RECOVERY_DEVICE_DERIVED_FIP_UPDATE'

assert 'AUTO_URSUSBOOT_INSTALL_UPDATE' in terms._DATA['methods']
assert 'AUTO_URSUSBOOT_INSTALL_UPDATE' not in terms._DATA['execution_environments']
assert terms.human('AUTO_URSUSBOOT_INSTALL_UPDATE','method') != 'AUTO_URSUSBOOT_INSTALL_UPDATE'

assert terms.action_title('future_action_key') == 'future_action_key'
assert terms.human('FUTURE_METHOD','method') == 'FUTURE_METHOD'

disabled=ds.DeviceState()
app=multi.action_applicability(disabled)
assert not app[3].enabled and app[3].reason
captured=[]
orig=multi.base._show_action
try:
    multi.base._show_action=lambda number, app, detail_ru='', detail_en='': captured.append((number,detail_ru,detail_en))
    multi._show_action(3,app,'DUPLICATE DETAIL','DUPLICATE DETAIL')
finally:
    multi.base._show_action=orig
assert captured == [(3,'','')], captured

print('STATEUI14_MULTIBOARD_REGISTRY_QA=PASS')

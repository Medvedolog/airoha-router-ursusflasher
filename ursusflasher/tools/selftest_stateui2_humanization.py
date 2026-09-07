#!/usr/bin/env python3
from __future__ import annotations
import os, sys
from pathlib import Path
D=Path(__file__).resolve().parents[1]
os.environ['NOKIA_LANG']='ru'
sys.path.insert(0,str(D/'data'))
import device_state as ds
import ui_terms as terms

assert terms.human('NOKIA_STOCK','system')=='Заводская прошивка Nokia'
assert terms.human('PARTIAL','probe_status')=='данные неполные'
assert terms.human('NOT_FOUND','backup_state')=='не найдена'
assert terms.human('WRITE_STATE_UNKNOWN','write_state')=='состояние записи неизвестно'
assert terms.human('TCBOOT','bootloader')=='Заводской загрузчик Nokia (tcboot)'
assert terms.human('FOUND','backup_state')=='найдена, не проверена'
assert terms.human('CLEAN','write_state')=='нет незавершённых операций'
assert terms.human(True,'tri_bool')=='есть'
assert terms.human(False,'tri_bool')=='нет'
assert terms.human('UNKNOWN','tri_bool')=='не определён'
state=ds.DeviceState(
    probe_status=ds.PROBE_PARTIAL, model='Nokia XG-040G-MD', soc='Airoha AN7581',
    current_system='NOKIA_STOCK', bootloader='URSUSBOOT', backup_state='NOT_FOUND',
    write_state='WRITE_STATE_UNKNOWN', access={'http':True,'ssh':False,'root':True},
)
lines='\n'.join(ds.state_summary_lines(state))
for leaked in ('NOKIA_STOCK','NOT_FOUND','PARTIAL','WRITE_STATE_UNKNOWN','root True','Полнота probe'):
    assert leaked not in lines, (leaked, lines)
assert 'Заводская прошивка Nokia' in lines
assert 'root есть' in lines
assert 'Проверка состояния:' in lines
for code, expected in {
    'STOCK_MODEL_SOC_MISMATCH':'Заводской веб-интерфейс отвечает, но модель и SoC не совпали с XG-040G-MD / AN7581',
    'OPENWRT_BOARD_LAYOUT_UNCONFIRMED':'OpenWrt отвечает по SSH, но модель платы и разметка не подтверждены',
    'OPENWRT_ROOT_SSH_UNAVAILABLE':'OpenWrt отвечает по HTTP, но проверить доступ root по SSH не удалось',
    'URSUS_MODEL_UNCONFIRMED':'UrsusBoot отвечает, но модель не подтверждена',
    'NO_NETWORK_ENDPOINT':'Роутер не отвечает ни по одному известному адресу',
    'NETWORK_IDENTITY_AMBIGUOUS':'Устройство отвечает по сети, но определить его точно не удалось',
}.items():
    assert terms.human(code,'probe_reason')==expected
print('STATEUI2_HUMANIZATION_QA=PASS')

os.environ['NOKIA_LANG']='en'
assert terms.human('NOKIA_STOCK','system')=='Nokia factory firmware'
assert terms.human('PARTIAL','probe_status')=='partial'
assert terms.human(True,'tri_bool')=='yes'
eng='\n'.join(ds.state_summary_lines(state, english=True))
for leaked in ('NOKIA_STOCK','NOT_FOUND','PARTIAL','WRITE_STATE_UNKNOWN','root True'):
    assert leaked not in eng, (leaked, eng)
print('STATEUI2_EN_HUMANIZATION_QA=PASS')

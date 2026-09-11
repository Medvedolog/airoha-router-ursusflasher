#!/usr/bin/env python3
from __future__ import annotations
import os, sys
from pathlib import Path
D=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(D/'data'))
import device_state as ds
import ui_terms as terms

TABLES={
    'system':'systems',
    'layout':'layouts',
    'bootloader':'bootloaders',
    'backup_state':'backup_states',
    'probe_status':'probe_states',
    'write_state':'write_states',
    'execution_environment':'execution_environments',
    'method':'methods',
    'probe_reason':'probe_reasons',
}

# Build-time completeness remains strict even though runtime rendering is now
# resilient. Every declared production enum must have an explicit UI entry.
for kind,values in ds.HUMAN_ENUM_VALUES.items():
    table_name=TABLES[kind]
    table=terms._DATA[table_name]
    for value in values:
        assert value in table, (kind,value,'missing UI_TERMS entry')

for lang in ('ru','en'):
    os.environ['NOKIA_LANG']=lang
    for kind, values in ds.HUMAN_ENUM_VALUES.items():
        for value in values:
            rendered=terms.human(value,kind)
            assert rendered and rendered.strip(), (lang,kind,value,rendered)

# Runtime presentation must not take down a recovery UI when a new value slips
# through. The raw value is shown and the warning is logged by ui_terms.
os.environ['NOKIA_LANG']='ru'
assert terms.human('UNKNOWN','bootloader') == 'Не определён'
for kind,value in (('bootloader','TCBOOT2'),('backup_state','FOUND_NEW'),('write_state','CLEAN_NEW'),('execution_environment','RAM_ROOT_NEW'),('method','SSH_NEW')):
    assert terms.human(value,kind) == value, (kind,value)
assert terms.action_title('future_action_key') == 'future_action_key'

assert terms.human('TCBOOT','bootloader') == 'Заводской загрузчик Nokia (tcboot)'
assert terms.human('STOCK_TCBOOT','bootloader') == 'Заводской загрузчик Nokia (tcboot)'
assert terms.human('FOUND','backup_state') == 'найдена, не проверена'
assert terms.human('FOUND_UNVERIFIED','backup_state') == 'найдена, не проверена'
assert terms.human('CLEAN','write_state') == 'нет незавершённых операций'
print('STATEUI3_ENUM_COVERAGE_QA=PASS')

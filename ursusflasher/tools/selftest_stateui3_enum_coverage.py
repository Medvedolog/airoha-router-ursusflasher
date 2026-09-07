#!/usr/bin/env python3
from __future__ import annotations
import os, sys
from pathlib import Path
D=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(D/'data'))
import device_state as ds
import ui_terms as terms

for lang in ('ru','en'):
    os.environ['NOKIA_LANG']=lang
    for kind, values in ds.HUMAN_ENUM_VALUES.items():
        for value in values:
            rendered=terms.human(value,kind)
            assert rendered and rendered.strip(), (lang,kind,value,rendered)

# Unknown is an explicit valid enum; a new unregistered value must fail closed.
os.environ['NOKIA_LANG']='ru'
assert terms.human('UNKNOWN','bootloader') == 'Не определён'
for kind,value in (('bootloader','TCBOOT2'),('backup_state','FOUND_NEW'),('write_state','CLEAN_NEW'),('execution_environment','RAM_ROOT_NEW'),('method','SSH_NEW')):
    try:
        terms.human(value,kind)
    except KeyError:
        pass
    else:
        raise AssertionError((kind,value,'unexpected fallback instead of KeyError'))

assert terms.human('TCBOOT','bootloader') == 'Заводской загрузчик Nokia (tcboot)'
assert terms.human('STOCK_TCBOOT','bootloader') == 'Заводской загрузчик Nokia (tcboot)'
assert terms.human('FOUND','backup_state') == 'найдена, не проверена'
assert terms.human('FOUND_UNVERIFIED','backup_state') == 'найдена, не проверена'
assert terms.human('CLEAN','write_state') == 'нет незавершённых операций'
print('STATEUI3_ENUM_COVERAGE_QA=PASS')

#!/usr/bin/env python3
from __future__ import annotations
import inspect, os, sys
from pathlib import Path
D=Path(__file__).resolve().parents[1]
os.environ.setdefault('NOKIA_LANG','ru')
sys.path.insert(0,str(D/'data'))
import proven_backend as pb
import expert
src=inspect.getsource(pb.backup_tftp)
assert 'allow_service_provisioning: bool = True' in src
assert 'allow_service_provisioning=allow_service_provisioning' in src
strict=inspect.getsource(expert.backup_stock_readonly)
assert 'allow_service_provisioning=False' in strict
assert 'enable_telnet' not in inspect.getsource(expert._readonly_stock_access)
for bad in ('mtd write all_flash','nand write','saveenv','sysupgrade'):
    try:
        pb._assert_bootrom_backup_shell_safe(bad)
    except Exception:
        pass
    else:
        raise AssertionError(bad)
print('READONLY_BACKUP_V529_QA=PASS')

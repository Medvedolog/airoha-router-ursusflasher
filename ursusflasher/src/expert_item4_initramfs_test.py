#!/usr/bin/env python3
from __future__ import annotations
import os, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import console_ui as ui
import stock_ab_initramfs_test as test

def main() -> int:
    ui.enable(); ui.startup_bear(); ui.banner('UrsusFlasher EXPERT ITEM 4', subtitle='Vanilla OpenWrt pregnant initramfs — BOOT-ONLY HW test')
    print('  1  Nokia XG-040G-MD / AN7581 / Fudan-capable Linux snapshot')
    print('  2  Nokia XG-040G-MF / AN7583')
    value = ui.prompt('Модель [1/2]: ').strip()
    profile = {'1':'xg040-md','2':'xg040-mf'}.get(value)
    if not profile:
        ui.status('СТОП', 'Не выбрана поддерживаемая модель.'); return 1
    host = os.environ.get('NOKIA_ROUTER_IP','192.168.1.1').strip() or '192.168.1.1'
    return test.run_expert(host=host, profile=profile)

if __name__ == '__main__':
    raise SystemExit(main())

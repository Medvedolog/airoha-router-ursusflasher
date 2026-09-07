#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'data'))

import device_state as ds
import expert

calls = []
orig_install = expert.ursusboot_install.run_install
orig_update = expert.update_bootloader_network
try:
    expert.ursusboot_install.run_install = lambda **kw: calls.append(kw) or 0
    expert.update_bootloader_network = lambda: calls.append({'route': 'recovery'})

    ow = ds.DeviceState(host='192.168.1.1', probe_status=ds.PROBE_COMPLETE)
    ow.current_system = 'OPENWRT_UBI'
    ow.current_layout = 'OPENWRT_UBI'
    ow.execution_environment = ds.EXEC_PERSISTENT_ROOT
    expert.run_bootloader_install_or_update(ow.host, ow)
    assert calls[-1].get('route') == 'openwrt', calls[-1]

    stock = ds.DeviceState(host='192.168.1.1', probe_status=ds.PROBE_COMPLETE)
    stock.current_system = 'NOKIA_STOCK'
    stock.current_layout = 'NOKIA_STOCK'
    expert.run_bootloader_install_or_update(stock.host, stock)
    assert calls[-1].get('route') == 'stock', calls[-1]

    rec = ds.DeviceState(host='192.168.1.1', probe_status=ds.PROBE_COMPLETE)
    rec.current_system = 'RECOVERY'
    rec.current_layout = 'OPENWRT_UBI'
    rec.bootloader = 'URSUSBOOT'
    expert.run_bootloader_install_or_update(rec.host, rec)
    assert calls[-1].get('route') == 'recovery', calls[-1]

    unknown = ds.DeviceState(host='192.168.1.1', probe_status=ds.PROBE_PARTIAL)
    unknown.current_system = 'UNKNOWN'
    try:
        expert.run_bootloader_install_or_update(unknown.host, unknown)
    except RuntimeError as exc:
        assert 'stock Web/Telnet' in str(exc), str(exc)
    else:
        raise AssertionError('UNKNOWN environment must fail closed')
finally:
    expert.ursusboot_install.run_install = orig_install
    expert.update_bootloader_network = orig_update

expert_src = (ROOT / 'data/expert.py').read_text(encoding='utf-8')
installer_src = (ROOT / 'data/ursusboot_install.py').read_text(encoding='utf-8')
assert '_interactive_diagnostic_state(ds.probe_device_state(host))' in expert_src
assert 'route="openwrt"' in expert_src
assert 'route="stock"' in expert_src
assert 'if route == "openwrt":' in installer_src
assert 'An open TCP/23 is never evidence of Nokia STOCK' in installer_src
run_block=installer_src[installer_src.index('def run_install('):installer_src.index('def _materialize_mtd0_backup')]
assert '_tcp_open(host, 23)' not in run_block
one_key_src = (ROOT / 'data/one_key.py').read_text(encoding='utf-8')
assert 'route="openwrt"' in one_key_src
assert 'route="stock"' in one_key_src

print('ROUTE1_OPENWRT_STOCK_DISAMBIGUATION_QA=PASS')

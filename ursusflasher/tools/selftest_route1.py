#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'data'))

import device_state as ds
import expert
import one_key

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

# A positive Nokia vendor fingerprint must enter the authenticated read-only
# stock probe.  A generic HTTP page must remain ambiguous.
orig_tcp = ds._tcp_open
orig_ursus = ds._probe_ursus
orig_stock = ds._probe_stock_web
orig_http_identity = one_key.probe_http_identity
try:
    ds._tcp_open = lambda host, port, timeout=0.65: port == 80
    ds._probe_ursus = lambda host, state: False

    stock_calls = []
    def fake_stock(host, state):
        stock_calls.append(host)
        state.current_system = 'NOKIA_STOCK'
        state.current_layout = 'NOKIA_STOCK'
        state.model = 'Nokia XG-040G-MD'
        state.soc = 'Airoha AN7581'
        return True
    ds._probe_stock_web = fake_stock

    one_key.probe_http_identity = lambda host: 'nokia_stock'
    detected = ds.probe_device_state('192.168.1.1')
    assert detected.current_system == 'NOKIA_STOCK', detected
    assert stock_calls == ['192.168.1.1'], stock_calls

    stock_calls.clear()
    one_key.probe_http_identity = lambda host: 'http'
    ambiguous = ds.probe_device_state('192.168.1.1')
    assert ambiguous.current_system == 'UNKNOWN', ambiguous
    assert not stock_calls, stock_calls
finally:
    ds._tcp_open = orig_tcp
    ds._probe_ursus = orig_ursus
    ds._probe_stock_web = orig_stock
    one_key.probe_http_identity = orig_http_identity

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

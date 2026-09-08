#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
if (HERE.parents[1] / 'data').is_dir():
    ROOT = HERE.parents[1]
    SRC = ROOT / 'data'
else:
    ROOT = HERE.parents[2]
    SRC = ROOT / 'ursusflasher' / 'src'
sys.path.insert(0, str(SRC))

import ursus_web_client as uw  # noqa: E402
import one_key  # noqa: E402


def test_diagcap2_bundle() -> None:
    real_root, real_status, real_text, real_console, real_log = uw.DIAG_ROOT, uw.status, uw._text, uw.console, uw._session_log
    captured = []
    try:
        with tempfile.TemporaryDirectory() as td:
            uw.DIAG_ROOT = Path(td)
            def fake_status(host='192.168.1.1'):
                return {
                    'product':'UrsusBoot','version':'0.1.0-alpha5-UBIUX1-TEST58',
                    'operation_stage':'COMPLETE','operation_complete':True,
                    'operation_transaction_state':'COMPLETION_PROVEN',
                    'operation_error_code':'NONE','operation_failed_at_stage':'NONE',
                    'operation_last_success_stage':'VERIFY_BL2',
                }
            uw.status = fake_status
            uw._text = lambda host, path, timeout=10: f'device-log {path}\n'
            uw.console = lambda host, command, timeout=20: f'{command}: OK\n'
            uw._session_log = captured.append
            bundle = uw.begin_diagnostics('192.0.2.1', 'selftest', status_snapshot=fake_status())
            assert bundle is not None
            uw.finish_diagnostics(bundle, '192.0.2.1', 'selftest', 'SUCCESS', status_snapshot=fake_status())
            expected = {'status-before.json','status-after.json','operation-log-before.txt','operation-log.txt','web-log.txt','console.txt','operation.json'}
            assert expected <= {p.name for p in bundle.iterdir()}
            op = __import__('json').loads((bundle/'operation.json').read_text(encoding='utf-8'))
            assert op['result']=='SUCCESS'
            assert op['transaction_state']=='COMPLETION_PROVEN'
            joined='\n'.join(captured)
            for marker in ('[URSUS_STATUS_BEFORE]','[URSUS_STATUS_AFTER]','[URSUS_OPERATION_LOG]','[URSUS_CONSOLE_SNAPSHOT]','[DIAGCAP2_END]'):
                assert marker in joined, marker
    finally:
        uw.DIAG_ROOT, uw.status, uw._text, uw.console, uw._session_log = real_root, real_status, real_text, real_console, real_log


def test_rebootwait1_source_contract() -> None:
    src=(SRC/'one_key.py').read_text(encoding='utf-8')
    install=(SRC/'ursusboot_install.py').read_text(encoding='utf-8')
    assert 'wait_ursus(RECOVERY_HOST, 90)' in src
    assert 'remain = max(0, int(deadline - time.time()))' in src
    assert 'DEFERRED_TO_ONECLICK' in install
    assert 'old 180 s inner wait + 10 s outer wait' in install


def test_builddate1_contract() -> None:
    if (ROOT/'ursusboot/scripts/build_alpha5_test58.sh').is_file():
        b=(ROOT/'ursusboot/scripts/build_alpha5_test58.sh').read_text(encoding='utf-8')
        assert 'RELEASE_EPOCH=1788860280' in b
        assert 'TEST58' in b
        patch=(ROOT/'ursusboot/patches/150-test58-buildid.patch').read_text(encoding='utf-8')
        assert 'UrsusBoot-0.1.0-alpha5-UBIUX1-TEST58' in patch


def main() -> int:
    test_diagcap2_bundle()
    test_rebootwait1_source_contract()
    test_builddate1_contract()
    print('TEST58_SELFTEST=PASS')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

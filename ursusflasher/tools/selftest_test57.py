#!/usr/bin/env python3
from __future__ import annotations

import builtins
import importlib
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
if (HERE.parents[1] / 'data').is_dir():
    ROOT = HERE.parents[1]
    SRC = ROOT / 'data'
    PATCH_ROOT = ROOT / 'data' / 'test57-source'
else:
    ROOT = HERE.parents[2]
    SRC = ROOT / 'ursusflasher' / 'src'
    PATCH_ROOT = ROOT
sys.path.insert(0, str(SRC))

import ursus_web_client as uw  # noqa: E402
import expert  # noqa: E402
import ursusboot_update  # noqa: E402


def test_upload_retry() -> None:
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / 'x.fip'
        f.write_bytes(b'A' * (uw.CHUNK + 37))
        state = {'received': 0, 'calls': 0, 'gen': None, 'total': f.stat().st_size}
        real_json, real_status = uw._json, uw.status
        try:
            def fake_json(host, method, path, **kw):
                headers = kw.get('headers') or {}
                if path.endswith('-begin'):
                    state['gen'] = headers['X-Ursus-Generation']
                    state['received'] = 0
                    return {'result': 'UPLOAD_READY', 'generation': state['gen'], 'declared_size': state['total'], 'received': 0}
                state['calls'] += 1
                off = int(headers['X-Ursus-Offset'])
                body = kw.get('body') or b''
                # First chunk: one reset before server commit.
                if off == 0 and state['calls'] == 1:
                    raise ConnectionResetError(10054, 'test reset before commit')
                # Last chunk: server commits but ACK is lost.
                if off == uw.CHUNK:
                    state['received'] = off + len(body)
                    raise ConnectionResetError(10054, 'test reset after commit')
                state['received'] = off + len(body)
                return {'result': 'CHUNK_OK', 'generation': state['gen'], 'declared_size': state['total'], 'received': state['received']}

            def fake_status(host='192.168.1.1'):
                return {
                    'product': 'UrsusBoot',
                    'ursus_fip_generation': state['gen'],
                    'ursus_fip_upload_received': state['received'],
                    'ursus_fip_upload_total': state['total'],
                    'ursus_fip_valid': state['received'] == state['total'],
                }

            uw._json = fake_json
            uw.status = fake_status
            result = uw.upload('192.0.2.1', f, 'fip', progress=False)
            assert result['result'] == 'VALID', result
            assert result['received'] == state['total'], result
        finally:
            uw._json, uw.status = real_json, real_status


def test_no_automatic_tftp_fallback() -> None:
    real_web, real_tftp = ursusboot_update.web_fip_update, ursusboot_update.tftp_update_automated
    called = {'tftp': False}
    try:
        def fail_web():
            raise RuntimeError('synthetic web failure')
        def tftp():
            called['tftp'] = True
        ursusboot_update.web_fip_update = fail_web
        ursusboot_update.tftp_update_automated = tftp
        try:
            expert.update_bootloader_network()
        except RuntimeError as exc:
            assert 'synthetic' in str(exc)
        else:
            raise AssertionError('web exception must propagate')
        assert not called['tftp'], 'TFTP fallback was launched automatically'
    finally:
        ursusboot_update.web_fip_update, ursusboot_update.tftp_update_automated = real_web, real_tftp


def test_post_success_ui_is_nonfatal() -> None:
    real_require = ursusboot_update.require_fip_payload
    real_input = builtins.input
    real_update = ursusboot_update.uw.update_bootloader
    real_label = ursusboot_update.terms.layout_label
    try:
        ursusboot_update.require_fip_payload = lambda: None
        builtins.input = lambda prompt='': ''
        ursusboot_update.uw.update_bootloader = lambda host, payload, confirm=True: {'current_layout': 'OPENWRT_UBI', 'bootloader_update_layout': 'UBI'}
        ursusboot_update.terms.layout_label = lambda value: (_ for _ in ()).throw(KeyError(value))
        ursusboot_update.web_fip_update()  # must not raise after proven success
    finally:
        ursusboot_update.require_fip_payload = real_require
        builtins.input = real_input
        ursusboot_update.uw.update_bootloader = real_update
        ursusboot_update.terms.layout_label = real_label


def test_reset_route_and_api_patch() -> None:
    patch_path = ROOT / 'ursusboot' / 'patches' / '140-test57-diagcap-resetnet1.patch'
    if not patch_path.is_file():
        return
    patch = patch_path.read_text(encoding='utf-8')
    assert 'URSUS_REQ_MATCH' in patch
    assert 'POST /api/reset-openwrt-settings' in patch
    assert 'POST /api/reset-openwrt-settings ", 34' not in patch
    assert 'GET /api/operation-log' in patch
    assert 'operation_error_code' in patch
    assert 'flash_page_size' in patch and 'flash_oob_size' in patch and 'flash_erase_size' in patch


def main() -> int:
    test_upload_retry()
    test_no_automatic_tftp_fallback()
    test_post_success_ui_is_nonfatal()
    test_reset_route_and_api_patch()
    print('TEST57_SELFTEST=PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
_REPO_ROOT = HERE.parent.parent
REPO_MODE = (_REPO_ROOT / 'payloads').is_dir() and (_REPO_ROOT / 'config').is_dir()
ROOT = _REPO_ROOT if REPO_MODE else HERE.parent
WORK = ROOT / 'work' / 'vanilla-initramfs-item4-test'

sys.path.insert(0, str(HERE))
import console_ui as ui  # noqa: E402
import proven_backend as pb  # noqa: E402
import stock_ab_transition as sat  # noqa: E402
import stock_fit_initramfs as sfi  # noqa: E402
import ursusboot_install as ubi  # noqa: E402

@dataclass(frozen=True)
class Policy:
    profile: str
    family: str
    model: str
    payload_dir: str
    payload_name: str
    slot_size: int = 0x02880000
    flag_size: int = 0x00040000
    erase_size: int = 0x00020000
    flag_mtd: int = 8
    flagback_mtd: int = 9
    master_mtd: int = 14
    slave_mtd: int = 15

POLICIES = {
    'xg040-md': Policy('xg040-md', 'md', 'Nokia XG-040G-MD', 'md', 'openwrt-airoha-an7581-nokia_xg-040g-md-ursus-initramfs-test.itb'),
    'xg040-mf': Policy('xg040-mf', 'mf', 'Nokia XG-040G-MF', 'mf', 'openwrt-airoha-an7583-nokia_xg-040g-mf-ursus-initramfs-test.itb'),
}

def _payload_root(policy: Policy) -> Path:
    base = ROOT / 'payloads' / 'vanilla-initramfs-test' / policy.payload_dir
    if not REPO_MODE:
        base = ROOT / 'data' / 'payloads' / 'vanilla-initramfs-test' / policy.payload_dir
    return base

def _load_payload(policy: Policy) -> tuple[bytes, dict]:
    root = _payload_root(policy)
    image = root / policy.payload_name
    meta_path = root / 'PAYLOAD.json'
    if not image.is_file() or not meta_path.is_file():
        raise RuntimeError(f'Vanilla initramfs TEST payload is missing: {root}')
    data = image.read_bytes()
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    got = hashlib.sha256(data).hexdigest()
    if got != str(meta.get('sha256', '')).lower():
        raise RuntimeError(f'initramfs payload SHA256 mismatch: {got} != {meta.get("sha256")}')
    if meta.get('profile') != policy.profile or meta.get('family') != policy.family:
        raise RuntimeError('initramfs payload profile metadata mismatch')
    if meta.get('mode') != 'VANILLA_INITRAMFS_BOOT_ONLY_TEST':
        raise RuntimeError('payload is not the guarded boot-only test image')
    if meta.get('destructive_stage2_enabled') is not False:
        raise RuntimeError('refusing payload with destructive stage2 enabled in boot-only test backend')
    sfi.source_fit_contract(data)
    return data, meta

def _require_stock_geometry(telnet: pb.Telnet, policy: Policy) -> None:
    import re
    rc, text = telnet.command_clean('cat /proc/mtd', timeout=20)
    if rc:
        raise RuntimeError('cannot read /proc/mtd')
    rows = {name: (int(size, 16), int(erase, 16), int(idx)) for idx, size, erase, name in re.findall(r'mtd(\d+):\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+\"([^\"]+)\"', text)}
    expected = {
        'flag': (policy.flag_size, policy.erase_size, policy.flag_mtd),
        'flagback': (policy.flag_size, policy.erase_size, policy.flagback_mtd),
        'nsb_master': (policy.slot_size, policy.erase_size, policy.master_mtd),
        'nsb_slave': (policy.slot_size, policy.erase_size, policy.slave_mtd),
    }
    for name, want in expected.items():
        got = rows.get(name)
        if got != want:
            raise RuntimeError(f'stock MTD geometry mismatch for {name}: {got} != {want}')

def _policy(name: str) -> Policy:
    try:
        return POLICIES[name]
    except KeyError as exc:
        raise RuntimeError(f'unsupported test profile: {name}') from exc

def run(*, host: str = '192.168.1.1', profile: str, reboot: bool = True) -> int:
    policy = _policy(profile)
    ui.enable()
    installer_fit, payload_meta = _load_payload(policy)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    run_dir = WORK / f'{policy.family}-{stamp}'
    run_dir.mkdir(parents=True, exist_ok=True)
    access = telnet = None
    try:
        access, telnet = ubi.open_root_auto(host)
        reported = str(getattr(access, 'family', '') or '').strip().lower()
        if reported not in ('', 'unknown', policy.family):
            raise RuntimeError(f'board profile mismatch: selected {policy.profile}, stock reports {reported}')
        _require_stock_geometry(telnet, policy)
        access.family = policy.family
        writer = sat._mtd_writer_preflight(telnet)
        full_backup = run_dir / 'full-stock-backup'
        pb.backup_tftp(access, access.host, full_backup, expected_family=policy.family, allow_service_provisioning=True)
        backup_result = pb.verify_stock_restore_backup(full_backup)
        ui.status('READY', f'Complete stock backup verified: {full_backup}')
        flag, flag_sha, flag_path = sat._backup_partition_bytes(full_backup, policy.flag_mtd, 'flag', policy.flag_size)
        flagback, flagback_sha, flagback_path = sat._backup_partition_bytes(full_backup, policy.flagback_mtd, 'flagback', policy.flag_size)
        master, master_sha, master_path = sat._backup_partition_bytes(full_backup, policy.master_mtd, 'nsb_master', policy.slot_size)
        slave, slave_sha, slave_path = sat._backup_partition_bytes(full_backup, policy.slave_mtd, 'nsb_slave', policy.slot_size)
        fs = sat.parse_flag(flag, policy)
        fbs = sat.parse_flag(flagback, policy)
        ui.status('INFO', f'Stock A/B state: flag={fs}; flagback={fbs}')
        slot_candidate, slot_meta = sfi.build_installer_slot(slave, installer_fit, slot_size=policy.slot_size)
        slot_path = run_dir / f'mtd{policy.slave_mtd}_nsb_slave_vanilla_initramfs_test.bin'
        slot_path.write_bytes(slot_candidate)
        flag_candidate, flag_meta = sat.build_activation_flag(flag, 1, policy)
        flag_path_out = run_dir / f'mtd{policy.flag_mtd}_flag_activate_slave.bin'
        flag_path_out.write_bytes(flag_candidate)
        transport, remote_slot, remote_flag = sat._select_and_preflight_transport(telnet, access, slot_path, flag_path_out)
        report = {
            'operation': f'{policy.profile}_vanilla_initramfs_boot_only_test', 'profile': policy.profile,
            'payload': payload_meta, 'slot': slot_meta, 'selector': flag_meta, 'flagback_observed': fbs,
            'backup': {'stock_family': backup_result.get('stock_family'), 'stock_variant': backup_result.get('stock_variant'),
                'full_directory': str(full_backup), 'flag_source': str(flag_path), 'flag_sha256': flag_sha,
                'flagback_source': str(flagback_path), 'flagback_sha256': flagback_sha,
                'nsb_master_source': str(master_path), 'nsb_master_sha256': master_sha,
                'nsb_slave_source': str(slave_path), 'nsb_slave_sha256': slave_sha},
            'writer': writer, 'transport': transport, 'destructive_stage2_enabled': False,
        }
        (run_dir / 'VANILLA_INITRAMFS_TEST_PLAN.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        ui.section('VANILLA INITRAMFS BOOT-ONLY TEST', style='amber2')
        ui.status('READY', f'{policy.model}: fresh OpenWrt snapshot initramfs verified')
        ui.status('READY', f'SLOT2 candidate SHA256 {slot_meta["candidate_sha256"]}')
        ui.status('READY', 'Full stock backup verified; SLOT1/master remains untouched')
        ui.status('READY', f'writer={writer}; transport={transport}; uploads SHA-verified')
        ui.status('INFO', 'Stage2 UBI/FIP/BL2 writes are physically disabled in this TEST image')
        ui.status('INFO', 'After boot: SSH root@192.168.1.1 (blank password); run: ursusstockslot status')
        ui.status('INFO', 'Rollback command: ursusstockslot master && sync && reboot -f')
        ans = ui.prompt(pb.tr('Preflight пройден. Записать TEST initramfs в SLOT2, проверить readback и загрузить его? [д/Н]: ', 'Preflight passed. Write TEST initramfs to SLOT2, verify readback and boot it? [y/N]: ')).strip().lower()
        if ans not in ('д', 'да', 'y', 'yes'):
            ui.status('STOP', pb.tr('Операция отменена; NAND не изменялась.', 'Operation cancelled; NAND was not modified.'))
            return 0
        sat._write_partition(telnet, remote_slot, 'nsb_slave', f'/dev/mtd{policy.slave_mtd}', policy.slot_size, writer, policy.erase_size, timeout=900)
        got = sat._remote_partition_sha(telnet, f'/dev/mtd{policy.slave_mtd}', timeout=600)
        if got != slot_meta['candidate_sha256']:
            raise RuntimeError(f'nsb_slave readback mismatch: {got} != {slot_meta["candidate_sha256"]}')
        ui.status('PASS', 'SLOT2 initramfs write/readback verified; SLOT1/master untouched')
        expected_flag_sha = hashlib.sha256(flag_candidate).hexdigest()
        sat._write_partition(telnet, remote_flag, 'flag', f'/dev/mtd{policy.flag_mtd}', policy.flag_size, writer, policy.erase_size, timeout=120)
        got_flag = sat._remote_partition_sha(telnet, f'/dev/mtd{policy.flag_mtd}', timeout=120)
        if got_flag != expected_flag_sha:
            raise RuntimeError(f'flag readback mismatch: {got_flag} != {expected_flag_sha}')
        ui.status('PASS', 'Stock selector active=1 readback verified; flagback untouched')
        if reboot:
            ui.status('ACTION', 'One approved transaction: rebooting immediately into SLOT2 initramfs; no second confirmation')
            try:
                telnet.send_line('sync; reboot')
            except Exception:
                pass
        else:
            ui.status('ACTION', 'Selector is armed for SLOT2; reboot is required')
        return 0
    finally:
        if telnet:
            try: telnet.close()
            except Exception: pass
        if access:
            try: access.close_web(announce=False)
            except Exception: pass

def run_expert(*, host: str, profile: str) -> int:
    return run(host=host, profile=profile, reboot=True)

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='UrsusFlasher Vanilla initramfs SLOT2 boot-only test')
    ap.add_argument('--host', default=os.environ.get('NOKIA_HOST', '192.168.1.1'))
    ap.add_argument('--profile', choices=tuple(POLICIES), required=True)
    ap.add_argument('--no-reboot', action='store_true')
    ns = ap.parse_args(argv)
    return run(host=ns.host, profile=ns.profile, reboot=not ns.no_reboot)

if __name__ == '__main__':
    raise SystemExit(main())

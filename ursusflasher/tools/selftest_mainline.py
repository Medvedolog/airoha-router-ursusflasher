#!/usr/bin/env python3
from __future__ import annotations
import ast, inspect, json, os, sys, hashlib
from pathlib import Path
D=Path(__file__).resolve().parents[1]
os.environ.setdefault('NOKIA_LANG','ru')
sys.path.insert(0,str(D/'data'))
import ursusboot_update as u
import ursusboot_install as bi
import one_key as ok
m=json.loads((D/'data/MANIFEST.json').read_text(encoding='utf-8')); meta=m['ursusboot']
assert m['version']=='0.2.52-md-alpha4-fudan1-stateui6-actionpreflight1-payloadrefresh1-rootfsmax2'
assert meta['version']=='0.1.0-alpha3'  # emergency lineage remains alpha3
assert bi.TARGET_URSUS=='0.1.0-alpha4-FUDAN1'
assert bi.PAYLOAD.name=='ursusboot-md-0.1.0-alpha4-FUDAN1-update.fip'
assert bi.ALPHA3_REFERENCE_PAYLOAD.name=='ursusboot-md-0.1.0-alpha3-update.fip'
assert meta['fip_sha256']=='597071e178470bfda23aab9738ad7ddb0b25e9b21ef336fd3eceb39c39f983ce'
assert meta['preloader_sha256']=='6c3b2339d036340396730a13adfe35c0d2a4dddedeffb6f9965a24e0c7908808'
assert meta['ram_installer_fip_sha256']=='dc08ed0be1b1d68f6bc247ae45293e6ab0ca9df7695541b664e4060a145228c8'
assert meta['bl2_image_sha256']=='6f9c928bad500de0339bbfdfa354c17a7ac044f96c913f3a01301971d6cd659d'
v=u.validate_emergency_fip_host(); assert v['fip_sha256']==meta['fip_sha256']
assert u.RAM_INSTALLER.name=='ursusboot-md-0.1.0-alpha3-ram-installer.fip'
assert u.PRELOADER.name=='openwrt-airoha-an7581-nokia_xg-040g-md-ubi-preloader.bin'
assert u.BL2_IMAGE.name=='ursusboot-md-0.1.0-alpha3-bl2.bin'
assert hashlib.sha256(u.BL2_IMAGE.read_bytes()).hexdigest()==meta['bl2_image_sha256']

# Destructive recovery reuses targets established by the read-only UBI/BL2 check.
trans=inspect.getsource(u.emergency_ursusboot_transaction)
for required in ('ubi create fip 0x100000 static 4','ubi write 0x{LOADADDR:x} fip','cmp.b 0x{LOADADDR:x} 0x{READBACK_ADDR:x}','mtd erase {bl2_target}','mtd write {bl2_target}','mtd read {bl2_target}','cmp.b 0x{BL2_ADDR:x} 0x{READBACK_ADDR:x}'):
    assert required in trans, required
assert 'ubi part {ubi_target}' in trans
for forbidden in ('ursusupdate write','fip.new->atomic','HF6',"f'hash sha256", "'ubi part ubi'"):
    assert forbidden not in trans, forbidden

# Gate policy: ordinary FIP update does not depend on emergency assets.
rf=inspect.getsource(u.require_fip_payload)
assert 'PRELOADER' not in rf and 'RAM_INSTALLER' not in rf and 'BL2_IMAGE' not in rf
re=inspect.getsource(u.require_emergency_payloads)
assert 'require_ram_bootstrap_payloads' in re and 'EMERGENCY_PAYLOAD' in re and 'BL2_IMAGE' in re and 'require_fip_payload' not in re
rr=inspect.getsource(u.require_ram_bootstrap_payloads)
assert 'require_fip_payload' not in rr and 'PRELOADER' in rr and 'RAM_INSTALLER' in rr and 'BL2_IMAGE' not in rr
assert not hasattr(u, 'require_payloads')

# No duplicate device-side check before write in exposed TFTP path or UART loader.
assert 'ursusupdate check' not in inspect.getsource(u.tftp_update_automated)
assert 'ursusupdate check' not in inspect.getsource(u.tftp_server_manual)
assert 'ursusupdate check' not in inspect.getsource(u.load_fip_xmodem)

# Item 10 is diagnostic-only and never calls a require_* gate.
assert 'require_' not in inspect.getsource(u.show_info)

# Read-only UBI/BL2 policy: diagnostics and destructive recovery are separate actions.
for_src=inspect.getsource(u.capture_bootchain_forensics)
prep_src=inspect.getsource(u._prepare_readonly_mtd_view)
for required in ('ubi info l','crc32','RAW_UBI_INFO_LAYOUT','RAW_FIP_CONTENT_CHECKS','FIP_CONTENT_CHECKS','persistent_writes=0','RAW_MTD_LIST_BEFORE_TEMP_ALIASES'):
    assert required in for_src, required
for required in ('mtd list','mtdparts delall','setenv mtdids','setenv mtdparts','ursus-diag-bl2','ursus-diag-ubi'):
    assert required in prep_src, required
for forbidden in ('ubi remove ','ubi create ','ubi write ','ubi rename','mtd erase ','mtd write '):
    assert forbidden not in for_src and forbidden not in prep_src, forbidden
assert "_uboot_command_no_rc(sp, log, 'saveenv'" not in prep_src
assert "_uboot_command_result(sp, log, 'saveenv'" not in prep_src
assert "'ubi part ubi'" not in for_src and "'mtd read bl2" not in for_src
assert 'ubi read 0x{READBACK_ADDR:x} {name} 0x{FIP_READ_SIZE:x}' in for_src
assert u.FIP_READ_SIZE == 503808
assert '0.1.0-alpha3' in u.FIP_CRC32_REFERENCES['82263464']
assert 'alpha4 LZMAFIX1' in u.FIP_CRC32_REFERENCES['b1b313a5']
assert 'alpha4/HF6' in u.FIP_CRC32_REFERENCES['66b31112']
flow_src=inspect.getsource(u._uart_bootrom_flow)
assert 'if not recover:' in flow_src
assert flow_src.index('capture_bootchain_forensics') < flow_src.index('load_fip_xmodem_emergency')
assert flow_src.index('capture_bootchain_forensics') < flow_src.index('load_bl2_xmodem_emergency')
assert 'recover=False' in inspect.getsource(u.uart_bootrom_forensics)
assert 'recover=True' in inspect.getsource(u.uart_bootrom_recover)
sample=(
    "Volume information dump:\n"
    "    vol_id          4\n"
    "    reserved_pebs   9\n"
    "    vol_type        4\n"
    "    used_bytes      503808\n"
    "    name            fip\n"
    "Volume information dump:\n"
    "    vol_id          7\n"
    "    reserved_pebs   9\n"
    "    vol_type        3\n"
    "    name            fip.old\n"
)
parsed=u._parse_ubi_layout(sample)
assert parsed[0]['id']==4 and parsed[0]['name']=='fip' and parsed[0]['type']=='static'
assert parsed[1]['id']==7 and parsed[1]['name']=='fip.old' and parsed[1]['type']=='dynamic'
assert u.BL2_CRC32=='9f7bf316'
sample_mtd=(
    'List of MTD devices:\n'
    '* spi-nand0\n'
    '  - 0x000000000000-0x000010000000 : \"spi-nand0\"\n'
    '          - 0x000000000000-0x000000020000 : \"bl2\"\n'
    '          - 0x000000020000-0x000010000000 : \"ubi\"\n'
)
mi=u._parse_mtd_list(sample_mtd)
assert mi['master']=='spi-nand0' and 'bl2' in mi['names'] and 'ubi' in mi['names']

# STOCK mtd0 install/restore preflight is target-scoped, not full-layout scoped.
pf_node=ast.parse(inspect.getsource(bi.mtd0_write_preflight))
constants={n.value for n in ast.walk(pf_node) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
assert not any(x in constants for x in ('mtd14','mtd15','mtd16','nsb_master','nsb_slave','all_flash'))
assert 'mtd0_write_preflight' not in inspect.getsource(bi.run_stock_access_check)
assert '/proc/mtd' not in inspect.getsource(bi.run_stock_access_check)
assert 'run_stock_access_check' in inspect.getsource(bi.run_preflight_only)
ri=inspect.getsource(bi.run_install)
assert ri.count('mtd0_write_preflight(')==1
assert 'revalidate_mtd0_target' in ri
assert 'preflight_after_full_backup' not in ri
assert 'mtd0_write_preflight' in inspect.getsource(bi.run_restore)

# ONE-KEY has no eager all-payload/all-firmware gate before state detection.
main_src=inspect.getsource(ok.main)
for forbidden in ('verify_firmware_bundle()', 'require_payloads()', 'ursusboot_install.require_payload()'):
    assert forbidden not in main_src, forbidden
assert 'require_bundle_role' in inspect.getsource(ok.install_or_update_openwrt)
assert 'require_fip_payload' in inspect.getsource(ok.ensure_target_ursus)

expert=(D/'data/expert.py').read_text(encoding='utf-8')
assert 'device_state as ds' in expert
assert 'full_backup_readonly' in expert
assert 'capability_report' in expert
assert 'restore_mtd0' not in expert
one=(D/'data/one_key.py').read_text(encoding='utf-8'); assert 'TARGET_URSUS = "0.1.0-alpha4-FUDAN1"' in one
assert 'PRODUCTION_PAYLOAD' in inspect.getsource(ok.ensure_target_ursus)
assert 'physical_reboot_to_recovery' not in one
assert 'примерно через 1 секунду' in one and '5-10 секунд' in one
assert 'debounce около 0,75 с' not in one
terms=json.loads((D/'data/UI_TERMS.json').read_text(encoding='utf-8'))
assert 'STATEUI6' in terms['contract']
expected={
 'install_openwrt':1,'install_or_repair_bootloader':2,'custom_openwrt':3,'update_bootloader':4,
 'recover_bootloader':5,'restore_nokia':6,'full_backup':7,'validate_backup':8,'disaster_kit':9,
 'capabilities':10,'flash_diagnostics':11,'package_files':12,
}
assert {k:int(v['number']) for k,v in terms['expert_actions'].items()}==expected
assert terms['expert_actions']['install_or_repair_bootloader']['ru']=='Установить или переустановить загрузчик'
assert terms['expert_actions']['restore_nokia']['ru']=='Восстановить заводскую прошивку Nokia'
assert '[ИНФО]' in one and 'layout_label' in one
web=(D/'data/ursus_web_client.py').read_text(encoding='utf-8')
for leak in ('Native UBI FIT update selected','One-way Nokia STOCK -> OPENWRT_UBI migration selected','OpenWrt stock-layout install/update selected'):
    assert leak not in web, leak
assert 'terms.layout_label' in web and 'terms.tr' in web
assert '[ПЕРЕДАЧА]' in web and '[WEB_STATUS_RAW]' in web
assert "print(f'[URSUS] {stage} {pct}% {detail}')" not in web
assert 'URSUS_UPDATE_COMMIT_OK. Перезагрузка' not in (D/'data/ursusboot_update.py').read_text(encoding='utf-8')
ui=(D/'data/console_ui.py').read_text(encoding='utf-8')
for row in (r'[\]_____[/]',r'|         |',r'|  ^   ^  |',r'|    Y    |',r'|  \___/  |',r" '-------' "):
    assert row in ui and len(row)==11
assert not (D/'data/payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-ram-installer.fip').exists()
# 0.2.31 single-variable fip.old experiment policy.
exp=inspect.getsource(u.fipold_alpha3_experiment_transaction)
assert 'ubi write 0x{LOADADDR:x} fip.old 0x{size:x}' in exp
assert 'ubi read 0x{READBACK_ADDR:x} fip.old 0x{size:x}' in exp
assert 'cmp.b 0x{LOADADDR:x} 0x{READBACK_ADDR:x} 0x{size:x}' in exp
for forbidden in ('ubi remove ', 'ubi create ', 'ubi rename', 'mtd erase ', 'mtd write '):
    assert forbidden not in exp, forbidden
assert "_uboot_command_no_rc(sp, log, 'saveenv'" not in exp and "_uboot_command_result(sp, log, 'saveenv'" not in exp
assert 'mtd read {bl2_target}' in exp and 'bl2_crc_after' in exp
assert 'fip_crc_after' in exp and 'ubi info l' in exp
assert 'WRITE FIP.OLD' in exp
gate=inspect.getsource(u._require_fipold_experiment_baseline)
for required in ('fip.old','fip','FIP_OLD_EXPERIMENT_OLD_CRC32','FIP_OLD_EXPERIMENT_NEW_CRC32','FIP_OLD_EXPERIMENT_EXPECTED_BL2_CRC32'):
    assert required in gate
reqexp=inspect.getsource(u.require_fipold_experiment_payloads)
assert 'require_ram_bootstrap_payloads' in reqexp and 'EMERGENCY_PAYLOAD' in reqexp and 'require_fip_payload' not in reqexp and 'BL2_IMAGE' not in reqexp
assert 'uart_bootrom_bl2_experiment' not in expert
assert u.FIP_OLD_EXPERIMENT_EXPECTED_BL2_CRC32=='09fb6b36'
assert u.FIP_OLD_EXPERIMENT_OLD_CRC32=='66b31112'
assert u.FIP_OLD_EXPERIMENT_NEW_CRC32=='82263464'
observed_view={
    'ubi_target':'ursus-diag-ubi',
    'volumes':[
        {'id':6,'name':'fip.old','type':'static','used_bytes':503808},
        {'id':7,'name':'fip','type':'static','used_bytes':503808},
    ],
    'fip_checks':[
        {'name':'fip.old','crc32':'66b31112'},
        {'name':'fip','crc32':'82263464'},
    ],
    'bl2_crc32':'09fb6b36',
}
ob=u._require_fipold_experiment_baseline(observed_view)
assert ob['fip_old_id']==6 and ob['fip_id']==7 and ob['bl2_crc32_before']=='09fb6b36'

# 0.2.32 single-variable BL2 experiment policy.
bl2exp=inspect.getsource(u.bl2_alpha3_experiment_transaction)
for required in ('mtd erase {bl2_target}','mtd write {bl2_target}','mtd read {bl2_target}','cmp.b 0x{BL2_ADDR:x} 0x{READBACK_ADDR:x}','WRITE BL2','ubi part {ubi_target}','fip.old','fip'):
    assert required in bl2exp, required
for forbidden in ('ubi write ', 'ubi remove ', 'ubi create ', 'ubi rename'):
    assert forbidden not in bl2exp, forbidden
assert "_uboot_command_no_rc(sp, log, 'saveenv'" not in bl2exp and "_uboot_command_result(sp, log, 'saveenv'" not in bl2exp
assert 'fip_old_crc_after' in bl2exp and 'fip_crc_after' in bl2exp and 'bl2_crc_after' in bl2exp
bl2gate=inspect.getsource(u._require_bl2_experiment_baseline)
for required in ('BL2_EXPERIMENT_EXPECTED_FIP_OLD_ID','BL2_EXPERIMENT_EXPECTED_FIP_ID','BL2_EXPERIMENT_EXPECTED_FIP_CRC32','BL2_EXPERIMENT_EXPECTED_OLD_CRC32'):
    assert required in bl2gate
reqbl2=inspect.getsource(u.require_bl2_experiment_payloads)
assert 'require_ram_bootstrap_payloads' in reqbl2 and 'BL2_IMAGE' in reqbl2 and 'require_fip_payload' not in reqbl2
bl2flow=inspect.getsource(u._uart_bootrom_bl2_experiment_flow)
assert bl2flow.index('capture_bootchain_forensics') < bl2flow.index('load_bl2_xmodem_emergency') < bl2flow.index('bl2_alpha3_experiment_transaction')
post_fipold_view={
    'ubi_target':'ursus-diag-ubi',
    'bl2_target':'ursus-diag-bl2',
    'volumes':[
        {'id':6,'name':'fip.old','type':'static','used_bytes':503808},
        {'id':7,'name':'fip','type':'static','used_bytes':503808},
    ],
    'fip_checks':[
        {'name':'fip.old','crc32':'82263464'},
        {'name':'fip','crc32':'82263464'},
    ],
    'bl2_crc32':'09fb6b36',
}
bb=u._require_bl2_experiment_baseline(post_fipold_view)
assert bb['fip_old_id']==6 and bb['fip_id']==7 and bb['bl2_crc32_before']=='09fb6b36'
assert u.BL2_CRC32=='9f7bf316'

assert u.PRODUCTION_PAYLOAD.name=='ursusboot-md-0.1.0-alpha4-FUDAN1-update.fip'
assert hashlib.sha256(u.PRODUCTION_PAYLOAD.read_bytes()).hexdigest()==meta['alpha4_fudan1_candidate']['fip_sha256']
assert u.EMERGENCY_PAYLOAD.name=='ursusboot-md-0.1.0-alpha3-update.fip'
expert_src=(D/'data/expert.py').read_text(encoding='utf-8')
assert 'Нажмите Enter, чтобы вернуться в меню EXPERT' in expert_src
assert not (D/'START.cmd').exists() and not (D/'START.sh').exists()
assert (D/'START_ONECLICK.cmd').exists() and (D/'START_EXPERT.cmd').exists()
print('URSUSFLASHER_0.2.52_FUDAN1_STATEUI6_ACTIONPREFLIGHT1_PAYLOADREFRESH1_ROOTFSMAX2_MAINLINE_QA=PASS')
print('USER_FLOW_GATE_POLICY_QA=PASS')

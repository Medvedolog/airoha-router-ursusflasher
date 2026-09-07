#!/usr/bin/env python3
from __future__ import annotations
import os,sys
from pathlib import Path
D=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(D/'data'))
os.environ['NOKIA_LANG']='ru'
import device_state as ds
import ui_terms as terms
assert ds.classify_openwrt_execution_environment('rootfs|rootfs|rw')==ds.EXEC_RAM_ROOT
assert ds.classify_openwrt_execution_environment('tmpfs|tmpfs|rw')==ds.EXEC_RAM_ROOT
assert ds.classify_openwrt_execution_environment('rootfs|rootfs|rw','/dev/ubiblock0_4|squashfs|ro','')==ds.EXEC_RAM_ROOT
assert ds.classify_openwrt_execution_environment('overlayfs:/overlay|overlay|rw','/dev/ubiblock0_4|squashfs|ro','/dev/ubi0_5|ubifs|rw')==ds.EXEC_PERSISTENT_ROOT
assert ds.classify_openwrt_execution_environment('/dev/root|squashfs|ro')==ds.EXEC_PERSISTENT_ROOT
assert ds.classify_openwrt_execution_environment('overlayfs:/overlay|overlay|rw','','tmpfs|tmpfs|rw')==ds.EXEC_UNKNOWN
ram=ds.DeviceState(probe_status=ds.PROBE_COMPLETE,current_system='OPENWRT_UBI',current_layout='OPENWRT_UBI',execution_environment=ds.EXEC_RAM_ROOT,bootloader='URSUSBOOT')
persist=ds.DeviceState(probe_status=ds.PROBE_COMPLETE,current_system='OPENWRT_UBI',current_layout='OPENWRT_UBI',execution_environment=ds.EXEC_PERSISTENT_ROOT,bootloader='URSUSBOOT')
stock=ds.DeviceState(probe_status=ds.PROBE_COMPLETE,current_system='NOKIA_STOCK',current_layout='NOKIA_STOCK',bootloader='TCBOOT')
assert ds.action_applicability(ram)[2].resolved_backend=='SSH_RAM_OPENWRT'
assert ds.action_applicability(persist)[2].resolved_backend=='SSH_PERSISTENT_OPENWRT'
assert ds.action_applicability(stock)[2].resolved_backend=='TELNET_NOKIA_STOCK'
assert terms.human('SSH_RAM_OPENWRT','method')=='Через SSH из OpenWrt, запущенной из оперативной памяти'
assert terms.human('PERSISTENT_ROOT','execution_environment')=='установленная OpenWrt во flash-памяти'
unknown=ds.DeviceState(probe_status=ds.PROBE_COMPLETE,current_system='OPENWRT_UBI',current_layout='OPENWRT_UBI',execution_environment=ds.EXEC_UNKNOWN,bootloader='URSUSBOOT')
ds.degrade_probe_status(unknown,ds.PROBE_PARTIAL,'EXECUTION_ENVIRONMENT_UNCONFIRMED')
assert ds.action_applicability(unknown)[2].enabled
assert ds.action_applicability(unknown)[2].resolved_backend=='AUTO_BOOTLOADER_INSTALL_REPAIR'
assert any('Среда выполнения:' in x and 'оперативной памяти' in x for x in ds.state_summary_lines(ram))
assert not any('Среда выполнения:' in x for x in ds.state_summary_lines(stock))
print('STATEUI4_EXECUTION_ENVIRONMENT_QA=PASS')

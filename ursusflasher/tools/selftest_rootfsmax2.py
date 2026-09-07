#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'data'))
import ursus_web_client as uw

REAL_UBI_INFO='''UBI: MTD device name:            "ursus-ubi-full"\nUBI: MTD device size:            255 MiB\nUBI: physical eraseblock size:   131072 bytes (128 KiB)\nUBI: logical eraseblock size:    126976 bytes\nUBI: number of good PEBs:        2047\nUBI: number of bad PEBs:         0\nUBI: smallest flash I/O unit:    2048\nUBI: VID header offset:          2048 (aligned 2048)\nUBI: data offset:                4096\nUBI: max. allowed volumes:       128\nUBI: wear-leveling threshold:    4096\nUBI: number of internal volumes: 1\nUBI: number of user volumes:     7\nUBI: available PEBs:             205\nUBI: total number of reserved PEBs: 1842\nUBI: number of PEBs reserved for bad PEB handling: 40\nUBI: max/mean erase counter: 2/1\n[return=0]\n'''

calls=[]
def fake_console(host:str, command:str, *, timeout:float=360.0)->str:
    calls.append(command)
    if 'URSUS_ROOTFSMAX_ATTACH_OK' in command:
        return 'UBI: attaching mtd\nURSUS_ROOTFSMAX_ATTACH_OK\n'
    if command=='ubi info':
        return REAL_UBI_INFO
    if 'URSUS_ROOTFSMAX_PRECHECK_OK' in command:
        return 'Volume rootfs_data found!\nURSUS_ROOTFSMAX_PRECHECK_OK\n'
    if 'URSUS_ROOTFSMAX_REMOVE_OK' in command:
        return 'Remove UBI volume rootfs_data (id 6)\nURSUS_ROOTFSMAX_REMOVE_OK\n'
    if 'URSUS_ROOTFSMAX_CREATE_OK' in command:
        assert 'ubi create rootfs_data 0xe3e6000 dynamic 6' in command, command
        return 'Creating dynamic volume rootfs_data of size 238968832\nURSUS_ROOTFSMAX_CREATE_OK\n'
    if 'URSUS_ROOTFSMAX_VOLUME_OK' in command:
        return ('Volume rootfs_data found!\nURSUS_ROOTFSMAX_VOLUME_OK\n' +
                REAL_UBI_INFO.replace('available PEBs:             205','available PEBs:             16'))
    if command=='ubi detach':
        return 'Detach UBI device\n'
    raise AssertionError(command)
orig=uw.console; uw.console=fake_console
try:
    r=uw.maximize_fresh_migration_rootfs_data('192.168.1.1',{'operation_complete':True})
finally:
    uw.console=orig
assert r=={'rootfs_data_lebs':1882,'rootfs_data_bytes':238968832,'free_pebs':16,'leb_size':126976},r
assert any('ubi remove rootfs_data' in c for c in calls)
assert any('0xe3e6000' in c for c in calls)
# Legacy spelling must remain accepted too.
import re
src=(ROOT/'data/ursus_web_client.py').read_text()
assert 'logical\\s+eraseblock' in src
# Fresh-migration guard must remain fail-closed.
try:
    uw.maximize_fresh_migration_rootfs_data('192.168.1.1',{'operation_complete':False})
except uw.UrsusWebError:
    pass
else:
    raise AssertionError('fresh-migration guard missing')
print('ROOTFSMAX2_REAL_HW_UBI_INFO_QA=PASS target_lebs=1882 free_pebs=16 target_bytes=238968832')

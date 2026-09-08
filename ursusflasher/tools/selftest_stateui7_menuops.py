#!/usr/bin/env python3
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'data'))
import device_state as ds

# Installed OpenWrt: custom image is available through native sysupgrade.
s=ds.DeviceState(host='192.168.1.1', probe_status=ds.PROBE_COMPLETE)
s.current_system='OPENWRT_UBI'; s.current_layout='OPENWRT_UBI'; s.execution_environment=ds.EXEC_PERSISTENT_ROOT
s.access={'http':True,'ssh':True,'root':'YES'}
app=ds.action_applicability(s)
assert app[2].enabled and app[2].resolved_backend=='SSH_PERSISTENT_OPENWRT', app[2]
assert app[3].enabled and app[3].resolved_backend=='SSH_PERSISTENT_OPENWRT_SYSUPGRADE', app[3]
assert app[4].enabled and app[4].resolved_backend=='ALIAS_TO_ACTION_2', app[4]

# UrsusBoot Recovery: item 2 becomes self-update, item 3 becomes Recovery image install.
r=ds.DeviceState(host='192.168.1.1', probe_status=ds.PROBE_COMPLETE)
r.current_system='RECOVERY'; r.current_layout='OPENWRT_UBI'; r.bootloader='URSUSBOOT'
r.access={'http':True,'ssh':False,'root':'UNKNOWN'}
app=ds.action_applicability(r)
assert app[2].enabled and app[2].resolved_backend=='URSUSBOOT_RECOVERY_SELFUPDATE', app[2]
assert app[3].enabled and app[3].resolved_backend=='URSUSBOOT_RECOVERY_CUSTOM_IMAGE', app[3]

expert=(ROOT/'data/expert.py').read_text(encoding='utf-8')
for needle in (
    'VISIBLE_ACTIONS = (1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12)',
    'Пункт 4 объединён с пунктом 2',
    'Установленная OpenWrt: SSH → передача образа → sysupgrade -T → sysupgrade',
    'UrsusBoot Recovery: HTTP → обновление FIP с сетевыми ретраями; TFTP только отдельным ручным recovery-путём',
    'USB-UART → Airoha BootROM → UrsusBoot из RAM → запись и проверка загрузчика',
    'Проверка на ПК: структура, размеры и SHA256; роутер не изменяется',
    'sysupgrade -v -n',
):
    assert needle in expert, needle
assert '_show_action(4' not in expert
proven=(ROOT/'data/proven_backend.py').read_text(encoding='utf-8')
assert 'def ssh_write_binary(' in proven
assert 'cat > {shlex.quote(partial)}' in proven
print('STATEUI7_MENUOPS1_QA=PASS')

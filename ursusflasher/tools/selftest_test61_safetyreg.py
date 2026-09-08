#!/usr/bin/env python3
from pathlib import Path
import hashlib, json
HERE=Path(__file__).resolve()
if (HERE.parents[1]/"data").is_dir():
    ROOT=HERE.parents[1]; SRC=ROOT/"data"; PATCH=None
else:
    ROOT=HERE.parents[2]; SRC=ROOT/"ursusflasher"/"src"; PATCH=ROOT/"ursusboot"/"patches"/"180-test61-safetyreg1.patch"
one=(SRC/"one_key.py").read_text(encoding="utf-8")
exp=(SRC/"expert.py").read_text(encoding="utf-8")
inst=(SRC/"ursusboot_install.py").read_text(encoding="utf-8")
web=(SRC/"ursus_web_client.py").read_text(encoding="utf-8")
assert 'TARGET_URSUS = "0.1.0-alpha5-UBIUX1-TEST61"' in one
assert "ensure_target_ursus" not in one
assert "update_bootloader(" not in one
assert "skip_full_backup=skip_full_backup" in one
assert "skip_full_backup=skip_backup" in exp
assert "Начать запись mtd0? [y/N]:" in inst
assert 'answer = "INSTALL"' not in inst
assert "UPLOAD_RECONNECT_GRACE = 75.0" in web
assert "Повторить передачу файла с начала? [y/N]:" in web
assert "'transaction_state': 'NOT_STARTED'" in web
manifest=json.loads((SRC/"MANIFEST.json").read_text(encoding="utf-8"))
c=manifest["ursusboot"]["alpha5_test61_candidate"]
pay=(SRC/"payloads/md/ursusboot")
raw=pay/"ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-u-boot.bin"
fip=pay/"ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip"
assert hashlib.sha256(raw.read_bytes()).hexdigest()==c["raw_bl33_sha256"]
assert hashlib.sha256(fip.read_bytes()).hexdigest()==c["fip_sha256"]
assert b"0.1.0-alpha5-UBIUX1-TEST61" in raw.read_bytes()
assert b"URSUS_UPDATE_UBI_REUSE" in raw.read_bytes()
if PATCH is not None:
    patch=PATCH.read_text(encoding="utf-8")
    assert "URSUS_UPDATE_UBI_REUSE" in patch
    assert '-        run_command("ubi detach", 0);' in patch
    assert '#define URSUS_VERSION "0.1.0-alpha5-UBIUX1-TEST61"' in patch
    assert "opView" in patch and "fwContext=!opActive" in patch
print("TEST61_SAFETYREG_HOST_SELFTEST=PASS")

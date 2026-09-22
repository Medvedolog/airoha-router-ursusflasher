#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/"ursusflasher"/"src"

route=(SRC/"ursusboot_pregnant.py").read_text(encoding="utf-8")
expert=(SRC/"expert.py").read_text(encoding="utf-8")
web=(SRC/"ursus_web_client.py").read_text(encoding="utf-8")

assert 'one_key.require_bundle_role("OPENWRT_UBI_SYSUPGRADE")' in route
assert 'one_key.require_bundle_role("STOCK_TO_UBI_PRELOADER_BL2_CANDIDATE")' in route
assert 'uw.update_firmware(' in route
assert 'preloader=preloader' in route
assert 'uw.upload(host, image, "initramfs"' not in route
assert 'boot_once(' not in route
assert 'UrsusBoot Recovery is retained' in route
assert 'Stock Nokia → OpenWrt UBI с UrsusBoot Recovery' in expert
assert 'UrsusBoot Recovery сохраняется' in expert
assert "'firmware': ('/api/firmware-begin', '/api/firmware-chunk')" in web
assert "'preloader': ('/api/ubi-preloader-begin', '/api/ubi-preloader-chunk')" in web
assert "'fip': ('/api/ursus-fip-begin', '/api/ursus-fip-chunk')" in web
print("selftest_item4_direct_ubi: PASS")

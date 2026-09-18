#!/usr/bin/env python3
from __future__ import annotations
import ast, json, os, sys
from pathlib import Path
os.environ.setdefault("NOKIA_LANG","en")
ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/"ursusflasher"/"src"
sys.path.insert(0,str(SRC))
import stock_fit_initramfs as sfi

def test_shipped_route():
    expert=(SRC/"expert.py").read_text(encoding="utf-8")
    multi=(SRC/"expert_multi.py").read_text(encoding="utf-8")
    assert "import stock_ab_pregnant" in expert and "import stock_ab_pregnant" in multi
    assert "stock_ab_pregnant.run_expert(host=host, profile=profile)" in expert
    assert "stock_ab_pregnant.run_expert(host=host, profile=profile)" in multi
    assert "stock_ab_transition.run_expert(host=host, profile=profile)" not in multi

def test_single_confirmation_boundary():
    source=(SRC/"stock_ab_pregnant.py").read_text(encoding="utf-8")
    tree=ast.parse(source); run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="run")
    prompts=[n for n in ast.walk(run) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="prompt"]
    assert len(prompts)==1, len(prompts)
    boundary=source.index("sat._write_partition(")
    assert ".prompt(" not in source[boundary:]
    assert "no second confirmation exists" in source

def test_slot_layout_contract():
    regions=[(sfi.PREGNANT_META_OFF,sfi.PREGNANT_META_SIZE),(sfi.PREGNANT_PRODUCTION_OFF,sfi.PREGNANT_PRODUCTION_WINDOW),(sfi.PREGNANT_FIP_OFF,sfi.PREGNANT_FIP_WINDOW),(sfi.PREGNANT_PRELOADER_OFF,sfi.PREGNANT_PRELOADER_WINDOW)]
    slot=0x02880000
    for off,size in regions:
        assert off%0x20000==0 and size%0x20000==0 and 0<=off<off+size<=slot
    for i,(a,alen) in enumerate(regions):
        for b,blen in regions[i+1:]: assert max(a,b)>=min(a+alen,b+blen)

def test_runtime_safety_contract():
    stage2=(ROOT/"openwrt"/"pregnant-overlay"/"usr"/"sbin"/"ursus-vanilla-stage2").read_text()
    slot=(ROOT/"openwrt"/"pregnant-overlay"/"usr"/"sbin"/"ursusstockslot").read_text()
    for forbidden in ("CONFIRM FORMAT AND FLASH","YES I UNDERSTAND","--force"):
        assert forbidden not in stage2 and forbidden not in slot
    start=slot.index("write_target()"); end=slot.index('case "${1:-status}"')
    wt=slot[start:end]; assert "probe_pristine" in wt and "flagback" not in wt
    order=[stage2.index('ubiupdatevol "/dev/${UBI_DEV}_5" "$PROD"'),stage2.index('ubiupdatevol "/dev/${UBI_DEV}_2" "$WORK/bosa.bin"'),stage2.index('ubiupdatevol "/dev/${UBI_DEV}_4" "$FIP"'),stage2.index('mtd write "$WORK/bl2.bin" bl2'),stage2.index("persist_state PROD_VERIFIED")]
    assert order==sorted(order),order
    for state in ("PROD_WRITING","PROD_VERIFIED","BOOT_CONFIRMED"): assert state in slot or state in stage2

def test_pinned_unameone_manifest():
    data=json.loads((ROOT/"config"/"UNAMEONE_2026-09-16_PAYLOADS.json").read_text())
    assert data["policy"]["single_production_payload_source"] is True
    assert data["profiles"]["xg040-md"]["ubi_sysupgrade"]["sha256"]=="9b1f0899ca4ef610f6d87e8572d369adb420f104bda667556e8a0b5979f066dd"
    assert data["profiles"]["xg040-mf"]["ubi_sysupgrade"]["sha256"]=="21dcf4c6ca64ea0c5bc3d601e4a8f99a3f002371b873f399f622cbd9223fd1d1"

test_shipped_route(); test_single_confirmation_boundary(); test_slot_layout_contract(); test_runtime_safety_contract(); test_pinned_unameone_manifest()
print("selftest_pregnant_item4: PASS")

# CI artifact refresh: exact FULL kit for current EXPERT/item4 contract.
#!/usr/bin/env python3
from __future__ import annotations
import ast, json, os, sys
from pathlib import Path
os.environ.setdefault("NOKIA_LANG","en")
ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/"ursusflasher"/"src"
sys.path.insert(0,str(SRC))
import stock_fit_initramfs as sfi
import stock_fit_wrapper as sfw

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
    assert "DESTRUCTIVE=0" in stage2
    assert "Pre-destructive failure: rebooting through stock tcboot" in stage2
    boundary=stage2.index("DESTRUCTIVE=1")
    assert boundary < stage2.index('ubiformat -y "/dev/mtd${UBI_IDX}"')
    assert "automatic stock rollback/reboot is disabled" in stage2


def test_stock_wrapper_accepts_fit_smaller_than_nt_payload():
    src=(SRC/"stock_fit_wrapper.py").read_text(encoding="utf-8")
    assert "total != nt_size - 0x100" not in src
    assert "fit_trailing_payload_size" in src
    fit_off=0x1000
    fit_total=0x200
    nt_end=0x5000
    blob=bytearray(b"\0"*nt_end)
    props={
        "/images/filesystem@1/data-position": (0x100,4),
        "/images/filesystem@1/data-size": (0x104,4),
    }
    import struct
    struct.pack_into(">I", blob, 0x100, 0x800)
    struct.pack_into(">I", blob, 0x104, 0x300)
    off,size=sfw.image_data_range(bytes(blob),props,"filesystem@1",fit_off=fit_off,fit_total=fit_total,nt_end=nt_end)
    assert (off,size)==(0x1800,0x300)


def test_md_pregnant_carrier_accepts_external_image_data():
    src=(SRC/"stock_fit_initramfs.py").read_text(encoding="utf-8")
    assert "ntfw_staging_bounds_verified" in src
    assert 'fit_meta.get("fdt_data_offset")' in src
    assert 'props["/images/filesystem@1/data"]' not in src
    assert 'props["/images/fdt@1/data"]' not in src


def test_stock_kernel_hash_algo_is_optional():
    import struct
    blob=bytearray(b"\0"*128)
    props={
        "/images/kernel-any/hash@7/value": (16,20),
    }
    blob[16:36]=b"x"*20
    fields=sfw.kernel_hash_fields(bytes(blob),props,"kernel-any")
    assert fields==[{
        "node":"hash@7",
        "algorithm":"sha1",
        "value_offset":16,
        "value_size":20,
        "algo_present":False,
    }]

    props256={
        "/images/kernel-any/hash@2/algo": (40,7),
        "/images/kernel-any/hash@2/value": (64,32),
    }
    blob[40:47]=b"sha256\0"
    blob[64:96]=b"y"*32
    fields=sfw.kernel_hash_fields(bytes(blob),props256,"kernel-any")
    assert fields[0]["algorithm"]=="sha256"
    assert fields[0]["node"]=="hash@2"

    src=(SRC/"stock_fit_wrapper.py").read_text(encoding="utf-8")
    contract=src[src.index("def stock_fit_contract"):src.index("def build_transition_slot")]
    assert '"/images/kernel@1/hash@1/algo": b"sha1\\0"' not in contract
    assert 'props["/images/kernel@1/hash@1/value"]' not in src


def test_stock_fit_topology_is_derived_not_hardcoded():
    src=(SRC/"stock_fit_wrapper.py").read_text(encoding="utf-8")
    contract=src[src.index("def selected_fit_nodes"):src.index("def build_transition_slot")]
    for forbidden in (
        '"/images/kernel@1/type"',
        '"/configurations/default": b"conf@1\\0"',
        '"/configurations/conf@1/kernel"',
        'load != 0x80088000',
        'entry != 0x80088000',
        'stock filesystem@1 is not SquashFS',
        'd6d0eea7fcead54b97829934f234b6e4',
    ):
        assert forbidden not in contract and forbidden not in (SRC/"stock_fit_initramfs.py").read_text(encoding="utf-8")
    assert "selected_fit_nodes" in src
    assert "expected exactly one in-range HDR2/FIT boot payload" in src
    assert "stock_fdt_magic_ok" in src
    assert "ntfw_staging_bounds_verified" in src

def test_md_staging_does_not_require_config_filesystem_or_fit_carrier():
    wrapper=(SRC/"stock_fit_wrapper.py").read_text(encoding="utf-8")
    src=(SRC/"stock_fit_initramfs.py").read_text(encoding="utf-8")
    assert 'for role in ("fdt", "filesystem")' in wrapper
    assert 'if key in props:' in wrapper
    md=src[src.index("def _build_md_proven_pregnant_slot"):src.index("def build_pregnant_slot")]
    assert "unique_covering_image(" not in md
    assert "nt_off <= off < off + size <= nt_end" in md
    assert '("active-kernel", int(fit_meta["kernel_data_offset"])' in md
    assert '("active-fdt", int(fit_meta["fdt_data_offset"])' in md
    assert "runtime_fit_off=runtime_ram_offset" in md
    assert 'runtime_ram_offset + len(runtime_fit) > int(fit_meta["total_size"])' in md
    assert "STOCK_FIP_HDR2_PROVEN_HANDOFF_NTFW_STAGING_V2" in md


def test_md_uses_hw_proven_stock_wrapper():
    sfi_source=(SRC/"stock_fit_initramfs.py").read_text(encoding="utf-8")
    pregnant=(SRC/"stock_ab_pregnant.py").read_text(encoding="utf-8")
    assert "STOCK_FIP_HDR2_PROVEN_HANDOFF_NTFW_STAGING_V2" in sfi_source
    assert "sfw.build_transition_slot(" in sfi_source
    assert "stock_tcboot_fdt_byte_identical" in sfi_source
    assert 'files["handoff"]' in pregnant
    assert "pregnant-handoff.linuximg" in pregnant

def test_md_handoff_is_networkless_and_returns_to_stock_ab():
    cfg=(ROOT/"ursusboot"/"configs"/"ursusboot-pregnant-handoff.cfg").read_text(encoding="utf-8")
    patch=(ROOT/"ursusboot"/"patches"/"191-md-pregnant-handoff.patch").read_text(encoding="utf-8")
    build=(ROOT/"ursusboot"/"scripts"/"build_md_pregnant_handoff.sh").read_text(encoding="utf-8")
    assert "CONFIG_NET_LWIP=y" in cfg
    for sym in ("CONFIG_CMD_PING","CONFIG_CMD_DHCP","CONFIG_CMD_WGET"):
        assert f"# {sym} is not set" in cfg
    baseline=(ROOT/"ursusboot"/"configs"/"u-boot.TEST61.full.config").read_text(encoding="utf-8")
    assert "CONFIG_PSCI_RESET=y" in baseline
    assert "CONFIG_RESET_AIROHA=y" in baseline
    assert 'run_command("bootm 0x92000000", 0)' in patch
    assert 'run_command("reset", 0)' in patch
    assert "resetting for stock A/B retry" in patch
    assert "WEB=DISABLED" in build
    assert "NETWORK_RUNTIME=UNUSED" in build
    assert "BOOTM_RETURN=RESET_TO_STOCK_AB" in build

def test_pinned_unameone_manifest():
    data=json.loads((ROOT/"config"/"UNAMEONE_2026-09-16_PAYLOADS.json").read_text())
    assert data["policy"]["single_production_payload_source"] is True
    assert data["profiles"]["xg040-md"]["ubi_sysupgrade"]["sha256"]=="9b1f0899ca4ef610f6d87e8572d369adb420f104bda667556e8a0b5979f066dd"
    assert data["profiles"]["xg040-mf"]["ubi_sysupgrade"]["sha256"]=="21dcf4c6ca64ea0c5bc3d601e4a8f99a3f002371b873f399f622cbd9223fd1d1"

def test_pinned_boot_chain_manifest():
    data=json.loads((ROOT/"config"/"VANILLA_BOOT_CHAIN_PROFILES.json").read_text())
    assert data["source"]["repository"]=="Medvedolog/nokia-router-medveflasher"
    assert data["source"]["commit"]=="342cac4cb99a924f3d83eb8e4b5259490377704e"
    md=data["profiles"]["xg040-md"]; mf=data["profiles"]["xg040-mf"]
    assert md["fip"]["sha256"]=="8625d786cdded8ce2e5de27abc1ead7b1546e058ee055089e5c9780518f540f1"
    assert md["fip"]["status"]=="HW_VERIFIED_BY_OPERATOR_FUDAN_MD"
    assert md["preloader"]["sha256"]=="ed42a1d2f2cfca1af08c0ba935a8311260954c7424301d1ff99166f9e10c2f30"
    assert mf["fip"]["sha256"]=="99b6c20a7cb46a56692eaeb9f086f70fc7e987a641396653e6a8fb5c03e07aa7"
    assert mf["preloader"]["sha256"]=="778d10a65276085b70bec005248fc87ec208b43b0239502f15ade20fe528301e"
    assembly=(ROOT/"ursusflasher"/"tools"/"assemble_pregnant_payload.py").read_text()
    assert "VANILLA_BOOT_CHAIN_PROFILES.json" in assembly

test_shipped_route(); test_single_confirmation_boundary(); test_slot_layout_contract(); test_runtime_safety_contract(); test_stock_wrapper_accepts_fit_smaller_than_nt_payload(); test_md_pregnant_carrier_accepts_external_image_data(); test_stock_kernel_hash_algo_is_optional(); test_stock_fit_topology_is_derived_not_hardcoded(); test_md_staging_does_not_require_config_filesystem_or_fit_carrier(); test_md_uses_hw_proven_stock_wrapper(); test_md_handoff_is_networkless_and_returns_to_stock_ab(); test_pinned_unameone_manifest(); test_pinned_boot_chain_manifest()
print("selftest_pregnant_item4: PASS")

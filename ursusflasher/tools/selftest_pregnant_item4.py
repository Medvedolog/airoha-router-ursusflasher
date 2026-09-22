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

def test_confirmation_boundary():
    source=(SRC/"stock_ab_pregnant.py").read_text(encoding="utf-8")
    tree=ast.parse(source); run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="run")
    prompts=[n for n in ast.walk(run) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="prompt"]
    assert len(prompts)==2, len(prompts)
    boundary=source.index("sat._write_partition(")
    assert ".prompt(" not in source[boundary:]
    assert 'if full_backup is None:' in source
    assert 'Type YES to continue' in source
    assert 'emergency != "YES"' in source

def test_item4_reuses_existing_verified_backup():
    source=(SRC/"stock_ab_pregnant.py").read_text(encoding="utf-8")
    run=source[source.index("def run("):source.index("def run_expert(")]
    helper=source[source.index("def _choose_verified_stock_backup"):source.index("def _payload_root")]
    assert "pb.backup_tftp(" not in run
    assert 'run_dir / "full-stock-backup"' not in run
    assert "_choose_verified_stock_backup(policy, backup_path)" in run
    assert "pb.verify_stock_restore_backup(path)" in helper
    assert "continue WITHOUT backup" in helper
    assert "return None, None" in helper
    assert "existing stock backup path is required for item 4" not in helper
    assert "--backup" in source

def test_slot_layout_contract():
    regions=[(sfi.PREGNANT_META_OFF,sfi.PREGNANT_META_SIZE),(sfi.PREGNANT_PRODUCTION_OFF,sfi.PREGNANT_PRODUCTION_WINDOW),(sfi.PREGNANT_FIP_OFF,sfi.PREGNANT_FIP_WINDOW),(sfi.PREGNANT_PRELOADER_OFF,sfi.PREGNANT_PRELOADER_WINDOW)]
    slot=0x02880000
    for off,size in regions:
        assert off%0x20000==0 and size%0x20000==0 and 0<=off<off+size<=slot
    for i,(a,alen) in enumerate(regions):
        for b,blen in regions[i+1:]: assert max(a,b)>=min(a+alen,b+blen)

def test_no_stock_snapshot_hash_gates():
    pregnant=(SRC/"stock_ab_pregnant.py").read_text(encoding="utf-8")
    initramfs=(SRC/"stock_fit_initramfs.py").read_text(encoding="utf-8")
    slot=(ROOT/"openwrt"/"pregnant-overlay"/"usr"/"sbin"/"ursusstockslot").read_text()
    for token in (
        "STOCK_BOOTLOADER_SHA256",
        "STOCK_MASTER_SHA256",
        "STOCK_FLAGBACK_SHA256",
        "STOCK_FLAG_TAIL_SHA256",
        "STOCK_BOSA_SHA256",
        "STOCK_RI_SHA256",
    ):
        assert token not in pregnant
        assert token not in initramfs
        assert token not in slot
    for refusal in (
        "STOCK_BOOTLOADER_CHANGED",
        "MASTER_CHANGED",
        "FLAGBACK_CHANGED",
        "FLAG_NON_ACTIVE_CHANGED",
        "BOSA_CHANGED",
        "RI_CHANGED",
    ):
        assert refusal not in slot
    assert "canonical_ubi_header_present && fail UBI_OR_PARTIAL_CONVERSION" in slot
    assert "require_geom nsb_slave 02880000 00020000" in slot


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


def test_item4_backup_is_optional_and_never_recaptured():
    source=(SRC/"stock_ab_pregnant.py").read_text(encoding="utf-8")
    run=source[source.index("def run("):source.index("def run_expert(")]
    assert "pb.backup_tftp(" not in run
    assert "continue WITHOUT backup" in source
    assert "_capture_live_partition(" in run
    assert "number=policy.slave_mtd" in run
    assert "number=policy.flag_mtd" in run
    assert "_remote_mtd_sha(telnet, policy.master_mtd)" in run
    assert "full_backup is None" in run
    assert "restore-grade backup" in run


def test_postwrite_readback_reconnect_never_rewrites():
    source=(SRC/"stock_ab_pregnant.py").read_text(encoding="utf-8")
    helper=source[source.index("def _readback_sha_with_reconnect"):source.index("def run(")]
    assert "attempts: int = 3" in helper
    assert "sat._remote_partition_sha" in helper
    assert "_reopen_verified_stock_root(host, policy)" in helper
    assert "_write_partition(" not in helper
    assert "NAND повторно НЕ записывается" in helper
    run=source[source.index("def run("):source.index("def run_expert(")]
    assert 'access, telnet, got = _readback_sha_with_reconnect(' in run
    assert 'access, telnet, got_flag = _readback_sha_with_reconnect(' in run


def test_postwrite_readback_reconnect_does_not_require_web():
    src=(SRC/"stock_ab_pregnant.py").read_text(encoding="utf-8")
    reopen=src[src.index("def _reopen_verified_stock_root"):src.index("def _readback_sha_with_reconnect")]
    retry=src[src.index("def _readback_sha_with_reconnect"):src.index("def run(")]
    assert "ubi.open_root_auto" not in reopen
    assert "pb.login_root_family(access, policy.family, allow_service_provisioning=False)" in reopen
    assert "current_access = current_telnet = None" not in retry
    assert "_reopen_verified_stock_root(host, policy, current_access)" in retry
    assert "close_web" in retry
    assert "_write_partition" not in retry


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

    propscrc={
        "/images/kernel-any/hash-1/algo": (96,6),
        "/images/kernel-any/hash-1/value": (104,4),
    }
    blob[96:102]=b"crc32\0"
    blob[104:108]=b"z"*4
    fields=sfw.kernel_hash_fields(bytes(blob),propscrc,"kernel-any")
    assert fields[0]["algorithm"]=="crc32"
    assert fields[0]["node"]=="hash-1"
    assert fields[0]["value_size"]==4

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
    generic=src[src.index("def stock_fit_contract"):src.index("def build_md_proven_transition_slot")]
    assert '"/images/kernel@1/hash@1/algo": b"sha1\\0"' not in generic
    assert 'props["/images/kernel@1/hash@1/value"]' not in generic
    proven=src[src.index("def build_md_proven_transition_slot"):src.index("def build_md_transition_slot")]
    assert '"/images/kernel@1/hash@1/algo": b"sha1\\0"' in proven
    assert 'props["/images/kernel@1/hash@1/value"]' in proven


def test_kernel_hash_refresh_is_fail_closed_and_crc32_big_endian():
    import struct
    import zlib

    payload = b"fudan-kernel-padded-span"
    crc = sfw.kernel_digest("crc32", payload)
    expected = struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
    assert crc == expected
    if expected != expected[::-1]:
        assert crc != expected[::-1], "FIT crc32 must be stored big-endian"

    props = {
        "/images/kernel@1/hash-1/value": (16, 4),
        "/images/kernel@1/hash-1/algo": (24, 6),
        "/images/kernel@1/hash-2/value": (32, 20),
        "/images/kernel@1/hash-2/algo": (56, 5),
    }
    assert sfw.kernel_hash_nodes(props, "kernel@1") == {"hash-1", "hash-2"}

    sfw.assert_no_stale_kernel_hashes(props, "kernel@1", {"hash-1", "hash-2"})
    try:
        sfw.assert_no_stale_kernel_hashes(props, "kernel@1", {"hash-2"})
    except RuntimeError as exc:
        assert "stale kernel digests" in str(exc)
        assert "hash-1" in str(exc)
    else:
        raise AssertionError("stale crc32 hash node was silently accepted")

    try:
        sfw.assert_no_stale_kernel_hashes(props, "kernel@1", {"hash-1"})
    except RuntimeError as exc:
        assert "hash-2" in str(exc)
    else:
        raise AssertionError("stale secondary kernel hash node was silently accepted")

    src=(SRC/"stock_fit_wrapper.py").read_text(encoding="utf-8")
    proven=src[src.index("def build_md_proven_transition_slot"):src.index("def build_md_transition_slot")]
    generic=src[src.index("def build_transition_slot"):]
    assert 'assert_no_stale_kernel_hashes(props, "kernel@1", {"hash@1"})' in proven
    assert "assert_no_stale_kernel_hashes(" in generic
    assert "kernel_digest(algo, kernel)" in generic


def test_stock_fit_topology_is_derived_not_hardcoded():
    src=(SRC/"stock_fit_wrapper.py").read_text(encoding="utf-8")
    generic=src[src.index("def selected_fit_nodes"):src.index("def build_md_proven_transition_slot")]
    initramfs=(SRC/"stock_fit_initramfs.py").read_text(encoding="utf-8")
    for forbidden in (
        '"/images/kernel@1/type"',
        '"/configurations/default": b"conf@1\\0"',
        '"/configurations/conf@1/kernel"',
        'load != 0x80088000',
        'entry != 0x80088000',
        'stock filesystem@1 is not SquashFS',
        'd6d0eea7fcead54b97829934f234b6e4',
    ):
        assert forbidden not in generic and forbidden not in initramfs
    proven=src[src.index("def build_md_proven_transition_slot"):src.index("def build_md_transition_slot")]
    assert '"/images/kernel@1/type"' in proven
    assert '"/configurations/default": b"conf@1\\0"' in proven
    assert "selected_fit_nodes" in src
    assert "expected exactly one in-range HDR2/FIT boot payload" in src
    assert "stock_fdt_magic_ok" in src
    assert "ntfw_staging_bounds_verified" in initramfs

def test_md_staging_does_not_require_config_filesystem_or_fit_carrier():
    wrapper=(SRC/"stock_fit_wrapper.py").read_text(encoding="utf-8")
    src=(SRC/"stock_fit_initramfs.py").read_text(encoding="utf-8")
    assert 'for role in ("fdt", "filesystem")' in wrapper
    assert 'if key in props:' in wrapper
    md=src[src.index("def _build_md_proven_pregnant_slot"):src.index("def build_pregnant_slot")]
    assert "unique_covering_image(" not in md
    assert "nt_off <= off < off + size <= nt_end" in md
    assert '("active-kernel", int(fit_meta["kernel_data_offset"])' not in md
    assert '("handoff-linux-image", kernel_off, len(patched_handoff))' in md
    assert '("active-fdt", int(fit_meta["fdt_data_offset"])' in md
    assert "runtime_fit_off=runtime_ram_offset" in md
    assert "loaded_nt_payload_size = nt_size - (fit_off - nt_off)" in md
    assert "runtime_ram_offset + len(runtime_fit) > loaded_nt_payload_size" in md
    assert 'runtime_ram_offset + len(runtime_fit) > int(fit_meta["total_size"])' not in md
    assert 'for image in fit_meta.get("image_ranges") or []:' in md
    assert 'occupied_end = max(end for _begin, end in occupied)' in md
    assert 'cursor = (occupied_end + 0x1FFFF) & ~0x1FFFF' in md
    assert 'runtime_region = alloc("runtime", len(runtime_fit))' in md
    assert 'meta_region = alloc("manifest", PREGNANT_META_SIZE)' in md
    assert 'out[runtime_off:runtime_off + len(runtime_fit)] = runtime_fit' in md
    assert "final_kernel = bytes(out[kernel_off:kernel_off + kernel_size])" not in md
    assert "final kernel hash length mismatch" not in md
    assert "STOCK_FIP_HDR2_PROVEN_HANDOFF_FREE_TAIL_V4" in md


def test_md_ntfw_tail_is_not_treated_as_free_carrier():
    src=(SRC/"stock_fit_initramfs.py").read_text(encoding="utf-8")
    md=src[src.index("def _build_md_proven_pregnant_slot"):src.index("def build_pregnant_slot")]
    assert "MD pregnant in-NT-FW tail staging is disabled" in md
    assert "FIT trailing payload is stock parser data, not free space" in md


def test_runtime_ram_bound_uses_ntfw_not_fit_totalsize():
    src=(SRC/"stock_fit_initramfs.py").read_text(encoding="utf-8")
    md=src[src.index("def _build_md_proven_pregnant_slot"):src.index("def build_pregnant_slot")]
    assert "loaded_nt_payload_size = nt_size - (fit_off - nt_off)" in md
    assert "runtime_ram_offset + len(runtime_fit) > loaded_nt_payload_size" in md
    assert 'fit_meta["total_size"]' not in md[md.index("runtime_ram_offset ="):md.index("patched_handoff =")]


def test_runtime_overlap_policy_matches_handoff_design():
    src=(SRC/"stock_fit_initramfs.py").read_text(encoding="utf-8")
    md=src[src.index("def _build_md_proven_pregnant_slot"):src.index("def build_pregnant_slot")]
    assert "Hardware-proven TRANSITION2 semantics" in md
    assert 'for image in fit_meta.get("image_ranges") or []:' in md
    assert 'occupied_end = max(end for _begin, end in occupied)' in md
    assert "handoff-linux-image" in md
    assert "active-kernel" not in md
    assert "refreshed_hash_ranges" not in md
    assert "transition_kernel_hashes_preserved" in md
    assert "PREGNANT_RUNTIME_OFF:PREGNANT_RUNTIME_OFF + PREGNANT_RUNTIME_WINDOW" not in md


def test_md_runtime_uses_exact_live_tail_span():
    src=(SRC/"stock_fit_initramfs.py").read_text(encoding="utf-8")
    md=src[src.index("def _build_md_proven_pregnant_slot"):src.index("def build_pregnant_slot")]
    assert 'occupied = [(nt_off, fit_off + int(fit_meta["total_size"]))]' in md
    assert 'occupied.append((int(image["offset"]), int(image["end"])))' in md
    assert 'out[production_off:production_off + len(production_itb)] = production_itb' in md
    assert 'out[fip_off:fip_off + len(vanilla_fip)] = vanilla_fip' in md
    assert 'out[preloader_off:preloader_off + len(vanilla_preloader)] = vanilla_preloader' in md


def test_stage2_discovers_dynamic_manifest_and_offsets():
    stage2=(ROOT/"openwrt"/"pregnant-overlay"/"usr"/"sbin"/"ursus-vanilla-stage2").read_text()
    assert "blocks=$((SLOT_SIZE / ERASE_SIZE))" in stage2
    assert "META_NOT_FOUND" in stage2
    assert "META_SLOT_OFF=$candidate_off" in stage2
    assert "PROD_SLOT_OFF=\"$(meta_get PRODUCTION_SLOT_OFF)\"" in stage2
    assert "FIP_SLOT_OFF=\"$(meta_get FIP_SLOT_OFF)\"" in stage2
    assert "PRE_SLOT_OFF=\"$(meta_get PRELOADER_SLOT_OFF)\"" in stage2
    assert '[ "$(meta_get PRODUCTION_SLOT_OFF)" = 0x01000000 ]' not in stage2
    assert '[ "$(meta_get FIP_SLOT_OFF)" = 0x01c00000 ]' not in stage2
    assert '[ "$(meta_get PRELOADER_SLOT_OFF)" = 0x01e00000 ]' not in stage2


def test_md_uses_hw_proven_stock_wrapper():
    sfi_source=(SRC/"stock_fit_initramfs.py").read_text(encoding="utf-8")
    pregnant=(SRC/"stock_ab_pregnant.py").read_text(encoding="utf-8")
    assert "STOCK_FIP_HDR2_PROVEN_HANDOFF_FREE_TAIL_V4" in sfi_source
    assert "sfw.build_md_transition_slot(" in sfi_source
    wrapper=(SRC/"stock_fit_wrapper.py").read_text(encoding="utf-8")
    assert "def build_md_proven_transition_slot(" in wrapper
    assert "MD_HW_PROVEN_TRANSITION2_LITERAL_FIT_V1" in wrapper
    assert "def build_md_transition_slot(" in wrapper
    assert "Node names are not an applicability gate" in wrapper
    assert "return build_transition_slot(" in wrapper
    assert "stock_tcboot_fdt_byte_identical" in sfi_source
    assert 'files["handoff"]' in pregnant
    assert "pregnant-handoff.linuximg" in pregnant

def test_md_proven_wrapper_matches_hw_transition2_mutation_surface():
    wrapper=(SRC/"stock_fit_wrapper.py").read_text(encoding="utf-8")
    proven=wrapper[wrapper.index("def build_md_proven_transition_slot"):wrapper.index("def build_md_transition_slot")]
    assert '"/images/kernel@1/data"' in proven
    assert '"/images/fdt@1/data"' in proven
    assert '"/images/filesystem@1/data"' in proven
    assert '"/images/kernel@1/hash@1/value"' in proven
    assert 'out[comp_off:comp_off + comp_len] = b"none\\0"' in proven
    assert "hashlib.sha1(kernel).digest()" in proven
    assert "unexpected bytes changed outside proven MD TRANSITION2 FIT fields" in proven


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


def test_recovery_loader_item4_route():
    expert=(SRC/"expert.py").read_text(encoding="utf-8")
    multi=(SRC/"expert_multi.py").read_text(encoding="utf-8")
    route=(SRC/"ursusboot_pregnant.py").read_text(encoding="utf-8")
    web=(SRC/"ursus_web_client.py").read_text(encoding="utf-8")
    for shipped in (expert, multi):
        assert "ursusboot_pregnant.run_expert(host=host, profile=profile)" in shipped
        assert "stock_ab_pregnant.run_expert(host=host, profile=profile)" not in shipped
    assert 'route="stock"' in route
    assert 'skip_full_backup=False' in route
    assert 'uw.upload(host, image, "initramfs"' in route
    assert "uw.boot_once(host)" in route
    assert "pregnant._monitor(host, policy, meta)" in route
    assert "stock_ab_transition" not in route
    assert "nsb_slave" not in route
    assert "'POST', '/api/expert/boot-once'" in web


def test_autonomous_fit_contract():
    builder=(ROOT/"ursusflasher"/"tools"/"build_pregnant_runtime.py").read_text(encoding="utf-8")
    payload=(ROOT/"ursusflasher"/"tools"/"build_vanilla_pregnant_payloads.py").read_text(encoding="utf-8")
    stage2=(ROOT/"openwrt"/"pregnant-overlay"/"usr"/"sbin"/"ursus-vanilla-stage2").read_text()
    assert "def add_external_installer_ramdisk(" in builder
    assert '"type", b"ramdisk\\0"' in builder
    assert '"ramdisk", b"ursus-installer-ramdisk\\0"' in builder
    assert "pregnant-autonomous.itb" in payload
    assert "kernel_unchanged" in builder\n    assert "autonomous FIT exceeds UrsusBoot 64 MiB staging" in builder
    assert "URSUS_PREGNANT_RAMDISK_V1" in stage2
    assert "/installer/production.itb" in stage2
    assert "/installer/vanilla.fip" in stage2
    assert "/installer/preloader.bin" in stage2
    assert "PAYLOAD_MODE=EMBEDDED_RAMDISK" in stage2
    order=[
        stage2.index('ubiupdatevol "/dev/${UBI_DEV}_5" "$PROD"'),
        stage2.index('ubiupdatevol "/dev/${UBI_DEV}_2" "$WORK/bosa.bin"'),
        stage2.index('ubiupdatevol "/dev/${UBI_DEV}_4" "$FIP"'),
        stage2.index('mtd write "$WORK/bl2.bin" bl2'),
        stage2.index("persist_state PROD_VERIFIED"),
    ]
    assert order == sorted(order), order
    boundary=stage2.index("DESTRUCTIVE=1")
    assert boundary < stage2.index('ubiformat -y "/dev/mtd${UBI_IDX}"')
    assert "temporary UrsusBoot Recovery" in stage2


def test_item4_ui_contract():
    expert=(SRC/"expert.py").read_text(encoding="utf-8")
    assert "Установить чистый OpenWrt через временный UrsusBoot Recovery" in expert
    assert "UrsusBoot в финале удаляется" in expert
    assert 'enabled = profile == "xg040-md"' in expert


test_recovery_loader_item4_route()
test_autonomous_fit_contract()
test_item4_ui_contract()
test_no_stock_snapshot_hash_gates()
test_md_ntfw_tail_is_not_treated_as_free_carrier()
test_pinned_unameone_manifest()
test_pinned_boot_chain_manifest()
print("selftest_pregnant_item4: PASS")

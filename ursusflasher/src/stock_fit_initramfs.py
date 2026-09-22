#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import struct

import stock_fit_wrapper as sfw

FDT_MAGIC = 0xD00DFEED
FIP_MAGIC = bytes.fromhex('010064aa78563412')


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _align4(v: int) -> int:
    return (v + 3) & ~3


def parse_fit(blob: bytes, offset: int = 0) -> tuple[dict[str, tuple[int, int]], dict]:
    if offset < 0 or offset + 40 > len(blob):
        raise RuntimeError('FIT header is truncated')
    hdr = struct.unpack_from('>10I', blob, offset)
    magic, total, off_struct, off_strings, _off_mem, version, last_comp, _bootcpu, size_strings, size_struct = hdr
    if magic != FDT_MAGIC or version < 17 or last_comp > version:
        raise RuntimeError('image is not a supported FIT/FDT')
    if total < 40 or offset + total > len(blob):
        raise RuntimeError('FIT totalsize is out of range')
    struct_start = offset + off_struct
    struct_end = struct_start + size_struct
    strings_start = offset + off_strings
    strings_end = strings_start + size_strings
    if not (offset <= struct_start <= struct_end <= offset + total):
        raise RuntimeError('FIT structure block is out of range')
    if not (offset <= strings_start <= strings_end <= offset + total):
        raise RuntimeError('FIT strings block is out of range')
    strings = blob[strings_start:strings_end]
    props: dict[str, tuple[int, int]] = {}
    path: list[str] = []
    p = struct_start
    while p + 4 <= struct_end:
        token = struct.unpack_from('>I', blob, p)[0]
        p += 4
        if token == 1:
            end = blob.find(b'\0', p, struct_end)
            if end < 0:
                raise RuntimeError('unterminated FIT node name')
            path.append(blob[p:end].decode('ascii', 'strict'))
            p = _align4(end + 1)
        elif token == 2:
            if not path:
                raise RuntimeError('unbalanced FIT END_NODE')
            path.pop()
        elif token == 3:
            if p + 8 > struct_end:
                raise RuntimeError('truncated FIT property header')
            length, nameoff = struct.unpack_from('>II', blob, p)
            p += 8
            value_off = p
            p = _align4(p + length)
            if p > struct_end or nameoff >= len(strings):
                raise RuntimeError('FIT property range is invalid')
            end = strings.find(b'\0', nameoff)
            if end < 0:
                raise RuntimeError('unterminated FIT property name')
            name = strings[nameoff:end].decode('ascii', 'strict')
            key = '/' + '/'.join(x for x in path if x) + '/' + name
            props[key] = (value_off, int(length))
        elif token == 4:
            continue
        elif token == 9:
            break
        else:
            raise RuntimeError(f'unsupported/corrupt FIT token: {token:#x}')
    return props, {'offset': offset, 'total_size': total}


def _prop(blob: bytes, props: dict[str, tuple[int, int]], key: str) -> bytes:
    off, size = props[key]
    return blob[off:off + size]


def _image_nodes(blob: bytes, props: dict[str, tuple[int, int]]) -> list[dict]:
    nodes: dict[str, dict[str, bytes]] = {}
    for key in props:
        if not key.startswith('/images/'):
            continue
        rest = key[len('/images/'):]
        if '/' not in rest:
            continue
        node, name = rest.split('/', 1)
        if '/' in name:
            continue
        nodes.setdefault(node, {})[name] = _prop(blob, props, key)
    return [{'name': name, **p} for name, p in nodes.items()]


def source_fit_contract(source: bytes) -> dict:
    props, meta = parse_fit(source, 0)
    images = _image_nodes(source, props)
    kernels = [x for x in images if x.get('type') == b'kernel\0']
    fdts = [x for x in images if x.get('type') == b'flat_dt\0']
    if len(kernels) != 1:
        raise RuntimeError(f'expected one kernel image in installer FIT, got {len(kernels)}')
    if not fdts:
        raise RuntimeError('installer FIT has no flat_dt image')
    k = kernels[0]
    if k.get('arch') not in (None, b'arm64\0'):
        raise RuntimeError(f'installer FIT kernel arch is not arm64: {k.get("arch")!r}')
    if k.get('os') not in (None, b'linux\0'):
        raise RuntimeError(f'installer FIT kernel OS is not linux: {k.get("os")!r}')
    kdata = k.get('data')
    if not kdata:
        raise RuntimeError('installer FIT kernel data is empty')
    if not any((x.get('data') or b'').startswith(struct.pack('>I', FDT_MAGIC)) for x in fdts):
        raise RuntimeError('installer FIT DTB data is invalid')
    default = b''
    if '/configurations/default' in props:
        default = _prop(source, props, '/configurations/default').rstrip(b'\0')
    return {
        'fit_total_size': meta['total_size'],
        'kernel_node': k['name'],
        'kernel_data_size': len(kdata),
        'kernel_compression': (k.get('compression') or b'').rstrip(b'\0').decode('ascii', 'replace'),
        'fdt_nodes': [x['name'] for x in fdts],
        'default_config': default.decode('ascii', 'replace'),
        'sha256': sha256_bytes(source[:meta['total_size']]),
    }


def find_stock_nt_fw(slot: bytes, *, slot_size: int) -> tuple[int, int, str]:
    if len(slot) != slot_size:
        raise RuntimeError(f'stock slot size mismatch: {len(slot):#x} != {slot_size:#x}')
    if slot[:8] != FIP_MAGIC:
        raise RuntimeError('stock nsb_slave has no Airoha FIP header')
    candidates: list[tuple[int, int, str]] = []
    pos = 16
    while pos + 40 <= len(slot):
        uuid = slot[pos:pos + 16]
        if uuid == b'\0' * 16:
            break
        off, size, _flags = struct.unpack_from('<QQQ', slot, pos + 16)
        if 0 < size and off + size <= len(slot) and size > 0x100:
            if slot[off:off + 4] == b'HDR2' and struct.unpack_from('>I', slot, off + 0x100)[0] == FDT_MAGIC:
                candidates.append((int(off), int(size), uuid.hex()))
        pos += 40
    if len(candidates) != 1:
        raise RuntimeError(f'expected exactly one stock HDR2/FIT NT-FW entry, got {len(candidates)}')
    return candidates[0]


def build_installer_slot(stock_slot: bytes, installer_fit: bytes, *, slot_size: int) -> tuple[bytes, dict]:
    src = source_fit_contract(installer_fit)
    nt_off, nt_size, nt_uuid = find_stock_nt_fw(stock_slot, slot_size=slot_size)
    fit_off = nt_off + 0x100
    capacity = nt_size - 0x100
    total = int(src['fit_total_size'])
    bundle_total = len(installer_fit)
    if bundle_total > capacity:
        raise RuntimeError(f'installer bundle does not fit stock NT-FW payload: {bundle_total:#x} > {capacity:#x}')
    if struct.unpack_from('<I', stock_slot, nt_off + 0x08)[0] != nt_size:
        raise RuntimeError('stock HDR2 NT-FW size does not match FIP entry')
    out = bytearray(stock_slot)
    out[fit_off:fit_off + capacity] = b'\0' * capacity
    out[fit_off:fit_off + bundle_total] = installer_fit
    struct.pack_into('<I', out, nt_off + 0x50, int(src['kernel_data_size']))
    struct.pack_into('<I', out, nt_off + 0x54, 0)
    for i, (a, b) in enumerate(zip(stock_slot[:fit_off], bytes(out[:fit_off]))):
        if a != b and not (nt_off + 0x50 <= i < nt_off + 0x58):
            raise RuntimeError(f'unexpected stock wrapper byte changed at {i:#x}')
    if bytes(out[fit_off + capacity:]) != stock_slot[fit_off + capacity:]:
        raise RuntimeError('unexpected bytes changed after stock NT-FW payload')
    check = source_fit_contract(bytes(out[fit_off:fit_off + total]))
    if check['sha256'] != src['sha256']:
        raise RuntimeError('embedded installer FIT changed during stock wrapping')
    return bytes(out), {
        'wrapper_contract': 'STOCK_FIP_HDR2_FULL_INNER_FIT_REPLACEMENT',
        'slot_size': slot_size,
        'nt_fw_offset': nt_off,
        'nt_fw_size': nt_size,
        'nt_fw_uuid': nt_uuid,
        'inner_fit_offset': fit_off,
        'inner_fit_capacity': capacity,
        'installer_fit_size': total,
        'installer_fit_padding': capacity - bundle_total,
        'installer_fit_sha256': src['sha256'],
        'installer_bundle_size': bundle_total,
        'installer_trailing_payload_size': bundle_total - total,
        'installer_bundle_sha256': sha256_bytes(installer_fit),
        'installer_kernel_node': src['kernel_node'],
        'installer_kernel_data_size': src['kernel_data_size'],
        'installer_kernel_compression': src['kernel_compression'],
        'installer_default_config': src['default_config'],
        'stock_sha256': sha256_bytes(stock_slot),
        'candidate_sha256': sha256_bytes(bytes(out)),
        'hdr2_kernel_size_updated': True,
        'hdr2_filesystem_size': 0,
        'outer_fip_entry_preserved': True,
        'destructive_stage2_embedded': False,
    }


PREGNANT_RUNTIME_OFF = 0x00600000
PREGNANT_RUNTIME_WINDOW = 0x00900000
PREGNANT_META_OFF = 0x00F00000
PREGNANT_META_SIZE = 0x00020000
PREGNANT_PRODUCTION_OFF = 0x01000000
PREGNANT_PRODUCTION_WINDOW = 0x00C00000
PREGNANT_FIP_OFF = 0x01C00000
PREGNANT_FIP_WINDOW = 0x00200000
PREGNANT_PRELOADER_OFF = 0x01E00000
PREGNANT_PRELOADER_WINDOW = 0x00100000


def _pregnant_overlap(a_off: int, a_size: int, b_off: int, b_size: int) -> bool:
    return max(a_off, b_off) < min(a_off + a_size, b_off + b_size)


def _patch_md_handoff(handoff: bytes, *, runtime_fit_off: int, runtime_fit_size: int) -> bytes:
    marker = b"URSPREG1" + struct.pack("<II", 0xFEEDFACE, 0xCAFEF00D)
    if handoff.count(marker) != 1:
        raise RuntimeError("MD pregnant handoff placeholder marker is missing or ambiguous")
    sfw.validate_linux_image(handoff)
    out = bytearray(handoff)
    pos = out.index(marker)
    struct.pack_into("<II", out, pos + 8, runtime_fit_off, runtime_fit_size)
    sfw.validate_linux_image(bytes(out))
    return bytes(out)


def _build_md_proven_pregnant_slot(
    stock_slot: bytes,
    handoff_linux: bytes,
    runtime_fit: bytes,
    production_itb: bytes,
    vanilla_fip: bytes,
    vanilla_preloader: bytes,
    *,
    slot_size: int,
    evidence: dict,
) -> tuple[bytes, dict]:
    """Build MD SLOT2 on the hardware-proven stock tcboot wrapper.

    tcboot sees the original Nokia FIP/HDR2/FIT topology and original active FDT.
    Only the active kernel payload plus existing compression/hash metadata are changed.
    The stock active filesystem data span is a carrier only; hardware logs prove
    tcboot does not load it before starting the handoff kernel.
    """
    nt_off, nt_size = sfw.fip_nt_fw(stock_slot, slot_size=slot_size)
    props, fit_meta = sfw.stock_fit_contract(stock_slot, nt_off, nt_size)
    fit_off = int(fit_meta["fit_offset"])

    reserved = [
        ("runtime", PREGNANT_RUNTIME_OFF, PREGNANT_RUNTIME_WINDOW),
        ("manifest", PREGNANT_META_OFF, PREGNANT_META_SIZE),
        ("production", PREGNANT_PRODUCTION_OFF, PREGNANT_PRODUCTION_WINDOW),
        ("fip", PREGNANT_FIP_OFF, PREGNANT_FIP_WINDOW),
        ("preloader", PREGNANT_PRELOADER_OFF, PREGNANT_PRELOADER_WINDOW),
    ]
    nt_end = nt_off + nt_size
    protected = [
        ("active-kernel", int(fit_meta["kernel_data_offset"]), int(fit_meta["kernel_data_size"])),
    ]
    if fit_meta.get("fdt_data_offset") is not None:
        protected.append(
            ("active-fdt", int(fit_meta["fdt_data_offset"]), int(fit_meta["fdt_data_size"]))
        )

    for name, off, size in reserved:
        if off % 0x20000 or size % 0x20000 or not (nt_off <= off < off + size <= nt_end):
            raise RuntimeError(
                f"MD pregnant staging region {name} is outside stock NT-FW payload: "
                f"region={off:#x}+{size:#x} ntfw={nt_off:#x}..{nt_end:#x}"
            )
        for protected_name, protected_off, protected_size in protected:
            if _pregnant_overlap(off, size, protected_off, protected_size):
                raise RuntimeError(
                    f"MD pregnant staging region {name} overlaps {protected_name}: "
                    f"region={off:#x}+{size:#x} protected={protected_off:#x}+{protected_size:#x}"
                )
    for i, (name_a, off_a, size_a) in enumerate(reserved):
        for name_b, off_b, size_b in reserved[i + 1:]:
            if _pregnant_overlap(off_a, size_a, off_b, size_b):
                raise RuntimeError(f"MD pregnant carrier regions overlap: {name_a}/{name_b}")

    if len(runtime_fit) > PREGNANT_RUNTIME_WINDOW:
        raise RuntimeError("pregnant runtime exceeds reserved MD runtime window")
    runtime_ram_offset = PREGNANT_RUNTIME_OFF - fit_off
    if runtime_ram_offset < 0 or runtime_ram_offset + len(runtime_fit) > int(fit_meta["total_size"]):
        raise RuntimeError("pregnant runtime is outside tcboot-loaded stock FIT memory")
    patched_handoff = _patch_md_handoff(
        handoff_linux,
        runtime_fit_off=runtime_ram_offset,
        runtime_fit_size=len(runtime_fit),
    )
    base, wrapper = sfw.build_transition_slot(
        stock_slot,
        patched_handoff,
        slot_size=slot_size,
        nt_fw_uuid=None,
    )

    fields = [
        "URSUS_PREGNANT_V1",
        f"FAMILY={evidence['family']}",
        f"PROFILE={evidence['profile']}",
        f"SLOT_SIZE=0x{slot_size:08x}",
        f"META_SLOT_OFF=0x{PREGNANT_META_OFF:08x}",
        f"RUNTIME_FIT_SLOT_OFF=0x{PREGNANT_RUNTIME_OFF:08x}",
        f"RUNTIME_FIT_SIZE={len(runtime_fit)}",
        f"RUNTIME_FIT_SHA256={sha256_bytes(runtime_fit)}",
        f"PRODUCTION_SLOT_OFF=0x{PREGNANT_PRODUCTION_OFF:08x}",
        f"PRODUCTION_SIZE={len(production_itb)}",
        f"PRODUCTION_SHA256={sha256_bytes(production_itb)}",
        f"FIP_SLOT_OFF=0x{PREGNANT_FIP_OFF:08x}",
        f"FIP_SIZE={len(vanilla_fip)}",
        f"FIP_SHA256={sha256_bytes(vanilla_fip)}",
        f"PRELOADER_SLOT_OFF=0x{PREGNANT_PRELOADER_OFF:08x}",
        f"PRELOADER_SIZE={len(vanilla_preloader)}",
        f"PRELOADER_SHA256={sha256_bytes(vanilla_preloader)}",
        f"STOCK_BOOTLOADER_SHA256={str(evidence['bootloader_sha256']).lower()}",
        f"STOCK_MASTER_SHA256={str(evidence['master_sha256']).lower()}",
        f"STOCK_FLAGBACK_SHA256={str(evidence['flagback_sha256']).lower()}",
        f"STOCK_FLAG_TAIL_SHA256={str(evidence['flag_tail_sha256']).lower()}",
        f"STOCK_BOSA_SHA256={str(evidence['bosa_sha256']).lower()}",
        f"STOCK_RI_SHA256={str(evidence['ri_sha256']).lower()}",
    ]
    body = ("\n".join(fields) + "\n").encode("ascii")
    manifest_sha = sha256_bytes(body)
    manifest = body + f"META_SHA256={manifest_sha}\n".encode("ascii")
    if len(manifest) > PREGNANT_META_SIZE:
        raise RuntimeError("pregnant manifest exceeds reserved eraseblock")

    out = bytearray(base)
    out[PREGNANT_RUNTIME_OFF:PREGNANT_RUNTIME_OFF + PREGNANT_RUNTIME_WINDOW] = (
        runtime_fit + b"\0" * (PREGNANT_RUNTIME_WINDOW - len(runtime_fit))
    )
    out[PREGNANT_META_OFF:PREGNANT_META_OFF + PREGNANT_META_SIZE] = (
        manifest + b"\0" * (PREGNANT_META_SIZE - len(manifest))
    )
    out[PREGNANT_PRODUCTION_OFF:PREGNANT_PRODUCTION_OFF + PREGNANT_PRODUCTION_WINDOW] = (
        production_itb + b"\0" * (PREGNANT_PRODUCTION_WINDOW - len(production_itb))
    )
    out[PREGNANT_FIP_OFF:PREGNANT_FIP_OFF + PREGNANT_FIP_WINDOW] = (
        vanilla_fip + b"\0" * (PREGNANT_FIP_WINDOW - len(vanilla_fip))
    )
    out[PREGNANT_PRELOADER_OFF:PREGNANT_PRELOADER_OFF + PREGNANT_PRELOADER_WINDOW] = (
        vanilla_preloader + b"\0" * (PREGNANT_PRELOADER_WINDOW - len(vanilla_preloader))
    )

    # After the proven kernel wrapper, only the declared staging windows may
    # differ. They are raw bytes inside stock NT-FW, not required to be a FIT
    # image node. Active kernel/FDT are protected above.
    cursor = 0
    for _name, begin, size in sorted(reserved, key=lambda row: row[1]):
        if bytes(out[cursor:begin]) != base[cursor:begin]:
            raise RuntimeError("unexpected MD pregnant byte change outside declared staging windows")
        cursor = begin + size
    if bytes(out[cursor:]) != base[cursor:]:
        raise RuntimeError("unexpected MD pregnant byte change after declared staging windows")

    if fit_meta.get("fdt_data_offset") is not None:
        fdt_off = int(fit_meta["fdt_data_offset"])
        fdt_size = int(fit_meta["fdt_data_size"])
        if bytes(out[fdt_off:fdt_off + fdt_size]) != stock_slot[fdt_off:fdt_off + fdt_size]:
            raise RuntimeError("stock tcboot active FDT changed in MD pregnant wrapper")

    meta = dict(wrapper)
    meta.update({
        "wrapper_contract": "STOCK_FIP_HDR2_PROVEN_HANDOFF_NTFW_STAGING_V2",
        "candidate_sha256": sha256_bytes(bytes(out)),
        "runtime_offset": PREGNANT_RUNTIME_OFF,
        "runtime_size": len(runtime_fit),
        "runtime_sha256": sha256_bytes(runtime_fit),
        "runtime_ram_source_offset": runtime_ram_offset,
        "runtime_ram_destination": "0x92000000",
        "manifest_offset": PREGNANT_META_OFF,
        "manifest_size": len(manifest),
        "manifest_sha256": manifest_sha,
        "production_offset": PREGNANT_PRODUCTION_OFF,
        "production_size": len(production_itb),
        "production_sha256": sha256_bytes(production_itb),
        "fip_offset": PREGNANT_FIP_OFF,
        "fip_size": len(vanilla_fip),
        "fip_sha256": sha256_bytes(vanilla_fip),
        "preloader_offset": PREGNANT_PRELOADER_OFF,
        "preloader_size": len(vanilla_preloader),
        "preloader_sha256": sha256_bytes(vanilla_preloader),
        "stock_tcboot_fdt_byte_identical": True,
        "stock_fit_topology_preserved": True,
        "ntfw_staging_bounds_verified": True,
        "active_kernel_fdt_protected": True,
        "handoff_linux_image_size": len(patched_handoff),
        "destructive_stage2_embedded": True,
        "stock_evidence_embedded": True,
    })
    return bytes(out), meta


def build_pregnant_slot(
    stock_slot: bytes,
    runtime_fit: bytes,
    production_itb: bytes,
    vanilla_fip: bytes,
    vanilla_preloader: bytes,
    *,
    slot_size: int,
    evidence: dict,
    handoff_linux: bytes | None = None,
) -> tuple[bytes, dict]:
    """Build one stock-bootable SLOT2 carrying the complete autonomous migration.

    MD uses the hardware-proven stock FIT -> Linux Image shim -> transient
    UrsusBoot handoff. MF retains the generic path until its stock wrapper is
    proven independently on hardware.
    production/FIP/preloader children are stored at erase-aligned fixed offsets
    in the same stock SLOT2 and are read back by Linux through the nsb_slave
    alias before any destructive operation.
    """
    runtime = source_fit_contract(runtime_fit)
    if len(runtime_fit) != int(runtime["fit_total_size"]):
        raise RuntimeError("pregnant runtime must contain exactly one FIT with no untracked tail")
    if len(production_itb) < 40 or struct.unpack_from(">I", production_itb, 0)[0] != FDT_MAGIC:
        raise RuntimeError("pinned production child is not a FIT image")
    if len(production_itb) > PREGNANT_PRODUCTION_WINDOW:
        raise RuntimeError("pinned production child exceeds reserved SLOT2 window")
    if len(vanilla_fip) < 16 or vanilla_fip[:8] != FIP_MAGIC:
        raise RuntimeError("Vanilla FIP magic mismatch")
    if len(vanilla_fip) > 0x00100000 or len(vanilla_fip) > PREGNANT_FIP_WINDOW:
        raise RuntimeError("Vanilla FIP exceeds allowed carrier/canonical volume size")
    if not vanilla_preloader or len(vanilla_preloader) > 129024 or len(vanilla_preloader) > PREGNANT_PRELOADER_WINDOW:
        raise RuntimeError("Vanilla preloader does not fit BL2/carrier constraints")
    required_evidence = (
        "family", "profile", "bootloader_sha256", "master_sha256",
        "flagback_sha256", "flag_tail_sha256", "bosa_sha256", "ri_sha256",
    )
    for key in required_evidence:
        if key not in evidence:
            raise RuntimeError(f"missing stock evidence field: {key}")
    for key in required_evidence[2:]:
        value = str(evidence[key]).lower()
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise RuntimeError(f"invalid stock evidence SHA256: {key}")

    if str(evidence.get("family")) == "md":
        if handoff_linux is None:
            raise RuntimeError("MD pregnant payload is missing the proven stock handoff Linux Image")
        return _build_md_proven_pregnant_slot(
            stock_slot,
            handoff_linux,
            runtime_fit,
            production_itb,
            vanilla_fip,
            vanilla_preloader,
            slot_size=slot_size,
            evidence=evidence,
        )
    if len(runtime_fit) != int(runtime["fit_total_size"]):
        raise RuntimeError("pregnant runtime must contain exactly one FIT with no untracked tail")
    if len(production_itb) < 40 or struct.unpack_from(">I", production_itb, 0)[0] != FDT_MAGIC:
        raise RuntimeError("pinned production child is not a FIT image")
    if len(vanilla_fip) < 16 or vanilla_fip[:8] != FIP_MAGIC:
        raise RuntimeError("Vanilla FIP magic mismatch")
    if not vanilla_preloader or len(vanilla_preloader) > 129024:
        raise RuntimeError("Vanilla preloader does not fit the 128 KiB BL2 image after the 0x800 prefix")
    if len(production_itb) > PREGNANT_PRODUCTION_WINDOW:
        raise RuntimeError("pinned production child exceeds reserved SLOT2 window")
    if len(vanilla_fip) > 0x00100000:
        raise RuntimeError("Vanilla FIP exceeds canonical 1 MiB UBI volume")
    if len(vanilla_fip) > PREGNANT_FIP_WINDOW:
        raise RuntimeError("Vanilla FIP exceeds reserved SLOT2 window")
    if len(vanilla_preloader) > PREGNANT_PRELOADER_WINDOW:
        raise RuntimeError("Vanilla preloader exceeds reserved SLOT2 window")

    required_evidence = (
        "family",
        "profile",
        "bootloader_sha256",
        "master_sha256",
        "flagback_sha256",
        "flag_tail_sha256",
        "bosa_sha256",
        "ri_sha256",
    )
    for key in required_evidence:
        if key not in evidence:
            raise RuntimeError(f"missing stock evidence field: {key}")
    for key in required_evidence[2:]:
        value = str(evidence[key]).lower()
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise RuntimeError(f"invalid stock evidence SHA256: {key}")

    base, wrapper = build_installer_slot(stock_slot, runtime_fit, slot_size=slot_size)
    runtime_off = int(wrapper["inner_fit_offset"])
    runtime_size = len(runtime_fit)
    reserved = [
        ("manifest", PREGNANT_META_OFF, PREGNANT_META_SIZE),
        ("production", PREGNANT_PRODUCTION_OFF, PREGNANT_PRODUCTION_WINDOW),
        ("fip", PREGNANT_FIP_OFF, PREGNANT_FIP_WINDOW),
        ("preloader", PREGNANT_PRELOADER_OFF, PREGNANT_PRELOADER_WINDOW),
    ]
    for name, off, size in reserved:
        if off % 0x20000 or size % 0x20000 or off < 0 or off + size > slot_size:
            raise RuntimeError(f"unsafe pregnant SLOT2 region {name}: off={off:#x} size={size:#x}")
        if _pregnant_overlap(runtime_off, runtime_size, off, size):
            raise RuntimeError(f"runtime FIT overlaps reserved pregnant SLOT2 region: {name}")
    for i, (name_a, off_a, size_a) in enumerate(reserved):
        for name_b, off_b, size_b in reserved[i + 1:]:
            if _pregnant_overlap(off_a, size_a, off_b, size_b):
                raise RuntimeError(f"pregnant SLOT2 regions overlap: {name_a}/{name_b}")

    fields = [
        "URSUS_PREGNANT_V1",
        f"FAMILY={evidence['family']}",
        f"PROFILE={evidence['profile']}",
        f"SLOT_SIZE=0x{slot_size:08x}",
        f"META_SLOT_OFF=0x{PREGNANT_META_OFF:08x}",
        f"RUNTIME_FIT_SIZE={runtime_size}",
        f"RUNTIME_FIT_SHA256={sha256_bytes(runtime_fit)}",
        f"PRODUCTION_SLOT_OFF=0x{PREGNANT_PRODUCTION_OFF:08x}",
        f"PRODUCTION_SIZE={len(production_itb)}",
        f"PRODUCTION_SHA256={sha256_bytes(production_itb)}",
        f"FIP_SLOT_OFF=0x{PREGNANT_FIP_OFF:08x}",
        f"FIP_SIZE={len(vanilla_fip)}",
        f"FIP_SHA256={sha256_bytes(vanilla_fip)}",
        f"PRELOADER_SLOT_OFF=0x{PREGNANT_PRELOADER_OFF:08x}",
        f"PRELOADER_SIZE={len(vanilla_preloader)}",
        f"PRELOADER_SHA256={sha256_bytes(vanilla_preloader)}",
        f"STOCK_BOOTLOADER_SHA256={str(evidence['bootloader_sha256']).lower()}",
        f"STOCK_MASTER_SHA256={str(evidence['master_sha256']).lower()}",
        f"STOCK_FLAGBACK_SHA256={str(evidence['flagback_sha256']).lower()}",
        f"STOCK_FLAG_TAIL_SHA256={str(evidence['flag_tail_sha256']).lower()}",
        f"STOCK_BOSA_SHA256={str(evidence['bosa_sha256']).lower()}",
        f"STOCK_RI_SHA256={str(evidence['ri_sha256']).lower()}",
    ]
    body = ("\n".join(fields) + "\n").encode("ascii")
    manifest_sha = sha256_bytes(body)
    manifest = body + f"META_SHA256={manifest_sha}\n".encode("ascii")
    if len(manifest) > PREGNANT_META_SIZE:
        raise RuntimeError("pregnant manifest exceeds reserved eraseblock")

    out = bytearray(base)
    out[PREGNANT_META_OFF:PREGNANT_META_OFF + PREGNANT_META_SIZE] = (
        manifest + b"\0" * (PREGNANT_META_SIZE - len(manifest))
    )
    out[PREGNANT_PRODUCTION_OFF:PREGNANT_PRODUCTION_OFF + len(production_itb)] = production_itb
    out[PREGNANT_FIP_OFF:PREGNANT_FIP_OFF + len(vanilla_fip)] = vanilla_fip
    out[PREGNANT_PRELOADER_OFF:PREGNANT_PRELOADER_OFF + len(vanilla_preloader)] = vanilla_preloader

    if bytes(out[PREGNANT_PRODUCTION_OFF:PREGNANT_PRODUCTION_OFF + len(production_itb)]) != production_itb:
        raise RuntimeError("production child changed during SLOT2 assembly")
    if bytes(out[PREGNANT_FIP_OFF:PREGNANT_FIP_OFF + len(vanilla_fip)]) != vanilla_fip:
        raise RuntimeError("Vanilla FIP changed during SLOT2 assembly")
    if bytes(out[PREGNANT_PRELOADER_OFF:PREGNANT_PRELOADER_OFF + len(vanilla_preloader)]) != vanilla_preloader:
        raise RuntimeError("Vanilla preloader changed during SLOT2 assembly")

    meta = dict(wrapper)
    meta.update({
        "wrapper_contract": "STOCK_FIP_HDR2_PREGNANT_UBI_RECOVERY_V1",
        "candidate_sha256": sha256_bytes(bytes(out)),
        "manifest_offset": PREGNANT_META_OFF,
        "manifest_size": len(manifest),
        "manifest_sha256": manifest_sha,
        "runtime_fit_offset": runtime_off,
        "runtime_fit_size": runtime_size,
        "runtime_fit_sha256": sha256_bytes(runtime_fit),
        "production_offset": PREGNANT_PRODUCTION_OFF,
        "production_size": len(production_itb),
        "production_sha256": sha256_bytes(production_itb),
        "fip_offset": PREGNANT_FIP_OFF,
        "fip_size": len(vanilla_fip),
        "fip_sha256": sha256_bytes(vanilla_fip),
        "preloader_offset": PREGNANT_PRELOADER_OFF,
        "preloader_size": len(vanilla_preloader),
        "preloader_sha256": sha256_bytes(vanilla_preloader),
        "destructive_stage2_embedded": True,
        "stock_evidence_embedded": True,
    })
    return bytes(out), meta

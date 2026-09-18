#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import struct

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

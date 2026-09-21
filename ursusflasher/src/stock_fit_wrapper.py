#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import struct


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_linux_image(data: bytes) -> dict:
    if len(data) < 64:
        raise RuntimeError("TRANSITION Linux Image handoff is too short")
    text_offset = struct.unpack_from("<Q", data, 8)[0]
    image_size = struct.unpack_from("<Q", data, 16)[0]
    flags = struct.unpack_from("<Q", data, 24)[0]
    magic = struct.unpack_from("<I", data, 56)[0]
    if magic != 0x644D5241:
        raise RuntimeError(f"TRANSITION Linux Image magic mismatch: {magic:#x}")
    if text_offset != 0 or image_size != len(data):
        raise RuntimeError(
            f"TRANSITION Linux Image header mismatch: text_offset={text_offset:#x} "
            f"image_size={image_size:#x} actual={len(data):#x}"
        )
    if flags != 0:
        raise RuntimeError(f"TRANSITION Linux Image flags are unexpected: {flags:#x}")
    # Payload identity is already pinned by TRANSITION2.json + SHA256 and the
    # mode/board/stock_inner_format metadata in stock_ab_transition._load_payload().
    # Do not require arbitrary printable strings inside BL33: the TEST61 Web
    # control build intentionally removed the old OFFICIAL_OPENWRT marker.
    return {"size": len(data), "text_offset": text_offset, "image_size": image_size, "flags": flags}


def fip_nt_fw(slot: bytes, *, slot_size: int, nt_fw_uuid: bytes) -> tuple[int, int]:
    if len(slot) != slot_size:
        raise RuntimeError(f"nsb_slave size mismatch: {len(slot):#x} != {slot_size:#x}")
    if slot[:8] != bytes.fromhex("010064aa78563412"):
        raise RuntimeError("nsb_slave has no stock Airoha FIP header")
    pos = 16
    while pos + 40 <= len(slot):
        uuid = slot[pos:pos + 16]
        if uuid == b"\0" * 16:
            break
        off, size, _flags = struct.unpack_from("<QQQ", slot, pos + 16)
        if uuid == nt_fw_uuid:
            if off + size > len(slot) or size <= 0x100:
                raise RuntimeError("stock NT-FW range is invalid")
            return int(off), int(size)
        pos += 40
    raise RuntimeError("stock nsb_slave has no Nokia NT-FW FIP entry")


def fit_props(slot: bytes, fit_off: int, nt_size: int) -> tuple[dict[str, tuple[int, int]], dict]:
    if fit_off + 40 > len(slot):
        raise RuntimeError("stock FIT header is truncated")
    hdr = struct.unpack_from(">10I", slot, fit_off)
    magic, total, off_struct, off_strings, _off_mem, version, last_comp, _bootcpu, size_strings, size_struct = hdr
    if magic != 0xD00DFEED or version < 17 or last_comp > version:
        raise RuntimeError("stock inner image is not a supported FIT/FDT")
    nt_payload = nt_size - 0x100
    if total < 40 or total > nt_payload or fit_off + total > len(slot):
        raise RuntimeError(
            f"stock FIT range is invalid: fit={total:#x} nt_payload={nt_payload:#x}"
        )
    struct_start = fit_off + off_struct
    struct_end = struct_start + size_struct
    strings_start = fit_off + off_strings
    strings_end = strings_start + size_strings
    if not (fit_off <= struct_start <= struct_end <= fit_off + total):
        raise RuntimeError("stock FIT structure block is out of range")
    if not (fit_off <= strings_start <= strings_end <= fit_off + total):
        raise RuntimeError("stock FIT strings block is out of range")
    strings = slot[strings_start:strings_end]
    props: dict[str, tuple[int, int]] = {}
    path: list[str] = []
    p = struct_start

    def align4(v: int) -> int:
        return (v + 3) & ~3

    while p + 4 <= struct_end:
        token = struct.unpack_from(">I", slot, p)[0]
        p += 4
        if token == 1:
            try:
                end = slot.index(0, p, struct_end)
            except ValueError as exc:
                raise RuntimeError("unterminated FIT node name") from exc
            path.append(slot[p:end].decode("ascii", "strict"))
            p = align4(end + 1)
        elif token == 2:
            if not path:
                raise RuntimeError("unbalanced FIT END_NODE")
            path.pop()
        elif token == 3:
            if p + 8 > struct_end:
                raise RuntimeError("truncated FIT property header")
            length, nameoff = struct.unpack_from(">II", slot, p)
            p += 8
            value_off = p
            p = align4(p + length)
            if p > struct_end or nameoff >= len(strings):
                raise RuntimeError("FIT property range is invalid")
            end = strings.find(b"\0", nameoff)
            if end < 0:
                raise RuntimeError("unterminated FIT property name")
            name = strings[nameoff:end].decode("ascii", "strict")
            key = "/" + "/".join(x for x in path if x) + "/" + name
            props[key] = (value_off, int(length))
        elif token == 4:
            continue
        elif token == 9:
            break
        else:
            raise RuntimeError(f"unsupported/corrupt FIT token: {token:#x}")
    return props, {"total_size": total, "fit_offset": fit_off}


def prop(slot: bytes, props: dict[str, tuple[int, int]], key: str) -> bytes:
    try:
        off, size = props[key]
    except KeyError as exc:
        raise RuntimeError(f"required stock FIT property is missing: {key}") from exc
    return slot[off:off + size]


def image_data_range(
    slot: bytes,
    props: dict[str, tuple[int, int]],
    node: str,
    *,
    fit_off: int,
    fit_total: int,
    nt_end: int,
) -> tuple[int, int]:
    base = f"/images/{node}"
    inline = f"{base}/data"
    if inline in props:
        off, size = props[inline]
    else:
        size_raw = prop(slot, props, f"{base}/data-size")
        if len(size_raw) != 4:
            raise RuntimeError(f"{node} data-size has unexpected length")
        size = struct.unpack(">I", size_raw)[0]
        if f"{base}/data-position" in props:
            pos_raw = prop(slot, props, f"{base}/data-position")
            if len(pos_raw) != 4:
                raise RuntimeError(f"{node} data-position has unexpected length")
            off = fit_off + struct.unpack(">I", pos_raw)[0]
        elif f"{base}/data-offset" in props:
            off_raw = prop(slot, props, f"{base}/data-offset")
            if len(off_raw) != 4:
                raise RuntimeError(f"{node} data-offset has unexpected length")
            external_base = (fit_off + fit_total + 3) & ~3
            off = external_base + struct.unpack(">I", off_raw)[0]
        else:
            raise RuntimeError(f"{node} has neither inline data nor external data reference")
    if size <= 0 or off < fit_off or off + size > nt_end:
        raise RuntimeError(
            f"{node} data range is outside stock NT-FW payload: off={off:#x} size={size:#x} nt_end={nt_end:#x}"
        )
    return int(off), int(size)


def stock_fit_contract(stock_slot: bytes, nt_off: int, nt_size: int) -> tuple[dict[str, tuple[int, int]], dict]:
    fit_off = nt_off + 0x100
    props, meta = fit_props(stock_slot, fit_off, nt_size)
    expected = {
        "/images/kernel@1/type": b"kernel\0",
        "/images/kernel@1/arch": b"arm64\0",
        "/images/kernel@1/os": b"linux\0",
        "/images/kernel@1/hash@1/algo": b"sha1\0",
        "/configurations/default": b"conf@1\0",
        "/configurations/conf@1/kernel": b"kernel@1\0",
        "/configurations/conf@1/fdt": b"fdt@1\0",
        "/configurations/conf@1/filesystem": b"filesystem@1\0",
    }
    for key, value in expected.items():
        got = prop(stock_slot, props, key)
        if got != value:
            raise RuntimeError(f"unexpected stock FIT property {key}: {got!r} != {value!r}")

    stock_compression = prop(stock_slot, props, "/images/kernel@1/compression")
    if stock_compression not in (b"none\0", b"lzma\0"):
        raise RuntimeError(
            "unsupported stock FIT kernel compression: "
            f"{stock_compression!r}; expected b'none\\x00' or b'lzma\\x00'"
        )

    load = struct.unpack(">I", prop(stock_slot, props, "/images/kernel@1/load"))[0]
    entry = struct.unpack(">I", prop(stock_slot, props, "/images/kernel@1/entry"))[0]
    if load != 0x80088000 or entry != 0x80088000:
        raise RuntimeError(f"unexpected stock kernel load/entry: {load:#x}/{entry:#x}")
    nt_end = nt_off + nt_size
    kernel_off, kernel_len = image_data_range(
        stock_slot, props, "kernel@1",
        fit_off=fit_off, fit_total=meta["total_size"], nt_end=nt_end,
    )
    fdt_off, fdt_len = image_data_range(
        stock_slot, props, "fdt@1",
        fit_off=fit_off, fit_total=meta["total_size"], nt_end=nt_end,
    )
    fs_off, fs_len = image_data_range(
        stock_slot, props, "filesystem@1",
        fit_off=fit_off, fit_total=meta["total_size"], nt_end=nt_end,
    )
    fdt_data = stock_slot[fdt_off:fdt_off + fdt_len]
    fs_data = stock_slot[fs_off:fs_off + fs_len]
    if not fdt_data.startswith(bytes.fromhex("d00dfeed")):
        raise RuntimeError("stock fdt@1 data is not an FDT")
    if not fs_data.startswith(b"hsqs"):
        raise RuntimeError("stock filesystem@1 is not SquashFS")
    if struct.unpack_from("<I", stock_slot, nt_off + 0x08)[0] != nt_size:
        raise RuntimeError("HDR2 NT-FW size does not match FIP entry")
    if struct.unpack_from("<I", stock_slot, nt_off + 0x50)[0] != kernel_len:
        raise RuntimeError("HDR2 kernel size does not match stock FIT kernel@1 data")
    if struct.unpack_from("<I", stock_slot, nt_off + 0x54)[0] != len(fs_data):
        raise RuntimeError("HDR2 filesystem size does not match stock FIT filesystem@1 data")
    meta.update({
        "kernel_data_offset": kernel_off,
        "kernel_data_size": kernel_len,
        "filesystem_data_offset": fs_off,
        "filesystem_data_size": len(fs_data),
        "fdt_data_offset": fdt_off,
        "fdt_data_size": len(fdt_data),
        "fit_trailing_payload_size": (nt_size - 0x100) - meta["total_size"],
        "kernel_load": load,
        "kernel_entry": entry,
        "stock_kernel_compression": stock_compression.rstrip(b"\0").decode("ascii"),
    })
    return props, meta


def build_transition_slot(stock_slot: bytes, linux_image: bytes, *, slot_size: int, nt_fw_uuid: bytes) -> tuple[bytes, dict]:
    validate_linux_image(linux_image)
    nt_off, nt_size = fip_nt_fw(stock_slot, slot_size=slot_size, nt_fw_uuid=nt_fw_uuid)
    if stock_slot[nt_off:nt_off + 4] != b"HDR2":
        raise RuntimeError(f"stock NT-FW does not start with HDR2 at {nt_off:#x}")
    props, fit_meta = stock_fit_contract(stock_slot, nt_off, nt_size)
    kernel_off = fit_meta["kernel_data_offset"]
    kernel_size = fit_meta["kernel_data_size"]
    if len(linux_image) > kernel_size:
        raise RuntimeError(f"TRANSITION Linux Image does not fit stock kernel@1: {len(linux_image)} > {kernel_size}")

    kernel = linux_image + (b"\0" * (kernel_size - len(linux_image)))
    out = bytearray(stock_slot)
    out[kernel_off:kernel_off + kernel_size] = kernel
    comp_off, comp_len = props["/images/kernel@1/compression"]
    if comp_len != 5:
        raise RuntimeError("stock kernel compression property length is unexpected")
    out[comp_off:comp_off + comp_len] = b"none\0"
    hash_off, hash_len = props["/images/kernel@1/hash@1/value"]
    if hash_len != 20:
        raise RuntimeError("stock kernel SHA1 property length is unexpected")
    out[hash_off:hash_off + hash_len] = hashlib.sha1(kernel).digest()

    if bytes(out[:nt_off + 0x100]) != stock_slot[:nt_off + 0x100]:
        raise RuntimeError("stock FIP/HDR2 preservation invariant failed")
    for label, off_key, size_key in (
        ("fdt@1", "fdt_data_offset", "fdt_data_size"),
        ("filesystem@1", "filesystem_data_offset", "filesystem_data_size"),
    ):
        off = fit_meta[off_key]
        size = fit_meta[size_key]
        if bytes(out[off:off + size]) != stock_slot[off:off + size]:
            raise RuntimeError(f"stock FIT preservation invariant failed for {label}")
    allowed = sorted([
        (kernel_off, kernel_off + kernel_size),
        (comp_off, comp_off + comp_len),
        (hash_off, hash_off + hash_len),
    ])
    cursor = 0
    for begin, end in allowed:
        if bytes(out[cursor:begin]) != stock_slot[cursor:begin]:
            raise RuntimeError("unexpected bytes changed outside TRANSITION kernel FIT fields")
        cursor = end
    if bytes(out[cursor:]) != stock_slot[cursor:]:
        raise RuntimeError("unexpected bytes changed after TRANSITION kernel FIT fields")

    return bytes(out), {
        "wrapper_contract": "STOCK_FIP_HDR2_FIT_LINUX_KERNEL_HANDOFF",
        "slot_size": len(out),
        "nt_fw_offset": nt_off,
        "nt_fw_size": nt_size,
        "fit_offset": fit_meta["fit_offset"],
        "fit_total_size": fit_meta["total_size"],
        "fit_trailing_payload_size": fit_meta["fit_trailing_payload_size"],
        "kernel_data_size": kernel_size,
        "transition_linux_image_size": len(linux_image),
        "transition_kernel_padding": kernel_size - len(linux_image),
        "kernel_load": fit_meta["kernel_load"],
        "kernel_entry": fit_meta["kernel_entry"],
        "stock_kernel_compression": fit_meta["stock_kernel_compression"],
        "transition_kernel_compression": "none",
        "filesystem_data_size": fit_meta["filesystem_data_size"],
        "fdt_data_size": fit_meta["fdt_data_size"],
        "stock_sha256": sha256_bytes(stock_slot),
        "candidate_sha256": sha256_bytes(bytes(out)),
        "kernel_sha1": hashlib.sha1(kernel).hexdigest(),
        "outer_fip_hdr2_byte_identical": True,
        "stock_fdt_byte_identical": True,
        "stock_filesystem_byte_identical": True,
    }

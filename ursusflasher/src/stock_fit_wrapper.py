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


def fip_nt_fw(slot: bytes, *, slot_size: int, nt_fw_uuid: bytes | None = None) -> tuple[int, int]:
    """Resolve the unique stock boot payload by structure, not by OEM UUID.

    nt_fw_uuid is accepted for API compatibility but intentionally ignored.
    The safe invariant is that exactly one in-range FIP entry contains the
    stock HDR2 wrapper followed by a valid FIT/FDT header.
    """
    if len(slot) != slot_size:
        raise RuntimeError(f"nsb_slave size mismatch: {len(slot):#x} != {slot_size:#x}")
    if slot[:8] != bytes.fromhex("010064aa78563412"):
        raise RuntimeError("nsb_slave has no stock Airoha FIP header")
    candidates: list[tuple[int, int]] = []
    pos = 16
    while pos + 40 <= len(slot):
        uuid = slot[pos:pos + 16]
        if uuid == b"\0" * 16:
            break
        off, size, _flags = struct.unpack_from("<QQQ", slot, pos + 16)
        off = int(off); size = int(size)
        if (
            size > 0x100
            and 0 <= off < off + size <= len(slot)
            and slot[off:off + 4] == b"HDR2"
            and off + 0x104 <= len(slot)
            and struct.unpack_from(">I", slot, off + 0x100)[0] == 0xD00DFEED
        ):
            candidates.append((off, size))
        pos += 40
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one in-range HDR2/FIT boot payload, got {len(candidates)}")
    return candidates[0]


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


def _cstring(slot: bytes, props: dict[str, tuple[int, int]], key: str) -> str:
    return prop(slot, props, key).split(b"\0", 1)[0].decode("ascii", "strict")


def selected_fit_nodes(slot: bytes, props: dict[str, tuple[int, int]]) -> dict:
    """Resolve the active FIT config without assuming optional references."""
    config_names = sorted({
        key[len("/configurations/"):].split("/", 1)[0]
        for key in props
        if key.startswith("/configurations/") and "/" in key[len("/configurations/"):]
    })
    default = None
    if "/configurations/default" in props:
        default = _cstring(slot, props, "/configurations/default")
    if not default:
        usable = [
            name for name in config_names
            if f"/configurations/{name}/kernel" in props
        ]
        if len(usable) != 1:
            raise RuntimeError(f"cannot resolve one active stock FIT configuration: {usable}")
        default = usable[0]

    base = f"/configurations/{default}"
    kernel_key = f"{base}/kernel"
    if kernel_key not in props:
        raise RuntimeError("active stock FIT config lacks kernel reference")
    kernel = _cstring(slot, props, kernel_key)
    if not kernel:
        raise RuntimeError("active stock FIT kernel reference is empty")

    out = {"config": default, "kernel": kernel}
    for role in ("fdt", "filesystem"):
        key = f"{base}/{role}"
        if key in props:
            value = _cstring(slot, props, key)
            if value:
                out[role] = value
    return out


def image_nodes(props: dict[str, tuple[int, int]]) -> list[str]:
    return sorted({
        key[len("/images/"):].split("/", 1)[0]
        for key in props
        if key.startswith("/images/") and "/" in key[len("/images/"):]
    })


def image_ranges(
    slot: bytes,
    props: dict[str, tuple[int, int]],
    *,
    fit_off: int,
    fit_total: int,
    nt_end: int,
) -> list[dict]:
    """Return every image node with a valid, in-range payload span."""
    out = []
    for node in image_nodes(props):
        try:
            off, size = image_data_range(
                slot, props, node,
                fit_off=fit_off, fit_total=fit_total, nt_end=nt_end,
            )
        except RuntimeError:
            continue
        out.append({"node": node, "offset": off, "size": size, "end": off + size})
    return out


def unique_covering_image(
    slot: bytes,
    props: dict[str, tuple[int, int]],
    *,
    fit_off: int,
    fit_total: int,
    nt_end: int,
    begin: int,
    end: int,
    exclude_nodes: tuple[str, ...] = (),
) -> dict:
    """Find the unique image payload that physically contains a required span."""
    candidates = [
        item for item in image_ranges(
            slot, props, fit_off=fit_off, fit_total=fit_total, nt_end=nt_end
        )
        if item["node"] not in exclude_nodes
        and int(item["offset"]) <= begin < end <= int(item["end"])
    ]
    if len(candidates) != 1:
        summary = [(x["node"], hex(int(x["offset"])), hex(int(x["end"]))) for x in candidates]
        raise RuntimeError(
            f"required carrier span {begin:#x}..{end:#x} is not covered by exactly one stock FIT image: {summary}"
        )
    return candidates[0]


def kernel_hash_fields(slot: bytes, props: dict[str, tuple[int, int]], kernel_node: str) -> list[dict]:
    """Resolve writable kernel digest fields without assuming node names."""
    prefix = f"/images/{kernel_node}/"
    nodes: dict[str, dict[str, str]] = {}
    for key in props:
        if not key.startswith(prefix):
            continue
        rest = key[len(prefix):]
        parts = rest.split("/", 1)
        if len(parts) != 2 or not parts[0].startswith("hash"):
            continue
        node, name = parts
        if name in ("algo", "value"):
            nodes.setdefault(node, {})[name] = key

    out: list[dict] = []
    for node, fields in sorted(nodes.items()):
        value_key = fields.get("value")
        if not value_key:
            continue
        value_off, value_len = props[value_key]
        algo = None
        algo_key = fields.get("algo")
        if algo_key:
            raw = prop(slot, props, algo_key).rstrip(b"\0")
            if raw == b"sha1":
                algo = "sha1"
            elif raw == b"sha256":
                algo = "sha256"
            else:
                # Unknown hash metadata does not authorize changing its value.
                # Preserve it byte-for-byte instead of rejecting the whole FIT.
                continue
        elif value_len == 20:
            algo = "sha1"
        elif value_len == 32:
            algo = "sha256"
        else:
            continue
        expected_len = 20 if algo == "sha1" else 32
        if value_len != expected_len:
            continue
        out.append({
            "node": node,
            "algorithm": algo,
            "value_offset": int(value_off),
            "value_size": int(value_len),
            "algo_present": bool(algo_key),
        })
    return out


def stock_fit_contract(stock_slot: bytes, nt_off: int, nt_size: int) -> tuple[dict[str, tuple[int, int]], dict]:
    fit_off = nt_off + 0x100
    props, meta = fit_props(stock_slot, fit_off, nt_size)
    nodes = selected_fit_nodes(stock_slot, props)
    kernel_node = str(nodes["kernel"])
    nt_end = nt_off + nt_size

    kernel_off, kernel_len = image_data_range(
        stock_slot, props, kernel_node,
        fit_off=fit_off, fit_total=meta["total_size"], nt_end=nt_end,
    )

    fdt_node = nodes.get("fdt")
    fdt_off = fdt_len = None
    fdt_magic_ok = None
    if fdt_node:
        try:
            fdt_off, fdt_len = image_data_range(
                stock_slot, props, str(fdt_node),
                fit_off=fit_off, fit_total=meta["total_size"], nt_end=nt_end,
            )
            fdt_magic_ok = stock_slot[fdt_off:fdt_off + min(fdt_len,4)] == bytes.fromhex("d00dfeed")
        except RuntimeError:
            fdt_node = None
            fdt_off = fdt_len = None

    kbase = f"/images/{kernel_node}"
    compression_key = f"{kbase}/compression"
    if compression_key in props:
        stock_compression = prop(stock_slot, props, compression_key).rstrip(b"\0").decode("ascii", "replace")
    else:
        stock_compression = "none"

    def optional_u32(key: str):
        if key not in props:
            return None
        raw = prop(stock_slot, props, key)
        return struct.unpack(">I", raw)[0] if len(raw) == 4 else None

    hdr2_nt_size = struct.unpack_from("<I", stock_slot, nt_off + 0x08)[0] if nt_off + 0x0c <= len(stock_slot) else None
    hdr2_kernel_size = struct.unpack_from("<I", stock_slot, nt_off + 0x50)[0] if nt_off + 0x54 <= len(stock_slot) else None
    hdr2_filesystem_size = struct.unpack_from("<I", stock_slot, nt_off + 0x54)[0] if nt_off + 0x58 <= len(stock_slot) else None

    meta.update({
        "config_node": nodes["config"],
        "kernel_node": kernel_node,
        "fdt_node": fdt_node,
        "filesystem_node": nodes.get("filesystem"),
        "kernel_data_offset": kernel_off,
        "kernel_data_size": kernel_len,
        "fdt_data_offset": fdt_off,
        "fdt_data_size": fdt_len,
        "fit_trailing_payload_size": (nt_size - 0x100) - meta["total_size"],
        "kernel_load": optional_u32(f"{kbase}/load"),
        "kernel_entry": optional_u32(f"{kbase}/entry"),
        "stock_kernel_compression": stock_compression,
        "compression_key": compression_key if compression_key in props else None,
        "kernel_hash_fields": kernel_hash_fields(stock_slot, props, kernel_node),
        "stock_fdt_magic_ok": fdt_magic_ok,
        "hdr2_nt_size": hdr2_nt_size,
        "hdr2_kernel_size": hdr2_kernel_size,
        "hdr2_filesystem_size": hdr2_filesystem_size,
        "image_ranges": image_ranges(
            stock_slot, props, fit_off=fit_off, fit_total=meta["total_size"], nt_end=nt_end
        ),
    })
    return props, meta



def build_md_proven_transition_slot(
    stock_slot: bytes,
    linux_image: bytes,
    *,
    slot_size: int,
    nt_fw_uuid: bytes | None = None,
) -> tuple[bytes, dict]:
    """Literal hardware-proven XG-040G-MD tcboot wrapper contract.

    Keep the exact TRANSITION2-visible FIT topology and mutate only
    kernel@1/data, kernel@1/compression and kernel@1/hash@1/value.
    """
    validate_linux_image(linux_image)
    nt_off, nt_size = fip_nt_fw(stock_slot, slot_size=slot_size, nt_fw_uuid=nt_fw_uuid)
    if stock_slot[nt_off:nt_off + 4] != b"HDR2":
        raise RuntimeError(f"stock NT-FW does not start with HDR2 at {nt_off:#x}")
    fit_off = nt_off + 0x100
    props, meta = fit_props(stock_slot, fit_off, nt_size)

    required = {
        "/images/kernel@1/type": b"kernel\0",
        "/images/kernel@1/arch": b"arm64\0",
        "/images/kernel@1/os": b"linux\0",
        "/images/kernel@1/hash@1/algo": b"sha1\0",
        "/configurations/default": b"conf@1\0",
        "/configurations/conf@1/kernel": b"kernel@1\0",
        "/configurations/conf@1/fdt": b"fdt@1\0",
        "/configurations/conf@1/filesystem": b"filesystem@1\0",
    }
    for key, value in required.items():
        got = prop(stock_slot, props, key)
        if got != value:
            raise RuntimeError(f"MD proven tcboot FIT contract mismatch for {key}: {got!r} != {value!r}")

    kernel_key = "/images/kernel@1/data"
    fdt_key = "/images/fdt@1/data"
    fs_key = "/images/filesystem@1/data"
    if kernel_key not in props or fdt_key not in props or fs_key not in props:
        raise RuntimeError("MD proven tcboot FIT requires inline kernel@1/fdt@1/filesystem@1 data")

    kernel_off, kernel_size = props[kernel_key]
    fdt_off, fdt_size = props[fdt_key]
    fs_off, fs_size = props[fs_key]
    if len(linux_image) > kernel_size:
        raise RuntimeError(
            f"TRANSITION Linux Image does not fit proven stock kernel@1 span: {len(linux_image)} > {kernel_size}"
        )
    if stock_slot[fdt_off:fdt_off + min(fdt_size, 4)] != bytes.fromhex("d00dfeed"):
        raise RuntimeError("MD proven stock fdt@1 data is not an FDT")
    if stock_slot[fs_off:fs_off + min(fs_size, 4)] != b"hsqs":
        raise RuntimeError("MD proven stock filesystem@1 is not SquashFS")

    comp_off, comp_len = props["/images/kernel@1/compression"]
    if comp_len != 5:
        raise RuntimeError("MD proven kernel@1 compression property length is not 5")
    hash_off, hash_len = props["/images/kernel@1/hash@1/value"]
    if hash_len != 20:
        raise RuntimeError("MD proven kernel@1 SHA1 field length is not 20")

    kernel = linux_image + (b"\0" * (kernel_size - len(linux_image)))
    out = bytearray(stock_slot)
    out[kernel_off:kernel_off + kernel_size] = kernel
    out[comp_off:comp_off + comp_len] = b"none\0"
    out[hash_off:hash_off + hash_len] = hashlib.sha1(kernel).digest()

    if bytes(out[:nt_off + 0x100]) != stock_slot[:nt_off + 0x100]:
        raise RuntimeError("MD proven FIP/HDR2 preservation invariant failed")
    if bytes(out[fdt_off:fdt_off + fdt_size]) != stock_slot[fdt_off:fdt_off + fdt_size]:
        raise RuntimeError("MD proven fdt@1 preservation invariant failed")
    if bytes(out[fs_off:fs_off + fs_size]) != stock_slot[fs_off:fs_off + fs_size]:
        raise RuntimeError("MD proven filesystem@1 preservation invariant failed")

    allowed = sorted([
        (kernel_off, kernel_off + kernel_size),
        (comp_off, comp_off + comp_len),
        (hash_off, hash_off + hash_len),
    ])
    cursor = 0
    for begin, end in allowed:
        if bytes(out[cursor:begin]) != stock_slot[cursor:begin]:
            raise RuntimeError("unexpected bytes changed outside proven MD TRANSITION2 FIT fields")
        cursor = end
    if bytes(out[cursor:]) != stock_slot[cursor:]:
        raise RuntimeError("unexpected bytes changed after proven MD TRANSITION2 FIT fields")

    generic_props, generic_meta = stock_fit_contract(stock_slot, nt_off, nt_size)
    return bytes(out), {
        "wrapper_contract": "MD_HW_PROVEN_TRANSITION2_LITERAL_FIT_V1",
        "slot_size": len(out),
        "nt_fw_offset": nt_off,
        "nt_fw_size": nt_size,
        "fit_offset": fit_off,
        "fit_total_size": meta["total_size"],
        "config_node": "conf@1",
        "kernel_node": "kernel@1",
        "fdt_node": "fdt@1",
        "filesystem_node": "filesystem@1",
        "kernel_data_offset": kernel_off,
        "kernel_data_size": kernel_size,
        "fdt_data_offset": fdt_off,
        "fdt_data_size": fdt_size,
        "filesystem_data_offset": fs_off,
        "filesystem_data_size": fs_size,
        "image_ranges": generic_meta["image_ranges"],
        "stock_sha256": sha256_bytes(stock_slot),
        "candidate_sha256": sha256_bytes(bytes(out)),
        "kernel_sha1": hashlib.sha1(kernel).hexdigest(),
        "outer_fip_hdr2_byte_identical": True,
        "stock_fdt_byte_identical": True,
        "stock_filesystem_byte_identical": True,
    }


def build_md_transition_slot(
    stock_slot: bytes,
    linux_image: bytes,
    *,
    slot_size: int,
    nt_fw_uuid: bytes | None = None,
) -> tuple[bytes, dict]:
    """Prefer the exact hardware-proven TRANSITION2 shape when present.

    Node names are not an applicability gate: non-matching stock revisions fall
    back to the generic structural builder.
    """
    nt_off, nt_size = fip_nt_fw(stock_slot, slot_size=slot_size, nt_fw_uuid=nt_fw_uuid)
    fit_off = nt_off + 0x100
    props, _meta = fit_props(stock_slot, fit_off, nt_size)
    proven = {
        "/configurations/default": b"conf@1\0",
        "/configurations/conf@1/kernel": b"kernel@1\0",
        "/configurations/conf@1/fdt": b"fdt@1\0",
        "/configurations/conf@1/filesystem": b"filesystem@1\0",
        "/images/kernel@1/hash@1/algo": b"sha1\0",
    }
    if all(key in props and prop(stock_slot, props, key) == value for key, value in proven.items()):
        return build_md_proven_transition_slot(
            stock_slot,
            linux_image,
            slot_size=slot_size,
            nt_fw_uuid=nt_fw_uuid,
        )
    return build_transition_slot(
        stock_slot,
        linux_image,
        slot_size=slot_size,
        nt_fw_uuid=nt_fw_uuid,
    )


def build_transition_slot(stock_slot: bytes, linux_image: bytes, *, slot_size: int, nt_fw_uuid: bytes | None = None) -> tuple[bytes, dict]:
    validate_linux_image(linux_image)
    nt_off, nt_size = fip_nt_fw(stock_slot, slot_size=slot_size, nt_fw_uuid=nt_fw_uuid)
    props, fit_meta = stock_fit_contract(stock_slot, nt_off, nt_size)
    kernel_off = int(fit_meta["kernel_data_offset"])
    kernel_size = int(fit_meta["kernel_data_size"])
    if len(linux_image) > kernel_size:
        raise RuntimeError(f"TRANSITION Linux Image does not fit active stock kernel span: {len(linux_image)} > {kernel_size}")

    kernel = linux_image + (b"\0" * (kernel_size - len(linux_image)))
    out = bytearray(stock_slot)
    out[kernel_off:kernel_off + kernel_size] = kernel

    allowed = [(kernel_off, kernel_off + kernel_size)]
    compression_key = fit_meta.get("compression_key")
    if compression_key:
        comp_off, comp_len = props[str(compression_key)]
        if comp_len < 5:
            raise RuntimeError("active stock kernel compression property cannot encode 'none'")
        comp_value = b"none\0" + (b"\0" * (comp_len - 5))
        out[comp_off:comp_off + comp_len] = comp_value
        allowed.append((comp_off, comp_off + comp_len))

    hash_fields = list(fit_meta.get("kernel_hash_fields") or [])
    for field in hash_fields:
        hash_off = int(field["value_offset"])
        hash_len = int(field["value_size"])
        algo = str(field["algorithm"])
        digest = hashlib.sha1(kernel).digest() if algo == "sha1" else hashlib.sha256(kernel).digest()
        if len(digest) != hash_len:
            raise RuntimeError(f"resolved kernel hash length mismatch: {algo}/{hash_len}")
        out[hash_off:hash_off + hash_len] = digest
        allowed.append((hash_off, hash_off + hash_len))

    # True safety invariant: only the active kernel payload and the existing
    # metadata fields needed to describe that payload may change.
    allowed = sorted(allowed)
    cursor = 0
    for begin, end in allowed:
        if begin < cursor:
            raise RuntimeError("overlapping writable FIT spans")
        if bytes(out[cursor:begin]) != stock_slot[cursor:begin]:
            raise RuntimeError("unexpected bytes changed outside active kernel FIT spans")
        cursor = end
    if bytes(out[cursor:]) != stock_slot[cursor:]:
        raise RuntimeError("unexpected bytes changed after active kernel FIT spans")

    return bytes(out), {
        "wrapper_contract": "STOCK_FIP_HDR2_FIT_ACTIVE_KERNEL_HANDOFF",
        "slot_size": len(out),
        "nt_fw_offset": nt_off,
        "nt_fw_size": nt_size,
        "fit_offset": fit_meta["fit_offset"],
        "fit_total_size": fit_meta["total_size"],
        "fit_trailing_payload_size": fit_meta["fit_trailing_payload_size"],
        "config_node": fit_meta["config_node"],
        "kernel_node": fit_meta["kernel_node"],
        "fdt_node": fit_meta.get("fdt_node"),
        "filesystem_node": fit_meta.get("filesystem_node"),
        "kernel_data_size": kernel_size,
        "transition_linux_image_size": len(linux_image),
        "transition_kernel_padding": kernel_size - len(linux_image),
        "kernel_load": fit_meta["kernel_load"],
        "kernel_entry": fit_meta["kernel_entry"],
        "stock_kernel_compression": fit_meta["stock_kernel_compression"],
        "transition_kernel_compression": "none",
        "fdt_data_size": fit_meta.get("fdt_data_size"),
        "stock_fdt_magic_ok": fit_meta.get("stock_fdt_magic_ok"),
        "hdr2_nt_size": fit_meta["hdr2_nt_size"],
        "hdr2_kernel_size": fit_meta["hdr2_kernel_size"],
        "hdr2_filesystem_size": fit_meta["hdr2_filesystem_size"],
        "stock_sha256": sha256_bytes(stock_slot),
        "candidate_sha256": sha256_bytes(bytes(out)),
        "kernel_hashes": [
            {
                "node": field["node"],
                "algorithm": field["algorithm"],
                "digest": (
                    hashlib.sha1(kernel).hexdigest()
                    if field["algorithm"] == "sha1"
                    else hashlib.sha256(kernel).hexdigest()
                ),
                "algo_present": field["algo_present"],
            }
            for field in hash_fields
        ],
        "outer_fip_hdr2_byte_identical": bytes(out[:nt_off + 0x100]) == stock_slot[:nt_off + 0x100],
        "stock_fdt_byte_identical": (
            True if fit_meta.get("fdt_data_offset") is None
            else bytes(out[int(fit_meta["fdt_data_offset"]):int(fit_meta["fdt_data_offset"]) + int(fit_meta["fdt_data_size"])])
            == stock_slot[int(fit_meta["fdt_data_offset"]):int(fit_meta["fdt_data_offset"]) + int(fit_meta["fdt_data_size"])]
        ),
    }

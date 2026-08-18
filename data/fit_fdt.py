#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field
import binascii
import hashlib
import struct
from pathlib import Path

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9
NAND_SIZE = 0x10000000
TCBOOT_UBI_START = 0x00100000
TCBOOT_UBI_SIZE = NAND_SIZE - TCBOOT_UBI_START
PROFILE_DESCRIPTION = "OpenWrt nokia_xg-040g-md-ubi"


class FdtError(ValueError):
    pass


@dataclass
class Node:
    name: str
    parent: "Node | None" = None
    props: dict[str, bytes] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)

    @property
    def path(self) -> str:
        parts: list[str] = []
        cur: Node | None = self
        while cur is not None:
            if cur.name:
                parts.append(cur.name)
            cur = cur.parent
        return "/" + "/".join(reversed(parts))

    def child(self, name: str) -> "Node":
        for child in self.children:
            if child.name == name:
                return child
        raise FdtError(f"missing node: {self.path.rstrip('/')}/{name}")

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def _u32(data: bytes) -> int:
    if len(data) != 4:
        raise FdtError(f"expected one 32-bit cell, got {len(data)} bytes")
    return struct.unpack(">I", data)[0]


def _uint(data: bytes) -> int:
    if len(data) == 4:
        return struct.unpack(">I", data)[0]
    if len(data) == 8:
        return struct.unpack(">Q", data)[0]
    raise FdtError(f"unsupported integer property length: {len(data)}")


def _cstr(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("utf-8", "strict")


def parse_fdt(data: bytes) -> tuple[Node, int]:
    if len(data) < 40:
        raise FdtError("short FDT")
    header = struct.unpack(">10I", data[:40])
    magic, totalsize, off_struct, off_strings, _off_rsvmap, _version, _last_comp, _boot_cpuid, size_strings, size_struct = header
    if magic != FDT_MAGIC:
        raise FdtError("bad FDT magic")
    if totalsize < 40 or totalsize > len(data):
        raise FdtError("invalid FDT totalsize")
    if off_struct + size_struct > totalsize or off_strings + size_strings > totalsize:
        raise FdtError("FDT blocks are outside totalsize")
    strings = data[off_strings:off_strings + size_strings]
    pos = off_struct
    end = off_struct + size_struct
    root: Node | None = None
    stack: list[Node] = []

    def prop_name(offset: int) -> str:
        if offset >= len(strings):
            raise FdtError("property name offset outside strings block")
        stop = strings.find(b"\0", offset)
        if stop < 0:
            raise FdtError("unterminated property name")
        return strings[offset:stop].decode("ascii", "strict")

    while pos + 4 <= end:
        token = struct.unpack(">I", data[pos:pos + 4])[0]
        pos += 4
        if token == FDT_BEGIN_NODE:
            stop = data.find(b"\0", pos, end)
            if stop < 0:
                raise FdtError("unterminated node name")
            name = data[pos:stop].decode("ascii", "strict")
            pos = (stop + 4) & ~3
            parent = stack[-1] if stack else None
            node = Node(name=name, parent=parent)
            if parent is not None:
                parent.children.append(node)
            elif root is None:
                root = node
            else:
                raise FdtError("multiple FDT roots")
            stack.append(node)
        elif token == FDT_END_NODE:
            if not stack:
                raise FdtError("unexpected END_NODE")
            stack.pop()
        elif token == FDT_PROP:
            if not stack or pos + 8 > end:
                raise FdtError("invalid FDT property")
            length, nameoff = struct.unpack(">II", data[pos:pos + 8])
            pos += 8
            if pos + length > end:
                raise FdtError("property extends outside structure block")
            value = data[pos:pos + length]
            pos = (pos + length + 3) & ~3
            stack[-1].props[prop_name(nameoff)] = value
        elif token == FDT_NOP:
            continue
        elif token == FDT_END:
            if stack:
                raise FdtError("FDT ended with open nodes")
            break
        else:
            raise FdtError(f"unknown FDT token {token:#x}")
    if root is None:
        raise FdtError("FDT has no root")
    return root, totalsize


def _image_data(fit_blob: bytes, fit_total: int, node: Node) -> bytes:
    if "data" in node.props:
        return node.props["data"]
    if "data-size" not in node.props:
        raise FdtError(f"{node.path}: data-size is missing")
    size = _uint(node.props["data-size"])
    if "data-position" in node.props:
        pos = _uint(node.props["data-position"])
    elif "data-offset" in node.props:
        # mkimage external-data offsets are relative to the aligned end of the FIT FDT.
        base = (fit_total + 3) & ~3
        pos = base + _uint(node.props["data-offset"])
    else:
        raise FdtError(f"{node.path}: neither inline data nor external data position is present")
    if pos < 0 or size < 0 or pos + size > len(fit_blob):
        raise FdtError(f"{node.path}: external data range is outside the file")
    return fit_blob[pos:pos + size]


def _verify_hashes(node: Node, payload: bytes) -> list[str]:
    verified: list[str] = []
    for child in node.children:
        if not child.name.startswith("hash"):
            continue
        algo = _cstr(child.props.get("algo", b""))
        expected = child.props.get("value")
        if not expected:
            raise FdtError(f"{child.path}: hash value missing")
        if algo == "crc32":
            got = struct.pack(">I", binascii.crc32(payload) & 0xFFFFFFFF)
        elif algo == "sha1":
            got = hashlib.sha1(payload).digest()
        elif algo == "sha256":
            got = hashlib.sha256(payload).digest()
        else:
            raise FdtError(f"{child.path}: unsupported hash algorithm {algo!r}")
        if got != expected:
            raise FdtError(f"{child.path}: {algo} mismatch")
        verified.append(algo)
    if not verified:
        raise FdtError(f"{node.path}: no image hash nodes")
    return verified


def _cells_to_int(data: bytes, count: int) -> int:
    if count <= 0 or count > 2 or len(data) != count * 4:
        raise FdtError(f"unsupported cell count/length: count={count}, len={len(data)}")
    value = 0
    for cell in struct.unpack(">" + "I" * count, data):
        value = (value << 32) | cell
    return value


def _int_to_cells(value: int, count: int) -> list[int]:
    if count <= 0 or count > 2 or value < 0 or value >= (1 << (32 * count)):
        raise FdtError(f"value {value:#x} does not fit in {count} cells")
    return [((value >> (32 * shift)) & 0xFFFFFFFF) for shift in reversed(range(count))]


def _inherited_cell_count(node: Node, prop: str, default: int) -> int:
    cur: Node | None = node
    while cur is not None:
        if prop in cur.props:
            return _u32(cur.props[prop])
        cur = cur.parent
    return default


@dataclass(frozen=True)
class SysupgradeInfo:
    path: Path
    size: int
    sha256: str
    fit_total_size: int
    config_name: str
    description: str
    kernel_name: str
    fdt_name: str
    rootfs_name: str
    fdt_size: int
    fdt_sha256: str
    ubi_path: str
    address_cells: int
    size_cells: int
    original_ubi_start: int
    original_ubi_size: int
    replacement_ubi_start: int
    replacement_ubi_size: int
    replacement_cells: tuple[int, ...]
    verified_hashes: tuple[str, ...]

    @property
    def uboot_reg_literal(self) -> str:
        return "<" + " ".join(f"0x{x:08x}" for x in self.replacement_cells) + ">"


def analyze_sysupgrade(path: Path) -> SysupgradeInfo:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FdtError(f"sysupgrade file not found: {path}")
    blob = path.read_bytes()
    if len(blob) < 0x100000 or len(blob) > 0x02000000:
        raise FdtError(f"unexpected sysupgrade size: {len(blob)}")
    fit, fit_total = parse_fdt(blob)
    images = fit.child("images")
    configs = fit.child("configurations")
    config_name = _cstr(configs.props.get("default", b""))
    if not config_name:
        raise FdtError("FIT /configurations/default is missing")
    config = configs.child(config_name)
    description = _cstr(config.props.get("description", b""))
    if description != PROFILE_DESCRIPTION:
        raise FdtError(f"wrong FIT profile: {description!r}")
    kernel_name = _cstr(config.props.get("kernel", b""))
    fdt_name = _cstr(config.props.get("fdt", b""))
    rootfs_name = _cstr(config.props.get("loadables", b""))
    if not kernel_name or not fdt_name or not rootfs_name:
        raise FdtError("FIT configuration must contain kernel, fdt and loadables")
    kernel_node = images.child(kernel_name)
    fdt_node = images.child(fdt_name)
    rootfs_node = images.child(rootfs_name)
    kernel_data = _image_data(blob, fit_total, kernel_node)
    fdt_data = _image_data(blob, fit_total, fdt_node)
    rootfs_data = _image_data(blob, fit_total, rootfs_node)
    verified: list[str] = []
    verified.extend(f"kernel:{x}" for x in _verify_hashes(kernel_node, kernel_data))
    verified.extend(f"fdt:{x}" for x in _verify_hashes(fdt_node, fdt_data))
    verified.extend(f"rootfs:{x}" for x in _verify_hashes(rootfs_node, rootfs_data))

    dt, _dt_total = parse_fdt(fdt_data)
    matches = [node for node in dt.walk() if _cstr(node.props.get("label", b"")) == "ubi"]
    if len(matches) != 1:
        raise FdtError(f"expected exactly one DT partition label='ubi', found {len(matches)}")
    ubi = matches[0]
    if ubi.parent is None:
        raise FdtError("ubi node has no parent")
    ac = _inherited_cell_count(ubi.parent, "#address-cells", 2)
    sc = _inherited_cell_count(ubi.parent, "#size-cells", 1)
    if ac not in (1, 2) or sc not in (1, 2):
        raise FdtError(f"unsupported partition cell format: address={ac}, size={sc}")
    reg = ubi.props.get("reg")
    if reg is None or len(reg) != 4 * (ac + sc):
        raise FdtError(f"{ubi.path}: reg is not one address/size tuple")
    original_start = _cells_to_int(reg[:4 * ac], ac)
    original_size = _cells_to_int(reg[4 * ac:], sc)
    original_end = original_start + original_size
    # Model-level compatibility gate, not a version pin: the official UBI area must
    # occupy the tail of this 256-MiB NAND and leave less than tcboot's 1-MiB reserve.
    if original_start < 0x20000 or original_start >= TCBOOT_UBI_START:
        raise FdtError(f"unexpected official UBI start: {original_start:#x}")
    if original_end != NAND_SIZE:
        raise FdtError(f"official UBI must end at NAND boundary {NAND_SIZE:#x}, got {original_end:#x}")
    cells = tuple(_int_to_cells(TCBOOT_UBI_START, ac) + _int_to_cells(TCBOOT_UBI_SIZE, sc))
    return SysupgradeInfo(
        path=path,
        size=len(blob),
        sha256=hashlib.sha256(blob).hexdigest(),
        fit_total_size=fit_total,
        config_name=config_name,
        description=description,
        kernel_name=kernel_name,
        fdt_name=fdt_name,
        rootfs_name=rootfs_name,
        fdt_size=len(fdt_data),
        fdt_sha256=hashlib.sha256(fdt_data).hexdigest(),
        ubi_path=ubi.path,
        address_cells=ac,
        size_cells=sc,
        original_ubi_start=original_start,
        original_ubi_size=original_size,
        replacement_ubi_start=TCBOOT_UBI_START,
        replacement_ubi_size=TCBOOT_UBI_SIZE,
        replacement_cells=cells,
        verified_hashes=tuple(verified),
    )

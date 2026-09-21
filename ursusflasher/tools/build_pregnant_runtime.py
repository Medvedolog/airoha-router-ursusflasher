#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import lzma
import os
import stat
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9


def a4(value: int) -> int:
    return (value + 3) & ~3


@dataclass
class Node:
    name: str
    props: list[tuple[str, bytes]] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)

    def get(self, key: str) -> bytes | None:
        for name, value in self.props:
            if name == key:
                return value
        return None

    def set(self, key: str, value: bytes) -> None:
        for index, (name, _old) in enumerate(self.props):
            if name == key:
                self.props[index] = (key, value)
                return
        self.props.append((key, value))

    def delete(self, key: str) -> None:
        self.props = [(name, value) for name, value in self.props if name != key]


class Fdt:
    def __init__(self, blob: bytes):
        if len(blob) < 40:
            raise ValueError("truncated FDT")
        header = struct.unpack(">10I", blob[:40])
        (
            magic,
            self.totalsize,
            self.off_struct,
            self.off_strings,
            self.off_mem,
            self.version,
            self.last_comp,
            self.boot_cpuid,
            self.size_strings,
            self.size_struct,
        ) = header
        if magic != FDT_MAGIC:
            raise ValueError("not FDT")
        if self.totalsize > len(blob):
            raise ValueError("FDT totalsize exceeds blob")
        self.strings = blob[self.off_strings : self.off_strings + self.size_strings]
        pos = self.off_struct
        end = pos + self.size_struct
        stack: list[Node] = []
        root = None
        while pos < end:
            token = struct.unpack(">I", blob[pos : pos + 4])[0]
            pos += 4
            if token == FDT_BEGIN_NODE:
                q = blob.index(b"\0", pos, end)
                node = Node(blob[pos:q].decode("utf-8", "surrogateescape"))
                pos = a4(q + 1)
                if stack:
                    stack[-1].children.append(node)
                else:
                    root = node
                stack.append(node)
            elif token == FDT_END_NODE:
                stack.pop()
            elif token == FDT_PROP:
                length, nameoff = struct.unpack(">II", blob[pos : pos + 8])
                pos += 8
                value = blob[pos : pos + length]
                pos = a4(pos + length)
                q = self.strings.index(b"\0", nameoff)
                name = self.strings[nameoff:q].decode("ascii")
                stack[-1].props.append((name, value))
            elif token == FDT_NOP:
                continue
            elif token == FDT_END:
                break
            else:
                raise ValueError(f"bad FDT token {token}")
        if root is None:
            raise ValueError("empty FDT")
        self.root = root

    def walk(self):
        def rec(node: Node, path: str):
            yield path, node
            for child in node.children:
                child_path = (path.rstrip("/") + "/" + child.name) if path != "/" else "/" + child.name
                yield from rec(child, child_path)

        yield from rec(self.root, "/")

    def node(self, path: str) -> Node:
        if path == "/":
            return self.root
        current = self.root
        for part in path.strip("/").split("/"):
            current = next((child for child in current.children if child.name == part), None)
            if current is None:
                raise KeyError(path)
        return current

    def build(self) -> bytes:
        names: list[str] = []
        for _path, node in self.walk():
            for name, _value in node.props:
                if name not in names:
                    names.append(name)
        strings = bytearray()
        nameoff: dict[str, int] = {}
        for name in names:
            nameoff[name] = len(strings)
            strings += name.encode("ascii") + b"\0"
        structure = bytearray()

        def emit(node: Node) -> None:
            nonlocal structure
            structure += struct.pack(">I", FDT_BEGIN_NODE)
            raw_name = node.name.encode("utf-8", "surrogateescape") + b"\0"
            structure += raw_name
            structure += b"\0" * ((-len(structure)) % 4)
            for name, value in node.props:
                structure += struct.pack(">III", FDT_PROP, len(value), nameoff[name])
                structure += value
                structure += b"\0" * ((-len(structure)) % 4)
            for child in node.children:
                emit(child)
            structure += struct.pack(">I", FDT_END_NODE)

        emit(self.root)
        structure += struct.pack(">I", FDT_END)
        memreserve = b"\0" * 16
        off_mem = 40
        off_struct = a4(off_mem + len(memreserve))
        pre = b"\0" * (off_struct - (off_mem + len(memreserve)))
        off_strings = off_struct + len(structure)
        total = off_strings + len(strings)
        header = struct.pack(
            ">10I",
            FDT_MAGIC,
            total,
            off_struct,
            off_strings,
            off_mem,
            self.version,
            self.last_comp,
            self.boot_cpuid,
            len(strings),
            len(structure),
        )
        return header + memreserve + pre + bytes(structure) + bytes(strings)


def cstr(value: bytes | None) -> str:
    if value is None:
        return ""
    return value.split(b"\0", 1)[0].decode("ascii", "replace")


def reg2(node: Node) -> tuple[int, int]:
    value = node.get("reg")
    if value is None or len(value) != 8:
        raise ValueError(f"{node.name} has no 2-cell reg")
    return struct.unpack(">II", value)


def hash_image(node: Node) -> None:
    data = node.get("data")
    if data is None:
        raise ValueError("FIT image missing data")
    for child in node.children:
        algo = cstr(child.get("algo"))
        if algo == "crc32":
            child.set("value", struct.pack(">I", zlib.crc32(data) & 0xFFFFFFFF))
        elif algo == "sha1":
            child.set("value", hashlib.sha1(data).digest())
        elif algo == "sha256":
            child.set("value", hashlib.sha256(data).digest())


@dataclass
class Entry:
    magic: bytes
    vals: list[int]
    name: str
    data: bytes


def parse_archive_at(raw: bytes, start: int):
    pos = start
    entries: list[Entry] = []
    try:
        while True:
            header = raw[pos : pos + 110]
            if len(header) != 110 or header[:6] not in (b"070701", b"070702"):
                return None
            vals = [int(header[6 + i * 8 : 14 + i * 8], 16) for i in range(13)]
            pos += 110
            filesize, namesize = vals[6], vals[11]
            if namesize < 1 or namesize > 4096:
                return None
            name_raw = raw[pos : pos + namesize]
            pos = a4(pos + namesize)
            if not name_raw.endswith(b"\0"):
                return None
            name = name_raw[:-1].decode("utf-8", "surrogateescape")
            data = raw[pos : pos + filesize]
            pos = a4(pos + filesize)
            entries.append(Entry(header[:6], vals, name, data))
            if name == "TRAILER!!!":
                if len(entries) > 100 and any(entry.name == "bin/busybox" for entry in entries):
                    return start, pos, entries
                return None
    except Exception:
        return None


def find_archive(raw: bytes):
    pos = 0
    while True:
        start = raw.find(b"070701", pos)
        if start < 0:
            raise ValueError("linked newc initramfs not found")
        parsed = parse_archive_at(raw, start)
        if parsed:
            return parsed
        pos = start + 1


def build_entry(entry: Entry) -> bytes:
    vals = entry.vals[:]
    vals[6] = len(entry.data)
    vals[11] = len(entry.name.encode("utf-8", "surrogateescape")) + 1
    vals[12] = 0
    header = entry.magic + b"".join(f"{value:08x}".encode("ascii") for value in vals)
    name_raw = entry.name.encode("utf-8", "surrogateescape") + b"\0"
    out = bytearray(header)
    out += name_raw
    out += b"\0" * ((-len(out)) % 4)
    out += entry.data
    out += b"\0" * ((-len(out)) % 4)
    return bytes(out)


def new_entry(name: str, data: bytes, mode: int, ino: int) -> Entry:
    vals = [ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name.encode()) + 1, 0]
    return Entry(b"070701", vals, name, data)


def overlay_entries(root: Path, start_ino: int):
    out: list[Entry] = []
    ino = start_ino
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        st = path.lstat()
        ino += 1
        if path.is_symlink():
            out.append(new_entry(rel, os.readlink(path).encode(), stat.S_IFLNK | 0o777, ino))
        elif path.is_dir():
            out.append(new_entry(rel, b"", stat.S_IFDIR | (st.st_mode & 0o7777), ino))
        elif path.is_file():
            out.append(new_entry(rel, path.read_bytes(), stat.S_IFREG | (st.st_mode & 0o7777), ino))
    return out, ino


def patch_cpio(raw: bytes, overlay: list[Entry]):
    start, end, entries = find_archive(raw)
    next_nonzero = end
    while next_nonzero < len(raw) and raw[next_nonzero] == 0:
        next_nonzero += 1
    capacity = next_nonzero - start
    replacements = {entry.name for entry in overlay}
    kept: list[Entry] = []
    removed: list[tuple[str, int]] = []
    for entry in entries:
        if entry.name == "TRAILER!!!" or entry.name in replacements:
            continue
        # Reclaim APK index/database metadata only. No binary, config, module,
        # firmware or runtime script is removed from the transient image.
        if entry.name.startswith("lib/apk/db/") or entry.name.startswith("lib/apk/packages/"):
            removed.append((entry.name, len(entry.data)))
            continue
        kept.append(entry)
    maxino = max(entry.vals[0] for entry in entries)
    kept += overlay
    maxino = max([maxino] + [entry.vals[0] for entry in overlay])
    kept.append(new_entry("TRAILER!!!", b"", 0, maxino + 1))
    archive = b"".join(build_entry(entry) for entry in kept)
    if len(archive) > capacity:
        raise ValueError(f"patched cpio {len(archive)} > fixed window {capacity}; need {len(archive) - capacity} more bytes")
    out = bytearray(raw)
    out[start:next_nonzero] = archive + b"\0" * (capacity - len(archive))
    if out[:start] != raw[:start] or out[next_nonzero:] != raw[next_nonzero:]:
        raise AssertionError("bytes outside linked initramfs window moved")
    return bytes(out), start, next_nonzero, len(archive), removed


def add_stock_aliases(dtb: bytes, family: str) -> bytes:
    expected = {
        "md": "nokia,xg-040g-md-ubi",
        "mf": "nokia,xg-040g-mf-ubi",
    }[family]
    fdt = Fdt(dtb)
    compatible = fdt.node("/").get("compatible") or b""
    compatibles = compatible.rstrip(b"\0").split(b"\0")
    if expected.encode() not in compatibles:
        raise ValueError(f"unexpected recovery DT compatible for {family}: {compatibles!r}")
    parts = fdt.node("/soc/spi@1fa10000/nand@0/partitions")
    by_label = {cstr(child.get("label")): child for child in parts.children if child.get("label")}
    required = {
        "all_flash": (0x00000000, 0x10000000),
        "bl2": (0x00000000, 0x00020000),
        "ubi": (0x00020000, 0x0FFE0000),
    }
    for label, want in required.items():
        node = by_label.get(label)
        if node is None or reg2(node) != want:
            raise ValueError(f"unexpected UBI recovery partition {label}: {reg2(node) if node else None} != {want}")
    # This transient migration DT is intentionally write-capable for BL2. The
    # final production DT remains the unmodified UnameOne image.
    by_label["bl2"].delete("read-only")
    specs = [
        ("stock-bootloader@0", "stock_bootloader", 0x00000000, 0x00080000, True),
        ("stock-nsb-master@c0000", "nsb_master", 0x000C0000, 0x02880000, True),
        ("stock-nsb-slave@2940000", "nsb_slave", 0x02940000, 0x02880000, True),
        ("stock-bosa@51c0000", "bosa_stock", 0x051C0000, 0x00040000, True),
        ("stock-ri@5200000", "ri_stock", 0x05200000, 0x00040000, True),
        ("stock-flag@5240000", "flag", 0x05240000, 0x00040000, False),
        ("stock-flagback@5280000", "flagback", 0x05280000, 0x00040000, True),
    ]
    existing_labels = set(by_label)
    for node_name, label, offset, size, readonly in specs:
        if label in existing_labels:
            raise ValueError(f"unexpected pre-existing stock alias: {label}")
        props = [("label", label.encode() + b"\0"), ("reg", struct.pack(">II", offset, size))]
        if readonly:
            props.append(("read-only", b""))
        parts.children.append(Node(node_name, props, []))
    out = fdt.build()
    verify = Fdt(out)
    labels = {cstr(node.get("label")): node for _path, node in verify.walk() if node.get("label")}
    for _node_name, label, offset, size, readonly in specs:
        node = labels.get(label)
        if node is None or reg2(node) != (offset, size):
            raise AssertionError(f"stock alias verification failed: {label}")
        if readonly != (node.get("read-only") is not None):
            raise AssertionError(f"stock alias read-only mismatch: {label}")
    if labels["bl2"].get("read-only") is not None:
        raise AssertionError("transition BL2 remained read-only")
    return out


def patch_fit(blob: bytes, overlay_root: Path, family: str):
    total = struct.unpack(">I", blob[4:8])[0]
    fit = Fdt(blob[:total])
    kernels = [node for _path, node in fit.walk() if cstr(node.get("type")) == "kernel"]
    fdts = [node for _path, node in fit.walk() if cstr(node.get("type")) == "flat_dt"]
    if len(kernels) != 1 or len(fdts) != 1:
        raise ValueError("expected exactly one kernel and one fdt in UBI recovery FIT")
    kernel, fdt_image = kernels[0], fdts[0]

    # Nokia stock tcboot is not a generic FIT consumer. Its OEM path expects
    # the legacy unit names conf@1 -> kernel@1 + fdt@1. OpenWrt snapshots use
    # config-1/kernel-1/fdt-1, which are valid FIT names but tcboot rejects them.
    configs = fit.node("/configurations")
    if len(configs.children) != 1:
        raise ValueError(f"expected exactly one FIT configuration, got {len(configs.children)}")
    conf = configs.children[0]
    kernel.name = "kernel@1"
    fdt_image.name = "fdt@1"
    conf.name = "conf@1"
    configs.set("default", b"conf@1\0")
    conf.set("kernel", b"kernel@1\0")
    conf.set("fdt", b"fdt@1\0")

    if cstr(kernel.get("compression")) != "lzma":
        raise ValueError("recovery kernel is not LZMA")
    old_kernel = kernel.get("data")
    old_dtb = fdt_image.get("data")
    if old_kernel is None or old_dtb is None:
        raise ValueError("FIT image data missing")
    raw = lzma.decompress(old_kernel, format=lzma.FORMAT_ALONE)
    _start, _end, entries = find_archive(raw)
    overlay, _ino = overlay_entries(overlay_root, max(entry.vals[0] for entry in entries))
    raw2, cpio_start, cpio_end, archive_len, removed = patch_cpio(raw, overlay)
    filters = [
        {
            "id": lzma.FILTER_LZMA1,
            "dict_size": 4 * 1024 * 1024,
            "lc": 3,
            "lp": 0,
            "pb": 2,
            "mode": lzma.MODE_NORMAL,
            "nice_len": 64,
            "mf": lzma.MF_BT4,
            "depth": 0,
        }
    ]
    new_kernel = lzma.compress(raw2, format=lzma.FORMAT_ALONE, filters=filters)
    kernel.set("data", new_kernel)
    fdt_image.set("data", add_stock_aliases(old_dtb, family))
    hash_image(kernel)
    hash_image(fdt_image)
    out = fit.build()

    verify = Fdt(out)
    # Build-time tcboot compatibility gate. Do not accept a merely standards-
    # compliant FIT here: the Nokia OEM parser uses these exact unit names.
    verify_kernel = verify.node("/images/kernel@1")
    verify_fdt = verify.node("/images/fdt@1")
    verify_configs = verify.node("/configurations")
    verify_conf = verify.node("/configurations/conf@1")
    if cstr(verify_configs.get("default")) != "conf@1":
        raise AssertionError("tcboot FIT default configuration is not conf@1")
    if cstr(verify_conf.get("kernel")) != "kernel@1":
        raise AssertionError("tcboot FIT configuration does not reference kernel@1")
    if cstr(verify_conf.get("fdt")) != "fdt@1":
        raise AssertionError("tcboot FIT configuration does not reference fdt@1")
    if cstr(verify_kernel.get("type")) != "kernel" or cstr(verify_fdt.get("type")) != "flat_dt":
        raise AssertionError("tcboot FIT image node types are invalid")
    verify_raw = lzma.decompress(verify_kernel.get("data"), format=lzma.FORMAT_ALONE)
    if len(verify_raw) != len(raw):
        raise AssertionError("linked Image raw size changed")
    verify_entries = find_archive(verify_raw)[2]
    by_name = {entry.name: entry for entry in verify_entries}
    for required in (
        "usr/sbin/ursus-vanilla-stage2",
        "usr/sbin/ursusstockslot",
        "etc/ursus/PREGNANT_RUNTIME",
        "etc/init.d/ursus-pregnant",
        "etc/rc.d/S98ursus-pregnant",
    ):
        if required not in by_name:
            raise AssertionError(f"injected path missing: {required}")
    init_link = by_name["etc/rc.d/S98ursus-pregnant"]
    if not stat.S_ISLNK(init_link.vals[1]) or init_link.data != b"../init.d/ursus-pregnant":
        raise AssertionError("pregnant stage2 rc.d link is not a symlink to ../init.d/ursus-pregnant")
    return out, {
        "family": family,
        "raw_size": len(raw),
        "cpio_window": [cpio_start, cpio_end],
        "cpio_archive": archive_len,
        "removed_metadata_bytes": sum(size for _name, size in removed),
        "removed_metadata_entries": len(removed),
        "kernel_lzma_old": len(old_kernel),
        "kernel_lzma_new": len(new_kernel),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build UrsusFlasher pregnant UBI-recovery runtime by fixed-window newc/FIT surgery")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--family", choices=("md", "mf"), required=True)
    args = parser.parse_args()
    out, metadata = patch_fit(args.input.read_bytes(), args.overlay, args.family)
    args.output.write_bytes(out)
    print(metadata)
    print("SHA256", hashlib.sha256(out).hexdigest(), "SIZE", len(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
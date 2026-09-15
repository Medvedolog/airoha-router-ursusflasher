#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import struct
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("NOKIA_LANG", "en")

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "ursusflasher" / "src"
sys.path.insert(0, str(SRC))

import stock_ab_transition as sat  # noqa: E402
import stock_fit_wrapper as sfw  # noqa: E402

FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_END = 9
TEST_NT_FW_UUID = bytes.fromhex("00112233445566778899aabbccddeeff")


def _align4(value: int) -> int:
    return (value + 3) & ~3


def _linux_image(size: int = 256) -> bytes:
    image = bytearray(size)
    struct.pack_into("<Q", image, 8, 0)
    struct.pack_into("<Q", image, 16, size)
    struct.pack_into("<Q", image, 24, 0)
    struct.pack_into("<I", image, 56, 0x644D5241)
    image[64:75] = b"TRANSITION2"
    image[80:96] = b"OFFICIAL_OPENWRT"
    return bytes(image)


def _fit_blob(compression: bytes, total_size: int = 0x2000) -> tuple[bytes, int, int]:
    strings = bytearray()
    name_offsets: dict[str, int] = {}
    struct_block = bytearray()

    def nameoff(name: str) -> int:
        if name not in name_offsets:
            name_offsets[name] = len(strings)
            strings.extend(name.encode("ascii") + b"\0")
        return name_offsets[name]

    def token(value: int) -> None:
        struct_block.extend(struct.pack(">I", value))

    def node(name: str) -> None:
        token(FDT_BEGIN_NODE)
        struct_block.extend(name.encode("ascii") + b"\0")
        struct_block.extend(b"\0" * (_align4(len(struct_block)) - len(struct_block)))

    def end_node() -> None:
        token(FDT_END_NODE)

    def prop(name: str, value: bytes) -> None:
        token(FDT_PROP)
        struct_block.extend(struct.pack(">II", len(value), nameoff(name)))
        struct_block.extend(value)
        struct_block.extend(b"\0" * (_align4(len(struct_block)) - len(struct_block)))

    kernel = b"K" * 512
    fdt_data = bytes.fromhex("d00dfeed") + (b"F" * 60)
    fs_data = b"hsqs" + (b"S" * 60)

    node("")
    node("images")
    node("kernel@1")
    prop("type", b"kernel\0")
    prop("arch", b"arm64\0")
    prop("os", b"linux\0")
    prop("compression", compression)
    prop("load", struct.pack(">I", 0x80088000))
    prop("entry", struct.pack(">I", 0x80088000))
    prop("data", kernel)
    node("hash@1")
    prop("algo", b"sha1\0")
    prop("value", hashlib.sha1(kernel).digest())
    end_node()
    end_node()
    node("fdt@1")
    prop("data", fdt_data)
    end_node()
    node("filesystem@1")
    prop("data", fs_data)
    end_node()
    end_node()

    node("configurations")
    prop("default", b"conf@1\0")
    node("conf@1")
    prop("kernel", b"kernel@1\0")
    prop("fdt", b"fdt@1\0")
    prop("filesystem", b"filesystem@1\0")
    end_node()
    end_node()
    end_node()
    token(FDT_END)

    off_struct = 40
    size_struct = len(struct_block)
    off_strings = _align4(off_struct + size_struct)
    size_strings = len(strings)
    if off_strings + size_strings > total_size:
        raise AssertionError("synthetic FIT exceeds requested total size")

    out = bytearray(total_size)
    struct.pack_into(
        ">10I",
        out,
        0,
        0xD00DFEED,
        total_size,
        off_struct,
        off_strings,
        0,
        17,
        16,
        0,
        size_strings,
        size_struct,
    )
    out[off_struct:off_struct + size_struct] = struct_block
    out[off_strings:off_strings + size_strings] = strings
    return bytes(out), len(kernel), len(fs_data)


def _stock_slot(compression: bytes) -> tuple[bytes, int, int, int]:
    fit, kernel_size, fs_size = _fit_blob(compression)
    nt_off = 0x400
    nt_size = 0x100 + len(fit)
    slot_size = 0x3000
    slot = bytearray(slot_size)

    slot[:8] = bytes.fromhex("010064aa78563412")
    slot[16:32] = TEST_NT_FW_UUID
    struct.pack_into("<QQQ", slot, 32, nt_off, nt_size, 0)
    slot[56:72] = b"\0" * 16

    slot[nt_off:nt_off + 4] = b"HDR2"
    struct.pack_into("<I", slot, nt_off + 0x08, nt_size)
    struct.pack_into("<I", slot, nt_off + 0x50, kernel_size)
    struct.pack_into("<I", slot, nt_off + 0x54, fs_size)
    slot[nt_off + 0x100:nt_off + nt_size] = fit
    return bytes(slot), slot_size, nt_off, nt_size


def test_fit_contract_behavior() -> None:
    linux_image = _linux_image()
    for stock_compression in (b"none\0", b"lzma\0"):
        stock, slot_size, nt_off, nt_size = _stock_slot(stock_compression)
        candidate, meta = sfw.build_transition_slot(
            stock,
            linux_image,
            slot_size=slot_size,
            nt_fw_uuid=TEST_NT_FW_UUID,
        )
        props, _ = sfw.stock_fit_contract(candidate, nt_off, nt_size)
        assert sfw.prop(candidate, props, "/images/kernel@1/compression") == b"none\0"

        kernel_off, kernel_size = props["/images/kernel@1/data"]
        hash_off, hash_size = props["/images/kernel@1/hash@1/value"]
        assert hash_size == 20
        expected_hash = hashlib.sha1(candidate[kernel_off:kernel_off + kernel_size]).digest()
        assert candidate[hash_off:hash_off + hash_size] == expected_hash
        assert meta["stock_kernel_compression"] == stock_compression.rstrip(b"\0").decode("ascii")
        assert meta["transition_kernel_compression"] == "none"


class _Access:
    family = "md"
    host = "192.0.2.1"

    def close_web(self, announce: bool = False) -> None:
        return None


class _Telnet:
    def __init__(self, events: list[tuple]) -> None:
        self.events = events

    def command_clean(self, command: str, timeout: int = 20) -> tuple[int, str]:
        if command.startswith("mtd write "):
            self.events.append(("write", command))
        return 0, ""

    def send_line(self, line: str) -> None:
        self.events.append(("reboot", line))

    def close(self) -> None:
        return None


def _drive_run(answer: str) -> tuple[int, list[tuple]]:
    events: list[tuple] = []
    access = _Access()
    telnet = _Telnet(events)
    old: list[tuple[object, str, object]] = []

    def patch(obj: object, name: str, value: object) -> None:
        old.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    with tempfile.TemporaryDirectory() as tempdir:
        try:
            patch(sat, "WORK", Path(tempdir))
            patch(sat, "_load_payload", lambda policy: (b"image", {}))
            patch(sat.ubi, "open_root_auto", lambda host: (access, telnet))
            patch(sat, "_require_stock_geometry", lambda *args, **kwargs: None)
            patch(sat, "_mtd_writer_preflight", lambda *args, **kwargs: "mtd")
            patch(sat.pb, "backup_tftp", lambda *args, **kwargs: None)
            patch(
                sat.pb,
                "verify_stock_restore_backup",
                lambda *args, **kwargs: {"stock_family": "MD", "stock_variant": "synthetic"},
            )

            blobs = {8: b"flag", 9: b"flagback", 14: b"master", 15: b"slave"}
            patch(
                sat,
                "_backup_partition_bytes",
                lambda directory, number, name, size: (
                    blobs[number],
                    hashlib.sha256(blobs[number]).hexdigest(),
                    directory / f"mtd{number}_{name}.bin.gz",
                ),
            )
            patch(
                sat,
                "parse_flag",
                lambda *args, **kwargs: {"active": 0, "curimg": 0, "startok": 1, "count": 3},
            )

            slot_candidate = b"SLOT"
            flag_candidate = b"FLAG"
            slot_sha = hashlib.sha256(slot_candidate).hexdigest()
            flag_sha = hashlib.sha256(flag_candidate).hexdigest()
            patch(
                sat,
                "build_transition_slot",
                lambda *args, **kwargs: (slot_candidate, {"candidate_sha256": slot_sha}),
            )
            patch(
                sat,
                "build_activation_flag",
                lambda *args, **kwargs: (flag_candidate, {"before": {}, "after": {}}),
            )

            def send_tcp(_telnet, _host, _local, remote) -> None:
                events.append(("transfer", "tcp", remote))

            def send_tftp(_telnet, _host, _local, remote, **kwargs) -> None:
                events.append(("transfer", "tftp", remote))

            patch(sat.pb, "send_file_to_router", send_tcp)
            patch(sat.pb, "send_file_to_router_tftp", send_tftp)
            patch(
                sat,
                "_verify_remote_upload",
                lambda _telnet, local, _remote: hashlib.sha256(local.read_bytes()).hexdigest(),
            )
            patch(
                sat,
                "_remote_partition_sha",
                lambda _telnet, dev, timeout=300: slot_sha if dev.endswith("15") else flag_sha,
            )
            patch(sat.ui, "enable", lambda: None)
            patch(sat.ui, "status", lambda *args, **kwargs: None)
            patch(sat.ui, "prompt", lambda _text: (events.append(("prompt", answer)) or answer))

            result = sat.run(
                host=access.host,
                profile="xg040-md",
                unattended=True,
                dry_run=False,
                reboot=False,
                own_transcript=False,
            )
            return result, events
        finally:
            for obj, name, value in reversed(old):
                setattr(obj, name, value)


def test_confirm_and_transport_boundary_behavior() -> None:
    result, events = _drive_run("n")
    assert result == 0
    prompt_index = next(i for i, event in enumerate(events) if event[0] == "prompt")
    assert not any(event[0] == "write" for event in events[prompt_index + 1:])
    assert not any(event[0] == "transfer" for event in events[prompt_index + 1:])

    result, events = _drive_run("y")
    assert result == 0
    prompt_index = next(i for i, event in enumerate(events) if event[0] == "prompt")
    assert sum(1 for event in events[prompt_index + 1:] if event[0] == "write") == 2
    assert not any(event[0] == "transfer" for event in events[prompt_index + 1:])


def test_mf_refusal_behavior() -> None:
    try:
        sat._policy("xg040-mf")
    except RuntimeError as exc:
        assert "refusing to copy MD MTD indices/offsets/HDR assumptions" in str(exc)
    else:
        raise AssertionError("xg040-mf must refuse before any stock/NAND access")


def test_expert_wiring_smoke() -> None:
    expert = (SRC / "expert.py").read_text(encoding="utf-8")
    assert "stock_ab_transition.run_expert(host=host, profile=profile)" in expert
    assert "Reset не менее 30 секунд" in expert


test_fit_contract_behavior()
test_confirm_and_transport_boundary_behavior()
test_mf_refusal_behavior()
test_expert_wiring_smoke()
print("selftest_transition_expert_item4: PASS")

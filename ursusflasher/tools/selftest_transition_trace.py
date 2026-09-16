#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "ursusflasher" / "src"
sys.path.insert(0, str(SRC))

import transition_trace  # noqa: E402


class UI:
    def __init__(self):
        self.events: list[tuple[str, str]] = []

    def status(self, label: str, text: str) -> None:
        self.events.append((label, text))


class PB:
    @staticmethod
    def tr(ru: str, en: str) -> str:
        return ru


class Policy:
    payload_name = "transition.linuximg"
    slave_mtd = 15
    flag_mtd = 8
    master_mtd = 14
    flagback_mtd = 9


def main() -> None:
    ui = UI()
    writes: list[tuple] = []

    def load_payload(policy):
        return b"PAYLOAD", {
            "source_commit": "0123456789abcdef",
            "transition_entry": "ursusdispatch->ursusweb",
            "final_target": "VANILLA_OPENWRT_UBI",
        }

    def build_slot(stock: bytes, image: bytes, policy=None):
        return b"CANDIDATE", {"candidate_sha256": "deadbeef"}

    def build_flag(flag: bytes, target: int, policy=None):
        return b"FLAG", {
            "before": {"active": 0, "curimg": 0, "startok": 1, "count": 15},
            "after": {"active": 1, "curimg": 0, "startok": 1, "count": 15},
        }

    def write_partition(telnet, remote, part, dev, size, method, erase_size, timeout=600):
        writes.append((remote, part, dev, size, method, erase_size, timeout))

    def readback(telnet, dev, timeout=300):
        return "a" * 64

    sat = SimpleNamespace(
        _load_payload=load_payload,
        build_transition_slot=build_slot,
        build_activation_flag=build_flag,
        _write_partition=write_partition,
        _remote_partition_sha=readback,
        ui=ui,
        pb=PB(),
        MD_POLICY=Policy(),
    )

    transition_trace.install(sat)
    sat._load_payload(Policy())
    sat.build_transition_slot(b"STOCK", b"IMAGE", Policy())
    sat.build_activation_flag(b"FLAG0", 1, Policy())
    sat._write_partition(None, "/tmp/slot.bin", "nsb_slave", "/dev/mtd15", 0x02880000, "mtd_debug", 0x20000, timeout=900)
    got = sat._remote_partition_sha(None, "/dev/mtd15", timeout=600)
    assert got == "a" * 64

    text = "\n".join(message for _label, message in ui.events)
    assert "Stock selector ДО: active=0, curimg=0, startok=1, count=15" in text
    assert "Stock selector ПОСЛЕ: active=1, curimg=0, startok=1, count=15" in text
    assert "меняется только active -> 1" in text
    assert "nsb_master/mtd14" in text and "flagback/mtd9" in text
    assert "NAND WRITE 1/2: nsb_slave -> /dev/mtd15" in text
    assert "writer=mtd_debug" in text
    assert "Полное обратное чтение /dev/mtd15 -> SHA256" in text
    assert ("a" * 64) in text
    assert writes == [("/tmp/slot.bin", "nsb_slave", "/dev/mtd15", 0x02880000, "mtd_debug", 0x20000, 900)]
    print("selftest_transition_trace: PASS")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "ursusflasher" / "src"
sys.path.insert(0, str(SRC))

import backup_progress as bp  # noqa: E402


def test_snapshot_tracks_current_partition_without_fake_byte_percent() -> None:
    numbers = (0, 1, 2)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        assert bp._snapshot(root, numbers) == (None, 0, 0)
        p0 = root / "mtd0_bootloader.bin.gz"
        p0.write_bytes(b"a" * 100)
        assert bp._snapshot(root, numbers) == (0, 100, 0)
        p1 = root / "mtd1_romfile.bin.gz"
        p1.write_bytes(b"b" * 250)
        assert bp._snapshot(root, numbers) == (1, 250, 1)
        p2 = root / "mtd2_kernel.bin.gz"
        p2.write_bytes(b"c" * 400)
        assert bp._snapshot(root, numbers) == (2, 400, 2)


def test_human_bytes() -> None:
    assert bp._human_bytes(512) == "512 B"
    assert bp._human_bytes(2048) == "2.0 KiB"
    assert bp._human_bytes(2 * 1024 * 1024) == "2.0 MiB"


test_snapshot_tracks_current_partition_without_fake_byte_percent()
test_human_bytes()
print("selftest_backup_progress: PASS")

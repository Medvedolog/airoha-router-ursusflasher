#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "ursusflasher" / "src"
sys.path.insert(0, str(SRC))

import backup_progress as bp  # noqa: E402


def test_helpers() -> None:
    assert bp._partition_number("mtd0_bootloader.bin.gz") == 0
    assert bp._partition_number("mtd11_data.bin.gz") == 11
    assert bp._partition_number("other.bin.gz") is None
    assert bp._human_bytes(512) == "512 B"
    assert bp._human_bytes(2048) == "2.0 KiB"
    assert bp._human_bytes(2 * 1024 * 1024) == "2.0 MiB"
    os.environ["NOKIA_LANG"] = "ru"
    line = bp._progress_line(3, 17, tuple(range(17)), 8 * 1024 * 1024, 4 * 1024 * 1024, 2)
    assert "3/17" not in line  # mtd3 is stage 4
    assert "4/17" in line
    assert "mtd3: 8.0 MiB gzip" in line
    assert "4.0 MiB/с" in line


def test_live_progress_uses_current_tftp_result() -> None:
    class Result:
        def __init__(self):
            self.bytes_transferred = 0
            self.error = None

    class FakePB:
        EXPECTED_NUMBERS = (0, 1)

        @staticmethod
        def receive_tftp_put(bind_ip, port, output, expected_name, allowed_host, ready, result, *args, **kwargs):
            ready.set()
            for _ in range(3):
                time.sleep(0.8)
                result.bytes_transferred += 1024 * 1024
            return None

        @staticmethod
        def backup_tftp(access, router_host, destination, *args, **kwargs):
            ready = threading.Event()
            result = Result()
            t = threading.Thread(
                target=FakePB.receive_tftp_put,
                args=("0.0.0.0", 1069, Path(destination) / "ignored.tmp", "mtd1_romfile.bin.gz", router_host, ready, result),
            )
            t.start()
            assert ready.wait(1)
            t.join()
            return Path(destination)

    pb = FakePB
    bp.install(pb)
    os.environ["NOKIA_LANG"] = "ru"
    with tempfile.TemporaryDirectory() as td, io.StringIO() as buf, contextlib.redirect_stdout(buf):
        pb.backup_tftp(SimpleNamespace(), "192.0.2.1", Path(td))
        out = buf.getvalue()
    assert "mtd1:" in out, out
    assert "0 B/с" not in out, out
    assert "2/2" in out, out
    assert "готово 100% разделов" in out, out


test_helpers()
test_live_progress_uses_current_tftp_result()
print("selftest_backup_progress: PASS")

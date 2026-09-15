#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("NOKIA_LANG", "en")

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "ursusflasher" / "src"
sys.path.insert(0, str(SRC))

import stock_ab_transition as sat  # noqa: E402


class _Access:
    family = "md"
    host = "192.0.2.1"

    def close_web(self, announce: bool = False) -> None:
        return None


class _Telnet:
    def __init__(self, events: list[tuple]) -> None:
        self.events = events

    def command_clean(self, command: str, timeout: int = 20) -> tuple[int, str]:
        return 0, ""

    def send_line(self, line: str) -> None:
        self.events.append(("reboot", line))

    def close(self) -> None:
        return None


def _drive_run(*, readback_override: dict[str, str] | None = None) -> tuple[int | None, Exception | None, list[tuple]]:
    events: list[tuple] = []
    access = _Access()
    telnet = _Telnet(events)
    policy = sat._policy("xg040-md")
    old: list[tuple[object, str, object]] = []
    readback_override = readback_override or {}

    def patch(obj: object, name: str, value: object) -> None:
        old.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    with tempfile.TemporaryDirectory() as tempdir:
        try:
            patch(sat, "WORK", Path(tempdir))
            patch(sat, "_load_payload", lambda _policy: (b"image", {}))
            patch(sat.ubi, "open_root_auto", lambda _host: (access, telnet))
            patch(sat, "_require_stock_geometry", lambda *args, **kwargs: None)
            patch(sat, "_mtd_writer_preflight", lambda *args, **kwargs: "mtd")
            patch(sat.pb, "backup_tftp", lambda *args, **kwargs: None)
            patch(
                sat.pb,
                "verify_stock_restore_backup",
                lambda *args, **kwargs: {"stock_family": "MD", "stock_variant": "synthetic"},
            )

            blobs = {
                policy.flag_mtd: b"flag",
                policy.flagback_mtd: b"flagback",
                policy.master_mtd: b"master",
                policy.slave_mtd: b"slave",
            }
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

            def record_write(_telnet, remote, part, dev, size, method, erase_size, timeout=600) -> None:
                events.append(("write", part, dev, remote, size, method, erase_size))

            patch(sat, "_write_partition", record_write)

            def readback(_telnet, dev: str, timeout: int = 300) -> str:
                events.append(("readback", dev))
                if dev in readback_override:
                    return readback_override[dev]
                if dev == f"/dev/mtd{policy.slave_mtd}":
                    return slot_sha
                if dev == f"/dev/mtd{policy.flag_mtd}":
                    return flag_sha
                raise AssertionError(f"unexpected readback target: {dev}")

            patch(sat, "_remote_partition_sha", readback)
            patch(sat.ui, "enable", lambda: None)
            patch(sat.ui, "status", lambda *args, **kwargs: None)
            patch(sat.ui, "prompt", lambda _text: (events.append(("prompt", "y")) or "y"))

            try:
                result = sat.run(
                    host=access.host,
                    profile="xg040-md",
                    unattended=True,
                    dry_run=False,
                    reboot=False,
                    own_transcript=False,
                )
                return result, None, events
            except Exception as exc:
                return None, exc, events
        finally:
            for obj, name, value in reversed(old):
                setattr(obj, name, value)


def _writes(events: list[tuple]) -> list[tuple]:
    return [event for event in events if event[0] == "write"]


def test_exact_write_targets() -> None:
    policy = sat._policy("xg040-md")
    result, error, events = _drive_run()
    assert error is None
    assert result == 0

    writes = _writes(events)
    assert len(writes) == 2
    assert writes[0][1:3] == ("nsb_slave", f"/dev/mtd{policy.slave_mtd}")
    assert writes[1][1:3] == ("flag", f"/dev/mtd{policy.flag_mtd}")

    touched = {(event[1], event[2]) for event in writes}
    assert ("nsb_master", f"/dev/mtd{policy.master_mtd}") not in touched
    assert ("flagback", f"/dev/mtd{policy.flagback_mtd}") not in touched
    assert all(event[2] != f"/dev/mtd{policy.master_mtd}" for event in writes)
    assert all(event[2] != f"/dev/mtd{policy.flagback_mtd}" for event in writes)


def test_slave_readback_mismatch_aborts_before_selector() -> None:
    policy = sat._policy("xg040-md")
    bad = "0" * 64
    result, error, events = _drive_run(
        readback_override={f"/dev/mtd{policy.slave_mtd}": bad}
    )
    assert result is None
    assert isinstance(error, RuntimeError)
    assert "nsb_slave readback mismatch" in str(error)

    writes = _writes(events)
    assert len(writes) == 1
    assert writes[0][1:3] == ("nsb_slave", f"/dev/mtd{policy.slave_mtd}")
    assert not any(event[1] == "flag" for event in writes)
    assert not any(event[0] == "reboot" for event in events)


def test_flag_readback_mismatch_aborts() -> None:
    policy = sat._policy("xg040-md")
    bad = "f" * 64
    result, error, events = _drive_run(
        readback_override={f"/dev/mtd{policy.flag_mtd}": bad}
    )
    assert result is None
    assert isinstance(error, RuntimeError)
    assert "flag readback mismatch" in str(error)

    writes = _writes(events)
    assert len(writes) == 2
    assert writes[0][1:3] == ("nsb_slave", f"/dev/mtd{policy.slave_mtd}")
    assert writes[1][1:3] == ("flag", f"/dev/mtd{policy.flag_mtd}")
    assert not any(event[0] == "reboot" for event in events)


test_exact_write_targets()
test_slave_readback_mismatch_aborts_before_selector()
test_flag_readback_mismatch_aborts()
print("selftest_transition_write_safety: PASS")

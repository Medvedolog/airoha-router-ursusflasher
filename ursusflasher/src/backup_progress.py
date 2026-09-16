#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import threading
import time


def _human_bytes(value: float | int) -> str:
    value = max(0.0, float(value))
    if value >= 1024 * 1024:
        return f"{value / 1048576:.1f} MiB"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{int(value)} B"


def _partition_number(name: str) -> int | None:
    match = re.match(r"^mtd(\d+)_.*\.bin\.gz$", str(name))
    return int(match.group(1)) if match else None


def _progress_line(number: int, total: int, numbers: tuple[int, ...], size: int, rate: float, elapsed: int) -> str:
    try:
        stage_index = numbers.index(number) + 1
    except ValueError:
        stage_index = min(total, number + 1)
    completed = max(0, stage_index - 1)
    overall = int(completed * 100 / max(1, total))
    lang = os.environ.get("NOKIA_LANG", "ru").strip().lower()
    if lang == "en":
        return (
            f"[PROGRESS] {stage_index}/{total} · completed {overall}% of partitions · "
            f"mtd{number}: {_human_bytes(size)} gzip · {_human_bytes(rate)}/s · {elapsed}s"
        )
    return (
        f"[ПРОГРЕСС] {stage_index}/{total} · готово {overall}% разделов · "
        f"mtd{number}: {_human_bytes(size)} gzip · {_human_bytes(rate)}/с · {elapsed} с"
    )


def install(pb_module) -> None:
    """Add UI-only live progress to full stock TFTP backups.

    The authoritative progress source is TftpResult.bytes_transferred from the
    currently active PUT, not the destination directory. Some receiver paths do
    not publish the final .bin.gz until transfer completion; observing files can
    therefore lag one partition and report a bogus initial rate followed by 0 B/s.

    Transport, verification, retry and error semantics stay inside proven_backend.
    This decorator only observes the result object passed to receive_tftp_put().
    """
    original_backup = pb_module.backup_tftp
    original_receive = pb_module.receive_tftp_put
    if getattr(original_backup, "_ursus_live_progress", False):
        return

    numbers = tuple(int(x) for x in getattr(pb_module, "EXPECTED_NUMBERS", tuple(range(17))))
    total = max(1, len(numbers))
    active_backup = threading.local()

    def receive_with_progress(bind_ip, port, output, expected_name, allowed_host, ready, result, *args, **kwargs):
        number = _partition_number(expected_name)
        enabled = bool(getattr(active_backup, "enabled", False)) and number is not None and number in numbers
        if not enabled:
            return original_receive(bind_ip, port, output, expected_name, allowed_host, ready, result, *args, **kwargs)

        stop = threading.Event()
        started = time.monotonic()

        def monitor() -> None:
            last_bytes = int(getattr(result, "bytes_transferred", 0) or 0)
            last_time = started
            while not stop.wait(2.0):
                now = time.monotonic()
                current = int(getattr(result, "bytes_transferred", 0) or 0)
                dt = max(0.001, now - last_time)
                delta = max(0, current - last_bytes)
                # Print only while the current transfer has actually advanced.
                # The backend already emits its own WAIT/READY messages, so a
                # repeated 0 B/s heartbeat adds noise and looks like a stall.
                if delta > 0:
                    print(
                        _progress_line(number, total, numbers, current, delta / dt, int(now - started)),
                        flush=True,
                    )
                last_bytes = current
                last_time = now

        watcher = threading.Thread(target=monitor, name=f"ursus-tftp-progress-mtd{number}", daemon=True)
        watcher.start()
        try:
            return original_receive(bind_ip, port, output, expected_name, allowed_host, ready, result, *args, **kwargs)
        finally:
            stop.set()
            watcher.join(timeout=3)

    receive_with_progress._ursus_live_progress = True
    receive_with_progress._ursus_original = original_receive
    pb_module.receive_tftp_put = receive_with_progress

    def backup_with_progress(access, router_host, destination, *args, **kwargs):
        active_backup.enabled = True
        try:
            result = original_backup(access, router_host, destination, *args, **kwargs)
            lang = os.environ.get("NOKIA_LANG", "ru").strip().lower()
            print(
                f"[PROGRESS] {total}/{total} · completed 100% of partitions"
                if lang == "en"
                else f"[ПРОГРЕСС] {total}/{total} · готово 100% разделов",
                flush=True,
            )
            return result
        finally:
            active_backup.enabled = False

    backup_with_progress._ursus_live_progress = True
    backup_with_progress._ursus_original = original_backup
    pb_module.backup_tftp = backup_with_progress

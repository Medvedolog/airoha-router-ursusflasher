#!/usr/bin/env python3
from __future__ import annotations

import os
import threading
import time
from pathlib import Path


def _human_bytes(value: int) -> str:
    value = max(0, int(value))
    if value >= 1024 * 1024:
        return f"{value / 1048576:.1f} MiB"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value} B"


def _snapshot(destination: Path, numbers: tuple[int, ...]) -> tuple[int | None, int, int]:
    """Return active MTD, active compressed bytes and completed-file count.

    A TFTP receiver writes the .bin.gz file while the transfer is in progress,
    so the newest/highest currently changing file is a useful UI signal.  The
    byte count is deliberately labelled as gzip/compressed bytes: the final
    compression ratio is unknowable until the stream ends, so it must not be
    presented as a fake per-partition percentage.
    """
    found: list[tuple[int, Path]] = []
    for number in numbers:
        matches = sorted(destination.glob(f"mtd{number}_*.bin.gz"))
        if matches:
            found.append((number, matches[-1]))
    if not found:
        return None, 0, 0
    active_number, active_path = found[-1]
    try:
        size = active_path.stat().st_size
    except OSError:
        size = 0
    # The active file is not counted complete until the backend advances to the
    # next partition (or returns).  This keeps the stage percentage honest.
    completed = max(0, len(found) - 1)
    return active_number, size, completed


def install(pb_module) -> None:
    """Decorate proven_backend.backup_tftp with UI-only live progress.

    Transport, verification and error semantics remain entirely inside the
    proven backend.  This wrapper only observes local output-file growth.
    """
    original = pb_module.backup_tftp
    if getattr(original, "_ursus_live_progress", False):
        return

    numbers = tuple(int(x) for x in getattr(pb_module, "EXPECTED_NUMBERS", tuple(range(17))))
    total = max(1, len(numbers))

    def wrapped(access, router_host, destination, *args, **kwargs):
        destination = Path(destination)
        stop = threading.Event()
        started = time.monotonic()

        def monitor() -> None:
            last_number: int | None = None
            last_size = 0
            last_time = started
            # Give the backend a moment to create the first receiver file.
            while not stop.wait(2.0):
                number, size, completed = _snapshot(destination, numbers)
                if number is None:
                    continue
                now = time.monotonic()
                if number != last_number:
                    last_number = number
                    last_size = 0
                    last_time = now
                dt = max(0.001, now - last_time)
                delta = max(0, size - last_size)
                rate = delta / dt
                stage_index = numbers.index(number) + 1 if number in numbers else min(total, completed + 1)
                overall = int(completed * 100 / total)
                elapsed = int(now - started)
                lang = os.environ.get("NOKIA_LANG", "ru").strip().lower()
                if lang == "en":
                    text = (
                        f"[PROGRESS] {stage_index}/{total} · completed {overall}% of partitions · "
                        f"mtd{number}: {_human_bytes(size)} gzip · {_human_bytes(rate)}/s · {elapsed}s"
                    )
                else:
                    text = (
                        f"[ПРОГРЕСС] {stage_index}/{total} · готово {overall}% разделов · "
                        f"mtd{number}: {_human_bytes(size)} gzip · {_human_bytes(rate)}/с · {elapsed} с"
                    )
                print(text, flush=True)
                last_size = size
                last_time = now

        watcher = threading.Thread(target=monitor, name="ursus-backup-progress", daemon=True)
        watcher.start()
        try:
            result = original(access, router_host, destination, *args, **kwargs)
            lang = os.environ.get("NOKIA_LANG", "ru").strip().lower()
            print(
                f"[PROGRESS] {total}/{total} · completed 100% of partitions"
                if lang == "en"
                else f"[ПРОГРЕСС] {total}/{total} · готово 100% разделов",
                flush=True,
            )
            return result
        finally:
            stop.set()
            watcher.join(timeout=3)

    wrapped._ursus_live_progress = True
    wrapped._ursus_original = original
    pb_module.backup_tftp = wrapped

#!/usr/bin/env python3
from __future__ import annotations

import re


_ANSI_CSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")
_ANSI_OSC = re.compile(rb"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def _strip_ansi(data: bytes) -> bytes:
    clean = _ANSI_OSC.sub(b"", data)
    clean = _ANSI_CSI.sub(b"", clean)
    return clean.replace(b"\x1b", b"")


def install(backend) -> None:
    """Make RAM U-Boot prompt acquisition tolerant of Airoha boot-menu ANSI tails.

    RC18 on real AN7581 can render ``AN7581>`` immediately after leaving the
    interactive boot menu while terminal escape bytes remain after the prompt.
    The proven backend intentionally requires a line-bounded prompt and therefore
    used to miss that otherwise valid prompt, waiting until timeout before the
    RECOVERY_SAFE gate could run.

    Keep the original detector as the authority.  Only if it misses do we retry
    the exact same detector on a copy with ANSI control sequences removed.
    """
    current = getattr(backend, "_uboot_prompt_present", None)
    if current is None or getattr(current, "_ursus_ansi_prompt_fix", False):
        return

    original = current

    def tolerant(data: bytes) -> bool:
        if original(data):
            return True
        clean = _strip_ansi(bytes(data))
        return clean != data and original(clean)

    tolerant._ursus_ansi_prompt_fix = True
    tolerant._ursus_original = original
    backend._uboot_prompt_present = tolerant

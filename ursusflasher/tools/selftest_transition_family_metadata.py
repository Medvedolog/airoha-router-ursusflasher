#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import selftest_transition_expert_item4 as item4  # noqa: E402


def test_unknown_family_metadata_is_not_a_false_gate() -> None:
    old = item4._Access.family
    try:
        item4._Access.family = "unknown"
        result, events = item4._drive_run("n")
        assert result == 0
        assert any(event[0] == "prompt" for event in events)
    finally:
        item4._Access.family = old


def test_explicit_wrong_family_still_stops() -> None:
    old = item4._Access.family
    try:
        item4._Access.family = "mf"
        try:
            item4._drive_run("n")
        except RuntimeError as exc:
            assert "board profile mismatch" in str(exc)
        else:
            raise AssertionError("an explicit foreign stock family must stop before transition")
    finally:
        item4._Access.family = old


test_unknown_family_metadata_is_not_a_false_gate()
test_explicit_wrong_family_still_stops()
print("selftest_transition_family_metadata: PASS")

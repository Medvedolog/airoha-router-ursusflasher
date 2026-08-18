#!/usr/bin/env python3
"""Shared view of what counts as the shipped UrsusFlasher kit.

The repository tree and the release archive hold the same files: the archive is
the tree minus repository-side material. Keeping that definition in one place is
what lets `SHA256SUMS` mean the same thing in CI, in the release ZIP and on a
tester's disk.
"""
from __future__ import annotations

import pathlib

# Repository-side only: CI, its helper scripts, and git's own metadata. `work/`
# is the runtime scratch directory — it ships as an empty directory, never with
# content.
EXCLUDED_TOP = {".git", ".github", "work"}

MANIFEST_NAME = "SHA256SUMS"


def shipped_files(root: pathlib.Path) -> list[str]:
    """Every file the kit consists of, relative to *root*, sorted.

    `SHA256SUMS` itself is excluded: a manifest cannot list its own digest.
    """
    out: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        parts = rel.parts
        if parts[0] in EXCLUDED_TOP or parts[0].startswith(".git"):
            continue
        if "__pycache__" in parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if rel.as_posix() == MANIFEST_NAME:
            continue
        out.append(rel.as_posix())
    return sorted(out)


def read_manifest(root: pathlib.Path) -> dict[str, str]:
    """Parse `SHA256SUMS` into {relative path: lowercase digest}."""
    path = root / MANIFEST_NAME
    if not path.is_file():
        raise SystemExit(f"ERROR: {MANIFEST_NAME} is missing from {root}")

    listed: dict[str, str] = {}
    for raw in path.read_text(encoding="ascii").splitlines():
        if not raw.strip():
            continue
        try:
            digest, rel = raw.split("  ", 1)
        except ValueError:
            raise SystemExit(f"ERROR: malformed {MANIFEST_NAME} line: {raw!r}")
        rel = rel.removeprefix("./")
        if len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
            raise SystemExit(f"ERROR: malformed digest for {rel}")
        if rel in listed:
            raise SystemExit(f"ERROR: duplicate {MANIFEST_NAME} entry: {rel}")
        listed[rel] = digest.lower()
    return listed

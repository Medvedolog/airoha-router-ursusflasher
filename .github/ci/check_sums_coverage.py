#!/usr/bin/env python3
"""Verify SHA256SUMS lists exactly the shipped kit, and every digest matches.

`sha256sum -c` walks the manifest and stops there, so a file that was added and
never listed passes unnoticed. This checks the other direction too.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from kit import MANIFEST_NAME, read_manifest, shipped_files  # noqa: E402

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
listed = read_manifest(root)
actual = shipped_files(root)

missing = sorted(set(actual) - set(listed))
extra = sorted(set(listed) - set(actual))
if missing:
    print(f"ERROR: shipped files absent from {MANIFEST_NAME}:", *missing, sep="\n  ")
if extra:
    print(f"ERROR: {MANIFEST_NAME} references files that are not shipped:", *extra, sep="\n  ")
if missing or extra:
    raise SystemExit(1)

for rel in actual:
    digest = hashlib.sha256((root / rel).read_bytes()).hexdigest()
    if digest != listed[rel]:
        raise SystemExit(
            f"ERROR: SHA256 mismatch: {rel}\n  expected {listed[rel]}\n  actual   {digest}"
        )

print(f"{MANIFEST_NAME} exact coverage PASS: {len(actual)} files")

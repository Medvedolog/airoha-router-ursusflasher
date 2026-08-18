#!/usr/bin/env python3
"""Verify the payloads MANIFEST.json pins are the payloads actually shipped.

`SHA256SUMS` proves the tree is internally consistent — it would happily certify
a kit whose tcboot base was quietly swapped, as long as the manifest was
regenerated afterwards. These digests are different: they are the ones the
hardware run was performed against, written down in `MANIFEST.json`, and
`tcboot_builder` refuses to build against anything else.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
manifest = json.loads((root / "data/MANIFEST.json").read_text(encoding="utf-8"))


def check(desc: str, rel: str, expected_sha: str, expected_size: int | None) -> None:
    path = root / rel
    if not path.is_file():
        raise SystemExit(f"ERROR: {desc}: missing {rel}")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_size is not None and len(raw) != expected_size:
        raise SystemExit(f"ERROR: {desc}: size {len(raw)} != {expected_size}")
    if digest != expected_sha:
        raise SystemExit(f"ERROR: {desc}: SHA256\n  expected {expected_sha}\n  actual   {digest}")
    print(f"PASS {desc}: {len(raw)} {digest} {rel}")


sysupgrade = manifest["default_sysupgrade"]
check(
    "bundled OpenWrt sysupgrade",
    sysupgrade["file"],
    sysupgrade["sha256"],
    int(sysupgrade["size"]),
)

tcboot = manifest["tcboot"]
size = int(tcboot["size"])
check("tcboot base image", tcboot["base_file"], tcboot["base_sha256"], size)
check(
    "default personalized tcboot",
    tcboot["default_personalized_file"],
    tcboot["default_personalized_sha256"],
    size,
)

# The layout is the whole reason tcboot survives its own sysupgrade: the first
# 1 MiB has to sit outside UBI, and UBI has to end at the end of the 256 MiB NAND.
layout = tcboot["layout"]
nand = int(manifest["target"]["nand_size"])
if layout["tcboot"] != [0, size]:
    raise SystemExit(f"ERROR: tcboot layout slot {layout['tcboot']} != [0, {size}]")
if layout["env"] != [size, 2 * size]:
    raise SystemExit(f"ERROR: tcboot env slot {layout['env']} != [{size}, {2 * size}]")
if layout["ubi"] != [2 * size, nand]:
    raise SystemExit(f"ERROR: UBI region {layout['ubi']} != [{2 * size}, {nand}]")

print(f"Pinned payload audit PASS: UBI 0x{2 * size:08x}..0x{nand:08x}, tcboot outside it")

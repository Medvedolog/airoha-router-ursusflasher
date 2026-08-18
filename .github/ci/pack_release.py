#!/usr/bin/env python3
"""Pack the staged kit into the release ZIP, deterministically.

Same tree in, same bytes out: fixed timestamps, sorted entries, explicit modes.
Two builds of one commit produce one digest, so a tester quoting a SHA256 is
quoting the commit and not the afternoon it was built on.

Usage: pack_release.py <stage-parent> <root-name> <output.zip>
"""
from __future__ import annotations

import pathlib
import stat
import sys
import zipfile

stage_parent = pathlib.Path(sys.argv[1]).resolve()
root_name = sys.argv[2]
zip_path = pathlib.Path(sys.argv[3])
root = stage_parent / root_name

# Fixed DOS timestamp; the ZIP format cannot store one before 1980.
EPOCH = (1980, 1, 1, 0, 0, 0)


def add_dir(zf: zipfile.ZipFile, arc: str) -> None:
    info = zipfile.ZipInfo(arc.rstrip("/") + "/", EPOCH)
    info.create_system = 3  # Unix, so the stored mode is honoured on extract
    info.external_attr = (0o755 | stat.S_IFDIR) << 16
    zf.writestr(info, b"")


with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    add_dir(zf, root_name)
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(stage_parent).as_posix()):
        arc = path.relative_to(stage_parent).as_posix()
        if path.is_dir():
            add_dir(zf, arc)
            continue
        info = zipfile.ZipInfo(arc, EPOCH)
        info.create_system = 3
        info.external_attr = ((path.stat().st_mode & 0o777) | stat.S_IFREG) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

print(f"packed {zip_path} ({zip_path.stat().st_size} bytes)")

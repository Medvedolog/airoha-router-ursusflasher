#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

VERSION = "0.1.0-xg140-profile1"

IDENTITY_FILES = (
    "cmd/ursusweb.c",
    "cmd/ursusubi.c",
    "cmd/ursusdispatch.c",
    "cmd/ursusstock.c",
    "cmd/ursusupdate.c",
    "include/ursusweb_ui.inc",
)

REPLACEMENTS = (
    ("Nokia XG-040G-MD", "Bell XG-140G-MD"),
    ("Nokia_XG-040G-MD", "Bell_XG-140G-MD"),
    ("nokia_xg-040g-md", "bell_xg-140g-md"),
    ("nokia,xg-040g-md-ubi", "bell,xg-140g-md"),
    ("nokia,xg-040g-md", "bell,xg-140g-md"),
    ("xg-040g-md", "xg-140g-md"),
    ("NOKIA_XG040GMD_STOCK", "BELL_XG140GMD_STOCK"),
    ("XG040GMC2P5G", "XG140GMC2P5G"),
)


def rewrite_identity(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text


def transform(root: Path) -> None:
    root = root.resolve()
    for rel in IDENTITY_FILES:
        path = root / rel
        if not path.is_file():
            raise SystemExit(f"XG140 MD-derived source missing: {rel}")
        path.write_text(rewrite_identity(path.read_text(encoding="utf-8")), encoding="utf-8")

    dispatch = (root / "cmd/ursusdispatch.c").read_text(encoding="utf-8")
    stock = (root / "cmd/ursusstock.c").read_text(encoding="utf-8")
    if 'run_command("ursusstockboot", 0)' not in dispatch:
        raise SystemExit("XG140 derivation lost proven MD stock boot dispatch")
    if "ursusstockboot" not in stock:
        raise SystemExit("XG140 derivation lost proven MD StockBridge command")

    version_h = root / "include/ursus_version.h"
    text = version_h.read_text(encoding="utf-8")
    text, count = re.subn(r'#define URSUS_VERSION "[^"]+"', f'#define URSUS_VERSION "{VERSION}"', text, count=1)
    if count != 1:
        raise SystemExit("XG140 version header anchor missing")
    version_h.write_text(text, encoding="utf-8")
    (root / ".scmversion").write_text(f"-UrsusBoot-{VERSION}\n", encoding="ascii")

    leaks: list[str] = []
    for rel in IDENTITY_FILES:
        data = (root / rel).read_text(encoding="utf-8")
        for token in ("Nokia XG-040G-MD", "nokia,xg-040g-md", "nokia_xg-040g-md", "XG040GMC2P5G"):
            if token in data:
                leaks.append(f"{rel}:{token}")
    if leaks:
        raise SystemExit("XG140 MD identity leak: " + ", ".join(leaks))

    print("XG140_MD_DERIVATION=PASS core=MD stockbridge=preserved policy_delta=identity+dts+profile")


def main() -> int:
    ap = argparse.ArgumentParser(description="Derive the XG140 UrsusBoot source from the proven MD core")
    ap.add_argument("root", type=Path)
    args = ap.parse_args()
    transform(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

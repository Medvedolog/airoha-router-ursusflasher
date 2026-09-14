#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

VERSION = "0.1.0-xg140-profile1"

# XG140 is intentionally derived from the proven MD implementation.  Identity
# changes are therefore allowed broadly across source/config text, while board
# behaviour remains isolated in the selected board-policy header and DTS.
IDENTITY_ROOTS = (
    "arch/arm/dts",
    "board",
    "cmd",
    "defenvs",
    "drivers",
    "include",
)

REPLACEMENTS = (
    ("Nokia XG-040G-MD", "Bell XG-140G-MD"),
    ("Nokia_XG-040G-MD", "Bell_XG-140G-MD"),
    ("nokia_xg-040g-md", "bell_xg-140g-md"),
    ("nokia,xg-040g-md-ubi", "bell,xg-140g-md"),
    ("nokia,xg-040g-md", "bell,xg-140g-md"),
    ("nokia-xg-040g-md", "bell-xg-140g-md"),
    ("xg-040g-md", "xg-140g-md"),
    ("NOKIA_XG040GMD_STOCK", "BELL_XG140GMD_STOCK"),
    ("XG040GMC2P5G", "XG140GMC2P5G"),
)

LEAK_TOKENS = tuple(old for old, _new in REPLACEMENTS)


def rewrite_identity(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text


def rewrite_tree(root: Path) -> tuple[int, int]:
    scanned = 0
    changed = 0
    for dirname in IDENTITY_ROOTS:
        base = root / dirname
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            try:
                raw = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            scanned += 1
            new = rewrite_identity(raw)
            if new != raw:
                path.write_text(new, encoding="utf-8")
                changed += 1
    return scanned, changed


def find_leaks(root: Path) -> list[str]:
    leaks: list[str] = []
    for dirname in IDENTITY_ROOTS:
        base = root / dirname
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            try:
                data = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for token in LEAK_TOKENS:
                if token in data:
                    leaks.append(f"{path.relative_to(root)}:{token}")
    return leaks


def transform(root: Path) -> None:
    root = root.resolve()
    required = (
        "cmd/ursusweb.c",
        "cmd/ursusdispatch.c",
        "cmd/ursusstock.c",
        "include/ursusweb_ui.inc",
        "include/ursus_version.h",
    )
    for rel in required:
        if not (root / rel).is_file():
            raise SystemExit(f"XG140 MD-derived source missing: {rel}")

    scanned, changed = rewrite_tree(root)

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

    leaks = find_leaks(root)
    if leaks:
        preview = ", ".join(leaks[:20])
        more = f" (+{len(leaks) - 20} more)" if len(leaks) > 20 else ""
        raise SystemExit("XG140 MD identity leak: " + preview + more)

    print(
        "XG140_MD_DERIVATION=PASS "
        f"core=MD stockbridge=preserved identity_files_scanned={scanned} "
        f"identity_files_changed={changed} policy_delta=identity+dts+profile"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Derive the XG140 UrsusBoot source from the proven MD core")
    ap.add_argument("root", type=Path)
    args = ap.parse_args()
    transform(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

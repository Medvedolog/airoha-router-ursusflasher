#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

ROLES = {
    "persistent": {
        "bootcmd": "bootcmd=ursusdispatch",
        "marker": "URSUS_RUNTIME_ROLE=persistent",
    },
    "ram-recovery": {
        "bootcmd": "bootcmd=ursusweb;true",
        "marker": "URSUS_RUNTIME_ROLE=ram-recovery",
    },
}

SEARCH_ROOTS = ("defenvs", "include", "board")
BASE_BOOTCMD = "bootcmd=ursusdispatch"


def iter_text_files(root: Path):
    for rel in SEARCH_ROOTS:
        base = root / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            yield path, text


def find_anchor(root: Path, token: str) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for path, text in iter_text_files(root):
        if token in text:
            found.append((path, text))
    return found


def write_role_header(root: Path, role: str) -> None:
    cfg = ROLES[role]
    header = root / "include" / "ursus_runtime_role.h"
    header.write_text(
        "/* SPDX-License-Identifier: GPL-2.0+ */\n"
        "#ifndef __URSUS_RUNTIME_ROLE_H__\n"
        "#define __URSUS_RUNTIME_ROLE_H__\n\n"
        f'#define URSUS_RUNTIME_ROLE_ID "{role}"\n'
        f'#define URSUS_RUNTIME_ROLE_MARKER "{cfg["marker"]}"\n'
        f'#define URSUS_RUNTIME_BOOTCMD "{cfg["bootcmd"]}"\n\n'
        "#endif\n",
        encoding="utf-8",
    )


def apply(root: Path, role: str) -> None:
    if role not in ROLES:
        raise SystemExit(f"unknown UrsusBoot runtime role: {role}")

    matches = find_anchor(root, BASE_BOOTCMD)
    if len(matches) != 1:
        locations = ", ".join(str(p.relative_to(root)) for p, _ in matches) or "none"
        raise SystemExit(
            f"runtime role bootcmd anchor expected exactly once, found {len(matches)}: {locations}"
        )

    path, text = matches[0]
    target = ROLES[role]["bootcmd"]
    if role == "ram-recovery":
        text = text.replace(BASE_BOOTCMD, target, 1)
        path.write_text(text, encoding="utf-8")

    write_role_header(root, role)

    # Verify source-level role selection. No post-build binary patching is allowed.
    after = []
    for p, data in iter_text_files(root):
        for token in ("bootcmd=ursusdispatch", "bootcmd=ursusweb;true"):
            if token in data:
                after.append((p, token))
    wanted = target
    wanted_hits = [(p, t) for p, t in after if t == wanted]
    forbidden = "bootcmd=ursusweb;true" if role == "persistent" else "bootcmd=ursusdispatch"
    forbidden_hits = [(p, t) for p, t in after if t == forbidden]
    if len(wanted_hits) != 1 or forbidden_hits:
        raise SystemExit(
            f"runtime role verification failed role={role} wanted={len(wanted_hits)} forbidden={len(forbidden_hits)}"
        )

    print(
        f"URSUS_RUNTIME_ROLE_APPLY=PASS role={role} bootcmd={wanted} "
        f"source={path.relative_to(root)} mode=source-level"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply an orthogonal UrsusBoot runtime role")
    ap.add_argument("root", type=Path)
    ap.add_argument("--role", choices=sorted(ROLES), required=True)
    args = ap.parse_args()
    root = args.root.resolve()
    apply(root, args.role)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

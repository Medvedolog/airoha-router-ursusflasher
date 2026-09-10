#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

ASSIGN_RE = re.compile(r"^(CONFIG_[A-Za-z0-9_]+)=.*$")
UNSET_RE = re.compile(r"^# (CONFIG_[A-Za-z0-9_]+) is not set$")


def symbol(line: str) -> str | None:
    m = ASSIGN_RE.match(line)
    if m:
        return m.group(1)
    m = UNSET_RE.match(line)
    if m:
        return m.group(1)
    return None


def read_fragment(path: Path) -> dict[str, str]:
    desired: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or (line.startswith("#") and not UNSET_RE.match(line)):
            continue
        name = symbol(line)
        if not name:
            raise SystemExit(f"{path}: unsupported config line: {raw!r}")
        desired[name] = line
    return desired


def parse_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        name = symbol(raw.strip())
        if name:
            values[name] = raw.strip()
    return values


def apply(config: Path, fragments: list[Path]) -> None:
    desired: dict[str, str] = {}
    for fragment in fragments:
        desired.update(read_fragment(fragment))

    lines = config.read_text(encoding="utf-8").splitlines()
    emitted: set[str] = set()
    out: list[str] = []
    for raw in lines:
        name = symbol(raw.strip())
        if name and name in desired:
            if name not in emitted:
                out.append(desired[name])
                emitted.add(name)
            continue
        out.append(raw)

    missing = [name for name in desired if name not in emitted]
    if missing:
        if out and out[-1] != "":
            out.append("")
        out.append("# UrsusBoot merged configuration fragments")
        out.extend(desired[name] for name in missing)

    config.write_text("\n".join(out) + "\n", encoding="utf-8")


def check(config: Path, fragments: list[Path]) -> None:
    desired: dict[str, str] = {}
    for fragment in fragments:
        desired.update(read_fragment(fragment))
    actual = parse_config(config)
    errors = []
    for name, expected in desired.items():
        got = actual.get(name)
        # Kconfig may omit an invisible symbol entirely instead of emitting
        # '# CONFIG_FOO is not set'. Semantically both states are disabled.
        if UNSET_RE.match(expected) and got is None:
            continue
        if got != expected:
            errors.append(f"{name}: expected {expected!r}, got {got!r}")
    if errors:
        raise SystemExit("Kconfig fragment contract failed:\n  " + "\n  ".join(errors))


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply/check deterministic U-Boot .config fragments")
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("fragments", nargs="+", type=Path)
    args = ap.parse_args()
    for path in [args.config, *args.fragments]:
        if not path.is_file():
            raise SystemExit(f"missing file: {path}")
    if args.check_only:
        check(args.config, args.fragments)
    else:
        apply(args.config, args.fragments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

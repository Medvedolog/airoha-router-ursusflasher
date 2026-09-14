#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

FIELDS = (
    "soc",
    "vendor",
    "model",
    "compatible",
    "board_policy_header",
    "boot_policy",
    "layout_policy",
    "environment_policy",
    "derivation",
)


def load_registry(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not isinstance(data.get("profiles"), dict):
        raise SystemExit(f"unsupported board profile registry: {path}")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve modular UrsusBoot Airoha board profiles")
    ap.add_argument("--registry", type=Path, required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--config-dir", type=Path)
    ap.add_argument("--field", choices=FIELDS)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    data = load_registry(args.registry)
    try:
        profile = data["profiles"][args.profile]
    except KeyError:
        known = ", ".join(sorted(data["profiles"]))
        raise SystemExit(f"unknown UrsusBoot board profile {args.profile!r}; known: {known}")

    fragments = profile.get("fragments")
    if not isinstance(fragments, list) or not fragments:
        raise SystemExit(f"profile {args.profile!r} has no fragments")

    if args.config_dir:
        resolved = []
        for name in fragments:
            path = args.config_dir / name
            if not path.is_file():
                raise SystemExit(f"profile {args.profile!r}: missing fragment {path}")
            resolved.append(str(path))
        profile = dict(profile)
        profile["fragments"] = resolved

    if args.field:
        value = profile.get(args.field)
        if value is None:
            raise SystemExit(f"profile {args.profile!r} has no field {args.field!r}")
        print(value)
    elif args.json:
        print(json.dumps(profile, sort_keys=True, separators=(",", ":")))
    else:
        print("\n".join(profile["fragments"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

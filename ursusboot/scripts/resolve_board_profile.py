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
    "default_role",
    "runtime_role",
)


def load_registry(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not isinstance(data.get("profiles"), dict):
        raise SystemExit(f"unsupported board profile registry: {path}")
    if not isinstance(data.get("runtime_roles"), dict):
        raise SystemExit(f"board profile registry has no runtime_roles: {path}")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve modular UrsusBoot Airoha board profiles")
    ap.add_argument("--registry", type=Path, required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--role", help="orthogonal runtime role; defaults to profile default_role")
    ap.add_argument("--config-dir", type=Path)
    ap.add_argument("--field", choices=FIELDS)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    data = load_registry(args.registry)
    try:
        profile = dict(data["profiles"][args.profile])
    except KeyError:
        known = ", ".join(sorted(data["profiles"]))
        raise SystemExit(f"unknown UrsusBoot board profile {args.profile!r}; known: {known}")

    fragments = profile.get("fragments")
    if not isinstance(fragments, list) or not fragments:
        raise SystemExit(f"profile {args.profile!r} has no fragments")

    default_role = profile.get("default_role")
    allowed_roles = profile.get("allowed_roles")
    if not isinstance(default_role, str) or not isinstance(allowed_roles, list) or not allowed_roles:
        raise SystemExit(f"profile {args.profile!r} has invalid runtime role contract")
    role = args.role or default_role
    if role not in allowed_roles:
        raise SystemExit(
            f"profile {args.profile!r} does not allow runtime role {role!r}; "
            f"allowed: {', '.join(allowed_roles)}"
        )
    if role not in data["runtime_roles"]:
        raise SystemExit(f"profile {args.profile!r} references unknown runtime role {role!r}")

    profile["runtime_role"] = role
    profile["runtime_role_config"] = data["runtime_roles"][role]

    if args.config_dir:
        resolved = []
        for name in fragments:
            path = args.config_dir / name
            if not path.is_file():
                raise SystemExit(f"profile {args.profile!r}: missing fragment {path}")
            resolved.append(str(path))
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

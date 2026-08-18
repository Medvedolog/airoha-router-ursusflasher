#!/usr/bin/env python3
"""Verify every place the release states its own version agrees with the rest.

A kit that calls itself 0.1.0-md-lab1fix10 in `VERSION` and something else in
`MANIFEST.json` is worse than one with no version at all: a tester reporting a
bug would name a build that never existed. Prints the resolved version on the
last line so the workflow can capture it.
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()

version = (root / "VERSION").read_text(encoding="utf-8").strip()
manifest = json.loads((root / "data/MANIFEST.json").read_text(encoding="utf-8"))
caps = json.loads((root / "data/FIRMWARE_CAPABILITIES.json").read_text(encoding="utf-8"))

# master.py is read, not imported: importing it would start the wizard.
app_version = build_tag = None
for node in ast.parse((root / "data/master.py").read_text(encoding="utf-8")).body:
    if not isinstance(node, ast.Assign):
        continue
    for target in node.targets:
        if not isinstance(target, ast.Name):
            continue
        if target.id == "APP_VERSION":
            app_version = ast.literal_eval(node.value)
        elif target.id == "BUILD_TAG":
            build_tag = ast.literal_eval(node.value)

declared = {
    "VERSION": version,
    "data/VERSION": (root / "data/VERSION").read_text(encoding="utf-8").strip(),
    "master.py APP_VERSION": app_version,
    "MANIFEST.version": manifest.get("version"),
    "FIRMWARE_CAPABILITIES.version": caps.get("version"),
}
for key, value in declared.items():
    print(f"{key}: {value}")

if any(value != version for value in declared.values()):
    raise SystemExit("ERROR: release version metadata is inconsistent")

expected_tag = f"ursusflasher-{version}"
if build_tag != expected_tag:
    raise SystemExit(f"ERROR: BUILD_TAG {build_tag!r} != {expected_tag!r}")

if manifest.get("project") != "UrsusFlasher":
    raise SystemExit(f"ERROR: MANIFEST.project {manifest.get('project')!r} != 'UrsusFlasher'")

print(f"Release identity PASS: {version} ({expected_tag})")
print(version)

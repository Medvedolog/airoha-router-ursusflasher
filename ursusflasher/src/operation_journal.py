#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
KIT = HERE.parent.parent if (HERE.parent.parent / "config").is_dir() else HERE.parent
DEFAULT_DIR = (KIT if (KIT / "config").is_dir() else HERE.parent) / "work" / "journal"

OPEN_STATES = {"PREPARED", "IN_PROGRESS", "COMPLETION_PROVEN"}
TERMINAL_POST = {"EXPECTED_STATE_MATCH", "EXPECTED_STATE_MISMATCH"}


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _atomic_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, path)
        if os.name != "nt":
            try:
                dfd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            except OSError:
                pass
    finally:
        temp.unlink(missing_ok=True)


def _path(operation_id: str, directory: Path | None = None) -> Path:
    root = directory or DEFAULT_DIR
    return root / f"{operation_id}.json"


def prepare(*, write_class: str, candidate_sha256: str | None = None,
            expected_artifact_identity: dict[str, Any] | None = None,
            target_device_binding: dict[str, Any] | None = None,
            facts: dict[str, Any] | None = None,
            directory: Path | None = None) -> dict[str, Any]:
    operation_id = uuid.uuid4().hex
    rec: dict[str, Any] = {
        "schema": 1,
        "operation_id": operation_id,
        "created_at": _utc(),
        "updated_at": _utc(),
        "record_state": "OPEN",
        "write_class": write_class,
        "candidate_sha256": candidate_sha256,
        "expected_artifact_identity": expected_artifact_identity,
        "target_device_binding": target_device_binding,
        "observed_device_binding": None,
        "transaction_state": "NOT_STARTED",
        "postcondition_state": "NOT_CHECKED",
        "facts": facts or {},
        "failure": None,
    }
    _atomic_json(_path(operation_id, directory), rec)
    return rec


def load(operation_id: str, directory: Path | None = None) -> dict[str, Any]:
    path = _path(operation_id, directory)
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"operation journal is unreadable: {path}: {exc}") from exc
    if obj.get("operation_id") != operation_id:
        raise RuntimeError(f"operation journal id mismatch: {path}")
    return obj


def update(operation_id: str, *, directory: Path | None = None, **facts: Any) -> dict[str, Any]:
    rec = load(operation_id, directory)
    allowed = {
        "observed_device_binding", "transaction_state", "postcondition_state",
        "candidate_sha256", "expected_artifact_identity", "target_device_binding",
        "actual_artifact_identity", "completion_proof_time", "readback_result",
        "record_state", "superseded_by", "failure",
    }
    unknown = set(facts) - allowed
    if unknown:
        raise ValueError(f"journal fields not allowed: {sorted(unknown)}")
    rec.update(facts)
    rec["updated_at"] = _utc()
    if rec.get("postcondition_state") in TERMINAL_POST:
        rec["record_state"] = "CLOSED"
    _atomic_json(_path(operation_id, directory), rec)
    return rec


def list_unclosed(directory: Path | None = None) -> list[dict[str, Any]]:
    root = directory or DEFAULT_DIR
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if rec.get("record_state") == "OPEN":
            out.append(rec)
    return out


def _binding_facts(binding: dict[str, Any] | None) -> dict[str, str]:
    if not binding:
        return {}
    stable: dict[str, str] = {}
    for key in ("factory_mac", "serial_number", "g984_serial", "model", "soc"):
        value = binding.get(key)
        if value not in (None, "", "UNKNOWN"):
            stable[key] = str(value).strip().upper()
    return stable


def _binding_proven_mismatch(target_binding: dict[str, Any] | None,
                             observed_binding: dict[str, Any] | None) -> bool:
    """Return true only when at least one shared stable fact positively conflicts.

    Missing facts, extra observed facts, and a device that could not be identified
    are unresolved states, not proof that a different device is attached.
    """
    target = _binding_facts(target_binding)
    observed = _binding_facts(observed_binding)
    common = set(target) & set(observed)
    return any(target[key] != observed[key] for key in common)


def abandon_on_proven_mismatch(operation_id: str, observed_device_binding: dict[str, Any],
                                *, directory: Path | None = None) -> tuple[bool, dict[str, Any]]:
    rec = load(operation_id, directory)
    rec["observed_device_binding"] = observed_device_binding
    if _binding_proven_mismatch(rec.get("target_device_binding"), observed_device_binding):
        rec["record_state"] = "ABANDONED"
        rec["updated_at"] = _utc()
        _atomic_json(_path(operation_id, directory), rec)
        return True, rec
    rec["updated_at"] = _utc()
    _atomic_json(_path(operation_id, directory), rec)
    return False, rec


def supersede(operation_id: str, new_operation_id: str, *, directory: Path | None = None) -> dict[str, Any]:
    rec = load(operation_id, directory)
    rec["record_state"] = "ABANDONED"
    rec["superseded_by"] = new_operation_id
    rec["updated_at"] = _utc()
    _atomic_json(_path(operation_id, directory), rec)
    return rec


def record_failure(operation_id: str, *, stage: str, error_code: str | None = None,
                   error_rc: int | None = None, detail: str | None = None,
                   transaction_state: str | None = None,
                   status_snapshot: str | None = None, diagnostic_bundle: str | None = None,
                   directory: Path | None = None) -> dict[str, Any]:
    failure = {
        "observed_at": _utc(),
        "stage": stage,
        "error_code": error_code,
        "error_rc": error_rc,
        "detail": detail,
        "transaction_state": transaction_state,
        "status_snapshot": status_snapshot,
        "diagnostic_bundle": diagnostic_bundle,
    }
    return update(operation_id, directory=directory, failure=failure)

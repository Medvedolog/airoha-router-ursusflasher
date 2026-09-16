#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path


def _human_size(value: int) -> str:
    value = max(0, int(value))
    if value >= 1024 * 1024:
        return f"{value / 1048576:.1f} MiB"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value} B"


def _short(value: object, length: int = 12) -> str:
    text = str(value or "").strip()
    return text[:length] if text else "unknown"


def install(sat) -> None:
    """Add operator-visible tracing to the stock A/B TRANSITION transaction.

    This module is UI-only. It decorates the real transition backend and never
    changes target selection, write order, writer/transport fallback rules or
    readback acceptance. Messages are derived from the arguments/results of the
    actual backend calls so the console cannot claim a different target than the
    one being used.
    """
    if getattr(sat, "_ursus_operator_trace", False):
        return

    original_load = sat._load_payload
    original_build_slot = sat.build_transition_slot
    original_build_flag = sat.build_activation_flag
    original_write = sat._write_partition
    original_readback = sat._remote_partition_sha

    def load_payload(policy):
        data, meta = original_load(policy)
        source_commit = _short(meta.get("source_commit"))
        sat.ui.status(
            "INFO",
            sat.pb.tr(
                f"TRANSITION payload: {policy.payload_name}; {_human_size(len(data))}; SHA256 {hashlib.sha256(data).hexdigest()}; source {source_commit}.",
                f"TRANSITION payload: {policy.payload_name}; {_human_size(len(data))}; SHA256 {hashlib.sha256(data).hexdigest()}; source {source_commit}.",
            ),
        )
        sat.ui.status(
            "INFO",
            sat.pb.tr(
                f"Роль payload: {meta.get('transition_entry', 'unknown')}; итоговая цель: {meta.get('final_target', 'unknown')}.",
                f"Payload role: {meta.get('transition_entry', 'unknown')}; final target: {meta.get('final_target', 'unknown')}.",
            ),
        )
        return data, meta

    def build_slot(stock_slot: bytes, linux_image: bytes, policy=None):
        if policy is None:
            candidate, meta = original_build_slot(stock_slot, linux_image)
            policy_obj = getattr(sat, "MD_POLICY", None)
        else:
            candidate, meta = original_build_slot(stock_slot, linux_image, policy)
            policy_obj = policy
        source_sha = hashlib.sha256(stock_slot).hexdigest()
        candidate_sha = hashlib.sha256(candidate).hexdigest()
        target_mtd = getattr(policy_obj, "slave_mtd", "?")
        sat.ui.status(
            "INFO",
            sat.pb.tr(
                f"Собираю индивидуальный stock-compatible SLOT2 из backup этого роутера: nsb_slave/mtd{target_mtd} SHA256 {source_sha}.",
                f"Building a per-device stock-compatible SLOT2 from this router backup: nsb_slave/mtd{target_mtd} SHA256 {source_sha}.",
            ),
        )
        sat.ui.status(
            "READY",
            sat.pb.tr(
                f"Индивидуальный SLOT2 собран: SHA256 {candidate_sha}; FIP/HDR2/FIT оболочка сохранена, TRANSITION kernel/hash обновлены.",
                f"Per-device SLOT2 built: SHA256 {candidate_sha}; FIP/HDR2/FIT envelope preserved, TRANSITION kernel/hash updated.",
            ),
        )
        return candidate, meta

    def build_flag(flag: bytes, target: int, policy=None):
        if policy is None:
            candidate, meta = original_build_flag(flag, target)
            policy_obj = getattr(sat, "MD_POLICY", None)
        else:
            candidate, meta = original_build_flag(flag, target, policy)
            policy_obj = policy
        flag_mtd = getattr(policy_obj, "flag_mtd", "?")
        master_mtd = getattr(policy_obj, "master_mtd", "?")
        flagback_mtd = getattr(policy_obj, "flagback_mtd", "?")
        sat.ui.status(
            "INFO",
            sat.pb.tr(
                f"Selector-кандидат собран из backup flag: target active={target}; запись будет только в flag/mtd{flag_mtd}.",
                f"Selector candidate built from backed-up flag: target active={target}; only flag/mtd{flag_mtd} will be written.",
            ),
        )
        sat.ui.status(
            "INFO",
            sat.pb.tr(
                f"Защитный контракт: nsb_master/mtd{master_mtd} и flagback/mtd{flagback_mtd} не записываются.",
                f"Safety contract: nsb_master/mtd{master_mtd} and flagback/mtd{flagback_mtd} are not written.",
            ),
        )
        return candidate, meta

    def write_partition(telnet, remote: str, part: str, dev: str, size: int, method: str, erase_size: int, timeout: int = 600):
        step = "1/2" if part == "nsb_slave" else "2/2" if part == "flag" else "?"
        sat.ui.status(
            "ACTION",
            sat.pb.tr(
                f"NAND WRITE {step}: {part} -> {dev}; {_human_size(size)}; writer={method}; source={Path(remote).name}.",
                f"NAND WRITE {step}: {part} -> {dev}; {_human_size(size)}; writer={method}; source={Path(remote).name}.",
            ),
        )
        sat.ui.status(
            "WAIT",
            sat.pb.tr(
                f"Идёт erase/write/sync {part}; writer после начала не переключается.",
                f"Erase/write/sync in progress for {part}; writer will not switch after start.",
            ),
        )
        result = original_write(telnet, remote, part, dev, size, method, erase_size, timeout=timeout)
        sat.ui.status(
            "READY",
            sat.pb.tr(
                f"Команда записи {part} завершилась успешно; начинаю полное обратное чтение раздела.",
                f"{part} write command completed successfully; starting full partition readback.",
            ),
        )
        return result

    def readback(telnet, dev: str, timeout: int = 300):
        sat.ui.status(
            "WAIT",
            sat.pb.tr(
                f"Полное обратное чтение {dev} -> SHA256; читается весь раздел, это может занять время.",
                f"Full readback {dev} -> SHA256; the whole partition is being read and may take some time.",
            ),
        )
        got = original_readback(telnet, dev, timeout=timeout)
        sat.ui.status(
            "READY",
            sat.pb.tr(
                f"Readback {dev}: SHA256 {got}.",
                f"Readback {dev}: SHA256 {got}.",
            ),
        )
        return got

    sat._load_payload = load_payload
    sat.build_transition_slot = build_slot
    sat.build_activation_flag = build_flag
    sat._write_partition = write_partition
    sat._remote_partition_sha = readback
    sat._ursus_operator_trace = True

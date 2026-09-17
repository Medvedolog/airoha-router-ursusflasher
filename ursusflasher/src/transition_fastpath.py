from __future__ import annotations

import os
import re
import shlex
import time
from pathlib import Path

import console_ui as ui
import proven_backend as pb


_INSTALLED = False


def _yes_default(prompt_ru: str, prompt_en: str) -> bool:
    ans = ui.prompt(pb.tr(prompt_ru, prompt_en)).strip().lower()
    return ans not in ("н", "нет", "n", "no")


def _latest_local_backup(work: Path) -> Path | None:
    found = [p for p in work.glob("*/full-stock-backup") if p.is_dir()]
    if not found:
        return None
    return max(found, key=lambda p: p.stat().st_mtime)


def _choose_existing_backup(mod) -> Path:
    env = os.environ.get("URSUS_TRANSITION_BACKUP", "").strip().strip('"')
    default = Path(env).expanduser() if env else _latest_local_backup(mod.WORK)
    shown = str(default) if default else ""
    raw = ui.prompt(pb.tr(
        f"Путь к уже проверенному full-stock-backup [{shown}]: " if shown else "Путь к уже проверенному full-stock-backup: ",
        f"Path to an already verified full-stock-backup [{shown}]: " if shown else "Path to an already verified full-stock-backup: ",
    )).strip().strip('"')
    path = Path(raw).expanduser() if raw else default
    if path is None or not path.is_dir():
        raise RuntimeError(pb.tr(
            "Для пропуска нового backup нужен существующий каталог full-stock-backup.",
            "Skipping a new backup requires an existing full-stock-backup directory.",
        ))
    return path.resolve()


def _adopt_telnet(dst, src) -> None:
    """Keep the caller's Telnet object identity while replacing a dead session."""
    if dst is src:
        return
    try:
        dst.close()
    except Exception:
        pass
    if not hasattr(dst, "__dict__") or not hasattr(src, "__dict__"):
        raise RuntimeError("Telnet reconnect cannot preserve session object identity")
    dst.__dict__.clear()
    dst.__dict__.update(src.__dict__)


def _reconnect_same_session(access, telnet, family: str) -> None:
    last = None
    for attempt in range(1, 4):
        try:
            ui.status("WAIT", pb.tr(
                f"Сетевая коллизия: переподключаю stock Telnet, попытка {attempt}/3.",
                f"Network collision: reconnecting stock Telnet, attempt {attempt}/3.",
            ))
            fresh = pb.login_root_family(access, family, allow_service_provisioning=True)
            rc, out = fresh.command_clean("id -u", timeout=20)
            if rc or not re.search(r"(?:^|\n)0(?:\n|$)", out.strip() + "\n"):
                fresh.close()
                raise RuntimeError("UID 0 not confirmed after reconnect")
            _adopt_telnet(telnet, fresh)
            ui.status("READY", pb.tr("Stock Telnet восстановлен.", "Stock Telnet reconnected."))
            return
        except Exception as exc:
            last = exc
            pb._write_session_only(f"[TRANSITION-RECONNECT] attempt={attempt} error={exc!r}")
            time.sleep(attempt * 2)
    raise RuntimeError(f"stock Telnet reconnect failed after 3 attempts: {last}")


def _remote_file_sha(telnet, remote: str, timeout: int = 180) -> str:
    rc, text = telnet.command_clean(f"sha256sum {shlex.quote(remote)}", timeout=timeout)
    if rc:
        raise RuntimeError(f"remote payload SHA failed: {remote}")
    hashes = re.findall(r"\b([0-9a-fA-F]{64})\b", text)
    if not hashes:
        raise RuntimeError(f"remote payload SHA missing: {remote}")
    return hashes[-1].lower()


def install(mod) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_run_expert = mod.run_expert
    original_backup_tftp = mod.pb.backup_tftp
    original_verify_backup = mod.pb.verify_stock_restore_backup
    original_backup_partition_bytes = mod._backup_partition_bytes
    original_select_and_preflight_transport = mod._select_and_preflight_transport
    original_write_partition = mod._write_partition
    original_remote_partition_sha = mod._remote_partition_sha
    original_open_root_auto = mod.ubi.open_root_auto

    state: dict[str, object] = {
        "access": None,
        "policy": None,
        "reuse_backup": None,
        "transport": None,
        "payloads": {},
    }

    def open_root_auto_capture(host: str = "192.168.1.1"):
        access, telnet = original_open_root_auto(host)
        state["access"] = access
        return access, telnet

    def backup_tftp_optional(access, host, destination, *args, **kwargs):
        reuse = state.get("reuse_backup")
        if reuse is None:
            return original_backup_tftp(access, host, destination, *args, **kwargs)
        ui.status("EXPERT", pb.tr(
            "Новый полный backup пропущен оператором; использую ранее проверенную копию только как источник flag/nsb_slave.",
            "A new full backup was skipped by the operator; reusing the previously verified copy only as the flag/nsb_slave source.",
        ))
        return None

    def verify_backup_optional(path):
        reuse = state.get("reuse_backup")
        return original_verify_backup(Path(reuse) if reuse is not None else path)

    def backup_partition_optional(backup_dir, number, name, expected_size):
        reuse = state.get("reuse_backup")
        return original_backup_partition_bytes(Path(reuse) if reuse is not None else backup_dir, number, name, expected_size)

    def select_and_preflight_capture(telnet, access, slot_candidate, flag_candidate):
        backend, remote_slot, remote_flag = original_select_and_preflight_transport(
            telnet, access, slot_candidate, flag_candidate
        )
        state["transport"] = backend
        state["payloads"] = {
            remote_slot: Path(slot_candidate),
            remote_flag: Path(flag_candidate),
        }
        return backend, remote_slot, remote_flag

    def ensure_remote_payload(telnet, remote: str, expected_sha: str | None = None) -> str:
        payloads = state.get("payloads") or {}
        local = payloads.get(remote) if isinstance(payloads, dict) else None
        transport = state.get("transport")
        access = state.get("access")
        if local is None or transport is None or access is None:
            got = _remote_file_sha(telnet, remote)
            if expected_sha is not None and got != expected_sha:
                raise RuntimeError(f"remote payload changed: {got} != {expected_sha}")
            return got

        local = Path(local)
        local_sha = mod.sha256_file(local)
        if expected_sha is not None and local_sha != expected_sha:
            raise RuntimeError(f"local frozen payload changed: {local_sha} != {expected_sha}")
        try:
            got = _remote_file_sha(telnet, remote)
            if got == local_sha:
                return got
            pb._write_session_only(
                f"[TRANSITION-REMOTE-PAYLOAD-MISMATCH] remote={remote} got={got} expected={local_sha}"
            )
        except Exception as exc:
            pb._write_session_only(
                f"[TRANSITION-REMOTE-PAYLOAD-MISSING] remote={remote} error={exc!r}"
            )

        ui.status("WAIT", pb.tr(
            f"После перезапуска stock пропал временный payload {remote}; заново передаю его тем же frozen transport={transport}.",
            f"The temporary payload {remote} disappeared after the stock restart; re-uploading it with the same frozen transport={transport}.",
        ))
        uploaded_sha = mod._upload_with_backend(str(transport), telnet, access, local, remote)
        if uploaded_sha != local_sha:
            raise RuntimeError(f"restored remote payload SHA mismatch: {uploaded_sha} != {local_sha}")
        ui.status("READY", pb.tr(
            f"Временный payload восстановлен и SHA-проверен: {remote}.",
            f"Temporary payload restored and SHA-verified: {remote}.",
        ))
        return local_sha

    def resilient_partition_sha(telnet, dev: str, timeout: int = 300) -> str:
        try:
            return original_remote_partition_sha(telnet, dev, timeout=timeout)
        except Exception as exc:
            access = state.get("access")
            policy = state.get("policy")
            if access is None or policy is None:
                raise
            pb._write_session_only(f"[TRANSITION-READBACK-COLLISION] dev={dev} error={exc!r}")
            _reconnect_same_session(access, telnet, policy.family)
            return original_remote_partition_sha(telnet, dev, timeout=timeout)

    def resilient_write_partition(telnet, remote: str, part: str, dev: str, size: int,
                                  method: str, erase_size: int, timeout: int = 600) -> None:
        access = state.get("access")
        policy = state.get("policy")
        if access is None or policy is None:
            return original_write_partition(telnet, remote, part, dev, size, method, erase_size, timeout=timeout)

        remote_sha = ensure_remote_payload(telnet, remote)
        last = None
        for attempt in range(1, 4):
            try:
                original_write_partition(telnet, remote, part, dev, size, method, erase_size, timeout=timeout)
                return
            except Exception as exc:
                last = exc
                pb._write_session_only(
                    f"[TRANSITION-WRITE-COLLISION] part={part} attempt={attempt} writer={method} error={exc!r}"
                )
                ui.status("WARNING", pb.tr(
                    f"Связь оборвалась во время записи {part}. Не запускаю другой writer: переподключаюсь и сначала проверяю NAND ({attempt}/3).",
                    f"Connection dropped while writing {part}. Not switching writers: reconnecting and checking NAND first ({attempt}/3).",
                ))
                _reconnect_same_session(access, telnet, policy.family)
                try:
                    got = original_remote_partition_sha(telnet, dev, timeout=max(timeout, 300))
                except Exception as read_exc:
                    pb._write_session_only(
                        f"[TRANSITION-WRITE-READBACK-RETRY] part={part} attempt={attempt} error={read_exc!r}"
                    )
                    got = ""
                if got == remote_sha:
                    ui.status("READY", pb.tr(
                        f"{part}: запись успела завершиться до обрыва; SHA readback совпал, повторная запись не нужна.",
                        f"{part}: write completed before the disconnect; readback SHA matches, no rewrite needed.",
                    ))
                    return
                if attempt >= 3:
                    break
                # A full stock reset clears /tmp. Restore the same exact payload with
                # the already frozen transport, then retry the same writer only.
                check_remote = ensure_remote_payload(telnet, remote, remote_sha)
                if check_remote != remote_sha:
                    raise RuntimeError(f"remote payload changed after reconnect: {check_remote} != {remote_sha}")
                ui.status("WAIT", pb.tr(
                    f"{part}: readback пока не совпал; повторяю тот же {method} с тем же payload, попытка {attempt + 1}/3.",
                    f"{part}: readback does not match yet; retrying the same {method} with the same payload, attempt {attempt + 1}/3.",
                ))
        raise RuntimeError(f"{method} write failed for {part} after bounded reconnect/retry: {last}")

    def run_expert_fast(*, host: str, profile: str) -> int:
        policy = mod._policy(profile)
        state["policy"] = policy
        state["access"] = None
        state["reuse_backup"] = None
        state["transport"] = None
        state["payloads"] = {}

        do_backup = _yes_default(
            "EXPERT: сделать полную резервную копию перед миграцией? [Д/н]: ",
            "EXPERT: create a complete backup before migration? [Y/n]: ",
        )
        if not do_backup:
            reuse = _choose_existing_backup(mod)
            result = original_verify_backup(reuse)
            family = str(result.get("stock_family") or "").strip().lower()
            if family and family != policy.family:
                raise RuntimeError(f"backup family mismatch: {family} != {policy.family}")
            state["reuse_backup"] = reuse
            ui.status("READY", pb.tr(
                f"Повторный backup не нужен: restore-validator принял {reuse}.",
                f"No repeat backup needed: restore-validator accepted {reuse}.",
            ))

        mod.pb.backup_tftp = backup_tftp_optional
        mod.pb.verify_stock_restore_backup = verify_backup_optional
        mod._backup_partition_bytes = backup_partition_optional
        mod._select_and_preflight_transport = select_and_preflight_capture
        mod._write_partition = resilient_write_partition
        mod._remote_partition_sha = resilient_partition_sha
        mod.ubi.open_root_auto = open_root_auto_capture
        try:
            return original_run_expert(host=host, profile=profile)
        finally:
            mod.pb.backup_tftp = original_backup_tftp
            mod.pb.verify_stock_restore_backup = original_verify_backup
            mod._backup_partition_bytes = original_backup_partition_bytes
            mod._select_and_preflight_transport = original_select_and_preflight_transport
            mod._write_partition = original_write_partition
            mod._remote_partition_sha = original_remote_partition_sha
            mod.ubi.open_root_auto = original_open_root_auto
            state["access"] = None
            state["policy"] = None
            state["reuse_backup"] = None
            state["transport"] = None
            state["payloads"] = {}

    mod.run_expert = run_expert_fast

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
_REPO_ROOT = HERE.parent.parent
REPO_MODE = (_REPO_ROOT / "payloads").is_dir() and (_REPO_ROOT / "config").is_dir()
ROOT = _REPO_ROOT if REPO_MODE else HERE.parent
WORK = ROOT / "work" / "vanilla-pregnant-item4"
sys.path.insert(0, str(HERE))

import console_ui as ui  # noqa: E402
import proven_backend as pb  # noqa: E402
import stock_ab_transition as sat  # noqa: E402
import stock_fit_initramfs as sfi  # noqa: E402
import ursusboot_install as ubi  # noqa: E402
import device_state as ds  # noqa: E402


@dataclass(frozen=True)
class Policy:
    profile: str
    family: str
    model: str
    payload_dir: str
    production_name: str
    slot_size: int = 0x02880000
    flag_size: int = 0x00040000
    erase_size: int = 0x00020000
    bootloader_mtd: int = 0
    flag_mtd: int = 8
    flagback_mtd: int = 9
    bosa_mtd: int = 6
    ri_mtd: int = 7
    master_mtd: int = 14
    slave_mtd: int = 15


POLICIES = {
    "xg040-md": Policy(
        "xg040-md",
        "md",
        "Nokia XG-040G-MD",
        "md",
        "openwrt-airoha-an7581-nokia_xg-040g-md-ubi-squashfs-sysupgrade.itb",
    ),
    "xg040-mf": Policy(
        "xg040-mf",
        "mf",
        "Nokia XG-040G-MF",
        "mf",
        "openwrt-airoha-an7583-nokia_xg-040g-mf-ubi-squashfs-sysupgrade.itb",
    ),
}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _policy(name: str) -> Policy:
    try:
        return POLICIES[name]
    except KeyError as exc:
        raise RuntimeError(f"unsupported pregnant profile: {name}") from exc


def _choose_verified_stock_backup(policy: Policy, supplied: str | Path | None = None) -> tuple[Path | None, dict | None]:
    """Optionally validate an existing restore-grade backup; never capture a new one."""
    if supplied is None:
        raw = input(pb.tr(
            "Путь к ранее сделанному полному stock backup [Enter — продолжить БЕЗ backup]: ",
            "Path to an existing complete stock backup [Enter — continue WITHOUT backup]: ",
        )).strip().strip('"')
        if not raw:
            return None, None
        path = Path(raw).expanduser()
    else:
        text = str(supplied).strip()
        if not text:
            return None, None
        path = Path(text).expanduser()

    try:
        if not path.is_dir():
            raise RuntimeError(f"stock backup directory not found: {path}")
        result = pb.verify_stock_restore_backup(path)
        family = str(result.get("stock_family") or "").strip().lower()
        if family and family != policy.family:
            raise RuntimeError(
                f"stock backup family mismatch: selected {policy.family}, backup reports {family}"
            )
    except Exception as exc:
        ui.status("WARNING", pb.tr(
            f"Указанный backup не принят ({exc}). EXPERT продолжит БЕЗ restore-grade backup.",
            f"The selected backup was not accepted ({exc}). EXPERT will continue WITHOUT a restore-grade backup.",
        ))
        return None, None

    ui.status("READY", f"Existing restore-grade stock backup verified: {path}")
    return path, result


def _capture_live_partition(
    telnet: pb.Telnet,
    access: pb.StockAccess,
    *,
    number: int,
    expected_size: int,
    out: Path,
) -> tuple[bytes, str, Path]:
    """Capture only a partition needed to construct the current transaction."""
    remote = f"/tmp/ursus-item4-mtd{number}.bin"
    blocks = (expected_size + 131071) // 131072
    rc, text = telnet.command_clean(
        f"rm -f {shlex.quote(remote)}; "
        f"dd if=/dev/mtd{number} of={shlex.quote(remote)} bs=131072 count={blocks} 2>/dev/null && "
        f"wc -c < {shlex.quote(remote)} && sha256sum {shlex.quote(remote)}",
        timeout=max(90, expected_size // (512 * 1024)),
    )
    if rc:
        raise RuntimeError(f"failed to capture live mtd{number}")
    sizes = [int(x) for x in __import__("re").findall(r"(?:^|\n)\s*(\d+)\s*(?:\n|$)", text)]
    hashes = __import__("re").findall(r"\b([0-9a-fA-F]{64})\b", text)
    if not sizes or sizes[-1] != expected_size or not hashes:
        raise RuntimeError(f"live mtd{number} capture metadata mismatch")
    remote_sha = hashes[-1].lower()
    ubi.receive_remote_file(telnet, access.host, remote, out)
    data = out.read_bytes()
    if len(data) != expected_size or sha_bytes(data) != remote_sha:
        raise RuntimeError(f"live mtd{number} PC copy mismatch")
    return data, remote_sha, out


def _remote_mtd_sha(telnet: pb.Telnet, number: int) -> str:
    rc, text = telnet.command_clean(
        f"sha256sum /dev/mtd{number}",
        timeout=180,
    )
    if rc:
        raise RuntimeError(f"cannot hash live mtd{number}")
    hashes = __import__("re").findall(r"\b([0-9a-fA-F]{64})\b", text)
    if not hashes:
        raise RuntimeError(f"live mtd{number} SHA256 missing")
    return hashes[-1].lower()



def _payload_root(policy: Policy) -> Path:
    base = ROOT / "payloads" / "vanilla-pregnant" / policy.payload_dir
    if not REPO_MODE:
        base = ROOT / "data" / "payloads" / "vanilla-pregnant" / policy.payload_dir
    return base


def _load_payload(policy: Policy) -> tuple[dict[str, Path], dict]:
    root = _payload_root(policy)
    meta_path = root / "PAYLOAD.json"
    if not meta_path.is_file():
        raise RuntimeError(f"pregnant payload metadata missing: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if (
        meta.get("mode") != "VANILLA_PREGNANT_MIGRATION"
        or meta.get("profile") != policy.profile
        or meta.get("family") != policy.family
    ):
        raise RuntimeError("pregnant payload metadata mismatch")
    files = {
        "runtime": root / "runtime.itb",
        "pregnant_itb": root / "pregnant-autonomous.itb",
        "production": root / policy.production_name,
        "fip": root / "vanilla-bl31-uboot.fip",
        "preloader": root / "vanilla-preloader.bin",
    }
    for role, path in files.items():
        spec = meta.get("files", {}).get(role, {})
        if not path.is_file():
            raise RuntimeError(f"pregnant component missing: {path}")
        digest = sha_file(path)
        if digest != str(spec.get("sha256", "")).lower() or path.stat().st_size != int(spec.get("size", -1)):
            raise RuntimeError(f"pregnant {role} integrity mismatch: {path.name}")
    if sha_file(files["production"]) != str(meta.get("unameone_sha256", "")).lower():
        raise RuntimeError("pinned UnameOne production SHA mismatch")
    sfi.source_fit_contract(files["runtime"].read_bytes())
    pregnant_contract = sfi.source_fit_contract(files["pregnant_itb"].read_bytes())
    autonomous = meta.get("autonomous") or {}
    if autonomous.get("mode") != "EMBEDDED_RAMDISK":
        raise RuntimeError("pregnant payload is not autonomous embedded-ramdisk mode")
    if int(autonomous.get("fit_size", -1)) != files["pregnant_itb"].stat().st_size:
        raise RuntimeError("autonomous pregnant FIT size metadata mismatch")
    if str(autonomous.get("fit_sha256", "")).lower() != sha_file(files["pregnant_itb"]):
        raise RuntimeError("autonomous pregnant FIT SHA metadata mismatch")
    if pregnant_contract["kernel_data_size"] != sfi.source_fit_contract(files["runtime"].read_bytes())["kernel_data_size"]:
        raise RuntimeError("autonomous payload unexpectedly changed transient kernel size")
    return files, meta


def _require_stock_geometry(telnet: pb.Telnet, policy: Policy) -> None:
    import re

    rc, text = telnet.command_clean("cat /proc/mtd", timeout=20)
    if rc:
        raise RuntimeError("cannot read /proc/mtd")
    rows = {
        name: (int(size, 16), int(erase, 16), int(index))
        for index, size, erase, name in re.findall(
            r'mtd(\d+):\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+"([^"]+)"', text
        )
    }
    expected = {
        "bootloader": (0x00080000, policy.erase_size, policy.bootloader_mtd),
        "flag": (policy.flag_size, policy.erase_size, policy.flag_mtd),
        "flagback": (policy.flag_size, policy.erase_size, policy.flagback_mtd),
        "bosa": (0x00040000, policy.erase_size, policy.bosa_mtd),
        "ri": (0x00040000, policy.erase_size, policy.ri_mtd),
        "nsb_master": (policy.slot_size, policy.erase_size, policy.master_mtd),
        "nsb_slave": (policy.slot_size, policy.erase_size, policy.slave_mtd),
    }
    for name, want in expected.items():
        if rows.get(name) != want:
            raise RuntimeError(f"stock MTD geometry mismatch for {name}: {rows.get(name)} != {want}")


def _production_confirm_command(policy: Policy, payload_meta: dict) -> tuple[str, str]:
    production = payload_meta["files"]["production"]
    expected_sha = str(production["sha256"]).lower()
    expected_size = int(production["size"])
    expected_board = f"nokia,xg-040g-{policy.family}-ubi"
    record = f"URSUS_STATE_V1\nSTATE=BOOT_CONFIRMED\nFAMILY={policy.family}\n"
    record_sha = hashlib.sha256(record.encode()).hexdigest()
    record_len = len(record.encode())
    # Positive production proof only: expected board, durable PROD_VERIFIED, and
    # exact pinned production FIT readback. This command never retries a writer.
    script = f"""
set -eu
[ \"$(cat /tmp/sysinfo/board_name)\" = {shlex.quote(expected_board)} ]
state_dev=; fit_dev=
for p in /sys/class/ubi/ubi[0-9]*_[0-9]*/name; do
  [ -r \"$p\" ] || continue
  n=$(cat \"$p\")
  d=/dev/$(basename \"${{p%/name}}\")
  [ -e \"$d\" ] || continue
  [ \"$n\" = ursusstate ] && state_dev=$d
  [ \"$n\" = fit ] && fit_dev=$d
done
[ -n \"$state_dev\" ] && [ -n \"$fit_dev\" ]
[ \"$(dd if=\"$state_dev\" bs=4096 count=1 2>/dev/null | tr '\\000' '\\n' | sed -n 's/^STATE=//p' | head -n1)\" = PROD_VERIFIED ]
[ \"$(dd if=\"$fit_dev\" bs=4096 count=$((({expected_size}+4095)/4096)) 2>/dev/null | head -c {expected_size} | sha256sum | awk '{{print $1}}')\" = {expected_sha} ]
printf {shlex.quote(record)} > /tmp/ursus-boot-confirmed.state
ubiupdatevol \"$state_dev\" /tmp/ursus-boot-confirmed.state >/dev/null
[ \"$(dd if=\"$state_dev\" bs=4096 count=1 2>/dev/null | head -c {record_len} | sha256sum | awk '{{print $1}}')\" = {record_sha} ]
echo URSUS_BOOT_CONFIRMED
""".strip()
    return script, record_sha


def _monitor(host: str, policy: Policy, payload_meta: dict, seconds: int = 600) -> None:
    deadline = time.time() + seconds
    transient_seen = False
    prod_verified = False
    last_status = ""
    started = time.time()
    next_stock_probe = started + 25
    ui.status(
        "WAIT",
        pb.tr(
            "Stage2 работает автономно; SSH используется только для чтения telemetry и подтверждения уже загруженной production-системы.",
            "Stage2 is autonomous; SSH is used only for telemetry and confirmation of an already booted production system.",
        ),
    )
    confirm_cmd, _record_sha = _production_confirm_command(policy, payload_meta)
    next_confirm_attempt = 0.0
    while time.time() < deadline:
        rc, output = pb.ssh_run(
            host,
            "cat /tmp/ursus-install/status.json 2>/dev/null; echo __URSUS_LOG__; tail -n 8 /tmp/ursus-install/install.log 2>/dev/null",
            timeout=15,
            allow_disconnect=True,
            quiet=True,
            batch_mode=True,
            minimal_auth=True,
            password_prompts=0,
        )
        if rc == 0 and "__URSUS_LOG__" in output:
            transient_seen = True
            status = output.split("__URSUS_LOG__", 1)[0].strip()
            if status and status != last_status:
                ui.status("INFO", f"stage2 {status}")
                last_status = status
            if '"state":"FAILED"' in status:
                raise RuntimeError("autonomous stage2 reported FAILED; no retry or alternate writer was attempted")
            if '"state":"PROD_VERIFIED"' in status:
                prod_verified = True
                ui.status("PASS", "Stage2 reported PROD_VERIFIED; waiting for production reboot.")
        elif not transient_seen and time.time() >= next_stock_probe:
            # Distinguish a return to the untouched stock OS from a generic
            # "pregnant never appeared" timeout. In the Recovery-loader route
            # this means boot-once never reached the transient Linux; stage2
            # therefore did not cross its destructive boundary.
            next_stock_probe = time.time() + 10
            try:
                state = ds.probe_device_state(host, interactive_ssh=False)
            except Exception as exc:
                pb._write_session_only(f"[PREGNANT-FALLBACK-PROBE] {exc!r}")
            else:
                if state.probe_status == ds.PROBE_COMPLETE and state.current_system == "NOKIA_STOCK":
                    model_ok = state.model in ("UNKNOWN", policy.model)
                    if model_ok:
                        ui.status(
                            "STOCK_MASTER_FALLBACK",
                            pb.tr(
                                "После boot-once снова загрузилась штатная Nokia stock. Pregnant initramfs не стартовал; stage2 и UBI migration не выполнялись.",
                                "Nokia stock booted again after boot-once. Pregnant initramfs did not start; stage2 and UBI migration were not executed.",
                            ),
                        )
                        raise RuntimeError(
                            "STOCK_FALLBACK: Nokia stock booted again after Recovery boot-once; "
                            "pregnant runtime did not start and no stage2 migration writes were attempted"
                        )
        elif transient_seen and prod_verified and time.time() >= next_confirm_attempt:
            # The transient SSH plane disappeared after verified writes. A later
            # successful command can only run in the production child.
            rc2, out2 = pb.ssh_run(
                host,
                confirm_cmd,
                timeout=30,
                allow_disconnect=True,
                quiet=True,
                batch_mode=True,
                minimal_auth=True,
                password_prompts=0,
            )
            next_confirm_attempt = time.time() + 10
            if rc2 == 0 and "URSUS_BOOT_CONFIRMED" in out2:
                ui.status("PASS", "Production OpenWrt boot confirmed; persistent state=BOOT_CONFIRMED readback verified.")
                ui.note("This confirms the software transaction, not a hardware acceptance PASS; keep the UART log for HW evidence.")
                return
        time.sleep(5)
    if prod_verified:
        ui.status(
            "WARNING",
            "Stage2 reached PROD_VERIFIED, but automatic production SSH confirmation was unavailable. No write was retried; verify the boot over UART/SSH.",
        )
    else:
        ui.status("WARNING", "Telemetry window ended. No write was retried; inspect UART or reconnect and read state/log.")


def _reopen_verified_stock_root(host: str, policy: Policy, access):
    """Reopen the already-proven stock root shell without re-entering Web UI.

    After NAND write starts, readback recovery must not depend on HTTP/Web state.
    The access object already contains Telnet/SU credentials obtained and verified
    before the destructive boundary; reuse only those credentials here.
    """
    if access is None:
        raise RuntimeError("post-write stock reconnect has no preserved Telnet credentials")
    if str(getattr(access, "host", "") or "") != host:
        raise RuntimeError(
            f"post-write reconnect host mismatch: credentials={getattr(access, 'host', None)!r} requested={host!r}"
        )
    reported = str(getattr(access, "family", "") or "").strip().lower()
    if reported not in ("", "unknown", policy.family):
        raise RuntimeError(f"board profile mismatch after reconnect: selected {policy.profile}, stock reports {reported}")
    telnet = pb.login_root_family(access, policy.family, allow_service_provisioning=False)
    _require_stock_geometry(telnet, policy)
    rc_uid, uid_text = telnet.command_clean("id -u", timeout=15)
    uid_lines = [line.strip() for line in uid_text.replace("\r", "\n").split("\n") if line.strip().isdigit()]
    if rc_uid or not uid_lines or uid_lines[-1] != "0":
        telnet.close()
        raise RuntimeError(f"reconnected stock Telnet is not UID 0: rc={rc_uid} output={uid_text!r}")
    access.family = policy.family
    return access, telnet


def _readback_sha_with_reconnect(
    host: str,
    policy: Policy,
    access,
    telnet,
    dev: str,
    *,
    timeout: int,
    attempts: int = 3,
):
    """Retry only readback across stock transport disconnects.

    NAND write is never retried here. Each retry re-establishes the same verified
    stock root transport and re-runs full-partition SHA256.
    """
    current_access, current_telnet = access, telnet
    for attempt in range(1, attempts + 1):
        try:
            digest = sat._remote_partition_sha(current_telnet, dev, timeout=timeout)
            return current_access, current_telnet, digest
        except (OSError, ConnectionError, TimeoutError, EOFError) as exc:
            pb._write_session_only(
                f"[PREGNANT-READBACK-DISCONNECT] dev={dev} attempt={attempt}/{attempts} error={exc!r}"
            )
            if attempt >= attempts:
                raise
            ui.status(
                "WARNING",
                pb.tr(
                    f"Соединение оборвалось во время readback {dev}; переподключаюсь и повторяю только SHA-чтение ({attempt + 1}/{attempts}). NAND повторно НЕ записывается.",
                    f"Connection dropped during {dev} readback; reconnecting and retrying SHA read only ({attempt + 1}/{attempts}). NAND is NOT rewritten.",
                ),
            )
            try:
                if current_telnet:
                    current_telnet.close()
            except Exception:
                pass
            try:
                if current_access:
                    current_access.close_web(announce=False)
            except Exception:
                pass
            # Preserve the already-verified Telnet/SU credentials in StockAccess.
            # Only the dead Telnet socket is discarded; post-write recovery must
            # never require the stock Web UI to become available again.
            current_telnet = None
            time.sleep(3)
            current_access, current_telnet = _reopen_verified_stock_root(host, policy, current_access)
    raise RuntimeError("unreachable readback retry state")


def run(*, host: str = "192.168.1.1", profile: str, monitor: bool = True, backup_path: str | Path | None = None) -> int:
    policy = _policy(profile)
    ui.enable()
    files, payload_meta = _load_payload(policy)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = WORK / f"{policy.family}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    access = telnet = None
    try:
        access, telnet = ubi.open_root_auto(host)
        reported = str(getattr(access, "family", "") or "").strip().lower()
        if reported not in ("", "unknown", policy.family):
            raise RuntimeError(f"board profile mismatch: selected {policy.profile}, stock reports {reported}")
        _require_stock_geometry(telnet, policy)
        access.family = policy.family
        writer = sat._mtd_writer_preflight(telnet)

        # Backup is optional insurance only. Candidate/selector always derive
        # from the current router, so an older valid backup can never dictate
        # the live FIT wrapper or selector bytes.
        full_backup, backup_result = _choose_verified_stock_backup(policy, backup_path)

        live_slave_path = run_dir / f"live-mtd{policy.slave_mtd}-nsb_slave.bin"
        slave, slave_sha, slave_path = _capture_live_partition(
            telnet, access, number=policy.slave_mtd,
            expected_size=policy.slot_size, out=live_slave_path,
        )
        live_flag_path = run_dir / f"live-mtd{policy.flag_mtd}-flag.bin"
        flag, flag_sha, flag_path = _capture_live_partition(
            telnet, access, number=policy.flag_mtd,
            expected_size=policy.flag_size, out=live_flag_path,
        )
        flag_state = sat.parse_flag(flag, policy)
        if flag_state["active"] != 0 or flag_state["curimg"] != 0:
            raise RuntimeError(
                f"SLOT1 fallback invariant requires live stock active=0 curimg=0, got {flag_state}"
            )

        # Stage2 will re-read bosa/ri from the live stock partitions immediately
        # before the destructive UBI boundary. Do not gate migration on snapshots
        # of unrelated stock partition hashes taken before reboot.
        flagback_state = {"source": "not-gated"}
        evidence = {
            "family": policy.family,
            "profile": policy.profile,
        }
        slot, slot_meta = sfi.build_pregnant_slot(
            slave,
            files["runtime"].read_bytes(),
            files["production"].read_bytes(),
            files["fip"].read_bytes(),
            files["preloader"].read_bytes(),
            slot_size=policy.slot_size,
            evidence=evidence,
            handoff_linux=files["handoff"].read_bytes() if policy.family == "md" else None,
        )
        slot_path = run_dir / f"mtd{policy.slave_mtd}_nsb_slave_pregnant.bin"
        slot_path.write_bytes(slot)
        flag_candidate, flag_meta = sat.build_activation_flag(flag, 1, policy)
        flag_out = run_dir / f"mtd{policy.flag_mtd}_flag_activate_slave.bin"
        flag_out.write_bytes(flag_candidate)

        # Transfer backend may change only while NAND is still pristine. The
        # selected writer and transfer are frozen before the single y/N.
        transport, remote_slot, remote_flag = sat._select_and_preflight_transport(
            telnet, access, slot_path, flag_out
        )

        # Reboot is part of the same destructive transaction. Freeze its stock
        # root transport before asking the sole y/N so we never discover after
        # selector write that the session was unprivileged or reboot unavailable.
        rc_uid, uid_text = telnet.command_clean("id -u", timeout=15)
        uid_lines = [line.strip() for line in uid_text.replace("\r", "\n").split("\n") if line.strip().isdigit()]
        if rc_uid or not uid_lines or uid_lines[-1] != "0":
            raise RuntimeError(f"stock reboot preflight requires UID 0 Telnet, got rc={rc_uid} output={uid_text!r}")
        rc_reboot, reboot_text = telnet.command_clean("command -v reboot", timeout=15)
        reboot_lines = [line.strip() for line in reboot_text.replace("\r", "\n").split("\n") if line.strip() and not line.startswith("__")]
        if rc_reboot or not reboot_lines:
            raise RuntimeError("stock root Telnet has no reboot command")
        reboot_command = reboot_lines[-1]
        report = {
            "operation": f"{policy.profile}_vanilla_pregnant_migration",
            "profile": policy.profile,
            "payload": payload_meta,
            "slot": slot_meta,
            "selector": flag_meta,
            "flagback_observed": flagback_state,
            "writer": writer,
            "transport": transport,
            "reboot": {"transport": "stock-root-telnet", "command": reboot_command, "uid": 0},
            "backup": {
                "present": full_backup is not None,
                "full_directory": str(full_backup) if full_backup else None,
                "stock_family": backup_result.get("stock_family") if backup_result else None,
                "stock_variant": backup_result.get("stock_variant") if backup_result else None,
            },
            "live_sources": {
                "slave_source": str(slave_path),
                "slave_sha256": slave_sha,
                "flag_source": str(flag_path),
                "flag_sha256": flag_sha,
            },
        }
        (run_dir / "VANILLA_PREGNANT_PLAN.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        ui.section("VANILLA PREGNANT MIGRATION", style="amber2")
        if full_backup:
            ui.status("READY", f"{policy.model}: existing restore-grade backup verified; SLOT1 remains untouched")
        else:
            ui.section(pb.tr("ВНИМАНИЕ: BACKUP НЕТ", "WARNING: NO BACKUP"), style="bad")
            ui.status("WARNING", pb.tr(
                "ПОЛНЫЙ RESTORE-GRADE BACKUP НЕ ВЫБРАН. ВОССТАНОВЛЕНИЕ ПРИ НЕШТАТНОМ СБОЕ МОЖЕТ ПОТРЕБОВАТЬ UART/BOOTROM И ДРУГОЙ ИСТОЧНИК ЗАВОДСКИХ ДАННЫХ.",
                "NO COMPLETE RESTORE-GRADE BACKUP IS SELECTED. RECOVERY FROM AN UNEXPECTED FAILURE MAY REQUIRE UART/BOOTROM AND ANOTHER SOURCE OF FACTORY DATA.",
            ))

        ui.status("READY", f"SLOT2 candidate SHA256 {slot_meta['candidate_sha256']}")
        ui.status("READY", f"Pinned UnameOne production SHA256 {payload_meta['unameone_sha256']}")
        ui.status("READY", f"writer={writer}; transport={transport}; both frozen before destructive boundary")
        ui.status("READY", f"reboot=stock root Telnet uid=0; command={reboot_command}")
        ui.note(
            "One normal y/N covers SLOT2 write/readback -> selector -> reboot -> autonomous UBI -> pinned UnameOne -> identity -> Vanilla FIP -> BL2-last -> final readback. Without a restore-grade backup, one explicit YES risk acknowledgement is required before that y/N. No confirmation exists after reboot."
        )
        if full_backup is None:
            emergency = ui.prompt(pb.tr(
                "BACKUP ОТСУТСТВУЕТ. ПРОДОЛЖЕНИЕ — НА РИСК ОПЕРАТОРА. Для продолжения введите YES: ",
                "NO BACKUP IS AVAILABLE. CONTINUING IS AT THE OPERATOR'S RISK. Type YES to continue: ",
            )).strip()
            if emergency != "YES":
                ui.status("STOP", pb.tr(
                    "Операция отменена до записи; NAND не изменялась.",
                    "Operation cancelled before write; NAND was not modified.",
                ))
                return 0

        answer = ui.prompt(
            pb.tr(
                "Preflight пройден. Запустить всю показанную migration transaction? [д/Н]: ",
                "Preflight passed. Start the complete migration transaction shown above? [y/N]: ",
            )
        ).strip().lower()
        if answer not in ("д", "да", "y", "yes"):
            ui.status("STOP", pb.tr("Операция отменена; NAND не изменялась.", "Operation cancelled; NAND was not modified."))
            return 0

        slot_dev = f"/dev/mtd{policy.slave_mtd}"
        try:
            sat._write_partition(
                telnet,
                remote_slot,
                "nsb_slave",
                slot_dev,
                policy.slot_size,
                writer,
                policy.erase_size,
                timeout=900,
            )
        except OSError as exc:
            # A stock Telnet session may be reset while mtd_debug is still
            # completing a long SLOT2 write. Never retry the writer blindly:
            # reconnect and let full-partition SHA decide whether the original
            # write completed. SLOT1 is still active at this point.
            pb._write_session_only(f"[PREGNANT-SLOT2-DISCONNECT] {exc!r}")
            ui.status(
                "WARNING",
                "Stock Telnet disconnected during SLOT2 write; reconnecting for readback only. NAND write will NOT be retried automatically.",
            )
            try:
                if telnet:
                    telnet.close()
            except Exception:
                pass
            try:
                if access:
                    access.close_web(announce=False)
            except Exception:
                pass
            access = telnet = None
            time.sleep(5)
            access, telnet = _reopen_verified_stock_root(host, policy)

        access, telnet, got = _readback_sha_with_reconnect(
            host, policy, access, telnet, slot_dev, timeout=600
        )
        if got != slot_meta["candidate_sha256"]:
            raise RuntimeError(
                f"nsb_slave readback mismatch after write/disconnect handling: {got} != {slot_meta['candidate_sha256']}; "
                "selector was NOT written and SLOT1 remains active"
            )
        ui.status("PASS", "SLOT2 pregnant installer write/readback verified; SLOT1 untouched")

        expected_flag_sha = sha_bytes(flag_candidate)
        sat._write_partition(
            telnet,
            remote_flag,
            "flag",
            f"/dev/mtd{policy.flag_mtd}",
            policy.flag_size,
            writer,
            policy.erase_size,
            timeout=120,
        )
        access, telnet, got_flag = _readback_sha_with_reconnect(
            host, policy, access, telnet, f"/dev/mtd{policy.flag_mtd}", timeout=120
        )
        if got_flag != expected_flag_sha:
            raise RuntimeError(f"flag readback mismatch: {got_flag} != {expected_flag_sha}")
        ui.status("PASS", "Selector active=1 readback verified; flagback untouched")
        ui.status(
            "ACTION",
            "Rebooting immediately into SLOT2. Autonomous stage2 owns all remaining writes; no second confirmation exists.",
        )
        try:
            telnet.send_line(f"sync; sleep 1; {shlex.quote(reboot_command)} -f")
            # A clean disconnect here is success: the stock userspace is dying.
            try:
                telnet.read(4.0, echo=False)
            except Exception:
                pass
        except Exception as exc:
            raise RuntimeError(f"failed to send reboot through verified stock root Telnet: {exc}") from exc
        time.sleep(2)
    finally:
        if telnet:
            try:
                telnet.close()
            except Exception:
                pass
        if access:
            try:
                access.close_web(announce=False)
            except Exception:
                pass

    if monitor:
        _monitor(host, policy, payload_meta)
    return 0


def run_expert(*, host: str, profile: str) -> int:
    return run(host=host, profile=profile, monitor=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UrsusFlasher full pregnant Vanilla migration")
    parser.add_argument("--host", default=os.environ.get("NOKIA_HOST", "192.168.1.1"))
    parser.add_argument("--profile", choices=tuple(POLICIES), required=True)
    parser.add_argument("--backup", help="existing restore-grade stock backup directory")
    parser.add_argument("--no-monitor", action="store_true")
    args = parser.parse_args(argv)
    return run(host=args.host, profile=args.profile, monitor=not args.no_monitor, backup_path=args.backup)


if __name__ == "__main__":
    raise SystemExit(main())
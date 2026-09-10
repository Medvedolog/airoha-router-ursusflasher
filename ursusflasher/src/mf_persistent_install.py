#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import console_ui as ui
import mf_persistent
import proven_backend as proven
import ursusboot_install as md_transport


def tr(ru: str, en: str) -> str:
    return en if os.environ.get("NOKIA_LANG") == "en" else ru


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _choose_bl33_lzma() -> Path:
    root = HERE.parent.parent
    candidates = [
        root / "work" / "mf2-ramboot" / "out" / "u-boot.lzma",
        root / "work" / "mf-ramboot" / "out" / "u-boot.lzma",
    ]
    env_path = os.environ.get("URSUS_MF_BL33_LZMA", "").strip()
    if env_path:
        candidates.insert(0, Path(env_path).expanduser())

    existing = [p.resolve() for p in candidates if p.is_file()]
    if existing:
        selected = existing[0]
        print(tr(
            f"[MF] Использую собранный BL33: {selected}",
            f"[MF] Using built BL33: {selected}",
        ))
        return selected

    raw = ui.prompt(tr(
        "Путь к MF UrsusBoot u-boot.lzma: ",
        "Path to MF UrsusBoot u-boot.lzma: ",
    )).strip().strip('"')
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError(tr(f"BL33 не найден: {path}", f"BL33 was not found: {path}"))
    return path


def run_stock_acceptance(access: proven.StockAccess) -> int:
    """Install the first stock-derived persistent UrsusBoot candidate on MF.

    This is deliberately a feature-branch hardware-acceptance path. It reuses
    the proven host-side stock TFTP/MTD/readback primitives but never calls the
    MD FIP candidate builder. The candidate comes from the live MF boot-area and
    changes only the NT_FW/BL33 payload plus its unavoidable FIP size/end fields.
    """
    if getattr(access, "family", "") != "mf":
        raise RuntimeError("MF persistent acceptance requires a positively identified MF stock device")

    bl33_path = _choose_bl33_lzma()
    bl33 = bl33_path.read_bytes()
    # Candidate identity/LZMA validity is checked again by the builder after the
    # actual device boot-area has been captured.
    bl33_sha = proven.sha_file(bl33_path)

    stamp = _stamp()
    work = Path(proven.WORK)
    private = work / "private" / "mf-persistent-acceptance"
    results = work / "results"
    backups = work / "backups"
    private.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    backups.mkdir(parents=True, exist_ok=True)

    full_backup = backups / f"stock-mf-before-ursusboot-{stamp}"
    before_path = private / f"mf-mtd0-before-{stamp}.bin"
    candidate_path = private / f"mf-mtd0-ursusboot-{stamp}.bin"
    report_path = results / f"mf-persistent-candidate-{stamp}.json"
    result_path = results / f"mf-persistent-install-{stamp}.json"

    result: dict = {
        "operation": "MF_STOCK_DERIVED_PERSISTENT_HW_ACCEPTANCE",
        "board": "Nokia XG-040G-MF",
        "soc": "Airoha AN7583",
        "status": "RUNNING",
        "started_at": stamp,
        "bl33": {
            "path": str(bl33_path),
            "size": len(bl33),
            "sha256": bl33_sha,
        },
    }

    telnet = None
    try:
        ui.rule(tr("MF PERSISTENT — HW ACCEPTANCE", "MF PERSISTENT — HW ACCEPTANCE"), style="amber2")
        ui.note(tr(
            "Используется фактический mtd0 этого MF. Ранние stock FIP-компоненты, native BL31, prefix и ENV сохраняются; заменяется только NT_FW/BL33.",
            "The candidate is derived from this MF device's actual mtd0. Native early FIP components, BL31, prefix and ENV are preserved; only NT_FW/BL33 is replaced.",
        ))

        # Automatic restore-grade backup is not an operator confirmation gate.
        print(tr(
            f"[BACKUP] До записи сохраняю полный stock backup MF: {full_backup}",
            f"[BACKUP] Capturing a complete MF stock backup before writing: {full_backup}",
        ))
        proven.backup_tftp(
            access,
            access.host,
            full_backup,
            expected_family="mf",
            allow_service_provisioning=False,
        )
        result["full_stock_backup"] = str(full_backup)

        telnet = proven.login_root_family(access, "mf", allow_service_provisioning=False)
        proven.require_supported_model_over_telnet(access, telnet)

        preflight = md_transport.mtd0_write_preflight(telnet)
        result["preflight"] = preflight

        _remote_before, live_sha = md_transport.capture_live_mtd0(telnet, access, before_path)
        live = before_path.read_bytes()
        if len(live) != mf_persistent.BOOT_AREA_SIZE:
            raise RuntimeError(f"live MF mtd0 size mismatch: {len(live)}")
        if proven.sha_file(before_path) != live_sha:
            raise RuntimeError("live MF mtd0 local/remote SHA256 mismatch")

        candidate, report = mf_persistent.build_stock_derived_candidate(live, bl33)
        candidate_path.write_bytes(candidate)
        report_path.write_text(json.dumps(asdict(report), indent=2, sort_keys=True) + "\n", encoding="ascii")
        result["source_mtd0"] = {"path": str(before_path), "sha256": live_sha, "size": len(live)}
        result["candidate"] = asdict(report)
        result["candidate_path"] = str(candidate_path)
        result["candidate_report"] = str(report_path)

        ui.status(tr("ГОТОВО", "READY"), tr(
            "MF candidate построен из фактического boot-area и прошёл structural preservation checks.",
            "The MF candidate was derived from the actual boot area and passed structural preservation checks.",
        ))
        print(f"  source mtd0 SHA256: {live_sha}")
        print(f"  candidate SHA256:   {report.candidate_sha256}")
        print(f"  stock FIP entries:  {report.fip_entries}")
        print(f"  NT_FW offset:        0x{report.nt_fw_offset:x}")
        print(f"  NT_FW size:          0x{report.source_nt_fw_size:x} -> 0x{report.candidate_nt_fw_size:x}")
        print(f"  FIP end:             0x{report.source_fip_end:x} -> 0x{report.candidate_fip_end:x}")
        print(f"  native BL31 exact:   {report.native_bl31_preserved}")
        print(f"  prefix exact:        {report.prefix_byte_exact}")
        print(f"  stock ENV exact:     {report.environment_byte_exact}")
        print(f"  non-BL33 exact:      {report.non_bl33_entries_byte_exact}")

        if live_sha == report.candidate_sha256:
            result["status"] = "ALREADY_EXACT"
            result["completed_at"] = _stamp()
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            ui.status(tr("ГОТОВО", "READY"), tr(
                "Точный candidate уже находится в mtd0; повторная запись пропущена.",
                "The exact candidate is already present in mtd0; rewrite skipped.",
            ))
            return 0

        remote = md_transport.upload_candidate(telnet, access, candidate_path)
        rc, check = telnet.command_clean(f"wc -c < {remote}; sha256sum {remote}", timeout=60)
        if rc or str(mf_persistent.BOOT_AREA_SIZE) not in check or report.candidate_sha256 not in check.lower():
            raise RuntimeError("MF candidate transfer verification failed")

        print()
        ui.rule(tr("РАЗРЕШЁННОЕ ДЕЙСТВИЕ", "RESOLVED ACTION"), style="amber2")
        print("  " + tr("Устройство: Nokia XG-040G-MF / Airoha AN7583", "Device: Nokia XG-040G-MF / Airoha AN7583"))
        print("  " + tr("Цель: mtd0 / bootloader, 0x00000000..0x0007ffff", "Target: mtd0 / bootloader, 0x00000000..0x0007ffff"))
        print("  " + tr("Изменение: только stock-derived NT_FW/BL33 внутри исходного 9-entry FIP", "Change: stock-derived NT_FW/BL33 only inside the original 9-entry FIP"))
        print("  " + tr(f"Writer: {preflight['writer']}; после записи — полный SHA256 readback", f"Writer: {preflight['writer']}; full SHA256 readback follows the write"))
        print("  " + tr(f"Резервная копия: {full_backup}", f"Backup: {full_backup}"))
        answer = ui.prompt(tr("Начать запись? [д/Н]: ", "Start writing? [y/N]: ")).strip().lower()
        if answer not in ("д", "да", "y", "yes"):
            result["status"] = "CANCELLED_BEFORE_WRITE"
            result["completed_at"] = _stamp()
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return 2

        result["write_started_at"] = _stamp()
        rc, write_out = md_transport.write_image(telnet, remote, preflight["writer"])
        result["write_rc"] = rc
        result["write_output_tail"] = write_out[-4000:]
        if rc:
            result["status"] = "WRITE_STATE_UNKNOWN"
            raise RuntimeError(f"MF mtd0 writer returned rc={rc}; no alternate writer will be attempted")

        readback_sha = md_transport.remote_mtd0_sha(telnet)
        result["readback_sha256"] = readback_sha
        if readback_sha != report.candidate_sha256:
            result["status"] = "READBACK_MISMATCH"
            raise RuntimeError(
                f"MF mtd0 readback mismatch: expected {report.candidate_sha256}, got {readback_sha}; do not reboot"
            )

        result["status"] = "WRITE_AND_READBACK_PASS_COLD_BOOT_REQUIRED"
        result["completed_at"] = _stamp()
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ui.status(tr("ГОТОВО", "READY"), tr(
            "MF mtd0 записан и полностью сверен. Автоматическая перезагрузка намеренно не выполняется.",
            "MF mtd0 was written and fully verified. Automatic reboot is intentionally disabled.",
        ))
        ui.note(tr(
            "Для hardware acceptance полностью выключите питание, отпустите Reset и включите роутер обычным способом. Сохраните UART с самого начала.",
            "For hardware acceptance, power the router fully off, release Reset and power it on normally. Capture UART from the beginning.",
        ))
        return 0
    except Exception as exc:
        if result.get("status") == "RUNNING":
            result["status"] = "FAILED_BEFORE_COMPLETION"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["completed_at"] = _stamp()
        try:
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
        raise
    finally:
        if telnet is not None:
            try:
                telnet.close()
            except Exception:
                pass

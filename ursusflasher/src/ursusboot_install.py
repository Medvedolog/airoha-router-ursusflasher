#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import socket
import struct
import sys
import threading
import time
import zipfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
_REPO_ROOT = HERE.parent.parent
REPO_MODE = (_REPO_ROOT / "fw").is_dir() and (_REPO_ROOT / "payloads").is_dir() and (_REPO_ROOT / "config").is_dir()
ROOT = _REPO_ROOT if REPO_MODE else HERE.parent
DATA = HERE if REPO_MODE else (ROOT / "data")
PAYLOAD_DIR = (ROOT / "payloads" / "md" / "ursusboot") if REPO_MODE else (ROOT / "data" / "payloads" / "md" / "ursusboot")
PAYLOAD = PAYLOAD_DIR / "ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip"
ALPHA3_REFERENCE_PAYLOAD = PAYLOAD_DIR / "ursusboot-md-0.1.0-alpha3-update.fip"
WORK = ROOT / "work"
PRIVATE = WORK / "private"
FULL_BACKUPS = WORK / "backups"
RESULTS = ROOT / "results"

sys.path.insert(0, str(DATA))
import proven_backend as pb  # noqa: E402
import ui_terms as terms  # noqa: E402
import console_ui as ui  # noqa: E402

MTD0_SIZE = 0x80000
ERASE_SIZE = 0x20000
FIP_PHYS_OFF = 0x800
STOCK_BOOT_ENV_OFF = 0x7C000
EXPECTED_ROM_HEADER_SHA256 = "82830140f4f8842702d0569065c27071b7cc24e0876e6c487cb4d9d81c294dd7"
EXPECTED_HYBRID_FIP_SIZE = 0x7B000
MANIFEST_PATH = (ROOT / 'config' / 'MANIFEST.json') if REPO_MODE else (ROOT / 'data' / 'MANIFEST.json')
_URSUS_ROOT_META = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))['ursusboot']
_URSUS_META = _URSUS_ROOT_META['alpha5_test61_candidate']
EXPECTED_HYBRID_FIP_SHA256 = _URSUS_META['fip_sha256']
EXPECTED_U_BOOT_SHA256 = _URSUS_META['raw_bl33_sha256']
TARGET_URSUS = _URSUS_META['version']
CHECKSUM_UUID = bytes.fromhex("a2cceab7f8254b279704633a6fd69ad8")
TB_FW_UUID = bytes.fromhex("5ff9ec0b4d223e4da544c39d81c73f0a")
NT_FW_UUID = bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4")
EXPECTED_STOCK_BL2_SHA256 = "07c9e1542a3de845055faa2244bbd07adc8c5a136811a61a0d678ec8fff5ee5e"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def control_fdt_memreserves(blob: bytes):
    magic=b"\xd0\x0d\xfe\xed"
    offs=[]; pos=0
    while True:
        pos=blob.find(magic,pos)
        if pos<0: break
        offs.append(pos); pos+=1
    if len(offs)!=1:
        raise RuntimeError(f"expected one embedded control DTB, found {len(offs)}")
    off=offs[0]; hdr=struct.unpack_from('>10I',blob,off); p=off+hdr[4]; out=[]
    while p+16<=len(blob):
        addr,size=struct.unpack_from('>QQ',blob,p); p+=16
        if addr==0 and size==0: return out
        out.append((addr,size))
    raise RuntimeError('unterminated embedded FDT memreserve table')


class Tee:
    def __init__(self, *targets):
        self.targets = targets
    def write(self, s):
        for t in self.targets:
            t.write(s)
            t.flush()
        return len(s)
    def flush(self):
        for t in self.targets:
            t.flush()


_STATUS_LINE_RE = re.compile(r"^\[([^]]+)\]\s*(.*)$", re.S)

def _status_line(text: str) -> None:
    """Render bracketed operator statuses through the shared Ursus console theme.

    The installer is imported by ONE-CLICK, so raw print() calls here used to
    drop back to the terminal default color after the backup backend returned.
    Preserve intentional leading blank lines, then route [LABEL] messages via
    console_ui.status(). Plain technical lines remain unstyled.
    """
    while text.startswith("\n"):
        print()
        text = text[1:]
    match = _STATUS_LINE_RE.match(text)
    if match:
        ui.status(match.group(1), match.group(2))
    else:
        print(text)


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def require_payload() -> bytes:
    if not PAYLOAD.is_file():
        raise RuntimeError(f"payload missing: {PAYLOAD}")
    data = PAYLOAD.read_bytes()
    if len(data) != EXPECTED_HYBRID_FIP_SIZE:
        raise RuntimeError(f"target UrsusBoot FIP size mismatch: {len(data)} != {EXPECTED_HYBRID_FIP_SIZE}")
    got = sha_bytes(data)
    if got != EXPECTED_HYBRID_FIP_SHA256:
        raise RuntimeError(f"target UrsusBoot FIP SHA256 mismatch: {got}")
    if data[:4] != b"\x01\x00\x64\xaa":
        raise RuntimeError("target UrsusBoot FIP magic mismatch")
    return data


def validate_checksum_entry(fip: bytes) -> dict:
    # FIP header is 16 bytes; standard entries are 40 bytes and terminated by a zero UUID.
    off = 16
    entry = None
    while off + 40 <= len(fip):
        uuid = fip[off:off+16]
        if uuid == b"\0" * 16:
            break
        payload_off, payload_size, flags = struct.unpack_from("<QQQ", fip, off + 16)
        if uuid == CHECKSUM_UUID:
            entry = (payload_off, payload_size, flags)
            break
        off += 40
    if entry is None:
        raise RuntimeError("FIP checksum UUID entry missing")
    payload_off, payload_size, flags = entry
    if payload_size != 40 or payload_off + payload_size > len(fip):
        raise RuntimeError("FIP checksum payload range invalid")
    covered_len, stored_crc = struct.unpack_from("<II", fip, payload_off)
    stored_sha = fip[payload_off + 8:payload_off + 40]
    if covered_len != payload_off:
        raise RuntimeError(f"FIP checksum len {covered_len:#x} != entry offset {payload_off:#x}")
    calc_crc = zlib.crc32(fip[:payload_off]) & 0xFFFFFFFF
    calc_sha = hashlib.sha256(fip[:payload_off]).digest()
    if stored_crc != calc_crc or stored_sha != calc_sha:
        raise RuntimeError("FIP checksum payload does not match covered bytes")
    return {
        "offset": payload_off,
        "size": payload_size,
        "covered_len": covered_len,
        "crc32": f"{stored_crc:08x}",
        "sha256": stored_sha.hex(),
    }


def fip_entries_from(data: bytes, base: int = 0) -> list[tuple[bytes,int,int,int]]:
    if data[base:base+8] != bytes.fromhex("010064aa78563412"):
        raise RuntimeError(f"FIP header invalid at {base:#x}")
    out=[]; pos=base+16
    while pos+40 <= len(data):
        uuid=data[pos:pos+16]
        if uuid == b"\0"*16:
            break
        off,size,flags=struct.unpack_from("<QQQ",data,pos+16)
        out.append((uuid,off,size,flags)); pos += 40
    return out


def validate_direct_stock_lineage(target: bytes) -> dict:
    """Prove that direct STOCK target keeps the alpha3 early-boot lineage.

    All FIP entries except NT_FW/BL33 and the checksum record must be byte-for-byte
    identical to the exact hardware-proven alpha3 FIP. This makes the direct stock
    transaction a narrow BL33 substitution inside the same proven early boot chain.
    """
    if not ALPHA3_REFERENCE_PAYLOAD.is_file():
        raise RuntimeError(f"alpha3 lineage reference missing: {ALPHA3_REFERENCE_PAYLOAD}")
    alpha3 = ALPHA3_REFERENCE_PAYLOAD.read_bytes()
    if hashlib.sha256(alpha3).hexdigest() != _URSUS_ROOT_META['alpha3_lineage_fip_sha256']:
        raise RuntimeError("alpha3 lineage reference SHA256 mismatch")
    validate_checksum_entry(alpha3)
    validate_checksum_entry(target)
    if alpha3[:16] != target[:16]:
        raise RuntimeError("target FIP header differs from proven alpha3 lineage")
    a_list = fip_entries_from(alpha3)
    t_list = fip_entries_from(target)
    a_entries = {u: (off, size, flags) for u, off, size, flags in a_list}
    t_entries = {u: (off, size, flags) for u, off, size, flags in t_list}
    if len(a_entries) != len(a_list) or len(t_entries) != len(t_list):
        raise RuntimeError("duplicate FIP UUID entry in lineage comparison")
    if set(a_entries) != set(t_entries):
        raise RuntimeError("target FIP entry set differs from proven alpha3 lineage")
    compared = 0
    for uuid, (a_off, a_size, a_flags) in a_entries.items():
        t_off, t_size, t_flags = t_entries[uuid]
        if uuid in (NT_FW_UUID, CHECKSUM_UUID):
            continue
        if (a_off, a_size, a_flags) != (t_off, t_size, t_flags):
            raise RuntimeError(f"target lineage metadata changed for UUID {uuid.hex()}")
        if alpha3[a_off:a_off+a_size] != target[t_off:t_off+t_size]:
            raise RuntimeError(f"target lineage payload changed for UUID {uuid.hex()}")
        compared += 1
    tb = t_entries.get(TB_FW_UUID)
    if not tb:
        raise RuntimeError("target FIP has no Trusted Boot Firmware entry")
    tb_off, tb_size, _ = tb
    tb_sha = sha_bytes(target[tb_off:tb_off+tb_size])
    if tb_sha != EXPECTED_STOCK_BL2_SHA256:
        raise RuntimeError(f"target Trusted Boot Firmware differs from proven lineage: {tb_sha}")
    return {
        "reference": "alpha3",
        "reference_sha256": sha_bytes(alpha3),
        "target_sha256": sha_bytes(target),
        "unchanged_non_bl33_entries": compared,
        "trusted_boot_firmware_sha256": tb_sha,
        "changed_entries": [NT_FW_UUID.hex(), CHECKSUM_UUID.hex()],
    }


def env_crc_info(live: bytes) -> dict:
    env=live[STOCK_BOOT_ENV_OFF:MTD0_SIZE]
    stored=struct.unpack_from("<I",env,0)[0]
    calc=zlib.crc32(env[4:]) & 0xffffffff
    if stored != calc:
        raise RuntimeError(f"live stock boot environment CRC mismatch: stored={stored:08x} calc={calc:08x}")
    return {"stored":f"{stored:08x}","calc":f"{calc:08x}","sha256":sha_bytes(env)}


def build_candidate(live: bytes, hybrid: bytes) -> tuple[bytes, dict]:
    if len(live) != MTD0_SIZE:
        raise RuntimeError(f"live mtd0 size {len(live):#x}, expected {MTD0_SIZE:#x}")
    if live[FIP_PHYS_OFF:FIP_PHYS_OFF+4] != b"\x01\x00\x64\xaa":
        raise RuntimeError("live mtd0 has no Airoha FIP at physical 0x800")
    rom_sha=sha_bytes(live[:FIP_PHYS_OFF])
    if rom_sha != EXPECTED_ROM_HEADER_SHA256:
        raise RuntimeError("live BootROM prefix 0x0..0x7ff differs from the proven Nokia prefix")
    env_meta=env_crc_info(live)
    if FIP_PHYS_OFF + len(hybrid) >= STOCK_BOOT_ENV_OFF:
        raise RuntimeError("hybrid FIP overlaps stock boot environment")

    # Accept either original Nokia mtd0 or an already-installed UrsusBoot revision.  Both must still
    # carry the exact proven Nokia BL2, because that is the persistent first stage.
    es=fip_entries_from(live,FIP_PHYS_OFF)
    tb=[x for x in es if x[0]==TB_FW_UUID]
    if len(tb)!=1:
        raise RuntimeError("live FIP does not contain exactly one Trusted Boot Firmware BL2 entry")
    _,tb_off,tb_size,_=tb[0]
    if FIP_PHYS_OFF+tb_off+tb_size > STOCK_BOOT_ENV_OFF:
        raise RuntimeError("live BL2 FIP range invalid")
    live_tb=live[FIP_PHYS_OFF+tb_off:FIP_PHYS_OFF+tb_off+tb_size]
    live_tb_sha=sha_bytes(live_tb)
    if live_tb_sha != EXPECTED_STOCK_BL2_SHA256:
        raise RuntimeError(f"live persistent BL2 differs from proven Nokia BL2: {live_tb_sha}")

    new_es=fip_entries_from(hybrid,0)
    nt=[x for x in new_es if x[0]==NT_FW_UUID]
    if len(nt)!=1:
        raise RuntimeError("new UrsusBoot hybrid has no unique BL33 entry")

    out=bytearray(live)
    out[FIP_PHYS_OFF:FIP_PHYS_OFF+len(hybrid)] = hybrid
    candidate=bytes(out)
    if candidate[:FIP_PHYS_OFF] != live[:FIP_PHYS_OFF]:
        raise RuntimeError("BootROM prefix preservation invariant failed")
    if candidate[STOCK_BOOT_ENV_OFF:] != live[STOCK_BOOT_ENV_OFF:]:
        raise RuntimeError("stock boot environment preservation invariant failed")
    return candidate,{
        "live_sha256":sha_bytes(live),
        "candidate_sha256":sha_bytes(candidate),
        "live_fip_entries":len(es),
        "live_stock_bl2_sha256":live_tb_sha,
        "rom_header_sha256":rom_sha,
        "environment":env_meta,
        "hybrid_fip_sha256":sha_bytes(hybrid),
        "hybrid_fip_size":len(hybrid),
        "hybrid_physical_range":[FIP_PHYS_OFF,FIP_PHYS_OFF+len(hybrid)],
    }


def open_root() -> tuple[pb.StockAccess, pb.Telnet]:
    access = pb.ask_credentials(require_model_gate=True, offer_interactive_plain_retry=True)
    telnet = pb.login_root_family(access, "md", allow_service_provisioning=True)
    pb.require_supported_model_over_telnet(access, telnet)
    rc, uid = telnet.command_clean("id -u")
    if rc or not re.search(r"(?:^|\n)0(?:\n|$)", uid.strip() + "\n"):
        telnet.close()
        access.close_web(announce=False)
        raise RuntimeError("UID 0 not confirmed")
    return access, telnet


def open_root_auto(host: str = "192.168.1.1") -> tuple[pb.StockAccess, pb.Telnet]:
    """Unattended stock-Web bootstrap using the documented universal Web credentials.

    The device-specific Telnet password is still read from the authenticated stock Web UI.
    No Telnet password is hard-coded or logged.
    """
    module = pb._load_stock_web_module()
    user = str(getattr(module, "DEFAULT_WEB_USER", "CMCCAdmin") or "CMCCAdmin")
    password = str(getattr(module, "DEFAULT_WEB_PASSWORD", "") or "")
    if not password:
        raise RuntimeError("stock Web module has no default password for unattended mode")
    pb._STARTUP_DEVICE_PROFILE.clear()
    pb._STARTUP_DEVICE_PROFILE.update({
        "family": "md", "model": "XG-040G-MD", "chipset": "", "host": host,
        "verified": True, "source": "one-key-auth-cache",
    })
    pb._STARTUP_WEB_AUTH.clear()
    pb._STARTUP_WEB_AUTH.update({"host": host, "user": user, "password": password})
    try:
        access = pb._automatic_stock_web_access(host, module, offer_interactive_plain_retry=False)
    except getattr(module, "LoginError"):
        # Some stock builds accept only the ordinary local HTTP form. Retry once,
        # automatically, with the same universal credentials.
        os.environ["NOKIA_ALLOW_PLAIN_WEB_LOGIN"] = "1"
        pb._STARTUP_DEVICE_PROFILE.clear()
        pb._STARTUP_DEVICE_PROFILE.update({
            "family": "md", "model": "XG-040G-MD", "chipset": "", "host": host,
            "verified": True, "source": "one-key-auth-cache",
        })
        pb._STARTUP_WEB_AUTH.clear()
        pb._STARTUP_WEB_AUTH.update({"host": host, "user": user, "password": password})
        access = pb._automatic_stock_web_access(host, module, offer_interactive_plain_retry=False)
    telnet = pb.login_root_family(access, "md", allow_service_provisioning=True)
    pb.require_supported_model_over_telnet(access, telnet)
    rc, uid = telnet.command_clean("id -u")
    if rc or not re.search(r"(?:^|\n)0(?:\n|$)", uid.strip() + "\n"):
        telnet.close(); access.close_web(announce=False)
        raise RuntimeError("UID 0 not confirmed")
    return access, telnet


MTD0_EXPECTED = (0x00080000, 0x00020000, "bootloader")
MTD_RW_MODULE = PAYLOAD_DIR / "openwrt-6.18.44-mtd-rw.ko"
MTD_RAW_HELPER = PAYLOAD_DIR / "ursus-mtd-raw"


def _tcp_open(host: str, port: int, timeout: float = 1.5) -> bool:
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()


def _ssh_read_binary(host: str, command: str, expected_size: int) -> bytes:
    """Read a fixed binary object over the verified system-OpenSSH session.

    The remote side is not required to provide base64, xxd, Python or SCP.
    stdout is captured as bytes and stderr remains separate in proven_backend.
    """
    blob = pb.ssh_read_binary(host, command, timeout=180)
    if len(blob) != expected_size:
        raise RuntimeError(f"SSH binary read size mismatch: {len(blob)} != {expected_size}")
    return blob


def _ssh_openwrt_identity(host: str) -> dict:
    pb.ensure_root_ssh_session(host)
    cmd = (
        "echo __URSUS_OPENWRT__; "
        "printf 'BOARD='; cat /tmp/sysinfo/board_name 2>/dev/null || true; echo; "
        "printf 'MODEL='; tr -d '\\000' </proc/device-tree/model 2>/dev/null || true; echo; "
        "printf 'COMPAT='; tr '\\000' ' ' </proc/device-tree/compatible 2>/dev/null || true; echo; "
        "printf 'KERNEL='; uname -r; "
        "printf 'UID='; id -u"
    )
    _rc, out = pb.ssh_run(host, cmd, timeout=60, quiet=True, batch_mode=True)
    if "__URSUS_OPENWRT__" not in out or not re.search(r"(?:^|\n)UID=0(?:\n|$)", out):
        raise RuntimeError("root OpenWrt SSH identity was not confirmed")
    fields = {}
    for key in ("BOARD", "MODEL", "COMPAT", "KERNEL"):
        m = re.search(rf"(?:^|\n){key}=([^\n]*)", out)
        fields[key.lower()] = m.group(1).strip() if m else ""
    identity = " ".join(fields.values()).lower().replace("_", "-")
    if "xg-040g-md" not in identity and "xg040g-md" not in identity:
        raise RuntimeError(
            "SSH target is not positively identified as Nokia XG-040G-MD: "
            + " | ".join(f"{k}={v}" for k, v in fields.items())
        )
    fields["host"] = host
    return fields


def _ssh_find_fip_volume(host: str) -> dict | None:
    cmd = (
        "for p in /sys/class/ubi/ubi*_*; do "
        "[ -f \"$p/name\" ] || continue; n=$(cat \"$p/name\" 2>/dev/null); "
        "[ \"$n\" = fip ] || continue; b=$(basename \"$p\"); "
        "t=$(cat \"$p/type\" 2>/dev/null || echo unknown); "
        "d=$(cat \"$p/data_bytes\" 2>/dev/null || echo 0); "
        "echo FIPVOL=$b TYPE=$t DATA=$d; done"
    )
    _rc, out = pb.ssh_run(host, cmd, timeout=30, quiet=True, batch_mode=True)
    hits = re.findall(r"FIPVOL=(ubi\d+_\d+)\s+TYPE=([^\s]+)\s+DATA=(\d+)", out)
    if not hits:
        return None
    if len(hits) != 1:
        raise RuntimeError(f"multiple UBI volumes named fip: {hits}")
    dev, typ, data = hits[0]
    data_bytes = int(data)
    if typ != "static":
        raise RuntimeError(f"UBI fip volume is {typ}, expected static")
    # A static fip volume may report its current data size.  It must at least
    # contain the exact FIP object that we are about to replace.
    if data_bytes and data_bytes < EXPECTED_HYBRID_FIP_SIZE:
        raise RuntimeError(f"UBI fip volume data_bytes too small: {data_bytes}")
    return {"device": f"/dev/{dev}", "sysfs": dev, "type": typ, "data_bytes": data_bytes}


def _ssh_mtd_table(host: str) -> list[dict]:
    _rc, out = pb.ssh_run(host, "cat /proc/mtd", timeout=30, quiet=True, batch_mode=True)
    entries = []
    for idx, size_hex, erase_hex, name in re.findall(
        r'^mtd(\d+):\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+"([^"]+)"', out, re.M
    ):
        i = int(idx)
        q = (
            f"printf 'OFF='; cat /sys/class/mtd/mtd{i}/offset 2>/dev/null || echo NA; "
            f"printf 'FLAGS='; cat /sys/class/mtd/mtd{i}/flags 2>/dev/null || echo NA"
        )
        _r, meta = pb.ssh_run(host, q, timeout=20, quiet=True, batch_mode=True)
        mo = re.search(r"OFF=([^\n]+)", meta)
        mf = re.search(r"FLAGS=([^\n]+)", meta)
        off_raw = mo.group(1).strip() if mo else "NA"
        flags_raw = mf.group(1).strip() if mf else "NA"
        try:
            offset = int(off_raw, 0)
        except ValueError:
            offset = None
        try:
            flags = int(flags_raw, 0)
        except ValueError:
            flags = None
        entries.append({
            "index": i,
            "device": f"/dev/mtd{i}",
            "size": int(size_hex, 16),
            "erase": int(erase_hex, 16),
            "name": name,
            "offset": offset,
            "flags": flags,
        })
    return entries


def _ssh_resolve_raw_boot_target(host: str, hybrid: bytes, before_path: Path) -> tuple[dict, bytes, dict]:
    entries = _ssh_mtd_table(host)
    candidates = []
    for e in entries:
        name = e["name"].lower()
        exact_boot = e["size"] == MTD0_SIZE and name in ("bootloader", "boot", "mtd0")
        master_zero = (
            e["size"] >= MTD0_SIZE
            and (
                e["offset"] == 0
                or (
                    e["offset"] is None
                    and e["index"] == 0
                    and name in ("all_flash", "all-flash", "flash", "master")
                )
            )
        )
        if exact_boot or master_zero:
            candidates.append(e)
    if not candidates:
        raise RuntimeError("BOOT_TARGET_UNAVAILABLE: no MTD object unambiguously covers physical 0x0..0x7ffff")

    proven = []
    failures = []
    for e in candidates:
        try:
            blob = _ssh_read_binary(
                host,
                f"dd if={shlex.quote(e['device'])} bs={ERASE_SIZE} count=4 2>/dev/null",
                MTD0_SIZE,
            )
            _candidate, meta = build_candidate(blob, hybrid)
            proven.append((e, blob, meta))
        except Exception as exc:
            failures.append(f"{e['device']}({e['name']}): {exc}")
    if len(proven) != 1:
        if not proven:
            raise RuntimeError(
                "BOOT_TARGET_UNAVAILABLE: candidate MTD objects exist but none contains a content-proven stock-style boot block; "
                + " | ".join(failures)
            )
        raise RuntimeError("BOOT_TARGET_UNAVAILABLE: more than one content-proven raw boot target")
    target, blob, meta = proven[0]
    before_path.write_bytes(blob)
    return target, blob, meta


def _ssh_make_mtd_writable_if_needed(host: str, target: dict) -> bool:
    flags = target.get("flags")
    # Linux MTD_WRITEABLE == 0x400. Unknown flags are not treated as read-only;
    # the selected writer remains authoritative and no fallback occurs after it starts.
    if flags is None or (flags & 0x400):
        return False
    _status_line("[ИНФО] Ядро пометило raw MTD как read-only; подключаю комплектный mtd-rw только для текущего сеанса.")
    if not MTD_RW_MODULE.is_file():
        raise RuntimeError("raw boot MTD is read-only and bundled mtd-rw module is missing")
    _rc, kernel_out = pb.ssh_run(host, "uname -r", timeout=20, quiet=True, batch_mode=True)
    kernel = kernel_out.strip().splitlines()[-1] if kernel_out.strip() else ""
    if kernel != "6.18.44":
        raise RuntimeError(f"raw boot MTD is read-only; bundled mtd-rw is for kernel 6.18.44, running {kernel}")
    remote = "/tmp/ursus-mtd-rw.ko"
    pb.scp_copy_to_recovery(host, MTD_RW_MODULE, remote, timeout=300)
    expected = sha_file(MTD_RW_MODULE)
    _rc, out = pb.ssh_run(host, f"sha256sum {remote}; insmod {remote} i_want_a_brick=1", timeout=60, quiet=True, batch_mode=True)
    if expected not in out:
        raise RuntimeError("mtd-rw transfer SHA256 mismatch")
    return True


def _ssh_raw_writer(host: str, target: dict) -> str:
    if MTD_RAW_HELPER.is_file():
        return "ursus-mtd-raw"
    _rc, out = pb.ssh_run(
        host,
        "for x in mtd mtd_debug flash_erase nandwrite sha256sum dd; do command -v $x 2>/dev/null && echo TOOL:$x; done",
        timeout=30,
        quiet=True,
        batch_mode=True,
    )
    tools = set(re.findall(r"TOOL:([A-Za-z0-9_]+)", out))
    dedicated = target["size"] == MTD0_SIZE
    if "mtd_debug" in tools:
        return "mtd_debug"
    if "flash_erase" in tools and "nandwrite" in tools:
        return "flash_erase+nandwrite"
    if dedicated and "mtd" in tools:
        return "mtd"
    if not dedicated:
        raise RuntimeError("all_flash/master target requires partial writer mtd_debug or flash_erase+nandwrite")
    raise RuntimeError("no supported OpenWrt raw MTD writer found")


def _ssh_write_raw(host: str, target: dict, remote: str, method: str) -> tuple[int, str]:
    dev = shlex.quote(target["device"])
    if method == "ursus-mtd-raw":
        cmd = f"/tmp/ursus-mtd-raw write {dev} {shlex.quote(remote)} {MTD0_SIZE}"
    elif method == "mtd_debug":
        cmd = f"mtd_debug erase {dev} 0 {MTD0_SIZE} && mtd_debug write {dev} 0 {MTD0_SIZE} {shlex.quote(remote)}"
    elif method == "flash_erase+nandwrite":
        cmd = f"flash_erase {dev} 0 4 && nandwrite -p -s 0 {dev} {shlex.quote(remote)}"
    elif method == "mtd":
        cmd = f"mtd -f write {shlex.quote(remote)} {shlex.quote(target['name'])}"
    else:
        raise RuntimeError(f"unsupported OpenWrt raw writer: {method}")
    # Destructive boundary: never try a second writer after this command is issued.
    return pb.ssh_run(host, cmd + " && sync", timeout=600, quiet=True, batch_mode=True)


def _ssh_confirm_write(unattended: bool, description: str, backup: Path) -> bool:
    if unattended:
        return True
    _status_line("[ВНИМАНИЕ] Сейчас начнётся запись NAND. После начала записи автоматического fallback на другой writer не будет.")
    print(description)
    print(f"Копия текущего boot object: {backup}")
    return ui.prompt("Начать запись? [y/N]: ").strip().lower() in ("y", "yes", "д", "да")


def run_install_ssh(*, host: str, hybrid: bytes, unattended: bool = False) -> int:
    """Install/restore persistent UrsusBoot from OpenWrt over root SSH.

    Healthy OPENWRT_UBI updates the existing static fip volume.  Otherwise the
    backend may use a content-proven stock-style physical boot block.  Layout
    classification itself is diagnostic and never an authorization gate.
    """
    PRIVATE.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    run_stamp = stamp()
    result_path = RESULTS / f"UrsusBoot-{TARGET_URSUS}-ssh-{run_stamp}.json"
    result = {
        "version": TARGET_URSUS,
        "operation": "persistent_install_over_openwrt_ssh",
        "host": host,
        "status": "RUNNING",
        "started_at": run_stamp,
    }
    identity = _ssh_openwrt_identity(host)
    result["identity"] = identity
    _status_line(f"[ГОТОВО] Root SSH подтверждён: {identity.get('board') or identity.get('model') or host}")

    # Prefer the native UBI fip object when it exists. This updates only BL33/FIP
    # content and never touches the raw BL2 eraseblocks.
    fipvol = _ssh_find_fip_volume(host)
    if fipvol:
        _rc, tools = pb.ssh_run(
            host,
            "command -v ubiupdatevol >/dev/null 2>&1 && echo UBIUPDATEVOL_OK",
            timeout=30,
            quiet=True,
            batch_mode=True,
        )
        if "UBIUPDATEVOL_OK" not in tools:
            raise RuntimeError("existing UBI fip volume found, but ubiupdatevol is unavailable")
        before = PRIVATE / f"fip-before-{run_stamp}.bin"
        current = _ssh_read_binary(
            host,
            f"dd if={shlex.quote(fipvol['device'])} bs=4096 count=123 2>/dev/null",
            EXPECTED_HYBRID_FIP_SIZE,
        )
        before.write_bytes(current)
        result["backend"] = "ubi_fip"
        result["fip_volume"] = fipvol
        result["backup"] = str(before)
        result["before_sha256"] = sha_bytes(current)
        target_sha = sha_bytes(hybrid)
        if current == hybrid:
            result["status"] = "ALREADY_EXACT"
            result["readback_sha256"] = target_sha
            result["completed_at"] = stamp()
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            _status_line("[ГОТОВО] Existing UBI fip already contains the exact target UrsusBoot; NAND write skipped.")
            return 0
        remote = "/tmp/ursusboot-target.fip"
        temp = PRIVATE / f"target-{run_stamp}.fip"
        temp.write_bytes(hybrid)
        pb.scp_copy_to_recovery(host, temp, remote, timeout=600)
        _rc, check = pb.ssh_run(host, f"wc -c < {remote}; sha256sum {remote}", timeout=60, quiet=True, batch_mode=True)
        if str(EXPECTED_HYBRID_FIP_SIZE) not in check or target_sha not in check.lower():
            raise RuntimeError("remote target UrsusBoot FIP transfer verification failed")
        if not _ssh_confirm_write(unattended, f"Обновляется только {fipvol['device']} (UBI volume fip), {EXPECTED_HYBRID_FIP_SIZE} байт.", before):
            result["status"] = "CANCELLED_BEFORE_WRITE"
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return 2
        result["write_started_at"] = stamp()
        try:
            pb.ssh_run(host, f"ubiupdatevol {shlex.quote(fipvol['device'])} {remote} && sync", timeout=600, quiet=True, batch_mode=True)
        except Exception as exc:
            result["status"] = "WRITE_STATE_UNKNOWN"
            result["error"] = str(exc)
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise RuntimeError("UBI FIP write started but completion is unproven; automatic retry is forbidden") from exc
        _rc, out = pb.ssh_run(
            host,
            f"dd if={shlex.quote(fipvol['device'])} bs=4096 count=123 2>/dev/null | sha256sum",
            timeout=180,
            quiet=True,
            batch_mode=True,
        )
        if target_sha not in out.lower():
            result["status"] = "READBACK_MISMATCH"
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise RuntimeError("UBI FIP full readback SHA256 mismatch; do not reboot")
        result["readback_sha256"] = target_sha
        result["status"] = "WRITE_AND_READBACK_PASS"
        result["completed_at"] = stamp()
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _status_line(f"[ГОТОВО] UBI fip записан и полностью сверен: {target_sha}")
        return 0

    # UBI may be absent or broken.  Resolve the physical boot target by MTD
    # geometry plus exact content proof; LAYOUT_UNKNOWN is not a blocker.
    before = PRIVATE / f"bootblock-before-{run_stamp}.bin"
    target, live, meta = _ssh_resolve_raw_boot_target(host, hybrid, before)
    candidate, _ = build_candidate(live, hybrid)
    candidate_path = PRIVATE / f"bootblock-target-{run_stamp}.bin"
    candidate_path.write_bytes(candidate)
    result["backend"] = "raw_boot_block"
    result["raw_target"] = target
    result["backup"] = str(before)
    result["candidate"] = meta
    expected = sha_bytes(candidate)
    if sha_bytes(live) == expected:
        result["status"] = "ALREADY_EXACT"
        result["readback_sha256"] = expected
        result["completed_at"] = stamp()
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _status_line("[ГОТОВО] Physical boot block already contains the exact target UrsusBoot hybrid; write skipped.")
        return 0
    _ssh_make_mtd_writable_if_needed(host, target)
    writer = _ssh_raw_writer(host, target)
    result["writer"] = writer
    remote = "/tmp/ursusboot-bootblock-target.bin"
    pb.scp_copy_to_recovery(host, candidate_path, remote, timeout=600)
    _rc, check = pb.ssh_run(host, f"wc -c < {remote}; sha256sum {remote}", timeout=60, quiet=True, batch_mode=True)
    if str(MTD0_SIZE) not in check or expected not in check.lower():
        raise RuntimeError("remote raw boot-block transfer verification failed")
    if writer == "ursus-mtd-raw":
        helper_remote = "/tmp/ursus-mtd-raw"
        helper_sha = sha_file(MTD_RAW_HELPER)
        pb.scp_copy_to_recovery(host, MTD_RAW_HELPER, helper_remote, timeout=300)
        _rc, helper_check = pb.ssh_run(
            host,
            f"chmod 700 {helper_remote}; sha256sum {helper_remote}; uname -m",
            timeout=60,
            quiet=True,
            batch_mode=True,
        )
        if helper_sha not in helper_check.lower() or "aarch64" not in helper_check.lower():
            raise RuntimeError("raw MTD helper transfer/architecture verification failed")
        result["raw_helper_sha256"] = helper_sha
    if not _ssh_confirm_write(
        unattended,
        f"Физический boot block 0x0..0x7ffff через {target['device']} ({target['name']}), writer={writer}.",
        before,
    ):
        result["status"] = "CANCELLED_BEFORE_WRITE"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 2
    result["write_started_at"] = stamp()
    try:
        _ssh_write_raw(host, target, remote, writer)
    except Exception as exc:
        result["status"] = "WRITE_STATE_UNKNOWN"
        result["error"] = str(exc)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError("raw boot-block write started but completion is unproven; automatic retry is forbidden") from exc
    _rc, out = pb.ssh_run(
        host,
        f"dd if={shlex.quote(target['device'])} bs={ERASE_SIZE} count=4 2>/dev/null | sha256sum",
        timeout=180,
        quiet=True,
        batch_mode=True,
    )
    if expected not in out.lower():
        result["status"] = "READBACK_MISMATCH"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError("raw boot-block full readback SHA256 mismatch; do not reboot")
    result["readback_sha256"] = expected
    result["status"] = "WRITE_AND_READBACK_PASS"
    result["completed_at"] = stamp()
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _status_line(f"[ГОТОВО] Physical boot block записан и полностью сверен: {expected}")
    return 0


def _require_mtd0_target(telnet: pb.Telnet, *, check_bad_blocks: bool = True) -> dict:
    """Validate only the physical target that this operation will write."""
    rc, proc_text = telnet.command_clean("cat /proc/mtd")
    if rc:
        raise RuntimeError("cannot read /proc/mtd")
    proc = pb.parse_proc_mtd_text(proc_text)
    if proc.get(0) != MTD0_EXPECTED:
        raise RuntimeError(f"mtd0 mismatch: got {proc.get(0)!r}, expected {MTD0_EXPECTED!r}")

    bad_blocks = None
    if check_bad_blocks:
        _rc, bad_text = telnet.command_clean("cat /sys/class/mtd/mtd0/bad_blocks 2>/dev/null || echo unavailable")
        m = re.search(r"(?:^|\n)(\d+)(?:\n|$)", bad_text)
        if m:
            bad_blocks = int(m.group(1))
            if bad_blocks != 0:
                raise RuntimeError(f"bootloader mtd0 reports {bad_blocks} bad blocks")
    return {
        "mtd0": {"size": MTD0_EXPECTED[0], "erase": MTD0_EXPECTED[1], "name": MTD0_EXPECTED[2]},
        "mtd0_bad_blocks": bad_blocks,
    }


def mtd0_write_preflight(telnet: pb.Telnet) -> dict:
    """Minimal pre-write gate for STOCK mtd0 install/restore.

    Do not require unrelated mtd1/mtd14/mtd15/mtd16 geometry here. Full-stock
    backup has its own restore-grade validator; a bootloader-only write targets
    only mtd0.
    """
    target = _require_mtd0_target(telnet)
    _rc, tools_text = telnet.command_clean(
        "for x in mtd flash_erase flash_eraseall nandwrite mtd_debug tftp sha256sum dd; do "
        "p=$(command -v $x 2>/dev/null || true); [ -n \"$p\" ] && echo TOOL:$x=$p; done"
    )
    tools = dict(re.findall(r"^TOOL:([A-Za-z0-9_]+)=(.+)$", tools_text, re.M))
    if "sha256sum" not in tools or "dd" not in tools:
        raise RuntimeError("stock Linux lacks dd or sha256sum")
    if "tftp" not in tools:
        pb.find_tftp(telnet)
        tools["tftp"] = "busybox/app"
    writer = select_writer(telnet, tools)
    return {**target, "tools": tools, "writer": writer}


def revalidate_mtd0_target(telnet: pb.Telnet) -> dict:
    """Cheap post-backup revalidation: same writable target, no repeated tool/layout exam."""
    return _require_mtd0_target(telnet)


def select_writer(telnet: pb.Telnet, tools: dict[str, str]) -> str:
    if "mtd" in tools:
        _, help_text = telnet.command_clean("mtd --help 2>&1 || mtd 2>&1 || true", timeout=20)
        low = help_text.lower()
        # Accept only the well-known Linux userspace mtd tool family where write takes
        # an image and MTD device/partition. We never auto-fallback after a write starts.
        if "write" in low and ("erase" in low or "usage" in low):
            return "mtd"
    if "flash_erase" in tools and "nandwrite" in tools:
        return "flash_erase+nandwrite"
    if "flash_eraseall" in tools and "nandwrite" in tools:
        return "flash_eraseall+nandwrite"
    if "mtd_debug" in tools:
        return "mtd_debug"
    raise RuntimeError("no supported NAND writer found in stock Linux")


def receive_remote_file(telnet: pb.Telnet, host: str, remote: str, local: Path,
                        *, port: int = 1069, block_size: int = 4096) -> None:
    tftp = pb.find_tftp(telnet)
    local_ip = pb.local_ip_for(host)
    expected_name = local.name
    ready = threading.Event()
    result = pb.TftpResult()
    thread = threading.Thread(
        target=pb.receive_tftp_put,
        args=("0.0.0.0", port, local, expected_name, host, ready, result),
        kwargs={"timeout": 180, "maximum_block_size": block_size},
        daemon=True,
    )
    thread.start()
    if not ready.wait(5) or result.error:
        raise RuntimeError(f"cannot start local TFTP PUT receiver: {result.error or 'timeout'}")
    command = (
        f"{shlex.quote(tftp)} -p -l {shlex.quote(remote)} -r {shlex.quote(expected_name)} "
        f"-b {block_size} {shlex.quote(local_ip)} {port}"
    )
    telnet.send_line(command + "; __rc=$?; echo __URSUS_PUT_${__rc}__")
    thread.join(timeout=360)
    if thread.is_alive():
        raise RuntimeError("TFTP PUT from Nokia timed out")
    text = telnet.wait_regex(r"__URSUS_PUT_(\d+)__", 60, echo=False)
    m = re.search(r"__URSUS_PUT_(\d+)__", text)
    if result.error or not m or m.group(1) != "0":
        raise RuntimeError(f"TFTP PUT from Nokia failed: {result.error or 'router rc != 0'}")


def capture_live_mtd0(telnet: pb.Telnet, access: pb.StockAccess, out: Path) -> tuple[str, str]:
    remote = "/tmp/ursusboot-mtd0-before.bin"
    rc, text = telnet.command_clean(
        f"rm -f {remote}; dd if=/dev/mtd0 of={remote} bs=131072 count=4 2>/tmp/ursus-dd.log && "
        f"wc -c < {remote} && sha256sum {remote}",
        timeout=90,
    )
    if rc:
        raise RuntimeError("failed to capture live mtd0 on Nokia")
    size_matches = re.findall(r"(?:^|\n)\s*(\d+)\s*(?:\n|$)", text)
    if not size_matches or int(size_matches[-1]) != MTD0_SIZE:
        raise RuntimeError(f"live mtd0 capture has unexpected size: {text[-500:]}")
    hashes = re.findall(r"\b([0-9a-fA-F]{64})\b", text)
    if not hashes:
        raise RuntimeError("remote live mtd0 SHA256 was not returned")
    remote_sha = hashes[-1].lower()
    receive_remote_file(telnet, access.host, remote, out)
    if out.stat().st_size != MTD0_SIZE or sha_file(out) != remote_sha:
        raise RuntimeError("PC copy of live mtd0 does not match the Nokia copy")
    return remote, remote_sha


def upload_candidate(telnet: pb.Telnet, access: pb.StockAccess, candidate: Path) -> str:
    remote = "/tmp/ursusboot-mtd0.bin"
    pb.send_file_to_router_tftp(telnet, access.host, candidate, remote, port=1069, block_size=4096)
    return remote


def remote_mtd0_sha(telnet: pb.Telnet) -> str:
    rc, text = telnet.command_clean("dd if=/dev/mtd0 bs=131072 count=4 2>/dev/null | sha256sum", timeout=120)
    if rc:
        raise RuntimeError("read-back SHA256 command failed")
    hashes = re.findall(r"\b([0-9a-fA-F]{64})\b", text)
    if not hashes:
        raise RuntimeError("read-back SHA256 not found")
    return hashes[-1].lower()


def write_image(telnet: pb.Telnet, remote: str, method: str) -> tuple[int, str]:
    if method == "mtd":
        cmd = f"mtd write {shlex.quote(remote)} bootloader"
    elif method == "flash_erase+nandwrite":
        cmd = f"flash_erase /dev/mtd0 0 0 && nandwrite -p /dev/mtd0 {shlex.quote(remote)}"
    elif method == "flash_eraseall+nandwrite":
        cmd = f"flash_eraseall /dev/mtd0 && nandwrite -p /dev/mtd0 {shlex.quote(remote)}"
    elif method == "mtd_debug":
        cmd = f"mtd_debug erase /dev/mtd0 0 {MTD0_SIZE} && mtd_debug write /dev/mtd0 0 {MTD0_SIZE} {shlex.quote(remote)}"
    else:
        raise RuntimeError(f"unsupported writer: {method}")
    # Once this command starts, do not try another writer automatically.
    rc, text = telnet.command_clean(cmd + " && sync", timeout=300)
    return rc, text


def probe_http_kind(host: str) -> str | None:
    try:
        with socket.create_connection((host, 80), timeout=2.0) as sock:
            sock.settimeout(2.0)
            sock.sendall(b"GET / HTTP/1.0\r\nHost: 192.168.1.1\r\nConnection: close\r\n\r\n")
            data = bytearray()
            while len(data) < 65536:
                try:
                    chunk = sock.recv(8192)
                except socket.timeout:
                    break
                if not chunk:
                    break
                data.extend(chunk)
            low = bytes(data).lower()
            if b"ursusboot" in low or b"web recovery" in low:
                return "ursus_recovery"
            if b"openwrt" in low or b"luci" in low or b"/cgi-bin/luci" in low:
                return "openwrt_http"
            stock_markers = (b"newmethodlogin", b"login.cgi", b"cmccadmin", b"crypto_page", b"jsencrypt", b"encrypted=1")
            hits = sum(marker in low for marker in stock_markers)
            if hits >= 2 and (b"login.cgi" in low or b"newmethodlogin" in low):
                return "stock_http"
            if low.startswith(b"http/"):
                return "generic_http"
    except OSError:
        return None
    return None


def wait_http_kind(host: str, timeout: int) -> str | None:
    end = time.time() + timeout
    while time.time() < end:
        kind = probe_http_kind(host)
        if kind:
            return kind
        time.sleep(2)
    return None


def run_stock_access_check() -> int:
    """Access check only. It must never run destructive preflight gates."""
    ui.enable()
    access = telnet = None
    try:
        access, telnet = open_root()
        _status_line(pb.tr(
            "\n[ГОТОВО] Заводская прошивка Nokia доступна: веб-интерфейс, Telnet, root-доступ и модель подтверждены. Ничего не записывалось.",
            "\n[READY] Nokia factory firmware is reachable: web interface, Telnet, root access and model are confirmed. Nothing was written.",
        ))
        return 0
    finally:
        if telnet:
            telnet.close()
        if access:
            access.close_web(announce=False)


def run_preflight_only() -> int:
    # Legacy CLI name; behavior is intentionally access-only.
    return run_stock_access_check()


def run_install(*, unattended: bool = False, host: str = "192.168.1.1", recovery_after: bool = False, recovery_host: str = "192.168.1.1", route: str = "auto", skip_full_backup: bool = False) -> int:
    ui.enable()
    hybrid = require_payload()
    checksum = validate_checksum_entry(hybrid)
    lineage = validate_direct_stock_lineage(hybrid)

    route = route.strip().lower()
    if route not in ("auto", "openwrt", "stock"):
        raise RuntimeError(f"unsupported install route: {route}")

    # ROUTE1: transports are selected only from positive environment proof.
    # An open TCP/23 is never evidence of Nokia STOCK.  This matters for
    # third-party OpenWrt builds that expose both SSH and Telnet.
    if route == "auto":
        if _tcp_open(host, 22):
            try:
                _ssh_openwrt_identity(host)
            except Exception as ssh_exc:
                kind = probe_http_kind(host)
                if kind != "stock_http":
                    raise RuntimeError(
                        "AUTO route could not positively identify OpenWrt or Nokia STOCK; "
                        "stock Web/Telnet fallback is disabled. SSH cause: " + str(ssh_exc)
                    ) from ssh_exc
                route = "stock"
            else:
                route = "openwrt"
        else:
            kind = probe_http_kind(host)
            if kind == "stock_http":
                route = "stock"
            elif kind == "openwrt_http":
                raise RuntimeError("OpenWrt HTTP was detected but root SSH is unavailable")
            else:
                raise RuntimeError("AUTO route could not positively identify OpenWrt or Nokia STOCK")

    if route == "openwrt":
        _ssh_openwrt_identity(host)
        rc = run_install_ssh(host=host, hybrid=hybrid, unattended=unattended)
        if rc == 0 and recovery_after:
            print()
            _status_line(pb.tr(
                f"[СДЕЛАЙТЕ] UrsusBoot {TARGET_URSUS} уже записан и сверен. После reboot сразу зажмите Reset и держите до 2 коротких + 3 длинных красных миганий и постоянного красного света; затем отпустите.",
                f"[ACTION] UrsusBoot {TARGET_URSUS} is written and verified. After reboot immediately hold Reset through 2 short + 3 long red flashes and steady red, then release.",
            ))
            ui.prompt(pb.tr("Нажмите Enter для перезагрузки OpenWrt: ", "Press Enter to reboot OpenWrt: "))
            try:
                pb.ssh_run(host, "sync; reboot -f", timeout=30, allow_disconnect=True, quiet=True)
            except Exception:
                pass
        return rc

    PRIVATE.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    run_stamp = stamp()
    log_path = RESULTS / f"ursusboot-install-{run_stamp}.log"
    result_path = RESULTS / f"UrsusBoot-{TARGET_URSUS}-{run_stamp}.json"
    before_path = PRIVATE / f"mtd0-before-{run_stamp}.bin"
    candidate_path = PRIVATE / f"mtd0-ursusboot-{run_stamp}.bin"

    access = telnet = None
    result: dict = {
        "version": TARGET_URSUS,
        "operation": "persistent_install",
        "started_at": run_stamp,
        "status": "RUNNING",
        "recovery_host": recovery_host,
        "direct_stock_lineage": lineage,
        "hybrid_fip": {
            "size": len(hybrid),
            "sha256": sha_bytes(hybrid),
            "checksum": checksum,
        },
    }

    original_stdout = sys.stdout
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        sys.stdout = Tee(original_stdout, log)
        try:
            print(f"UrsusBoot {TARGET_URSUS} — прямая установка со stock")
            print("Записывается только mtd0. Системные разделы Nokia master/slave не трогаю.\n")
            access, telnet = open_root_auto(host) if unattended else open_root()
            result["host"] = access.host
            pf = mtd0_write_preflight(telnet)
            result["preflight"] = pf
            _status_line(f"[ГОТОВО] Целевой раздел mtd0 загрузчика подтверждён. Способ записи: {pf['writer']}")
            if skip_full_backup:
                # EXPERT-only test convenience: caller explicitly chose to skip the
                # long mtd0..mtd16 capture for this run. The live mtd0 capture below
                # is still mandatory because prefix/env must come from this device.
                result["full_stock_backup"] = None
                result["full_stock_backup_skipped"] = True
                _status_line(pb.tr(
                    "[EXPERT] Полный backup mtd0..mtd16 пропущен для этого запуска по выбору оператора.",
                    "[EXPERT] Full mtd0..mtd16 backup skipped for this run by operator choice.",
                ))
            else:
                # Normal ONE-CLICK requires a complete restore-grade stock backup
                # before the first destructive write.
                FULL_BACKUPS.mkdir(parents=True, exist_ok=True)
                full_backup = FULL_BACKUPS / f"stock-full-{run_stamp}"
                _status_line(pb.tr(
                    "[ШАГ] До записи NAND сохраняю полную копию mtd0..mtd16. Запись не начнётся, пока копия не пройдёт проверку восстановления.",
                    "[BACKUP] Before writing NAND, capturing a complete stock mtd0..mtd16 backup. No write starts until the restore validator passes.",
                ))
                telnet.close()
                telnet = None
                pb.backup_tftp(access, access.host, full_backup, expected_family="md")
                result["full_stock_backup"] = str(full_backup)
                identity_json = full_backup / "DEVICE_IDENTITY.json"
                if identity_json.is_file():
                    try:
                        result["device_identity"] = json.loads(identity_json.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                _status_line(pb.tr(
                    f"[ГОТОВО] Полная копия заводской прошивки Nokia сохранена: {full_backup}",
                    f"[PASS] Complete stock backup saved: {full_backup}",
                ))

                # Re-open root after the long read-only backup and revalidate only
                # the actual destructive target. Do not repeat unrelated gates.
                telnet = pb.login_root_family(access, "md", allow_service_provisioning=True)
                pb.require_supported_model_over_telnet(access, telnet)
                rc, uid = telnet.command_clean("id -u")
                if rc or not re.search(r"(?:^|\n)0(?:\n|$)", uid.strip() + "\n"):
                    raise RuntimeError("UID 0 not confirmed after full backup")
                target_after = revalidate_mtd0_target(telnet)
                result["mtd0_revalidated_after_full_backup"] = target_after
                _status_line("[ГОТОВО] После копирования повторно подтверждён только целевой mtd0.")
            remote_before, remote_sha = capture_live_mtd0(telnet, access, before_path)
            _status_line(f"[ГОТОВО] Текущий mtd0 сохранён на компьютере: {before_path}")
            _status_line(f"[ГОТОВО] SHA256 текущего mtd0: {remote_sha}")
            live = before_path.read_bytes()
            candidate, meta = build_candidate(live, hybrid)
            candidate_path.write_bytes(candidate)
            result["image"] = meta
            result["private_backup"] = str(before_path)
            result["private_candidate"] = str(candidate_path)
            _status_line(f"[ГОТОВО] Новый образ mtd0 подготовлен из считанного mtd0: {meta['candidate_sha256']}")
            _status_line("[ГОТОВО] ROM prefix сохранён: 0x00000000..0x000007ff")
            _status_line("[ГОТОВО] env сохранён: 0x0007c000..0x0007ffff")
            _status_line(f"[ГОТОВО] FIP UrsusBoot занимает только 0x00000800..0x{FIP_PHYS_OFF + len(hybrid) - 1:08x}")
            expected_sha = meta["candidate_sha256"]
            already_exact = (remote_sha == expected_sha)
            result["target_already_exact"] = already_exact

            if already_exact:
                _status_line(f"[ГОТОВО] В mtd0 уже находится точный UrsusBoot {TARGET_URSUS}; SHA256 совпадает с подготовленным образом.")
                _status_line("[ИНФО] Повторная запись NAND не нужна и будет пропущена. Перехожу только к входу в Recovery.")
                after_sha = remote_sha
                result["readback_sha256"] = after_sha
                result["status"] = "BOOTSTRAP_ALREADY_EXACT"
            else:
                remote_candidate = upload_candidate(telnet, access, candidate_path)
                rc, remote_verify = telnet.command_clean(f"wc -c < {remote_candidate}; sha256sum {remote_candidate}", timeout=60)
                if rc or expected_sha not in remote_verify.lower():
                    raise RuntimeError("candidate SHA256 on Nokia does not match PC")
                _status_line("[ГОТОВО] Новый образ mtd0 передан в роутер, SHA256 совпал.")
                _status_line("\n[ГОТОВО] Новый mtd0 подготовлен. Размер загрузочного блока: 512 КиБ.")
                print("Разделы Nokia master/slave в эту запись не входят.")
                _status_line("\n[ВНИМАНИЕ] Сейчас начнётся запись в NAND. После начала записи питание не отключать.")
                print(f"Что записываю: FIP с UrsusBoot {TARGET_URSUS} в mtd0, 512 КиБ.")
                print(f"Копия текущего mtd0: {before_path}")
                answer = ui.prompt("Начать запись mtd0? [y/N]: ").strip().lower()
                if answer not in ("y", "yes", "д", "да"):
                    result["status"] = "CANCELLED_BEFORE_WRITE"
                    result["completed_at"] = stamp()
                    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    _status_line("[СТОП] Отменено до записи. Копия текущего mtd0 осталась на компьютере.")
                    return 2

                result["write_started_at"] = stamp()
                _status_line(f"\n[ШАГ] Начинаю запись mtd0. Способ: {pf['writer']}")
                rc, write_out = write_image(telnet, remote_candidate, pf["writer"])
                result["write_rc"] = rc
                result["write_output_tail"] = write_out[-4000:]
                if rc:
                    result["status"] = "WRITE_COMMAND_FAILED"
                    raise RuntimeError(f"NAND writer returned rc={rc}; no automatic second writer will be attempted")

                after_sha = remote_mtd0_sha(telnet)
                result["readback_sha256"] = after_sha
                if after_sha != expected_sha:
                    result["status"] = "READBACK_MISMATCH"
                    _status_line(f"[ОШИБКА] SHA256 после записи: {after_sha}")
                    _status_line(f"[ОШИБКА] Ожидался SHA256: {expected_sha}")
                    print(f"Копия исходного mtd0: {before_path}")
                    _status_line("[ОШИБКА] Проверка после записи не пройдена. НЕ перезагружайте и не выключайте роутер; текущая Telnet-сессия ещё доступна для восстановления.")
                    result["completed_at"] = stamp()
                    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    return 3

                _status_line(f"[ГОТОВО] mtd0 считан обратно, SHA256 совпал: {after_sha}")
                result["status"] = "WRITE_AND_READBACK_PASS"
            result["completed_at"] = stamp()
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            if unattended and recovery_after:
                print()
                if already_exact:
                    _status_line(pb.tr(
                        f"[ГОТОВО] Точный UrsusBoot {TARGET_URSUS} уже был в mtd0; повторная запись пропущена.",
                        f"[OK] Exact UrsusBoot {TARGET_URSUS} was already present in mtd0; the rewrite was skipped.",
                    ))
                else:
                    _status_line(pb.tr(
                        f"[ГОТОВО] UrsusBoot {TARGET_URSUS} напрямую записан в mtd0 и считан обратно для сверки.",
                        f"[OK] UrsusBoot {TARGET_URSUS} was written directly to mtd0 and passed readback.",
                    ))
                _status_line(pb.tr(
                    "[СДЕЛАЙТЕ] После перезагрузки следите за индикаторами роутера: когда они все мигнут/перезапустятся, сразу зажмите Reset. Держите до красной последовательности 2 коротких + 3 длинных и постоянного красного света; затем отпустите.",
                    "[ACTION] During reboot watch the router LEDs: when they blink/restart together, immediately hold Reset. Keep it held through 2 short + 3 long red flashes and steady red, then release.",
                ))
                ui.prompt(pb.tr(
                    "Нажмите Enter для перезагрузки: ",
                    "Press Enter to reboot: ",
                ))
                _status_line(pb.tr("[ШАГ] Отправляю команду перезагрузки...", "[STEP] Sending reboot command..."))
                try:
                    telnet.send_line("sync; reboot")
                    time.sleep(0.5)
                except Exception:
                    pass
                _status_line(pb.tr(
                    "[СДЕЛАЙТЕ] Команда reboot отправлена. Дождитесь общего мигания/перезапуска индикаторов и СРАЗУ зажмите Reset. Держите до 2 коротких + 3 длинных красных миганий и постоянного красного света; затем отпустите.",
                    "[ACTION] Reboot command sent. Wait for the router-wide LED blink/restart, then IMMEDIATELY hold Reset. Keep it held through 2 short + 3 long red flashes and steady red, then release.",
                ))
                reboot = "__already_sent__"
            elif unattended:
                reboot = ""
            else:
                prompt = (f"Точный UrsusBoot {TARGET_URSUS} уже находится в mtd0. Нажмите Enter для перезагрузки или N, чтобы остаться в текущей системе: "
                          if already_exact else
                          "mtd0 записан и сверен. Нажмите Enter для перезагрузки или N, чтобы остаться в текущей системе: ")
                reboot = ui.prompt(prompt).strip().lower()
            if reboot in ("n", "no", "нет"):
                _status_line("[ГОТОВО] Перезагрузка пропущена. UrsusBoot уже записан и сверен.")
                return 0

            if reboot != "__already_sent__":
                _status_line("[ШАГ] Перезагружаю Nokia...")
                try:
                    telnet.send_line("sync; reboot")
                    time.sleep(1)
                except Exception:
                    pass
            try:
                telnet.close()
            except Exception:
                pass
            telnet = None
            access.close_web(announce=False)
            access = None
            if unattended and recovery_after:
                # REBOOTWAIT1: ONE-CLICK owns the post-reboot Recovery wait.
                # Do not interpret a still-alive pre-reboot stock HTTP response as
                # evidence that the new boot cycle already completed. Returning here
                # also avoids the old 180 s inner wait + 10 s outer wait split brain.
                result["post_reboot_http_kind"] = "DEFERRED_TO_ONECLICK"
                result["status"] = "WRITE_PASS_RECOVERY_WAIT_DEFERRED"
                _status_line(pb.tr(
                    "[ЖДУ] Перезагрузка началась. ONE-CLICK теперь ждёт именно UrsusBoot Recovery; старый ответ stock Web не считается новой загрузкой.",
                    "[WAIT] Reboot has started. ONE-CLICK now waits specifically for UrsusBoot Recovery; a stale stock Web response is not accepted as a new boot."))
            else:
                _status_line("[ЖДУ] До 3 минут жду ответ роутера после перезагрузки...")
                kind = wait_http_kind(str(result.get("host") or "192.168.1.1"), 180)
                result["post_reboot_http_kind"] = kind
                if kind == "stock_http":
                    _status_line(f"[ИНФО] Загрузилась заводская прошивка Nokia. Запись UrsusBoot {TARGET_URSUS} уже проверена.")
                    result["status"] = "PASS"
                elif kind == "ursus_recovery":
                    _status_line("[ВНИМАНИЕ] Режим восстановления UrsusBoot отвечает, но заводская прошивка Nokia не загрузилась. Загрузчик работает; смотрите UART-лог.")
                    result["status"] = "PERSISTENT_BOOT_RECOVERY_FALLBACK"
                else:
                    _status_line("[ВНИМАНИЕ] За 3 минуты HTTP не ответил. Запись mtd0 уже сверена; проверьте UART.")
                    result["status"] = "WRITE_PASS_REBOOT_UNCONFIRMED"
            result["completed_at"] = stamp()
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return 0
        except Exception as exc:
            result["error"] = str(exc)
            if result.get("status") == "RUNNING":
                result["status"] = "FAIL"
            result["completed_at"] = stamp()
            try:
                result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except Exception:
                pass
            _status_line(f"\n[ОШИБКА] {exc}")
            return 1
        finally:
            sys.stdout = original_stdout
            if telnet:
                telnet.close()
            if access:
                access.close_web(announce=False)


def _materialize_mtd0_backup(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise RuntimeError(f"файл не найден: {path}")
    if path.suffix.lower() == ".gz":
        try:
            raw = zlib.decompress(path.read_bytes(), 16 + zlib.MAX_WBITS)
        except Exception as exc:
            raise RuntimeError(f"не удалось распаковать gzip-копию mtd0: {exc}") from exc
        if len(raw) != MTD0_SIZE:
            raise RuntimeError(f"распакованный mtd0 имеет размер {len(raw)}, ожидалось {MTD0_SIZE}")
        PRIVATE.mkdir(parents=True, exist_ok=True)
        out = PRIVATE / "mtd0-restore-selected.bin"
        out.write_bytes(raw)
        return out
    if path.stat().st_size != MTD0_SIZE:
        if "u-boot" in path.name.lower():
            raise RuntimeError(
                f"{path.name} — это BL33/u-boot.bin ({path.stat().st_size} байт), а не резервная копия mtd0. "
                "Для аварийного восстановления комплектного UrsusBoot используйте " + terms.action_ref("recover_bootloader") + "; "
                + terms.action_ref("restore_nokia") + " принимает только точную копию mtd0 размером 524288 байт."
            )
        raise RuntimeError(f"это не backup mtd0: размер {path.stat().st_size}, требуется ровно {MTD0_SIZE} байт")
    return path


def choose_mtd0_backup() -> Path | None:
    candidates = sorted(PRIVATE.glob("mtd0-before-*.bin"), key=lambda p: p.stat().st_mtime, reverse=True)
    # A complete stock backup stores mtd0 as gzip; accept it too.
    candidates += sorted(FULL_BACKUPS.glob("**/mtd0_*.bin.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        print("Найдены сохранённые копии mtd0:")
        for index, path in enumerate(candidates[:10], 1):
            print(f"  {index}. {path}")
        raw = ui.prompt("Номер копии [1] или путь к другому mtd0: ").strip().strip('\"')
        if not raw:
            return _materialize_mtd0_backup(candidates[0])
        if raw.isdigit() and 1 <= int(raw) <= min(10, len(candidates)):
            return _materialize_mtd0_backup(candidates[int(raw) - 1])
    else:
        _status_line("[ВНИМАНИЕ] В этой распаковке автоматическая копия mtd0 не найдена.")
        print("Если копия осталась в предыдущем каталоге UrsusFlasher, укажите её путь вручную.")
        raw = ui.prompt("Путь к mtd0 (.bin или .bin.gz), Enter — отмена: ").strip().strip('\"')
        if not raw:
            _status_line("[СТОП] Откат mtd0 отменён. На роутере ничего не изменено.")
            return None
    return _materialize_mtd0_backup(Path(raw))


def run_restore() -> int:
    ui.enable()
    backup = choose_mtd0_backup()
    if backup is None:
        return 2
    print(f"Выбранная копия mtd0: {backup}")
    print(f"SHA256: {sha_file(backup)}")
    _status_line("[ВНИМАНИЕ] Этот способ требует загруженной заводской прошивки Nokia и root-доступа по Telnet.")
    access = telnet = None
    try:
        access, telnet = open_root()
        pf = mtd0_write_preflight(telnet)
        remote = "/tmp/ursusboot-restore-mtd0.bin"
        pb.send_file_to_router_tftp(telnet, access.host, backup, remote, port=1069, block_size=4096)
        _status_line("\n[ВНИМАНИЕ] Сейчас сохранённая копия полностью заменит mtd0.")
        print(f"Копия: {backup}")
        answer = ui.prompt("Чтобы продолжить, наберите латиницей RESTORE. Любой другой ввод — отмена.\nПодтверждение: ").strip()
        if answer != "RESTORE":
            _status_line("[СТОП] Восстановление отменено до записи. mtd0 не изменён.")
            return 2
        rc, out = write_image(telnet, remote, pf["writer"])
        if rc:
            raise RuntimeError(f"restore writer returned rc={rc}: {out[-1200:]}")
        got = remote_mtd0_sha(telnet)
        expected = sha_file(backup)
        if got != expected:
            raise RuntimeError(f"restore read-back mismatch: {got} != {expected}")
        _status_line(f"[ГОТОВО] Сохранённый mtd0 восстановлен и считан обратно для сверки: {got}")
        return 0
    finally:
        if telnet:
            telnet.close()
        if access:
            access.close_web(announce=False)


def selftest() -> int:
    hybrid = require_payload()
    check = validate_checksum_entry(hybrid)
    lineage = validate_direct_stock_lineage(hybrid)
    stock_ref = PAYLOAD_DIR / "stock_mtd0_reference.bin"
    if not stock_ref.is_file() or stock_ref.stat().st_size != MTD0_SIZE:
        raise RuntimeError("stock mtd0 reference missing")
    live = stock_ref.read_bytes()
    candidate, meta = build_candidate(live, hybrid)
    if candidate[:FIP_PHYS_OFF] != live[:FIP_PHYS_OFF] or candidate[STOCK_BOOT_ENV_OFF:] != live[STOCK_BOOT_ENV_OFF:]:
        raise RuntimeError("candidate preservation selftest failed")
    uboot = PAYLOAD_DIR / "ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-u-boot.bin"
    if sha_file(uboot) != EXPECTED_U_BOOT_SHA256:
        raise RuntimeError("UrsusBoot u-boot hash mismatch")
    reserves=control_fdt_memreserves(uboot.read_bytes())
    if reserves:
        raise RuntimeError(f"UrsusBoot control DTB memreserve regression: {reserves}")
    manifest = ROOT / "URSUSBOOT_PAYLOAD_SHA256SUMS.txt"
    if manifest.is_file():
        for raw in manifest.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            expected, rel = raw.split(None, 1)
            rel = rel.strip().lstrip("*")
            target = ROOT / rel
            if not target.is_file():
                raise RuntimeError(f"manifest file missing: {rel}")
            got = sha_file(target)
            if got != expected.lower():
                raise RuntimeError(f"manifest SHA256 mismatch for {rel}: {got}")
    # Runtime packages do not vendor an exact HF6 source tree. Do not make the
    # runtime selftest depend on a stale source overlay. The packaged HF6 raw
    # BL33 above is the release artifact and its embedded control DTB is checked
    # directly by control_fdt_memreserves().
    print(f"UrsusBoot {TARGET_URSUS} INSTALLER SELFTEST PASS")
    print(f"  hybrid FIP: {len(hybrid)} bytes {sha_bytes(hybrid)}")
    print(f"  target FIP self-check: off=0x{check['offset']:x} crc32={check['crc32']}")
    print(f"  direct-stock lineage: unchanged_non_bl33_entries={lineage['unchanged_non_bl33_entries']} trusted_boot={lineage['trusted_boot_firmware_sha256']}")
    print(f"  stock reference: {sha_file(stock_ref)}")
    print(f"  deterministic candidate from reference: {meta['candidate_sha256']}")
    print("  preserved: ROM header 0x0..0x7ff, stock boot environment 0x7c000..0x7ffff")
    print("  control DTB memreserve entries: 0")
    print("  stock master/slave are outside mtd0 and never targeted by installer")
    return 0


def pack_results() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in RESULTS.glob("*") if p.is_file())
    if not files:
        print("No UrsusBoot result files yet.")
        return 1
    out = ROOT / f"UrsusBoot-{TARGET_URSUS}-results-{stamp()}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.name)
        # Do not include work/private/*.bin: it contains the user's live bootloader/environment.
        note = (
            "Raw mtd0 backups/candidates are intentionally excluded from result ZIP.\n"
            "They remain under work/private for local restore.\n"
        )
        z.writestr("PRIVATE_FILES_NOT_INCLUDED.txt", note)
    print(out)
    print(sha_file(out))
    return 0


def main() -> int:
    os.environ.setdefault("NOKIA_LANG", "ru")
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--install", action="store_true")
    g.add_argument("--preflight", action="store_true")
    g.add_argument("--restore", action="store_true")
    g.add_argument("--selftest", action="store_true")
    g.add_argument("--pack", action="store_true")
    args = ap.parse_args()
    try:
        if args.install:
            return run_install()
        if args.preflight:
            return run_preflight_only()
        if args.restore:
            return run_restore()
        if args.selftest:
            return selftest()
        if args.pack:
            return pack_results()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 130
    except Exception as exc:
        _status_line(f"[ОШИБКА] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

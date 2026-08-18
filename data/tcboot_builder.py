#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import lzma
import struct
from pathlib import Path

from fit_fdt import SysupgradeInfo

EXPECTED_ORIG = "2cd248f49ec1e73c048b3bfb9886c759c9cbb06f19823993c906500178dffb50"
EXPECTED_BL33 = "3cfbcf379f451665d9b0095e9e3d5f9ca85501145bf82f0b0956a648fe20c6df"
FIP_BASE = 0x800
BL33_TOC = 0x950
BL33_REL = 0x29C00
BL33_OFF = FIP_BASE + BL33_REL
END_TOC = 0x978
HANDLER = 0x77F0C
INSTALL_OFF = 0x8B8F7
INSTALL_CAP = 1832
POST_OFF = 0x8DE8F
POST_CAP = 1438
ALIGN = 0x800
TCBOOT_SIZE = 0x80000


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _req(cond: bool, message: str) -> None:
    if not cond:
        raise ValueError(message)


def make_post_script(info: SysupgradeInfo) -> str:
    # The path is selected from the actual nested DTB by label='ubi'. No RAM
    # address and no byte offset inside the DTB is embedded here.
    path = info.ubi_path
    if any(ch.isspace() for ch in path) or "'" in path or ";" in path:
        raise ValueError(f"unsafe UBI DT path: {path!r}")
    reg = info.uboot_reg_literal
    script = (
        'if test "$um" = 1;then echo U:CAL_BOSA_RESTORE_BEGIN;'
        'ubi write 8e000000 bosa 40000&&ubi read 8e100000 bosa 40000&&cmp.b 8e000000 8e100000 40000&&echo U:CAL_BOSA_RESTORE_OK&&'
        'echo U:CAL_RI_RESTORE_BEGIN&&ubi write 8e040000 ri 40000&&ubi read 8e140000 ri 40000&&cmp.b 8e040000 8e140000 40000&&echo U:CAL_RI_RESTORE_OK;fi&&'
        'echo U:FIT_VOLUME_CREATE_BEGIN;ubi create fit $us dynamic 5&&echo U:FIT_WRITE_BEGIN&&ubi write $ua fit $us&&echo U:FIT_WRITE_DONE&&'
        'echo U:FIT_READBACK_BEGIN&&ubi read 90000000 fit $us&&cmp.b $ua 90000000 $us&&echo U:FIT_READBACK_OK&&'
        'echo U:ROOTFS_DATA_CREATE_BEGIN&&ubi create rootfs_data - dynamic 6&&echo U:VOLUMES_READY&&'
        f'setenv up {path}&&'
        "setenv bootcmd 'echo U:BOOT_OPENWRT_BEGIN;ubi part ubi&&ubi read $loadaddr fit&&iminfo $loadaddr&&"
        'echo U:BOOT_START_BEGIN&&bootm start $loadaddr&&echo U:BOOT_START_OK&&'
        'echo U:LOADOS_BEGIN&&bootm loados&&echo U:LOADOS_OK&&echo U:RAMDISK_BEGIN&&bootm ramdisk&&echo U:RAMDISK_OK&&'
        'echo U:FDT_LOAD_BEGIN&&bootm fdt&&echo U:FDT_LOAD_OK&&echo U:FDT_PATCH_BEGIN&&echo U:FDT_PATH=$up&&'
        f'fdt set $up reg {reg}&&fdt print $up reg&&echo U:FDT_PATCH_OK&&'
        "echo U:PREP_BEGIN&&bootm prep&&echo U:PREP_OK&&echo U:KERNEL_GO&&bootm go'&&"
        'setenv us;setenv ua;echo U:ENV_SAVE_BEGIN&&saveenv&&echo U:ENV_SAVE_OK&&echo U:FLASH_COMPLETE_RESET&&reset'
    )
    if len(script.encode("ascii")) + 1 > POST_CAP:
        raise ValueError(f"personalized post script too large: {len(script)} > {POST_CAP - 1}")
    return script


def build_tcboot(payload_dir: Path, info: SysupgradeInfo, output: Path) -> tuple[Path, str, str]:
    payload_dir = Path(payload_dir)
    original = payload_dir / "tcboot-original.bin"
    install_path = payload_dir / "ursus_install.cmd"
    patch_path = payload_dir / "patch_fw.bin"
    tc = bytearray(original.read_bytes())
    _req(len(tc) == TCBOOT_SIZE, "tcboot-original size")
    _req(_sha(tc) == EXPECTED_ORIG, "tcboot-original SHA256")
    _req(tc[BL33_TOC:BL33_TOC + 16] == bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4"), "BL33 UUID")
    rel, old_size, flags = struct.unpack_from("<QQQ", tc, BL33_TOC + 16)
    _req((rel, old_size, flags) == (BL33_REL, 0x42B42, 0), "BL33 TOC")
    bl = bytearray(lzma.decompress(tc[BL33_OFF:BL33_OFF + old_size], format=lzma.FORMAT_ALONE))
    _req(_sha(bl) == EXPECTED_BL33, "BL33 SHA256")

    install = install_path.read_bytes().rstrip(b"\r\n")
    _req(len(install) + 1 <= INSTALL_CAP, "install script too large")
    _req(bl.find(b"\0", INSTALL_OFF) == INSTALL_OFF + INSTALL_CAP, "install slot changed")
    bl[INSTALL_OFF:INSTALL_OFF + INSTALL_CAP + 1] = install + b"\0" + b"\0" * (INSTALL_CAP - len(install))

    post = make_post_script(info).encode("ascii")
    _req(bl.find(b"\0", POST_OFF) == POST_OFF + POST_CAP, "post slot changed")
    bl[POST_OFF:POST_OFF + POST_CAP + 1] = b"\0" * (POST_CAP + 1)
    bl[POST_OFF:POST_OFF + len(post)] = post
    bl[POST_OFF + len(post)] = 0

    patch = patch_path.read_bytes()
    _req(len(patch) == 48, "handler patch size")
    expected = b"".join(w.to_bytes(4, "little") for w in [0xB0000080, 0x91343800, 0x97FFF12E, 0x910083E0, 0xB0000081, 0x91361821, 0x97FFF100])
    _req(bl[HANDLER:HANDLER + 28] == expected, "handler original bytes")
    bl[HANDLER:HANDLER + 48] = patch

    def fixed(old: bytes, new: bytes) -> None:
        p = bl.find(old + b"\0")
        _req(p >= 0, f"environment string missing: {old!r}")
        _req(len(new) <= len(old), "environment replacement too long")
        bl[p:p + len(old)] = new + b" " * (len(old) - len(new))

    fixed(b"bootargs=ubi.mtd=ubi root=/dev/ubiblock0_1 rootwait", b"bootargs=console=ttyS0,115200 earlycon")
    fixed(
        b'bootcmd=echo "Booting from UBI..." && ubi part ubi && ubi read $loadaddr kernel && echo "Starting kernel..." && bootm $loadaddr',
        b"bootcmd=echo U00_RECOVERY; httpd 192.168.1.1",
    )
    old = b"uboot2.0 version:25.10.01"
    tag = b"UrsusITB FDT p8"
    _req(len(tag) <= len(old) and bl.count(old) >= 4, "HTML version marker")
    bl[:] = bl.replace(old, tag + b" " * (len(old) - len(tag)))
    for old_text, new_text in [
        (b"<title>Firmware update</title>", b"<title>OpenWrt  update</title>"),
        (b"<h1>FIRMWARE UPDATE</h1>", "<h1>🐻 OPENWRT   </h1>".encode("utf-8")),
    ]:
        _req(len(old_text) == len(new_text) and bl.count(old_text) == 1, "HTML fixed marker")
        bl[:] = bl.replace(old_text, new_text)

    def fixed_blob(old_text: bytes, new_text: bytes) -> None:
        _req(len(new_text) <= len(old_text) and bl.count(old_text) >= 1, "HTML text marker")
        bl[:] = bl.replace(old_text, new_text + b" " * (len(old_text) - len(new_text)))

    fixed_blob(b"<h1>UPDATE IN PROGRESS</h1>", "<h1>🐻 UPDATING</h1>".encode("utf-8"))
    fixed_blob(
        b'<div id="f">You can find more information about this project on <a href="https://github.com/pepe2k/u-boot_mod" target="_blank">GitHub</a></div>',
        '<div id="f">🐻 UrsusFlasher WebFailsafe - <a href="https://github.com/pepe2k/u-boot_mod" target="_blank">tcboot/u-boot_mod</a></div>'.encode("utf-8"),
    )
    fixed_blob(b"if everything goes well, the device will restart", b"browser may wait; UART Uxx shows write status")
    fixed_blob(
        b"you can upload whatever you want, so be sure that you choose proper firmware image for your device",
        b"upload only Nokia MD UBI sysupgrade.itb; UART U: markers show every destructive stage",
    )

    filters = [{"id": lzma.FILTER_LZMA1, "dict_size": 0x800000, "lc": 3, "lp": 0, "pb": 2, "mode": lzma.MODE_NORMAL, "nice_len": 64, "mf": lzma.MF_BT4}]
    comp = bytearray(lzma.compress(bytes(bl), format=lzma.FORMAT_ALONE, filters=filters))
    comp[5:13] = len(bl).to_bytes(8, "little")
    new_size = len(comp)
    new_end_rel = (BL33_REL + new_size + ALIGN - 1) & ~(ALIGN - 1)
    _req(FIP_BASE + new_end_rel <= len(tc), "FIP overflow")
    old_end = BL33_OFF + old_size
    _req(all(x == 0 for x in tc[old_end:]), "tcboot tail is not zero")
    tc[BL33_OFF:] = b"\0" * (len(tc) - BL33_OFF)
    tc[BL33_OFF:BL33_OFF + new_size] = comp
    struct.pack_into("<Q", tc, BL33_TOC + 24, new_size)
    struct.pack_into("<Q", tc, END_TOC + 16, new_end_rel)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(tc)
    return output, _sha(tc), _sha(bl)

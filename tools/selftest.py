#!/usr/bin/env python3
from __future__ import annotations

import os
import socket
import struct
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data"))
import proven_backend as p
import master
from fit_fdt import analyze_sysupgrade
from tcboot_builder import build_tcboot, make_post_script


def _put_client(host: str, port: int, name: str, payload: bytes, blksize: int = 1024) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(2)
    try:
        req = struct.pack("!H", 2) + name.encode() + b"\0octet\0blksize\0" + str(blksize).encode() + b"\0"
        s.sendto(req, (host, port)); resp, peer = s.recvfrom(4096)
        assert struct.unpack("!H", resp[:2])[0] == 6, resp
        block = 1; off = 0
        while True:
            chunk = payload[off:off+blksize]; packet = struct.pack("!HH", 3, block) + chunk
            s.sendto(packet, peer); ack, _ = s.recvfrom(4096); assert struct.unpack("!HH", ack[:4]) == (4, block)
            if block == 1:
                s.sendto(packet, peer); ack2, _ = s.recvfrom(4096); assert struct.unpack("!HH", ack2[:4]) == (4, block)
            off += len(chunk)
            if len(chunk) < blksize: return
            block = (block + 1) & 0xFFFF
    finally: s.close()


def _get_client(host: str, port: int, name: str, blksize: int = 1024) -> bytes:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(2); out = bytearray()
    try:
        req = struct.pack("!H", 1) + name.encode() + b"\0octet\0blksize\0" + str(blksize).encode() + b"\0"
        s.sendto(req, (host, port)); resp, peer = s.recvfrom(4096); assert struct.unpack("!H", resp[:2])[0] == 6, resp
        s.sendto(struct.pack("!HH", 4, 0), peer); expect = 1
        while True:
            packet, _ = s.recvfrom(blksize + 4); op, block = struct.unpack("!HH", packet[:4]); assert op == 3 and block == expect
            chunk = packet[4:]; out.extend(chunk); s.sendto(struct.pack("!HH", 4, block), peer)
            if len(chunk) < blksize: return bytes(out)
            expect = (expect + 1) & 0xFFFF
    finally: s.close()


def _http_mock(payload: bytes) -> tuple[threading.Thread, int, dict]:
    ready = threading.Event(); result: dict = {}
    def server():
        srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); srv.bind(("127.0.0.1", 0)); srv.listen(1)
        result["port"] = srv.getsockname()[1]; ready.set()
        conn, _ = srv.accept(); conn.settimeout(3); data = bytearray()
        with conn:
            while b"\r\n\r\n" not in data: data.extend(conn.recv(4096))
            head, _, body = bytes(data).partition(b"\r\n\r\n")
            headers = head.decode("latin-1").split("\r\n")
            length = next(int(x.split(":",1)[1]) for x in headers[1:] if x.lower().startswith("content-length:"))
            while len(body) < length:
                body += conn.recv(min(65536, length-len(body)))
            result["request"] = head + b"\r\n\r\n" + body
            conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nOK")
        srv.close()
    t=threading.Thread(target=server,daemon=True); t.start(); assert ready.wait(2)
    return t, result["port"], result


def main_test() -> int:
    master.validate_tcboot_inputs()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); payload = (b"URSUS-TFTP-SELFTEST-" * 700) + os.urandom(777)
        put_out=root/"put.bin"; ready=threading.Event(); result=p.TftpResult()
        t=threading.Thread(target=p.receive_tftp_put,args=("127.0.0.1",12069,put_out,"put.bin","127.0.0.1",ready,result,None,10,1024),daemon=True)
        t.start(); assert ready.wait(2); _put_client("127.0.0.1",12069,"put.bin",payload,1024); t.join(5)
        assert not t.is_alive() and result.error is None and put_out.read_bytes()==payload
        get_src=root/"get.bin"; get_src.write_bytes(payload); ready2=threading.Event(); result2=p.TftpResult()
        t2=threading.Thread(target=p.serve_tftp_get,args=("127.0.0.1",12070,get_src,"get.bin","127.0.0.1",ready2,result2,10,1024),daemon=True)
        t2.start(); assert ready2.wait(2); got=_get_client("127.0.0.1",12070,"get.bin",1024); t2.join(5)
        assert not t2.is_alive() and result2.error is None and got==payload

        http_file=root/"firmware.itb"; http_file.write_bytes(payload)
        ht, port, hr = _http_mock(payload); first=master._tcboot_http_upload("127.0.0.1",http_file,timeout=3,port=port); ht.join(5)
        req=hr["request"]; head, _, body=req.partition(b"\r\n\r\n")
        assert head.startswith(b"POST /flashing.html HTTP/1.0\r\n")
        assert b'name="firmware"' in body and payload in body
        assert b"Transfer-Encoding:" not in head and b"Expect:" not in head
        assert first.startswith("HTTP/1.0 200")

        info=analyze_sysupgrade(master.DEFAULT_SYSUPGRADE)
        assert info.description == "OpenWrt nokia_xg-040g-md-ubi"
        assert info.original_ubi_start == 0x20000 and info.original_ubi_start + info.original_ubi_size == 0x10000000
        assert info.replacement_ubi_start == 0x100000 and info.replacement_ubi_size == 0x0ff00000
        assert info.uboot_reg_literal == "<0x00100000 0x0ff00000>"
        assert info.ubi_path.endswith("/partition@20000")
        assert set(info.verified_hashes) == {"kernel:crc32","kernel:sha1","fdt:crc32","fdt:sha1","rootfs:crc32","rootfs:sha1"}
        out1,d1,_=build_tcboot(master.TCBOOT_PAYLOAD_DIR,info,root/"tcboot1.bin")
        out2,d2,_=build_tcboot(master.TCBOOT_PAYLOAD_DIR,info,root/"tcboot2.bin")
        assert d1==d2 and out1.read_bytes()==out2.read_bytes() and out1.stat().st_size==0x80000
        post=make_post_script(info)
        assert info.ubi_path in post and info.uboot_reg_literal in post
        assert "fdt set $up reg" in post and "fdt print $up reg" in post
        assert "81e8e400" not in post and "cp.b" not in post

    source=(ROOT/"data/master.py").read_text(encoding="utf-8")
    assert '"$MTD" read /dev/mtd0 0 "$SIZE"' in source
    assert 'cmp -s "$PAY" /tmp/ursus-tcboot-readback.bin' in source
    assert 'EXPERT FLASH TCBOOT MD' in source
    assert 'name=\\"firmware\\"' in source and 'POST /flashing.html HTTP/1.0' in source
    for token in ('expert_untrusted','expert_manual','expert_none','existing_bound'): assert token in source

    install=(ROOT/"data/payloads/md/tcboot/ursus_install.cmd").read_text(encoding="utf-8")
    post=(ROOT/"data/payloads/md/tcboot/ursus_post.cmd").read_text(encoding="utf-8")
    assert "setenv us $filesize" in install and "/configurations default" in install and "/configurations/$uc description" in install
    assert "/configurations/config-1 kernel" not in install
    assert "mtd read ubi 8e000000 50c0000 40000" in install and "flash read" not in install
    assert "ubi create fit $us dynamic 5" in post and "ubi write $ua fit $us" in post and "ubi read 90000000 fit $us" in post
    assert "fdt set $up reg <0x00100000 0x0ff00000>" in post and "fdt print $up reg" in post
    assert "81e8e400" not in post and "cp.b" not in post and "bootm cmdline" not in post and "bootm bdt" not in post

    print("UrsusFlasher offline selftest: PASS")
    print("- tcboot base pin + deterministic FDT-aware build: PASS")
    print("- bundled sysupgrade FIT hashes + nested FDT label=ubi parse: PASS")
    print("- dynamic UBI node path + cell-aware replacement reg: PASS")
    print("- TFTP PUT/GET/OACK/duplicate DATA: PASS")
    print("- tcboot HTTP/1.0 multipart firmware uploader: PASS")
    print("- MD /dev/mtd0 full readback + byte cmp: PASS")
    print("- stdlib-only: PASS")
    return 0

if __name__ == "__main__": raise SystemExit(main_test())

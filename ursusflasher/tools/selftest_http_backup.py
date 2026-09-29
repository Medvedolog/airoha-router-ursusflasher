#!/usr/bin/env python3
"""Host contract for the HTTP streaming NAND backup (UrsusBoot t77+).

A fake router serves the catalog and the streaming endpoint from an in-memory
NAND image and can be told to misbehave: cut the connection mid-body, answer
409 "busy", or -- the fault the firmware's main-loop design exists to prevent --
skip a span while still sending the right number of bytes.
"""
from __future__ import annotations

import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ursusflasher" / "src"))
os.environ.setdefault("NOKIA_LANG", "en")

import ursus_http_backup as hb  # noqa: E402
import ursus_ws_nand as nand  # noqa: E402
from ursus_ws_nand import Geometry, Region  # noqa: E402

ERASE = 0x20000
BLOCKS = 16
SIZE = ERASE * BLOCKS
BAD = (3 * ERASE, 9 * ERASE)
STATUS = {
    "version": "0.1.0-alpha5-t77", "board": "Nokia XG-040G-MD", "soc": "Airoha AN7581",
    "flash_chip": "FM25G02B", "flash_id": "abcd", "flash_size_mib": SIZE >> 20 or 1,
    "flash_erase_size": ERASE, "flash_page_size": 0x800, "bad_blocks": len(BAD),
    "current_layout": "OPENWRT_UBI",
}


def make_image() -> bytes:
    img = bytearray()
    for b in range(BLOCKS):
        off = b * ERASE
        img += (b"\xff" * ERASE) if off in BAD else bytes(((off + i) * 31 + b) & 0xFF for i in range(ERASE))
    return bytes(img)


IMAGE = make_image()


class FakeRouter(http.server.BaseHTTPRequestHandler):
    faults: list[str] = []
    requests: list[tuple[int, int]] = []
    catalog_overrides: dict = {}
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the test output readable
        pass

    def _json(self, status: int, obj: dict) -> None:
        body = (json.dumps(obj) + "\n").encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/api/backup/catalog":
            cat = {"schema": 1, "mtd": [
                {"name": "spi-nand0", "root": "spi-nand0", "offset": 0, "size": SIZE,
                 "erase": ERASE, "page": 0x800, "whole": True},
                {"name": "ursus-ubi-full", "root": "spi-nand0", "offset": 4 * ERASE,
                 "size": 8 * ERASE, "erase": ERASE, "page": 0x800, "whole": False},
            ], "ubi": {"attached": False}}
            cat.update(self.catalog_overrides)
            return self._json(200, cat)
        if not self.path.startswith("/api/backup/mtd/spi-nand0?"):
            return self._json(404, {"result": "REJECTED", "reason": "unknown backup resource"})
        q = dict(p.split("=") for p in self.path.split("?", 1)[1].split("&"))
        off, size = int(q["offset"]), int(q["size"])
        FakeRouter.requests.append((off, size))
        if off % ERASE or size % ERASE or off + size > SIZE:
            return self._json(400, {"result": "REJECTED", "reason": "range must be eraseblock aligned"})
        fault = FakeRouter.faults.pop(0) if FakeRouter.faults else "ok"
        if fault == "busy":
            return self._json(409, {"result": "REJECTED",
                                    "reason": "another backup stream is already running"})
        if fault == "console":
            return self._json(409, {"result": "REJECTED",
                                    "reason": "live WebSocket console owns the control plane; disconnect it first"})
        if fault == "locked":
            return self._json(409, {"result": "REJECTED", "reason": "another operation is active"})
        data = bytearray(IMAGE[off:off + size])
        if fault == "skip":
            # The bug the main-loop design prevents: the right length, but one
            # span skipped and everything after it shifted.
            data = bytearray(IMAGE[off + ERASE:off + size] + IMAGE[off + size - ERASE:off + size])
        self.send_response(200)
        self.send_header("Content-Length", str(size))
        self.send_header("Connection", "close")
        self.end_headers()
        if fault == "cut":
            self.wfile.write(bytes(data[:size // 2 + 777]))   # ends mid-eraseblock
            self.wfile.flush()
            self.connection.close()
            return
        self.wfile.write(bytes(data))


class FakeSession:
    """Stands in for the WebSocket console: `mtd read` into RAM, then `hash`."""

    def __init__(self, host: str):
        self.ram = b""

    def close(self) -> None:
        pass

    def command(self, cmd: str, timeout: float = 60) -> bytes:
        parts = cmd.split()
        if parts[:2] == ["mtd", "read"]:
            off, length = int(parts[4], 16), int(parts[5], 16)
            self.ram = IMAGE[off:off + length]
        return b"UrsusBoot> "

    def sha(self, address: int, size: int) -> str:
        return hashlib.sha256(self.ram[:size]).hexdigest()


def serve():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeRouter)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def expect(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"{exc.__name__} expected from {fn.__name__}")


def geometry() -> Geometry:
    return Geometry("spi-nand0", SIZE, ERASE, 0x800, (Region("ursus-ubi-full", 4 * ERASE, 8 * ERASE),), BAD)


def capability_and_catalog() -> None:
    for ver, want in (("0.1.0-alpha5-t76", False), ("0.1.0-alpha5-t77", True), ("0.1.0-alpha5-t78", True),
                      ("0.1.0-alpha5-t100", True), ("0.1.0-alpha5-t75", False), ("", False)):
        assert hb.available({"version": ver}) is want, ver
    assert hb.available({"version": "0.1.0-alpha5-t70", "http_backup_available": True})
    assert not hb.available({"version": "0.1.0-alpha5-t99", "http_backup_available": False})

    good = {"schema": 1, "mtd": [{"name": "a", "root": "a", "offset": 0, "size": 8, "erase": 4,
                                  "page": 2, "whole": True}], "ubi": {"attached": False}}
    assert hb.parse_catalog(good).devices[0].name == "a"
    for bad in ({"schema": 2, "mtd": []},
                {"schema": 1, "mtd": [{"name": "../x", "root": "a", "offset": 0, "size": 8,
                                        "erase": 4, "page": 2, "whole": True}]},
                {"schema": 1, "mtd": [{"name": "a", "root": "a", "offset": 0, "size": 0,
                                        "erase": 4, "page": 2, "whole": True}]},
                {"schema": 1, "mtd": [{"name": "a"}]}, [], None):
        expect(hb.BackupError, hb.parse_catalog, bad)

    # plan(): one whole device that agrees with UrsusBoot's own status.
    cat = hb.parse_catalog({"schema": 1, "mtd": [
        {"name": "spi-nand0", "root": "spi-nand0", "offset": 0, "size": SIZE, "erase": ERASE,
         "page": 0x800, "whole": True},
        {"name": "ursus-ubi-full", "root": "spi-nand0", "offset": 4 * ERASE, "size": 8 * ERASE,
         "erase": ERASE, "page": 0x800, "whole": False},
        {"name": "ursus-factory-kernel", "root": "ursus-factory-kernel", "offset": 0, "size": 2 * ERASE,
         "erase": ERASE, "page": 0x800, "whole": True}]})
    st = dict(STATUS, flash_size_mib=SIZE >> 20)
    st["flash_size_mib"] = SIZE / (1 << 20)          # 2 MiB in this model
    st["flash_size_mib"] = 2
    master, parts = hb.plan(st, cat)
    assert master.name == "spi-nand0" and parts == (Region("ursus-ubi-full", 4 * ERASE, 8 * ERASE),)
    # A stock layout must not offer the DTS aliases as stock partitions (MF has
    # no proven map); MD gets UrsusBoot's diagnostic map instead.
    stock_mf = dict(st, current_layout="STOCK", soc="Airoha AN7583")
    assert hb.plan(stock_mf, cat)[1] == ()
    stock_md = dict(st, current_layout="STOCK", soc="Airoha AN7581",
                    stock_parts=[["bosa", 0, 2 * ERASE]])
    assert hb.plan(stock_md, cat)[1] == (Region("bosa", 0, 2 * ERASE),)
    expect(hb.BackupError, hb.plan, dict(st, flash_erase_size=ERASE * 2), cat)
    expect(hb.BackupError, hb.plan, dict(st, flash_size_mib=4), cat)


def download_and_resume(port: int) -> None:
    with tempfile.TemporaryDirectory() as d:
        want = hashlib.sha256(IMAGE).hexdigest()

        FakeRouter.faults, FakeRouter.requests = [], []
        p = Path(d) / "clean.partial"
        assert hb.download("127.0.0.1", "spi-nand0", 0, SIZE, ERASE, p, port=port) == want
        assert p.read_bytes() == IMAGE and FakeRouter.requests == [(0, SIZE)]

        # Two cuts inside an eraseblock, a "previous stream" 409 and a "console
        # still closing" 409: the file must still come out byte-identical, and
        # every resume must ask for an eraseblock-aligned range moving forward.
        FakeRouter.faults, FakeRouter.requests = ["cut", "busy", "console", "cut"], []
        p = Path(d) / "faulty.partial"
        assert hb.download("127.0.0.1", "spi-nand0", 0, SIZE, ERASE, p, port=port,
                           sleep=lambda s: None) == want
        assert p.read_bytes() == IMAGE
        offs = [o for o, _ in FakeRouter.requests]
        assert all(o % ERASE == 0 for o in offs) and offs == sorted(offs), offs
        assert offs[0] == 0 and offs[-1] > 0, offs

        # Resume from a leftover file: whole blocks are kept, a torn tail is dropped.
        p = Path(d) / "left.partial"
        p.write_bytes(IMAGE[:5 * ERASE + 999])
        FakeRouter.faults, FakeRouter.requests = [], []
        assert hb.download("127.0.0.1", "spi-nand0", 0, SIZE, ERASE, p, port=port) == want
        assert p.read_bytes() == IMAGE and FakeRouter.requests == [(5 * ERASE, SIZE - 5 * ERASE)]

        # Too many failures give up; a permanent refusal does not retry at all.
        FakeRouter.faults, FakeRouter.requests = ["cut"] * 10, []
        e = expect(hb.BackupError, hb.download, "127.0.0.1", "spi-nand0", 0, SIZE, ERASE,
                   Path(d) / "giveup.partial", port=port, attempts=3, sleep=lambda s: None)
        assert "3 attempts" in str(e) and len(FakeRouter.requests) == 3
        FakeRouter.faults, FakeRouter.requests = ["locked"], []
        expect(hb.BackupError, hb.download, "127.0.0.1", "spi-nand0", 0, SIZE, ERASE,
               Path(d) / "locked.partial", port=port, sleep=lambda s: None)
        assert len(FakeRouter.requests) == 1


def end_to_end(port: int) -> None:
    geo = geometry()
    st = dict(STATUS, flash_size_mib=2)
    with tempfile.TemporaryDirectory() as d, mock.patch.object(nand, "Session", FakeSession):
        FakeRouter.faults, FakeRouter.requests = [], []
        out = Path(d) / "whole.bin"
        hb.backup("127.0.0.1", st, Region("entire-nand", 0, SIZE), out, geo=geo, port=port)
        meta = json.loads(Path(str(out) + ".json").read_text())
        assert out.read_bytes() == IMAGE and meta["sha256"] == hashlib.sha256(IMAGE).hexdigest()
        # The console presets' manifest keys must all still be there, so the
        # existing restore accepts this archive unchanged.
        for key in ("schema", "format", "region", "board", "soc", "flash_chip", "flash_id",
                    "flash_size", "erase_size", "page_size", "bad_blocks", "sha256",
                    "oob", "bad_block_fill", "ursusboot_version"):
            assert key in meta, key
        assert meta["format"] == "ursus-nand-main-area-ecc" and meta["transport"] == "http-stream"
        assert meta["bad_blocks"] == list(BAD) and meta["verify"]["mode"] == "sampled"
        assert not list(Path(d).glob("*.partial*"))

        # A partition is an absolute range on the whole device.
        FakeRouter.requests = []
        part = Path(d) / "part.bin"
        hb.backup("127.0.0.1", st, geo.parts[0], part, geo=geo, verify_all=True, port=port)
        assert part.read_bytes() == IMAGE[4 * ERASE:12 * ERASE]
        assert FakeRouter.requests == [(4 * ERASE, 8 * ERASE)]
        assert json.loads(Path(str(part) + ".json").read_text())["verify"]["mode"] == "full"

        # THE fault: right length, one span skipped.  The direct-read cross-check
        # must catch it, keep the file as .unverified and write no manifest.
        FakeRouter.faults = ["skip"]
        bad = Path(d) / "skipped.bin"
        e = expect(hb.BackupError, hb.backup, "127.0.0.1", st, Region("entire-nand", 0, SIZE),
                   bad, geo=geo, port=port)
        assert "verification failed" in str(e)
        assert not bad.exists() and not Path(str(bad) + ".json").exists()
        assert Path(str(bad) + ".unverified").exists()
        # Over the whole device the shift also moves the bad blocks, so the
        # cheap 0xFF check trips first.  Prove the cross-check on its own, on a
        # region with no bad block in it: only the direct-read comparison can
        # see this one.
        tail = Region("tail", 10 * ERASE, 6 * ERASE)
        tail_geo = Geometry("spi-nand0", SIZE, ERASE, 0x800, (tail,), BAD)
        FakeRouter.faults = ["skip"]
        shifted = Path(d) / "tail.bin"
        e = expect(hb.BackupError, hb.backup, "127.0.0.1", st, tail, shifted, geo=tail_geo, port=port)
        assert "differs from a direct read" in str(e), str(e)
        assert "0xFF" not in str(e)
        FakeRouter.faults = []
        # ...and the same region streamed correctly passes the same check.
        hb.backup("127.0.0.1", st, tail, Path(d) / "tail-ok.bin", geo=tail_geo, port=port)
        assert (Path(d) / "tail-ok.bin").read_bytes() == IMAGE[10 * ERASE:]

        # A bad eraseblock that is not 0xFF in the file is refused even before
        # the cross-check.
        corrupt = Path(d) / "corrupt.bin"
        corrupt.write_bytes(IMAGE[:BAD[0]] + b"\x00" * ERASE + IMAGE[BAD[0] + ERASE:])
        expect(hb.BackupError, hb.check_bad_fill, corrupt, Region("entire-nand", 0, SIZE), geo)

        # A leftover .partial for a different request is never resumed.
        stale = Path(d) / "stale.bin"
        (Path(d) / "stale.bin.partial").write_bytes(b"\x00" * ERASE)
        (Path(d) / "stale.bin.partial.json").write_text(json.dumps({"master": "other"}))
        e = expect(hb.BackupError, hb.backup, "127.0.0.1", st, Region("entire-nand", 0, SIZE),
                   stale, geo=geo, port=port)
        assert "different request" in str(e)
        # An existing archive is never overwritten.
        expect(FileExistsError, hb.backup, "127.0.0.1", st, Region("entire-nand", 0, SIZE),
               out, geo=geo, port=port)

    # Block selection: first, last, seeded spread, never a bad block.
    blocks = hb.choose_blocks(Region("entire-nand", 0, SIZE), geo, 6)
    assert blocks[0] == 0 and blocks[-1] == SIZE - ERASE and not set(blocks) & set(BAD)
    assert blocks == hb.choose_blocks(Region("entire-nand", 0, SIZE), geo, 6)
    assert len(hb.choose_blocks(Region("entire-nand", 0, SIZE), geo, None)) == BLOCKS - len(BAD)


def discover_flow() -> None:
    cat = {"schema": 1, "mtd": [{"name": "spi-nand0", "root": "spi-nand0", "offset": 0, "size": SIZE,
                                 "erase": ERASE, "page": 0x800, "whole": True}], "ubi": {"attached": False}}
    st = dict(STATUS, flash_size_mib=2)
    with mock.patch.object(hb, "fetch_catalog", lambda host, **kw: hb.parse_catalog(cat)), \
            mock.patch.object(nand, "Session", FakeSession), \
            mock.patch.object(nand, "_current_bad", lambda s, m: BAD):
        master, geo = hb.discover("127.0.0.1", st)
        assert geo.bad == BAD and geo.master == "spi-nand0"
        # Refusals happen before anything is downloaded.
        expect(hb.BackupError, hb.discover, "127.0.0.1", dict(st, version="0.1.0-alpha5-t76"))
        expect(hb.BackupError, hb.discover, "127.0.0.1", dict(st, board="Some Other Router"))
        expect(hb.BackupError, hb.discover, "127.0.0.1", dict(st, operation_active=True))
        expect(hb.BackupError, hb.discover, "127.0.0.1", dict(st, bad_blocks=5))


def main() -> int:
    capability_and_catalog()
    server, port = serve()
    try:
        download_and_resume(port)
        end_to_end(port)
    finally:
        server.shutdown()
    discover_flow()
    print("URSUS_HTTP_BACKUP_SELFTEST=PASS catalog=1 resume=1 cross_check_catches_skip=1 "
          "stale_partial_refused=1 restore_manifest_compatible=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

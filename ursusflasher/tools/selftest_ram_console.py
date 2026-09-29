#!/usr/bin/env python3
"""BootROM -> current UrsusBoot in RAM -> live console over LAN.

A fake serial port and fake BootROM/U-Boot steps: checks the order of the steps,
that the chosen RAM loader is the one sent, that `ursusweb` is started and its
readiness awaited, that no NAND-writing command is ever sent, and that the LAN
console opens only after HTTP answers.
"""
from __future__ import annotations

import builtins
import contextlib
import io
import os
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ursusflasher" / "src"))
os.environ.setdefault("NOKIA_LANG", "en")

import proven_backend as proven  # noqa: E402
import ursus_ram_console as rc  # noqa: E402
import ursusboot_update as uu  # noqa: E402

ALPHA3 = ROOT / "payloads" / "md" / "ursusboot" / "ursusboot-md-0.1.0-alpha3-update.fip"
TEST61 = ROOT / "payloads" / "md" / "ursusboot" / "ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip"


class FakeSerial:
    def __init__(self, port, script=(b"...", b"URSUS_HTTP_LISTEN_OK port=80\nURSUS_WEBFAILSAFE_READY\n")):
        self.port = port
        self.rx = list(script)
        self.tx = []
        self.closed = False

    def read(self, size=4096, timeout=0.2):
        return self.rx.pop(0) if self.rx else b""

    def write(self, data):
        self.tx.append(bytes(data))

    def reset_input(self):
        pass

    def close(self):
        self.closed = True


def run(steps, *answers, serial_script=None, http_ok=True, prompt="prompt"):
    answers = list(answers)
    sent_files, lines, ports = [], [], []
    opened = []

    def make_serial(port):
        sp = FakeSerial(port, serial_script) if serial_script is not None else FakeSerial(port)
        opened.append(sp)
        return sp

    def fake_send(sp, path, label, log):
        sent_files.append(Path(path))
        steps.append("xmodem:" + Path(path).name)

    patches = [
        mock.patch.object(builtins, "input", lambda p="": answers.pop(0)),
        mock.patch.object(uu, "choose_port", lambda: ports.append(1) or "COM9"),
        mock.patch.object(proven, "probe_serial_port", lambda port: None),
        mock.patch.object(proven, "RecoverySerial", make_serial),
        mock.patch.object(proven, "wait_bootrom_xmodem", lambda sp, log, phase, **kw: steps.append("bootrom")),
        mock.patch.object(proven, "xmodem_send", fake_send),
        mock.patch.object(proven, "wait_uboot_prompt", lambda sp, log: steps.append("prompt") or prompt),
        mock.patch.object(proven, "_uboot_wait_quiet", lambda *a, **k: None),
        mock.patch.object(proven, "_uboot_send_line", lambda sp, line: lines.append(line) or steps.append("line:" + line)),
        mock.patch.object(rc, "_wait_http", (lambda host, timeout=45.0: steps.append("http:" + host)) if http_ok
                          else (lambda host, timeout=45.0: (_ for _ in ()).throw(proven.Error("no http")))),
    ]
    import ursus_web_client as uw
    patches.append(mock.patch.object(uw, "live_console", lambda host: steps.append("console:" + host)))
    out = io.StringIO()
    with contextlib.ExitStack() as stack, contextlib.redirect_stdout(out):
        for p in patches:
            stack.enter_context(p)
        try:
            rc.boot_to_lan("md", host="192.168.1.1")
            err = None
        except Exception as exc:  # noqa: BLE001
            err = exc
    return err, out.getvalue(), sent_files, lines, opened


def main() -> int:
    bundled = rc._loaders("md")[2]
    assert bundled, "the kit's current MD FIP must be offered as the RAM loader"

    # 1. default: bundled loader -> BootROM -> prompt -> ursusweb -> HTTP -> LAN console
    steps: list[str] = []
    err, out, files, lines, opened = run(steps, "")
    assert err is None, err
    assert files[1] == bundled[0].path and files[0].name.endswith("preloader.bin"), files
    assert lines == ["ursusweb"], lines
    assert steps[-3:] == ["line:ursusweb", "http:192.168.1.1", "console:192.168.1.1"], steps
    assert steps.index("prompt") < steps.index("line:ursusweb")
    assert opened and all(sp.closed for sp in opened), "the UART is released before the LAN console"
    forbidden = ("mtd erase", "mtd write", "ubi write", "ubi remove", "ubi create", "saveenv", "ursusupdate")
    assert not any(any(f in l for f in forbidden) for l in lines), lines

    # 2. a custom RAM loader is allowed behind the typed acceptance, and is what gets sent
    steps = []
    err, out, files, lines, _ = run(steps, "2", str(TEST61), "CUSTOM FIP")
    assert err is None and files[1] == TEST61.resolve(), (err, files)
    # an older loader is warned about (no WebSocket console before T77)
    steps = []
    err, out, files, lines, _ = run(steps, "2", str(ALPHA3), "CUSTOM FIP")
    assert "T77" in out, out
    assert files[1] == ALPHA3.resolve(), files

    # 3. cancel before the port is even opened
    steps = []
    err, out, files, lines, opened = run(steps, "q")
    assert err is None and not files and not opened and not steps, steps

    # 4. no prompt (a normal boot started): stop, no ursusweb, no console
    steps = []
    err, out, files, lines, opened = run(steps, "", prompt="production")
    assert isinstance(err, proven.Error) and not lines and not any(s.startswith("console") for s in steps)
    assert all(sp.closed for sp in opened)

    # 5. ursusweb missing / never ready: a clear error, no console
    steps = []
    err, *_ = run(steps, "", serial_script=[b"Unknown command 'ursusweb' - try 'help'\n"])
    assert isinstance(err, proven.Error) and not any(s.startswith("console") for s in steps)
    with mock.patch.object(rc.time, "monotonic", side_effect=[0.0] + [1000.0] * 50):
        steps = []
        err, *_ = run(steps, "", serial_script=[])
    assert isinstance(err, proven.Error) and not any(s.startswith("console") for s in steps), err
    # output that is not the readiness marker does not count as ready
    with mock.patch.object(rc.time, "monotonic", side_effect=[0.0, 1.0, 1000.0] + [1000.0] * 50):
        steps = []
        err, *_ = run(steps, "", serial_script=[b"URSUS_WEB_BEGIN\n", b"eth0: up\n"])
    assert isinstance(err, proven.Error) and not any(s.startswith("console") for s in steps), err

    # 6. HTTP never answers: no console is opened on a dead link
    steps = []
    err, *_ = run(steps, "", http_ok=False)
    assert isinstance(err, proven.Error) and not any(s.startswith("console") for s in steps)

    # 7. a tampered UART preloader is refused before anything is sent
    with mock.patch.object(rc.ubr, "sha256", lambda path: "0" * 64):
        steps = []
        err, out, files, lines, opened = run(steps)
    assert isinstance(err, proven.Error) and not files and not opened

    print(f"RAM_CONSOLE_QA=PASS (NOKIA_LANG={os.environ.get('NOKIA_LANG')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

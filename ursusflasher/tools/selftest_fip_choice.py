#!/usr/bin/env python3
"""Host contract for "which UrsusBoot will be written, and can I pick my own".

Covers the FIP identifier, the chooser, and every write path that now uses it:
the network update, the BootROM emergency recovery (alpha3 stays the default;
another FIP leaves BL2 alone unless asked) and the boot-area restore.  No
device, no serial port: U-Boot commands are recorded, not sent.
"""
from __future__ import annotations

import builtins
import contextlib
import hashlib
import io
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ursusflasher" / "src"))
os.environ.setdefault("NOKIA_LANG", "en")

import fip_choice as fc  # noqa: E402
import uart_bootarea_restore as ubr  # noqa: E402
import ursusboot_update as uu  # noqa: E402

PAYLOADS = ROOT / "payloads" / "md" / "ursusboot"
ALPHA3 = PAYLOADS / "ursusboot-md-0.1.0-alpha3-update.fip"
TEST61 = PAYLOADS / "ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip"
ALPHA3_SHA = "597071e178470bfda23aab9738ad7ddb0b25e9b21ef336fd3eceb39c39f983ce"
EN = os.environ.get("NOKIA_LANG") == "en"


class Script:
    """Scripted operator: answers ``input()`` in order and fails on an unexpected extra question."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.asked: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.asked.append(prompt)
        assert self.answers, f"unexpected prompt: {prompt!r}"
        return self.answers.pop(0)


def run(fn, *answers: str):
    script = Script(*answers)
    out = io.StringIO()
    with mock.patch.object(builtins, "input", script), contextlib.redirect_stdout(out):
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - the tests inspect it
            result = exc
    return result, out.getvalue(), script


def custom_fip(tmp: Path, name: str = "mine.fip", *, byte: int = 0x1000) -> Path:
    """A structurally valid FIP that is not one the project knows: one byte of another component changed."""
    data = bytearray(TEST61.read_bytes())
    data[byte] ^= 0xFF
    path = tmp / name
    path.write_bytes(bytes(data))
    return path


def test_identify() -> None:
    a3 = fc.identify(ALPHA3.read_bytes(), known={ALPHA3_SHA: "pinned"})
    assert a3.ok and a3.version == "0.1.0-alpha3" and a3.label == "pinned", (a3.version, a3.problems)
    assert a3.sha256 == ALPHA3_SHA and a3.size == 503808 and a3.bl33_size == 742240
    t61 = fc.identify(TEST61.read_bytes())
    assert t61.ok and t61.version == "0.1.0-alpha5-UBIUX1-TEST61" and t61.label is None
    assert fc.identify(TEST61.read_bytes(), known={t61.crc32: "by crc"}).label == "by crc"

    good = ALPHA3.read_bytes()
    bad_cases = {
        "empty": b"",
        "not a fip": b"\x00" * 0x20000,
        "wrong serial": good[:4] + b"\x00\x00\x00\x00" + good[8:],
        "wrong magic": b"\x00\x00\x00\x00" + good[4:],
        "truncated": good[:0x30000],
        "trailing junk": good + b"\x00" * 16,
    }
    for label, blob in bad_cases.items():
        info = fc.identify(blob)
        assert not info.ok and info.problems, label

    lzma_hdr = bytearray(good)
    lzma_hdr[a3.nt_offset] = 0x5D                       # wrong LZMA properties byte
    assert not fc.identify(bytes(lzma_hdr)).ok
    corrupt = bytearray(good)
    corrupt[a3.nt_offset + 40] ^= 0xFF                  # inside the compressed BL33
    info = fc.identify(bytes(corrupt))
    assert not info.ok and info.version is None
    assert not fc.identify(good, window=0x1000).ok      # does not fit the boot-area window
    assert fc.identify(good, expect_nt_offset=0x12345).problems       # MD placement is enforced ...
    assert fc.identify(good, expect_nt_offset=None).ok                # ... and skippable for MF

    rej = fc.identify(good, rejected=[ALPHA3_SHA])
    assert rej.rejected and not rej.ok

    # a slice out of a boot-area image: the hash is of the FIP alone, not of what follows it
    sliced = fc.identify(good + b"\xff" * 4096, exact_end=False)
    assert sliced.ok and sliced.sha256 == ALPHA3_SHA and sliced.size == len(good)


def test_choose_default_and_menu() -> None:
    opt = fc.Option("bundled", "комплектный", "bundled", path=TEST61)
    choice, out, script = run(lambda: fc.choose([opt]), "")
    assert isinstance(choice, fc.Choice) and choice.kind == "bundled" and choice.path == TEST61
    assert "0.1.0-alpha5-UBIUX1-TEST61" in out and choice.info.sha256 in out, out
    assert "SHA256" in out and ("size" in out if EN else "размер" in out)

    # garbage, out-of-range and zero are re-asked, never guessed
    choice, _, script = run(lambda: fc.choose([opt]), "abc", "0", "9", "1")
    assert choice.kind == "bundled" and len(script.asked) == 4

    result, _, _ = run(lambda: fc.choose([opt]), "q")
    assert isinstance(result, fc.Cancelled), result

    # a listed option that fails validation is refused, not written
    bad = fc.Option("bundled", "x", "x", path=ALPHA3)
    result, out, script = run(lambda: fc.choose([bad], rejected=[ALPHA3_SHA]), "1", "q")
    assert isinstance(result, fc.Cancelled), result
    assert ("will not be written" if EN else "не будет записан") in out

    # advisory options (built by the project itself): problems shown, the device still gates
    with tempfile.TemporaryDirectory() as td:
        broken = Path(td) / "derived.fip"
        broken.write_bytes(b"\x00" * 0x20000)
        adv = fc.Option("derived", "d", "d", path=broken, advisory=True)
        choice, out, _ = run(lambda: fc.choose([adv]), "1")
        assert choice.kind == "derived" and "PROBLEM" in out.upper() or "ПРОБЛЕМА" in out
        # ... but the project's own reject list is never advisory
        adv2 = fc.Option("derived", "d", "d", path=ALPHA3, advisory=True)
        result, _, _ = run(lambda: fc.choose([adv2], rejected=[ALPHA3_SHA]), "1", "q")
        assert isinstance(result, fc.Cancelled), result

    # a factory (device-derived file) runs only when its option is chosen
    with tempfile.TemporaryDirectory() as td:
        made = custom_fip(Path(td), "derived.fip")
        calls = []
        fac = fc.Option("derived", "d", "d", factory=lambda: (calls.append(1), made)[1], advisory=True)
        result, _, _ = run(lambda: fc.choose([fac]), "q")
        assert isinstance(result, fc.Cancelled) and not calls
        choice, _, _ = run(lambda: fc.choose([fac]), "1")
        assert calls == [1] and choice.path == made


def test_choose_custom() -> None:
    opt = fc.Option("bundled", "b", "b", path=TEST61)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        mine = custom_fip(tmp)
        junk = tmp / "junk.fip"
        junk.write_bytes(b"not a fip" * 100)

        # the typed acceptance is the only way in
        choice, out, _ = run(lambda: fc.choose([opt]), "2", str(mine), fc.CUSTOM_TOKEN)
        assert choice.custom and choice.path == mine.resolve() and choice.kind == "custom"
        assert "own risk" in out.lower() or "риск" in out.lower()
        assert "known builds" in out or "известных сборок" in out
        for wrong in ("y", "yes", "да", "custom fip", "CUSTOM", ""):
            result, _, script = run(lambda: fc.choose([opt]), "2", str(mine), wrong, "q")
            assert isinstance(result, fc.Cancelled), (wrong, result)

        # a missing file, a directory and a non-FIP are refused before any acceptance is asked
        for target in (tmp / "nope.fip", tmp, junk):
            result, out, script = run(lambda: fc.choose([opt]), "2", str(target), "q")
            assert isinstance(result, fc.Cancelled), (target, result)
            assert not any(fc.CUSTOM_TOKEN in p for p in script.asked[2:]), script.asked

        # empty path goes back to the menu
        choice, _, _ = run(lambda: fc.choose([opt]), "2", "", "1")
        assert choice.kind == "bundled"

        # the reject list applies to custom files too
        result, out, _ = run(lambda: fc.choose([opt], rejected=[fc.identify_file(mine).sha256]), "2", str(mine), "q")
        assert isinstance(result, fc.Cancelled) and ("REJECT" in out.upper() or "ЧЁРНОМ" in out)

        # no bundled option at all: the only entry is the custom one
        choice, _, _ = run(lambda: fc.choose([]), "1", str(mine), fc.CUSTOM_TOKEN)
        assert choice.custom
        # ... and it can be switched off
        result, _, _ = run(lambda: fc.choose([opt], allow_custom=False), "2", "1")
        assert result.kind == "bundled"


def test_summary_marks_custom() -> None:
    with tempfile.TemporaryDirectory() as td:
        mine = custom_fip(Path(td))
        info = fc.identify_file(mine)
        text = "\n".join(fc.summary_lines(fc.Choice("custom", mine, info), installed="UrsusBoot 0.1.0-alpha3"))
        assert info.sha256 in text and "0.1.0-alpha3" in text and "0.1.0-alpha5-UBIUX1-TEST61" in text
        assert ("CUSTOM" in text) or ("СВОЙ" in text)
        plain = "\n".join(fc.summary_lines(fc.Choice("bundled", TEST61, fc.identify_file(TEST61))))
        assert "CUSTOM" not in plain and "СВОЙ" not in plain


def test_web_update() -> None:
    """The network update shows what it writes and passes exactly that file on."""
    sent: list[Path] = []

    def fake_update(host, fip, confirm=True):
        sent.append(Path(fip))
        return {"current_layout": "OPENWRT_UBI"}

    patches = (
        mock.patch.object(uu.uw, "update_bootloader", fake_update),
        mock.patch.object(uu.uw, "status", lambda host: {"version": "0.1.0-alpha3"}),
        mock.patch.object(uu, "require_fip_payload", lambda: None),
    )
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)

        _, out, _ = run(uu.web_fip_update, "", "")                    # Enter, Enter: the bundled release
        assert sent == [uu.PRODUCTION_PAYLOAD], sent
        assert "0.1.0-alpha3" in out and fc.identify_file(uu.PRODUCTION_PAYLOAD).sha256 in out

        sent.clear()
        with tempfile.TemporaryDirectory() as td:
            mine = custom_fip(Path(td))
            _, out, _ = run(uu.web_fip_update, "", "2", str(mine), fc.CUSTOM_TOKEN)
            assert sent == [mine.resolve()], sent
            assert fc.identify_file(mine).sha256 in out

            sent.clear()                                              # risk not accepted -> nothing is sent
            run(uu.web_fip_update, "", "2", str(mine), "no", "q")
            assert not sent

        sent.clear()
        _, out, _ = run(uu.web_fip_update, "", "q")                   # backing out before the upload
        assert not sent and ("Cancelled" in out or "Отменено" in out)


def test_web_update_without_bundle() -> None:
    """A broken/missing bundled FIP no longer blocks a custom one, and is never offered."""
    sent: list[Path] = []

    def broken():
        raise uu.Error("bundled FIP missing")

    with tempfile.TemporaryDirectory() as td, \
            mock.patch.object(uu, "require_fip_payload", broken), \
            mock.patch.object(uu.uw, "status", lambda host: {}), \
            mock.patch.object(uu.uw, "update_bootloader", lambda h, f, confirm=True: sent.append(Path(f)) or {}):
        mine = custom_fip(Path(td))
        _, out, _ = run(uu.web_fip_update, "", "1", str(mine), fc.CUSTOM_TOKEN)
        assert sent == [mine.resolve()]
        assert "bundled FIP missing" in out


class FakeSerial:
    pass


def _record_transaction(choice, write_bl2, *, confirm="RECOVER URSUSBOOT"):
    """Run the emergency transaction with U-Boot commands recorded instead of sent."""
    cmds: list[str] = []
    view = {"ubi_target": "ubi0", "bl2_target": "bl2mtd", "bl2_offset": 0}
    meta = {"fip_sha256": (choice.info.sha256 if choice else ALPHA3_SHA), "fip_size": 503808}
    with mock.patch.object(uu, "_uboot_command_no_rc", lambda sp, log, c, timeout=30: cmds.append(c) or b""), \
            mock.patch.object(uu, "_uboot_require_ok", lambda sp, log, c, t, label: cmds.append(c) or b""):
        result, out, _ = run(lambda: uu.emergency_ursusboot_transaction(
            FakeSerial(), None, meta, view, choice=choice, write_bl2=write_bl2), confirm, "")
    return result, cmds, out


def test_emergency_transaction() -> None:
    has_bl2 = lambda cmds: any(c.startswith("mtd erase") or c.startswith("mtd write") for c in cmds)  # noqa: E731

    # default (no choice): the historical alpha3 FIP + BL2 pair, byte for byte the same commands
    result, cmds, out = _record_transaction(None, True)
    assert result == "UBI_ID4_PLUS_BL2", result
    assert "ubi create fip 0x100000 static 4" in cmds and has_bl2(cmds)
    assert cmds.index("ubi create fip 0x100000 static 4") < next(i for i, c in enumerate(cmds) if c.startswith("mtd erase"))
    assert "alpha3" in out

    # a chosen FIP without BL2: the FIP is written and verified, BL2 is never touched
    with tempfile.TemporaryDirectory() as td:
        mine = custom_fip(Path(td))
        choice = fc.Choice("custom", mine, fc.identify_file(mine))
        result, cmds, out = _record_transaction(choice, False)
        assert result == "UBI_ID4_ONLY", result
        assert any(c.startswith("ubi write") for c in cmds) and any(c.startswith("cmp.b") for c in cmds)
        assert not has_bl2(cmds) and not any(c.startswith("mtd ") for c in cmds), cmds
        assert choice.info.sha256 in out and "0.1.0-alpha5-UBIUX1-TEST61" in out
        assert "CUSTOM" in out.upper() or "СВОЙ" in out.upper()

        # ... and the same choice with BL2 asked for writes the pair
        result, cmds, _ = _record_transaction(choice, True)
        assert result == "UBI_ID4_PLUS_BL2" and has_bl2(cmds)

        # the typed confirmation still gates everything
        for wrong in ("", "y", "recover ursusboot"):
            result, cmds, _ = _record_transaction(choice, False, confirm=wrong)
            assert result == "CANCELLED" and not cmds, (wrong, cmds)


def test_emergency_choice() -> None:
    # Source trees intentionally do not vendor the pinned production FIP; the public-kit\n    # builder injects it via URSUSBOOT_RELEASE.json.  Use an existing valid FIP here so\n    # this unit test exercises chooser/BL2 semantics rather than artifact packaging.\n    with mock.patch.object(uu, "require_fip_payload", lambda: None), \\\n            mock.patch.object(uu, "PRODUCTION_PAYLOAD", TEST61):
        (choice, write_bl2), out, script = run(uu._choose_emergency_fip, "")
        assert choice.kind == "pinned" and write_bl2 is True and choice.info.sha256 == ALPHA3_SHA
        assert len(script.asked) == 1                                  # Enter: no extra questions on the default path
        assert "alpha3" in out and "BL2" in out
        assert ("RAM" in out)                                          # explains alpha3 in RAM is only the helper

        # the bundled release is offered as option 2, and asks about BL2 (default: leave it)
        (choice, write_bl2), out, script = run(uu._choose_emergency_fip, "2", "")
        assert choice.kind == "bundled" and write_bl2 is False and choice.path == uu.PRODUCTION_PAYLOAD
        (choice, write_bl2), _, _ = run(uu._choose_emergency_fip, "2", "y")
        assert write_bl2 is True

        with tempfile.TemporaryDirectory() as td:
            mine = custom_fip(Path(td))
            (choice, write_bl2), out, _ = run(uu._choose_emergency_fip, "3", str(mine), fc.CUSTOM_TOKEN, "n")
            assert choice.custom and write_bl2 is False and choice.path == mine.resolve()
            assert "not modified" in out or "не изменяется" in out

            # the bytes written are the bytes shown: a file swapped after the choice is refused
            meta, _path = uu._emergency_meta_for(choice)
            assert meta["fip_sha256"] == choice.info.sha256 and meta["fip_size"] == 503808
            mine.write_bytes(custom_fip(Path(td), "other.fip", byte=0x2000).read_bytes())
            try:
                uu._emergency_meta_for(choice)
            except uu.Error as exc:
                assert "changed" in str(exc) or "изменился" in str(exc)
            else:
                raise AssertionError("a swapped FIP must be refused")

    # pinned goes through the exact-file validation, never through the custom path
    meta, path = uu._emergency_meta_for(None)
    assert path == uu.PAYLOAD and meta["fip_sha256"] == ALPHA3_SHA
    meta, path = uu._emergency_meta_for(fc.Choice("pinned", ALPHA3, fc.identify_file(ALPHA3)))
    assert path == uu.PAYLOAD


def test_emergency_flow_wiring() -> None:
    import inspect
    flow = inspect.getsource(uu._uart_bootrom_flow)
    # the operator picks before any BootROM step, and the pick is what gets loaded and written
    assert flow.index("_choose_emergency_fip") < flow.index("choose_port")
    assert "load_fip_xmodem_emergency(sp, log, choice)" in flow
    assert "emergency_ursusboot_transaction(sp, log, meta, view, choice=choice, write_bl2=write_bl2)" in flow
    assert flow.index("if write_bl2:") < flow.index("load_bl2_xmodem_emergency(sp, log)")
    assert flow.index("capture_bootchain_forensics") < flow.index("load_fip_xmodem_emergency")
    trans = inspect.getsource(uu.emergency_ursusboot_transaction)
    for required in ("ubi create fip 0x100000 static 4", "ubi write 0x{LOADADDR:x} fip", "cmp.b 0x{LOADADDR:x} 0x{READBACK_ADDR:x}",
                     "mtd erase {bl2_target}", "mtd write {bl2_target}", "mtd read {bl2_target}",
                     "cmp.b 0x{BL2_ADDR:x} 0x{READBACK_ADDR:x}", "ubi part {ubi_target}"):
        assert required in trans, required
    for forbidden in ("ursusupdate write", "fip.new->atomic", "HF6", "f'hash sha256", "'ubi part ubi'"):
        assert forbidden not in trans, forbidden
    # the RAM helper is alpha3 whatever the operator picked
    assert "require_emergency_payloads()" in flow


def test_uart_update_paths() -> None:
    import inspect
    for fn in (uu.web_fip_update, uu.tftp_update_automated, uu.tftp_server_manual, uu.uart_update_installed):
        src = inspect.getsource(fn)
        assert "_choose_update_fip(" in src and "fc.Cancelled" in src, fn.__name__
    src = inspect.getsource(uu.uart_update_installed)
    assert src.count("payload=choice.path") == 2 and src.count("commit_uart(sp, log, choice.path)") == 2
    # the loaders write the chosen file, not the module constant
    assert "xmodem_send(sp, payload," in inspect.getsource(uu.load_fip_xmodem)
    assert "PRODUCTION_PAYLOAD" in inspect.getsource(uu.web_fip_update)
    assert "PRODUCTION_PAYLOAD" in inspect.getsource(uu.tftp_update_automated)


def test_boot_area_restore_reports_fip() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        fip = ALPHA3.read_bytes()
        image = tmp / "mtd0.bin"
        image.write_bytes(bytes(0x800) + fip + bytes(ubr.BOOT_AREA_SIZE - 0x800 - len(fip)))
        meta = ubr.validate_image(image)
        assert meta["fip_magic"] and meta["fip"].version == "0.1.0-alpha3"
        assert meta["fip"].sha256 == ALPHA3_SHA, "the FIP hash must not include what follows the FIP"
        assert meta["sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ubr._print_fip_inside(meta)
        assert "0.1.0-alpha3" in out.getvalue() and ALPHA3_SHA in out.getvalue()

        # restore() itself announces the FIP before it touches the serial port
        class Stop(Exception):
            pass

        def stop(*a, **k):
            raise Stop()

        out = io.StringIO()
        with mock.patch.object(ubr, "boot_ram", stop), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                ubr.restore("md", image)
            except Stop:
                pass
        text = out.getvalue()
        assert "0.1.0-alpha3" in text and ALPHA3_SHA in text, text

        # an image without a FIP is still restorable (raw recovery): nothing is claimed about it
        blank = tmp / "blank.bin"
        blank.write_bytes(b"\xff" * ubr.BOOT_AREA_SIZE)
        meta = ubr.validate_image(blank)
        assert meta["fip"] is None and not meta["fip_magic"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ubr._print_fip_inside(meta)
        assert out.getvalue() == ""


def test_md_uart_routing() -> None:
    """Item 2 over UART reaches the running UrsusBoot updater, not only BootROM recovery."""
    import bootloader_install_menu as bim

    calls: list[str] = []
    with mock.patch.object(bim.ursusboot_update, "uart_update_installed", lambda: calls.append("installed")), \
            mock.patch.object(bim.ursusboot_update, "uart_bootrom_recover", lambda: calls.append("bootrom")):
        for answer, want in (("1", ["installed"]), ("2", ["bootrom"]), ("0", [])):
            calls.clear()
            _, out, _ = run(lambda: bim._run_uart("md", None), answer)
            assert calls == want, (answer, calls)
        # garbage is re-asked, never routed
        calls.clear()
        run(lambda: bim._run_uart("md", None), "x", "", "1")
        assert calls == ["installed"], calls
        _, out, _ = run(lambda: bim._run_uart("md", None), "0")
        assert "BootROM" in out and ("already running" in out or "уже запущенный" in out), out
    # the updater itself asks which FIP before it opens the port
    import inspect
    src = inspect.getsource(uu.uart_update_installed)
    assert src.index("_choose_update_fip(") < src.index("choose_port()")


def test_known_table() -> None:
    known = uu._known_fips()
    assert known.get(ALPHA3_SHA), "the pinned alpha3 must be named"
    assert "82263464" in known and "b1b313a5" in known
    assert isinstance(uu._rejected_fips(), set)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"FIP_CHOICE_QA=PASS ({len(tests)} tests, NOKIA_LANG={os.environ.get('NOKIA_LANG')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

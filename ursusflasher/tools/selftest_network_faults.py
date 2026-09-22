#!/usr/bin/env python3
"""Selftest: ursus_web_client.upload() against a fake UrsusBoot API with injected link faults,
plus Telnet EOF detection. No router needed."""
import http.client, http.server, json, os, sys, tempfile, threading, hashlib, socket, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
os.environ['NOKIA_LANG'] = 'en'
import ursus_web_client as uw
uw.UPLOAD_RECONNECT_GRACE = 6.0

class State:
    gen = ''; total = 0; buf = bytearray(); faults = []; chunk_posts = 0
S = State()

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj=None, raw=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == '/api/status':
            return self._send(200, {'product': 'UrsusBoot', 'ubi_preloader_generation': S.gen, 'ubi_preloader_upload_received': len(S.buf),
                                    'ubi_preloader_upload_total': S.total, 'ubi_preloader_valid': True, 'ubi_bl2_candidate_valid': True})
        self._send(404, {})
    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0); data = self.rfile.read(n) if n else b''
        if self.path.endswith('-begin'):
            S.gen = self.headers['X-Ursus-Generation']; S.total = int(self.headers['X-Ursus-Total']); S.buf = bytearray()
            return self._send(200, {'generation': S.gen, 'declared_size': S.total, 'received': 0})
        S.chunk_posts += 1
        fault = S.faults.pop(0) if S.faults else None
        off = int(self.headers['X-Ursus-Offset'])
        if fault == 'drop-before-commit':
            self.close_connection = True; self.connection.shutdown(2); return
        if off == len(S.buf):
            S.buf += data
        if fault == 'drop-after-commit':
            self.close_connection = True; self.connection.shutdown(2); return
        if fault == '503':
            return self._send(503, {'reason': 'busy'})
        if fault == 'badjson':
            return self._send(200, raw=b'{"generation": "tru')
        res = {'generation': S.gen, 'declared_size': S.total, 'received': len(S.buf)}
        if len(S.buf) == S.total: res['result'] = 'VALID'
        self._send(200, res)

srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
_Orig = http.client.HTTPConnection
http.client.HTTPConnection = lambda host, _p, timeout=None: _Orig('127.0.0.1', port, timeout=timeout)

payload = Path(tempfile.mkstemp()[1]); payload.write_bytes(os.urandom(300000)); want = hashlib.sha256(payload.read_bytes()).hexdigest()
cases = {
    'clean': [],
    'drop-before-commit': [None, 'drop-before-commit'],
    'drop-after-commit': [None, None, 'drop-after-commit'],
    '503-once': ['503'],
    'badjson-after-commit': [None, 'badjson'],
    '4-drops-in-a-row': [None, 'drop-before-commit', 'drop-before-commit', 'drop-after-commit', 'drop-before-commit'],
}
import builtins
FAILED = []
for name, faults in cases.items():
    S.faults = list(faults); S.chunk_posts = 0
    builtins.input = lambda *_: (_ for _ in ()).throw(AssertionError('asked operator to restart'))
    try:
        r = uw.upload('192.168.1.1', payload, 'preloader', progress=False)
        ok = hashlib.sha256(bytes(S.buf)).hexdigest() == want and r.get('received') == S.total
        print(f'{name:<22} {"PASS" if ok else "FAIL"} posts={S.chunk_posts} result={r.get("result")}')
        ok or FAILED.append(name)
    except Exception as e:
        print(f'{name:<22} FAIL {type(e).__name__}: {e}'); FAILED.append(name)
# 6 consecutive drops on one chunk must end in the operator prompt (bounded), not a loop.
S.faults = [None] + ['drop-before-commit'] * 6
answers = iter(['n'])
builtins.input = lambda *_: next(answers)
try:
    uw.upload('192.168.1.1', payload, 'preloader', progress=False); print('exhausted              FAIL (no stop)'); FAILED.append('exhausted')
except uw.UrsusWebError as e:
    print(f'exhausted              PASS stops after {uw.UPLOAD_CHUNK_ATTEMPTS} attempts: {e}')

# Telnet: a router-side close must fail at once, not after the command timeout.
import proven_backend as pb
tsrv = socket.socket(); tsrv.bind(('127.0.0.1', 0)); tsrv.listen(1)
def _peer():
    c, _ = tsrv.accept(); c.recv(4096); c.sendall(b'writing...\n'); time.sleep(0.5); c.close()
threading.Thread(target=_peer, daemon=True).start()
t = pb.Telnet('127.0.0.1', tsrv.getsockname()[1]); t0 = time.time()
try:
    t.command('nandwrite -p /dev/mtd0 x', timeout=30, echo=False); FAILED.append('telnet-eof')
except pb.Error as e:
    took = time.time() - t0
    print(f'telnet-eof             {"PASS" if took < 5 else "FAIL"} {took:.1f}s: {e}')
    took < 5 or FAILED.append('telnet-eof')
payload.unlink()
print('selftest_network_faults:', 'FAIL ' + ','.join(FAILED) if FAILED else 'PASS')
sys.exit(1 if FAILED else 0)

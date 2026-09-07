from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
data_dir = ROOT / ('data' if (ROOT / 'data').is_dir() else 'src')
backend = (data_dir / 'proven_backend.py').read_text(encoding='utf-8')
# The legacy USB backup agent is intentionally not part of the current kit and
# must not make the supported kit verifier fail.
required_line = next(line for line in backend.splitlines() if line.strip().startswith('required = (root_version'))
assert 'BACKUP_AGENT' not in required_line, required_line
assert 'if not BACKUP_AGENT.is_file()' in backend
assert 'используйте штатный TFTP или BootROM/RAM backup' in backend
print('STATEUI6_KIT_BOUNDARY_QA=PASS')

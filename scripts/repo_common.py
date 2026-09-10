from __future__ import annotations
import hashlib, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(root: Path) -> None:
    manifest = root / 'SHA256SUMS'
    rows = []
    for p in sorted(root.rglob('*'), key=lambda item: item.relative_to(root).as_posix()):
        if not p.is_file() or p == manifest:
            continue
        rows.append(f'{sha256(p)}  {p.relative_to(root).as_posix()}')
    manifest.write_text('\n'.join(rows) + '\n', encoding='utf-8', newline='\n')


def export_tree(dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    for name in (
        'START_ONECLICK.cmd', 'START_ONECLICK.sh',
        'START_EXPERT.cmd', 'START_EXPERT.sh',
        'START_UART_RESTORE.cmd', 'START_UART_RESTORE.sh',
        'VERSION',
    ):
        shutil.copy2(ROOT / name, dest / name)
    # Preserve the README that actually shipped in the current release.
    # The repository README is deliberately richer than the exported package README.
    shutil.copy2(ROOT / 'ursusflasher' / 'release' / 'README.md', dest / 'README.md')

    shutil.copytree(ROOT / 'ursusflasher' / 'src', dest / 'data')
    for p in (ROOT / 'config').glob('*.json'):
        shutil.copy2(p, dest / 'data' / p.name)
    shutil.copy2(ROOT / 'VERSION', dest / 'data' / 'VERSION')
    shutil.copytree(ROOT / 'payloads', dest / 'data' / 'payloads')
    shutil.copytree(ROOT / 'ursusflasher' / 'tools', dest / 'tools')
    shutil.copytree(ROOT / 'fw', dest / 'fw')
    shutil.copytree(ROOT / 'docs', dest / 'doc')

    payload_rows = []
    payload_root = dest / 'data' / 'payloads'
    for p in sorted(payload_root.rglob('*'), key=lambda item: item.relative_to(payload_root).as_posix()):
        if p.is_file():
            payload_rows.append(f'{sha256(p)}  {p.relative_to(dest).as_posix()}')
    (dest / 'PAYLOAD_SHA256SUMS.txt').write_text(
        '\n'.join(payload_rows) + '\n', encoding='utf-8', newline='\n'
    )
    write_manifest(dest)
    return dest

from __future__ import annotations
import hashlib, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Hardware-test ZIP payload allowlist. Build-only donors, source files,
# superseded engineering artifacts and large recovery-source duplicates stay
# out of data/payloads. Recovery/transition resources are exported through
# ursusflasher/src/data where their runtime backends expect them.
RELEASE_PAYLOADS = (
    # MD / AN7581 runtime + emergency line
    'payloads/md/ursusboot/openwrt-6.18.44-mtd-rw.ko',
    'payloads/md/ursusboot/openwrt-airoha-an7581-nokia_xg-040g-md-ubi-preloader.bin',
    'payloads/md/ursusboot/stock_mtd0_reference.bin',
    'payloads/md/ursusboot/ursus-mtd-raw',
    'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha3-bl2.bin',
    'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha3-ram-installer.fip',
    'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha3-update.fip',
    'payloads/md/ursusboot/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip',
    # MF / AN7583 current runtime + recovery + transition BL2
    'payloads/mf/ursusboot/u-boot.runtime.lzma',
    'payloads/mf/recovery/ursusboot-mf-0.1.0-TEST61-uart-preloader.bin',
    'payloads/mf/recovery/ursusboot-mf-0.1.0-TEST61-ram.fip',
    'payloads/mf/proven/nokia-xg-040g-mf-an7583-production-preloader.bin',
)


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


def _copy_payload_allowlist(dest: Path) -> None:
    payload_root = dest / 'data' / 'payloads'
    for rel in RELEASE_PAYLOADS:
        src = ROOT / rel
        if not src.is_file():
            raise FileNotFoundError(f'required release payload missing: {rel}')
        out = dest / 'data' / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)


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

    shutil.copy2(ROOT / 'ursusflasher' / 'release' / 'README.md', dest / 'README.md')

    ignore_runtime_junk = shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo')
    shutil.copytree(ROOT / 'ursusflasher' / 'src', dest / 'data', ignore=ignore_runtime_junk)
    for p in (ROOT / 'config').glob('*.json'):
        shutil.copy2(p, dest / 'data' / p.name)
    shutil.copy2(ROOT / 'VERSION', dest / 'data' / 'VERSION')

    _copy_payload_allowlist(dest)

    # Hardware-test package intentionally omits developer selftests/tools.
    # The final Actions workflow performs those checks before export.
    shutil.copytree(ROOT / 'fw', dest / 'fw', ignore=ignore_runtime_junk)
    shutil.copytree(ROOT / 'docs', dest / 'doc', ignore=ignore_runtime_junk)

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

from __future__ import annotations
import hashlib, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Hardware-test ZIP payload allowlist. Build-only donors, source files,
# superseded engineering artifacts and large recovery-source duplicates stay
# out of data/payloads. Recovery resources are exported through
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
    # MF / AN7583 current runtime + recovery + STOCK->UBI BL2
    'payloads/mf/ursusboot/u-boot.runtime.lzma',
    'payloads/mf/recovery/ursusboot-mf-0.1.0-TEST61-uart-preloader.bin',
    'payloads/mf/recovery/ursusboot-mf-0.1.0-TEST61-ram.fip',
    'payloads/mf/proven/nokia-xg-040g-mf-an7583-production-preloader.bin',
)

# Operator-facing documents only. Historical TEST57-TEST60 notes remain in the
# repository for provenance but do not belong in a TEST61 hardware kit.
RELEASE_DOCS = (
    'INSTRUCTIONS_RU.md',
    'INSTRUCTIONS_EN.md',
    'EMERGENCY_URSUSBOOT_RU.md',
    'TEST61_TEST_RU.md',
    'CHANGELOG_RU.md',
    'CHANGELOG_EN.md',
    'README_EN.md',
    'UrsusBoot_UrsusFlasher_TZ_RU_v5.38_MF_PERSISTENT_CORRECTION.md',
)

# Superseded MedveFlasher transition installer and rejected acceptance stages.
RUNTIME_EXCLUDES = {
    '__pycache__',
    'vendor',
    'alpha4_hwfix_test.py',
    'expert_mf_acceptance.py',
    'mf_persistent_install.py',
    'transition-bundle.bin',
    'transition-manual-bundle.bin',
    'mf-transition-bundle.bin',
    'mf-transition-manual-bundle.bin',
    'stock-launcher.sh.in',
    'env_patcher.py',
}
RECOVERY_SOURCE_EXCLUDES = {
    'manual-transition-source',
    'transition-control-source',
    'transition-network-source',
    'recovery-clients-source',
    'recovery-safe-uboot-source',
}


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
    for rel in RELEASE_PAYLOADS:
        src = ROOT / rel
        if not src.is_file():
            raise FileNotFoundError(f'required release payload missing: {rel}')
        out = dest / 'data' / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)


def _runtime_ignore(directory: str, names: list[str]) -> set[str]:
    ignored = {name for name in names if name in RUNTIME_EXCLUDES or name.endswith(('.pyc', '.pyo'))}
    if Path(directory).name == 'recovery':
        ignored.update(name for name in names if name in RECOVERY_SOURCE_EXCLUDES)
    return ignored


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
    shutil.copytree(ROOT / 'ursusflasher' / 'src', dest / 'data', ignore=_runtime_ignore)
    for p in (ROOT / 'config').glob('*.json'):
        shutil.copy2(p, dest / 'data' / p.name)
    shutil.copy2(ROOT / 'VERSION', dest / 'data' / 'VERSION')

    _copy_payload_allowlist(dest)

    # Firmware is canonical and intentionally limited to the eight UnameOne
    # MD/MF images committed under fw/.
    shutil.copytree(ROOT / 'fw', dest / 'fw', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))

    doc_dest = dest / 'doc'
    doc_dest.mkdir(parents=True, exist_ok=True)
    for name in RELEASE_DOCS:
        src = ROOT / 'docs' / name
        if not src.is_file():
            raise FileNotFoundError(f'required release document missing: docs/{name}')
        shutil.copy2(src, doc_dest / name)

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

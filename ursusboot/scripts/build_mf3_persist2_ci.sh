#!/bin/bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
GITHUB_SHA=${GITHUB_SHA:-$(git rev-parse HEAD)}
export GITHUB_SHA
MEDVE_DIR=${MF2_MEDVE_DIR:-"$ROOT/work/medveflasher-rc35"}
export MF2_MEDVE_DIR="$MEDVE_DIR"

python3 - <<'PY'
from pathlib import Path

p = Path('ursusboot/scripts/build_mf2_ramboot.sh')
s = p.read_text(encoding='utf-8')
old = 'VERSION="0.1.0-mf2-ram1"\n'
if s.count(old) != 1:
    raise SystemExit(f'VERSION anchor count={s.count(old)}')
s = s.replace(old, 'VERSION="0.1.0-mf3-persist2"\n', 1)

anchor = 'python3 "$TRANSFORM" "$WORK/u-boot"\n'
extra = anchor + (
    'python3 "$ROOT/ursusboot/scripts/mf2_lan23_led_pinmux.py" "$WORK/u-boot"\n'
    'python3 "$ROOT/ursusboot/scripts/mf2_hwtest7_phy_probe.py" "$WORK/u-boot"\n'
    'python3 "$ROOT/ursusboot/scripts/mf2_hwtest8_led_fix.py" "$WORK/u-boot"\n'
    'python3 "$ROOT/ursusboot/scripts/mf2_hwtest5_web_quiet.py" "$WORK/u-boot"\n'
    'python3 "$ROOT/ursusboot/scripts/mf3_persist1_enable.py" "$WORK/u-boot"\n'
    'python3 "$ROOT/ursusboot/scripts/mf3_persist2_validator.py" "$WORK/u-boot"\n'
    'python3 "$ROOT/ursusboot/scripts/mf3_persist2_identity.py" "$WORK/u-boot" "${GITHUB_SHA}"\n'
)
if s.count(anchor) != 1:
    raise SystemExit(f'transform anchor count={s.count(anchor)}')
s = s.replace(anchor, extra, 1)

epoch = 'export CROSS_COMPILE=aarch64-openwrt-linux-musl- SOURCE_DATE_EPOCH="$RELEASE_EPOCH"\n'
dyn_epoch = (
    'BUILD_EPOCH=$(git show -s --format=%ct "${GITHUB_SHA}")\n'
    'export CROSS_COMPILE=aarch64-openwrt-linux-musl- SOURCE_DATE_EPOCH="$BUILD_EPOCH"\n'
)
if s.count(epoch) != 1:
    raise SystemExit(f'SOURCE_DATE_EPOCH anchor count={s.count(epoch)}')
s = s.replace(epoch, dyn_epoch, 1)

scm_check = '[ "$(cat .scmversion)" = "-UrsusBoot-${VERSION}" ] || { echo "MF2 .scmversion mismatch" >&2; exit 1; }\n'
scm_new = "grep -Eq '^-UrsusBoot-0\\.1\\.0-mf3-persist2\\+g[0-9a-f]{8}$' .scmversion || { echo \"MF3 PERSIST2 .scmversion mismatch\" >&2; exit 1; }\n"
if s.count(scm_check) != 1:
    raise SystemExit('scmversion check anchor missing')
s = s.replace(scm_check, scm_new, 1)

hdr_check = 'grep -Fq "#define URSUS_VERSION \\\"${VERSION}\\\"" include/ursus_version.h || { echo "MF2 version header mismatch" >&2; exit 1; }\n'
hdr_new = "grep -Eq '^#define URSUS_VERSION \\\"0\\.1\\.0-mf3-persist2\\+g[0-9a-f]{8}\\\"$' include/ursus_version.h || { echo \"MF3 PERSIST2 version header mismatch\" >&2; exit 1; }\n"
if s.count(hdr_check) != 1:
    raise SystemExit('version header check anchor missing')
s = s.replace(hdr_check, hdr_new, 1)

start = s.index('for marker in "$VERSION"')
end = s.index("if grep -Fq 'Nokia XG-040G-MD'", start)
marker_loop = '''for marker in '0.1.0-mf3-persist2' 'Nokia XG-040G-MF' 'Airoha AN7583' 'URSUS_MF3_PERSIST2_PRECHECK' 'URSUS_MF3_PERSIST2_COMMIT_OK' 'URSUS_MF3_PERSIST2_POST_ALLOW' 'URSUS_MF3_PERSIST2_POST_REJECT' 'FIP_UPDATE_ROLLBACK' 'URSUSBOOT_MF' 'NOKIA_XG040GMF_STOCK' 'AN7583DT' 'XG040GMF' 'MD_STYLE_GENERAL' 'URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE' 'URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION' 'URSUS_MF2_READONLY_REJECT operation=SETTINGS_RESET_BACKEND' 'URSUS_MF2_HWTEST8_LED_BEGIN'; do
    grep -Fq "$marker" "$WORK/u-boot.strings" || { echo "MF3 PERSIST2 binary marker missing: $marker" >&2; exit 1; }
done
! grep -Fq 'FIP_ONLY_CANARY' "$WORK/u-boot.strings" || { echo "obsolete canary policy survived PERSIST2" >&2; exit 1; }
! grep -Fq 'URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE' "$WORK/u-boot.strings" || { echo "MF2 FIP write gate survived PERSIST2" >&2; exit 1; }
'''
s = s[:start] + marker_loop + s[end:]

s = s.replace('"MODE=RAM_ONLY_READONLY_BRINGUP"', '"MODE=PERSIST2_FIP_UPDATE_ROLLBACK"')
s = s.replace('"PERSISTENT_WRITES=DISABLED"', '"PERSISTENT_WRITES=FIP_UPDATE_ROLLBACK"')
s = s.replace('"HTTP_POST=REJECTED"', '"HTTP_POST=RAM_INITRAMFS_PLUS_FIP_UPDATE_ROLLBACK"')
s = s.replace('"RECOVERY_PORTS=LAN2,LAN3"', '"RECOVERY_PORTS=LAN2,LAN3,LAN4"')
p.write_text(s, encoding='utf-8')

cfg = Path('ursusboot/configs/an7583_nokia_xg-040g-mf_MF2_RAM_defconfig')
c = cfg.read_text(encoding='utf-8')
if c.count('CONFIG_LOGLEVEL=9') != 1:
    raise SystemExit('CONFIG_LOGLEVEL=9 anchor missing')
cfg.write_text(c.replace('CONFIG_LOGLEVEL=9', 'CONFIG_LOGLEVEL=7', 1), encoding='utf-8')
print('MF3_PERSIST2_BUILD_BINDING=PASS hwtest8=retained validator=md-style-general writes=fip-update-rollback loglevel=7')
PY

bash ursusboot/scripts/build_mf2_ramboot.sh

OUT="$ROOT/work/mf2-ramboot/out"
SRC="$ROOT/work/mf2-ramboot/u-boot"
DONOR="$MEDVE_DIR/data/payloads/nokia-xg-040g-mf-an7583-production-bl31-uboot.fip"
test "$(stat -c %s "$DONOR")" = 319568
test "$(sha256sum "$DONOR" | awk '{print $1}')" = 99b6c20a7cb46a56692eaeb9f086f70fc7e987a641396653e6a8fb5c03e07aa7

python3 ursusboot/scripts/mf2_repack_from_medve.py \
  --medve-patcher "$MEDVE_DIR/data/recovery/recovery-safe-uboot-source/patch_recovery_safe_fip.py" \
  --source "$DONOR" \
  --bl33-raw "$OUT/u-boot.bin" \
  --bl33-output "$OUT/u-boot.persistent.lzma" \
  --output "$OUT/ursusboot-mf-0.1.0-mf3-persist2-persistent.fip" \
  --report "$OUT/MF3-PERSIST2-FIP-REPACK.json"

python3 - <<'PY'
import json
from pathlib import Path
r=json.loads(Path('work/mf2-ramboot/out/MF3-PERSIST2-FIP-REPACK.json').read_text())
assert r['entry_count'] == 2
assert r['bl31_byte_exact'] is True
assert r['mf2_bl33_roundtrip'] is True
assert r['mf2_bl33_lzma_known_size'] is True
assert r['mf2_bl33_lzma_eopm'] is False
print('MF3_PERSIST2_FIP_QA=PASS sha256=' + r['output_sha256'] + ' size=' + str(r['output_size']))
PY
sha256sum "$OUT/ursusboot-mf-0.1.0-mf3-persist2-persistent.fip" "$OUT/u-boot.persistent.lzma" >> "$OUT/SHA256SUMS"

CFG="$OUT/u-boot.MF2_RAM.full.config"
BIN="$OUT/u-boot.bin"
for sym in CONFIG_CMD_MTD CONFIG_CMD_MTD_MARKBAD CONFIG_CMD_MTD_NAND_WRITE_TEST CONFIG_CMD_UBI CONFIG_CMD_UBI_RENAME CONFIG_CMD_ERASEENV CONFIG_CMD_NAND CONFIG_CMD_SF CONFIG_ENV_IS_IN_MTD CONFIG_ENV_IS_IN_UBI; do
  ! grep -q "^${sym}=y" "$CFG"
done
grep -Eq '^CONFIG_ENV_IS_NOWHERE=y$' "$CFG"
grep -Eq '^CONFIG_LOGLEVEL=7$' "$CFG"

strings "$BIN" | grep -Eq '0\.1\.0-mf3-persist2\+g[0-9a-f]{8}'
for marker in \
  'URSUS_MF3_PERSIST2_COMMIT_BEGIN' \
  'URSUS_MF3_PERSIST2_COMMIT_OK' \
  'URSUS_MF3_FIP_IDENTITY identity=%s validation=FIP_PARSE+NTFW_LZMA+BOARD_SOC' \
  'URSUS_UPDATE_CURRENT_FIP_OK identity=%s bytes=0x%x' \
  'NOKIA_XG040GMF_STOCK' \
  'URSUSBOOT_MF' \
  'AN7583DT' \
  'XG040GMF' \
  'nokia,xg-040g-mf' \
  'airoha,an7583' \
  'validator=MD_STYLE_GENERAL' \
  'FIP_UPDATE_ROLLBACK' \
  'URSUS_UPDATE_READBACK_OK layout=STOCK bytes=0x%lx prefix=preserved env=preserved' \
  'URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE' \
  'URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION' \
  'URSUS_MF2_READONLY_REJECT operation=SETTINGS_RESET_BACKEND' \
  'URSUS_MF2_HWTEST8_LED_END result=OK'; do
  strings "$BIN" | grep -Fq "$marker"
done
! strings "$BIN" | grep -Fq 'FIP_ONLY_CANARY'
! strings "$BIN" | grep -Fq 'URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE'

python3 - <<'PY'
from pathlib import Path
web=Path('work/mf2-ramboot/u-boot/cmd/ursusweb.c').read_text()
upd=Path('work/mf2-ramboot/u-boot/cmd/ursusupdate.c').read_text()

# General MF validator must follow the MD sequence: parse FIP -> locate NT FW ->
# LZMA decompress -> classify board/SoC. No exact artifact hash/size whitelist.
vc0=upd.index('static int ursus_fip_validate_buf(')
vc1=upd.index('\nint ursus_fip_validate(', vc0)
validator=upd[vc0:vc1]
assert 'ursus_fip_parse(buf, len' in validator
assert 'lzmaBuffToBuffDecompress' in validator
assert 'U-Boot 2026.07-UrsusBoot-' in validator
assert 'nokia,xg-040g-mf' in validator
assert 'airoha,an7583' in validator
assert 'AN7583DT' in validator
assert 'XG040GMF' in validator
assert 'sha256_csum_wd' in validator
for bad in ('eadfd9be0309c615', '296382', 'FIP_ONLY_CANARY'):
    assert bad not in validator, bad

# Stock layout writer remains exactly one full 512-KiB preserve/replace/readback
# transaction. Generic writer CLI and unrelated Web writes remain unavailable.
gate=web.index('URSUS_MF3_PERSIST2_POST_REJECT')
for route in (
    'POST /api/console ', 'POST /api/firmware-begin ',
    'POST /api/ubi-preloader-begin ', 'POST /api/install-openwrt-stock-layout ',
    'POST /api/install-ubi ', 'POST /api/reset-openwrt-settings '):
    assert web.index(route, gate) > gate, route
step0=upd.index('int ursus_fip_update_step(void)')
step1=upd.index('static int ursus_update_run(', step0)
step=upd[step0:step1]
assert 'run_command("ubi ' not in step
assert 'URSUS_UP_UBI_' not in step
assert 'mtd_erase(ursus_update_nand' in step
assert 'mtd_write(ursus_update_nand' in step
assert 'memcmp(ursus_up.stock_candidate, ursus_up.stock_readback' in step
assert 'MF3_PERSIST2_UBI_BLOCKED' in step
print('MF3_PERSIST2_SOURCE_SCOPE=PASS validator=general-mf+stock-rollback stock-fip-direct-mtd-only=1 readback=full-512KiB')
PY

python3 - <<'PY'
import hashlib, json
from pathlib import Path
out=Path('work/mf2-ramboot/out')
files={
    'ram_preloader': out/'ursusboot-mf-0.1.0-mf3-persist2-uart-preloader.bin',
    'ram_fip': out/'ursusboot-mf-0.1.0-mf3-persist2-ram.fip',
    'persistent_fip': out/'ursusboot-mf-0.1.0-mf3-persist2-persistent.fip',
    'uboot': out/'u-boot.bin',
}
report={
    'result':'PASS',
    'target':'Nokia XG-040G-MF / Airoha AN7583',
    'mode':'PERSIST2_FIP_UPDATE_ROLLBACK',
    'validator':'MD-style structural FIP + NT FW LZMA decompression + MF identity',
    'accepted_candidate_identities':['URSUSBOOT_MF','NOKIA_XG040GMF_STOCK'],
    'exact_build_whitelist':'NONE',
    'write_scope':'stock mtd0 0x00000000..0x0007ffff only, via full-span preserve/replace/readback',
    'fip_offset':'0x800',
    'stock_bootloader_span':'0x80000',
    'stock_env_offset':'0x7c000',
    'stock_env_size':'0x4000',
    'ubi_migration':'BLOCKED',
    'openwrt_install':'BLOCKED',
    'settings_write':'BLOCKED',
    'web_console':'BLOCKED_BY_POST_GATE',
    'generic_writer_commands':'DISABLED_BY_KCONFIG',
    'bl2_write':'NONE',
    'lan234_hw_baseline':'HWTEST8_ACCEPTED_BY_OPERATOR',
    'files':{},
}
for name,p in files.items():
    b=p.read_bytes()
    report['files'][name]={'name':p.name,'size':len(b),'sha256':hashlib.sha256(b).hexdigest()}
(out/'MF3-PERSIST2-AUDIT.json').write_text(json.dumps(report,indent=2)+'\n')
print('MF3_PERSIST2_AUDIT=PASS')
PY

SHORT_SHA=${GITHUB_SHA:0:8}
BUILD_EPOCH=$(git show -s --format=%ct "$GITHUB_SHA")
BUILD_UTC=$(date -u -d "@$BUILD_EPOCH" '+%Y-%m-%dT%H:%M:%SZ')
PERSIST_SIZE=$(stat -c %s "$OUT/ursusboot-mf-0.1.0-mf3-persist2-persistent.fip")
PERSIST_SHA=$(sha256sum "$OUT/ursusboot-mf-0.1.0-mf3-persist2-persistent.fip" | awk '{print $1}')
{
  echo 'STAGE=PERSIST2'
  echo "GIT_SHA=$GITHUB_SHA"
  echo "DISPLAY_VERSION=0.1.0-mf3-persist2+g$SHORT_SHA"
  echo "BUILD_UTC=$BUILD_UTC"
  echo 'HW_BASELINE=MF2 HWTEST8 LAN2/LAN3/LAN4 accepted on hardware'
  echo 'VALIDATOR=MD_STYLE_GENERAL_FIP_PARSE_NTFW_LZMA_MF_IDENTITY'
  echo 'ACCEPTED=URSUSBOOT_MF,NOKIA_XG040GMF_STOCK'
  echo 'EXACT_BUILD_WHITELIST=NONE'
  echo 'WRITE_SCOPE=FIP_UPDATE_ROLLBACK'
  echo 'STOCK_BOOTLOADER_SPAN=0x80000'
  echo 'FIP_OFFSET=0x800'
  echo 'ENV_OFFSET=0x7c000'
  echo 'ENV_SIZE=0x4000'
  echo 'UBI_MIGRATION=BLOCKED'
  echo 'BL2_WRITE=NONE'
  echo 'GENERIC_WRITER_COMMANDS=DISABLED'
  echo "PERSISTENT_FIP_SIZE=$PERSIST_SIZE"
  echo "PERSISTENT_FIP_SHA256=$PERSIST_SHA"
} | tee "$OUT/MF3-PERSIST2-BUILD-ID.txt"

echo "MF3_PERSIST2_CI=PASS out=$OUT"

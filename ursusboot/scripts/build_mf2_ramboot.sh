#!/bin/bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=${URSUS_BUILD_DIR:-"$ROOT/work/mf2-ramboot"}
SDK_BUNDLE="$ROOT/toolchains/openwrt-sdk-r35906/openwrt-sdk-r35906.tar.zst"
SOURCE_BUNDLE="$ROOT/ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-TEST61-source.tar.zst"
CONFIG="$ROOT/ursusboot/configs/an7583_nokia_xg-040g-mf_MF2_RAM_defconfig"
ENVFILE="$ROOT/ursusboot/configs/an7583_nokia_xg-040g-mf_MF2_RAM_env"
TRANSFORM="$ROOT/ursusboot/scripts/mf2_ramreadonly_transform.py"
MEDVE_DIR=${MF2_MEDVE_DIR:-"$ROOT/work/medveflasher-rc35"}
PRELOADER="$MEDVE_DIR/data/payloads/nokia-xg-040g-mf-an7583-uart-preloader.bin"
DONOR="$MEDVE_DIR/data/payloads/nokia-xg-040g-mf-an7583-uart-recovery-safe-bl31-uboot.fip"
OUT="$WORK/out"
VERSION="0.1.0-mf2-ram1"
RELEASE_EPOCH=1788948000

EXPECTED_PRELOADER_SIZE=118322
EXPECTED_PRELOADER_SHA=c2ac1c183b18bc34632c958dfe0bd1dfdfb607f090e39c41126956641893362f
EXPECTED_DONOR_SIZE=339010
EXPECTED_DONOR_SHA=8bfe8870e44923a463a3ed66c8b1906214f5c820fd8c15865c63430185de8bb2

for x in tar make gcc perl python3 sha256sum strings patch stat; do command -v "$x" >/dev/null; done
[ -f "$SOURCE_BUNDLE" ] || { echo "TEST61 source snapshot missing" >&2; exit 1; }
[ -f "$CONFIG" ] || { echo "MF2 config missing" >&2; exit 1; }
[ -f "$ENVFILE" ] || { echo "MF2 env missing" >&2; exit 1; }
[ -f "$PRELOADER" ] || { echo "Pinned MedveFlasher MF UART preloader missing: $PRELOADER" >&2; exit 1; }
[ -f "$DONOR" ] || { echo "Pinned MedveFlasher MF SAFE FIP missing: $DONOR" >&2; exit 1; }

[ "$(stat -c %s "$PRELOADER")" = "$EXPECTED_PRELOADER_SIZE" ] || { echo "MF preloader size mismatch" >&2; exit 1; }
[ "$(sha256sum "$PRELOADER" | awk '{print $1}')" = "$EXPECTED_PRELOADER_SHA" ] || { echo "MF preloader SHA256 mismatch" >&2; exit 1; }
[ "$(stat -c %s "$DONOR")" = "$EXPECTED_DONOR_SIZE" ] || { echo "MF SAFE donor size mismatch" >&2; exit 1; }
[ "$(sha256sum "$DONOR" | awk '{print $1}')" = "$EXPECTED_DONOR_SHA" ] || { echo "MF SAFE donor SHA256 mismatch" >&2; exit 1; }

echo "MF2_MEDVE_INPUTS=PASS commit=342cac4cb99a924f3d83eb8e4b5259490377704e"

if [ ! -f "$SDK_BUNDLE" ]; then bash "$ROOT/toolchains/openwrt-sdk-r35906/reassemble-sdk.sh" >/dev/null; fi
EXPECTED_SDK=$(awk '{print $1}' "$ROOT/toolchains/openwrt-sdk-r35906/SDK_SHA256SUMS")
ACTUAL_SDK=$(sha256sum "$SDK_BUNDLE" | awk '{print $1}')
[ "$ACTUAL_SDK" = "$EXPECTED_SDK" ] || { echo "SDK SHA256 mismatch" >&2; exit 1; }

rm -rf "$WORK"
mkdir -p "$WORK/sdk" "$WORK/u-boot" "$OUT"
tar --zstd -xf "$SDK_BUNDLE" -C "$WORK/sdk"
tar --zstd -xf "$SOURCE_BUNDLE" -C "$WORK/u-boot"

# The exact TEST61 snapshot already contains the native OpenWrt AN7583 target.
# Only the dedicated MF2 identity/read-only delta is applied here.
python3 "$TRANSFORM" "$WORK/u-boot"
cp "$ENVFILE" "$WORK/u-boot/defenvs/an7583_nokia_xg-040g-mf_env"
cp "$CONFIG" "$WORK/u-boot/.config"

SDK_ROOT=$(find "$WORK/sdk" -mindepth 1 -maxdepth 1 -type d -name 'openwrt-sdk-*' | head -n1)
[ -n "$SDK_ROOT" ] || { echo "SDK root not found" >&2; exit 1; }
TC="$SDK_ROOT/staging_dir/toolchain-aarch64_cortex-a53_gcc-14.4.0_musl/bin"
HOST="$SDK_ROOT/staging_dir/host"
chmod +x "$ROOT/toolchains/hostshim/xxd" 2>/dev/null || true
export URSUS_SDK_ROOT="$SDK_ROOT" STAGING_DIR="$SDK_ROOT/staging_dir" STAGING_DIR_HOST="$HOST" BISON_PKGDATADIR="$HOST/share/bison"
export PATH="$ROOT/toolchains/hostshim:$TC:$HOST/bin:/usr/bin:/bin"
export CROSS_COMPILE=aarch64-openwrt-linux-musl- SOURCE_DATE_EPOCH="$RELEASE_EPOCH"

cd "$WORK/u-boot"
make olddefconfig

# Compile-time RAM-only contract: retain MTD/SPI-NAND drivers for reads and
# AN7583 LAN2/LAN3 diagnostics, but expose no generic persistent writer.
for sym in CONFIG_CMD_MTD CONFIG_CMD_MTD_MARKBAD CONFIG_CMD_MTD_NAND_WRITE_TEST CONFIG_CMD_UBI CONFIG_CMD_UBI_RENAME CONFIG_CMD_ERASEENV CONFIG_CMD_NAND CONFIG_CMD_SF CONFIG_CMD_PXE CONFIG_ENV_IS_IN_MTD CONFIG_ENV_IS_IN_UBI; do
    if grep -q "^${sym}=y" .config; then
        echo "MF2 RAM-only config violation: ${sym}=y" >&2
        exit 1
    fi
done
for sym in CONFIG_TARGET_AN7583 CONFIG_MTD CONFIG_DM_MTD CONFIG_MTD_SPI_NAND CONFIG_NET_LWIP CONFIG_AIROHA_ETH CONFIG_PCS_AIROHA_AN7583 CONFIG_PINCTRL_AIROHA_AN7583 CONFIG_ENV_IS_NOWHERE CONFIG_CONSOLE_RECORD; do
    grep -q "^${sym}=y" .config || { echo "Required MF2 symbol missing: ${sym}" >&2; exit 1; }
done

grep -Fq 'CONFIG_DEFAULT_DEVICE_TREE="an7583-nokia-xg-040g-mf"' .config || { echo "wrong MF2 DTS" >&2; exit 1; }
grep -Fxq 'bootcmd=ursusweb' defenvs/an7583_nokia_xg-040g-mf_env || { echo "MF2 bootcmd is not ursusweb" >&2; exit 1; }
! grep -Eq 'saveenv|mtd (erase|write)|ubi (write|create|remove|rename|detach)' defenvs/an7583_nokia_xg-040g-mf_env || { echo "persistent command leaked into MF2 env" >&2; exit 1; }

make -j"${JOBS:-$(nproc)}"

gcc -O2 -Wall -Wextra lzma1ext_noeopm.c -llzma -o "$WORK/lzma1ext_noeopm"
"$WORK/lzma1ext_noeopm" u-boot.bin u-boot.lzma 1048576
python3 repack_persistent_fip.py "$DONOR" u-boot.lzma "ursusboot-mf-${VERSION}-ram.fip"

cp u-boot u-boot.bin u-boot.map u-boot.sym System.map u-boot.lzma "ursusboot-mf-${VERSION}-ram.fip" "$OUT/"
cp "$PRELOADER" "$OUT/ursusboot-mf-${VERSION}-uart-preloader.bin"
cp .config "$OUT/u-boot.MF2_RAM.full.config"
cp defenvs/an7583_nokia_xg-040g-mf_env "$OUT/MF2_RAM.env"

[ "$(cat .scmversion)" = "-UrsusBoot-${VERSION}" ] || { echo "MF2 .scmversion mismatch" >&2; exit 1; }
grep -Fq "#define URSUS_VERSION \"${VERSION}\"" include/ursus_version.h || { echo "MF2 version header mismatch" >&2; exit 1; }
strings u-boot.bin > "$WORK/u-boot.strings"
for marker in "$VERSION" 'Nokia XG-040G-MF' 'Airoha AN7583' 'URSUS_MF2_READONLY_REJECT operation=FIP_UPDATE' 'URSUS_MF2_READONLY_REJECT operation=UBI_UPDATE' 'URSUS_MF2_READONLY_REJECT operation=UBI_MIGRATION' 'URSUS_MF2_READONLY_REJECT operation=SETTINGS_RESET' 'MF2 RAM-only build: persistent operations disabled'; do
    grep -Fq "$marker" "$WORK/u-boot.strings" || { echo "MF2 binary marker missing: $marker" >&2; exit 1; }
done
if grep -Fq 'Nokia XG-040G-MD' "$WORK/u-boot.strings"; then
    echo "MD board identity leaked into MF2 binary" >&2
    exit 1
fi

python3 - "$OUT/ursusboot-mf-${VERSION}-ram.fip" <<'PYQA'
import hashlib, struct, sys
p=sys.argv[1]
d=open(p,'rb').read()
assert struct.unpack_from('<I',d,0)[0] == 0xaa640001
pos=16; nt=None
for _ in range(32):
    u=d[pos:pos+16]
    off,size,flags=struct.unpack_from('<QQQ',d,pos+16)
    if u == b'\0'*16: break
    if u == bytes.fromhex('d6d0eea7fcead54b97829934f234b6e4'):
        nt=(off,size)
    pos += 40
assert nt, 'BL33/NT_FW_CONFIG entry missing'
assert nt[0]+nt[1] <= len(d), (nt, len(d))
print(f'MF2_FIP_QA=PASS size={len(d)} nt_off=0x{nt[0]:x} nt_size={nt[1]} sha256={hashlib.sha256(d).hexdigest()}')
PYQA

sha256sum "$OUT/ursusboot-mf-${VERSION}-uart-preloader.bin" "$OUT/ursusboot-mf-${VERSION}-ram.fip" "$OUT/u-boot.bin" "$OUT/u-boot.lzma" | tee "$OUT/SHA256SUMS"
printf '%s\n' \
  "UrsusBoot ${VERSION}" \
  "TARGET=Nokia XG-040G-MF / Airoha AN7583" \
  "MODE=RAM_ONLY_READONLY_BRINGUP" \
  "SOURCE=TEST61 exact source snapshot" \
  "OPENWRT_BASELINE=3d1645ee26d6a2e20be71d7fa1716721bac78e53" \
  "MEDVEFLASHER_COMMIT=342cac4cb99a924f3d83eb8e4b5259490377704e" \
  "UART_PRELOADER_SHA256=${EXPECTED_PRELOADER_SHA}" \
  "DONOR_SAFE_FIP_SHA256=${EXPECTED_DONOR_SHA}" \
  "PERSISTENT_WRITES=DISABLED" \
  "HTTP_POST=REJECTED" \
  "ENV=NOWHERE" \
  "RECOVERY_PORTS=LAN2,LAN3" \
  "LAN1_EN8811=OUT_OF_SCOPE_MF2" > "$OUT/MF2-BUILD_INFO.txt"

echo "MF2_RAMBOOT_BUILD=PASS"
echo "Artifacts: $OUT"

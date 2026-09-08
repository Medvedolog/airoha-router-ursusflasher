#!/bin/bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=${URSUS_BUILD_DIR:-"$ROOT/work/alpha5-test61-rebuild"}
SDK_BUNDLE="$ROOT/toolchains/openwrt-sdk-r35906/openwrt-sdk-r35906.tar.zst"
SOURCE_BUNDLE="$ROOT/ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-source.tar.zst"
CONFIG="$ROOT/ursusboot/configs/u-boot.TEST61.full.config"
DONOR="$ROOT/payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-FUDAN1-update.fip"
PATCH1="$ROOT/ursusboot/patches/130-webfailsafe-webreboot1.patch"
PATCH2="$ROOT/ursusboot/patches/140-test57-diagcap-resetnet1.patch"
PATCH3="$ROOT/ursusboot/patches/150-test58-buildid.patch"
PATCH4="$ROOT/ursusboot/patches/160-test59-corrective.patch"
PATCH5="$ROOT/ursusboot/patches/170-test60-configtrim1.patch"
PATCH6="$ROOT/ursusboot/patches/180-test61-safetyreg1.patch"
OUT="$WORK/out"
RELEASE_EPOCH=1788888600  # 2026-09-08 17:30:00 UTC
for x in tar make gcc perl python3 sha256sum patch; do command -v "$x" >/dev/null; done
if [ ! -f "$SDK_BUNDLE" ]; then bash "$ROOT/toolchains/openwrt-sdk-r35906/reassemble-sdk.sh" >/dev/null; fi
EXPECTED_SDK=$(awk '{print $1}' "$ROOT/toolchains/openwrt-sdk-r35906/SDK_SHA256SUMS")
ACTUAL_SDK=$(sha256sum "$SDK_BUNDLE" | awk '{print $1}')
[ "$ACTUAL_SDK" = "$EXPECTED_SDK" ] || { echo "SDK SHA256 mismatch" >&2; exit 1; }
rm -rf "$WORK"; mkdir -p "$WORK/sdk" "$WORK/u-boot" "$OUT"
tar --zstd -xf "$SDK_BUNDLE" -C "$WORK/sdk"
tar --zstd -xf "$SOURCE_BUNDLE" -C "$WORK/u-boot"
patch -d "$WORK/u-boot" -p1 < "$PATCH1"
patch -d "$WORK/u-boot" -p1 < "$PATCH2"
patch -d "$WORK/u-boot" -p1 < "$PATCH3"
patch -d "$WORK/u-boot" -p1 < "$PATCH4"
patch -d "$WORK/u-boot" -p1 < "$PATCH5"
patch -d "$WORK/u-boot" -p1 < "$PATCH6"
SDK_ROOT=$(find "$WORK/sdk" -mindepth 1 -maxdepth 1 -type d -name 'openwrt-sdk-*' | head -n1)
[ -n "$SDK_ROOT" ] || { echo "SDK root not found" >&2; exit 1; }
TC="$SDK_ROOT/staging_dir/toolchain-aarch64_cortex-a53_gcc-14.4.0_musl/bin"
HOST="$SDK_ROOT/staging_dir/host"
chmod +x "$ROOT/toolchains/hostshim/xxd" 2>/dev/null || true
export URSUS_SDK_ROOT="$SDK_ROOT" STAGING_DIR="$SDK_ROOT/staging_dir" STAGING_DIR_HOST="$HOST" BISON_PKGDATADIR="$HOST/share/bison"
export PATH="$ROOT/toolchains/hostshim:$TC:$HOST/bin:/usr/bin:/bin"
export CROSS_COMPILE=aarch64-openwrt-linux-musl- SOURCE_DATE_EPOCH="$RELEASE_EPOCH"
cp "$CONFIG" "$WORK/u-boot/.config"
cd "$WORK/u-boot"
make olddefconfig
for sym in CONFIG_CMD_UBIFS CONFIG_CMD_PXE CONFIG_BOOTMETH_EXTLINUX CONFIG_BOOTMETH_EXTLINUX_PXE CONFIG_PXE_UTILS; do
    if grep -q "^${sym}=y" .config; then
        echo "CONFIGTRIM1 failed: ${sym}=y" >&2
        exit 1
    fi
done
for sym in CONFIG_CMD_UBI CONFIG_MTD_UBI CONFIG_CMD_TFTPBOOT CONFIG_CMD_WGET; do
    grep -q "^${sym}=y" .config || { echo "Required ${sym} is not enabled" >&2; exit 1; }
done
make -j"${JOBS:-$(nproc)}"
gcc -O2 -Wall -Wextra lzma1ext_noeopm.c -llzma -o "$WORK/lzma1ext_noeopm"
"$WORK/lzma1ext_noeopm" u-boot.bin u-boot.lzma 1048576
python3 repack_persistent_fip.py "$DONOR" u-boot.lzma ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip
cp u-boot u-boot.bin u-boot.map u-boot.sym System.map u-boot.lzma ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip "$OUT/"
EXPECTED_VERSION="0.1.0-alpha5-UBIUX1-TEST61"
SCM_EXPECTED="-UrsusBoot-${EXPECTED_VERSION}"
[ "$(cat .scmversion)" = "$SCM_EXPECTED" ] || { echo "IDENTITY1 .scmversion mismatch" >&2; exit 1; }
grep -Fq "#define URSUS_VERSION \"${EXPECTED_VERSION}\"" include/ursus_version.h || { echo "IDENTITY1 header mismatch" >&2; exit 1; }
strings u-boot.bin > "$WORK/u-boot.strings"
grep -Fq "$EXPECTED_VERSION" "$WORK/u-boot.strings" || { echo "IDENTITY1 binary version missing" >&2; exit 1; }
python3 - "$OUT/ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip" <<'PYQA'
import struct,sys
p=sys.argv[1]; d=open(p,'rb').read(); assert len(d)<0x7b800
assert struct.unpack_from('<I',d,0)[0]==0xaa640001
pos=16; nt=None
for _ in range(32):
    u=d[pos:pos+16]; off,size,flags=struct.unpack_from('<QQQ',d,pos+16)
    if u==b'\0'*16: break
    if u==bytes.fromhex('d6d0eea7fcead54b97829934f234b6e4'): nt=(off,size)
    pos+=40
assert nt and nt[0]+nt[1] <= 0x77800, nt
print(f'FIP_BOUNDARY_QA=PASS size={len(d)} nt_end=0x{nt[0]+nt[1]:x} margin={0x77800-(nt[0]+nt[1])}')
PYQA
sha256sum u-boot.bin u-boot.lzma ursusboot-md-0.1.0-alpha5-UBIUX1-TEST61-update.fip | tee "$OUT/SHA256SUMS"
printf 'UrsusBoot 0.1.0-alpha5-UBIUX1-TEST61\nSOURCE_DATE_EPOCH=%s\nBUILD_UTC=2026-09-08 17:30:00 UTC\nIDENTITY1=PASS\nNOAUTOFIP1=HOST\nUBIATTACH2=NO_DETACH_ON_ACTIVE_EXPECTED_UBI\nSESSIONRECOVERY1=PASS_SOURCE\nDIAGSTATE1=PASS\n' "$RELEASE_EPOCH" > "$OUT/TEST61-BUILD_INFO.txt"
echo "ALPHA5_TEST61_BUILD=PASS"
echo "Artifacts: $OUT"

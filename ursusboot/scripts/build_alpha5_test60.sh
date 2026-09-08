#!/bin/bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=${URSUS_BUILD_DIR:-"$ROOT/work/alpha5-test60-rebuild"}
SDK_BUNDLE="$ROOT/toolchains/openwrt-sdk-r35906/openwrt-sdk-r35906.tar.zst"
SOURCE_BUNDLE="$ROOT/ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-source.tar.zst"
CONFIG="$ROOT/ursusboot/configs/u-boot.TEST60.full.config"
DONOR="$ROOT/payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-FUDAN1-update.fip"
PATCH1="$ROOT/ursusboot/patches/130-webfailsafe-webreboot1.patch"
PATCH2="$ROOT/ursusboot/patches/140-test57-diagcap-resetnet1.patch"
PATCH3="$ROOT/ursusboot/patches/150-test58-buildid.patch"
PATCH4="$ROOT/ursusboot/patches/160-test59-corrective.patch"
PATCH5="$ROOT/ursusboot/patches/170-test60-configtrim1.patch"
OUT="$WORK/out"
RELEASE_EPOCH=1788879600  # 2026-09-08 15:00:00 UTC
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
python3 repack_persistent_fip.py "$DONOR" u-boot.lzma ursusboot-md-0.1.0-alpha5-UBIUX1-TEST60-update.fip
cp u-boot u-boot.bin u-boot.map u-boot.sym System.map u-boot.lzma ursusboot-md-0.1.0-alpha5-UBIUX1-TEST60-update.fip "$OUT/"
EXPECTED_RAW=4679214615c5b53d67173a31ff9203b834a880e9b1f407b10fcc9cda8e2d32d1
EXPECTED_LZMA=335d92d42b63677e2d471c675cdab3867a062380919a207e407c8b074df168a9
EXPECTED_FIP=c0e88d734a33a72ef0ca002860eaf7ff6c7fa7cc856de3f781371259d013d9bb
check(){ actual=$(sha256sum "$1"|awk '{print $1}'); [ "$actual" = "$2" ] || { echo "$3 SHA256 mismatch: $actual != $2" >&2; exit 1; }; echo "$3 SHA256 PASS: $actual"; }
check u-boot.bin "$EXPECTED_RAW" RAW
check u-boot.lzma "$EXPECTED_LZMA" LZMA
check ursusboot-md-0.1.0-alpha5-UBIUX1-TEST60-update.fip "$EXPECTED_FIP" FIP
sha256sum u-boot.bin u-boot.lzma ursusboot-md-0.1.0-alpha5-UBIUX1-TEST60-update.fip | tee "$OUT/SHA256SUMS"
printf 'UrsusBoot 0.1.0-alpha5-UBIUX1-TEST60\nSOURCE_DATE_EPOCH=%s\nBUILD_UTC=2026-09-08 15:00:00 UTC\n' "$RELEASE_EPOCH" > "$OUT/TEST60-BUILD_INFO.txt"
echo "ALPHA5_TEST60_BUILD=PASS"
echo "Artifacts: $OUT"

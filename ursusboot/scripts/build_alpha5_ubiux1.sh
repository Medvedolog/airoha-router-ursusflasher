#!/bin/bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=${URSUS_BUILD_DIR:-"$ROOT/work/alpha5-ubiux1-rebuild"}
SDK_BUNDLE="$ROOT/toolchains/openwrt-sdk-r35906/openwrt-sdk-r35906.tar.zst"
SOURCE_BUNDLE="$ROOT/ursusboot/source/ursusboot-0.1.0-alpha5-UBIUX1-source.tar.zst"
CONFIG="$ROOT/ursusboot/configs/u-boot.FUDAN1.full.config"
DONOR="$ROOT/payloads/md/ursusboot/ursusboot-md-0.1.0-alpha4-FUDAN1-update.fip"
OUT="$WORK/out"

EXPECTED_RAW=06397f68ba876e01ba6a07ebbdbbcfac1e5341b9d82926fd6b4a54ae1bf7e552
EXPECTED_LZMA=648fe1e12616068a99305645b34bee74d669ee9219f51c26ddd0b6b5003e0b1f
EXPECTED_FIP=548c446555231ee1b6ec4666000831226e0749c576d702c06dc5f501a6f510db

command -v tar >/dev/null
command -v make >/dev/null
command -v gcc >/dev/null
command -v perl >/dev/null
command -v python3 >/dev/null
command -v sha256sum >/dev/null

if [ ! -f "$SDK_BUNDLE" ]; then
  "$ROOT/toolchains/openwrt-sdk-r35906/reassemble-sdk.sh" >/dev/null
fi
EXPECTED_SDK=$(awk '{print $1}' "$ROOT/toolchains/openwrt-sdk-r35906/SDK_SHA256SUMS")
ACTUAL_SDK=$(sha256sum "$SDK_BUNDLE" | awk '{print $1}')
[ "$ACTUAL_SDK" = "$EXPECTED_SDK" ] || { echo "SDK SHA256 mismatch" >&2; exit 1; }

rm -rf "$WORK"
mkdir -p "$WORK/sdk" "$WORK/u-boot" "$OUT"
tar --zstd -xf "$SDK_BUNDLE" -C "$WORK/sdk"
tar --zstd -xf "$SOURCE_BUNDLE" -C "$WORK/u-boot"
SDK_ROOT=$(find "$WORK/sdk" -mindepth 1 -maxdepth 1 -type d -name 'openwrt-sdk-*' | head -n1)
[ -n "$SDK_ROOT" ] || { echo "SDK root not found" >&2; exit 1; }

TC="$SDK_ROOT/staging_dir/toolchain-aarch64_cortex-a53_gcc-14.4.0_musl/bin"
HOST="$SDK_ROOT/staging_dir/host"
export URSUS_SDK_ROOT="$SDK_ROOT"
export STAGING_DIR="$SDK_ROOT/staging_dir"
export STAGING_DIR_HOST="$HOST"
export BISON_PKGDATADIR="$HOST/share/bison"
export PATH="$ROOT/toolchains/hostshim:$TC:$HOST/bin:/usr/bin:/bin"
export CROSS_COMPILE=aarch64-openwrt-linux-musl-
export SOURCE_DATE_EPOCH=1788446468

cp "$CONFIG" "$WORK/u-boot/.config"
cd "$WORK/u-boot"
make olddefconfig
make -j"${JOBS:-$(nproc)}"

gcc -O2 -Wall -Wextra lzma1ext_noeopm.c -llzma -o "$WORK/lzma1ext_noeopm"
"$WORK/lzma1ext_noeopm" u-boot.bin u-boot.lzma 1048576
python3 repack_persistent_fip.py "$DONOR" u-boot.lzma ursusboot-md-0.1.0-alpha5-UBIUX1-update.fip

check() {
  local file=$1 expected=$2 label=$3
  local actual
  actual=$(sha256sum "$file" | awk '{print $1}')
  if [ "$actual" != "$expected" ]; then
    echo "$label SHA256 mismatch: $actual != $expected" >&2
    exit 1
  fi
  echo "$label SHA256 PASS: $actual"
}
check u-boot.bin "$EXPECTED_RAW" RAW
check u-boot.lzma "$EXPECTED_LZMA" LZMA
check ursusboot-md-0.1.0-alpha5-UBIUX1-update.fip "$EXPECTED_FIP" FIP

cp u-boot u-boot.bin u-boot.map u-boot.sym System.map u-boot.lzma \
   ursusboot-md-0.1.0-alpha5-UBIUX1-update.fip "$OUT/"
echo "ALPHA5_UBIUX1_REPRO_BUILD=PASS"
echo "Artifacts: $OUT"

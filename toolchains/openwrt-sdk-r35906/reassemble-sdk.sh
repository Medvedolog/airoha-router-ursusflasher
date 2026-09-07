#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OUT="$HERE/openwrt-sdk-r35906.tar.zst"
cat "$HERE"/parts/openwrt-sdk-r35906.tar.zst.part* > "$OUT"
EXPECTED=$(awk '{print $1}' "$HERE/SDK_SHA256SUMS")
ACTUAL=$(sha256sum "$OUT" | awk '{print $1}')
[ "$ACTUAL" = "$EXPECTED" ] || { echo "SDK SHA256 mismatch" >&2; rm -f "$OUT"; exit 1; }
echo "$OUT"

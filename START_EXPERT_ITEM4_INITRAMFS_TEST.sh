#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec python3 ursusflasher/src/expert_item4_initramfs_test.py "$@"

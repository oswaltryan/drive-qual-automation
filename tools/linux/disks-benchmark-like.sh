#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$ROOT_DIR/disks-benchmark-like.c"
BIN="$ROOT_DIR/.disks-benchmark-like-bin"

gcc -O2 -Wall -Wextra -std=c11 "$SRC" -o "$BIN"
exec "$BIN" "$@"

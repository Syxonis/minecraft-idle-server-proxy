#!/usr/bin/env bash
#
# Start script for Minecraft Idle Server Proxy.
# Intended for Crafty Controller or manual use.
#

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "[ERROR] Python was not found: $PYTHON_BIN" >&2
    exit 1
fi

exec "$PYTHON_BIN" -u "$SCRIPT_DIR/idle-server.py"
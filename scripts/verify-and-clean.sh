#!/usr/bin/env bash
# The Python verifier owns an explicit source manifest and finally-based cleanup.
set -euo pipefail
AEGIS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AEGIS_PYTHON="${AEGIS_PYTHON:-$AEGIS_ROOT/.venv/bin/python}"
exec "$AEGIS_PYTHON" "$AEGIS_ROOT/scripts/verify.py"

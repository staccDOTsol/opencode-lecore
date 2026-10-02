#!/usr/bin/env bash
set -euo pipefail

task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export LECORE_PYTHON="${LECORE_PYTHON:-$task_root/packages/lecore/.venv/bin/python}"
if [[ ! -x "$LECORE_PYTHON" ]]; then
  printf '%s\n' 'Run script/lecore-setup.sh first, or set LECORE_PYTHON to a Python runtime with NumPy.' >&2
  exit 1
fi

# Preserve the caller's project directory; source paths are absolute.
exec bun run "$task_root/packages/opencode/src/index.ts" "$@"

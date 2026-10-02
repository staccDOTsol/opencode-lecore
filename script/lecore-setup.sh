#!/usr/bin/env bash
set -euo pipefail

task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
task_venv="$task_root/packages/lecore/.venv"
cd "$task_root"
git submodule update --init vendor/lecore

if command -v uv >/dev/null 2>&1; then
  if [[ ! -x "$task_venv/bin/python" ]]; then
    uv venv --python 3.12 "$task_venv"
  fi
  uv pip install --python "$task_venv/bin/python" 'numpy==2.3.5'
else
  "${LECORE_BOOTSTRAP_PYTHON:-python3}" -c 'import sys; assert sys.version_info >= (3, 11), "lecore setup requires Python 3.11 or newer"'
  "${LECORE_BOOTSTRAP_PYTHON:-python3}" -m venv "$task_venv"
  "$task_venv/bin/python" -m pip install 'numpy==2.3.5'
fi

printf '%s\n' 'leCore runtime ready. Install OpenCode dependencies with bun install, then run script/lecore.sh.'

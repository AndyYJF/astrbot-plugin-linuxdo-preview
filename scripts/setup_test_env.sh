#!/usr/bin/env bash
set -euo pipefail

project='/c/Users/AndyYan/Desktop/codex/astrbot-plugin-linuxdo-preview'
bootstrap_python='/c/Users/AndyYan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
venv_python="$project/.venv/Scripts/python.exe"

if [[ ! -x "$venv_python" ]]; then
  "$bootstrap_python" -m venv "$project/.venv"
fi

"$venv_python" -m pip install --disable-pip-version-check \
  'aiohttp>=3.11.18' \
  'pytest>=8.4,<9' \
  'pytest-asyncio>=1.1,<2' \
  'ruff==0.15.22'

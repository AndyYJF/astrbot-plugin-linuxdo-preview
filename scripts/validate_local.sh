#!/usr/bin/env bash
set -euo pipefail

project='/c/Users/AndyYan/Desktop/codex/astrbot-plugin-linuxdo-preview'
python="$project/.venv/Scripts/python.exe"

cd "$project"
"$python" --version
"$python" -m compileall -q main.py linuxdo_preview tests
"$python" -m pytest -q
"$python" -m ruff check main.py linuxdo_preview tests

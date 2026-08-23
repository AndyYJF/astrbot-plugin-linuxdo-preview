#!/usr/bin/env bash
set -euo pipefail

project_dir='/c/Users/AndyYan/Desktop/codex/astrbot-plugin-linuxdo-preview'
python="$project_dir/.venv/Scripts/python.exe"

"$python" "$project_dir/scripts/project_audit.py"

#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -W)"
project="$(cd -- "$script_dir/.." && pwd -W)"
cd "$project"
version="$(sed -n 's/^version: //p' metadata.yaml)"
archive="dist/astrbot_plugin_linuxdo_preview-${version}.tar.gz"

mkdir -p dist
tar -czf "$archive" \
  --exclude='*/__pycache__' \
  --exclude='*.pyc' \
  --transform='s,^,astrbot_plugin_linuxdo_preview/,' \
  main.py metadata.yaml _conf_schema.json requirements.txt linuxdo_preview

printf '__SHA256__\n'
sha256sum "$archive"
printf '__ARCHIVE_CONTENTS__\n'
tar -tzf "$archive" | sort

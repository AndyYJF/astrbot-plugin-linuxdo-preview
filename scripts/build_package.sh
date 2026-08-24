#!/usr/bin/env bash
set -euo pipefail

project='/c/Users/AndyYan/Desktop/codex/astrbot-plugin-linuxdo-preview'
version="$(sed -n 's/^version: //p' "$project/metadata.yaml")"
archive="$project/dist/astrbot_plugin_linuxdo_preview-${version}.tar.gz"

mkdir -p "$project/dist"
cd "$project"
tar -czf "$archive" \
  --exclude='*/__pycache__' \
  --exclude='*.pyc' \
  --transform='s,^,astrbot_plugin_linuxdo_preview/,' \
  main.py metadata.yaml _conf_schema.json requirements.txt linuxdo_preview

printf '__SHA256__\n'
sha256sum "$archive"
printf '__ARCHIVE_CONTENTS__\n'
tar -tzf "$archive" | sort

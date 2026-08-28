#!/usr/bin/env bash
set -euo pipefail

attempts="${LINUXDO_X_DISPLAY_WAIT_ATTEMPTS:-100}"
interval_seconds="${LINUXDO_X_DISPLAY_WAIT_INTERVAL_SECONDS:-0.1}"

for attempt in $(seq 1 "$attempts"); do
  if xdotool getmouselocation --shell >/dev/null 2>&1; then
    printf 'X display is ready.\n'
    exit 0
  fi
  sleep "$interval_seconds"
done

printf 'X display did not become ready within the bounded wait.\n' >&2
exit 1

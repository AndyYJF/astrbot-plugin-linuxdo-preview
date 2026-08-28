#!/usr/bin/env bash
set -euo pipefail

case "${LINUXDO_ENTRYPOINT_MODULE:-sidecar.app}" in
  sidecar.app|sidecar.device_authorize|sidecar.session_authorize)
    exec /app/.venv/bin/python -m "${LINUXDO_ENTRYPOINT_MODULE:-sidecar.app}"
    ;;
  *)
    printf 'unsupported sidecar module\n' >&2
    exit 2
    ;;
esac

#!/usr/bin/env bash
set -euo pipefail

Xvfb :99 -screen 0 1280x900x24 -nolisten tcp &
fluxbox -display :99 &
x11vnc -display :99 -forever -shared -localhost -rfbport 5900 -nopw &
websockify --web=/usr/share/novnc 6080 localhost:5900 &

case "${LINUXDO_ENTRYPOINT_MODULE:-sidecar.app}" in
  sidecar.app|sidecar.device_authorize)
    exec python -m "${LINUXDO_ENTRYPOINT_MODULE:-sidecar.app}"
    ;;
  *)
    printf 'unsupported sidecar module\n' >&2
    exit 2
    ;;
esac

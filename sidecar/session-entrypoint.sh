#!/usr/bin/env bash
set -euo pipefail

export DISPLAY=:99

Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
xvfb_pid=$!
/opt/linuxdo-sidecar/sidecar/wait-for-x-display.sh
x11vnc -display :99 -localhost -nopw -forever -shared -rfbport 5900 &
x11vnc_pid=$!
websockify --web=/usr/share/novnc 0.0.0.0:6080 127.0.0.1:5900 &
websockify_pid=$!

fit_browser_window() {
  for attempt in $(seq 1 120); do
    window_ids="$(xdotool search --onlyvisible --class firefox 2>/dev/null || true)"
    if [[ -n "$window_ids" ]]; then
      for window_id in $window_ids; do
        xdotool windowmove --sync "$window_id" 0 0
        xdotool windowsize --sync "$window_id" 1920 1080
      done
      printf 'Firefox 登录窗口已约束到 1920x1080 虚拟屏幕。\n'
      return 0
    fi
    sleep 1
  done
  printf '未在限定时间内发现 Firefox 登录窗口。\n' >&2
}
fit_browser_window &
window_fit_pid=$!

cleanup() {
  kill "$window_fit_pid" "$websockify_pid" "$x11vnc_pid" "$xvfb_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

/app/.venv/bin/python -m sidecar.session_authorize

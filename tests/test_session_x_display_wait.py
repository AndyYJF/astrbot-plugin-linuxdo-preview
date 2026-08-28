from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_x_display_wait_retries_until_display_accepts_connections(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_xdotool = fake_bin / "xdotool"
    fake_xdotool.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
counter_file="${0%/*}/attempts"
count=0
if test -f "$counter_file"; then
  count="$(cat "$counter_file")"
fi
count=$((count + 1))
printf '%s\n' "$count" > "$counter_file"
test "$count" -ge 3
""",
        encoding="utf-8",
    )
    fake_xdotool.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
    env["LINUXDO_X_DISPLAY_WAIT_ATTEMPTS"] = "3"
    env["LINUXDO_X_DISPLAY_WAIT_INTERVAL_SECONDS"] = "0"

    result = subprocess.run(
        ["bash", "sidecar/wait-for-x-display.sh"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (fake_bin / "attempts").read_text(encoding="utf-8").strip() == "3"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_x_display_wait_fails_after_bounded_attempts(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_xdotool = fake_bin / "xdotool"
    fake_xdotool.write_text(
        """#!/usr/bin/env bash
exit 1
""",
        encoding="utf-8",
    )
    fake_xdotool.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
    env["LINUXDO_X_DISPLAY_WAIT_ATTEMPTS"] = "2"
    env["LINUXDO_X_DISPLAY_WAIT_INTERVAL_SECONDS"] = "0"

    result = subprocess.run(
        ["bash", "sidecar/wait-for-x-display.sh"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "X display did not become ready" in result.stderr

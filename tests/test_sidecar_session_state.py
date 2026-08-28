from __future__ import annotations

import json

import pytest

from sidecar.session_state import (
    SessionStateError,
    load_session_state,
    sanitize_session_state,
    validate_session_state,
    write_session_state,
)


def _state(domain: str = ".linux.do"):
    return {
        "cookies": [
            {
                "name": "_forum_session",
                "value": "opaque-secret-value",
                "domain": domain,
                "path": "/",
                "expires": -1,
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            }
        ],
        "origins": [
            {
                "origin": "https://linux.do",
                "localStorage": [{"name": "theme", "value": "light"}],
            }
        ],
    }


def test_session_state_accepts_only_linuxdo_storage():
    assert validate_session_state(_state())["cookies"][0]["domain"] == ".linux.do"
    with pytest.raises(SessionStateError, match="origin"):
        validate_session_state(_state(".example.com"))


def test_session_state_rejects_empty_or_extra_root_fields():
    with pytest.raises(SessionStateError):
        validate_session_state({"cookies": [], "origins": []})
    with pytest.raises(SessionStateError):
        validate_session_state({**_state(), "private": "leak"})


def test_session_state_writer_filters_third_party_login_storage():
    state = _state()
    state["cookies"].append(
        {
            **state["cookies"][0],
            "domain": ".identity.example",
        }
    )
    state["origins"].append(
        {
            "origin": "https://identity.example",
            "localStorage": [{"name": "third-party", "value": "secret"}],
        }
    )

    sanitized = sanitize_session_state(state)

    assert len(sanitized["cookies"]) == 1
    assert len(sanitized["origins"]) == 1
    assert "identity.example" not in json.dumps(sanitized)


def test_session_state_round_trip_uses_private_regular_file(tmp_path):
    path = tmp_path / "linuxdo-storage-state.json"

    write_session_state(str(path), _state())
    loaded = load_session_state(str(path))

    assert loaded["cookies"][0]["name"] == "_forum_session"
    assert json.loads(path.read_text(encoding="utf-8")) == loaded

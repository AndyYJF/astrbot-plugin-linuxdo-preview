#!/usr/bin/env python3
"""Device-code authorization for a read-only Linux.do User API Key."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .user_api_authorize import (
    APPLICATION_NAME,
    SITE,
    AuthorizationError,
    _decode_payload,
    _decrypt_payload,
    _require_absolute,
    _require_outside_project,
    _run_openssl,
    _write_plugin_secret,
    _write_private,
)

DEVICE_URL = f"{SITE}/user-api-key/device.json"
POLL_URL = f"{SITE}/user-api-key/device/poll.json"
MAX_HTTP_BYTES = 65_536


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _validate_proxy(proxy: str) -> str:
    candidate = proxy.strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise AuthorizationError("proxy must be an HTTP(S) URL without credentials")
    return candidate


def _post_json(
    url: str,
    payload: dict[str, object],
    *,
    proxy: str,
    timeout: int,
) -> dict[str, object]:
    proxy_handler = ProxyHandler(
        {"http": proxy, "https": proxy} if proxy else {}
    )
    opener = build_opener(proxy_handler, _NoRedirect())
    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "AstrBot-LinuxDo-Preview-Auth/0.7",
        },
        method="POST",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(MAX_HTTP_BYTES + 1)
            status = response.status
            headers = response.headers
    except HTTPError as exc:
        marker = str(exc.headers.get("cf-mitigated", "")).lower()
        if exc.code == 403 and marker == "challenge":
            raise AuthorizationError(
                "Cloudflare challenge blocked device authorization"
            ) from exc
        raise AuthorizationError(f"device authorization HTTP {exc.code}") from exc
    except (OSError, URLError, TimeoutError) as exc:
        raise AuthorizationError("device authorization network request failed") from exc
    if status != 200:
        raise AuthorizationError(f"device authorization HTTP {status}")
    if len(body) > MAX_HTTP_BYTES:
        raise AuthorizationError("device authorization response is too large")
    content_type = str(headers.get("content-type", "")).lower()
    if "json" not in content_type:
        raise AuthorizationError("device authorization response is not JSON")
    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorizationError("device authorization returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise AuthorizationError("device authorization response root is invalid")
    return result


def _validate_device_response(payload: dict[str, object]) -> dict[str, object]:
    device_code = payload.get("device_code")
    user_code = payload.get("user_code")
    verification_uri = payload.get("verification_uri")
    verification_with_request = payload.get("verification_uri_with_request")
    expires_in = payload.get("expires_in")
    interval = payload.get("interval")
    if (
        not isinstance(device_code, str)
        or len(device_code) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in device_code)
        or not isinstance(user_code, str)
        or not 4 <= len(user_code) <= 32
        or not isinstance(verification_uri, str)
        or not verification_uri.startswith(f"{SITE}/user-api-key/activate")
        or not isinstance(verification_with_request, str)
        or not verification_with_request.startswith(
            f"{SITE}/user-api-key/activate?"
        )
        or not isinstance(expires_in, int)
        or not 60 <= expires_in <= 3600
        or not isinstance(interval, int)
        or not 1 <= interval <= 30
    ):
        raise AuthorizationError("device authorization response fields are invalid")
    return payload


def _start(args: argparse.Namespace) -> None:
    work_root = _require_absolute(args.work_dir, label="work directory")
    _require_outside_project(work_root, label="work directory")
    work_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not work_root.is_dir() or work_root.is_symlink():
        raise AuthorizationError("work directory is invalid")
    if os.name == "posix":
        work_root.chmod(stat.S_IRWXU)
    proxy = _validate_proxy(args.proxy)

    session_dir = work_root / f"device-{secrets.token_hex(8)}"
    session_dir.mkdir(mode=0o700)
    private_key = session_dir / "private-key.pem"
    public_key = session_dir / "public-key.pem"
    state_file = session_dir / "state.json"
    try:
        _run_openssl(
            args.openssl,
            [
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:4096",
                "-out",
                str(private_key),
            ],
        )
        if os.name == "posix":
            private_key.chmod(stat.S_IRUSR | stat.S_IWUSR)
        _run_openssl(
            args.openssl,
            ["pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
        )
        client_id = secrets.token_hex(32)
        nonce = secrets.token_urlsafe(24)
        response = _validate_device_response(
            _post_json(
                DEVICE_URL,
                {
                    "application_name": APPLICATION_NAME,
                    "client_id": client_id,
                    "scopes": "read",
                    "public_key": public_key.read_text(encoding="ascii"),
                    "nonce": nonce,
                    "padding": "oaep",
                },
                proxy=proxy,
                timeout=args.timeout,
            )
        )
        state = {
            "version": 1,
            "flow": "device",
            "site": SITE,
            "client_id": client_id,
            "nonce": nonce,
            "private_key_file": str(private_key),
            "device_code": response["device_code"],
            "interval": response["interval"],
            "expires_in": response["expires_in"],
            "proxy": proxy,
        }
        _write_private(
            state_file,
            (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
    except Exception:
        state_file.unlink(missing_ok=True)
        public_key.unlink(missing_ok=True)
        private_key.unlink(missing_ok=True)
        session_dir.rmdir()
        raise
    public_key.unlink(missing_ok=False)

    print(f"授权会话目录：{session_dir}")
    print(f"浏览器授权地址：{response['verification_uri_with_request']}")
    print(f"核对码：{response['user_code']}")
    print("页面必须只显示 read/读取权限。批准后运行本工具的 poll 命令。")
    print("不要把地址、核对码、Cookie、密码或 API Key 粘贴到聊天。")


def _prepare_browser(args: argparse.Namespace) -> None:
    work_root = _require_absolute(args.work_dir, label="work directory")
    _require_outside_project(work_root, label="work directory")
    work_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not work_root.is_dir() or work_root.is_symlink():
        raise AuthorizationError("work directory is invalid")
    session_dir = work_root / f"device-browser-{secrets.token_hex(8)}"
    session_dir.mkdir(mode=0o700)
    private_key = session_dir / "private-key.pem"
    public_key = session_dir / "public-key.pem"
    state_file = session_dir / "state.json"
    request_file = session_dir / "device-request.json"
    try:
        _run_openssl(
            args.openssl,
            [
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:4096",
                "-out",
                str(private_key),
            ],
        )
        if os.name == "posix":
            private_key.chmod(stat.S_IRUSR | stat.S_IWUSR)
        _run_openssl(
            args.openssl,
            ["pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
        )
        client_id = secrets.token_hex(32)
        nonce = secrets.token_urlsafe(24)
        request_payload = {
            "application_name": APPLICATION_NAME,
            "client_id": client_id,
            "scopes": "read",
            "public_key": public_key.read_text(encoding="ascii"),
            "nonce": nonce,
            "padding": "oaep",
        }
        state = {
            "version": 1,
            "flow": "device-browser-prepared",
            "site": SITE,
            "client_id": client_id,
            "nonce": nonce,
            "private_key_file": str(private_key),
        }
        _write_private(
            state_file,
            (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        _write_private(
            request_file,
            (json.dumps(request_payload, ensure_ascii=False) + "\n").encode("utf-8"),
        )
    except Exception:
        request_file.unlink(missing_ok=True)
        state_file.unlink(missing_ok=True)
        public_key.unlink(missing_ok=True)
        private_key.unlink(missing_ok=True)
        session_dir.rmdir()
        raise
    public_key.unlink(missing_ok=False)
    print(f"浏览器授权会话目录：{session_dir}")
    print(f"同源设备请求文件：{request_file}")
    print("该文件只有临时公钥、nonce、client ID 和 read scope，不含账号材料。")


def _replace_private_json(path: Path, payload: dict[str, object]) -> None:
    replacement = path.with_name(f"{path.name}.new")
    replacement.unlink(missing_ok=True)
    _write_private(
        replacement,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    os.replace(replacement, path)


def _read_browser_response(
    args: argparse.Namespace,
    *,
    session_dir: Path,
    expected_name: str,
    prompt: str,
) -> tuple[dict[str, object], Path | None]:
    raw_response_file = str(getattr(args, "response_file", "") or "").strip()
    response_file: Path | None = None
    if raw_response_file:
        response_file = _require_absolute(
            raw_response_file,
            label="browser response file",
        )
        if (
            response_file.parent != session_dir
            or response_file.name != expected_name
            or response_file.is_symlink()
            or not response_file.is_file()
            or response_file.stat().st_size <= 0
            or response_file.stat().st_size > MAX_HTTP_BYTES
        ):
            raise AuthorizationError("browser response file is invalid")
        try:
            response = json.loads(response_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AuthorizationError("browser response is invalid JSON") from exc
    else:
        try:
            response = json.loads(input(prompt))
        except json.JSONDecodeError as exc:
            raise AuthorizationError("browser response is invalid JSON") from exc
    if not isinstance(response, dict):
        raise AuthorizationError("browser response root is invalid")
    return response, response_file


def _record_browser(args: argparse.Namespace) -> None:
    session_dir = _require_absolute(args.session_dir, label="session directory")
    state, _private_key = _load_state(
        session_dir,
        allowed_flows={"device-browser-prepared"},
    )
    response, response_file = _read_browser_response(
        args,
        session_dir=session_dir,
        expected_name="device-response.json",
        prompt="粘贴浏览器设备请求 JSON：\n",
    )
    response = _validate_device_response(response)
    state.update(
        flow="device-browser",
        device_code=response["device_code"],
        interval=response["interval"],
        expires_in=response["expires_in"],
    )
    poll_request = session_dir / "poll-request.json"
    if poll_request.exists() or poll_request.is_symlink():
        raise AuthorizationError("browser poll request already exists")
    _write_private(
        poll_request,
        (
            json.dumps({"device_code": response["device_code"]}) + "\n"
        ).encode("utf-8"),
    )
    try:
        _replace_private_json(session_dir / "state.json", state)
    except Exception:
        poll_request.unlink(missing_ok=True)
        raise
    if response_file is not None:
        response_file.unlink(missing_ok=False)
    print(f"浏览器授权地址：{response['verification_uri_with_request']}")
    print(f"核对码：{response['user_code']}")


def _complete_browser(args: argparse.Namespace) -> None:
    session_dir = _require_absolute(args.session_dir, label="session directory")
    output_file = _require_absolute(args.output, label="secret output")
    _require_outside_project(output_file, label="secret output")
    if output_file.exists() or output_file.is_symlink():
        raise AuthorizationError("secret output already exists")
    if not output_file.parent.is_dir() or output_file.parent.is_symlink():
        raise AuthorizationError("secret output parent is invalid")
    state, private_key = _load_state(
        session_dir,
        allowed_flows={"device-browser"},
    )
    response, response_file = _read_browser_response(
        args,
        session_dir=session_dir,
        expected_name="poll-response.json",
        prompt="粘贴浏览器设备轮询 JSON：\n",
    )
    if (
        response.get("status") != "authorized"
        or not isinstance(response.get("payload"), str)
    ):
        raise AuthorizationError("browser poll is not authorized")
    payload = _decrypt_payload(
        encrypted=_decode_payload(response["payload"]),
        private_key=private_key,
        session_dir=session_dir,
        openssl=args.openssl,
    )
    fingerprint = _write_plugin_secret(
        output_file=output_file,
        payload=payload,
        expected_nonce=str(state["nonce"]),
        client_id=str(state["client_id"]),
    )
    private_key.unlink(missing_ok=False)
    (session_dir / "state.json").unlink(missing_ok=False)
    (session_dir / "device-request.json").unlink(missing_ok=True)
    (session_dir / "poll-request.json").unlink(missing_ok=True)
    if response_file is not None:
        response_file.unlink(missing_ok=False)
    print(f"只读 secret 已写入：{output_file}")
    print(f"Key 指纹：sha256:{fingerprint}")
    print("密钥正文未输出。")


def _load_state(
    session_dir: Path,
    *,
    allowed_flows: set[str] | None = None,
) -> tuple[dict[str, object], Path]:
    state_file = session_dir / "state.json"
    if state_file.is_symlink() or not state_file.is_file():
        raise AuthorizationError("device authorization state is missing")
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorizationError("device authorization state is invalid") from exc
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or state.get("flow") not in (allowed_flows or {"device"})
        or state.get("site") != SITE
        or not isinstance(state.get("nonce"), str)
        or not isinstance(state.get("client_id"), str)
    ):
        raise AuthorizationError("device authorization state metadata is invalid")
    if state.get("flow") != "device-browser-prepared" and not isinstance(
        state.get("device_code"), str
    ):
        raise AuthorizationError("device authorization code is missing")
    private_key = Path(str(state.get("private_key_file", "")))
    if (
        not private_key.is_absolute()
        or private_key.parent != session_dir
        or private_key.name != "private-key.pem"
        or private_key.is_symlink()
        or not private_key.is_file()
    ):
        raise AuthorizationError("device authorization private key is invalid")
    return state, private_key


def _poll(args: argparse.Namespace) -> None:
    session_dir = _require_absolute(args.session_dir, label="session directory")
    output_file = _require_absolute(args.output, label="secret output")
    _require_outside_project(output_file, label="secret output")
    if output_file.exists() or output_file.is_symlink():
        raise AuthorizationError("secret output already exists")
    if not output_file.parent.is_dir() or output_file.parent.is_symlink():
        raise AuthorizationError("secret output parent is invalid")
    state, private_key = _load_state(session_dir)
    proxy = _validate_proxy(str(state.get("proxy", "")))
    interval = max(1, min(30, int(state.get("interval", 5))))
    deadline = time.monotonic() + max(1, min(args.wait_seconds, 600))

    while True:
        response = _post_json(
            POLL_URL,
            {"device_code": state["device_code"]},
            proxy=proxy,
            timeout=args.timeout,
        )
        status = response.get("status")
        if status == "authorization_pending":
            if time.monotonic() + interval > deadline:
                raise AuthorizationError("authorization is still pending")
            time.sleep(interval)
            continue
        if status == "access_denied":
            raise AuthorizationError("authorization was denied")
        if status == "expired_token":
            raise AuthorizationError("authorization expired; start a new session")
        if status != "authorized" or not isinstance(response.get("payload"), str):
            raise AuthorizationError("device poll response is invalid")
        encrypted = _decode_payload(response["payload"])
        break

    payload = _decrypt_payload(
        encrypted=encrypted,
        private_key=private_key,
        session_dir=session_dir,
        openssl=args.openssl,
    )
    fingerprint = _write_plugin_secret(
        output_file=output_file,
        payload=payload,
        expected_nonce=str(state["nonce"]),
        client_id=str(state["client_id"]),
    )
    private_key.unlink(missing_ok=False)
    (session_dir / "state.json").unlink(missing_ok=False)
    print(f"只读 secret 已写入：{output_file}")
    print(f"Key 指纹：sha256:{fingerprint}")
    print("密钥正文未输出；不再使用时请在 Linux.do 的 Apps 中撤销。")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Authorize a Linux.do read-only User API Key by device code.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--work-dir", required=True)
    start.add_argument("--proxy", default="")
    start.add_argument("--timeout", type=int, default=20)
    start.add_argument("--openssl", default="openssl")
    start.set_defaults(handler=_start)
    poll = subparsers.add_parser("poll")
    poll.add_argument("--session-dir", required=True)
    poll.add_argument("--output", required=True)
    poll.add_argument("--wait-seconds", type=int, default=90)
    poll.add_argument("--timeout", type=int, default=20)
    poll.add_argument("--openssl", default="openssl")
    poll.set_defaults(handler=_poll)
    prepare_browser = subparsers.add_parser("prepare-browser")
    prepare_browser.add_argument("--work-dir", required=True)
    prepare_browser.add_argument("--openssl", default="openssl")
    prepare_browser.set_defaults(handler=_prepare_browser)
    record_browser = subparsers.add_parser("record-browser")
    record_browser.add_argument("--session-dir", required=True)
    record_browser.add_argument("--response-file", default="")
    record_browser.set_defaults(handler=_record_browser)
    complete_browser = subparsers.add_parser("complete-browser")
    complete_browser.add_argument("--session-dir", required=True)
    complete_browser.add_argument("--output", required=True)
    complete_browser.add_argument("--response-file", default="")
    complete_browser.add_argument("--openssl", default="openssl")
    complete_browser.set_defaults(handler=_complete_browser)
    return parser


def main() -> int:
    try:
        args = _parser().parse_args()
        args.handler(args)
    except AuthorizationError as exc:
        print(f"设备授权失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

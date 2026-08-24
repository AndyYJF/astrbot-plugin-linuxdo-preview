#!/usr/bin/env python3
"""Create and complete a read-only Discourse User API Key authorization.

The helper never prints the returned API key. ``start`` creates an ephemeral RSA
keypair and a browser authorization URL. ``complete`` reads the encrypted
redirect URL from stdin, verifies its nonce, writes the versioned plugin secret,
and removes the ephemeral private material after a successful write.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

SITE = "https://linux.do"
DEFAULT_REDIRECT = "discourse://auth_redirect"
APPLICATION_NAME = "AstrBot LINUX DO Preview"
MAX_REDIRECT_CHARS = 16_384
MAX_PLAINTEXT_BYTES = 8_192
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AuthorizationError(RuntimeError):
    pass


def _require_absolute(path_text: str, *, label: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        raise AuthorizationError(f"{label} must be an absolute path")
    return path


def _require_outside_project(path: Path, *, label: str) -> None:
    resolved = path.resolve(strict=False)
    if resolved == PROJECT_ROOT or PROJECT_ROOT in resolved.parents:
        raise AuthorizationError(f"{label} must be outside the Git project")


def _run_openssl(openssl: str, arguments: list[str]) -> None:
    try:
        completed = subprocess.run(
            [openssl, *arguments],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise AuthorizationError("OpenSSL could not be started") from exc
    if completed.returncode != 0:
        raise AuthorizationError("OpenSSL operation failed")


def _write_private(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb", closefd=True) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if os.name == "posix":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _build_authorization_url(
    *,
    public_key: str,
    client_id: str,
    nonce: str,
    auth_redirect: str,
) -> str:
    query = urlencode(
        {
            "application_name": APPLICATION_NAME,
            "client_id": client_id,
            "scopes": "read",
            "public_key": public_key,
            "nonce": nonce,
            "auth_redirect": auth_redirect,
            "padding": "oaep",
        }
    )
    return f"{SITE}/user-api-key/new?{query}"


def _redirect_base(value: str) -> str:
    parsed = urlparse(value)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _decode_payload(value: str) -> bytes:
    if len(value) > MAX_REDIRECT_CHARS:
        raise AuthorizationError("encrypted payload is too large")
    encoded = value.strip()
    encoded += "=" * (-len(encoded) % 4)
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            decoded = decoder(encoded.encode("ascii"))
        except (UnicodeEncodeError, ValueError):
            continue
        if decoded:
            return decoded
    raise AuthorizationError("encrypted payload is not valid base64")


def _parse_redirect_payload(redirect_url: str, expected_redirect: str) -> bytes:
    candidate = redirect_url.strip()
    if not candidate or len(candidate) > MAX_REDIRECT_CHARS:
        raise AuthorizationError("redirect URL is empty or too large")
    if _redirect_base(candidate) != _redirect_base(expected_redirect):
        raise AuthorizationError("redirect URL destination does not match")
    values = parse_qs(urlparse(candidate).query, keep_blank_values=False)
    payload_values = values.get("payload", [])
    if len(payload_values) != 1:
        raise AuthorizationError("redirect URL must contain one payload")
    return _decode_payload(payload_values[0])


def _start(args: argparse.Namespace) -> None:
    work_root = _require_absolute(args.work_dir, label="work directory")
    _require_outside_project(work_root, label="work directory")
    work_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not work_root.is_dir() or work_root.is_symlink():
        raise AuthorizationError("work directory is not a regular directory")
    if os.name == "posix":
        work_root.chmod(stat.S_IRWXU)

    session_dir = work_root / f"pending-{secrets.token_hex(8)}"
    session_dir.mkdir(mode=0o700)
    private_key = session_dir / "private-key.pem"
    public_key = session_dir / "public-key.pem"
    state_file = session_dir / "state.json"
    authorization_file = session_dir / "authorize.url.txt"

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
    public_text = public_key.read_text(encoding="ascii")
    authorization_url = _build_authorization_url(
        public_key=public_text,
        client_id=client_id,
        nonce=nonce,
        auth_redirect=args.auth_redirect,
    )
    state = {
        "version": 1,
        "site": SITE,
        "client_id": client_id,
        "nonce": nonce,
        "auth_redirect": args.auth_redirect,
        "private_key_file": str(private_key),
    }
    _write_private(
        state_file,
        (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    _write_private(authorization_file, (authorization_url + "\n").encode("utf-8"))

    public_key.unlink(missing_ok=False)
    print(f"授权会话目录：{session_dir}")
    print(f"授权链接文件：{authorization_file}")
    print("请在已登录 Linux.do 的浏览器中打开该链接，只批准 read 权限。")
    print("完成后复制 discourse://auth_redirect?... 的完整地址，并运行 complete。")
    print("不要把 Cookie、密码、回调地址或 API Key 粘贴到聊天。")


def _load_state(session_dir: Path) -> tuple[dict[str, str], Path]:
    state_file = session_dir / "state.json"
    if state_file.is_symlink() or not state_file.is_file():
        raise AuthorizationError("authorization state file is missing")
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorizationError("authorization state is invalid") from exc
    required = {
        "site",
        "client_id",
        "nonce",
        "auth_redirect",
        "private_key_file",
    }
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or state.get("site") != SITE
        or not required.issubset(state)
        or any(not isinstance(state[key], str) for key in required)
    ):
        raise AuthorizationError("authorization state metadata is invalid")
    private_key = Path(state["private_key_file"])
    if (
        not private_key.is_absolute()
        or private_key.parent != session_dir
        or private_key.name != "private-key.pem"
        or private_key.is_symlink()
        or not private_key.is_file()
    ):
        raise AuthorizationError("authorization private key path is invalid")
    return state, private_key


def _complete(args: argparse.Namespace) -> None:
    session_dir = _require_absolute(args.session_dir, label="session directory")
    output_file = _require_absolute(args.output, label="secret output")
    _require_outside_project(output_file, label="secret output")
    if output_file.exists() or output_file.is_symlink():
        raise AuthorizationError("secret output already exists")
    if not output_file.parent.is_dir() or output_file.parent.is_symlink():
        raise AuthorizationError("secret output parent is invalid")

    state, private_key = _load_state(session_dir)
    redirect_url = input("粘贴完整加密回调地址（输入不会写入项目文件）：\n").strip()
    encrypted = _parse_redirect_payload(redirect_url, state["auth_redirect"])

    payload = _decrypt_payload(
        encrypted=encrypted,
        private_key=private_key,
        session_dir=session_dir,
        openssl=args.openssl,
    )
    fingerprint = _write_plugin_secret(
        output_file=output_file,
        payload=payload,
        expected_nonce=state["nonce"],
        client_id=state["client_id"],
    )

    private_key.unlink(missing_ok=False)
    (session_dir / "state.json").unlink(missing_ok=False)
    print(f"只读 secret 已写入：{output_file}")
    print(f"Key 指纹：sha256:{fingerprint}")
    print("密钥正文未输出；授权失败或不再使用时请在 Linux.do 的 Apps 中撤销。")


def _decrypt_payload(
    *,
    encrypted: bytes,
    private_key: Path,
    session_dir: Path,
    openssl: str,
) -> dict[str, object]:
    encrypted_file = session_dir / "payload.bin"
    plaintext_file = session_dir / "payload.json"
    _write_private(encrypted_file, encrypted)
    try:
        _run_openssl(
            openssl,
            [
                "pkeyutl",
                "-decrypt",
                "-inkey",
                str(private_key),
                "-pkeyopt",
                "rsa_padding_mode:oaep",
                "-pkeyopt",
                "rsa_oaep_md:sha1",
                "-pkeyopt",
                "rsa_mgf1_md:sha1",
                "-in",
                str(encrypted_file),
                "-out",
                str(plaintext_file),
            ],
        )
        if plaintext_file.stat().st_size > MAX_PLAINTEXT_BYTES:
            raise AuthorizationError("decrypted payload is too large")
        try:
            payload = json.loads(plaintext_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AuthorizationError("decrypted payload is invalid") from exc
        if not isinstance(payload, dict):
            raise AuthorizationError("decrypted payload root is invalid")
        return payload
    finally:
        plaintext_file.unlink(missing_ok=True)
        encrypted_file.unlink(missing_ok=True)


def _write_plugin_secret(
    *,
    output_file: Path,
    payload: dict[str, object],
    expected_nonce: str,
    client_id: str,
) -> str:
    if payload.get("nonce") != expected_nonce:
        raise AuthorizationError("authorization nonce does not match")
    key = payload.get("key")
    if not isinstance(key, str) or not 20 <= len(key) <= 512:
        raise AuthorizationError("authorization payload omitted the API key")
    secret_payload = {
        "version": 1,
        "site": SITE,
        "user_api_key": key,
        "user_api_client_id": client_id,
        "sidecar_token": secrets.token_urlsafe(32),
    }
    _write_private(
        output_file,
        (json.dumps(secret_payload, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        ),
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a read-only Linux.do Discourse User API Key secret.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="create an authorization URL")
    start.add_argument("--work-dir", required=True)
    start.add_argument("--auth-redirect", default=DEFAULT_REDIRECT)
    start.add_argument("--openssl", default="openssl")
    start.set_defaults(handler=_start)

    complete = subparsers.add_parser("complete", help="decrypt the callback")
    complete.add_argument("--session-dir", required=True)
    complete.add_argument("--output", required=True)
    complete.add_argument("--openssl", default="openssl")
    complete.set_defaults(handler=_complete)
    return parser


def main() -> int:
    try:
        args = _parser().parse_args()
        args.handler(args)
    except AuthorizationError as exc:
        print(f"授权助手失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Regression for server-side revocation of signed JIEJING sessions."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-session-revocation-test"
SAAS_DB = OUT / "saas.sqlite"
RUNTIME_DB = OUT / "runtime.sqlite"


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(SAAS_DB),
            "--runtime-db",
            str(RUNTIME_DB),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        if not _wait_for_health(base_url):
            return _fail("backend did not become healthy")
        registered = _request_json(
            f"{base_url}/auth/register",
            payload={
                "email": "session-revocation@example.test",
                "password": "session-revocation-password",
                "company_name": "Session Revocation Test",
            },
        )
        old_token = str(registered.get("token") or "")
        if not old_token or not _request_json(f"{base_url}/me", token=old_token).get("user"):
            return _fail("newly issued session should authenticate")
        logout = _request_json(f"{base_url}/auth/logout", token=old_token, payload={})
        if logout.get("ok") is not True or logout.get("session_revoked") is not True:
            return _fail(f"logout should revoke the current server session: {logout}")
        old_status, old_body = _request_json_error(f"{base_url}/me", token=old_token)
        if old_status != 401 or "revoked" not in str(old_body.get("error") or ""):
            return _fail(f"revoked bearer token must stop working immediately: {old_status}, {old_body}")
        login = _request_json(
            f"{base_url}/auth/login",
            payload={"email": "session-revocation@example.test", "password": "session-revocation-password"},
        )
        new_token = str(login.get("token") or "")
        if not new_token or new_token == old_token:
            return _fail("new login must issue an independent session")
        if not _request_json(f"{base_url}/me", token=new_token).get("user"):
            return _fail("new session should remain valid after old-session revocation")
        print("PASS jiejing_session_revocation")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def _wait_for_health(base_url: str) -> bool:
    for _ in range(80):
        try:
            if _request_json(f"{base_url}/health").get("status") == "ok":
                return True
        except Exception:
            time.sleep(0.1)
    return False


def _request_json(
    url: str,
    *,
    token: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    method = "GET"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_json_error(url: str, *, token: str) -> tuple[int, dict[str, Any]]:
    try:
        return 200, _request_json(url, token=token)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}


if __name__ == "__main__":
    raise SystemExit(main())

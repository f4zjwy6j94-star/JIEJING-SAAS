#!/usr/bin/env python3
"""HTTP contract for short access cookies and rotating refresh cookies."""

from __future__ import annotations

import json
import io
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import redirect_stderr
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import SaaSBackendHandler


OUT = ROOT / "output" / "jiejing-rotating-browser-session-http-test"


def refresh_same_browser_session(
    base_url: str, refresh_token: str, *, current_session_ref: str, expected_count: int
) -> tuple[str, str]:
    """Renew the three-second fixture without creating or replacing a device family."""
    status, body, headers = request_json(
        f"{base_url}/auth/refresh",
        cookies={"jiejing_saas_refresh": refresh_token},
        forwarded_https=True,
        payload={},
    )
    if status != 200 or body != {"ok": True, "session_refreshed": True, "secret_exposed": False}:
        raise AssertionError("current device refresh must succeed with the fixed value-free response")
    cookies = response_cookies(headers)
    access = str((cookies.get("jiejing_saas_session") or {}).value or "")
    next_refresh = str((cookies.get("jiejing_saas_refresh") or {}).value or "")
    if not access or not next_refresh or next_refresh == refresh_token:
        raise AssertionError("current device refresh must rotate both usable browser cookies")
    inventory_status, inventory, _ = request_json(
        f"{base_url}/auth/sessions", cookies={"jiejing_saas_session": access}
    )
    sessions = inventory.get("sessions") if isinstance(inventory.get("sessions"), list) else []
    current = [item for item in sessions if item.get("current") is True]
    if (
        inventory_status != 200
        or len(sessions) != expected_count
        or len(current) != 1
        or not current_session_ref
        or current[0].get("session_ref") != current_session_ref
    ):
        raise AssertionError("refresh must preserve the exact current device family and inventory count")
    return access, next_refresh


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    env = os.environ.copy()
    env["JIEJING_SAAS_SESSION_TTL_SECONDS"] = "3"
    env["JIEJING_SAAS_REFRESH_TTL_SECONDS"] = "3600"
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(OUT / "saas.sqlite"),
            "--runtime-db",
            str(OUT / "runtime.sqlite"),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        if not _wait_for_health(base_url):
            return fail("backend did not become healthy")
        status, registered, headers = request_json(
            f"{base_url}/auth/register",
            payload={
                "email": "rotating-http@example.test",
                "password": "rotating-http-password",
                "company_name": "Rotating HTTP Contract",
            },
            forwarded_https=True,
        )
        if status != 201:
            return fail(f"registration failed: {status}, {registered}")
        cookies = response_cookies(headers)
        access_cookie = cookies.get("jiejing_saas_session")
        refresh_cookie = cookies.get("jiejing_saas_refresh")
        if access_cookie is None or refresh_cookie is None:
            return fail(f"login must issue access and refresh cookies: {headers.get_all('Set-Cookie')}")
        if not access_cookie["httponly"] or not access_cookie["secure"] or access_cookie["samesite"].lower() != "lax":
            return fail("access cookie must be HttpOnly, Secure and SameSite=Lax")
        if int(access_cookie["max-age"] or 0) > 1800:
            return fail("access cookie must be short-lived")
        if not refresh_cookie["httponly"] or not refresh_cookie["secure"] or refresh_cookie["samesite"].lower() != "strict":
            return fail("refresh cookie must be HttpOnly, Secure and SameSite=Strict")
        if refresh_cookie["path"] != "/auth":
            return fail("refresh cookie must match the public /auth route exactly")
        refresh_token = str(refresh_cookie.value or "")
        access_token = str(registered.get("token") or "")
        if not refresh_token or refresh_token in json.dumps(registered, ensure_ascii=False):
            return fail("refresh token must stay out of JSON")

        time.sleep(4)
        expired_status, _expired, _ = request_json(f"{base_url}/me", token=access_token)
        if expired_status != 401:
            return fail(f"short access token must expire: status={expired_status}")
        refresh_status, refreshed, refresh_headers = request_json(
            f"{base_url}/auth/refresh",
            cookies={"jiejing_saas_refresh": refresh_token},
            forwarded_https=True,
            payload={},
        )
        if refresh_status != 200 or refreshed != {
            "ok": True,
            "session_refreshed": True,
            "secret_exposed": False,
        }:
            return fail(f"refresh response must be fixed and value-free: {refresh_status}, {refreshed}")
        rotated_cookies = response_cookies(refresh_headers)
        next_refresh = str((rotated_cookies.get("jiejing_saas_refresh") or {}).value or "")
        if not next_refresh or next_refresh == refresh_token:
            return fail("refresh must rotate the HttpOnly refresh cookie")
        next_access = str((rotated_cookies.get("jiejing_saas_session") or {}).value or "")
        me_status, me, _ = request_json(f"{base_url}/me", cookies={"jiejing_saas_session": next_access})
        if me_status != 200 or not isinstance(me.get("user"), dict):
            return fail("rotated access cookie must restore the authenticated session")

        replay_status, replay, replay_headers = request_json(
            f"{base_url}/auth/refresh",
            cookies={"jiejing_saas_refresh": refresh_token},
            forwarded_https=True,
            payload={},
        )
        if replay_status != 401 or str(replay.get("error") or "") != "session_refresh_replay_blocked":
            return fail(f"refresh replay must revoke the family: {replay_status}, {replay}")
        if any(refresh_token in value or next_refresh in value for value in replay_headers.get_all("Set-Cookie", [])):
            return fail("replay response must not echo a refresh token")
        revoked_status, _revoked, _ = request_json(
            f"{base_url}/me",
            cookies={"jiejing_saas_session": next_access},
        )
        if revoked_status != 401:
            return fail("family replay must revoke the newly issued access cookie")

        login_a_status, login_a, login_a_headers = request_json(
            f"{base_url}/auth/login",
            payload={"email": "rotating-http@example.test", "password": "rotating-http-password"},
            forwarded_https=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/140.0",
        )
        login_b_status, login_b, login_b_headers = request_json(
            f"{base_url}/auth/login",
            payload={"email": "rotating-http@example.test", "password": "rotating-http-password"},
            forwarded_https=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0) Edg/140.0",
        )
        if login_a_status != 200 or login_b_status != 200:
            return fail("two independent device logins must succeed")
        cookies_a = response_cookies(login_a_headers)
        cookies_b = response_cookies(login_b_headers)
        access_a = str((cookies_a.get("jiejing_saas_session") or {}).value or "")
        refresh_a = str((cookies_a.get("jiejing_saas_refresh") or {}).value or "")
        access_b = str((cookies_b.get("jiejing_saas_session") or {}).value or "")
        refresh_b = str((cookies_b.get("jiejing_saas_refresh") or {}).value or "")
        sessions_status, sessions_body, _ = request_json(
            f"{base_url}/auth/sessions",
            cookies={"jiejing_saas_session": access_a},
        )
        sessions = sessions_body.get("sessions") if isinstance(sessions_body.get("sessions"), list) else []
        if sessions_status != 200 or len(sessions) != 2:
            return fail(f"device inventory must show the two active sessions: {sessions_status}, {sessions_body}")
        serialized_sessions = json.dumps(sessions, ensure_ascii=False).lower()
        for forbidden in ("token", "hash", "cookie", "user_agent", "ip_address", "company_id", "user_id"):
            if forbidden in serialized_sessions:
                return fail(f"device inventory leaked forbidden field: {forbidden}")
        edge_sessions = [item for item in sessions if item.get("device_label") == "Edge · Windows"]
        current_sessions = [item for item in sessions if item.get("current") is True]
        if len(edge_sessions) != 1:
            return fail(f"device inventory must expose only a fixed device label: {sessions}")
        if len(current_sessions) != 1:
            return fail(f"device inventory must identify exactly one current session: {sessions}")
        other_status, _other, other_headers = request_json(
            f"{base_url}/auth/register",
            payload={
                "email": "rotating-http-other@example.test",
                "password": "rotating-http-other-password",
                "company_name": "Other Tenant",
            },
            forwarded_https=True,
        )
        other_access = str((response_cookies(other_headers).get("jiejing_saas_session") or {}).value or "")
        cross_status, cross_body, _ = request_json(
            f"{base_url}/auth/sessions/{current_sessions[0].get('session_ref')}/revoke",
            cookies={"jiejing_saas_session": other_access},
            payload={},
        )
        if other_status != 201 or cross_status != 404 or cross_body.get("error") != "session_revoke_not_allowed":
            return fail(f"cross-tenant session revocation must fail without existence disclosure: {cross_status}, {cross_body}")
        # Account setup is unrelated to this exact-device revoke assertion and
        # can consume the deliberately short access lifetime on a loaded host.
        access_a, refresh_a = refresh_same_browser_session(
            base_url, refresh_a,
            current_session_ref=str(current_sessions[0].get("session_ref") or ""), expected_count=2,
        )
        revoke_status, revoke_body, _ = request_json(
            f"{base_url}/auth/sessions/{edge_sessions[0].get('session_ref')}/revoke",
            cookies={"jiejing_saas_session": access_a},
            payload={},
        )
        if revoke_status != 200 or revoke_body.get("session_revoked") is not True:
            return fail(f"current user must be able to revoke one exact other device: {revoke_status}, {revoke_body}")
        b_access_status, _b_access, _ = request_json(
            f"{base_url}/me",
            cookies={"jiejing_saas_session": access_b},
        )
        b_refresh_status, _b_refresh, _ = request_json(
            f"{base_url}/auth/refresh",
            cookies={"jiejing_saas_refresh": refresh_b},
            forwarded_https=True,
            payload={},
        )
        # A successful refresh of A's same family also proves B's revocation
        # did not revoke A; do not substitute a fresh login for this check.
        access_a, refresh_a = refresh_same_browser_session(
            base_url, refresh_a,
            current_session_ref=str(current_sessions[0].get("session_ref") or ""), expected_count=1,
        )
        a_access_status, _a_access, _ = request_json(
            f"{base_url}/me",
            cookies={"jiejing_saas_session": access_a},
        )
        if (b_access_status, b_refresh_status, a_access_status) != (401, 401, 200):
            return fail(
                "exact device revocation must stop that device only: "
                f"B access={b_access_status}, B refresh={b_refresh_status}, A access={a_access_status}"
            )
        logout_status, _logout_login, logout_login_headers = request_json(
            f"{base_url}/auth/login",
            payload={"email": "rotating-http@example.test", "password": "rotating-http-password"},
            forwarded_https=True,
        )
        logout_cookies = response_cookies(logout_login_headers)
        logout_access = str((logout_cookies.get("jiejing_saas_session") or {}).value or "")
        logout_refresh = str((logout_cookies.get("jiejing_saas_refresh") or {}).value or "")
        if logout_status != 200 or not logout_access or not logout_refresh:
            return fail("logout-expiry fixture must create a complete browser session")
        time.sleep(4)
        logout_result_status, logout_result, _ = request_json(
            f"{base_url}/auth/logout",
            cookies={
                "jiejing_saas_session": logout_access,
                "jiejing_saas_refresh": logout_refresh,
            },
            forwarded_https=True,
            payload={},
        )
        after_logout_refresh_status, _after_logout_refresh, _ = request_json(
            f"{base_url}/auth/refresh",
            cookies={"jiejing_saas_refresh": logout_refresh},
            forwarded_https=True,
            payload={},
        )
        if logout_result_status != 200 or logout_result.get("session_revoked") is not True or after_logout_refresh_status != 401:
            return fail("logout must revoke the refresh family even after the access cookie expires")
        if not access_log_redacts_session_ref():
            return fail("access log must normalize browser session references and discard query values")
        print("PASS jiejing_rotating_browser_session_http")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def request_json(
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str = "",
    cookies: dict[str, str] | None = None,
    forwarded_https: bool = False,
    user_agent: str = "",
) -> tuple[int, dict[str, Any], Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if cookies:
        headers["Cookie"] = "; ".join(f"{name}={value}" for name, value in cookies.items())
    if forwarded_https:
        headers["X-Forwarded-Proto"] = "https"
    if user_agent:
        headers["User-Agent"] = user_agent
    data = None
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=20)
    except urllib.error.HTTPError as exc:
        response = exc
    body = response.read().decode("utf-8")
    return int(response.status), json.loads(body) if body else {}, response.headers


def response_cookies(headers: Any) -> SimpleCookie[str]:
    cookies: SimpleCookie[str] = SimpleCookie()
    for header in headers.get_all("Set-Cookie", []):
        cookies.load(header)
    return cookies


def access_log_redacts_session_ref() -> bool:
    sentinel = "SENTINEL-BROWSER-SESSION-REF"
    handler = object.__new__(SaaSBackendHandler)
    handler.path = f"/auth/sessions/{sentinel}/revoke?refresh_token=SENTINEL-QUERY"
    handler.command = "POST"
    handler.settings = type("Settings", (), {"is_production_like": True})()
    captured = io.StringIO()
    with redirect_stderr(captured):
        handler.log_message('"POST %s HTTP/1.1" %s %s', handler.path, "200", "0")
    value = captured.getvalue()
    return sentinel not in value and "SENTINEL-QUERY" not in value and "/auth/sessions/:session_ref/revoke" in value


def _wait_for_health(base_url: str) -> bool:
    for _ in range(100):
        try:
            status, body, _ = request_json(f"{base_url}/health")
            if status == 200 and body.get("status") == "ok":
                return True
        except Exception:
            time.sleep(0.1)
    return False


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

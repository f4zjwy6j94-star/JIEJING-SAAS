#!/usr/bin/env python3
"""Exercise the product-grade journey's production HttpOnly session contract."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SESSION_COOKIE = "jiejing_saas_session=opaque-session-cookie-sentinel"


class Handler(BaseHTTPRequestHandler):
    requests: list[dict[str, str]] = []

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers.get("content-length") or 0))
        self.requests.append(
            {
                "path": self.path,
                "cookie": str(self.headers.get("cookie") or ""),
                "authorization": str(self.headers.get("authorization") or ""),
            }
        )
        if self.path == "/auth/register":
            self._json(
                201,
                {
                    "token_returned_to_frontend": False,
                    "user": {
                        "user_id": "cookie-user",
                        "default_company_id": "cookie-company",
                    },
                    "company": {"company_id": "cookie-company"},
                    "secret_exposed": False,
                },
                set_cookie=f"{SESSION_COOKIE}; Path=/; HttpOnly; SameSite=Lax",
            )
            return
        if self.headers.get("cookie") != SESSION_COOKIE or self.headers.get("authorization"):
            self._json(401, {"error": "missing backend session cookie"})
            return
        if self.path == "/billing/test-event":
            self._json(200, {"billing_test_event": {"status": "activated"}})
            return
        if self.path == "/stores":
            self._json(201, {"store": {"store_id": "cookie-store"}})
            return
        self._json(404, {"error": "not found"})

    def _json(self, status: int, body: dict[str, object], *, set_cookie: str = "") -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        if set_cookie:
            self.send_header("set-cookie", set_cookie)
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = {
            **os.environ,
            "JIEJING_TEST_BASE": f"http://127.0.0.1:{server.server_port}",
            "JIEJING_AUTH_SESSION_SMOKE_ONLY": "true",
        }
        completed = subprocess.run(
            ["node", "tools/codex_jiejing_ai_ceo_market_listing_bridge_smoke.js"],
            cwd=ROOT,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    if completed.returncode != 0:
        raise AssertionError(completed.stdout + completed.stderr)
    result = json.loads(completed.stdout)
    if result != {
        "ok": True,
        "status": "backend_session_cookie_ready",
        "session_cookie_used": True,
        "token_returned_to_frontend": False,
        "real_platform_writes_enabled": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "secret_exposed": False,
    }:
        raise AssertionError(f"unexpected value-free result: {result}")
    if [item["path"] for item in Handler.requests] != [
        "/auth/register",
        "/billing/test-event",
        "/stores",
    ]:
        raise AssertionError(f"unexpected request sequence: {Handler.requests}")
    if Handler.requests[0]["cookie"] or Handler.requests[0]["authorization"]:
        raise AssertionError("registration must not send a pre-existing credential")
    if any(item["cookie"] != SESSION_COOKIE or item["authorization"] for item in Handler.requests[1:]):
        raise AssertionError("protected setup calls must use only the backend-owned session cookie")
    combined = completed.stdout + completed.stderr
    if "opaque-session-cookie-sentinel" in combined:
        raise AssertionError("session cookie leaked into the smoke output")
    print("PASS jiejing_product_grade_journey_session_cookie")


if __name__ == "__main__":
    main()

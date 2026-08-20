#!/usr/bin/env python3
"""Static security contract for rotating browser sessions in the merchant UI."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    ops = (ROOT / "ops.js").read_text(encoding="utf-8")
    required = (
        "let saasBrowserSessionRefreshPromise = null;",
        "function saasRequestCanRetryAfterSessionRefresh(path, options = {})",
        "method === \"GET\" || method === \"HEAD\"",
        "async function refreshSaasBrowserSession()",
        'const SAAS_BROWSER_SESSION_REFRESH_LOCK = "jiejing-browser-session-refresh-v1";',
        "const SAAS_BROWSER_SESSION_REFRESH_TIMEOUT_MS = 10000;",
        "controller.abort()",
        "navigator.locks.request(SAAS_BROWSER_SESSION_REFRESH_LOCK",
        'saasBrowserSessionRefreshFetch(`${state.saasApiBase}/me`',
        'saasBrowserSessionRefreshFetch(`${state.saasApiBase}/auth/refresh`',
        "saasBrowserSessionRefreshPromise",
        "saasRequestRetriedAfterRefresh",
        "saasBrowserSessions: [],",
        'optionalSaasFetchFast("/auth/sessions"',
        "const saasBrowserSessionButtonBindings = new WeakMap();",
        "function renderSaasBrowserSessionsPanel()",
        "function bindSaasBrowserSessionControls(root)",
        "saasBrowserSessionButtonBindings.set(button, sessionRef)",
        "async function revokeSaasBrowserSession(button)",
    )
    for marker in required:
        if marker not in app:
            return fail(f"missing rotating browser session UI marker: {marker}")
    forbidden = (
        "data-session-ref=",
        "data-session-id=",
        "dataset.sessionRef",
        "dataset.sessionId",
        "localStorage.setItem(saasStorageKeys.browserSessions",
        "sessionStorage.setItem(saasStorageKeys.browserSessions",
    )
    for marker in forbidden:
        if marker in app:
            return fail(f"browser session reference must not enter DOM or storage: {marker}")
    ops_required = (
        'const OPS_BROWSER_SESSION_REFRESH_LOCK = "jiejing-browser-session-refresh-v1";',
        "const OPS_BROWSER_SESSION_REFRESH_TIMEOUT_MS = 10000;",
        "let opsBrowserSessionRefreshPromise = null;",
        "function opsRequestCanRetryAfterSessionRefresh(path, options = {})",
        'navigator.locks.request(OPS_BROWSER_SESSION_REFRESH_LOCK',
        'opsBrowserSessionRefreshFetch("/permissions/me"',
        'opsBrowserSessionRefreshFetch("/auth/refresh"',
        "opsRequestRetriedAfterRefresh",
    )
    for marker in ops_required:
        if marker not in ops:
            return fail(f"missing operations rotating session marker: {marker}")
    if "localStorage" in ops or "sessionStorage" in ops:
        return fail("operations session state must stay in HttpOnly cookies and request-local memory")
    print("PASS jiejing_frontend_rotating_browser_sessions")
    return 0


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

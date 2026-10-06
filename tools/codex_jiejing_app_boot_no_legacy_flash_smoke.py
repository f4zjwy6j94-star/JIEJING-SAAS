from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright


LEGACY_MARKERS = ("旅行压缩收纳袋", "第一条商品自动化板")
STATIC_FILES = {
    "app.html",
    "index.html",
    "app.js",
    "styles.css",
    "privacy.html",
    "terms.html",
    "refund-policy.html",
    "support.html",
    "risk-disclosure.html",
}


def api_json(base_url: str, path: str, *, token: str = "", method: str = "GET", body=None) -> dict:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0 Codex Jiejing Boot Smoke",
            **({"authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8", errors="replace")
            return {"ok": 200 <= response.status < 300, "status": response.status, "json": json.loads(text or "{}")}
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(text or "{}")
        except json.JSONDecodeError:
            data = {"raw": text[:500]}
        return {"ok": False, "status": error.code, "json": data}


def make_smoke_session(base_url: str) -> dict:
    suffix = f"{int(time.time() * 1000)}"
    email = f"codex-boot-{suffix}@local.invalid"
    password = f"Codex-boot-{suffix}"
    registered = api_json(
        base_url,
        "/auth/register",
        method="POST",
        body={"email": email, "password": password, "company_name": "Codex Boot Smoke"},
    )
    if not registered["ok"]:
        raise RuntimeError(f"register failed: {registered['status']} {json.dumps(registered['json'])[:300]}")
    token = registered["json"].get("token") or ""
    user = registered["json"].get("user") or {}
    company = registered["json"].get("company") or {}
    created = api_json(
        base_url,
        "/stores",
        token=token,
        method="POST",
        body={
            "platform": "ebay",
            "store_name": "Codex Boot Smoke Store",
            "marketplace": "EBAY_US",
            "stage": "store_opened",
            "settings": {"created_from": "codex_app_boot_smoke", "placeholder_store_name": True},
        },
    )
    if not created["ok"]:
        raise RuntimeError(f"store create failed: {created['status']} {json.dumps(created['json'])[:300]}")
    return {
        "token": token,
        "email": email,
        "user_id": user.get("user_id") or "",
        "company_id": company.get("company_id") or user.get("default_company_id") or "",
        "store_id": (created["json"].get("store") or {}).get("store_id") or "",
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Verify app direct-start routes do not flash the legacy entry shell."
    )
    parser.add_argument(
        "--url",
        default="https://app.jiejing.shop/app.html?start=app&view=cockpit&onboarded=1",
    )
    parser.add_argument(
        "--local-static-root",
        default=str(Path(__file__).resolve().parent.parent),
        help="Serve public-host frontend requests from this local worktree without contacting production.",
    )
    parser.add_argument(
        "--backend-base",
        default="",
        help="Explicit backend base for --auth-smoke-session. Omit for the read-only public-login smoke.",
    )
    parser.add_argument("--delay-ms", type=int, default=2500)
    parser.add_argument(
        "--screenshot",
        default="C:/Users/57249/AppData/Local/Temp/jiejing-app-boot-no-legacy-flash.png",
    )
    parser.add_argument(
        "--session-hint",
        action="store_true",
        help="Seed the browser as an already-started Jiejing account before page scripts run.",
    )
    parser.add_argument(
        "--allow-auth-redirect",
        action="store_true",
        help="Allow the final state to return to public login when the smoke has no real backend session.",
    )
    parser.add_argument(
        "--auth-smoke-session",
        action="store_true",
        help="Create a temporary staging account and verify the logged-in workbench boot path.",
    )
    args = parser.parse_args()

    delayed = {"value": False}
    console_logs: list[dict[str, str]] = []
    page_origin = urllib.parse.urljoin(args.url, "/")
    static_root = Path(args.local_static_root).resolve()
    backend_base = args.backend_base.strip().rstrip("/")
    if args.auth_smoke_session and not backend_base:
        raise RuntimeError("--auth-smoke-session requires an explicit --backend-base")
    session = make_smoke_session(backend_base) if args.auth_smoke_session else None

    def serve_local_frontend(route, *, block_app_js: bool = False):
        request_url = urllib.parse.urlparse(route.request.url)
        relative_path = urllib.parse.unquote(request_url.path).lstrip("/") or "index.html"
        if relative_path not in STATIC_FILES and not relative_path.startswith("assets/"):
            route.fulfill(status=204, body=b"")
            return
        file_path = (static_root / relative_path).resolve()
        try:
            file_path.relative_to(static_root)
        except ValueError:
            route.abort()
            return
        if not file_path.is_file():
            route.abort()
            return
        if relative_path == "app.js" and block_app_js:
            delayed["value"] = True
            route.fulfill(status=200, content_type="text/javascript; charset=utf-8", body=b"")
            return
        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        route.fulfill(
            status=200,
            content_type=f"{mime_type}; charset=utf-8" if mime_type.startswith("text/") else mime_type,
            headers={"cache-control": "no-store"},
            body=file_path.read_bytes(),
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        if session:
            host = urllib.parse.urlparse(page_origin).hostname or ""
            context.add_cookies(
                [
                    {
                        "name": "jiejing_saas_session",
                        "value": session["token"],
                        "domain": host,
                        "path": "/",
                        "httpOnly": True,
                        "secure": page_origin.startswith("https://"),
                        "sameSite": "Lax",
                    }
                ]
            )
        if args.session_hint:
            context.add_init_script(
                """
                try {
                  localStorage.setItem("jiejing_saas_backend_session_hint", "1");
                  localStorage.setItem("jiejing_saas_last_account", "owner");
                  localStorage.setItem("jiejing_saas_onboarding_done:owner", "1");
                } catch (error) {}
                """
            )
        if session:
            session_payload = json.dumps({**session, "base": backend_base})
            context.add_init_script(
                """
                (() => {
                  const session = __SESSION_PAYLOAD__;
                  try {
                    const accountKey = String(session.user_id || session.email || "codex").toLowerCase();
                    localStorage.setItem("jiejing_saas_api_base", session.base);
                    localStorage.setItem("jiejing_saas_backend_store_id", session.store_id);
                    localStorage.setItem("jiejing_saas_backend_session_hint", "1");
                    localStorage.setItem("jiejing_saas_session_hint", "1");
                    localStorage.setItem("jiejing_saas_last_account", accountKey);
                    localStorage.setItem(`jiejing_saas_onboarding_done:${accountKey}`, "1");
                    window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
                  } catch (error) {}
                })();
                """.replace("__SESSION_PAYLOAD__", session_payload),
            )
        early_page = context.new_page()
        early_page.on(
            "console",
            lambda msg: console_logs.append({"type": msg.type, "text": msg.text})
            if msg.type in {"error", "warning"}
            else None,
        )
        early_page.route(
            f"{page_origin.rstrip('/')}/**",
            lambda route, _request: serve_local_frontend(route, block_app_js=True),
        )
        early_page.goto(args.url, wait_until="domcontentloaded")
        early_page.wait_for_timeout(min(max(args.delay_ms, 0), 500))
        early = inspect_page(early_page)
        screenshot_path = Path(args.screenshot)
        early_screenshot_path = screenshot_path.with_name(
            f"{screenshot_path.stem}.early{screenshot_path.suffix}"
        )
        early_page.screenshot(path=str(early_screenshot_path), full_page=False)
        early_page.close()

        page = context.new_page()
        page.on(
            "console",
            lambda msg: console_logs.append({"type": msg.type, "text": msg.text})
            if msg.type in {"error", "warning"}
            else None,
        )
        page.route(
            f"{page_origin.rstrip('/')}/**",
            lambda route, _request: serve_local_frontend(route),
        )
        page.goto(args.url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        page.wait_for_timeout(500)
        final = inspect_page(page)
        page.screenshot(path=str(screenshot_path), full_page=False)
        context.close()
        browser.close()

    ignored_static_server_errors = ("Unsupported method", "ERR_CONNECTION_REFUSED")
    ignored_auth_redirect_errors = ("401",) if args.allow_auth_redirect else ()
    relevant_logs = [
        log
        for log in console_logs
        if not any(marker in log["text"] for marker in ignored_static_server_errors)
        and not any(marker in log["text"] for marker in ignored_auth_redirect_errors)
    ]
    final_auth_redirect_ok = (
        args.allow_auth_redirect
        and not final["appVisible"]
        and "index.html" in final["url"]
        and not final["entryVisible"]
    )
    early_auth_redirect_ok = (
        args.allow_auth_redirect
        and not early["appVisible"]
        and "index.html" in early["url"]
        and not early["entryVisible"]
    )
    ok = (
        delayed["value"]
        and not early["entryVisible"]
        and not early["hasLegacyIntroText"]
        and (early["loadingVisible"] or early_auth_redirect_ok)
        and not early["appVisible"]
        and (
            (
                session
                and final["appVisible"]
                and not final["entryVisible"]
                and not final["hasLegacyIntroText"]
            )
            or (not session and (final["loadingVisible"] or final_auth_redirect_ok))
        )
        and not relevant_logs
    )
    print(
        json.dumps(
            {
                "ok": ok,
                "delayed": delayed["value"],
                "early": early,
                "final": final,
                "finalAuthRedirectOk": final_auth_redirect_ok,
                "relevantLogs": relevant_logs,
                "earlyScreenshot": str(early_screenshot_path),
                "screenshot": str(screenshot_path),
                "session": (
                    {
                        "email_masked": session["email"].replace(session["email"][2 : session["email"].find("@")], "***"),
                        "store_id": session["store_id"],
                    }
                    if session
                    else None
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


def inspect_page(page):
    return page.evaluate(
        """
        (legacyMarkers) => {
          const visible = (el) =>
            !!el &&
            getComputedStyle(el).display !== "none" &&
            getComputedStyle(el).visibility !== "hidden" &&
            el.getClientRects().length > 0;
          const text = document.body.innerText || "";
          return {
            url: window.location.href,
            htmlClass: document.documentElement.className,
            entryVisible: visible(document.querySelector("#entryShell")),
            loadingVisible: visible(document.querySelector("#appBootLoading")),
            appVisible: visible(document.querySelector("#appShell")),
            hasLegacyIntroText: legacyMarkers.some((marker) => text.includes(marker)),
            hasWorkbenchText: text.includes("AI CEO") && text.includes("Listing"),
            visibleText: text.slice(0, 500),
          };
        }
        """,
        list(LEGACY_MARKERS),
    )


if __name__ == "__main__":
    raise SystemExit(main())

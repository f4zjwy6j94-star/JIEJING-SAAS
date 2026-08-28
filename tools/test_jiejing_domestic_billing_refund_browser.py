#!/usr/bin/env python3
"""Browser regression for the merchant-visible approved refund closure."""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_domestic import request_domestic_billing_refund_review  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-domestic-billing-refund-browser-test"
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


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    env["JIEJING_SAAS_ENV"] = "test"
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
        if not _wait_for_health(base):
            return _fail("browser refund backend did not become healthy")
        account = _request_json(
            base,
            "/auth/register",
            method="POST",
            body={
                "email": "refund-browser-owner@example.test",
                "password": "Refund-browser-owner-2026",
                "company_name": "Refund Browser Test",
            },
        )
        token = str(account.get("token") or "")
        user = account.get("user") if isinstance(account.get("user"), dict) else {}
        company = account.get("company") if isinstance(account.get("company"), dict) else {}
        user_id = str(user.get("user_id") or "")
        company_id = str(company.get("company_id") or user.get("default_company_id") or "")
        if not token or not user_id or not company_id:
            return _fail("browser refund fixture did not receive a complete test session")
        store = _request_json(
            base,
            "/stores",
            token=token,
            method="POST",
            body={
                "platform": "ebay",
                "store_name": "Refund Browser Store",
                "marketplace": "EBAY_US",
                "stage": "store_opened",
                "settings": {"created_from": "refund_browser_regression", "placeholder_store_name": True},
            },
        ).get("store", {})
        store_id = str(store.get("store_id") or "")
        if not store_id:
            return _fail("browser refund fixture could not create its test store")

        order_id = "domestic_refund_browser_approved"
        repository = SaaSRepository(OUT / "saas.sqlite")
        repository.create_domestic_billing_order_record(
            order_id=order_id,
            company_id=company_id,
            user_id=user_id,
            provider="wechat_pay_native",
            plan_key="starter",
            amount_minor=9900,
            currency="CNY",
            duration_days=30,
            status="pending_payment",
            idempotency_key_hash="e" * 64,
            order={"provider_mode": "refund_browser_regression"},
        )
        repository.mark_domestic_billing_order_paid(
            company_id=company_id,
            order_id=order_id,
            provider_order_id="wx-paid-refund-browser",
            paid_at="2026-08-28T00:00:00+00:00",
            payment={"signature_verified": True, "amount_verified": True},
        )
        review = request_domestic_billing_refund_review(
            repository,
            company_id=company_id,
            user_id=user_id,
            order_id=order_id,
            reason="Browser regression verifies the explicit refund boundary.",
        )
        confirmation_id = str(review.get("confirmation_id") or "")
        if not confirmation_id:
            return _fail(f"browser refund fixture did not create a confirmation: {review}")
        repository.decide_confirmation(
            company_id=company_id,
            confirmation_id=confirmation_id,
            decision="approve",
            decided_by=user_id,
            note="Browser regression approval only; provider execution remains separate.",
        )

        result = _inspect_browser(
            base=base,
            token=token,
            email=str(user.get("email") or "refund-browser-owner@example.test"),
            user_id=user_id,
            store_id=store_id,
            order_id=order_id,
        )
        (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if not result.get("ok"):
            return _fail(f"browser refund closure failed: {result}")
        print("PASS jiejing_domestic_billing_refund_browser")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _inspect_browser(*, base: str, token: str, email: str, user_id: str, store_id: str, order_id: str) -> dict[str, Any]:
    page_errors: list[str] = []
    screenshots: list[str] = []
    checks: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 960})
        context.add_cookies(
            [
                {
                    "name": "jiejing_saas_session",
                    "value": token,
                    "domain": "127.0.0.1",
                    "path": "/",
                    "httpOnly": True,
                    "secure": False,
                    "sameSite": "Lax",
                }
            ]
        )
        session_payload = json.dumps({"userId": user_id, "email": email, "storeId": store_id, "base": base})
        context.add_init_script(
            """
            (() => {
              const { userId, email, storeId, base } = __SESSION_PAYLOAD__;
              const accountKeys = [userId, email].map((value) => String(value || "").trim().toLowerCase()).filter(Boolean);
              accountKeys.forEach((key) => localStorage.setItem(`jiejing_saas_onboarding_done:${key}`, "1"));
              localStorage.setItem("jiejing_saas_api_base", base);
              localStorage.setItem("jiejing_saas_backend_store_id", storeId);
              localStorage.setItem("jiejing_saas_backend_session_hint", "1");
              localStorage.setItem("jiejing_saas_last_account", accountKeys[0] || "browser");
              window.__JIEJING_FORCE_PUBLIC_MVP__ = true;
            })();
            """.replace("__SESSION_PAYLOAD__", session_payload),
        )
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route(f"{base}/**", _serve_local_frontend)
        page.goto(f"{base}/app.html?start=app&view=confirm&onboarded=1", wait_until="domcontentloaded")
        try:
            page.wait_for_selector("#appShell", state="visible", timeout=30000)
        except Exception:
            failure_screenshot = OUT / "app-shell-timeout.png"
            page.screenshot(path=str(failure_screenshot), full_page=True)
            return {
                "ok": False,
                "checks": [],
                "page_errors": page_errors,
                "screenshots": [str(failure_screenshot)],
                "diagnostic": page.evaluate(
                    """() => ({
                      url: location.href,
                      title: document.title,
                      body: (document.body?.innerText || "").slice(0, 800),
                      app_shell_exists: Boolean(document.querySelector("#appShell")),
                      app_shell_display: document.querySelector("#appShell") ? getComputedStyle(document.querySelector("#appShell")).display : "missing",
                      html_class: document.documentElement.className,
                    })"""
                ),
                "real_refund_performed": False,
            }
        page.locator('.nav-item[data-view="confirm"]').click()
        page.wait_for_selector(
            f'[data-saas-action="domestic-billing-refund-execute"][data-domestic-order-id="{order_id}"]',
            state="visible",
            timeout=30000,
        )
        checks.append(_capture(page, "desktop-confirm", screenshots))
        page.locator('.nav-item[data-view="connect"]').click()
        page.wait_for_selector('.saas-settings-clean-nav [data-saas-settings-tab="billing"]', state="visible")
        page.locator('.saas-settings-clean-nav [data-saas-settings-tab="billing"]').click()
        page.wait_for_selector(
            f'[data-saas-action="domestic-billing-refund-execute"][data-domestic-order-id="{order_id}"]',
            state="visible",
        )
        checks.append(_capture(page, "desktop-billing", screenshots))
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator('.nav-item[data-view="confirm"]').click()
        page.wait_for_selector(
            f'[data-saas-action="domestic-billing-refund-execute"][data-domestic-order-id="{order_id}"]',
            state="visible",
        )
        checks.append(_capture(page, "mobile-confirm", screenshots))
        page.locator('.nav-item[data-view="connect"]').click()
        page.locator('.saas-settings-clean-nav [data-saas-settings-tab="billing"]').click()
        page.wait_for_selector(
            f'[data-saas-action="domestic-billing-refund-execute"][data-domestic-order-id="{order_id}"]',
            state="visible",
        )
        checks.append(_capture(page, "mobile-billing", screenshots))
        browser.close()
    ok = not page_errors and all(
        check.get("execute_button_visible") is True
        and check.get("horizontal_overflow") is False
        and check.get("internal_copy_visible") is False
        and check.get("account_refund_inherits_listing_copy") is False
        for check in checks
    )
    return {"ok": ok, "checks": checks, "page_errors": page_errors, "screenshots": screenshots, "real_refund_performed": False}


def _capture(page, label: str, screenshots: list[str]) -> dict[str, Any]:
    screenshot = OUT / f"{label}.png"
    page.screenshot(path=str(screenshot), full_page=True)
    screenshots.append(str(screenshot))
    return page.evaluate(
        """
        ({ label }) => {
          const button = Array.from(document.querySelectorAll('[data-saas-action="domestic-billing-refund-execute"]'))
            .find((item) => item.getClientRects().length > 0);
          const text = document.body.innerText || "";
          const actionCardText = button?.closest("article")?.innerText || "";
          return {
            label,
            execute_button_visible: Boolean(button),
            horizontal_overflow: document.documentElement.scrollWidth > window.innerWidth + 2,
            internal_copy_visible: ["client_secret", "api_v3_key", "主理人", "内部验收"].some((marker) => text.includes(marker)),
            account_refund_inherits_listing_copy: actionCardText.includes("eBay 店铺资料还没有指定 SKU"),
            viewport_width: window.innerWidth,
            document_width: document.documentElement.scrollWidth,
          };
        }
        """,
        {"label": label},
    )


def _serve_local_frontend(route) -> None:
    request_url = urllib.parse.urlparse(route.request.url)
    relative_path = urllib.parse.unquote(request_url.path).lstrip("/") or "index.html"
    if relative_path not in STATIC_FILES and not relative_path.startswith("assets/"):
        route.continue_()
        return
    file_path = (ROOT / relative_path).resolve()
    try:
        file_path.relative_to(ROOT)
    except ValueError:
        route.abort()
        return
    if not file_path.is_file():
        route.abort()
        return
    mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    route.fulfill(
        status=200,
        content_type=f"{mime_type}; charset=utf-8" if mime_type.startswith("text/") else mime_type,
        headers={"cache-control": "no-store"},
        body=file_path.read_bytes(),
    )


def _request_json(base: str, path: str, *, token: str = "", method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 Jiejing Refund Browser Test"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base}{path}",
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for_health(base: str) -> bool:
    for _ in range(100):
        try:
            if _request_json(base, "/health").get("status") == "ok":
                return True
        except Exception:
            time.sleep(0.1)
    return False


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

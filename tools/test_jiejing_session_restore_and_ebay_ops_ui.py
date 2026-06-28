#!/usr/bin/env python3
"""Regression checks for Jiejing session restore and eBay operations UI."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    index_html = (ROOT / "index.html").read_text(encoding="utf-8")
    api_server = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    security = (ROOT / "jiejing_saas" / "security.py").read_text(encoding="utf-8")

    for marker in [
        "SESSION_COOKIE_NAME = \"jiejing_saas_session\"",
        "headers=[(\"set-cookie\", self._session_cookie_header(token))]",
        "def _session_cookie_token(self) -> str:",
        "missing bearer token or session cookie",
        "auth/logout",
        "_expired_session_cookie_header",
    ]:
        if marker not in api_server:
            return fail(f"backend missing persistent session cookie marker: {marker}")

    for marker in [
        "JIEJING_SAAS_SESSION_TTL_SECONDS",
        "60 * 60 * 24 * 7",
    ]:
        if marker not in security:
            return fail(f"session ttl should support longer merchant login restore: {marker}")

    for marker in [
        "credentials: options.credentials || \"include\"",
        "sessionHint: \"jiejing_saas_backend_session_hint\"",
        "protectedSnapshot: \"jiejing_saas_protected_snapshot\"",
        "hydrateSaasProtectedStateFromCache()",
        "saveSaasProtectedStateSnapshot()",
        "state.saasProtectedStateFromCache",
        "viewId === \"cockpit\" && hasSaasProtectedSessionCandidate()",
        "hasSaasPersistentSessionHint()",
        "state.saasToken || hasSaasPersistentSessionHint()",
        "localStorage.setItem(saasStorageKeys.sessionHint, \"1\")",
        "localStorage.removeItem(saasStorageKeys.sessionHint)",
    ]:
        if marker not in app_js:
            return fail(f"frontend missing cookie/session restore marker: {marker}")

    for marker in [
        "var sessionHint = localStorage.getItem(\"jiejing_saas_backend_session_hint\") === \"1\"",
        "isPublic && !sessionHint",
        "var browserOnboardingDone = !isPublic && localStorage.getItem(\"jiejing_saas_onboarding_done:browser\") === \"1\"",
        "const browserOnboardingDone = !isPublic && localStorage.getItem(\"jiejing_saas_onboarding_done:browser\") === \"1\"",
        "if (!onboardingDone) return;",
    ]:
        if marker not in app_html:
            return fail(f"app shell should restore persistent merchant session before redirect: {marker}")

    if "localStorage.getItem(\"jiejing_saas_backend_token\")" in app_html:
        return fail("app shell must not accept localStorage bearer tokens in public staging")
    if "sessionStorage.getItem(\"jiejing_saas_backend_token\")" in app_html:
        return fail("app shell must not accept sessionStorage bearer tokens in public staging")
    if "explicitOnboarded ||" in app_html:
        return fail("app shell must not let onboarded=1 bypass account-scoped onboarding completion")
    if "params.get(\"onboarded\") === \"1\") return true" in app_js:
        return fail("app route guard must not let onboarded=1 bypass account-scoped onboarding completion")

    for marker in [
        "!(isSaasPublicMvpMode() && key === `${saasStorageKeys.onboardingDone}:browser`)",
        "if (isSaasPublicMvpMode() && !shouldOpenSaasAppRoute(params))",
        "if (!shouldOpenSaasAppRoute(params))",
    ]:
        if marker not in app_js:
            return fail(f"frontend should not let browser-level onboarding state bypass public account onboarding: {marker}")

    for marker in [
        "localStorage.setItem(\"jiejing_saas_backend_session_hint\", \"1\")",
    ]:
        if marker not in index_html:
            return fail(f"entry login should persist merchant session across browser restarts: {marker}")

    if "includeCompany: true" in app_js or "登录进入向导" in app_js or "注册并进入向导" in app_js:
        return fail("login should not ask for company/store name or route repeated users back to onboarding copy")

    for marker in [
        "const saasAuthorizedConnectionStatuses = new Set([\"read_only_authorized\", \"publish_authorized\", \"authorized\", \"connected\"])",
        "isSaasAuthorizedConnectionStatus(connection?.status)",
        "saasStoreDisplayName(store, connection)",
        "renderSaasEbayOperationsSnapshotPanel",
        "inventory_and_offers",
        "orders_and_fulfillment",
        "account_business_policies",
        "finances",
        "eBay 真实货架 / 订单",
    ]:
        if marker not in app_js:
            return fail(f"frontend missing authorized restore or eBay operations marker: {marker}")

    print("PASS jiejing_session_restore_and_ebay_ops_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

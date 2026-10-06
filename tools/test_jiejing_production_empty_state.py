#!/usr/bin/env python3
"""Merchant production shell must fail closed to a real empty state."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")

    merchant_bundle = f"{app_html}\n{app_js}"
    for marker in ("northvalesource", "US 主店", "UK 测试店", "AU 二店"):
        if marker.lower() in merchant_bundle.lower():
            return fail(f"merchant bundle contains a fixed merchant, store, or product: {marker}")

    chat = re.search(r'<div class="chat-log" id="ceoChat">(.*?)</div>\s*<form', app_html, re.DOTALL)
    if not chat:
        return fail("AI CEO chat hook is missing")
    if 'class="message ' in chat.group(1):
        return fail("static AI CEO chat must not preload a merchant conversation")

    service = re.search(r'<div class="service-kpi-grid" id="serviceKpiGrid">(.*?)</div>', app_html, re.DOTALL)
    if not service:
        return fail("service KPI hook is missing")
    if re.search(r"<strong>\s*(?:\d+|退款\s*/\s*重发)\s*</strong>", service.group(1)):
        return fail("static service page must not preload fake KPIs")

    for marker in (
        '<strong id="pendingCount">—</strong>',
        '<strong id="taskProgress">—</strong>',
        '<strong id="profitMetric">待设置</strong>',
        '<span class="pill neutral">等待商品资料</span>',
    ):
        if marker not in app_html:
            return fail(f"static workbench does not fail closed: {marker}")
    cockpit_start = app_html.index('<section class="view is-active" id="view-cockpit"')
    cockpit_end = app_html.index('<section class="view" id="view-product"', cockpit_start)
    if re.search(r'<i style="width:\s*[1-9]\d*%"', app_html[cockpit_start:cockpit_end]):
        return fail("static workbench preloads a fake market score")

    for marker in (
        'activeStore: ""',
        'activeProject: ""',
        'activeListingDraft: ""',
        'activeCockpitMarketDraft: ""',
    ):
        if marker not in app_js:
            return fail(f"production empty-state default is missing: {marker}")

    if "productionMerchantSeedData" in app_js:
        return fail("merchant seed data is still runtime-hidden instead of physically removed")

    for collection in (
        "stores",
        "tasks",
        "agents",
        "productListingDrafts",
        "bulkListingDraftCatalog",
        "listingDraftCatalog",
        "activities",
        "confirmations",
        "conversations",
        "logisticsItems",
    ):
        if not re.search(rf"const {collection}\s*=\s*\[\s*\];", app_js):
            return fail(f"{collection} still carries production seed records")

    for collection in ("cockpitProfiles", "cockpitMarketProfiles"):
        if not re.search(rf"const {collection}\s*=\s*\{{\s*\}};", app_js):
            return fail(f"{collection} still carries production demo profiles")

    for marker in ("上传商品图片", "粘贴货源链接", "补充真实规格"):
        if marker not in app_html:
            return fail(f"merchant empty state is missing a supported input: {marker}")

    for marker in ('id="authModal"', 'id="ceoForm"', 'id="onboardingExit"'):
        if marker not in app_html:
            return fail(f"login/onboarding/data-loading hook was removed: {marker}")
    for marker in ("refreshSaasState({ silent: true })", "state.saasStores =", "state.saasReports ="):
        if marker not in app_js:
            return fail(f"existing merchant data loading path was removed: {marker}")

    print("PASS jiejing_production_empty_state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

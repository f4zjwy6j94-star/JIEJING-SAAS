#!/usr/bin/env python3
"""Contract tests for binding AI CEO turns to one exact Listing project."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import _ai_ceo_listing_project_identity_for_turn  # noqa: E402


IDENTITY = {
    "key": "project-incense-a",
    "source_report_id": "report-incense-a",
    "candidate_id": "candidate-incense-a",
}


def main() -> None:
    request = {
        "active_listing_context": {
            "contract_version": "active_listing_context_v1",
            "listing_project_identity": IDENTITY,
        }
    }
    assert _ai_ceo_listing_project_identity_for_turn(request, route="ebay_workflow") == IDENTITY
    assert _ai_ceo_listing_project_identity_for_turn(request, route="confirmation_required") == IDENTITY
    assert _ai_ceo_listing_project_identity_for_turn(request, route="general_chat") == {}
    assert _ai_ceo_listing_project_identity_for_turn(
        request,
        route="ebay_workflow",
        message="请新建一个独立商品项目，不复用当前香炉项目。",
    ) == {}
    assert _ai_ceo_listing_project_identity_for_turn(
        request,
        route="ebay_workflow",
        message="继续当前香炉项目，不得新建重复商品项目或 Offer。",
    ) == IDENTITY
    assert _ai_ceo_listing_project_identity_for_turn(
        {"active_listing_context": {"contract_version": "wrong", "listing_project_identity": IDENTITY}},
        route="ebay_workflow",
    ) == {}
    assert _ai_ceo_listing_project_identity_for_turn(
        {
            "active_listing_context": {
                "contract_version": "active_listing_context_v1",
                "listing_project_identity": {**IDENTITY, "candidate_id": "bad candidate/id"},
            }
        },
        route="ebay_workflow",
    ) == {**IDENTITY, "candidate_id": ""}

    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "listing_project_identity: chat?.listing_project_identity || null" in app_js
    assert "listing_project_identity: listingProjectIdentity" in app_js
    assert "await refreshSaasMerchantProjectStatus();" in app_js
    assert "function commitSaasActiveListingProjectContext" in app_js
    refresh_view_body = app_js[
        app_js.index("function activeSaasRefreshView") :
        app_js.index("function redirectToSaasLogin")
    ]
    assert 'startupView && currentView === "cockpit" ? startupView : currentView' in refresh_view_body
    commit_body = app_js[
        app_js.index("function commitSaasActiveListingProjectContext") :
        app_js.index("function renderSaasMerchantProjectStatusStrip")
    ]
    for marker in [
        "saveSaasProtectedStateSnapshot();",
        "syncSaasProjectRoute(normalizedView)",
        "refreshSaasMerchantProjectStatus({ projectId })",
        "mountSaasMerchantProjectStatusStrip(normalizedView)",
    ]:
        assert marker in commit_body, marker
    render_body = app_js[
        app_js.index("function renderSaasProductListingCenter") :
        app_js.index("function renderProductListingCenter")
    ]
    assert 'commitSaasActiveListingProjectContext("product");' in render_body
    print("PASS jiejing_ai_ceo_project_trace")


if __name__ == "__main__":
    main()

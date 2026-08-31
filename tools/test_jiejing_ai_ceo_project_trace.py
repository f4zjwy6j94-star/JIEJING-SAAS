#!/usr/bin/env python3
"""Contract tests for binding AI CEO turns to one exact Listing project."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import _ai_ceo_listing_project_identity_for_turn  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


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
    assert "listing_project_identity: reportListingIdentity || latest.listing_project_identity" in app_js
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
        "syncSaasProjectRoute(normalizedView, { projectId })",
        "refreshSaasMerchantProjectStatus({ projectId })",
        "mountSaasMerchantProjectStatusStrip(normalizedView)",
    ]:
        assert marker in commit_body, marker
    render_body = app_js[
        app_js.index("function renderSaasProductListingCenter") :
        app_js.index("function renderProductListingCenter")
    ]
    assert 'commitSaasActiveListingProjectContext("product");' in render_body

    with tempfile.TemporaryDirectory(prefix="jiejing-current-project-report-", ignore_cleanup_errors=True) as temp:
        repository = SaaSRepository(Path(temp) / "saas.sqlite")
        task = repository.create_task(
            company_id="company_current_project",
            store_id="store_current_project",
            user_id="user_current_project",
            task_type="ai_ceo.chat",
            title="AI CEO current project continuation",
            input_data={"message": "继续当前复古黄铜书签项目。"},
        )
        saved = repository.save_ai_ceo_market_research_report(
            task=task,
            message=(
                "继续当前复古黄铜书签（做旧工艺）模拟演练项目，不新建重复项目、商品、SKU 或 Listing。"
                "品牌 Unbranded、材质 做旧黄铜、商品尺寸 12 x 3 x 0.1 cm、净重 18 g。"
                "不得保存 eBay 草稿、公开发布或写入 eBay。"
            ),
            chat={
                "answer": (
                    "### 继续当前复古黄铜书签（做旧工艺）受控处理演练项目\n"
                    "收到，本轮继续现有项目，不新建重复项目。\n"
                    "### 受控处理演练规格\n|"
                ),
                "route": "confirmation_required",
                "status": "model_answered",
                "source_records": [{"title": "Current project", "url": "https://example.com/current"}],
            },
            listing_project_identity=IDENTITY,
            active_listing_product_name="复古黄铜书签（做旧工艺）",
        )
        assert saved is not None
        report = saved["report"]
        assert report["listing_project_identity"] == IDENTITY, report
        assert report["product"] == "复古黄铜书签（做旧工艺）", report
        assert report["selected_product_candidate"]["name"] == "复古黄铜书签（做旧工艺）", report
        assert report["conversation_context"]["selection_mode"] == "active_listing_context", report

        new_task = repository.create_task(
            company_id="company_current_project",
            store_id="store_current_project",
            user_id="user_current_project",
            task_type="ai_ceo.chat",
            title="AI CEO brand-new market research",
            input_data={"message": "新建一个全新商品项目。"},
        )
        new_report = repository.save_ai_ceo_market_research_report(
            task=new_task,
            message="新建一个全新商品项目，完成市场调研，给出一个候选商品并推荐。",
            chat={
                "answer": "候选商品 1：不锈钢咖啡量勺\n推荐度评分：82/100\n最终推荐：不锈钢咖啡量勺。",
                "route": "ebay_workflow",
                "status": "model_answered",
                "answer_quality": {"accepted": True},
                "source_records": [{"title": "Market source", "url": "https://example.com/market"}],
            },
        )
        assert new_report is not None
        new_body = new_report["report"]
        new_identity = new_body.get("listing_project_identity") or {}
        assert new_identity.get("key", "").startswith("listing-project-"), new_body
        assert new_identity.get("source_report_id") == new_report["report_id"], new_body
        assert new_identity.get("candidate_id") == new_body["selected_candidate_id"], new_body
        fetched_new_report = repository.get_report_for_company(
            company_id="company_current_project",
            report_id=new_report["report_id"],
        )
        assert fetched_new_report is not None, new_report
        assert fetched_new_report.get("store_id") == "store_current_project", fetched_new_report
        assert fetched_new_report.get("report_id") == new_report["report_id"], fetched_new_report
    print("PASS jiejing_ai_ceo_project_trace")


if __name__ == "__main__":
    main()

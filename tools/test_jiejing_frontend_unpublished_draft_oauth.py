#!/usr/bin/env python3
"""Static safety contract for the merchant unpublished-draft OAuth flow."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"


def require(source: str, marker: str, message: str) -> None:
    if marker not in source:
        raise AssertionError(message)


def main() -> None:
    app = APP_JS.read_text(encoding="utf-8")

    if "plan-ebay-publish-oauth" in app or "/ebay-oauth/publish-plan" in app:
        raise AssertionError("the legacy direct publish authorization path must be unreachable from the merchant frontend")

    flow_start = app.index("async function planSaasEbayUnpublishedDraftOAuth()")
    flow_end = app.index("async function syncSaasEbayReadOnlyData()", flow_start)
    flow = app[flow_start:flow_end]
    approve_start = app.index("async function approveFirstSaasConfirmation")
    approve_end = app.index("async function loginSaasBackendSession", approve_start)
    approve = app[approve_start:approve_end]

    intake = "/ebay-oauth/unpublished-draft-confirmation"
    plan = "/ebay-oauth/unpublished-draft-plan"
    require(flow, intake, "first click must create the dedicated draft-scope confirmation")
    require(flow, plan, "only an approved exact confirmation may create the draft-scope OAuth plan")
    if flow.index(intake) >= flow.index(plan):
        raise AssertionError("draft confirmation intake must precede draft OAuth planning")

    for marker, message in [
        ("seller_unpublished_draft", "draft OAuth must use its own scope profile"),
        ("controlled_ebay_unpublished_draft_save", "draft confirmation must use the exact backend source"),
        ("unpublished_draft_oauth_authorization_gate", "draft confirmation must use the exact backend step"),
        ("isSaasFreshApprovedUnpublishedDraftOAuthConfirmation", "expired or malformed approvals must fail closed"),
        ("saasUnpublishedDraftOAuthPlanAttemptKeys.has(planAttemptKey)", "one page may attempt an exact draft plan only once"),
        ("validatedSaasUnpublishedDraftOAuthPlanResponse(payload, store, existingConfirmation)", "the redirect must validate the exact draft plan response"),
        ("confirmation_id: existingConfirmation.confirmation_id", "the plan must carry the exact in-memory confirmation"),
        ('String(pending.company_id || "") !== companyId', "confirmation intake must bind the live company"),
        ('String(pending.store_id || "") !== storeId', "confirmation intake must bind activeSaasStore exactly"),
        ('String(request.confirmation_id || "") !== confirmationId', "the plan response must bind the confirmation at request level"),
        ('data-saas-action="plan-ebay-draft-oauth"', "settings must expose the dedicated unpublished-draft action"),
        ("public_publish_enabled !== false", "all draft OAuth response layers must keep public publish strictly false"),
        ("draft_save_capability_requested !== true", "all draft OAuth response layers must bind the requested draft capability"),
        ("saasEbayUnpublishedDraftOAuthScopeAllowlist", "the actual OAuth URL must use the exact draft scope allowlist"),
    ]:
        require(app, marker, message)

    if "state.saasStores[0]" in flow:
        raise AssertionError("draft OAuth must bind activeSaasStore, never the first tenant store")
    require(
        app,
        'normalizedSaasConnectionStatus(connection?.status) === "draft_save_authorized"',
        "only the dedicated draft authorization status may suppress draft OAuth",
    )
    if "state.saasLatestOAuthUrl" in flow:
        raise AssertionError("draft OAuth authorization URL must never persist in frontend state")
    if flow.index("saasUnpublishedDraftOAuthPlanAttemptKeys.add(planAttemptKey)") >= flow.index(plan):
        raise AssertionError("the one-shot draft plan claim must happen before the plan POST")

    require(approve, "isExactUnpublishedDraftOAuth", "draft approval must have a dedicated decision-only branch")
    branch_start = approve.index("if (isExactUnpublishedDraftOAuth")
    branch_end = approve.index("const preflight", branch_start)
    decision_only = approve[branch_start:branch_end]
    if "/preflight" in decision_only or "/execute" in decision_only:
        raise AssertionError("approving draft OAuth must not execute a platform write")

    print("PASS test_jiejing_frontend_unpublished_draft_oauth")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Static contract checks for the merchant exact-confirmation eBay OAuth UI."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"
STYLES = ROOT / "styles.css"


def require(source: str, marker: str, message: str) -> None:
    if marker not in source:
        raise AssertionError(message)


def main() -> None:
    app = APP_JS.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")
    flow_start = app.index("async function planSaasEbayReadOnlyOAuth()")
    flow_end = app.index("async function planSaasEbayUnpublishedDraftOAuth()", flow_start)
    flow = app[flow_start:flow_end]
    approve_start = app.index("async function approveFirstSaasConfirmation")
    approve_end = app.index("async function loginSaasBackendSession", approve_start)
    approve = app[approve_start:approve_end]

    intake = "/ebay-oauth/read-only-confirmation"
    plan = "/ebay-oauth/read-only-plan"
    require(flow, intake, "first click must use the pending confirmation intake")
    require(flow, plan, "approved flow must use the read-only plan route")
    if flow.index(intake) >= flow.index(plan):
        raise AssertionError("confirmation intake must appear before OAuth plan creation")
    require(flow, "confirmation_id: existingConfirmation.confirmation_id", "plan must carry the exact approved confirmation")
    require(flow, "saasReadOnlyOAuthPlanAttemptKeys.has(planAttemptKey)", "one in-memory exact confirmation may create at most one plan attempt per page")
    require(flow, "saasReadOnlyOAuthPlanAttemptKeys.add(planAttemptKey)", "the in-memory attempt claim must happen before the OAuth plan request")
    if flow.index("saasReadOnlyOAuthPlanAttemptKeys.add(planAttemptKey)") >= flow.index(plan):
        raise AssertionError("the exact confirmation attempt must be claimed before the plan POST")
    require(flow, "isSaasFreshApprovedReadOnlyOAuthConfirmation", "expired approval must fail closed before planning")
    require(flow, 'state.saasLatestOAuthUrl = ""', "read-only OAuth URL must not persist in frontend state")
    require(approve, "if (isExactReadOnlyOAuth)", "OAuth approval needs a decision-only branch")
    oauth_branch = approve[approve.index("if (isExactReadOnlyOAuth)") : approve.index("const preflight", approve.index("if (isExactReadOnlyOAuth)"))]
    if "/preflight" in oauth_branch or "/execute" in oauth_branch:
        raise AssertionError("OAuth confirmation approval must not preflight or execute a platform write")

    require(app, 'data-saas-confirmation-flow="ebay-read-only-oauth-current-store"', "OAuth confirmation DOM needs an opaque flow handle")
    require(app, ".filter((confirmation) => !isSaasReadOnlyOAuthSensitiveConfirmation", "OAuth confirmation identity must not enter protected localStorage snapshots")
    require(app, "state.saasOauthRequests = merchantSafeSaasOAuthRequests(oauthRequests.oauth_requests);", "OAuth request URLs and state must be removed at the frontend ingest boundary")
    require(app, "validatedSaasReadOnlyOAuthPlanResponse(payload, store, existingConfirmation)", "OAuth redirect must validate the exact current-store plan response before navigation")
    require(app, "saasEbayReadOnlyOAuthScopeAllowlist.has(scope)", "OAuth plan responses must use the strict seller read-only scope allowlist")
    require(app, "validatedSaasReadOnlyOAuthAuthorizationUrl(rawUrl, planScopes, planState)", "the actual eBay authorization URL must be parsed against the validated scope and state contract")
    require(app, 'queryKeys.length !== requiredQueryKeys.size', "OAuth authorization URLs must reject missing, duplicate, and extra query fields")
    require(app, 'JSON.stringify(urlScopes) !== JSON.stringify(expectedScopes)', "OAuth URL scopes must exactly match the plan and request scopes")
    require(app, 'urlState !== String(expectedState || "")', "OAuth URL state must exactly match the backend plan state")
    require(app, "normalizedRequestUrl !== authorizationUrl", "the persisted request URL must match the redirect URL")
    require(app, "requestBody.real_platform_writes_enabled !== false", "nested OAuth request write flags must be strict false")
    require(app, "payload.secret_exposed !== false", "OAuth response secret flags must be strict false")
    require(app, 'String(requestBody.confirmation_id || "") !== confirmationId', "OAuth plan response must bind the in-memory exact confirmation")
    require(app, 'data-ebay-oauth-confirmation-status=', "settings must expose a safe merchant status without the confirmation ID")
    require(styles, ".saas-oauth-confirmation-guidance", "pending/approved status needs bounded responsive styling")

    print("PASS test_jiejing_frontend_oauth_confirmation_flow")


if __name__ == "__main__":
    main()

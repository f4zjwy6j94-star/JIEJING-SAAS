#!/usr/bin/env python3
"""Guardrail for account-scoped frontend cache in the JIEJING workbench.

This test is intentionally static. The browser smoke proves behavior with real
pages; this file keeps future UI edits from accidentally reintroducing global
localStorage reads for AI CEO chat, source records, feedback, or command state.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def function_body(source: str, name: str) -> str:
    marker = f"function {name}"
    start = source.find(marker)
    if start < 0:
        raise AssertionError(f"missing function {name}")
    end = source.find("\nfunction ", start + len(marker))
    return source[start : end if end > start else len(source)]


def require(body: str, marker: str, label: str) -> None:
    if marker not in body:
        raise AssertionError(f"missing {label}: {marker}")


def reject(body: str, marker: str, label: str) -> None:
    if marker in body:
        raise AssertionError(f"forbidden {label}: {marker}")


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    browser_smoke = (ROOT / "tools" / "codex_jiejing_first_user_browser_smoke.js").read_text(encoding="utf-8")

    source_account_key = function_body(app_js, "saasSourceRecordAccountKey")
    for marker in [
        "state.saasUser?.user_id",
        "state.saasIdentity?.user_id",
        "state.saasUser?.email",
        "state.saasCompany?.company_id",
        "safeStorageValue(saasStorageKeys.lastAccount)",
        "session-${Math.abs(hashString(token))}",
    ]:
        require(source_account_key, marker, "stable account cache key")

    account_cache_gate = function_body(app_js, "shouldReadSaasAccountScopedLocalCache")
    for marker in [
        "state.saasProtectedStateFromCache",
        "state.saasUser?.user_id",
        "state.saasIdentity?.user_id",
        "state.saasCompany?.company_id",
        "safeStorageValue(saasStorageKeys.lastAccount)",
    ]:
        require(account_cache_gate, marker, "confirmed-account cache gate")

    source_scope = function_body(app_js, "saasSourceRecordStorageScope")
    require(source_scope, "saasSourceRecordAccountKey()", "source record account-scoped key")
    require(source_scope, "saasSourceRecordStoreKey()", "source record store-scoped key")

    scope_functions = {
        "loadSaasSourceRecords": [
            "localStorage.getItem(saasStorageKeys.sourceRecords)",
            "saasSourceRecordStorageScopes(true).flatMap",
            "payload[scope]",
        ],
        "persistSaasSourceRecords": [
            "payload[saasSourceRecordStorageScope()]",
            "localStorage.setItem(saasStorageKeys.sourceRecords",
        ],
        "loadSaasMerchantFeedback": [
            "localStorage.getItem(saasStorageKeys.merchantFeedback)",
            "payload[saasMerchantFeedbackStorageScope()]",
        ],
        "persistSaasMerchantFeedback": [
            "payload[saasMerchantFeedbackStorageScope()]",
            "localStorage.setItem(saasStorageKeys.merchantFeedback",
        ],
        "loadSaasLastCeoCommand": [
            "shouldReadSaasAccountScopedLocalCache()",
            "localStorage.getItem(saasStorageKeys.ceoCommand)",
            "payload[saasCeoCommandStorageScope()]",
        ],
        "persistSaasLastCeoCommand": [
            "shouldReadSaasAccountScopedLocalCache()",
            "payload[saasCeoCommandStorageScope()]",
            "localStorage.setItem(saasStorageKeys.ceoCommand",
        ],
        "loadSaasAiCeoThread": [
            "shouldReadSaasAccountScopedLocalCache()",
            "localStorage.getItem(saasStorageKeys.ceoThread)",
            "payload[saasCeoCommandStorageScope()]",
        ],
        "persistSaasAiCeoThread": [
            "shouldReadSaasAccountScopedLocalCache()",
            "payload[saasCeoCommandStorageScope()]",
            "localStorage.setItem(saasStorageKeys.ceoThread",
        ],
    }
    for name, markers in scope_functions.items():
        body = function_body(app_js, name)
        for marker in markers:
            require(body, marker, f"{name} tenant scoped storage")
        for forbidden in [
            "Object.values(payload)",
            "Object.keys(payload)[0]",
            "payload[0]",
            "payload.default",
            "payload.global",
            "payload.anonymous",
        ]:
            reject(body, forbidden, f"{name} global fallback")

    hydrate_body = function_body(app_js, "hydrateSaasCeoAccountScopedLocalState")
    for marker in ["loadSaasLastCeoCommand()", "loadSaasAiCeoThread()", "syncSaasAiCeoLatestTurnFromThread()", "saasCeoCommandStorageScope()"]:
        require(hydrate_body, marker, "AI CEO account-scoped hydration")

    latest_sync_body = function_body(app_js, "syncSaasAiCeoLatestTurnFromThread")
    for marker in ["state.saasAiCeoLatestTurn", "turns[turns.length - 1]", "shouldKeepSaasAiCeoThreadTurn"]:
        require(latest_sync_body, marker, "AI CEO latest turn sync")

    backend_history_body = function_body(app_js, "saasAiCeoThreadForBackendSync")
    for marker in [
        "!turn.pending",
        "turn.user_text && turn.assistant_text",
        "store_id: turn.store_id || currentStoreId",
        "model_resolution: null",
        "model_connection: null",
    ]:
        require(backend_history_body, marker, "account history backend-safe turn packet")

    merge_history_body = function_body(app_js, "mergeSaasAiCeoHistoryFromBackend")
    for marker in [
        "payload?.ai_ceo_chat_history",
        "uniqueSaasAiCeoThreadTurns",
        'history.scope === "account"',
        "history.cross_store === true",
        "persistSaasAiCeoThread({ syncBackend: false })",
    ]:
        require(merge_history_body, marker, "cross-device backend history merge")

    sync_history_body = function_body(app_js, "syncSaasAiCeoThreadWithBackend")
    for marker in [
        '"/ai-ceo/chat-history/sync"',
        'method: "POST"',
        "saasAiCeoThreadForBackendSync()",
        "mergeSaasAiCeoHistoryFromBackend(payload)",
    ]:
        require(sync_history_body, marker, "account history backend sync")

    cloud_dom_body = function_body(app_js, "syncSaasAiCeoCloudDomState")
    for marker in [
        ".saas-ai-ceo-thread",
        'state.saasAiCeoThreadCloudReady ? "account" : "local"',
        "thread.dataset.aiCeoHistoryScope",
    ]:
        require(cloud_dom_body, marker, "non-sensitive cloud history browser proof")

    merge_score_body = function_body(app_js, "saasAiCeoThreadTurnMergeScore")
    for marker in ["normalized.pending ? 0 : 100000", "normalized.assistant_text", "normalized.source_records"]:
        require(merge_score_body, marker, "cross-device completed-turn conflict preference")
    unique_turns_body = function_body(app_js, "uniqueSaasAiCeoThreadTurns")
    for marker in [
        "saasAiCeoThreadTurnMergeScore(existing)",
        "candidateScore >= existingScore",
        "orderedKeys",
        ".sort(compareSaasAiCeoThreadTurns)",
    ]:
        require(unique_turns_body, marker, "deterministic cross-device turn merge")
    turn_timestamp_body = function_body(app_js, "saasAiCeoThreadTurnTimestamp")
    for marker in ["Date.parse(turn?.created_at", "assistant_id", "parseInt(match[1], 16)"]:
        require(turn_timestamp_body, marker, "cross-device chronological timestamp fallback")
    turn_compare_body = function_body(app_js, "compareSaasAiCeoThreadTurns")
    for marker in ["saasAiCeoThreadTurnTimestamp(left)", "saasAiCeoThreadTurnTimestamp(right)", "localeCompare"]:
        require(turn_compare_body, marker, "cross-device chronological ordering")

    viewport_body = function_body(app_js, "syncSaasAiCeoFixedChatViewportState")
    require(viewport_body, "syncSaasAiCeoCloudDomState()", "cloud history marker after chat rerender")

    snapshot_body = function_body(app_js, "hydrateSaasProtectedStateFromCache")
    for marker in ["state.saasLastCeoCommand = null", "state.saasAiCeoThread = []", "state.saasAiCeoLatestTurn = null"]:
        require(snapshot_body, marker, "cached snapshot must not prehydrate AI CEO chat")

    refresh_body = function_body(app_js, "refreshSaasState")
    for marker in [
        "activeAccountAliasesBeforeRefresh",
        "confirmedAccountAliases",
        "shouldPreserveActiveCeoState",
        "confirmedAccountAliases.some((alias) => activeAccountAliasesBeforeRefresh.has(alias))",
        "shouldPreserveActiveCeoState ? activeCeoCommandBeforeRefresh : null",
        "...(shouldPreserveActiveCeoState ? activeCeoThreadBeforeRefresh : [])",
        "state.saasProtectedStateFromCache = false",
        "loadSaasLastCeoCommand()",
        "loadSaasAiCeoThread()",
        'optionalSaasFetchFast("/ai-ceo/chat-history?limit=30"',
        "coreCeoChatHistory.ai_ceo_chat_history.turns",
        "scheduleSaasAiCeoThreadBackendSync(0)",
    ]:
        require(refresh_body, marker, "backend-confirmed account gate before AI CEO hydration")

    remember_body = function_body(app_js, "rememberSaasAuthAccount")
    require(remember_body, "hydrateSaasCeoAccountScopedLocalState()", "rehydrate after account switch")
    require(remember_body, "clearStoredSaasStoreContext()", "clear stale store context after account switch")

    for marker in [
        "account_b_did_not_show_account_a_chat",
        "account_b_scoped_local_cache_clean",
        "ACCOUNT_A_PRIVATE_CHAT_SENTINEL",
        "ACCOUNT_A_PRIVATE_SOURCE_SENTINEL",
        "ACCOUNT_A_PRIVATE_FEEDBACK_SENTINEL",
        "ACCOUNT_A_PRIVATE_COMMAND_SENTINEL",
        "loadSaasSourceRecords",
        "loadSaasMerchantFeedback",
        "loadSaasLastCeoCommand",
        "loadSaasAiCeoThread",
        "no_ebay_oauth_triggered",
    ]:
        require(browser_smoke, marker, "browser smoke cross-account cache proof")

    print("PASS jiejing_frontend_tenant_cache_scope")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        raise SystemExit(fail(str(error)))

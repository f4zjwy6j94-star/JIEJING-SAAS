#!/usr/bin/env python3
"""First-day Jiejing account smoke without real eBay writes or real charges."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = f"{os.getpid()}-{int(time.time() * 1000)}"
OUT = ROOT / "output" / "jiejing-first-day-account-smoke" / RUN_ID
SAAS_DB = OUT / "saas-first-day.sqlite"
RUNTIME_DB = OUT / "runtime-first-day.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def request_json(url: str, *, method: str = "GET", body: dict[str, Any] | None = None, token: str = "") -> dict[str, Any]:
    payload = json.dumps(body or {}, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=payload, method=method)
    request.add_header("content-type", "application/json")
    if token:
        request.add_header("authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw or "{}")
            parsed["_http_status"] = response.status
            return parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw or "{}")
        parsed["_http_status"] = exc.code
        return parsed


def wait_for_health(base_url: str, timeout_seconds: float = 25.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            health = request_json(f"{base_url}/health")
            if health.get("status") == "ok":
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def check_static_first_day_contracts() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    index_html = (ROOT / "index.html").read_text(encoding="utf-8")
    api_server = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    ai_ceo_chat = (ROOT / "jiejing_saas" / "ai_ceo_chat.py").read_text(encoding="utf-8")
    first_user_browser_smoke = (ROOT / "tools" / "codex_jiejing_first_user_browser_smoke.js").read_text(encoding="utf-8")

    required_markers = [
        (index_html, "function hasEntryOnboardingCompleted", "homepage must know whether onboarding is complete"),
        (index_html, "lastEntryAuthAccountAliases", "homepage must keep user_id/email aliases for one merchant account"),
        (index_html, "function entryOnboardingDoneKeys", "homepage onboarding completion must be written for account aliases"),
        (index_html, "entryOnboardingDoneKeys(accountKey).forEach", "completed guide must persist all account aliases"),
        (index_html, "lastEntryAuthAccount = accountKey || emailKey", "entry login should prefer backend user_id as canonical account key"),
        (index_html, "openLoggedInExperience(activePath, { onboarded: true })", "completed onboarding must be explicit"),
        (app_js, "function shouldOpenSaasAppRoute", "app route must not bypass onboarding"),
        (app_js, "start === \"app\" && !shouldOpenSaasAppRoute(params)", "direct app route must be guarded"),
        (app_js, "function saasAccountStorageAliases", "workbench must scope local state to the current account aliases"),
        (app_js, "function saasOnboardingDoneStorageKeys", "workbench onboarding must check account aliases"),
        (app_js, "saasOnboardingDoneStorageKeys().some", "workbench must not rely on a single stale onboarding key"),
        (app_js, "function saasProtectedSnapshotStorageKeys", "protected snapshot cache must support account aliases"),
        (app_js, "function saasProtectedSnapshotStorageKey", "protected snapshots must be account-scoped"),
        (app_js, "function hydrateSaasCeoAccountScopedLocalState", "AI CEO chat state must hydrate per account"),
        (app_js, "function renderSaasFirstDayPathStrip", "login and protected app entry must share the same first-day path"),
        (app_js + index_html, "login_onboarding_ai_ceo_v3", "first-day path must make login, onboarding and AI CEO route visible"),
        (app_js, "刷新不会跳过向导", "first-day path must tell merchants refresh cannot skip onboarding"),
        (app_js, "一句话交给 AI CEO", "first-day path must point users to the simple AI CEO entry"),
        (app_js, "function saasAiCeoMerchantSafeFailureText", "frontend model failures must be merchant-safe"),
        (app_js, "AI 用量或服务商账单挡住了本次回复", "frontend model quota failure copy should be clear"),
        (app_js, "不用在前台重复粘贴凭证", "frontend model failure should not ask for repeated credential setup"),
        (app_js, "merchant_safe_ai_recovery_v1", "frontend model recovery hint should be lightweight and actionable"),
        (app_js, "function scheduleSaasAiCeoPendingWatchdog", "AI CEO slow replies must remain merchant-safe"),
        (app_js, "merchant_clear_pending_v2", "AI CEO pending state must use merchant-readable copy"),
        (api_server, "\"billing_trial\": billing_trial", "registration must expose no-charge trial status"),
        (api_server, "triggers_real_charge\": False", "trial fallback must explicitly avoid real charge"),
        (ai_ceo_chat, "def _classify_model_failure", "backend model failures must be classified safely"),
        (ai_ceo_chat, "def _model_unavailable_fallback_answer", "backend model failures must use safe copy"),
        (first_user_browser_smoke, "onboarded_query_did_not_bypass_onboarding", "browser smoke must prove old onboarded links cannot skip onboarding"),
        (first_user_browser_smoke, "first_day_path_strip_present", "browser smoke must prove first-day path is present in the shipped workbench asset"),
        (first_user_browser_smoke, "account_b_did_not_show_account_a_chat", "browser smoke must prove account B cannot see account A chat residue"),
        (first_user_browser_smoke, "account_b_scoped_local_cache_clean", "browser smoke must prove account B cannot read account A local cache"),
        (first_user_browser_smoke, "model_402_route_intercepted", "browser smoke must intercept model 402 without calling a real model"),
        (first_user_browser_smoke, "model_402_copy_is_merchant_safe", "browser smoke must prove model quota copy is merchant-safe"),
        (first_user_browser_smoke, "workbench_logo_returns_to_current_index", "browser smoke must prove logo returns to the current homepage"),
        (first_user_browser_smoke, "no_ebay_oauth_triggered", "browser smoke must explicitly avoid eBay OAuth"),
    ]
    for body, marker, label in required_markers:
        if marker not in body:
            return fail(f"missing first-day contract: {label}: {marker}")
    forbidden_markers = [
        "AI CEO 暂时没有返回结果：${publicRuntimeText",
        "openLoggedInExperience(activePath)",
    ]
    for marker in forbidden_markers:
        if marker in app_js + index_html:
            return fail(f"first-day flow still has stale unsafe marker: {marker}")
    return 0


def main() -> int:
    static_result = check_static_first_day_contracts()
    if static_result:
        return static_result

    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()

    port = free_port()
    env = {
        **os.environ,
        "JIEJING_BILLING_PROVIDER": "stripe_test_mock",
        "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
        "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "0",
        "JIEJING_ENABLE_HERMES_EBAY_BRIDGE": "0",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(SAAS_DB),
            "--runtime-db",
            str(RUNTIME_DB),
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
        base_url = f"http://127.0.0.1:{port}"
        if not wait_for_health(base_url):
            stderr = process.stderr.read() if process.stderr else ""
            return fail(f"saas backend did not become healthy: {stderr[-800:]}")

        suffix = str(int(time.time() * 1000))
        first = register_and_create_store(base_url, f"first-day-a-{suffix}@local.invalid")
        second = register_and_create_store(base_url, f"first-day-b-{suffix}@local.invalid")

        first_chat = request_json(
            f"{base_url}/stores/{first['store_id']}/merchant-ceo/chat",
            method="POST",
            token=first["token"],
            body={
                "message": "今天几号",
                "client_now": "2026-06-25T12:00:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "command": {
                    "id": "first-day-clock-smoke",
                    "text": "今天几号",
                    "title": "日期咨询",
                    "summary": "普通咨询不进长期经营记忆",
                    "intent": "question",
                    "status": "ready",
                    "routes": [],
                },
            },
        ).get("ai_ceo_chat", {})
        if first_chat.get("status") != "local_clock_answered":
            return fail(f"first account AI CEO basic chat should answer locally: {first_chat}")
        if first_chat.get("long_term_memory") is True:
            return fail("ordinary AI CEO clock chat must not become long-term operating memory")

        model_block = request_json(
            f"{base_url}/stores/{first['store_id']}/merchant-ceo/chat",
            method="POST",
            token=first["token"],
            body={
                "message": "帮我调研 eBay 上热销的五个产品",
                "client_now": "2026-06-25T12:01:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "command": {
                    "id": "first-day-model-block-smoke",
                    "text": "帮我调研 eBay 上热销的五个产品",
                    "title": "选品调研",
                    "summary": "模型未配置时应清楚阻断",
                    "intent": "research",
                    "status": "ready",
                    "routes": [],
                },
            },
        ).get("ai_ceo_chat", {})
        model_answer = str(model_block.get("answer") or "")
        if model_block.get("status") != "blocked_before_model_chat":
            return fail(f"model-required chat without model secret should block before model: {model_block}")
        if any(marker in model_answer.lower() for marker in ("402", "traceback", "secret", "api key", "token")):
            return fail(f"merchant model-block answer must not expose internal error or secrets: {model_answer}")

        second_latest = request_json(f"{base_url}/stores/{second['store_id']}/merchant-ceo/commands/latest", token=second["token"])
        if second_latest.get("command") is not None or second_latest.get("merchant_ceo_command") is not None:
            return fail(f"second account should not inherit first account AI CEO command history: {second_latest}")

        print(
            json.dumps(
                {
                    "status": "pass",
                    "first_account_trial": first["billing_trial_status"],
                    "second_account_trial": second["billing_trial_status"],
                    "first_chat_status": first_chat.get("status"),
                    "model_block_status": model_block.get("status"),
                    "second_latest_empty": True,
                    "real_platform_writes_enabled": False,
                    "triggers_real_charge": False,
                    "secret_exposed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("PASS jiejing_first_day_account_smoke")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def register_and_create_store(base_url: str, email: str) -> dict[str, str]:
    registered = request_json(
        f"{base_url}/auth/register",
        method="POST",
        body={"email": email, "password": "password123", "company_name": "First Day Smoke"},
    )
    token = str(registered.get("token") or "")
    if not token:
        raise RuntimeError(f"register returned no token: {registered}")
    trial = registered.get("billing_trial") if isinstance(registered.get("billing_trial"), dict) else {}
    if trial.get("ok") is not True:
        raise RuntimeError(f"register did not seed test entitlement: {trial}")
    if trial.get("triggers_real_charge") is not False or trial.get("calls_stripe_api") is not False:
        raise RuntimeError(f"register trial must not charge or call Stripe: {trial}")
    store_response = request_json(
        f"{base_url}/stores",
        method="POST",
        token=token,
        body={
            "platform": "ebay",
            "store_name": f"Smoke Store {email}",
            "marketplace": "EBAY_US",
            "stage": "store_opened",
        },
    )
    store = store_response.get("store") if isinstance(store_response.get("store"), dict) else {}
    store_id = str(store.get("store_id") or "")
    if not store_id:
        raise RuntimeError(f"store create returned no store_id: {store_response}")
    return {
        "token": token,
        "store_id": store_id,
        "billing_trial_status": str(trial.get("status") or ""),
    }


if __name__ == "__main__":
    raise SystemExit(main())

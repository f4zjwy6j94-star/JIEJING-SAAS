#!/usr/bin/env python3
"""Smoke test for the AI CEO platform-managed model fallback."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.ai_ceo_semantic_test_fixture import PLANNER_PROMPT_PREFIX, semantic_decision_json
from tools.test_jiejing_ai_ceo_routing_supplier_http_red import SAFE_CHILD_ENV_NAMES
OUT = ROOT / "output" / "jiejing-saas-ai-ceo-platform-model" / "test"
SAAS_DB = OUT / "saas-ai-ceo-platform-model.sqlite"
RUNTIME_DB = OUT / "runtime-ai-ceo-platform-model.sqlite"


class FakeModelHandler(BaseHTTPRequestHandler):
    calls: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0") or "0")
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        FakeModelHandler.calls.append(
            {
                "path": self.path,
                "authorization_present": bool(self.headers.get("authorization")),
                "body": body,
            }
        )
        messages = body.get("messages") or []
        system_prompt = str(messages[0].get("content") or "") if messages else ""
        content = (semantic_decision_json(intent="chat") if system_prompt.startswith(PLANNER_PROMPT_PREFIX)
                   else "捷境 AI CEO 已通过平台托管 AI 连接回答；本次不会触发 eBay 写入。")
        payload = {
            "choices": [
                {
                    "message": {
                        "content": content
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(base_url: str) -> bool:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            fetch_json(f"{base_url}/health")
            return False
        except Exception:
            time.sleep(0.2)
    return True


def fetch_json(url: str, *, token: str | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_headers(token=token))
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], *, token: str | None = None) -> dict[str, Any]:
    if "/merchant-ceo/chat" in url:
        payload = {**payload, "semantic_dispatch_contract": "ai_ceo_semantic_dispatch_v1"}
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=_headers(token=token), method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json_expect_error(url: str, payload: dict[str, Any], *, token: str | None = None) -> tuple[int, dict[str, Any]]:
    try:
        return 200, post_json(url, payload, token=token)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return int(exc.code), json.loads(raw) if raw else {}


def _headers(*, token: str | None = None) -> dict[str, str]:
    headers = {"content-type": "application/json", "accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()

    model_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModelHandler)
    model_thread = threading.Thread(target=model_server.serve_forever, daemon=True)
    model_thread.start()
    saas_port = free_port()
    platform_key = "unit-platform-model-key-not-returned"
    env = {key: value for key, value in os.environ.items() if key.upper() in SAFE_CHILD_ENV_NAMES}
    env.update({"JIEJING_SAAS_ENV": "test", "JIEJING_DATABASE_ENGINE": "sqlite",
                "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false", "JIEJING_PUBLIC_CHARGING_ALLOWED": "false",
                "JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED": "0", "JIEJING_AI_CEO_BUILTIN_WEB_FALLBACK_ENABLED": "0"})
    env["JIEJING_BILLING_PROVIDER"] = "stripe_test_mock"
    env["JIEJING_QUOTA_ENFORCEMENT_ENABLED"] = "1"
    env["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "1"
    env["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(OUT / "local-model-secrets.json")
    env["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = "0"
    env["JIEJING_AI_CEO_PLATFORM_MODEL_ENABLED"] = "1"
    env["JIEJING_AI_CEO_PLATFORM_MODEL_PROVIDER"] = "deepseek"
    env["JIEJING_AI_CEO_PLATFORM_MODEL_API_KEY"] = platform_key
    env["JIEJING_AI_CEO_PLATFORM_MODEL"] = "deepseek-v4-pro"
    env["JIEJING_AI_CEO_PLATFORM_MODEL_BASE_URL"] = f"http://127.0.0.1:{model_server.server_address[1]}/v1"
    env["JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT"] = "1"
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
            str(saas_port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{saas_port}"
        if wait_for_health(base_url):
            stderr = process.stderr.read() if process.stderr else ""
            return fail(f"saas backend did not become healthy: {stderr[-800:]}")

        auth = post_json(
            f"{base_url}/auth/register",
            {"email": "ai-ceo-platform-model@example.com", "password": "password123", "company_name": "AI CEO Platform Co"},
        )
        token = str(auth.get("token") or "")
        store = post_json(
            f"{base_url}/stores",
            {"platform": "ebay", "store_name": "Platform AI Store", "marketplace": "EBAY_US", "stage": "store_opened"},
            token=token,
        ).get("store", {})
        store_id = str(store.get("store_id") or "")
        if not store_id:
            return fail("store creation should return a store_id")

        settings_before = fetch_json(f"{base_url}/stores/{store_id}/model/settings", token=token).get("model_settings", {})
        if platform_key in json.dumps(settings_before, ensure_ascii=False):
            return fail("model settings must not expose the platform model API key")
        quota_before = (
            settings_before.get("platform_trial_quota")
            if isinstance(settings_before.get("platform_trial_quota"), dict)
            else {}
        )
        if (
            quota_before.get("scope") != "account_trial_window"
            or quota_before.get("usage_owner") != "jiejing_platform_trial"
            or quota_before.get("monthly_limit") != 1
            or quota_before.get("trial_duration_days") != 7
            or quota_before.get("used") != 0
            or quota_before.get("allowed") is not True
            or quota_before.get("frontend_can_grant_quota") is not False
            or quota_before.get("byok_bypasses_platform_trial") is not True
        ):
            return fail(f"model settings should expose safe account trial quota before use: {quota_before}")

        response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "Introduce Jiejing in one sentence.",
                "client_now": "2026-05-25T10:00:00+08:00",
                "client_timezone": "Asia/Shanghai",
            },
            token=token,
        )
        serialized = json.dumps(response, ensure_ascii=False)
        if platform_key in serialized:
            return fail("platform model response must not expose the model API key")
        chat = response.get("ai_ceo_chat", {})
        if chat.get("status") != "model_answered":
            return fail(f"AI CEO should answer through the platform-managed model fallback: {chat}")
        resolution = response.get("model_secret_resolution", {})
        if resolution.get("mode") != "platform_managed_default":
            return fail(f"AI CEO should report platform-managed model mode: {resolution}")
        if resolution.get("secret_ref_scope") != "platform":
            return fail(f"AI CEO should mark the fallback as platform scoped: {resolution}")
        if resolution.get("merchant_pays_provider_directly") is not False or resolution.get("jiejing_pays_provider_usage") is not True:
            return fail(f"platform fallback should be billed as Jiejing-managed usage: {resolution}")
        platform_trial = resolution.get("platform_trial_quota") if isinstance(resolution.get("platform_trial_quota"), dict) else {}
        if platform_trial.get("monthly_limit") != 1 or platform_trial.get("used") != 0 or platform_trial.get("allowed") is not True:
            return fail(f"platform fallback should expose backend trial quota before the first use: {platform_trial}")
        if not FakeModelHandler.calls:
            return fail("platform fallback should call the backend model provider")
        first_call_count = len(FakeModelHandler.calls)
        tasks_after_success = fetch_json(f"{base_url}/tasks?store_id={store_id}&limit=30", token=token).get("tasks", [])
        successful_attempts = [item for item in tasks_after_success if item.get("task_type") == "merchant_ceo_chat_attempt"]
        model_tasks = [item for item in tasks_after_success if item.get("task_type") == "merchant_ceo_chat"]
        if len(successful_attempts) != 1 or len(model_tasks) != 1:
            return fail(f"one model request should create one attempt and one metered model task: {tasks_after_success}")
        successful_attempt = successful_attempts[0]
        successful_output = successful_attempt.get("output") if isinstance(successful_attempt.get("output"), dict) else {}
        if successful_attempt.get("status") != "completed" or successful_output.get("attempt_state") != "completed":
            return fail(f"successful model request should complete its single attempt: {successful_attempt}")
        if successful_output.get("actual_task_id") != model_tasks[0].get("task_id"):
            return fail(f"successful attempt must link the actual metered model task: {successful_attempt}")
        if successful_output.get("artifact_outcome") != "not_requested":
            return fail(f"general chat should record artifact_outcome=not_requested: {successful_attempt}")
        if successful_attempt.get("input", {}).get("model_usage_required") is not False:
            return fail(f"attempt itself must remain non-metered: {successful_attempt}")

        settings_after_first = fetch_json(f"{base_url}/stores/{store_id}/model/settings", token=token).get("model_settings", {})
        quota_after_first = (
            settings_after_first.get("platform_trial_quota")
            if isinstance(settings_after_first.get("platform_trial_quota"), dict)
            else {}
        )
        if quota_after_first.get("used") != 1 or quota_after_first.get("remaining") != 0 or quota_after_first.get("allowed") is not False:
            return fail(f"model settings should show exhausted platform trial quota after first use: {quota_after_first}")

        blocked_status, blocked_response = post_json_expect_error(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat?stream=1",
            {
                "message": "Answer one more general question.",
                "client_now": "2026-05-25T10:01:00+08:00",
                "client_timezone": "Asia/Shanghai",
            },
            token=token,
        )
        if blocked_status != 402:
            return fail(
                "an immediate streamed platform fallback rejection should use ordinary HTTP 402 JSON, "
                f"got {blocked_status}: {blocked_response}"
            )
        blocked_chat = blocked_response.get("ai_ceo_chat", {})
        if "platform_default_model_trial_exhausted" not in set(blocked_chat.get("blocked_by") or []):
            return fail(f"trial quota exhaustion should be explicit: {blocked_chat}")
        blocked_quota = blocked_chat.get("platform_trial_quota") if isinstance(blocked_chat.get("platform_trial_quota"), dict) else {}
        if blocked_quota.get("monthly_limit") != 1 or blocked_quota.get("used") != 1 or blocked_quota.get("allowed") is not False:
            return fail(f"blocked platform fallback should expose exhausted backend quota: {blocked_quota}")
        if len(FakeModelHandler.calls) != first_call_count:
            return fail("exhausted platform fallback should not call the backend model provider again")
        tasks_after_quota_block = fetch_json(f"{base_url}/tasks?store_id={store_id}&limit=30", token=token).get("tasks", [])
        attempts_after_quota_block = [item for item in tasks_after_quota_block if item.get("task_type") == "merchant_ceo_chat_attempt"]
        model_tasks_after_quota_block = [item for item in tasks_after_quota_block if item.get("task_type") == "merchant_ceo_chat"]
        blocked_attempts = [
            item
            for item in attempts_after_quota_block
            if item.get("status") == "blocked" and item.get("output", {}).get("attempt_state") == "blocked_quota"
        ]
        if len(attempts_after_quota_block) != 2 or len(blocked_attempts) != 1:
            return fail(f"quota rejection should update exactly one additional non-metered attempt: {tasks_after_quota_block}")
        if len(model_tasks_after_quota_block) != 1:
            return fail(f"quota rejection must not create another metered model task: {tasks_after_quota_block}")
        blocked_attempt_input = blocked_attempts[0].get("input") if isinstance(blocked_attempts[0].get("input"), dict) else {}
        if blocked_attempt_input.get("model_usage_required") is not False:
            return fail(f"quota-blocked attempt must remain non-metered: {blocked_attempts[0]}")

        merchant_key = "unit-merchant-model-key-not-returned"
        saved_model = post_json(
            f"{base_url}/stores/{store_id}/model/api-key",
            {
                "provider_key": "deepseek",
                "api_key": merchant_key,
                "model": "deepseek-v4-pro",
                "base_url": f"http://127.0.0.1:{model_server.server_address[1]}/v1",
                "connection_scope": "account",
            },
            token=token,
        )
        if merchant_key in json.dumps(saved_model, ensure_ascii=False):
            return fail("saved account BYOK response must not expose the merchant model key")
        saved_connection = saved_model.get("model_connection", {})
        saved_settings = saved_model.get("model_settings", {})
        if saved_connection.get("status") != "ready" or saved_connection.get("verified") is not True:
            return fail(f"saving BYOK should verify the provider before reporting success: {saved_connection}")
        if saved_settings.get("connection_state") != "ready" or saved_settings.get("configured") is not True:
            return fail(f"verified BYOK should become the account default: {saved_settings}")
        verified_again = post_json(
            f"{base_url}/stores/{store_id}/model/verify",
            {"model_secret_ref": saved_model.get("model_secret_ref", {}).get("secret_ref")},
            token=token,
        )
        if verified_again.get("verified") is not True or verified_again.get("model_settings", {}).get("configured") is not True:
            return fail(f"saved BYOK should be re-verifiable without re-entering the key: {verified_again}")
        byok_response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "请用一句话介绍跨境电商运营。",
                "client_now": "2026-05-25T10:01:30+08:00",
                "client_timezone": "Asia/Shanghai",
            },
            token=token,
        )
        byok_chat = byok_response.get("ai_ceo_chat", {})
        byok_resolution = byok_response.get("model_secret_resolution", {})
        if byok_chat.get("status") != "model_answered" or byok_resolution.get("mode") != "account_byok":
            return fail(f"account BYOK should answer after the platform trial is exhausted: {byok_response}")
        if byok_resolution.get("merchant_pays_provider_directly") is not True:
            return fail(f"account BYOK usage ownership should remain merchant-paid: {byok_resolution}")
        settings_after_byok = fetch_json(f"{base_url}/stores/{store_id}/model/settings", token=token).get("model_settings", {})
        quota_after_byok = settings_after_byok.get("platform_trial_quota", {})
        if quota_after_byok.get("used") != 1 or quota_after_byok.get("allowed") is not False:
            return fail(f"account BYOK must not consume or reset the exhausted Jiejing trial: {quota_after_byok}")

        FakeModelHandler.calls.clear()
        capability_response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "你现在什么大模型",
                "client_now": "2026-05-25T10:02:00+08:00",
                "client_timezone": "Asia/Shanghai",
            },
            token=token,
        )
        capability_chat = capability_response.get("ai_ceo_chat", {})
        if capability_chat.get("status") != "model_answered" or capability_response.get("model_secret_resolution", {}).get("mode") != "account_byok":
            return fail("capability consultation must use the semantic planner and the current account BYOK connection")
        if len(FakeModelHandler.calls) != 2:
            return fail("capability consultation must meter both planning and answering calls")

        # A Listing quality failure may use one automatic repair request, but it
        # remains one merchant-visible Jiejing trial action. The next platform-
        # managed Listing must be rejected before another provider request.
        listing_auth = post_json(
            f"{base_url}/auth/register",
            {
                "email": "listing-platform-trial@example.com",
                "password": "password123",
                "company_name": "Listing Platform Trial Co",
            },
        )
        listing_token = str(listing_auth.get("token") or "")
        listing_store = post_json(
            f"{base_url}/stores",
            {"platform": "ebay", "store_name": "Listing Trial Store", "marketplace": "EBAY_US", "stage": "store_opened"},
            token=listing_token,
        ).get("store", {})
        listing_store_id = str(listing_store.get("store_id") or "")
        listing_payload = {
            "listing_project_identity": {"key": "listing-project-platform-trial-http"},
            "merchant_product_fact_packet": {
                "merchant_confirmed_facts": {
                    "product_name": "Foldable Tablet Stand",
                    "condition": "NEW",
                    "material": "Aluminum alloy",
                }
            },
            "current_draft_fields": {},
        }
        FakeModelHandler.calls.clear()
        failed_status, failed_listing = post_json_expect_error(
            f"{base_url}/stores/{listing_store_id}/listing-drafts/generate",
            listing_payload,
            token=listing_token,
        )
        if failed_status != 422 or failed_listing.get("failure_code") != "listing_model_output_invalid_json":
            return fail(f"invalid platform Listing should fail after one repair: {failed_status} {failed_listing}")
        if failed_listing.get("model_called") is not True or failed_listing.get("model_usage", {}).get("request_count") != 2:
            return fail(f"failed Listing must report both provider requests: {failed_listing}")
        if len(FakeModelHandler.calls) != 2:
            return fail(f"Listing quality repair should make exactly two provider requests: {FakeModelHandler.calls}")
        listing_tasks = fetch_json(
            f"{base_url}/tasks?store_id={listing_store_id}&limit=30",
            token=listing_token,
        ).get("tasks", [])
        metered_listing_tasks = [item for item in listing_tasks if item.get("task_type") == "listing_draft_generation"]
        if len(metered_listing_tasks) != 1:
            return fail(f"one failed Listing action should leave exactly one metered task: {listing_tasks}")
        listing_output = metered_listing_tasks[0].get("output", {})
        if (
            metered_listing_tasks[0].get("status") != "failed"
            or listing_output.get("usage_consumed") is not True
            or listing_output.get("model_request_count") != 2
        ):
            return fail(f"failed Listing task lost precise usage: {metered_listing_tasks[0]}")
        listing_reports = fetch_json(f"{base_url}/reports?limit=100", token=listing_token).get("reports", [])
        if any(item.get("report_type") == "listing.package" for item in listing_reports):
            return fail(f"quality-blocked Listing created a report: {listing_reports}")
        with sqlite3.connect(SAAS_DB) as connection:
            usage_row = connection.execute(
                "select usage_owner, request_count, usage_json from model_usage_ledger where task_id = ?",
                (metered_listing_tasks[0].get("task_id"),),
            ).fetchone()
        if not usage_row or usage_row[0] != "jiejing_platform_trial" or int(usage_row[1] or 0) != 2:
            return fail(f"failed Listing usage ledger is incomplete: {usage_row}")
        usage_details = json.loads(str(usage_row[2] or "{}")).get("details", {})
        if usage_details.get("outcome") != "failed":
            return fail(f"failed Listing usage ledger lost its outcome: {usage_details}")
        listing_quota = fetch_json(
            f"{base_url}/stores/{listing_store_id}/model/settings",
            token=listing_token,
        ).get("model_settings", {}).get("platform_trial_quota", {})
        if listing_quota.get("used") != 1 or listing_quota.get("remaining") != 0 or listing_quota.get("allowed") is not False:
            return fail(f"one failed Listing action should consume one trial unit: {listing_quota}")

        blocked_call_count = len(FakeModelHandler.calls)
        blocked_listing_status, blocked_listing = post_json_expect_error(
            f"{base_url}/stores/{listing_store_id}/listing-drafts/generate",
            listing_payload,
            token=listing_token,
        )
        if blocked_listing_status != 402 or "platform_default_model_trial_exhausted" not in set(blocked_listing.get("blocked_by") or []):
            return fail(f"second platform Listing should be blocked before model use: {blocked_listing_status} {blocked_listing}")
        if len(FakeModelHandler.calls) != blocked_call_count:
            return fail("trial-blocked Listing called the provider")
        tasks_after_listing_block = fetch_json(
            f"{base_url}/tasks?store_id={listing_store_id}&limit=30",
            token=listing_token,
        ).get("tasks", [])
        if len([item for item in tasks_after_listing_block if item.get("task_type") == "listing_draft_generation"]) != 1:
            return fail(f"trial-blocked Listing created another metered task: {tasks_after_listing_block}")

        listing_byok_key = "unit-listing-byok-key-not-returned"
        saved_listing_byok = post_json(
            f"{base_url}/stores/{listing_store_id}/model/api-key",
            {
                "provider_key": "deepseek",
                "api_key": listing_byok_key,
                "model": "deepseek-v4-pro",
                "base_url": f"http://127.0.0.1:{model_server.server_address[1]}/v1",
                "connection_scope": "account",
            },
            token=listing_token,
        )
        if listing_byok_key in json.dumps(saved_listing_byok, ensure_ascii=False):
            return fail("Listing BYOK response exposed the merchant model key")
        byok_baseline_calls = len(FakeModelHandler.calls)
        byok_listing_status, byok_listing = post_json_expect_error(
            f"{base_url}/stores/{listing_store_id}/listing-drafts/generate",
            {**listing_payload, "listing_project_identity": {"key": "listing-project-byok-after-trial"}},
            token=listing_token,
        )
        if byok_listing_status != 422 or byok_listing.get("failure_code") != "listing_model_output_invalid_json":
            return fail(f"BYOK Listing should bypass trial exhaustion and reach the model: {byok_listing_status} {byok_listing}")
        if len(FakeModelHandler.calls) != byok_baseline_calls + 2:
            return fail("BYOK Listing did not reach the provider for generation and one repair")
        quota_after_listing_byok = fetch_json(
            f"{base_url}/stores/{listing_store_id}/model/settings",
            token=listing_token,
        ).get("model_settings", {}).get("platform_trial_quota", {})
        if quota_after_listing_byok.get("used") != 1 or quota_after_listing_byok.get("allowed") is not False:
            return fail(f"BYOK Listing changed Jiejing-funded trial usage: {quota_after_listing_byok}")
        print("PASS jiejing_saas_ai_ceo_platform_model_fallback")
        return 0
    finally:
        model_server.shutdown()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())

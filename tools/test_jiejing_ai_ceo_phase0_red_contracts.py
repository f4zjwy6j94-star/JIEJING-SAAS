#!/usr/bin/env python3
"""Phase-0 RED contracts for AI CEO artifact authority and Listing handoff.

The HTTP fixture uses temporary SQLite databases and a hermetic, non-live child
environment. It never inherits production database/provider credentials and it
cannot enable real platform writes.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.ai_ceo_chat import (  # noqa: E402
    AI_CEO_ROUTE_EBAY_WORKFLOW,
    _classify_ai_ceo_route,
    _classify_external_realtime_request,
)
from jiejing_saas.api_server import build_ai_ceo_market_report_delivery  # noqa: E402
from jiejing_saas.repository import SaaSRepository, _looks_like_ai_ceo_market_research_turn  # noqa: E402


APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
EBAY_RESEARCH_PROMPT = "请为我的 eBay 美国店铺调研三个全新候选商品，并生成可审计的选品报告。"
LOCAL_TEST_PASSWORD = "local-test-password"
LOCAL_SESSION_SECRET = "local-ai-ceo-red-session-secret"
APPROVED_ATTEMPT_INPUT_KEYS = {
    "attempt_state",
    "command_id",
    "frontend_gets_model_api_key",
    "model_usage_required",
    "real_platform_writes_enabled",
    "route",
    "route_label",
    "runtime_gets_raw_ebay_token",
    "secret_exposed",
}
SECRET_LIKE_VALUE_MARKERS = (
    "api-key",
    "api_key",
    "apikey",
    "bearer ",
    "password",
    "refresh_token",
    "secret",
    "sk-",
    "token",
)
SAFE_CHILD_ENV_NAMES = {
    "COMSPEC",
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PATHEXT",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "TZ",
    "USERPROFILE",
    "WINDIR",
}


def function_body(source: str, name: str) -> str:
    marker = f"function {name}"
    start = source.index(marker)
    next_function = source.find("\nfunction ", start + len(marker))
    next_async = source.find("\nasync function ", start + len(marker))
    ends = [value for value in (next_function, next_async) if value > start]
    return source[start : min(ends) if ends else len(source)]


def string_leaf_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in string_leaf_values(item)]
    if isinstance(value, (list, tuple)):
        return [leaf for item in value for leaf in string_leaf_values(item)]
    return []


def run_node_json(script: str) -> dict[str, object]:
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"node fixture failed before behavior assertion:\n{completed.stderr or completed.stdout}")
    output = completed.stdout.strip().splitlines()
    if not output:
        raise AssertionError("node fixture returned no JSON")
    return json.loads(output[-1])


def route_and_chat(message: str, answer: str) -> tuple[str, dict[str, object]]:
    realtime_kind = _classify_external_realtime_request(message)
    route = _classify_ai_ceo_route(message, realtime_kind=realtime_kind)
    return route, {
        "answer": answer,
        "route": route,
        "route_label": route,
        "status": "realtime_search_answered" if realtime_kind else "model_answered",
    }


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {"accept": "application/json"}
    if payload is not None:
        headers["content-type"] = "application/json"
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return int(response.status), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return int(exc.code), json.loads(raw) if raw else {}


def wait_for_health(base_url: str) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            status, _payload = request_json(f"{base_url}/health")
            if status == 200:
                return
        except OSError:
            pass
        time.sleep(0.1)
    raise AssertionError("local AI CEO RED fixture did not become healthy")


def isolated_backend_env(*, port: int) -> dict[str, str]:
    """Build a child environment from a small OS-only allowlist."""

    env = {key: value for key, value in os.environ.items() if key.upper() in SAFE_CHILD_ENV_NAMES}
    env.update(
        {
            "JIEJING_SAAS_ENV": "test",
            "JIEJING_SAAS_SESSION_SECRET": LOCAL_SESSION_SECRET,
            "JIEJING_DATABASE_ENGINE": "sqlite",
            "JIEJING_DATABASE_ADAPTER": "sqlite-local",
            "JIEJING_DATABASE_URL": "",
            "JIEJING_QUEUE_PROVIDER": "local_worker",
            "JIEJING_QUEUE_URL": "",
            "JIEJING_EXECUTION_ADAPTER": "demo_no_platform_write",
            "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
            "JIEJING_EBAY_WRITE_LIVE": "false",
            "JIEJING_EBAY_DRAFT_SAVE_LIVE": "false",
            "JIEJING_WECHAT_PAY_LIVE_API_ENABLED": "false",
            "JIEJING_WECHAT_PAY_CHARGE_ALLOWED": "false",
            "JIEJING_MEDIA_PROVIDER_LIVE_ENABLED": "false",
            "JIEJING_PUBLIC_CHARGING_ALLOWED": "false",
            "JIEJING_NETWORK_DISABLED": "true",
            "JIEJING_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}",
            "JIEJING_BILLING_PROVIDER": "stripe_test_mock",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
            "JIEJING_AI_CEO_PLATFORM_MODEL_ENABLED": "1",
            "JIEJING_AI_CEO_PLATFORM_MODEL_PROVIDER": "openai",
            "JIEJING_AI_CEO_PLATFORM_MODEL_BASE_URL": "http://127.0.0.1:1/v1",
            "JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED": "0",
            "JIEJING_AI_CEO_BUILTIN_WEB_FALLBACK_ENABLED": "0",
            "JIEJING_PUBLIC_SEARCH_LIVE_ENABLED": "0",
            "JIEJING_VAULT_ENABLED": "false",
            "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED": "0",
            "JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": "0",
        }
    )
    return env


class AiCeoBackendAuthorityRedTests(unittest.TestCase):
    def test_pre_model_dependency_failure_persists_non_billable_attempt_without_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jiejing-ai-ceo-premodel-red-", ignore_cleanup_errors=True) as temp:
            temp_root = Path(temp)
            db_path = temp_root / "saas.sqlite"
            runtime_db_path = temp_root / "runtime.sqlite"
            output_root = temp_root / "output"
            stdout_path = temp_root / "backend-stdout.log"
            stderr_path = temp_root / "backend-stderr.log"
            port = free_port()
            env = isolated_backend_env(port=port)
            with stdout_path.open("w", encoding="utf-8") as child_stdout, stderr_path.open(
                "w", encoding="utf-8"
            ) as child_stderr:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
                        "serve",
                        "--db",
                        str(db_path),
                        "--runtime-db",
                        str(runtime_db_path),
                        "--output-root",
                        str(output_root),
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=child_stdout,
                    stderr=child_stderr,
                    text=True,
                )
                try:
                    base_url = f"http://127.0.0.1:{port}"
                    wait_for_health(base_url)
                    register_status, registered = request_json(
                        f"{base_url}/auth/register",
                        method="POST",
                        payload={
                            "email": "ai-ceo-premodel-red@example.test",
                            "password": LOCAL_TEST_PASSWORD,
                            "company_name": "AI CEO pre-model RED",
                        },
                    )
                    self.assertEqual(201, register_status)
                    token = str(registered.get("token") or "")
                    company_id = str((registered.get("company") or {}).get("company_id") or "")
                    store_status, store_payload = request_json(
                        f"{base_url}/stores",
                        method="POST",
                        payload={"platform": "ebay", "store_name": "Pre-model RED Store", "marketplace": "EBAY_US"},
                        token=token,
                    )
                    self.assertEqual(201, store_status)
                    store_id = str((store_payload.get("store") or {}).get("store_id") or "")
                    before_status, settings_before = request_json(
                        f"{base_url}/stores/{store_id}/model/settings",
                        token=token,
                    )
                    quota_before = (settings_before.get("model_settings") or {}).get("platform_trial_quota") or {}
                    chat_status, blocked = request_json(
                        f"{base_url}/stores/{store_id}/merchant-ceo/chat",
                        method="POST",
                        payload={
                            "message": EBAY_RESEARCH_PROMPT,
                            "client_now": "2026-08-23T12:00:00+08:00",
                            "client_timezone": "Asia/Shanghai",
                        },
                        token=token,
                    )
                    after_status, settings_after = request_json(
                        f"{base_url}/stores/{store_id}/model/settings",
                        token=token,
                    )
                    quota_after = (settings_after.get("model_settings") or {}).get("platform_trial_quota") or {}
                    repository = SaaSRepository(db_path, database_engine="sqlite", database_url="")
                    tasks = repository.list_tasks(company_id=company_id, store_id=store_id, limit=30)
                    reports = repository.list_reports(company_id=company_id, limit=30)
                    audits = repository.list_audit_logs(company_id=company_id, limit=100)
                    blocked_chat = blocked.get("ai_ceo_chat") if isinstance(blocked.get("ai_ceo_chat"), dict) else {}
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)

            child_logs = stdout_path.read_text(encoding="utf-8") + stderr_path.read_text(encoding="utf-8")
            for forbidden_value in (EBAY_RESEARCH_PROMPT, LOCAL_TEST_PASSWORD, LOCAL_SESSION_SECRET, token):
                self.assertNotIn(forbidden_value, child_logs)

            self.assertEqual(200, before_status)
            self.assertEqual(200, after_status)
            used_before = quota_before.get("used")
            used_after = quota_after.get("used")
            self.assertIsInstance(used_before, (int, float))
            self.assertNotIsInstance(used_before, bool)
            self.assertIsInstance(used_after, (int, float))
            self.assertNotIsInstance(used_after, bool)
            self.assertEqual(503, chat_status)
            self.assertEqual("blocked_before_model_chat", blocked_chat.get("status"))
            self.assertEqual(used_before, used_after)
            self.assertIs(blocked.get("usage_consumed"), False)
            self.assertIs(blocked.get("listing_created"), False)
            self.assertIsNone(blocked.get("ai_ceo_market_report"))
            self.assertIsNone(blocked.get("ai_ceo_market_report_delivery"))
            self.assertFalse([item for item in reports if item.get("report_type") == "ai_ceo.market_research"])
            attempts = [item for item in tasks if item.get("task_type") == "merchant_ceo_chat_attempt"]
            self.assertTrue(
                attempts,
                "a pre-model dependency failure must persist a non-billable merchant_ceo_chat_attempt",
            )
            attempt = attempts[0]
            attempt_input = attempt.get("input") if isinstance(attempt.get("input"), dict) else {}
            attempt_output = attempt.get("output") if isinstance(attempt.get("output"), dict) else {}
            self.assertLessEqual(set(attempt_input), APPROVED_ATTEMPT_INPUT_KEYS)
            attempt_input_text = json.dumps(attempt_input, ensure_ascii=False, sort_keys=True)
            for forbidden_value in (EBAY_RESEARCH_PROMPT, LOCAL_TEST_PASSWORD, LOCAL_SESSION_SECRET, token):
                self.assertNotIn(forbidden_value, attempt_input_text)
            self.assertNotIn("message", attempt_input)
            self.assertNotIn("prompt", attempt_input)
            for value in string_leaf_values(attempt_input):
                normalized_value = value.casefold()
                for marker in SECRET_LIKE_VALUE_MARKERS:
                    self.assertNotIn(marker, normalized_value)
            self.assertEqual("blocked", attempt.get("status"))
            self.assertIs(attempt_input.get("model_usage_required"), False)
            self.assertEqual("blocked_model_connection", attempt_output.get("attempt_state"))
            self.assertEqual("platform_model_default_not_configured", attempt_output.get("failure_code"))
            metered_tasks = [
                item
                for item in tasks
                if item.get("task_type") == "merchant_ceo_chat"
                and item.get("input", {}).get("model_usage_required") is not False
            ]
            self.assertFalse(metered_tasks, "a pre-model failure must not create a metered model task")
            create_audits = [
                item
                for item in audits
                if item.get("action_type") == "task.create"
                and item.get("target_id") == attempt.get("task_id")
                and item.get("details", {}).get("task_type") == "merchant_ceo_chat_attempt"
            ]
            status_audits = [
                item
                for item in audits
                if item.get("action_type") == "task.status.update"
                and item.get("target_id") == attempt.get("task_id")
                and item.get("details", {}).get("status") == "blocked"
            ]
            self.assertTrue(create_audits, "attempt creation must be tenant-auditable")
            self.assertTrue(status_audits, "attempt blocked status must be tenant-auditable")

    def test_ticker_company_research_is_not_an_ebay_market_report(self) -> None:
        message = "帮我查一下 AAOI 这家公司产品和市场怎么样"
        answer = "公开来源显示，AAOI 的产品在目标市场增长。"
        _route, chat = route_and_chat(message, answer)
        self.assertFalse(
            _looks_like_ai_ceo_market_research_turn(message=message, chat=chat),
            "ticker/company research is not a merchant request to create an eBay Listing artifact",
        )

    def test_generic_cloud_price_search_is_not_an_ebay_market_report(self) -> None:
        message = "帮我查一下腾讯云服务器最新价格"
        answer = "公开市场资料显示，该产品当前价格为每月 90 元。"
        _route, chat = route_and_chat(message, answer)
        self.assertFalse(
            _looks_like_ai_ceo_market_research_turn(message=message, chat=chat),
            "generic web research must not become an eBay Listing artifact because the answer says product and market",
        )

    def test_generic_cloud_cost_analysis_does_not_enter_ebay_workflow_or_report(self) -> None:
        message = "帮我分析腾讯云费用"
        answer = "这是云服务产品的市场费用分析。"
        route, chat = route_and_chat(message, answer)
        self.assertNotEqual(
            route,
            AI_CEO_ROUTE_EBAY_WORKFLOW,
            "the generic words 分析 + 费用 must not route unrelated cloud-cost questions into an eBay workflow",
        )
        self.assertFalse(_looks_like_ai_ceo_market_research_turn(message=message, chat=chat))

    def test_market_report_audit_readiness_matches_the_actual_handoff(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jiejing-ai-ceo-audit-red-", ignore_cleanup_errors=True) as temp:
            repository = SaaSRepository(
                Path(temp) / "saas.sqlite",
                database_engine="sqlite",
                database_url="",
            )
            fixture = repository.create_user_with_company(
                email="ai-ceo-audit-red@example.test",
                password=LOCAL_TEST_PASSWORD,
                company_name="AI CEO audit RED",
            )
            company_id = fixture["company"]["company_id"]
            user_id = fixture["user"]["user_id"]
            store = repository.create_store(
                company_id=company_id,
                user_id=user_id,
                payload={"platform": "ebay", "store_name": "Audit RED Store", "marketplace": "EBAY_US"},
            )
            task = repository.create_task(
                company_id=company_id,
                store_id=store["store_id"],
                user_id=user_id,
                task_type="merchant_ceo_chat_attempt",
                title="Rejected market report audit contract",
                input_data={"model_usage_required": False},
            )
            saved = repository.save_ai_ceo_market_research_report(
                task=task,
                message="请做一份 eBay 市场调研报告并推荐一个商品。",
                chat={
                    "answer": "当前证据不足，不能形成可导入 Listing 的商品结论。",
                    "route": "ebay_workflow",
                    "route_label": "eBay 经营任务",
                    "status": "source_backed_market_report_draft",
                    "answer_quality": {"accepted": False},
                    "source_records": [],
                    "work_records": [],
                    "confirmation_items": [],
                },
            )
            self.assertIsNotNone(saved)
            report = saved.get("report") if isinstance(saved, dict) else {}
            handoff = report.get("listing_handoff") if isinstance(report.get("listing_handoff"), dict) else {}
            self.assertIs(handoff.get("ready_for_listing_draft"), False)
            delivery = build_ai_ceo_market_report_delivery(saved)
            self.assertIsInstance(delivery, dict)
            self.assertIs(delivery.get("listing_import_ready"), handoff.get("ready_for_listing_draft"))
            matching_audits = [
                item
                for item in repository.list_audit_logs(company_id=company_id, limit=50)
                if item.get("action_type") == "ai_ceo.market_research.saved" and item.get("target_id") == saved.get("report_id")
            ]
            self.assertTrue(matching_audits, "saved market report must leave tenant-scoped audit evidence")
            audit = matching_audits[0]
            self.assertIs(
                audit.get("details", {}).get("ready_for_listing_draft"),
                handoff.get("ready_for_listing_draft"),
                "audit readiness must match the persisted non-importable Listing handoff",
            )


class AiCeoFrontendAuthorityRedTests(unittest.TestCase):
    def test_non_importable_delivery_does_not_render_listing_cta(self) -> None:
        render_delivery = function_body(APP_JS, "renderSaasAiCeoMarketReportDeliveryMarkup")
        result = run_node_json(
            "\n".join(
                [
                    "const normalizeSaasAiCeoLatestTurn = (value) => value;",
                    "const saasAiCeoMarketProductLabel = () => '';",
                    "const saasIsConcreteProductLabel = () => false;",
                    "const rememberSaasAiCeoMarketImportTarget = () => null;",
                    "const escapeHtml = (value) => String(value ?? '');",
                    render_delivery,
                    "const html = renderSaasAiCeoMarketReportDeliveryMarkup({",
                    "  market_report_delivery: {",
                    "    report_id: 'report_blocked',",
                    "    report_type: 'ai_ceo.market_research',",
                    "    structured_report_saved: true,",
                    "    listing_import_ready: false,",
                    "    title: 'AI CEO 市场调研待继续',",
                    "    product: '',",
                    "    source_record_count: 0",
                    "  }",
                    "});",
                    "console.log(JSON.stringify({ hasCta: html.includes('data-saas-action=\\\"ai-ceo-import-market-to-listing\\\"'), html }));",
                ]
            )
        )
        self.assertFalse(
            result["hasCta"],
            "a saved work record with listing_import_ready=false may be shown, but it must not offer Listing import",
        )

    def test_missing_backend_report_does_not_create_frontend_authoritative_report(self) -> None:
        ensure_report = function_body(APP_JS, "ensureSaasAiCeoMarketReportRecordFromTurn")
        result = run_node_json(
            "\n".join(
                [
                    "let localBuildCount = 0;",
                    "let upsertCount = 0;",
                    "const normalizeSaasAiCeoLatestTurn = (value) => value;",
                    "const saasAiCeoMarketReportRecordFromTurn = () => {",
                    "  localBuildCount += 1;",
                    "  return { report_id: 'frontend-report', report_type: 'ai_ceo.market_research' };",
                    "};",
                    "const upsertSaasReportRecord = () => { upsertCount += 1; };",
                    "const saasAiCeoMarketReportDeliveryFromRecord = (record) => ({ report_id: record.report_id });",
                    ensure_report,
                    "const turn = ensureSaasAiCeoMarketReportRecordFromTurn({ assistant_id: 'assistant-1', pending: false }, null);",
                    "console.log(JSON.stringify({ localBuildCount, upsertCount, reportId: turn.market_report_id || '', delivery: turn.market_report_delivery || null }));",
                ]
            )
        )
        self.assertEqual(
            result,
            {"localBuildCount": 0, "upsertCount": 0, "reportId": "", "delivery": None},
            "only an authoritative backend report/delivery may create a report id or Listing handoff in the frontend",
        )

    def test_command_is_not_synced_to_listing_before_backend_response(self) -> None:
        submit_command = function_body(APP_JS, "handleSaasCeoCommandSubmit")
        result = run_node_json(
            "\n".join(
                [
                    "const events = [];",
                    "const state = { saasLastCeoCommand: null, saasCeoCommandChatVisible: false, saasAiCeoLatestTurn: null, view: 'cockpit' };",
                    "const saasMerchantWorkbenchContext = () => ({});",
                    "const buildSaasCeoCommand = (text) => ({ id: 'cmd-1', text, route: 'general_chat', memory_policy: 'transient_no_long_term_memory' });",
                    "const persistSaasLastCeoCommand = () => null;",
                    "const recordSaasCeoCommandSourceRecord = () => null;",
                    "const hashString = () => 1;",
                    "const buildSaasLocalClockAnswer = () => null;",
                    "const syncSaasCeoCommandToListing = () => { events.push('listing-sync'); return true; };",
                    "const addCeoMessage = () => null;",
                    "const scheduleSaasAiCeoPendingWatchdog = () => null;",
                    "const requestSaasAiCeoChat = () => { events.push('backend-request'); return new Promise(() => {}); };",
                    "const document = { querySelector: () => null };",
                    "const refreshSaasCeoRoutingTaskCard = () => null;",
                    submit_command,
                    "handleSaasCeoCommandSubmit('普通股票问题');",
                    "console.log(JSON.stringify({ events }));",
                ]
            )
        )
        self.assertEqual(
            result["events"],
            ["backend-request"],
            "submitting a chat may contact the backend, but must not pre-route unvalidated text into the Listing workspace",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

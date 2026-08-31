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
from jiejing_saas.api_server import (  # noqa: E402
    build_ai_ceo_market_report_delivery,
    build_ai_ceo_pre_model_attempt_input,
)
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


def request_json_without_transport_error(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Turn an unhandled-handler disconnect into an assertion-friendly result."""

    try:
        return request_json(url, method=method, payload=payload, token=token)
    except Exception as exc:  # The RED contract must fail assertions, never error in the test harness.
        return 0, {"transport_error_type": exc.__class__.__name__, "secret_exposed": False}


def fault_injection_sitecustomize(fault_mode: str) -> str:
    """Build a hermetic child-only fault injector for attempt-terminalization tests."""

    return f'''\
from jiejing_saas import api_server as _api
from jiejing_saas.repository import SaaSRepository as _Repository

_FAULT_MODE = {fault_mode!r}
_SENTINEL = "private raw internal failure text must never escape"

class _SuccessfulModelClient:
    name = "unit_model_client"
    model = "unit-model"
    endpoint = ""

    def generate_text(self, **kwargs):
        callback = kwargs.get("on_text_delta")
        text = "捷境帮助跨境电商商家整理经营信息并形成可审核的工作草稿。"
        if callable(callback):
            callback(text)
        return {{
            "text": text,
            "finish_reason": "stop",
            "model": self.model,
            "_usage": {{"input_tokens": 11, "output_tokens": 17, "total_tokens": 28}},
        }}

def _resolved_model(self, **kwargs):
    return {{
        "status": "resolved",
        "mode": "account_byok",
        "secret_ref": "ref_unit_only",
        "secret_ref_scope": "account",
        "provider_key": "unit_provider",
        "provider_label": "Unit provider",
        "model": "unit-model",
        "merchant_pays_provider_directly": True,
        "jiejing_pays_provider_usage": False,
        "model_client": _SuccessfulModelClient(),
        "frontend_gets_model_api_key": False,
        "secret_exposed": False,
    }}

_api.SaaSBackendHandler._resolve_model_client_for_store = _resolved_model

if _FAULT_MODE in {{"provider_execution_exception", "model_task_creation_exception"}}:
    _original_resolved_model = _resolved_model
    def _platform_resolved_model(self, **kwargs):
        resolved = _original_resolved_model(self, **kwargs)
        return {{
            **resolved,
            "mode": "platform_managed_default",
            "secret_ref": "",
            "secret_ref_scope": "platform",
            "merchant_pays_provider_directly": False,
            "jiejing_pays_provider_usage": True,
        }}
    _api.SaaSBackendHandler._resolve_model_client_for_store = _platform_resolved_model

if _FAULT_MODE == "provider_execution_exception":
    class _FailingModelClient:
        name = "unit_failing_model_client"
        model = "unit-model"
        endpoint = ""

        def generate_text(self, **kwargs):
            raise TimeoutError(_SENTINEL)

    def _provider_failure_model(self, **kwargs):
        resolved = _platform_resolved_model(self, **kwargs)
        return {{**resolved, "model_client": _FailingModelClient()}}
    _api.SaaSBackendHandler._resolve_model_client_for_store = _provider_failure_model

if _FAULT_MODE == "model_task_creation_exception":
    _original_create_task = _Repository.create_task
    def _fail_first_metered_task_create(self, *args, **kwargs):
        if kwargs.get("task_type") == "merchant_ceo_chat" and not getattr(self, "_red_model_task_create_failed", False):
            self._red_model_task_create_failed = True
            raise RuntimeError(_SENTINEL)
        return _original_create_task(self, *args, **kwargs)
    _Repository.create_task = _fail_first_metered_task_create

if _FAULT_MODE == "quota_exception":
    def _quota_exception(self, identity, action_unit, *args, **kwargs):
        if action_unit == "ai_ceo_task":
            raise RuntimeError(_SENTINEL)
        return True
    _api.SaaSBackendHandler._require_quota = _quota_exception
else:
    def _quota_allowed(self, *args, **kwargs):
        return True
    _api.SaaSBackendHandler._require_quota = _quota_allowed

if _FAULT_MODE == "command_persistence_exception":
    _original_save_command = _Repository.save_merchant_ceo_command
    def _save_command_then_fail(self, *args, **kwargs):
        call_count = int(getattr(self, "_red_command_save_count", 0)) + 1
        self._red_command_save_count = call_count
        if call_count >= 2:
            raise RuntimeError(_SENTINEL)
        return _original_save_command(self, *args, **kwargs)
    _Repository.save_merchant_ceo_command = _save_command_then_fail

if _FAULT_MODE == "metering_persistence_exception":
    def _record_model_usage_failure(self, *args, **kwargs):
        raise RuntimeError(_SENTINEL)
    _Repository.record_model_usage = _record_model_usage_failure
'''


def run_attempt_fault_fixture(fault_mode: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"jiejing-ai-ceo-{fault_mode}-", ignore_cleanup_errors=True) as temp:
        temp_root = Path(temp)
        hook_root = temp_root / "python-hook"
        hook_root.mkdir(parents=True, exist_ok=True)
        (hook_root / "sitecustomize.py").write_text(
            fault_injection_sitecustomize(fault_mode),
            encoding="utf-8",
        )
        db_path = temp_root / "saas.sqlite"
        runtime_db_path = temp_root / "runtime.sqlite"
        stdout_path = temp_root / "backend-stdout.log"
        stderr_path = temp_root / "backend-stderr.log"
        port = free_port()
        env = isolated_backend_env(port=port)
        env["PYTHONPATH"] = os.pathsep.join((str(hook_root), str(ROOT)))
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
                    str(temp_root / "output"),
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
                        "email": f"{fault_mode}@example.test",
                        "password": LOCAL_TEST_PASSWORD,
                        "company_name": f"AI CEO {fault_mode}",
                    },
                )
                if register_status != 201:
                    raise AssertionError(f"fault fixture registration failed: {register_status}")
                token = str(registered.get("token") or "")
                company_id = str((registered.get("company") or {}).get("company_id") or "")
                store_status, store_payload = request_json(
                    f"{base_url}/stores",
                    method="POST",
                    payload={"platform": "ebay", "store_name": "Fault RED Store", "marketplace": "EBAY_US"},
                    token=token,
                )
                if store_status != 201:
                    raise AssertionError(f"fault fixture store creation failed: {store_status}")
                store_id = str((store_payload.get("store") or {}).get("store_id") or "")
                response_status, response_payload = request_json_without_transport_error(
                    f"{base_url}/stores/{store_id}/merchant-ceo/chat",
                    method="POST",
                    payload={
                        "message": "请用一句话介绍捷境平台。",
                        "command": {"id": f"cmd-{fault_mode}", "text": "请用一句话介绍捷境平台。"},
                        "client_now": "2026-08-23T12:00:00+08:00",
                        "client_timezone": "Asia/Shanghai",
                    },
                    token=token,
                )
                repository = SaaSRepository(db_path, database_engine="sqlite", database_url="")
                tasks = repository.list_tasks(company_id=company_id, store_id=store_id, limit=30)
                audit_logs = repository.list_audit_logs(company_id=company_id, limit=100)
                with repository._connect() as conn:
                    model_usage_rows = [
                        dict(row)
                        for row in conn.execute(
                            "select * from model_usage_ledger where company_id = ? order by created_at",
                            (company_id,),
                        ).fetchall()
                    ]
                settings_status, settings_payload = request_json(
                    f"{base_url}/stores/{store_id}/model/settings",
                    token=token,
                )
                platform_trial_quota = (
                    (settings_payload.get("model_settings") or {}).get("platform_trial_quota") or {}
                    if settings_status == 200
                    else {}
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        logs = stdout_path.read_text(encoding="utf-8") + stderr_path.read_text(encoding="utf-8")
        attempts = [item for item in tasks if item.get("task_type") == "merchant_ceo_chat_attempt"]
        return {
            "response_status": response_status,
            "response_payload": response_payload,
            "attempts": attempts,
            "tasks": tasks,
            "audit_logs": audit_logs,
            "model_usage_rows": model_usage_rows,
            "platform_trial_quota": platform_trial_quota,
            "logs": logs,
        }


class AiCeoBackendAuthorityRedTests(unittest.TestCase):
    def _assert_safe_attempt_failure_audit(
        self,
        *,
        result: dict[str, Any],
        attempt_id: str,
        expected_stage: str,
        expected_error_type: str,
    ) -> None:
        matching = [
            item
            for item in result.get("audit_logs") or []
            if item.get("target_id") == attempt_id
            and (item.get("details") or {}).get("stage") == expected_stage
            and (item.get("details") or {}).get("error_type") == expected_error_type
        ]
        self.assertTrue(
            matching,
            "attempt failure audit must preserve a fixed failure stage and a sanitized error category",
        )
        serialized = json.dumps(matching, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("private raw internal failure text must never escape", serialized)
        self.assertNotIn("exception_message", serialized.lower())

    def test_provider_call_failure_is_metered_and_trial_counted(self) -> None:
        result = run_attempt_fault_fixture("provider_execution_exception")
        self.assertTrue(500 <= int(result.get("response_status") or 0) < 600)
        attempts = result.get("attempts") or []
        model_tasks = [item for item in result.get("tasks") or [] if item.get("task_type") == "merchant_ceo_chat"]
        usage_rows = result.get("model_usage_rows") or []
        self.assertEqual(1, len(attempts))
        self.assertEqual(1, len(model_tasks), "a provider call that reached the network still needs one metered task fact")
        self.assertEqual(1, len(usage_rows), "provider-call telemetry must survive the provider exception")
        attempt = attempts[0]
        attempt_output = attempt.get("output") if isinstance(attempt.get("output"), dict) else {}
        self.assertIs(result.get("response_payload", {}).get("usage_consumed"), True)
        self.assertIs(attempt_output.get("usage_consumed"), True)
        self.assertEqual(model_tasks[0].get("task_id"), attempt_output.get("actual_task_id"))
        self.assertEqual(model_tasks[0].get("task_id"), usage_rows[0].get("task_id"))
        self.assertGreaterEqual(int(usage_rows[0].get("request_count") or 0), 1)
        self.assertEqual(1, int((result.get("platform_trial_quota") or {}).get("used") or 0))
        self._assert_safe_attempt_failure_audit(
            result=result,
            attempt_id=str(attempt.get("task_id") or ""),
            expected_stage="model_provider",
            expected_error_type="model_network_or_timeout",
        )

    def test_first_metered_task_create_failure_recovers_one_trial_fact(self) -> None:
        result = run_attempt_fault_fixture("model_task_creation_exception")
        self.assertTrue(500 <= int(result.get("response_status") or 0) < 600)
        attempts = result.get("attempts") or []
        model_tasks = [item for item in result.get("tasks") or [] if item.get("task_type") == "merchant_ceo_chat"]
        usage_rows = result.get("model_usage_rows") or []
        self.assertEqual(1, len(attempts))
        self.assertEqual(1, len(model_tasks), "recovery must create exactly one idempotent metered task after the first create fault")
        self.assertEqual(1, len(usage_rows), "recovered task must retain one model usage ledger fact")
        attempt = attempts[0]
        attempt_output = attempt.get("output") if isinstance(attempt.get("output"), dict) else {}
        self.assertIs(result.get("response_payload", {}).get("usage_consumed"), True)
        self.assertIs(attempt_output.get("usage_consumed"), True)
        self.assertEqual(model_tasks[0].get("task_id"), attempt_output.get("actual_task_id"))
        self.assertEqual(model_tasks[0].get("task_id"), usage_rows[0].get("task_id"))
        self.assertEqual(1, int((result.get("platform_trial_quota") or {}).get("used") or 0))
        self._assert_safe_attempt_failure_audit(
            result=result,
            attempt_id=str(attempt.get("task_id") or ""),
            expected_stage="model_task_persistence",
            expected_error_type="RuntimeError",
        )

    def test_unexpected_attempt_failure_audit_is_stage_categorized(self) -> None:
        result = run_attempt_fault_fixture("quota_exception")
        attempts = result.get("attempts") or []
        self.assertEqual(1, len(attempts))
        self._assert_safe_attempt_failure_audit(
            result=result,
            attempt_id=str(attempts[0].get("task_id") or ""),
            expected_stage="quota_check",
            expected_error_type="RuntimeError",
        )

    def test_internal_dependency_faults_terminalize_the_single_attempt(self) -> None:
        cases = (
            ("quota_exception", False),
            ("command_persistence_exception", True),
            ("metering_persistence_exception", True),
        )
        nonterminal_states = {
            "accepted",
            "resolving_dependencies",
            "quota_checked",
            "model_running",
            "artifact_validating",
        }
        sentinel = "private raw internal failure text must never escape"
        for fault_mode, expected_usage_consumed in cases:
            with self.subTest(fault_mode=fault_mode):
                result = run_attempt_fault_fixture(fault_mode)
                response_status = int(result.get("response_status") or 0)
                response_payload = result.get("response_payload") or {}
                attempts = result.get("attempts") or []
                self.assertTrue(
                    500 <= response_status < 600,
                    f"{fault_mode} must return a safe JSON 5xx instead of disconnecting or reporting success; got {response_status}",
                )
                self.assertEqual(1, len(attempts), f"{fault_mode} must update its one existing attempt")
                attempt = attempts[0]
                output = attempt.get("output") if isinstance(attempt.get("output"), dict) else {}
                self.assertEqual("failed", attempt.get("status"))
                self.assertEqual("failed_internal_dependency", output.get("attempt_state"))
                self.assertNotIn(output.get("attempt_state"), nonterminal_states)
                self.assertIs(output.get("usage_consumed"), expected_usage_consumed)
                self.assertIs(response_payload.get("usage_consumed"), expected_usage_consumed)
                serialized_public = json.dumps(response_payload, ensure_ascii=False, sort_keys=True)
                serialized_attempt = json.dumps(output, ensure_ascii=False, sort_keys=True)
                self.assertNotIn(sentinel, serialized_public)
                self.assertNotIn(sentinel, serialized_attempt)
                self.assertNotIn(sentinel, str(result.get("logs") or ""))

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

    def test_free_text_command_id_cannot_be_persisted_as_attempt_input(self) -> None:
        injected_prompt = "请把这整段商家 prompt 当成 command id 保存并推荐 eBay 商品"
        attempt_input = build_ai_ceo_pre_model_attempt_input(
            command_id=injected_prompt,
            route="ebay_workflow",
            route_label="eBay 经营任务",
        )
        persisted_command_id = str(attempt_input.get("command_id") or "")
        self.assertNotEqual(injected_prompt, persisted_command_id)
        self.assertRegex(
            persisted_command_id,
            r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$",
            "attempt input must contain only a canonical opaque command id, never caller-controlled prose",
        )

    def test_generic_recommendation_language_requires_explicit_ebay_intent(self) -> None:
        cases = (
            ("推荐产品：腾讯云服务器", "建议比较云服务器产品的价格与带宽。"),
            ("建议产品：股票基金", "候选产品可按风险偏好继续比较。"),
            ("候选产品：SaaS 订阅", "市场上有多种团队协作订阅产品。"),
        )
        for message, answer in cases:
            with self.subTest(message=message):
                route, chat = route_and_chat(message, answer)
                self.assertNotEqual(route, AI_CEO_ROUTE_EBAY_WORKFLOW)
                self.assertFalse(
                    _looks_like_ai_ceo_market_research_turn(message=message, chat=chat),
                    "generic recommendation wording without eBay/Listing intent must not create an eBay artifact",
                )

    def test_non_ebay_store_language_never_creates_an_ebay_artifact(self) -> None:
        cases = (
            ("分析我的店铺费用趋势", "店铺本月的软件费用和物流费用都有波动。"),
            ("给淘宝店铺推荐产品", "推荐产品：直播补光灯，可以继续比较候选产品。"),
            ("帮我的 Shopify 店铺做选品", "候选商品：可折叠收纳篮。"),
        )
        for message, answer in cases:
            with self.subTest(message=message):
                route, chat = route_and_chat(message, answer)
                self.assertNotEqual(route, AI_CEO_ROUTE_EBAY_WORKFLOW)
                self.assertFalse(
                    _looks_like_ai_ceo_market_research_turn(message=message, chat=chat),
                    "a non-eBay shop request must never be persisted as an eBay market artifact",
                )

        ebay_message = "给我的 eBay 店铺推荐一个商品并整理 Listing 选品报告"
        ebay_route, ebay_chat = route_and_chat(ebay_message, "候选商品：可折叠硅胶漏斗。")
        self.assertEqual(AI_CEO_ROUTE_EBAY_WORKFLOW, ebay_route)
        self.assertTrue(_looks_like_ai_ceo_market_research_turn(message=ebay_message, chat=ebay_chat))

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

    def test_market_report_contract_blocks_zero_evidence_and_supplier_fact_gaps(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jiejing-ai-ceo-artifact-red-", ignore_cleanup_errors=True) as temp:
            repository = SaaSRepository(Path(temp) / "saas.sqlite", database_engine="sqlite", database_url="")
            fixture = repository.create_user_with_company(
                email="ai-ceo-artifact-red@example.test",
                password=LOCAL_TEST_PASSWORD,
                company_name="AI CEO artifact RED",
            )
            company_id = fixture["company"]["company_id"]
            user_id = fixture["user"]["user_id"]
            store = repository.create_store(
                company_id=company_id,
                user_id=user_id,
                payload={"platform": "ebay", "store_name": "Artifact RED Store", "marketplace": "EBAY_US"},
            )
            task = repository.create_task(
                company_id=company_id,
                store_id=store["store_id"],
                user_id=user_id,
                task_type="merchant_ceo_chat",
                title="Artifact completeness contract",
                input_data={"model_usage_required": True},
            )
            saved = repository.save_ai_ceo_market_research_report(
                task=task,
                message="请为我的 eBay 美国店铺选一个商品并整理 Listing 市场调研。",
                chat={
                    "answer": "### 候选商品卡\n#### 候选商品 1: 可折叠硅胶漏斗\n推荐度评分：88/100",
                    "route": "ebay_workflow",
                    "route_label": "eBay 经营任务",
                    "status": "model_answered",
                    "answer_quality": {"accepted": True},
                    "source_records": [],
                    "work_records": [],
                    "confirmation_items": [],
                },
            )
            self.assertIsNotNone(saved)
            report = saved.get("report") if isinstance(saved, dict) else {}
            required_fields = {
                "artifact_type",
                "artifact_version",
                "merchant_intent",
                "candidate_products",
                "candidate_count",
                "selected_candidate_id",
                "evidence_status",
                "supplier_fact_status",
                "listing_import_ready",
                "blocked_by",
                "source_records",
                "secret_exposed",
            }
            self.assertFalse(required_fields - set(report), f"missing authoritative artifact fields: {required_fields - set(report)}")
            self.assertEqual("ai_ceo.market_research", report.get("artifact_type"))
            self.assertEqual("ebay_product_research", report.get("merchant_intent"))
            self.assertIs(report.get("listing_import_ready"), False)
            self.assertTrue(report.get("blocked_by"), "zero evidence and supplier fact gaps must remain explicit")
            handoff = report.get("listing_handoff") if isinstance(report.get("listing_handoff"), dict) else {}
            delivery = build_ai_ceo_market_report_delivery(saved)
            matching_audits = [
                item
                for item in repository.list_audit_logs(company_id=company_id, limit=50)
                if item.get("action_type") == "ai_ceo.market_research.saved" and item.get("target_id") == saved.get("report_id")
            ]
            self.assertTrue(matching_audits)
            self.assertIs(handoff.get("ready_for_listing_draft"), False)
            self.assertIs(delivery.get("listing_import_ready"), False)
            self.assertIs(matching_audits[0].get("details", {}).get("ready_for_listing_draft"), False)

    def test_complete_but_unverified_supplier_facts_are_explicitly_blocked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jiejing-ai-ceo-unverified-supplier-red-", ignore_cleanup_errors=True) as temp:
            repository = SaaSRepository(Path(temp) / "saas.sqlite", database_engine="sqlite", database_url="")
            task = repository.create_task(
                company_id="company_unverified_supplier",
                store_id="store_unverified_supplier",
                user_id="user_unverified_supplier",
                task_type="merchant_ceo_chat",
                title="Unverified supplier fact contract",
                input_data={"model_usage_required": True},
            )
            saved = repository.save_ai_ceo_market_research_report(
                task=task,
                message="请为我的 eBay 店铺选一个商品并整理 Listing 市场调研。",
                chat={
                    "answer": (
                        "### 候选商品卡\n"
                        "候选商品 1：可折叠硅胶漏斗\n"
                        "推荐度评分：88/100\n"
                        "### 最值得测试：可折叠硅胶漏斗"
                    ),
                    "route": "ebay_workflow",
                    "route_label": "eBay 经营任务",
                    "status": "model_answered",
                    "answer_quality": {"accepted": True},
                    "source_records": [{"title": "公开市场来源", "url": "https://example.test/source"}],
                    "supplier_facts": {
                        "material": "food-grade silicone",
                        "package_weight_g": 120,
                        "package_dimensions_cm": "12 x 10 x 4",
                        "item_location": "Shenzhen, China",
                        "unit_cost": "CNY 8.50",
                    },
                    "supplier_facts_verified": False,
                },
            )
            self.assertIsNotNone(saved)
            report = saved.get("report") if isinstance(saved, dict) else {}
            self.assertEqual("unverified", report.get("supplier_fact_status"))
            self.assertIs(report.get("listing_import_ready"), False)
            self.assertIn("supplier_facts_unverified", report.get("blocked_by") or [])
            self.assertNotIn("可导入", str(report.get("merchant_readable_summary") or ""))
            handoff = report.get("listing_handoff") if isinstance(report.get("listing_handoff"), dict) else {}
            self.assertIn("supplier_facts_unverified", handoff.get("blocked_by") or [])


class AiCeoFrontendAuthorityRedTests(unittest.TestCase):
    def test_clicked_report_id_never_falls_back_to_same_assistant_or_latest_report(self) -> None:
        resolver = function_body(APP_JS, "saasAiCeoMarketResearchTurnForImport")
        result = run_node_json(
            "\n".join(
                [
                    "const wrongRemembered = { assistant_id: 'assistant-shared', market_report_id: 'report-other', assistant_text: 'other report' };",
                    "const wrongLatest = { assistant_id: 'assistant-latest', market_report_id: 'report-latest', assistant_text: 'latest report' };",
                    "const saasAiCeoMarketImportTargets = new Map([['assistant:assistant-shared', wrongRemembered]]);",
                    "const state = { saasReports: [] };",
                    "const normalizeSaasAiCeoLatestTurn = (value) => value && typeof value === 'object' ? value : null;",
                    "const saasAiCeoMarketTurnFromReport = (record) => record;",
                    "const saasAiCeoMarketResearchCandidates = () => [wrongLatest];",
                    "const saasAiCeoMarketResearchEligibility = (turn) => ({ eligible: Boolean(turn), latest: turn });",
                    "const saasAiCeoMarketResearchTurnMatchesClickedProduct = () => true;",
                    resolver,
                    "const selected = saasAiCeoMarketResearchTurnForImport({ dataset: { reportId: 'report-wanted', aiCeoAssistantId: 'assistant-shared', productName: 'Wanted' } });",
                    "console.log(JSON.stringify({ selectedReportId: selected?.market_report_id || '' }));",
                ]
            )
        )
        self.assertEqual(
            "",
            result["selectedReportId"],
            "when a click carries reportId, neither a same-assistant report nor remembered/latest state may substitute for it",
        )

    def test_non_importable_delivery_does_not_render_listing_cta(self) -> None:
        render_delivery = function_body(APP_JS, "renderSaasAiCeoMarketReportDeliveryMarkup")
        result = run_node_json(
            "\n".join(
                [
                    "const normalizeSaasAiCeoLatestTurn = (value) => value;",
                    "const saasAiCeoMarketProductLabel = () => '';",
                    "const saasIsConcreteProductLabel = () => false;",
                    "const rememberSaasAiCeoMarketImportTarget = () => null;",
                    "const saasAuthoritativeAiCeoMarketReportForTurn = () => null;",
                    "const saasAiCeoMarketReportCanStartBlockedListingDraft = () => false;",
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
                    "const saasMerchantProjectRouteId = () => '';",
                    "const saasCurrentMerchantProjectId = () => '';",
                    "const saasAiCeoCommandUsesProductTaskContext = () => false;",
                    "const setSaasAiCeoTaskContextState = () => null;",
                    "const refreshSaasAiCeoTaskContext = () => null;",
                    "const prepareSaasNewListingProjectRequest = (text) => ({ active: false, blocked: false, commandText: text, sourceAssetIds: [] });",
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

    def test_logical_503_does_not_sync_listing_and_states_no_usage_or_draft(self) -> None:
        submit_command = function_body(APP_JS, "handleSaasCeoCommandSubmit")
        result = run_node_json(
            "\n".join(
                [
                    "(async () => {",
                    "let syncCount = 0; let renderedAnswer = '';",
                    "const state = { saasLastCeoCommand: null, saasCeoCommandChatVisible: false, saasAiCeoLatestTurn: null, saasReports: [], view: 'other' };",
                    "const saasMerchantWorkbenchContext = () => ({});",
                    "const buildSaasCeoCommand = (text) => ({ id: 'cmd-503', text, route: 'ebay_workflow', memory_policy: 'transient_no_long_term_memory' });",
                    "const persistSaasLastCeoCommand = () => null; const recordSaasCeoCommandSourceRecord = () => null;",
                    "const hashString = () => 1; const buildSaasLocalClockAnswer = () => null; const addCeoMessage = () => null;",
                    "const scheduleSaasAiCeoPendingWatchdog = () => null; const updateCeoAssistantStreamingMessage = () => null;",
                    "const requestSaasAiCeoChat = () => Promise.resolve({ _http_status: 503, usage_consumed: false, listing_created: false, ai_ceo_market_report: null, ai_ceo_market_report_delivery: null, ai_ceo_chat: { status: 'blocked_before_model_chat', answer: 'AI 连接暂时不可用。', route: 'ebay_workflow', blocked_by: ['platform_model_default_not_configured'] } });",
                    "const saasMerchantProjectRouteId = () => ''; const saasCurrentMerchantProjectId = () => '';",
                    "const saasAiCeoCommandUsesProductTaskContext = () => false; const setSaasAiCeoTaskContextState = () => null; const refreshSaasAiCeoTaskContext = () => null;",
                    "const prepareSaasNewListingProjectRequest = (text) => ({ active: false, blocked: false, commandText: text, sourceAssetIds: [] });",
                    "const normalizeSaasAiCeoLatestTurn = (value) => value && typeof value === 'object' ? value : null;",
                    "const saasPendingNewListingProjectOutcomeUnknown = () => false; const saasNormalizeListingProjectIdentity = () => null;",
                    "const isSaasUnrecoverableSessionError = () => false;",
                    "const normalizeSaasAiCeoMarketReportDelivery = () => null; const saasAiCeoProductizedAnswerText = (value) => String(value || '');",
                    "const normalizeSaasAiCeoSourceRecords = () => []; const normalizeSaasAiCeoWorkRecords = () => []; const normalizeSaasAiCeoConfirmationItems = () => [];",
                    "const ensureSaasAiCeoMarketReportRecordFromTurn = (turn) => turn; const backendSaasCeoCommandFromPayload = () => null;",
                    "const normalizeSaasCeoCommand = (value) => value; const newestSaasCeoCommand = (value) => value;",
                    "const syncSaasCeoCommandToListing = () => { syncCount += 1; return true; };",
                    "const updateCeoAssistantMessage = (_id, answer) => { renderedAnswer = answer; }; const updateSaasAiCeoLatestReply = (turn) => { state.saasAiCeoLatestTurn = turn; }; const upsertSaasAiCeoThreadTurn = () => null;",
                    "const document = { querySelector: () => null }; const replaceJiejingTrustedHtml = () => null; const trustedJiejingHtml = (value) => value; const renderSaasCeoCommandConsole = () => ''; const refreshSaasCeoRoutingTaskCard = () => null;",
                    submit_command,
                    "handleSaasCeoCommandSubmit('请为 eBay 店铺选品');",
                    "await state.saasLastCeoCommandPersistPromise;",
                    "console.log(JSON.stringify({ syncCount, renderedAnswer }));",
                    "})().catch((error) => { console.error(error); process.exit(1); });",
                ]
            )
        )
        self.assertEqual(0, result["syncCount"], "a logical HTTP 503 must never populate the Listing workspace")
        for expected in ("未调用模型", "未消耗次数", "未生成草稿"):
            self.assertIn(expected, result["renderedAnswer"])

    def test_legacy_local_or_untyped_reports_never_become_authoritative(self) -> None:
        normalize_delivery = function_body(APP_JS, "normalizeSaasAiCeoMarketReportDelivery")
        authoritative_report = function_body(APP_JS, "saasAuthoritativeAiCeoMarketReportForTurn")
        result = run_node_json(
            "\n".join(
                [
                    "const publicRuntimeText = (value) => String(value ?? '');",
                    "const normalizeSaasAiCeoLatestTurn = (value) => value;",
                    normalize_delivery,
                    authoritative_report,
                    "const checks = [];",
                    "for (const marker of ['frontend_generated_from_ai_ceo_chat', 'safe_local_only']) {",
                    "  const record = { report_id: `legacy-${marker}`, report_type: 'ai_ceo.market_research', report: { [marker]: true, listing_handoff: { ready_for_listing_draft: true } } };",
                    "  globalThis.state = { saasReports: [record] };",
                    "  const delivery = normalizeSaasAiCeoMarketReportDelivery({ report_id: record.report_id, report_type: 'ai_ceo.market_research', structured_report_saved: true, listing_import_ready: true });",
                    "  checks.push({ marker, authoritative: Boolean(saasAuthoritativeAiCeoMarketReportForTurn({ market_report_id: record.report_id, market_report_delivery: delivery })) });",
                    "}",
                    "const backendRecord = { report_id: 'untyped-report', report_type: 'ai_ceo.market_research', report: { listing_handoff: { ready_for_listing_draft: true } } };",
                    "globalThis.state = { saasReports: [backendRecord] };",
                    "const untyped = normalizeSaasAiCeoMarketReportDelivery({ report_id: backendRecord.report_id, structured_report_saved: true, listing_import_ready: true });",
                    "checks.push({ marker: 'missing_report_type', normalizedType: untyped?.report_type || '', authoritative: Boolean(saasAuthoritativeAiCeoMarketReportForTurn({ market_report_id: backendRecord.report_id, market_report_delivery: untyped })) });",
                    "console.log(JSON.stringify({ checks }));",
                ]
            )
        )
        for check in result["checks"]:
            with self.subTest(marker=check["marker"]):
                self.assertFalse(check["authoritative"], f"{check['marker']} must never establish backend artifact authority")
        missing_type = next(item for item in result["checks"] if item["marker"] == "missing_report_type")
        self.assertEqual("", missing_type["normalizedType"], "missing report_type must not default to market research")


if __name__ == "__main__":
    unittest.main(verbosity=2)

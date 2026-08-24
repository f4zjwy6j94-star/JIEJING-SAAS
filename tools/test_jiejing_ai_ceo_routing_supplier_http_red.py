#!/usr/bin/env python3
"""RED contracts for cross-platform routing and merchant supplier-fact intake.

The HTTP fixture is hermetic: it uses temporary SQLite files, a local fake
model/search boundary, and explicit no-network/no-write environment flags.
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

from jiejing_saas.ai_ceo_chat import AI_CEO_ROUTE_EBAY_WORKFLOW, ai_ceo_route_metadata  # noqa: E402
from jiejing_saas.repository import (  # noqa: E402
    ai_ceo_market_artifact_eligible,
    normalize_ai_ceo_supplier_fact_attestation,
)


APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")
LOCAL_TEST_PASSWORD = "local-test-password"
LOCAL_SESSION_SECRET = "local-routing-supplier-red-session-secret"
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
    markers = (f"async function {name}", f"function {name}")
    starts = [source.find(marker) for marker in markers]
    starts = [value for value in starts if value >= 0]
    if not starts:
        raise AssertionError(f"missing JavaScript function: {name}")
    start = min(starts)
    next_function = source.find("\nfunction ", start + 1)
    next_async = source.find("\nasync function ", start + 1)
    ends = [value for value in (next_function, next_async) if value > start]
    return source[start : min(ends) if ends else len(source)]


def run_node_json(script: str) -> dict[str, Any]:
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


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str = "",
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
        with urllib.request.urlopen(request, timeout=25) as response:
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
    raise AssertionError("local routing/supplier RED fixture did not become healthy")


def isolated_backend_env(*, port: int, hook_root: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key.upper() in SAFE_CHILD_ENV_NAMES}
    env.update(
        {
            "PYTHONPATH": os.pathsep.join((str(hook_root), str(ROOT))),
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
            "JIEJING_AI_CEO_PLATFORM_MODEL_ENABLED": "0",
            "JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED": "0",
            "JIEJING_AI_CEO_BUILTIN_WEB_FALLBACK_ENABLED": "0",
            "JIEJING_PUBLIC_SEARCH_LIVE_ENABLED": "0",
            "JIEJING_VAULT_ENABLED": "false",
            "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED": "0",
            "JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": "0",
        }
    )
    return env


def supplier_http_sitecustomize() -> str:
    return r'''
from jiejing_saas import ai_ceo_chat as _chat
from jiejing_saas import api_server as _api

_ANSWER = """### 候选商品 1：可折叠硅胶漏斗
推荐度评分：88/100
理由：轻小件，需求清晰，但需要核对材质。[S1]
### 候选商品 2：旅行线缆标签
推荐度评分：82/100
理由：收纳场景明确，但需要核对包装。[S1]
### 候选商品 3：旅行收纳挂钩
推荐度评分：79/100
理由：用途直观，但需要核对尺寸。[S1]
### 最值得测试：可折叠硅胶漏斗
先核对供应商材质、重量、尺寸、成本和发货地；未核对前不发布。"""

class _SuccessfulSelectionModel:
    name = "unit_selection_model"
    model = "unit-selection-model"
    endpoint = ""

    def generate_text(self, **kwargs):
        callback = kwargs.get("on_text_delta")
        if callable(callback):
            callback(_ANSWER)
        return {
            "text": _ANSWER,
            "finish_reason": "stop",
            "model": self.model,
            "model_mode": "live_unit",
            "_usage": {"input_tokens": 31, "output_tokens": 97, "total_tokens": 128},
        }

def _resolved_model(self, **kwargs):
    return {
        "status": "resolved",
        "mode": "account_byok",
        "secret_ref": "ref_unit_selection_only",
        "secret_ref_scope": "account",
        "provider_key": "unit_provider",
        "provider_label": "Unit provider",
        "model": "unit-selection-model",
        "merchant_pays_provider_directly": True,
        "jiejing_pays_provider_usage": False,
        "model_client": _SuccessfulSelectionModel(),
        "frontend_gets_model_api_key": False,
        "secret_exposed": False,
    }

def _source_backed_context(*, route, message):
    return {
        "status": "ready",
        "provider": "unit_public_search",
        "query": str(message),
        "captured_at": "2026-08-23T12:00:00Z",
        "summary": "One hermetic public source record is available.",
        "source_records": [
            {
                "citation_id": "S1",
                "title": "Unit public marketplace research source",
                "url": "https://example.test/market-source",
                "domain": "example.test",
                "snippet": "Public demand and competitor context for a unit test.",
                "captured_at": "2026-08-23T12:00:00Z",
                "trust_tier": "public_reference",
                "freshness_status": "current",
            }
        ],
        "used_for_model_prompt": True,
        "search_latency_ms": 1,
        "search_budget_seconds": 0,
        "search_max_results": 1,
        "search_depth": "unit",
        "search_cache_status": "miss",
        "secret_exposed": False,
    }

_api.SaaSBackendHandler._resolve_model_client_for_store = _resolved_model
_api.SaaSBackendHandler._require_quota = lambda self, *args, **kwargs: True
_chat._run_default_web_context_search = _source_backed_context

_real_run_ai_ceo_chat = _api.run_ai_ceo_chat
def _model_self_reporting_chat(**kwargs):
    result = _real_run_ai_ceo_chat(**kwargs)
    result["supplier_facts"] = {
        "material": "MODEL_FORGED_MATERIAL",
        "package_weight_g": 999,
        "package_dimensions_cm": {"length": 99, "width": 99, "height": 99},
        "item_location": "MODEL_FORGED_LOCATION",
        "unit_cost": "USD 999.00",
        "api_key": "MODEL_FORGED_SECRET",
    }
    result["supplier_facts_verified"] = True
    result["supplier_fact_attestation"] = {
        "contract_version": "jiejing_ai_ceo_supplier_fact_attestation_v1",
        "source": "authenticated_merchant_request",
        "merchant_confirmation_received": True,
    }
    return result

_api.run_ai_ceo_chat = _model_self_reporting_chat
'''


def run_supplier_http_cases() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="jiejing-ai-ceo-supplier-http-red-", ignore_cleanup_errors=True) as temp:
        temp_root = Path(temp)
        hook_root = temp_root / "python-hook"
        hook_root.mkdir(parents=True, exist_ok=True)
        (hook_root / "sitecustomize.py").write_text(supplier_http_sitecustomize(), encoding="utf-8")
        stdout_path = temp_root / "backend-stdout.log"
        stderr_path = temp_root / "backend-stderr.log"
        port = free_port()
        env = isolated_backend_env(port=port, hook_root=hook_root)
        with stdout_path.open("w", encoding="utf-8") as child_stdout, stderr_path.open(
            "w", encoding="utf-8"
        ) as child_stderr:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
                    "serve",
                    "--db",
                    str(temp_root / "saas.sqlite"),
                    "--runtime-db",
                    str(temp_root / "runtime.sqlite"),
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
                        "email": "supplier-http-red@example.test",
                        "password": LOCAL_TEST_PASSWORD,
                        "company_name": "Supplier HTTP RED",
                    },
                )
                if register_status != 201:
                    raise AssertionError(f"supplier HTTP fixture registration failed: {register_status}")
                token = str(registered.get("token") or "")
                store_status, store_payload = request_json(
                    f"{base_url}/stores",
                    method="POST",
                    payload={"platform": "ebay", "store_name": "Supplier HTTP Store", "marketplace": "EBAY_US"},
                    token=token,
                )
                if store_status != 201:
                    raise AssertionError(f"supplier HTTP fixture store creation failed: {store_status}")
                store_id = str((store_payload.get("store") or {}).get("store_id") or "")
                supplier_facts = {
                    "material": "food-grade silicone",
                    "package_weight_g": 120,
                    "package_dimensions_cm": {"length": 12, "width": 10, "height": 4},
                    "item_location": "Shenzhen, China",
                    "unit_cost": "CNY 8.50",
                }
                cases = (
                    ("verified", supplier_facts, True, "请为我的 eBay 美国店铺调研三个全新候选商品，并生成可审计的选品报告。"),
                    ("unverified", supplier_facts, False, "请为我的 eBay 美国店铺调研三个全新候选商品，并生成可审计的选品报告。"),
                    ("missing", {}, False, "请为我的 eBay 美国店铺调研三个全新候选商品，并生成可审计的选品报告。"),
                    ("no_source", {}, False, "请为我的 eBay 美国店铺调研三个轻小不带电的候选商品，我现在没有货源。"),
                )
                results: list[dict[str, Any]] = []
                for label, facts, verified, message in cases:
                    response_status, response_payload = request_json(
                        f"{base_url}/stores/{store_id}/merchant-ceo/chat",
                        method="POST",
                        payload={
                            "message": message,
                            "command": {"id": f"cmd-supplier-{label}", "text": message},
                            "supplier_facts": facts,
                            "supplier_facts_verified": verified,
                            "client_now": "2026-08-23T20:00:00+08:00",
                            "client_timezone": "Asia/Shanghai",
                        },
                        token=token,
                    )
                    results.append(
                        {
                            "label": label,
                            "status": response_status,
                            "payload": response_payload,
                            "requested_facts": facts,
                            "requested_verified": verified,
                        }
                    )
                product_fact_status, product_fact_payload = request_json(
                    f"{base_url}/stores/{store_id}/product-facts",
                    method="POST",
                    payload={
                        "merchant_product_fact_packet": {
                            "contract_version": "merchant_product_fact_packet_v1",
                            "source_confirmed_facts": {
                                "material": "MODEL_OR_BROWSER_CANNOT_ASSERT_SOURCE_FACTS"
                            },
                            "merchant_confirmed_facts": {
                                "product_name": "Silicone Cable Organizer",
                                "source_url": "https://supplier.example/item/123",
                                "sku": "JJ-CABLE-001",
                                "material": "Silicone",
                                "package_weight_g": 90,
                                "package_length_cm": 10,
                                "package_width_cm": 6,
                                "package_height_cm": 2,
                                "unit_cost": 1.2,
                                "selling_price": 9.99,
                                "currency": "USD",
                                "quantity": 10,
                                "item_location": "Shenzhen, China",
                                "image_urls": ["https://supplier.example/item/123/main.jpg"],
                                "image_rights_confirmed": True,
                            },
                        }
                    },
                    token=token,
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        return {
            "chat_results": results,
            "product_fact_status": product_fact_status,
            "product_fact_payload": product_fact_payload,
        }


class AiCeoCrossPlatformRoutingRedTests(unittest.TestCase):
    def test_other_platform_listing_language_never_routes_or_persists_as_ebay(self) -> None:
        negative_cases = (
            "帮我在 Shopify 店铺上架一个商品",
            "帮我在 Amazon 店铺创建 listing",
            "给淘宝店铺做上架市场调研",
        )
        answer = "候选商品：可折叠收纳篮。市场调研完成。"
        for message in negative_cases:
            with self.subTest(message=message):
                route = str(ai_ceo_route_metadata(message).get("route") or "")
                self.assertNotEqual(AI_CEO_ROUTE_EBAY_WORKFLOW, route)
                self.assertFalse(
                    ai_ceo_market_artifact_eligible(
                        message=message,
                        chat={"route": route, "status": "model_answered", "answer": answer},
                    )
                )

        positive_cases = (
            "把当前商品同步到 eBay",
            "为 eBay 生成 Listing",
        )
        for message in positive_cases:
            with self.subTest(message=message):
                self.assertEqual(AI_CEO_ROUTE_EBAY_WORKFLOW, ai_ceo_route_metadata(message).get("route"))


class AiCeoSupplierFactsHttpRedTests(unittest.TestCase):
    def test_authenticated_chat_intake_controls_authoritative_listing_readiness(self) -> None:
        fixture = run_supplier_http_cases()
        results = fixture["chat_results"]
        self.assertEqual(["verified", "unverified", "missing", "no_source"], [item.get("label") for item in results])
        for item in results:
            label = str(item.get("label") or "")
            with self.subTest(label=label):
                self.assertEqual(201, item.get("status"))
                payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                saved = payload.get("ai_ceo_market_report") if isinstance(payload.get("ai_ceo_market_report"), dict) else {}
                report = saved.get("report") if isinstance(saved.get("report"), dict) else {}
                delivery = payload.get("ai_ceo_market_report_delivery") if isinstance(payload.get("ai_ceo_market_report_delivery"), dict) else {}
                self.assertEqual(3, report.get("candidate_count"), "the real HTTP turn must retain concrete candidates")
                self.assertGreaterEqual(int(report.get("source_record_count") or 0), 1)
                self.assertIs(report.get("secret_exposed"), False)
                if label == "verified":
                    self.assertEqual(item.get("requested_facts"), report.get("supplier_facts"))
                    self.assertIs(report.get("supplier_facts_verified"), True)
                    self.assertEqual("verified", report.get("supplier_fact_status"))
                    self.assertIs(report.get("listing_import_ready"), True)
                    self.assertIs(delivery.get("listing_import_ready"), True)
                elif label == "unverified":
                    self.assertEqual(item.get("requested_facts"), report.get("supplier_facts"))
                    self.assertIs(report.get("supplier_facts_verified"), False)
                    self.assertEqual("unverified", report.get("supplier_fact_status"))
                    self.assertIs(report.get("listing_import_ready"), False)
                    self.assertIn("supplier_facts_unverified", report.get("blocked_by") or [])
                else:
                    self.assertEqual({}, report.get("supplier_facts"))
                    self.assertEqual("incomplete", report.get("supplier_fact_status"))
                    self.assertIs(report.get("listing_import_ready"), False)
                    self.assertIn("supplier_facts_incomplete", report.get("blocked_by") or [])
                    if label == "no_source":
                        self.assertEqual("merchant_has_no_source", report.get("source_mode"))
                        self.assertIs(report.get("merchant_product_source_required"), True)
                        self.assertIn("merchant_product_source_required", report.get("blocked_by") or [])
                serialized = json.dumps(payload, ensure_ascii=False)
                self.assertNotIn("MODEL_FORGED", serialized)

        self.assertEqual(201, fixture["product_fact_status"])
        product_payload = fixture["product_fact_payload"]
        packet = product_payload.get("merchant_product_fact_packet") or {}
        report = (product_payload.get("report") or {}).get("report") or {}
        self.assertEqual("merchant_product_fact_packet_v1", packet.get("contract_version"))
        self.assertEqual({}, packet.get("source_confirmed_facts"))
        self.assertEqual("JJ-CABLE-001", (packet.get("merchant_confirmed_facts") or {}).get("sku"))
        self.assertEqual("merchant.product_facts", report.get("artifact_type"))
        self.assertIs(product_payload.get("model_called"), False)
        self.assertIs(product_payload.get("real_platform_writes_enabled"), False)
        self.assertIs(product_payload.get("secret_exposed"), False)

    def test_supplier_fact_normalizer_fails_closed_and_never_echoes_unknown_values(self) -> None:
        normalized = normalize_ai_ceo_supplier_fact_attestation(
            supplier_facts={
                "material": "food-grade silicone",
                "package_weight_g": True,
                "package_dimensions_cm": {"length": 12, "width": -1, "height": 4},
                "item_location": "待确认",
                "unit_cost": "8.50 without currency",
                "api_key": "UNKNOWN_PRIVATE_VALUE_SENTINEL",
            },
            supplier_facts_verified=True,
            source="authenticated_merchant_request",
        )
        self.assertEqual({"material": "food-grade silicone"}, normalized.get("supplier_facts"))
        self.assertIs(normalized.get("supplier_facts_verified"), False)
        self.assertEqual(
            ["package_weight_g", "package_dimensions_cm", "item_location", "unit_cost"],
            normalized.get("missing_supplier_fact_keys"),
        )
        self.assertEqual(1, normalized.get("unknown_field_count"))
        serialized = json.dumps(normalized, ensure_ascii=False)
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("UNKNOWN_PRIVATE_VALUE_SENTINEL", serialized)

        forged = normalize_ai_ceo_supplier_fact_attestation(
            supplier_facts={
                "material": "food-grade silicone",
                "package_weight_g": 120,
                "package_dimensions_cm": {"length": 12, "width": 10, "height": 4},
                "item_location": "Shenzhen, China",
                "unit_cost": "CNY 8.50",
            },
            supplier_facts_verified=True,
            source="untrusted_chat_output",
        )
        self.assertIs(forged.get("merchant_confirmation_received"), False)
        self.assertIs(forged.get("supplier_facts_verified"), False)


class AiCeoSupplierFactsFrontendRedTests(unittest.TestCase):
    def test_manual_form_confirmation_is_the_only_frontend_source_of_verified_payload(self) -> None:
        build_intake = function_body(APP_JS, "buildSaasAiCeoSupplierFactIntake")
        confirm_intake = function_body(APP_JS, "confirmManualSourceFactsForAiCeo")
        command_payload = function_body(APP_JS, "supplierFactsForSaasAiCeoCommand")
        request_chat = function_body(APP_JS, "requestSaasAiCeoChat")
        result = run_node_json(
            "\n".join(
                [
                    "const isFilledOperationalValue = (value) => Boolean(String(value || '').trim()) && !/待|未确认|unknown|pending|tbd/i.test(String(value));",
                    "const state = { saasAiCeoSupplierFactAttestation: null };",
                    "let confirmationResult = true; let confirmationCount = 0;",
                    "const window = { confirm: () => { confirmationCount += 1; return confirmationResult; } };",
                    build_intake,
                    confirm_intake,
                    command_payload,
                    request_chat,
                    "const manual = { material: 'food-grade silicone', package_weight: '120 g', package_dimensions: '12 x 10 x 4 cm', source_location: 'Shenzhen, China', purchase_price: 'CNY 8.50' };",
                    "const confirmed = confirmManualSourceFactsForAiCeo(manual);",
                    "const ebayPayload = supplierFactsForSaasAiCeoCommand({ text: '为 eBay 生成 Listing', route: 'listing', intent: 'listing' });",
                    "state.saasAiCeoSupplierFactAttestation = confirmed;",
                    "const unknownFactsPayload = supplierFactsForSaasAiCeoCommand({ text: '当前没有供应商和实物，重量尺寸材质采购价都未知，只做选品', route: 'research', intent: 'research' });",
                    "const shopifyPayload = supplierFactsForSaasAiCeoCommand({ text: '帮我在 Shopify 店铺上架', route: 'listing', intent: 'listing' });",
                    "confirmationResult = false;",
                    "const declined = confirmManualSourceFactsForAiCeo(manual);",
                    "let capturedBody = null;",
                    "const normalizeSaasCeoCommand = (value) => value;",
                    "const hasSaasProtectedSessionCandidate = () => true;",
                    "const sanitizeSaasCeoCommandSourceText = (value) => String(value || '');",
                    "const saasAiCeoConversationHistoryForRequest = () => [];",
                    "const isSaasRealPlatformWritesEnabled = () => false;",
                    "const saasFetchNdjsonWithTimeout = async (_path, options) => { capturedBody = JSON.parse(options.body); return {}; };",
                    "(async () => {",
                    "  state.saasAiCeoSupplierFactAttestation = confirmed;",
                    "  await requestSaasAiCeoChat({ store_id: 'store_unit', text: '为 eBay 生成 Listing', route: 'listing', intent: 'listing', summary: '', title: '' });",
                    "  console.log(JSON.stringify({ confirmed, declined, ebayPayload, unknownFactsPayload, shopifyPayload, capturedBody, confirmationCount }));",
                    "})().catch((error) => { console.error(error); process.exit(1); });",
                ]
            )
        )
        expected_facts = {
            "material": "food-grade silicone",
            "package_weight_g": 120,
            "package_dimensions_cm": {"length": 12, "width": 10, "height": 4},
            "item_location": "Shenzhen, China",
            "unit_cost": "CNY 8.50",
        }
        self.assertEqual(2, result.get("confirmationCount"))
        self.assertEqual(expected_facts, result.get("confirmed", {}).get("supplier_facts"))
        self.assertIs(result.get("confirmed", {}).get("supplier_facts_verified"), True)
        self.assertIs(result.get("declined", {}).get("supplier_facts_verified"), False)
        self.assertEqual(expected_facts, result.get("ebayPayload", {}).get("supplier_facts"))
        self.assertEqual({}, result.get("unknownFactsPayload"))
        self.assertEqual({}, result.get("shopifyPayload"))
        self.assertEqual(expected_facts, result.get("capturedBody", {}).get("supplier_facts"))
        self.assertIs(result.get("capturedBody", {}).get("supplier_facts_verified"), True)
        handler_source = function_body(APP_JS, "handleSourceIntakeAction")
        self.assertIn("confirmManualSourceFactsForAiCeo(facts)", handler_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)

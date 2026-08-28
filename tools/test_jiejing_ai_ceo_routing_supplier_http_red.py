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
                            "active_listing_context": {
                                "contract_version": "active_listing_context_v1",
                                "listing_project_identity": {
                                    "key": "project-current-http",
                                    "source_report_id": "report-current-http",
                                    "candidate_id": "candidate-current-http",
                                },
                                "product_name": "Current HTTP Product",
                                "listing": {
                                    "sku": "JJ-CURRENT-HTTP-01",
                                    "known_facts": {"material": "resin", "api_key": "MUST_NOT_LEAK"},
                                    "missing_fact_keys": ["selling_price"],
                                },
                                "media": {"asset_manifest_count": 1, "listing_eligible_asset_count": 1},
                                "ebay_draft": {
                                    "offer_id": "245675556011",
                                    "sku": "JJ-CURRENT-HTTP-01",
                                    "offer_status": "UNPUBLISHED",
                                    "public_listing_created": False,
                                    "refresh_token": "MUST_NOT_LEAK",
                                },
                                "account_health": {"status": "restricted", "severity": "red"},
                                "access_token": "MUST_NOT_LEAK",
                            } if label == "verified" else None,
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
                        "listing_project_identity": {
                            "key": "listing-project-report-incense-candidate-a",
                            "source_report_id": "report-incense-market-a",
                            "candidate_id": "candidate-incense-a",
                        },
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
                reports_status, reports_payload = request_json(
                    f"{base_url}/reports",
                    token=token,
                )
                empty_identity_status, empty_identity_payload = request_json(
                    f"{base_url}/stores/{store_id}/product-facts",
                    method="POST",
                    payload={
                        "listing_project_identity": {
                            "key": "",
                            "source_report_id": "must-not-authorize-an-empty-key",
                            "candidate_id": "must-not-authorize-an-empty-key",
                        },
                        "merchant_product_fact_packet": {
                            "merchant_confirmed_facts": {
                                "product_name": "Legacy Product Without Exact Identity",
                            }
                        },
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
            "reports_status": reports_status,
            "reports_payload": reports_payload,
            "empty_identity_status": empty_identity_status,
            "empty_identity_payload": empty_identity_payload,
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
                self.assertNotIn("MUST_NOT_LEAK", serialized)
                if label == "verified":
                    active = ((payload.get("ai_ceo_chat") or {}).get("context") or {}).get("active_listing_context") or {}
                    self.assertEqual("project-current-http", (active.get("listing_project_identity") or {}).get("key"))
                    self.assertEqual("JJ-CURRENT-HTTP-01", (active.get("listing") or {}).get("sku"))
                    self.assertEqual(1, (active.get("media") or {}).get("asset_manifest_count"))
                    self.assertEqual("245675556011", (active.get("ebay_draft") or {}).get("offer_id"))

        self.assertEqual(201, fixture["product_fact_status"])
        product_payload = fixture["product_fact_payload"]
        packet = product_payload.get("merchant_product_fact_packet") or {}
        report = (product_payload.get("report") or {}).get("report") or {}
        self.assertEqual("merchant_product_fact_packet_v1", packet.get("contract_version"))
        self.assertEqual({}, packet.get("source_confirmed_facts"))
        self.assertEqual("JJ-CABLE-001", (packet.get("merchant_confirmed_facts") or {}).get("sku"))
        self.assertEqual("merchant.product_facts", report.get("artifact_type"))
        expected_identity = {
            "key": "listing-project-report-incense-candidate-a",
            "source_report_id": "report-incense-market-a",
            "candidate_id": "candidate-incense-a",
        }
        self.assertEqual(expected_identity, product_payload.get("listing_project_identity"))
        self.assertEqual(expected_identity, (product_payload.get("task") or {}).get("input", {}).get("listing_project_identity"))
        self.assertEqual(expected_identity, report.get("listing_project_identity"))
        self.assertEqual(200, fixture.get("reports_status"))
        saved_reports = (fixture.get("reports_payload") or {}).get("reports") or []
        saved_product_report = next(item for item in saved_reports if item.get("report_type") == "merchant.product_facts")
        self.assertEqual(expected_identity, (saved_product_report.get("report") or {}).get("listing_project_identity"))
        self.assertIs(product_payload.get("model_called"), False)
        self.assertIs(product_payload.get("real_platform_writes_enabled"), False)
        self.assertIs(product_payload.get("secret_exposed"), False)

    def test_empty_listing_project_key_cannot_create_an_exact_product_fact_identity(self) -> None:
        fixture = run_supplier_http_cases()
        self.assertEqual(201, fixture.get("empty_identity_status"))
        payload = fixture.get("empty_identity_payload") or {}
        self.assertNotIn("listing_project_identity", payload)
        self.assertNotIn("listing_project_identity", (payload.get("task") or {}).get("input") or {})
        self.assertNotIn("listing_project_identity", ((payload.get("report") or {}).get("report") or {}))

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
    def test_listing_project_identity_prefers_the_persisted_structured_identity(self) -> None:
        normalize_identity = function_body(APP_JS, "saasNormalizeListingProjectIdentity")
        identity_function = function_body(APP_JS, "saasCurrentListingProjectIdentity")
        result = run_node_json(
            "\n".join(
                [
                    "const state = { saasListingComposerDraft: null, activeListingDraft: '' };",
                    "const publicRuntimeText = (value = '') => String(value || '');",
                    "const activeListingDraft = () => null;",
                    "const isSaasPublicMvpMode = () => true;",
                    "const isLegacySampleMediaDraftKey = () => false;",
                    "const saasIsConcreteProductLabel = (value) => Boolean(String(value || '').trim());",
                    "const hashString = (value) => String(value || '').length;",
                    normalize_identity,
                    identity_function,
                    "const identity = saasCurrentListingProjectIdentity({",
                    "  listing_project_identity: { key: 'project-report-a-candidate-a', source_report_id: 'report-a', candidate_id: 'candidate-a' },",
                    "  source_report_id: 'stale-report',",
                    "  selected_product_candidate: { candidate_id: 'stale-candidate', name: 'Same Name Incense Burner' },",
                    "  product: 'Edited Same Name Incense Burner'",
                    "});",
                    "console.log(JSON.stringify(identity));",
                ]
            )
        )
        self.assertEqual("project-report-a-candidate-a", result.get("key"))
        self.assertEqual("report-a", result.get("source_report_id"))
        self.assertEqual("report-a", result.get("source_id"), "publish compatibility alias must remain available")
        self.assertEqual("candidate-a", result.get("candidate_id"))

    def test_listing_project_identity_survives_the_protected_snapshot(self) -> None:
        snapshot_function = function_body(APP_JS, "sanitizeSaasListingComposerDraftSnapshot")
        result = run_node_json(
            "\n".join(
                [
                    "const publicRuntimeText = (value = '') => String(value || '');",
                    "const pickSaasSnapshotFields = (source = {}, fields = []) => Object.fromEntries(fields.filter((key) => source[key] !== undefined).map((key) => [key, source[key]]));",
                    "const saasCurrentListingProjectIdentity = () => ({ key: 'project-a', source_report_id: 'report-a', source_id: 'report-a', candidate_id: 'candidate-a' });",
                    "const saasNormalizeListingProjectIdentity = (value) => value && value.key ? ({ key: value.key, source_report_id: value.source_report_id || value.source_id || '', candidate_id: value.candidate_id || '' }) : null;",
                    "const sanitizeSaasListingPublishPrefillSnapshot = (value) => value || {};",
                    "const sanitizeSaasMerchantProductFactPacketSnapshot = (value) => value || null;",
                    "const sanitizeSaasListingMediaWritebackSnapshot = (value) => value || null;",
                    snapshot_function,
                    "const snapshot = sanitizeSaasListingComposerDraftSnapshot({",
                    "  product: 'Same Name Incense Burner',",
                    "  listing_project_identity: { key: 'project-a', source_report_id: 'report-a', candidate_id: 'candidate-a' },",
                    "  selected_product_candidate: { candidate_id: 'candidate-a', name: 'Same Name Incense Burner' },",
                    "  fields: {}, publish_prefill: {}, merchant_product_fact_packet: {},",
                    "});",
                    "console.log(JSON.stringify(snapshot));",
                ]
            )
        )
        self.assertEqual(
            {"key": "project-a", "source_report_id": "report-a", "candidate_id": "candidate-a"},
            result.get("listing_project_identity"),
        )

    def test_ai_ceo_report_import_creates_a_structured_listing_project_identity(self) -> None:
        import_function = function_body(APP_JS, "saasListingDraftFromReport")
        normalize_identity = function_body(APP_JS, "saasNormalizeListingProjectIdentity")
        result = run_node_json(
            "\n".join(
                [
                    "const saasAiCeoMarketReportCanStartBlockedListingDraft = () => true;",
                    "const saasAiCeoListingHandoffFieldsFromReport = () => ({",
                    "  selected_product_candidate: { candidate_id: 'candidate-a', name: 'Same Name Incense Burner', reasons: ['grounded'] },",
                    "  product_candidates: [], market_rationale: [], selling_points: [], keywords: [], risk_notes: [],",
                    "  recommendation_score: 90, description_seed: '', item_specifics: '', category_id: '', category_suggestion: '',",
                    "  price_band: '', image_urls: '', image_requirements: '', logistics_requirements: '', publish_prefill: {},",
                    "  ebay_listing_field_map_contract: '', publish_preflight_required_fields: [], publish_preflight_gaps: [],",
                    "  merchant_required_answers: [], ebay_publish_field_matrix: [], listing_readiness: {}, merchant_product_fact_packet: null",
                    "});",
                    "const saasSelectedMarketProductCandidate = () => null;",
                    "const saasCleanMarketCandidateName = (value) => String(value || '');",
                    "const saasProductLabelForRecord = () => '';",
                    "const saasReportSummary = () => '';",
                    "const saasWorkbenchReportSections = () => ({});",
                    "const runtimeSectionTitle = (value) => value;",
                    "const saasWorkbenchFormatReportSectionValue = () => '';",
                    "const saasListingMerchantSourceLabel = () => 'AI CEO';",
                    "const saasListingComposerDraftFromText = () => ({ fields: {}, gaps: [] });",
                    "const saasListingEbayTitleFromProduct = (value) => value;",
                    "const saasListingSafeItemSpecifics = (value) => value;",
                    "const applySaasMerchantProductFactPacketToDraft = (draft) => draft;",
                    "const saasCurrentListingProjectIdentity = (draft) => ({ key: `project-${draft.source_report_id}-${draft.selected_product_candidate.candidate_id}`, source_report_id: draft.source_report_id, source_id: draft.source_report_id, candidate_id: draft.selected_product_candidate.candidate_id });",
                    "const publicRuntimeText = (value = '') => String(value || '');",
                    normalize_identity,
                    import_function,
                    "const draft = saasListingDraftFromReport({ report_id: 'report-a', report_type: 'ai_ceo.market_research', report: {} }, 'ai_ceo_market_report');",
                    "console.log(JSON.stringify(draft));",
                ]
            )
        )
        self.assertEqual("project-report-a-candidate-a", result.get("listing_project_key"))
        self.assertEqual(
            {"key": "project-report-a-candidate-a", "source_report_id": "report-a", "candidate_id": "candidate-a"},
            result.get("listing_project_identity"),
        )

    def test_product_vision_handoff_persists_its_structured_listing_project_identity(self) -> None:
        vision_handoff = function_body(APP_JS, "applySaasAiCeoProductFactPacket")
        result = run_node_json(
            "\n".join(
                [
                    "const state = { saasReports: [], activeMediaDraft: '' };",
                    "const saasListingComposerDraftFromText = () => ({ product: 'Vision Product', title: 'Vision Product', fields: {} });",
                    "const applySaasMerchantProductFactPacketToDraft = (draft, packet) => ({ ...draft, merchant_product_fact_packet: packet });",
                    "const saasCurrentListingProjectIdentity = (draft) => ({ key: `project-${draft.source_report_id}`, source_report_id: draft.source_report_id, source_id: draft.source_report_id, candidate_id: '' });",
                    "const saveSaasProtectedStateSnapshot = () => {};",
                    vision_handoff,
                    "const draft = applySaasAiCeoProductFactPacket({ product_name: 'Vision Product', listing_copy: {} }, 'merchant images', { report_id: 'vision-facts-a' });",
                    "console.log(JSON.stringify({ draft, activeMediaDraft: state.activeMediaDraft }));",
                ]
            )
        )
        self.assertEqual("project-vision-facts-a", result.get("draft", {}).get("listing_project_key"))
        self.assertEqual(
            {"key": "project-vision-facts-a", "source_report_id": "vision-facts-a", "candidate_id": ""},
            result.get("draft", {}).get("listing_project_identity"),
        )
        self.assertEqual("project-vision-facts-a", result.get("activeMediaDraft"))

    def test_candidate_switch_rekeys_the_project_and_clears_old_media(self) -> None:
        switch_function = function_body(APP_JS, "selectSaasListingMarketCandidate")
        result = run_node_json(
            "\n".join(
                [
                    "const state = {",
                    "  saasListingComposerDraft: {",
                    "    source_report_id: 'report-a', product: 'Same Name Incense Burner', title: 'Same Name Incense Burner',",
                    "    listing_project_key: 'project-report-a-candidate-a',",
                    "    listing_project_identity: { key: 'project-report-a-candidate-a', source_report_id: 'report-a', candidate_id: 'candidate-a' },",
                    "    product_candidates: [",
                    "      { candidate_id: 'candidate-a', name: 'Same Name Incense Burner', selected: true },",
                    "      { candidate_id: 'candidate-b', name: 'Same Name Incense Burner', selected: false },",
                    "    ],",
                    "    selected_product_candidate: { candidate_id: 'candidate-a', name: 'Same Name Incense Burner' },",
                    "    source_media_job_id: 'media-a', media_writeback: { media_job_id: 'media-a' },",
                    "    source_product_fact_report_id: 'facts-a',",
                    "    merchant_product_fact_packet: { product_name: 'Same Name Incense Burner', merchant_confirmed_facts: { sku: 'STALE-SKU', material: 'STALE-MATERIAL' }, unknown_facts: [] },",
                    "    fields: {}, publish_prefill: {}",
                    "  },",
                    "  saasMediaSourceUpload: { asset_id: 'asset-a', listing_project_key: 'project-report-a-candidate-a' },",
                    "  activeMediaDraft: 'project-report-a-candidate-a', saasActiveMediaPreviewKey: 'preview-a', saasMediaSourceUploadEpoch: 7,",
                    "  saasAiCeoSupplierFactAttestation: { supplier_facts: { material: 'STALE-MATERIAL' }, supplier_facts_verified: true }, supplierFactsStatus: 'verified'",
                    "};",
                    "const saasNormalizeMarketProductCandidates = (value) => value;",
                    "const resetSaasListingPublishEvidenceForNewProject = () => {};",
                    "const saasListingEbayTitleFromProduct = (value) => value;",
                    "const resetSaasBulkWorkspaceForListingProject = () => {};",
                    "const saasListingImportedAiCeoMarketInput = () => '';",
                    "const renderProductListingCenter = () => {};",
                    "const toasts = []; const showActionToast = (message) => toasts.push(message);",
                    "const saasCurrentListingProjectIdentity = (draft) => ({ key: `project-${draft.source_report_id}-${draft.selected_product_candidate.candidate_id}`, source_report_id: draft.source_report_id, source_id: draft.source_report_id, candidate_id: draft.selected_product_candidate.candidate_id });",
                    switch_function,
                    "const switched = selectSaasListingMarketCandidate('candidate-b');",
                    "console.log(JSON.stringify({ switched, draft: state.saasListingComposerDraft, activeMediaDraft: state.activeMediaDraft, upload: state.saasMediaSourceUpload, preview: state.saasActiveMediaPreviewKey, supplierAttestation: state.saasAiCeoSupplierFactAttestation, supplierFactsStatus: state.supplierFactsStatus, uploadEpoch: state.saasMediaSourceUploadEpoch, toasts }));",
                ]
            )
        )
        self.assertIs(result.get("switched"), True)
        self.assertEqual("project-report-a-candidate-b", result.get("draft", {}).get("listing_project_key"))
        self.assertEqual(
            {"key": "project-report-a-candidate-b", "source_report_id": "report-a", "candidate_id": "candidate-b"},
            result.get("draft", {}).get("listing_project_identity"),
        )
        self.assertEqual("", result.get("draft", {}).get("source_media_job_id"))
        self.assertIsNone(result.get("draft", {}).get("media_writeback"))
        self.assertIsNone(result.get("draft", {}).get("merchant_product_fact_packet"))
        self.assertEqual("", result.get("draft", {}).get("source_product_fact_report_id"))
        self.assertNotIn("STALE-SKU", json.dumps(result.get("draft") or {}, ensure_ascii=False))
        self.assertNotIn("STALE-MATERIAL", json.dumps(result.get("draft") or {}, ensure_ascii=False))
        self.assertEqual("project-report-a-candidate-b", result.get("activeMediaDraft"))
        self.assertIsNone(result.get("upload"))
        self.assertEqual("", result.get("preview"))
        self.assertIsNone(result.get("supplierAttestation"))
        self.assertEqual("idle", result.get("supplierFactsStatus"))
        self.assertEqual(8, result.get("uploadEpoch"))
        self.assertTrue(any("商品已切换" in item and "重新上传" in item for item in result.get("toasts") or []))

    def test_media_jobs_require_exact_structured_project_identity(self) -> None:
        normalize_identity = function_body(APP_JS, "saasNormalizeListingProjectIdentity")
        product_facts_function = function_body(APP_JS, "saasMediaAssetJobProductFacts")
        matcher_function = function_body(APP_JS, "saasMediaAssetJobMatchesListingProject")
        result = run_node_json(
            "\n".join(
                [
                    "const state = { saasListingComposerDraft: null };",
                    "const publicRuntimeText = (value = '') => String(value || '');",
                    normalize_identity,
                    "const saasCurrentListingProjectIdentity = (draft) => ({",
                    "  key: draft.listing_project_identity?.key || draft.listing_project_key || '',",
                    "  product: draft.product || '',",
                    "  source_report_id: draft.listing_project_identity?.source_report_id || '',",
                    "  source_id: draft.listing_project_identity?.source_report_id || '',",
                    "  candidate_id: draft.listing_project_identity?.candidate_id || '',",
                    "});",
                    product_facts_function,
                    matcher_function,
                    "const draftA = { product: 'Same Name Incense Burner', listing_project_key: 'project-a', listing_project_identity: { key: 'project-a', source_report_id: 'report-a', candidate_id: 'candidate-a' } };",
                    "const draftLegacy = { product: 'Legacy Product', listing_project_key: 'legacy-project' };",
                    "const draftManual = { product: 'Manual Product', listing_project_key: 'project-manual', listing_project_identity: { key: 'project-manual', source_report_id: '', candidate_id: '' } };",
                    "const job = (facts) => ({ job: { job_spec: { inputs: { product_facts: facts } } } });",
                    "const results = {",
                    "  exactA: saasMediaAssetJobMatchesListingProject(job({ product: 'Same Name Incense Burner', listing_project_key: 'project-a', listing_project_identity: { key: 'project-a', source_report_id: 'report-a', candidate_id: 'candidate-a' } }), draftA),",
                    "  keyOnly: saasMediaAssetJobMatchesListingProject(job({ product: 'Same Name Incense Burner', listing_project_key: 'project-a', listing_project_identity: { key: 'project-a' } }), draftA),",
                    "  missingSource: saasMediaAssetJobMatchesListingProject(job({ product: 'Same Name Incense Burner', listing_project_key: 'project-a', listing_project_identity: { key: 'project-a', candidate_id: 'candidate-a' } }), draftA),",
                    "  missingCandidate: saasMediaAssetJobMatchesListingProject(job({ product: 'Same Name Incense Burner', listing_project_key: 'project-a', listing_project_identity: { key: 'project-a', source_report_id: 'report-a' } }), draftA),",
                    "  candidateB: saasMediaAssetJobMatchesListingProject(job({ product: 'Same Name Incense Burner', listing_project_key: 'project-a', listing_project_identity: { key: 'project-a', source_report_id: 'report-a', candidate_id: 'candidate-b' } }), draftA),",
                    "  projectB: saasMediaAssetJobMatchesListingProject(job({ product: 'Same Name Incense Burner', listing_project_key: 'project-b', listing_project_identity: { key: 'project-b', source_report_id: 'report-b', candidate_id: 'candidate-b' } }), draftA),",
                    "  productOnly: saasMediaAssetJobMatchesListingProject(job({ product: 'Same Name Incense Burner' }), draftA),",
                    "  legacyExactKey: saasMediaAssetJobMatchesListingProject(job({ product: 'Different label', listing_project_key: 'legacy-project' }), draftLegacy),",
                    "  manualExact: saasMediaAssetJobMatchesListingProject(job({ listing_project_key: 'project-manual', listing_project_identity: { key: 'project-manual', source_report_id: '', candidate_id: '' } }), draftManual),",
                    "  manualIncomingSource: saasMediaAssetJobMatchesListingProject(job({ listing_project_key: 'project-manual', listing_project_identity: { key: 'project-manual', source_report_id: 'unexpected-report', candidate_id: '' } }), draftManual),",
                    "  manualIncomingCandidate: saasMediaAssetJobMatchesListingProject(job({ listing_project_key: 'project-manual', listing_project_identity: { key: 'project-manual', source_report_id: '', candidate_id: 'unexpected-candidate' } }), draftManual),",
                    "};",
                    "console.log(JSON.stringify(results));",
                ]
            )
        )
        self.assertIs(result.get("exactA"), True)
        self.assertIs(result.get("keyOnly"), False)
        self.assertIs(result.get("missingSource"), False)
        self.assertIs(result.get("missingCandidate"), False)
        self.assertIs(result.get("candidateB"), False)
        self.assertIs(result.get("projectB"), False)
        self.assertIs(result.get("productOnly"), False)
        self.assertIs(result.get("legacyExactKey"), True)
        self.assertIs(result.get("manualExact"), True)
        self.assertIs(result.get("manualIncomingSource"), False)
        self.assertIs(result.get("manualIncomingCandidate"), False)

    def test_media_product_facts_bind_structured_identity_and_reject_unbound_uploads(self) -> None:
        facts_function = function_body(APP_JS, "currentMediaStudioProductFacts")
        result = run_node_json(
            "\n".join(
                [
                    "const state = {",
                    "  activeListingDraft: '', activeMediaDraft: 'project-a',",
                    "  mediaTaskEntry: 'single',",
                    "  saasListingComposerDraft: { product: 'Same Name Incense Burner', listing_project_key: 'project-a', listing_project_identity: { key: 'project-a', source_report_id: 'report-a', candidate_id: 'candidate-a' } },",
                    "  saasMediaSourceUpload: { asset_id: 'unbound-asset', sha256: 'aa' },",
                    "};",
                    "const publicRuntimeText = (value = '') => String(value || '');",
                    "const isSaasPublicMvpMode = () => true;",
                    "const saasMerchantWorkbenchContext = () => ({ store: { marketplace: 'EBAY_US' } });",
                    "const activeListingDraft = () => null;",
                    "const isLegacySampleMediaDraftKey = () => false;",
                    "const saasCurrentListingProjectIdentity = () => { const value = state.saasListingComposerDraft.listing_project_identity || {}; return { key: value.key || '', product: state.saasListingComposerDraft.product || '', source_report_id: value.source_report_id || '', source_id: value.source_report_id || '', candidate_id: value.candidate_id || '' }; };",
                    "const latestSaasReportByTypes = () => null;",
                    "const activeSaasStore = () => ({ marketplace: 'EBAY_US' });",
                    "const saasMediaSourceAssetForListingDraft = () => null;",
                    "const saasNormalizeListingProjectIdentity = (value) => value && value.key ? value : null;",
                    facts_function,
                    "const unbound = currentMediaStudioProductFacts({ entry: 'single' });",
                    "state.saasMediaSourceUpload = { asset_id: 'key-only', listing_project_key: 'project-a', listing_project_identity: { key: 'project-a' } };",
                    "const keyOnly = currentMediaStudioProductFacts({});",
                    "state.saasMediaSourceUpload = { asset_id: 'missing-source', listing_project_key: 'project-a', listing_project_identity: { key: 'project-a', candidate_id: 'candidate-a' } };",
                    "const missingSource = currentMediaStudioProductFacts({});",
                    "state.saasMediaSourceUpload = { asset_id: 'missing-candidate', listing_project_key: 'project-a', listing_project_identity: { key: 'project-a', source_report_id: 'report-a' } };",
                    "const missingCandidate = currentMediaStudioProductFacts({});",
                    "state.saasMediaSourceUpload = { asset_id: 'asset-a', sha256: 'bb', listing_project_key: 'project-a', listing_project_identity: { key: 'project-a', source_report_id: 'report-a', candidate_id: 'candidate-a' } };",
                    "const bound = currentMediaStudioProductFacts({});",
                    "state.saasListingComposerDraft = { product: 'Manual Product', listing_project_key: 'project-manual', listing_project_identity: { key: 'project-manual', source_report_id: '', candidate_id: '' } };",
                    "state.saasMediaSourceUpload = { asset_id: 'manual-source', listing_project_key: 'project-manual', listing_project_identity: { key: 'project-manual', source_report_id: 'unexpected-report', candidate_id: '' } };",
                    "const manualIncomingSource = currentMediaStudioProductFacts({});",
                    "state.saasMediaSourceUpload = { asset_id: 'manual-candidate', listing_project_key: 'project-manual', listing_project_identity: { key: 'project-manual', source_report_id: '', candidate_id: 'unexpected-candidate' } };",
                    "const manualIncomingCandidate = currentMediaStudioProductFacts({});",
                    "state.saasMediaSourceUpload = { asset_id: 'manual-exact', listing_project_key: 'project-manual', listing_project_identity: { key: 'project-manual', source_report_id: '', candidate_id: '' } };",
                    "const manualExact = currentMediaStudioProductFacts({});",
                    "state.saasListingComposerDraft = {}; state.saasMediaSourceUpload = { asset_id: 'standalone-asset', sha256: 'cc', listing_project_key: '', listing_project_identity: null };",
                    "const standalone = currentMediaStudioProductFacts({ entry: 'single' });",
                    "console.log(JSON.stringify({ unbound, keyOnly, missingSource, missingCandidate, bound, manualIncomingSource, manualIncomingCandidate, manualExact, standalone }));",
                ]
            )
        )
        self.assertEqual("", result.get("unbound", {}).get("source_asset_id"))
        self.assertEqual("", result.get("keyOnly", {}).get("source_asset_id"))
        self.assertEqual("", result.get("missingSource", {}).get("source_asset_id"))
        self.assertEqual("", result.get("missingCandidate", {}).get("source_asset_id"))
        self.assertEqual("asset-a", result.get("bound", {}).get("source_asset_id"))
        self.assertEqual("", result.get("manualIncomingSource", {}).get("source_asset_id"))
        self.assertEqual("", result.get("manualIncomingCandidate", {}).get("source_asset_id"))
        self.assertEqual("manual-exact", result.get("manualExact", {}).get("source_asset_id"))
        self.assertEqual("standalone-asset", result.get("standalone", {}).get("source_asset_id"))
        self.assertIsNone(result.get("standalone", {}).get("listing_project_identity"))
        self.assertEqual(
            {"key": "project-a", "source_report_id": "report-a", "candidate_id": "candidate-a"},
            result.get("bound", {}).get("listing_project_identity"),
        )

    def test_delayed_media_upload_cannot_rebind_from_project_a_to_project_b(self) -> None:
        handle_upload = function_body(APP_JS, "handleMediaSourceFile")
        result = run_node_json(
            "\n".join(
                [
                    "const identityA = { key: 'project-a', source_report_id: 'report-a', candidate_id: 'candidate-a' };",
                    "const identityB = { key: 'project-b', source_report_id: 'report-b', candidate_id: 'candidate-b' };",
                    "const state = { saasListingComposerDraft: { product: 'Product A', listing_project_identity: identityA }, activeMediaDraft: 'project-a', saasMediaSourceUpload: null, mediaSourceObjectUrl: '', saasMediaSourceUploadEpoch: 0 };",
                    "const document = { querySelector: () => null };",
                    "const URL = { createObjectURL: () => 'blob:source-a', revokeObjectURL: () => {} };",
                    "const inferMediaLocalPath = () => ({ path: 'source-a.jpg', note: 'test' });",
                    "const ui = {}; const setText = (selector, value) => { ui[selector] = value; };",
                    "const setMediaNewTaskMode = () => {};",
                    "const syncMediaGenerationActionState = () => {};",
                    "const publicRuntimeText = (value = '') => String(value || '');",
                    "const saasCurrentListingProjectIdentity = (draft) => { const value = draft?.listing_project_identity || {}; return { key: value.key || '', source_report_id: value.source_report_id || '', source_id: value.source_report_id || '', candidate_id: value.candidate_id || '' }; };",
                    "const toasts = []; const showActionToast = (message) => toasts.push(message);",
                    "let resolveUpload; const delayedUpload = new Promise((resolve) => { resolveUpload = resolve; });",
                    "const uploadSaasMediaSourceFile = async () => delayedUpload;",
                    handle_upload,
                    "(async () => {",
                    "  const pending = handleMediaSourceFile({ name: 'source-a.jpg', type: 'image/jpeg', size: 1024 }, {});",
                    "  await Promise.resolve();",
                    "  state.saasMediaSourceUploadEpoch += 1; state.saasListingComposerDraft = { product: 'Product B', listing_project_identity: identityB }; state.activeMediaDraft = 'project-b'; state.saasMediaSourceUpload = null; ui['#mediaProductionStatus'] = 'B_CURRENT_STATUS'; toasts.push('商品已切换，请为当前商品重新上传来源图。');",
                    "  resolveUpload({ asset_id: 'asset-from-a', sha256: 'aa' });",
                    "  await pending;",
                    "  const raceUpload = state.saasMediaSourceUpload; const raceStatus = ui['#mediaProductionStatus']; const raceToast = toasts[toasts.length - 1];",
                    "  state.saasListingComposerDraft = { product: 'Product A', listing_project_identity: identityA }; state.activeMediaDraft = 'project-a'; state.saasMediaSourceUpload = null;",
                    "  await handleMediaSourceFile({ name: 'source-a-stable.jpg', type: 'image/jpeg', size: 1024 }, {});",
                    "  console.log(JSON.stringify({ raceUpload, raceStatus, raceToast, stableUpload: state.saasMediaSourceUpload, toasts }));",
                    "})().catch((error) => { console.error(error); process.exit(1); });",
                ]
            )
        )
        self.assertIsNone(result.get("raceUpload"))
        self.assertEqual("B_CURRENT_STATUS", result.get("raceStatus"))
        self.assertEqual("商品已切换，请为当前商品重新上传来源图。", result.get("raceToast"))
        self.assertEqual("asset-from-a", result.get("stableUpload", {}).get("asset_id"))
        self.assertEqual(
            {"key": "project-a", "source_report_id": "report-a", "candidate_id": "candidate-a"},
            result.get("stableUpload", {}).get("listing_project_identity"),
        )
        self.assertTrue(any("商品已切换" in item and "重新上传" in item for item in result.get("toasts") or []))

    def test_newer_same_project_upload_wins_when_older_finishes_last(self) -> None:
        handle_upload = function_body(APP_JS, "handleMediaSourceFile")
        result = run_node_json(
            "\n".join(
                [
                    "const identityA = { key: 'project-a', source_report_id: 'report-a', candidate_id: 'candidate-a' };",
                    "const state = { saasListingComposerDraft: { product: 'Product A', listing_project_identity: identityA }, activeMediaDraft: 'project-a', saasMediaSourceUpload: null, mediaSourceObjectUrl: '', saasMediaSourceUploadEpoch: 0 };",
                    "const document = { querySelector: () => null };",
                    "let previewCount = 0; const URL = { createObjectURL: () => `blob:source-${++previewCount}`, revokeObjectURL: () => {} };",
                    "const inferMediaLocalPath = (file) => ({ path: file.name, note: 'test' });",
                    "const ui = {}; const setText = (selector, value) => { ui[selector] = value; };",
                    "const setMediaNewTaskMode = () => {};",
                    "const syncMediaGenerationActionState = () => {};",
                    "const publicRuntimeText = (value = '') => String(value || '');",
                    "const saasCurrentListingProjectIdentity = (draft) => { const value = draft?.listing_project_identity || {}; return { key: value.key || '', source_report_id: value.source_report_id || '', source_id: value.source_report_id || '', candidate_id: value.candidate_id || '' }; };",
                    "const toasts = []; const showActionToast = (message) => toasts.push(message);",
                    "const deferred = []; const uploadSaasMediaSourceFile = async () => new Promise((resolve, reject) => deferred.push({ resolve, reject }));",
                    handle_upload,
                    "(async () => {",
                    "  const older = handleMediaSourceFile({ name: 'older.jpg', type: 'image/jpeg', size: 1024 }, {}); await Promise.resolve();",
                    "  const newer = handleMediaSourceFile({ name: 'newer.jpg', type: 'image/jpeg', size: 1024 }, {}); await Promise.resolve();",
                    "  deferred[1].resolve({ asset_id: 'asset-newer', sha256: 'bb' }); await newer;",
                    "  const statusAfterNewer = ui['#mediaProductionStatus']; const toastAfterNewer = toasts[toasts.length - 1];",
                    "  deferred[0].resolve({ asset_id: 'asset-older', sha256: 'aa' }); await older;",
                    "  console.log(JSON.stringify({ upload: state.saasMediaSourceUpload, status: ui['#mediaProductionStatus'], toast: toasts[toasts.length - 1], statusAfterNewer, toastAfterNewer, epoch: state.saasMediaSourceUploadEpoch }));",
                    "})().catch((error) => { console.error(error); process.exit(1); });",
                ]
            )
        )
        self.assertEqual("asset-newer", result.get("upload", {}).get("asset_id"))
        self.assertEqual(
            {"key": "project-a", "source_report_id": "report-a", "candidate_id": "candidate-a"},
            result.get("upload", {}).get("listing_project_identity"),
        )
        self.assertEqual(result.get("statusAfterNewer"), result.get("status"))
        self.assertEqual(result.get("toastAfterNewer"), result.get("toast"))
        self.assertEqual(2, result.get("epoch"))

    def test_delayed_upload_stays_invalid_after_project_a_to_b_to_a(self) -> None:
        handle_upload = function_body(APP_JS, "handleMediaSourceFile")
        result = run_node_json(
            "\n".join(
                [
                    "const identityA = { key: 'project-a', source_report_id: 'report-a', candidate_id: 'candidate-a' };",
                    "const identityB = { key: 'project-b', source_report_id: 'report-b', candidate_id: 'candidate-b' };",
                    "const state = { saasListingComposerDraft: { product: 'Product A', listing_project_identity: identityA }, activeMediaDraft: 'project-a', saasMediaSourceUpload: null, mediaSourceObjectUrl: '', saasMediaSourceUploadEpoch: 0 };",
                    "const document = { querySelector: () => null };",
                    "const URL = { createObjectURL: () => 'blob:source-a', revokeObjectURL: () => {} };",
                    "const inferMediaLocalPath = () => ({ path: 'source-a.jpg', note: 'test' });",
                    "const ui = {}; const setText = (selector, value) => { ui[selector] = value; };",
                    "const setMediaNewTaskMode = () => {};",
                    "const syncMediaGenerationActionState = () => {};",
                    "const publicRuntimeText = (value = '') => String(value || '');",
                    "const saasCurrentListingProjectIdentity = (draft) => { const value = draft?.listing_project_identity || {}; return { key: value.key || '', source_report_id: value.source_report_id || '', source_id: value.source_report_id || '', candidate_id: value.candidate_id || '' }; };",
                    "const toasts = []; const showActionToast = (message) => toasts.push(message);",
                    "let resolveUpload; const delayedUpload = new Promise((resolve) => { resolveUpload = resolve; });",
                    "const uploadSaasMediaSourceFile = async () => delayedUpload;",
                    handle_upload,
                    "(async () => {",
                    "  const pending = handleMediaSourceFile({ name: 'source-a.jpg', type: 'image/jpeg', size: 1024 }, {}); await Promise.resolve();",
                    "  state.saasMediaSourceUploadEpoch += 1; state.saasListingComposerDraft = { product: 'Product B', listing_project_identity: identityB }; state.activeMediaDraft = 'project-b';",
                    "  state.saasMediaSourceUploadEpoch += 1; state.saasListingComposerDraft = { product: 'Product A', listing_project_identity: identityA }; state.activeMediaDraft = 'project-a'; state.saasMediaSourceUpload = null; ui['#mediaProductionStatus'] = 'A_RESELECTED_STATUS'; toasts.push('A_RESELECTED_TOAST');",
                    "  resolveUpload({ asset_id: 'stale-asset-a', sha256: 'aa' }); await pending;",
                    "  console.log(JSON.stringify({ upload: state.saasMediaSourceUpload, status: ui['#mediaProductionStatus'], toast: toasts[toasts.length - 1], epoch: state.saasMediaSourceUploadEpoch }));",
                    "})().catch((error) => { console.error(error); process.exit(1); });",
                ]
            )
        )
        self.assertIsNone(result.get("upload"))
        self.assertEqual("A_RESELECTED_STATUS", result.get("status"))
        self.assertEqual("A_RESELECTED_TOAST", result.get("toast"))
        self.assertEqual(3, result.get("epoch"))

    def test_stale_failed_upload_does_not_clear_current_project_upload_or_ui(self) -> None:
        handle_upload = function_body(APP_JS, "handleMediaSourceFile")
        result = run_node_json(
            "\n".join(
                [
                    "const identityA = { key: 'project-a', source_report_id: 'report-a', candidate_id: 'candidate-a' };",
                    "const identityB = { key: 'project-b', source_report_id: 'report-b', candidate_id: 'candidate-b' };",
                    "const state = { saasListingComposerDraft: { product: 'Product A', listing_project_identity: identityA }, activeMediaDraft: 'project-a', saasMediaSourceUpload: null, mediaSourceObjectUrl: '', saasMediaSourceUploadEpoch: 0 };",
                    "const document = { querySelector: () => null };",
                    "const URL = { createObjectURL: () => 'blob:source-a', revokeObjectURL: () => {} };",
                    "const inferMediaLocalPath = () => ({ path: 'source-a.jpg', note: 'test' });",
                    "const ui = {}; const setText = (selector, value) => { ui[selector] = value; };",
                    "const setMediaNewTaskMode = () => {};",
                    "const syncMediaGenerationActionState = () => {};",
                    "const publicRuntimeText = (value = '') => String(value || '');",
                    "const saasCurrentListingProjectIdentity = (draft) => { const value = draft?.listing_project_identity || {}; return { key: value.key || '', source_report_id: value.source_report_id || '', source_id: value.source_report_id || '', candidate_id: value.candidate_id || '' }; };",
                    "const toasts = []; const showActionToast = (message) => toasts.push(message);",
                    "let rejectUpload; const delayedUpload = new Promise((resolve, reject) => { rejectUpload = reject; });",
                    "const uploadSaasMediaSourceFile = async () => delayedUpload;",
                    handle_upload,
                    "(async () => {",
                    "  const pending = handleMediaSourceFile({ name: 'source-a.jpg', type: 'image/jpeg', size: 1024 }, {}); await Promise.resolve();",
                    "  state.saasMediaSourceUploadEpoch += 1; state.saasListingComposerDraft = { product: 'Product B', listing_project_identity: identityB }; state.activeMediaDraft = 'project-b'; state.saasMediaSourceUpload = { asset_id: 'asset-b', listing_project_key: 'project-b', listing_project_identity: identityB }; ui['#mediaProductionStatus'] = 'B_CURRENT_STATUS'; toasts.push('B_CURRENT_TOAST');",
                    "  rejectUpload(new Error('old upload failed')); await pending;",
                    "  console.log(JSON.stringify({ upload: state.saasMediaSourceUpload, status: ui['#mediaProductionStatus'], toast: toasts[toasts.length - 1], epoch: state.saasMediaSourceUploadEpoch }));",
                    "})().catch((error) => { console.error(error); process.exit(1); });",
                ]
            )
        )
        self.assertEqual("asset-b", result.get("upload", {}).get("asset_id"))
        self.assertEqual("project-b", result.get("upload", {}).get("listing_project_key"))
        self.assertEqual("B_CURRENT_STATUS", result.get("status"))
        self.assertEqual("B_CURRENT_TOAST", result.get("toast"))
        self.assertEqual(2, result.get("epoch"))

    def test_failed_upload_from_old_identity_is_stale_even_without_epoch_change(self) -> None:
        handle_upload = function_body(APP_JS, "handleMediaSourceFile")
        result = run_node_json(
            "\n".join(
                [
                    "const identityA = { key: 'project-a', source_report_id: 'report-a', candidate_id: 'candidate-a' };",
                    "const identityB = { key: 'project-b', source_report_id: 'report-b', candidate_id: 'candidate-b' };",
                    "const state = { saasListingComposerDraft: { product: 'Product A', listing_project_identity: identityA }, activeMediaDraft: 'project-a', saasMediaSourceUpload: null, mediaSourceObjectUrl: '', saasMediaSourceUploadEpoch: 0, mediaTaskEntry: 'project' };",
                    "const document = { querySelector: () => null };",
                    "const URL = { createObjectURL: () => 'blob:source-a', revokeObjectURL: () => {} };",
                    "const inferMediaLocalPath = () => ({ path: 'source-a.jpg', note: 'test' });",
                    "const ui = {}; const setText = (selector, value) => { ui[selector] = value; };",
                    "const setMediaNewTaskMode = () => { state.mediaTaskEntry = 'single'; };",
                    "const syncMediaGenerationActionState = () => {};",
                    "const publicRuntimeText = (value = '') => String(value || '');",
                    "const saasCurrentListingProjectIdentity = (draft) => { const value = draft?.listing_project_identity || {}; return { key: value.key || '', source_report_id: value.source_report_id || '', source_id: value.source_report_id || '', candidate_id: value.candidate_id || '' }; };",
                    "const toasts = []; const showActionToast = (message) => toasts.push(message);",
                    "let rejectUpload; const delayedUpload = new Promise((resolve, reject) => { rejectUpload = reject; });",
                    "const uploadSaasMediaSourceFile = async () => delayedUpload;",
                    handle_upload,
                    "(async () => {",
                    "  const pending = handleMediaSourceFile({ name: 'source-a.jpg', type: 'image/jpeg', size: 1024 }, {}); await Promise.resolve();",
                    "  state.saasListingComposerDraft = { product: 'Product B', listing_project_identity: identityB }; state.activeMediaDraft = 'project-b'; state.saasMediaSourceUpload = { asset_id: 'asset-b', listing_project_key: 'project-b', listing_project_identity: identityB }; ui['#mediaProductionStatus'] = 'B_CURRENT_STATUS'; toasts.push('B_CURRENT_TOAST');",
                    "  rejectUpload(new Error('old upload failed')); await pending;",
                    "  console.log(JSON.stringify({ upload: state.saasMediaSourceUpload, status: ui['#mediaProductionStatus'], toast: toasts[toasts.length - 1], epoch: state.saasMediaSourceUploadEpoch }));",
                    "})().catch((error) => { console.error(error); process.exit(1); });",
                ]
            )
        )
        self.assertEqual("asset-b", result.get("upload", {}).get("asset_id"))
        self.assertEqual("project-b", result.get("upload", {}).get("listing_project_key"))
        self.assertEqual("B_CURRENT_STATUS", result.get("status"))
        self.assertEqual("B_CURRENT_TOAST", result.get("toast"))
        self.assertEqual(1, result.get("epoch"))

    def test_media_idempotency_changes_when_candidate_identity_changes(self) -> None:
        payload_function = function_body(APP_JS, "buildSaasMediaAssetJobPayload")
        result = run_node_json(
            "\n".join(
                [
                    "const state = { saasModelSettings: {} };",
                    "const activeSaasStore = () => ({ store_id: 'store-a' });",
                    "let currentFacts = {};",
                    "const currentMediaStudioProductFacts = () => currentFacts;",
                    "const mediaGenerationTierKey = () => 'standard';",
                    "const mediaQualityModeKey = () => 'fidelity_first';",
                    "const MEDIA_FACT_LOCKS = Object.freeze(['product_structure']);",
                    "const saasMediaGenerationGroundingGate = () => ({ conceptOnly: false });",
                    "const mediaVideoDurationSeconds = () => 0;",
                    "const hashString = (value) => Array.from(String(value)).reduce((sum, character, index) => sum + character.charCodeAt(0) * (index + 1), 0);",
                    payload_function,
                    "const base = { product: 'Same Name Incense Burner', listing_project_key: 'shared-key', source_asset_id: 'asset-a', source_image_sha256: 'aa', reference_images: [] };",
                    "currentFacts = { ...base, listing_project_identity: { key: 'shared-key', source_report_id: 'report-a', candidate_id: 'candidate-a' } };",
                    "const payloadA = buildSaasMediaAssetJobPayload('same request', { count: 1, generationTierKey: 'standard', qualityMode: 'fidelity_first' });",
                    "currentFacts = { ...base, listing_project_identity: { key: 'shared-key', source_report_id: 'report-a', candidate_id: 'candidate-b' } };",
                    "const payloadB = buildSaasMediaAssetJobPayload('same request', { count: 1, generationTierKey: 'standard', qualityMode: 'fidelity_first' });",
                    "console.log(JSON.stringify({ keyA: payloadA.idempotency_key, keyB: payloadB.idempotency_key, identityA: payloadA.inputs.product_facts.listing_project_identity }));",
                ]
            )
        )
        self.assertNotEqual(result.get("keyA"), result.get("keyB"))
        self.assertEqual("candidate-a", result.get("identityA", {}).get("candidate_id"))

    def test_exact_project_restore_rejects_same_name_facts_and_does_not_revive_unknowns(self) -> None:
        restore_listing = function_body(APP_JS, "restoreSaasListingComposerDraftFromBackendReports")
        result = run_node_json(
            "\n".join(
                [
                    "const identityA = { key: 'project-a', source_report_id: 'report-market-a', candidate_id: 'candidate-a' };",
                    "const identityB = { key: 'project-b', source_report_id: 'report-market-b', candidate_id: 'candidate-b' };",
                    "const state = {",
                    "  saasListingComposerDraft: {",
                    "    product: 'Same Name Incense Burner', listing_project_key: 'project-a', listing_project_identity: identityA,",
                    "    merchant_product_fact_packet: { product_name: 'Same Name Incense Burner', source_confirmed_facts: {}, merchant_confirmed_facts: { sku: 'STALE-SKU', material: 'STALE-MATERIAL' }, derived_listing_suggestions: {}, unknown_facts: ['material', 'sku'], blocked_by: ['old-material', 'old-sku'] }",
                    "  },",
                    "  saasReports: [",
                    "    { report_id: 'facts-partial-key', report_type: 'merchant.product_facts', report: { product: 'Same Name Incense Burner', listing_project_identity: { key: 'project-a' }, merchant_product_fact_packet: { product_name: 'Same Name Incense Burner', source_confirmed_facts: {}, merchant_confirmed_facts: { sku: 'PARTIAL-KEY' }, derived_listing_suggestions: {}, unknown_facts: [] } } },",
                    "    { report_id: 'facts-partial-source', report_type: 'merchant.product_facts', report: { product: 'Same Name Incense Burner', listing_project_identity: { key: 'project-a', candidate_id: 'candidate-a' }, merchant_product_fact_packet: { product_name: 'Same Name Incense Burner', source_confirmed_facts: {}, merchant_confirmed_facts: { sku: 'PARTIAL-SOURCE' }, derived_listing_suggestions: {}, unknown_facts: [] } } },",
                    "    { report_id: 'facts-partial-candidate', report_type: 'merchant.product_facts', report: { product: 'Same Name Incense Burner', listing_project_identity: { key: 'project-a', source_report_id: 'report-market-a' }, merchant_product_fact_packet: { product_name: 'Same Name Incense Burner', source_confirmed_facts: {}, merchant_confirmed_facts: { sku: 'PARTIAL-CANDIDATE' }, derived_listing_suggestions: {}, unknown_facts: [] } } },",
                    "    { report_id: 'facts-b', report_type: 'merchant.product_facts', report: { product: 'Same Name Incense Burner', listing_project_identity: identityB, merchant_product_fact_packet: { product_name: 'Same Name Incense Burner', source_confirmed_facts: {}, merchant_confirmed_facts: { sku: 'B-SKU', image_urls: 'https://b.example/image.jpg' }, derived_listing_suggestions: {}, unknown_facts: [], blocked_by: [] } } },",
                    "    { report_id: 'facts-a', report_type: 'merchant.product_facts', report: { product: 'Same Name Incense Burner', listing_project_identity: identityA, merchant_product_fact_packet: { product_name: 'Same Name Incense Burner', source_confirmed_facts: { material: 'Resin' }, merchant_confirmed_facts: {}, derived_listing_suggestions: {}, unknown_facts: ['sku'], blocked_by: ['merchant_product_fact_missing:sku'] } } },",
                    "  ],",
                    "};",
                    "const saasListingDraftHasConcreteProduct = () => true;",
                    "const latestSaasActionableProductReportByTypes = () => null;",
                    "const saasListingDraftFromReport = () => null;",
                    "const saasCurrentListingProjectIdentity = (draft) => ({ ...(draft.listing_project_identity || {}), source_id: draft.listing_project_identity?.source_report_id || '', product: draft.product || '' });",
                    "const saasNormalizeListingProjectIdentity = (value) => value && value.key ? value : null;",
                    "const isLegacySampleMediaDraftKey = () => false;",
                    "const saasMarketCandidateMatchKey = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9\\u4e00-\\u9fff]+/g, '');",
                    "const applySaasMerchantProductFactPacketToDraft = (draft, packet) => ({ ...draft, merchant_product_fact_packet: packet });",
                    restore_listing,
                    "const restored = restoreSaasListingComposerDraftFromBackendReports();",
                    "console.log(JSON.stringify(restored));",
                ]
            )
        )
        packet = result.get("merchant_product_fact_packet") or {}
        self.assertEqual("facts-a", result.get("source_product_fact_report_id"))
        self.assertEqual(["sku"], packet.get("unknown_facts"))
        self.assertEqual(["merchant_product_fact_missing:sku"], packet.get("blocked_by"))
        self.assertEqual("Resin", (packet.get("source_confirmed_facts") or {}).get("material"))
        self.assertNotIn("material", packet.get("merchant_confirmed_facts") or {})
        self.assertNotIn("sku", packet.get("merchant_confirmed_facts") or {})
        self.assertNotIn("B-SKU", json.dumps(packet, ensure_ascii=False))
        self.assertNotIn("b.example", json.dumps(packet, ensure_ascii=False))
        self.assertNotIn("PARTIAL-", json.dumps(packet, ensure_ascii=False))

    def test_manual_structured_restore_rejects_incoming_extra_identity_fields(self) -> None:
        restore_listing = function_body(APP_JS, "restoreSaasListingComposerDraftFromBackendReports")
        result = run_node_json(
            "\n".join(
                [
                    "const manualIdentity = { key: 'project-manual', source_report_id: '', candidate_id: '' };",
                    "const state = {",
                    "  saasListingComposerDraft: { product: 'Manual Product', listing_project_key: 'project-manual', listing_project_identity: manualIdentity, merchant_product_fact_packet: { product_name: 'Manual Product', source_confirmed_facts: {}, merchant_confirmed_facts: {}, derived_listing_suggestions: {}, unknown_facts: [] } },",
                    "  saasReports: [",
                    "    { report_id: 'extra-source', report_type: 'merchant.product_facts', report: { listing_project_identity: { key: 'project-manual', source_report_id: 'unexpected-report', candidate_id: '' }, merchant_product_fact_packet: { product_name: 'Manual Product', merchant_confirmed_facts: { sku: 'EXTRA-SOURCE' } } } },",
                    "    { report_id: 'extra-candidate', report_type: 'merchant.product_facts', report: { listing_project_identity: { key: 'project-manual', source_report_id: '', candidate_id: 'unexpected-candidate' }, merchant_product_fact_packet: { product_name: 'Manual Product', merchant_confirmed_facts: { sku: 'EXTRA-CANDIDATE' } } } },",
                    "    { report_id: 'manual-exact', report_type: 'merchant.product_facts', report: { listing_project_identity: manualIdentity, merchant_product_fact_packet: { product_name: 'Manual Product', source_confirmed_facts: {}, merchant_confirmed_facts: { sku: 'MANUAL-EXACT' }, derived_listing_suggestions: {}, unknown_facts: [], blocked_by: [] } } },",
                    "  ],",
                    "};",
                    "const saasListingDraftHasConcreteProduct = () => true;",
                    "const latestSaasActionableProductReportByTypes = () => null;",
                    "const saasListingDraftFromReport = () => null;",
                    "const saasCurrentListingProjectIdentity = (draft) => ({ ...draft.listing_project_identity, source_id: draft.listing_project_identity.source_report_id, product: draft.product });",
                    "const saasNormalizeListingProjectIdentity = (value) => value && value.key ? ({ key: value.key, source_report_id: value.source_report_id || '', candidate_id: value.candidate_id || '' }) : null;",
                    "const publicRuntimeText = (value = '') => String(value || '');",
                    "const isLegacySampleMediaDraftKey = () => false;",
                    "const saasMarketCandidateMatchKey = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9\\u4e00-\\u9fff]+/g, '');",
                    "const applySaasMerchantProductFactPacketToDraft = (draft, packet) => ({ ...draft, merchant_product_fact_packet: packet });",
                    restore_listing,
                    "const restored = restoreSaasListingComposerDraftFromBackendReports();",
                    "console.log(JSON.stringify(restored));",
                ]
            )
        )
        self.assertEqual("manual-exact", result.get("source_product_fact_report_id"))
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertIn("MANUAL-EXACT", serialized)
        self.assertNotIn("EXTRA-SOURCE", serialized)
        self.assertNotIn("EXTRA-CANDIDATE", serialized)

    def test_ambiguous_same_name_legacy_fact_reports_do_not_restore(self) -> None:
        restore_listing = function_body(APP_JS, "restoreSaasListingComposerDraftFromBackendReports")
        result = run_node_json(
            "\n".join(
                [
                    "const state = {",
                    "  saasListingComposerDraft: { product: 'Legacy Same Name', merchant_product_fact_packet: { product_name: 'Legacy Same Name', source_confirmed_facts: {}, merchant_confirmed_facts: {}, derived_listing_suggestions: {}, unknown_facts: [] } },",
                    "  saasReports: [",
                    "    { report_id: 'legacy-a', report_type: 'merchant.product_facts', report: { product: 'Legacy Same Name', merchant_product_fact_packet: { product_name: 'Legacy Same Name', merchant_confirmed_facts: { sku: 'A' } } } },",
                    "    { report_id: 'legacy-b', report_type: 'merchant.product_facts', report: { product: 'Legacy Same Name', merchant_product_fact_packet: { product_name: 'Legacy Same Name', merchant_confirmed_facts: { sku: 'B' } } } },",
                    "  ],",
                    "};",
                    "const saasListingDraftHasConcreteProduct = () => true;",
                    "const latestSaasActionableProductReportByTypes = () => null;",
                    "const saasListingDraftFromReport = () => null;",
                    "const saasCurrentListingProjectIdentity = () => ({ key: 'legacy-generated', source_report_id: '', source_id: '', candidate_id: '', product: 'Legacy Same Name' });",
                    "const saasNormalizeListingProjectIdentity = (value) => value && value.key ? value : null;",
                    "const publicRuntimeText = (value = '') => String(value || '');",
                    "const isLegacySampleMediaDraftKey = () => false;",
                    "const saasMarketCandidateMatchKey = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9\\u4e00-\\u9fff]+/g, '');",
                    "const applySaasMerchantProductFactPacketToDraft = (draft, packet) => ({ ...draft, merchant_product_fact_packet: packet });",
                    restore_listing,
                    "const restored = restoreSaasListingComposerDraftFromBackendReports();",
                    "console.log(JSON.stringify(restored));",
                ]
            )
        )
        self.assertNotIn("source_product_fact_report_id", result)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn('"sku": "A"', serialized)
        self.assertNotIn('"sku": "B"', serialized)

    def test_frontend_product_fact_save_posts_identity_and_applies_the_server_packet(self) -> None:
        save_function = function_body(APP_JS, "saveSaasMerchantProductFacts")
        result = run_node_json(
            "\n".join(
                [
                    "const identity = { key: 'project-a', source_report_id: 'report-a', candidate_id: 'candidate-a' };",
                    "const SAAS_MERCHANT_PRODUCT_FACT_PACKET_CONTRACT = 'merchant_product_fact_packet_v1';",
                    "const state = {",
                    "  saasConnected: true, saasTasks: [], saasReports: [],",
                    "  saasListingComposerDraft: { product: 'Incense Burner', title: 'Incense Burner', listing_project_key: 'project-a', listing_project_identity: identity, fields: {}, publish_prefill: {}, merchant_product_fact_packet: { product_name: 'Incense Burner', source_records: [], source_confirmed_facts: {}, merchant_confirmed_facts: {}, derived_listing_suggestions: {}, unknown_facts: ['material'] } },",
                    "};",
                    "const collectSaasMerchantProductFacts = () => ({ merchantConfirmed: { product_name: 'Incense Burner' }, unknownFacts: ['material'] });",
                    "const saasMerchantProductFactPacket = (draft) => ({ ...draft.merchant_product_fact_packet, listing_readiness: { ready_for_listing_generation: false } });",
                    "const saasMerchantProductFactProjectedValue = (_packet, facts, key, fallback) => facts[key] || fallback || '';",
                    "const saasListingItemSpecificsWithMerchantFacts = (value) => value;",
                    "const saasMerchantProductFactLabel = (value) => value;",
                    "const saveSaasProtectedStateSnapshot = () => {};",
                    "const renderProductListingCenter = () => {};",
                    "const activeSaasStore = () => ({ store_id: 'store-a' });",
                    "const sanitizeSaasMerchantProductFactPacketSnapshot = (packet) => packet;",
                    "const saasCurrentListingProjectIdentity = () => ({ ...identity, source_id: identity.source_report_id });",
                    "const saasNormalizeListingProjectIdentity = (value) => value && value.key ? value : null;",
                    "let capturedBody = null; let applied = false;",
                    "const saasFetch = async (_path, options) => { capturedBody = JSON.parse(options.body); return {",
                    "  listing_project_identity: identity,",
                    "  merchant_product_fact_packet: { product_name: 'Incense Burner', source_confirmed_facts: { material: 'Resin' }, merchant_confirmed_facts: {}, derived_listing_suggestions: {}, unknown_facts: [], blocked_by: [] },",
                    "  task: { task_id: 'task-a' }, report: { report_id: 'facts-a' },",
                    "}; };",
                    "const applySaasMerchantProductFactPacketToDraft = (draft, packet) => { applied = true; return { ...draft, merchant_product_fact_packet: packet, applied_server_packet: true }; };",
                    "const showActionToast = () => {};",
                    save_function,
                    "(async () => { await saveSaasMerchantProductFacts(); console.log(JSON.stringify({ capturedBody, applied, draft: state.saasListingComposerDraft })); })().catch((error) => { console.error(error); process.exit(1); });",
                ]
            )
        )
        expected_identity = {"key": "project-a", "source_report_id": "report-a", "candidate_id": "candidate-a"}
        self.assertEqual(expected_identity, result.get("capturedBody", {}).get("listing_project_identity"))
        self.assertIs(result.get("applied"), True)
        self.assertIs(result.get("draft", {}).get("applied_server_packet"), True)
        self.assertEqual([], result.get("draft", {}).get("merchant_product_fact_packet", {}).get("unknown_facts"))
        self.assertEqual(expected_identity, result.get("draft", {}).get("listing_project_identity"))

    def test_completed_vision_report_recovers_into_the_matching_existing_listing(self) -> None:
        restore_listing = function_body(APP_JS, "restoreSaasListingComposerDraftFromBackendReports")
        result = run_node_json(
            "\n".join(
                [
                    "const sourceUrl = 'https://qr.1688.com/s/FqVegjLr';",
                    "const state = {",
                    "  saasListingComposerDraft: {",
                    "    product: '禅意佛手托莲花倒流香炉',",
                    "    merchant_product_fact_packet: {",
                    "      merchant_confirmed_facts: { source_url: sourceUrl, supplier_item_number: 'JC2023041300002', product_name: '禅意佛手托莲花倒流香炉' },",
                    "      source_confirmed_facts: {}, derived_listing_suggestions: {}, source_records: []",
                    "    }",
                    "  },",
                    "  saasReports: [{",
                    "    report_id: 'report_vision_saved', report_type: 'merchant.product_facts',",
                    "    report: { product: '禅意佛手莲花倒流香炉', merchant_product_fact_packet: {",
                    "      product_name: '禅意佛手莲花倒流香炉',",
                    "      source_confirmed_facts: { source_url: sourceUrl, supplier_item_number: 'JC2023041300002', net_weight_g: '451' },",
                    "      merchant_confirmed_facts: {}, derived_listing_suggestions: { condition: 'NEW' },",
                    "      field_evidence: { net_weight_g: { image_indexes: [5], confidence: 0.99 } },",
                    "      fact_conflicts: [{ field: 'material', values: ['树脂', '紫砂'] }],",
                    "      unknown_facts: ['sku', 'material'], source_records: [{ type: 'merchant_product_image', asset_id: 'asset_1' }]",
                    "    }}",
                    "  }]",
                    "};",
                    "const saasListingDraftHasConcreteProduct = () => true;",
                    "const latestSaasActionableProductReportByTypes = () => null;",
                    "const saasListingDraftFromReport = () => null;",
                    "const saasCurrentListingProjectIdentity = () => ({ key: 'incense' });",
                    "const saasNormalizeListingProjectIdentity = (value) => value && value.key ? value : null;",
                    "const publicRuntimeText = (value = '') => String(value || '');",
                    "const isLegacySampleMediaDraftKey = () => false;",
                    "const saasMarketCandidateMatchKey = (value) => String(value || '').toLowerCase().replace(/[^a-z0-9\\u4e00-\\u9fff]+/g, '');",
                    "const applySaasMerchantProductFactPacketToDraft = (draft, packet) => ({ ...draft, merchant_product_fact_packet: packet });",
                    restore_listing,
                    "const restored = restoreSaasListingComposerDraftFromBackendReports();",
                    "console.log(JSON.stringify({ restored, sourceMode: state.saasListingSourceMode }));",
                ]
            )
        )
        packet = result.get("restored", {}).get("merchant_product_fact_packet", {})
        self.assertEqual("report_vision_saved", result.get("restored", {}).get("source_product_fact_report_id"))
        self.assertEqual("JC2023041300002", packet.get("merchant_confirmed_facts", {}).get("supplier_item_number"))
        self.assertEqual([5], packet.get("field_evidence", {}).get("net_weight_g", {}).get("image_indexes"))
        self.assertEqual("backend_product_fact_restore", result.get("sourceMode"))

    def test_product_vision_chat_gets_a_longer_timeout_without_slowing_text_chat(self) -> None:
        request_chat = function_body(APP_JS, "requestSaasAiCeoChat")
        result = run_node_json(
            "\n".join(
                [
                    "const state = { saasAiCeoSupplierFactAttestation: null };",
                    "const normalizeSaasCeoCommand = (value) => value;",
                    "const hasSaasProtectedSessionCandidate = () => true;",
                    "const sanitizeSaasCeoCommandSourceText = (value) => String(value || '');",
                    "const saasAiCeoConversationHistoryForRequest = () => [];",
                    "const isSaasRealPlatformWritesEnabled = () => false;",
                    "const supplierFactsForSaasAiCeoCommand = () => ({});",
                    "const capturedTimeouts = [];",
                    "const saasFetchNdjsonWithTimeout = async (_path, _options, timeoutMs) => { capturedTimeouts.push(timeoutMs); return {}; };",
                    request_chat,
                    "(async () => {",
                    "  const command = { store_id: 'store_unit', text: '整理商品资料', route: 'listing', intent: 'listing', summary: '', title: '' };",
                    "  await requestSaasAiCeoChat(command, {}, []);",
                    "  await requestSaasAiCeoChat(command, {}, ['asset_1', 'asset_2', 'asset_3', 'asset_4', 'asset_5', 'asset_6', 'asset_7']);",
                    "  console.log(JSON.stringify({ capturedTimeouts }));",
                    "})().catch((error) => { console.error(error); process.exit(1); });",
                ]
            )
        )
        self.assertEqual([60000, 180000], result.get("capturedTimeouts"))

    def test_chat_request_carries_only_the_active_listing_snapshot(self) -> None:
        active_context = function_body(APP_JS, "saasAiCeoActiveListingContext")
        request_chat = function_body(APP_JS, "requestSaasAiCeoChat")
        result = run_node_json(
            "\n".join(
                [
                    "const state = {",
                    "  saasAiCeoSupplierFactAttestation: null,",
                    "  saasListingComposerDraft: {",
                    "    product: '禅意佛手托莲花倒流香炉', title: 'Zen Hand Lotus Backflow Incense Burner',",
                    "    listing_project_identity: { key: 'project-incense', source_report_id: 'report-incense', candidate_id: 'candidate-incense' },",
                    "    merchant_product_fact_packet: { source_confirmed_facts: { net_weight_g: '451', source_url: 'https://supplier.example/item' }, merchant_confirmed_facts: { sku: 'JJ-INCENSE-01' }, unknown_facts: ['package_weight_g', 'selling_price'] },",
                    "    media_writeback: { media_job_id: 'media-incense', asset_count: 1, image_urls: ['https://private.example/asset.jpg'], status: 'merchant_reviewed_for_listing_draft', review_status: 'approved_for_listing', rights_status: 'merchant_rights_confirmed', listing_use_status: 'approved_for_listing_draft' }",
                    "  },",
                    "  saasAccountHealth: { status: 'restricted', severity: 'red', onboarding_stage: 'account_review_required', access_token: 'MUST_NOT_LEAK' }",
                    "};",
                    "const normalizeSaasCeoCommand = (value) => value;",
                    "const hasSaasProtectedSessionCandidate = () => true;",
                    "const sanitizeSaasCeoCommandSourceText = (value) => String(value || '');",
                    "const saasAiCeoConversationHistoryForRequest = () => [];",
                    "const isSaasRealPlatformWritesEnabled = () => false;",
                    "const supplierFactsForSaasAiCeoCommand = () => ({});",
                    "const saasCurrentListingProjectIdentity = () => ({ key: 'project-incense', product: '禅意佛手托莲花倒流香炉', source_report_id: 'report-incense', candidate_id: 'candidate-incense' });",
                    "const saasListingDraftAuthoritativeSku = () => 'JJ-INCENSE-01';",
                    "const latestSaasMediaAssetJobWithManifest = () => null;",
                    "const saasMediaManifestAssetCards = () => [];",
                    "const saasMediaManifestAssetsForListing = () => [];",
                    "const saasListingMediaWritebackForDraft = (draft) => draft.media_writeback || null;",
                    "const saasListingMediaWritebackRightsReady = () => true;",
                    "const saasCurrentUnpublishedDraftReceipt = () => ({ offerId: '245675556011', sku: 'JJ-INCENSE-01', executionId: 'exec-incense', confirmationId: 'confirm-incense', status: 'UNPUBLISHED' });",
                    "const publicRuntimeText = (value = '') => String(value || '');",
                    active_context,
                    request_chat,
                    "let capturedBody = null;",
                    "let capturedTimeout = 0;",
                    "const saasFetchNdjsonWithTimeout = async (_path, options, timeoutMs) => { capturedBody = JSON.parse(options.body); capturedTimeout = timeoutMs; return {}; };",
                    "(async () => {",
                    "  await requestSaasAiCeoChat({ store_id: 'store-unit', text: '继续当前 SKU 和 Offer 做第二遍验收', route: 'listing', intent: 'listing', summary: '', title: '' });",
                    "  console.log(JSON.stringify({ ...capturedBody, capturedTimeout }));",
                    "})().catch((error) => { console.error(error); process.exit(1); });",
                ]
            )
        )
        snapshot = result.get("active_listing_context") or {}
        self.assertEqual("active_listing_context_v1", snapshot.get("contract_version"))
        self.assertEqual("project-incense", snapshot.get("listing_project_identity", {}).get("key"))
        self.assertEqual("JJ-INCENSE-01", snapshot.get("listing", {}).get("sku"))
        self.assertEqual(1, snapshot.get("media", {}).get("asset_manifest_count"))
        self.assertEqual(1, snapshot.get("media", {}).get("listing_eligible_asset_count"))
        self.assertIs(snapshot.get("media", {}).get("rights_confirmed_for_listing_draft"), True)
        self.assertIs(snapshot.get("media", {}).get("product_fact_review_required_before_publish"), True)
        self.assertEqual("245675556011", snapshot.get("ebay_draft", {}).get("offer_id"))
        self.assertIs(snapshot.get("ebay_draft", {}).get("public_listing_created"), False)
        self.assertEqual("restricted", snapshot.get("account_health", {}).get("status"))
        self.assertEqual(180000, result.get("capturedTimeout"))
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("MUST_NOT_LEAK", serialized)
        self.assertNotIn("private.example", serialized)

    def test_decision_center_rejects_stale_product_confirmations_for_active_listing(self) -> None:
        matcher = function_body(APP_JS, "saasConfirmationMatchesActiveListingContext")
        result = run_node_json(
            "\n".join(
                [
                    "const state = {};",
                    "const saasCurrentListingProjectIdentity = () => ({ key: 'project-incense', product: '禅意佛手托莲花倒流香炉', source_report_id: 'report-incense', candidate_id: 'candidate-incense' });",
                    "const saasListingDraftAuthoritativeSku = () => 'JJ-INCENSE-01';",
                    "const saasCurrentUnpublishedDraftReceipt = () => ({ offerId: '245675556011', sku: 'JJ-INCENSE-01' });",
                    "const saasNormalizeListingProjectIdentity = (value) => value && value.key ? value : null;",
                    matcher,
                    "const current = { confirmation_id: 'confirm-current', action_type: 'publish_listing', item: { listing_project_identity: { key: 'project-incense', source_report_id: 'report-incense', candidate_id: 'candidate-incense' }, existing_ebay_draft: { offer_id: '245675556011', sku: 'JJ-INCENSE-01' } } };",
                    "const stale = { confirmation_id: 'confirm-stale', action_type: 'change_price', task_id: 'old-task', item: { product_name: '旧手机壳', publish_payload: { listing: { sku: 'OLD-CASE-01' } } } };",
                    "const unbound = { confirmation_id: 'confirm-unbound', action_type: 'change_store_policy', task_id: 'old-policy-task', item: {} };",
                    "console.log(JSON.stringify({ current: saasConfirmationMatchesActiveListingContext(current), stale: saasConfirmationMatchesActiveListingContext(stale), unbound: saasConfirmationMatchesActiveListingContext(unbound) }));",
                ]
            )
        )
        self.assertIs(result.get("current"), True)
        self.assertIs(result.get("stale"), False)
        self.assertIs(result.get("unbound"), False)

    def test_decision_center_recovers_current_listing_scope_before_listing_view_renders(self) -> None:
        scope_helper = function_body(APP_JS, "saasActiveListingConfirmationScope")
        matcher = function_body(APP_JS, "saasConfirmationMatchesActiveListingContext")
        result = run_node_json(
            "\n".join(
                [
                    "const state = { saasConfirmations: [] };",
                    "const saasCurrentListingProjectIdentity = () => ({ key: '', product: '', source_report_id: '', candidate_id: '' });",
                    "const saasListingDraftAuthoritativeSku = () => '';",
                    "const saasCurrentUnpublishedDraftReceipt = () => null;",
                    "const saasNormalizeListingProjectIdentity = (value) => value && value.key ? value : null;",
                    "const saasTimestampMillis = (value) => Date.parse(value || '') || 0;",
                    scope_helper,
                    matcher,
                    "const cards = [",
                    "  { confirmation_id: 'confirm-old-price', action_type: 'change_price', created_at: '2026-08-10T19:11:00Z', item: {} },",
                    "  { confirmation_id: 'confirm-current-publish', action_type: 'publish_listing', status: 'approved', created_at: '2026-08-26T12:17:00Z', item: { controlled_existing_draft_publish: true, listing_project_identity: { key: 'project-incense', source_report_id: 'report-incense', candidate_id: 'candidate-incense' }, existing_ebay_draft: { offer_id: '245675556011', sku: 'JJ-INCENSE-01' } } },",
                    "  { confirmation_id: 'confirm-old-policy', action_type: 'change_store_policy', created_at: '2026-08-10T19:11:00Z', item: {} },",
                    "];",
                    "const scope = saasActiveListingConfirmationScope(cards);",
                    "console.log(JSON.stringify({ scope, current: saasConfirmationMatchesActiveListingContext(cards[1], scope), oldPrice: saasConfirmationMatchesActiveListingContext(cards[0], scope), oldPolicy: saasConfirmationMatchesActiveListingContext(cards[2], scope) }));",
                ]
            )
        )
        self.assertEqual("JJ-INCENSE-01", result.get("scope", {}).get("sku"))
        self.assertEqual("245675556011", result.get("scope", {}).get("offer_id"))
        self.assertIs(result.get("current"), True)
        self.assertIs(result.get("oldPrice"), False)
        self.assertIs(result.get("oldPolicy"), False)

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

#!/usr/bin/env python3
"""Readiness accepts only one callback-bound unpublished eBay draft receipt."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.ebay_oauth import EbayOAuthPlanner, UNPUBLISHED_DRAFT_SCOPES  # noqa: E402
from jiejing_saas.ebay_oauth_callback import process_ebay_oauth_callback  # noqa: E402
from jiejing_saas.readiness import build_product_readiness  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.secret_store import SecretStoreBoundary  # noqa: E402
from jiejing_runtime.execution import ExecutionRequest, ExecutionService  # noqa: E402
from jiejing_saas.ebay_write_adapter import build_ebay_execution_plan


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def _canonical_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _attach_server_resolved_publish_evidence(
    payload: dict[str, Any],
    *,
    company_id: str,
    store_id: str,
) -> None:
    project_key = "readiness-exact-draft-project"
    report_id = "report_readiness_exact_draft"
    payload["listing_project_identity"] = {
        "key": project_key,
        "source_report_id": report_id,
        "candidate_id": "candidate_readiness_exact_draft",
    }
    manifest = payload.get("asset_manifest") if isinstance(payload.get("asset_manifest"), dict) else {}
    assets = manifest.get("assets") if isinstance(manifest.get("assets"), list) else []
    covered_assets = []
    for raw_asset in assets:
        asset = raw_asset if isinstance(raw_asset, dict) else {}
        asset_url = str(asset.get("url") or asset.get("url_or_file_path") or "").strip()
        covered_assets.append(
            {
                "asset_id": str(asset.get("asset_id") or "").strip(),
                "url_sha256": hashlib.sha256(asset_url.encode("utf-8")).hexdigest(),
                "evidence_type": "merchant_product_fact_report",
                "evidence_id": report_id,
            }
        )
    evidence = {
        "contract_version": "2026-08-31-publish-source-rights-evidence-v1",
        "status": "ready",
        "server_resolved": True,
        "scope": {
            "company_id": company_id,
            "store_id": store_id,
            "listing_project_key": project_key,
        },
        "refs": {
            "product_fact_report_id": report_id,
            "media_job_id": "",
        },
        "product_source": {
            "status": "verified",
            "source_mode": "merchant_source_supplied",
            "evidence_type": "merchant_product_fact_report",
            "evidence_id": report_id,
        },
        "image_rights": {
            "status": "verified",
            "required_asset_count": len(covered_assets),
            "covered_asset_count": len(covered_assets),
            "coverage_complete": True,
            "assets": covered_assets,
        },
        "resolved_at": "2026-08-31T00:00:00Z",
        "secret_exposed": False,
    }
    fingerprint_payload = {
        key: value for key, value in evidence.items() if key not in {"resolved_at", "fingerprint"}
    }
    evidence["fingerprint"] = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    payload["publish_evidence"] = evidence


def _oauth_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
    del timeout
    if request.get_method() == "GET" and request.full_url.endswith("/commerce/identity/v1/user/"):
        return (
            200,
            {"content-type": "application/json"},
            json.dumps(
                {
                    "userId": "READINESS-EXACT-SELLER-DO-NOT-LEAK",
                    "username": "readiness-exact-seller",
                    "registrationMarketplaceId": "EBAY_US",
                    "accountType": "BUSINESS",
                    "status": "CONFIRMED",
                }
            ).encode("utf-8"),
        )
    if request.get_method() == "POST" and "/identity/v1/oauth2/token" in request.full_url:
        return (
            200,
            {"content-type": "application/json"},
            json.dumps(
                {
                    "access_token": "READINESS-ACCESS-TOKEN-DO-NOT-LEAK",
                    "refresh_token": "READINESS-REFRESH-TOKEN-DO-NOT-LEAK",
                    "expires_in": 7200,
                    "refresh_token_expires_in": 47304000,
                    "scope": " ".join(UNPUBLISHED_DRAFT_SCOPES),
                }
            ).encode("utf-8"),
        )
    return 404, {"content-type": "application/json"}, b'{"error":"missing"}'


def _vault_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
    del timeout
    if request.get_method() != "POST":
        return 405, {"content-type": "application/json"}, b'{"errors":["method"]}'
    return 204, {"content-type": "application/json"}, b""


def _new_case(root: Path, case_key: str) -> tuple[SaaSSettings, SaaSRepository, dict[str, str]]:
    settings = SaaSSettings.from_env(
        db_path=root / f"{case_key}.sqlite",
        runtime_db_path=root / f"{case_key}-runtime.sqlite",
        output_root=root / case_key,
        host="127.0.0.1",
        port=8788,
    )
    repo = SaaSRepository(settings.db_path, database_engine="sqlite")
    account = repo.create_user_with_company(
        email=f"{case_key}@example.test",
        password="Password123!",
        company_name=f"{case_key} company",
    )
    user = account["user"]
    store = repo.create_store(
        company_id=user["default_company_id"],
        user_id=user["user_id"],
        payload={"platform": "ebay", "store_name": f"{case_key} store", "marketplace": "EBAY_US"},
    )
    return settings, repo, {
        "company_id": user["default_company_id"],
        "user_id": user["user_id"],
        "store_id": store["store_id"],
    }


def _seed_exact_draft_callback(
    settings: SaaSSettings,
    repo: SaaSRepository,
    context: dict[str, str],
) -> dict[str, Any]:
    planner = EbayOAuthPlanner(settings)
    confirmation = repo.create_unpublished_draft_oauth_confirmation(
        company_id=context["company_id"],
        store_id=context["store_id"],
        user_id=context["user_id"],
    )
    confirmation = repo.decide_confirmation(
        company_id=context["company_id"],
        confirmation_id=confirmation["confirmation_id"],
        decision="approve",
        decided_by=context["user_id"],
        note="Exact readiness callback fixture.",
        expected_access_epochs=repo.access_session_epochs(user_id=context["user_id"],company_id=context["company_id"]),
    )
    plan = planner.unpublished_draft_authorization_plan(
        company_id=context["company_id"],
        store_id=context["store_id"],
        user_id=context["user_id"],
        marketplace_id="EBAY_US",
        requested_scopes=UNPUBLISHED_DRAFT_SCOPES,
    )
    plan["confirmation_id"] = confirmation["confirmation_id"]
    request = repo.create_approved_unpublished_draft_oauth_authorization_request(
        company_id=context["company_id"],
        store_id=context["store_id"],
        user_id=context["user_id"],
        confirmation_id=confirmation["confirmation_id"],
        plan=plan,
    )
    callback = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=planner,
        state=request["state_nonce"],
        code="READINESS_EXACT_DRAFT_AUTH_CODE",
        error="",
        oauth_transport=_oauth_transport,
        vault_transport=_vault_transport,
    )
    if callback.get("status") != "callback_exchange_completed":
        raise AssertionError(f"exact draft OAuth callback did not complete: {callback.get('status')}")
    boundary = repo.unpublished_draft_execution_credential_boundary(
        company_id=context["company_id"],
        store_id=context["store_id"],
    )
    if boundary.get("ready") is not True or boundary.get("connection_status") != "draft_save_authorized":
        raise AssertionError(f"exact draft credential boundary not ready: {boundary.get('code')}")
    return boundary


def _seed_read_only_callback(
    settings: SaaSSettings,
    repo: SaaSRepository,
    context: dict[str, str],
) -> None:
    planner = EbayOAuthPlanner(settings)
    plan = planner.read_only_authorization_plan(
        company_id=context["company_id"],
        store_id=context["store_id"],
        user_id=context["user_id"],
        marketplace_id="EBAY_US",
    )
    request = repo.create_oauth_authorization_request(
        company_id=context["company_id"],
        store_id=context["store_id"],
        user_id=context["user_id"],
        plan=plan,
    )
    callback = process_ebay_oauth_callback(
        repository=repo,
        settings=settings,
        secret_store_boundary=SecretStoreBoundary(settings),
        ebay_oauth_planner=planner,
        state=request["state_nonce"],
        code="READINESS_READ_ONLY_AUTH_CODE",
        error="",
        oauth_transport=_oauth_transport,
        vault_transport=_vault_transport,
    )
    if callback.get("status") != "callback_exchange_completed":
        raise AssertionError(f"read-only OAuth callback did not complete: {callback.get('status')}")
    if (callback.get("connection") or {}).get("status") != "read_only_authorized":
        raise AssertionError("read-only callback fixture must start with read_only_authorized")


def _seed_draft_execution(
    repo: SaaSRepository,
    context: dict[str, str],
    boundary: dict[str, Any],
) -> str:
    publish_payload = {
        "account_health": {"status": "ready"},
        "listing": {
            "sku": "READINESS-EXACT-DRAFT-001",
            "title": "Readiness exact unpublished draft",
            "description_html": "Exact unpublished draft readiness proof.",
            "category_id": "20349",
            "category_leaf": "Cases, Covers & Skins",
            "condition": "NEW",
            "price": 9.99,
            "quantity": 1,
            "item_specifics": {"Brand": "Unbranded", "Type": "Fitted Case/Skin"},
            "merchant_location_key": "readiness-warehouse",
        },
        "business_policies": {
            "fulfillment_policy_id": "readiness-fulfillment",
            "payment_policy_id": "readiness-payment",
            "return_policy_id": "readiness-return",
        },
        "asset_manifest": {
            "assets": [
                {
                    "asset_id": "asset_readiness_exact_draft_main",
                    "asset_type": "image",
                    "role": "main",
                    "url": "https://i.ebayimg.com/images/g/example/s-l1600.webp",
                }
            ]
        },
        "marketplace_id": "EBAY_US",
    }
    _attach_server_resolved_publish_evidence(
        publish_payload,
        company_id=context["company_id"],
        store_id=context["store_id"],
    )
    task = repo.create_task(
        company_id=context["company_id"],
        store_id=context["store_id"],
        user_id=context["user_id"],
        task_type="ebay_draft_save_intake",
        title="Controlled exact draft proof",
        input_data={"secret_exposed": False},
    )
    confirmation = repo.create_confirmation(
        company_id=context["company_id"],
        store_id=context["store_id"],
        task_id=task["task_id"],
        runtime_run_id="merchant_ebay_draft_save_intake",
        action_type="save_ebay_listing_draft",
        title="Controlled exact draft proof",
        item={
            "source": "merchant_ebay_draft_save_intake",
            "company_id": context["company_id"],
            "store_id": context["store_id"],
            "draft_save_capability_requested": True,
            "writes_to_ebay_after_approval": True,
            "public_publish_enabled": False,
            "real_platform_writes_enabled": False,
            "publish_payload": publish_payload,
            "publish_payload_sha256": _canonical_sha256(publish_payload),
            "secret_exposed": False,
        },
        created_by=context["user_id"],
    )
    repo.decide_confirmation(
        company_id=context["company_id"],
        confirmation_id=confirmation["confirmation_id"],
        decision="approve",
        decided_by=context["user_id"],
        note="Approve exact unpublished draft readiness fixture.",
        expected_access_epochs=repo.access_session_epochs(user_id=context["user_id"],company_id=context["company_id"]),
    )
    binding = {
        "confirmation_id": confirmation["confirmation_id"],
        "company_id": context["company_id"],
        "store_id": context["store_id"],
        "action_type": "save_ebay_listing_draft",
        "task_id": task["task_id"],
        "idempotency_key": "readiness-exact-draft",
        "marketplace_id": "EBAY_US",
        "payload_sha256": _canonical_sha256(publish_payload),
        "preparation_sha256": hashlib.sha256(b"readiness-exact-draft-preparation").hexdigest(),
        "contract_version": "2026-08-13-unpublished-draft-credential-v1",
        **{
        key: str(boundary.get(key) or "")
        for key in (
            "connection_id_sha256",
            "credential_ref_sha256",
            "oauth_request_id_sha256",
            "seller_identity_sha256",
        )
        },
    }
    if not all(binding.values()):
        raise AssertionError("exact draft credential boundary must return all value-free receipt hashes")
    claim_binding = {
        "confirmation_id": confirmation["confirmation_id"],
        "company_id": context["company_id"],
        "store_id": context["store_id"],
        "action_type": "save_ebay_listing_draft",
        "task_id": task["task_id"],
        "idempotency_key": "readiness-exact-draft",
        "payload_sha256": _canonical_sha256(publish_payload),
        **binding,
    }
    claimed, capability = repo.claim_unpublished_draft_execution(
        company_id=context["company_id"],
        confirmation_id=confirmation["confirmation_id"],
        user_id=context["user_id"],
        expected_binding=claim_binding,
        expected_access_epochs=repo.access_session_epochs(user_id=context['user_id'],company_id=context['company_id']),
        operation_plan=build_ebay_execution_plan(request=SimpleNamespace(**context,
            confirmation_id=confirmation['confirmation_id'],task_id=task['task_id'],
            action_type='save_ebay_listing_draft',payload=publish_payload),
            marketplace_id='EBAY_US',credential_boundary=boundary,draft_offer_id=''),
    )
    consumed = repo.consume_unpublished_draft_execution_claim(capability=capability)
    claimed = {
        **claimed,
        **consumed,
    }
    execution_request = ExecutionRequest(
        action_type="save_ebay_listing_draft",
        task_id=task["task_id"],
        user_id=context["user_id"],
        company_id=context["company_id"],
        store_id=context["store_id"],
        platform="ebay",
        payload=publish_payload,
        confirmation_id=confirmation["confirmation_id"],
        confirmed_by=context["user_id"],
        confirmed_at=claimed["decided_at"],
        idempotency_key="readiness-exact-draft",
    )
    boundary_audit = ExecutionService(demo_mode=False).execute(execution_request).to_dict()["audit"]
    execution_audit = {
        "user_id": context["user_id"],
        "company_id": context["company_id"],
        "store_id": context["store_id"],
        "platform": "ebay",
        "confirmation_id": confirmation["confirmation_id"],
        "confirmed_by": context["user_id"],
        "confirmed_at": claimed["decided_at"],
        "idempotency_key_present": True,
        "execution_mode": "ebay_inventory_draft_save_adapter",
        "platform_adapter_called": True,
        "preflight": boundary_audit["preflight"],
        "idempotency": boundary_audit["idempotency"],
        "execution_intent": boundary_audit["execution_intent"],
        "real_execution": {"ebay_draft_saved": True, "published_to_ebay": False},
    }
    result = {
        "status": "saved_to_ebay_draft",
        "action_type": "save_ebay_listing_draft",
        "task_id": task["task_id"],
        "created_at": "2026-08-13T00:00:00+00:00",
        "platform_result": {
            "offer_status": "UNPUBLISHED",
            "writes_to_ebay": True,
            "published_to_ebay": False,
            "public_listing_created": False,
            "authorization_kind": "unpublished_draft",
            "scope_profile": "seller_unpublished_draft",
            **binding,
        },
        "audit": execution_audit,
        "secret_exposed": False,
    }
    repo.save_execution_result(confirmation=claimed, result=result)
    return confirmation["confirmation_id"]


def _execution_item(settings: SaaSSettings, repo: SaaSRepository) -> dict[str, Any]:
    # Keep real readiness/operational-health logic, but isolate its HTTP boundary.
    expected = (
        (
            "health",
            "https://vault.example.test/v1/sys/health",
            {},
            {"initialized": True, "sealed": False},
        ),
        (
            "lookup",
            "https://vault.example.test/v1/auth/token/lookup-self",
            {"x-vault-token": "READINESS-VAULT-TOKEN-DO-NOT-LEAK"},
            {"data": {"id": "READINESS-SYNTHETIC-LOOKUP", "renewable": True, "period": 3600}},
        ),
    )
    observed: list[str] = []

    def synthetic_vault_urlopen(*args: Any, **kwargs: Any) -> BytesIO:
        attempt = len(observed)
        # Record before validation: readiness may catch the resulting exception.
        # Store only fixed labels, never unknown URLs, headers or request bodies.
        observed.append("unexpected")
        if (len(args) != 1 or set(kwargs) != {"timeout"}
                or type(kwargs["timeout"]) is not int or kwargs["timeout"] != 3
                or attempt >= len(expected)):
            raise AssertionError("unexpected readiness HTTP call contract")
        request = args[0]
        label, url, headers, payload = expected[attempt]
        if (not isinstance(request, Request) or request.full_url != url
                or request.get_method() != "GET" or request.data is not None
                or sorted((key.lower(), value) for key, value in request.header_items())
                != sorted(headers.items())):
            raise AssertionError("unexpected readiness Vault request contract")
        observed[attempt] = label
        return BytesIO(json.dumps(payload).encode("utf-8"))

    with patch("jiejing_saas.operational_health.urllib.request.urlopen", side_effect=synthetic_vault_urlopen):
        readiness = build_product_readiness(settings, repo)
    if observed != ["health", "lookup"]:
        raise AssertionError("readiness must use only the two exact synthetic Vault GETs")
    return next(item for item in readiness["items"] if item["key"] == "execution_service")


def _proof_count(repo: SaaSRepository) -> int:
    evidence = repo.product_readiness_evidence()
    return int(evidence.get("ebay_unpublished_draft_save_proof_count") or 0)


def _require_exact_baseline(repo: SaaSRepository, label: str) -> None:
    if _proof_count(repo) != 1:
        raise AssertionError(f"{label} mutation requires a proven exact callback baseline")


def _seed_exact_case(
    root: Path,
    case_key: str,
    *,
    upgrade_from_read_only: bool = False,
) -> tuple[SaaSSettings, SaaSRepository, dict[str, str], dict[str, Any], str]:
    settings, repo, context = _new_case(root, case_key)
    if upgrade_from_read_only:
        _seed_read_only_callback(settings, repo, context)
    boundary = _seed_exact_draft_callback(settings, repo, context)
    confirmation_id = _seed_draft_execution(repo, context, boundary)
    return settings, repo, context, boundary, confirmation_id


def _mutate_execution_result(
    repo: SaaSRepository,
    confirmation_id: str,
    mutate: Any,
) -> None:
    with repo._connect() as conn:
        row = conn.execute(
            "select result_json from execution_results where confirmation_id = ?",
            (confirmation_id,),
        ).fetchone()
        if not row:
            raise AssertionError("draft execution fixture missing")
        result = json.loads(row["result_json"])
        mutate(result)
        conn.execute(
            "update execution_results set result_json = ? where confirmation_id = ?",
            (json.dumps(result, ensure_ascii=False), confirmation_id),
        )


def _case_exact_callback_chain(root: Path) -> None:
    settings, repo, _context, _boundary, _confirmation_id = _seed_exact_case(
        root,
        "exact-callback-draft",
    )
    if _proof_count(repo) != 1:
        raise AssertionError("exact callback/connection/secret/receipt chain must count exactly once")
    execution = _execution_item(settings, repo)
    if execution.get("status") != "unpublished_ebay_draft_save_proven" or execution.get("severity") != "info":
        raise AssertionError(f"exact draft proof should close readiness warning: {execution}")


def _case_fake_publish_random_secret_rejected(root: Path) -> None:
    _settings, repo, context, boundary, _confirmation_id = _seed_exact_case(
        root,
        "fake-publish-random-secret",
    )
    _require_exact_baseline(repo, "fake publish/random secret")
    random_secret = repo.create_secret_reference(
        company_id=context["company_id"],
        store_id=context["store_id"],
        user_id=context["user_id"],
        provider="ebay",
        purpose="ebay_refresh_token",
        status="managed_vault_stored",
        metadata={"credential_owner": "merchant_fixture", "secret_exposed": False},
    )
    exact_connection = boundary.get("connection") if isinstance(boundary.get("connection"), dict) else {}
    with repo._connect() as conn:
        conn.execute(
            """
            update platform_connections
            set status = 'publish_authorized', secret_ref = ?, metadata_json = ?
            where connection_id = ?
            """,
            (
                random_secret["secret_ref"],
                json.dumps({"credential_source": "merchant_fixture", "secret_exposed": False}),
                exact_connection.get("connection_id"),
            ),
        )
    if _proof_count(repo) != 0:
        raise AssertionError("fake publish_authorized plus unrelated active secret must never form draft proof")


def _case_second_active_connection_rejected(root: Path) -> None:
    _settings, repo, context, boundary, _confirmation_id = _seed_exact_case(
        root,
        "second-active-connection",
    )
    _require_exact_baseline(repo, "second active connection")
    exact_secret = boundary.get("secret_reference") if isinstance(boundary.get("secret_reference"), dict) else {}
    repo.create_platform_connection(
        company_id=context["company_id"],
        store_id=context["store_id"],
        user_id=context["user_id"],
        payload={
            "platform": "ebay",
            "connection_type": "oauth",
            "status": "read_only_authorized",
            "scopes": ["https://api.ebay.com/oauth/api_scope"],
            "secret_ref": exact_secret.get("secret_ref"),
            "metadata": {"secret_exposed": False},
        },
    )
    if _proof_count(repo) != 0:
        raise AssertionError("two active eBay OAuth connections must fail the exact-one draft boundary")


def _case_malformed_json_fails_closed(root: Path) -> None:
    _settings, repo, _context, _boundary, confirmation_id = _seed_exact_case(
        root,
        "malformed-execution-json",
    )
    _require_exact_baseline(repo, "malformed execution JSON")
    with repo._connect() as conn:
        conn.execute(
            "update execution_results set result_json = ? where confirmation_id = ?",
            ("{malformed", confirmation_id),
        )
    try:
        count = _proof_count(repo)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise AssertionError(f"malformed stored JSON must not escape readiness: {type(exc).__name__}") from exc
    if count != 0:
        raise AssertionError("malformed stored execution JSON must fail closed with zero proof")


def _case_rotated_secret_rejected(root: Path) -> None:
    _settings, repo, context, boundary, _confirmation_id = _seed_exact_case(
        root,
        "rotated-secret",
    )
    _require_exact_baseline(repo, "rotated secret")
    exact_secret = boundary.get("secret_reference") if isinstance(boundary.get("secret_reference"), dict) else {}
    with repo._connect() as conn:
        conn.execute(
            "update secret_refs set status = 'superseded_scope_upgrade' where secret_ref = ?",
            (exact_secret.get("secret_ref"),),
        )
    repo.create_secret_reference(
        company_id=context["company_id"],
        store_id=context["store_id"],
        user_id=context["user_id"],
        provider="ebay",
        purpose="ebay_refresh_token",
        status="managed_vault_stored",
        metadata={"credential_owner": "unrelated_rotation", "secret_exposed": False},
    )
    if _proof_count(repo) != 0:
        raise AssertionError("rotated exact secret plus unrelated active secret must not satisfy draft proof")


def _case_receipt_hash_mismatch_rejected(root: Path) -> None:
    _settings, repo, _context, _boundary, confirmation_id = _seed_exact_case(
        root,
        "receipt-hash-mismatch",
    )
    _require_exact_baseline(repo, "receipt credential hash")
    _mutate_execution_result(
        repo,
        confirmation_id,
        lambda result: result["platform_result"].update(
            {"credential_ref_sha256": hashlib.sha256(b"wrong-secret-ref").hexdigest()}
        ),
    )
    if _proof_count(repo) != 0:
        raise AssertionError("receipt credential hash mismatch must fail closed")


def _case_seller_hash_mismatch_rejected(root: Path) -> None:
    _settings, repo, _context, _boundary, confirmation_id = _seed_exact_case(
        root,
        "seller-hash-mismatch",
    )
    _require_exact_baseline(repo, "seller identity hash")
    _mutate_execution_result(
        repo,
        confirmation_id,
        lambda result: result["platform_result"].update(
            {"seller_identity_sha256": hashlib.sha256(b"wrong-seller").hexdigest()}
        ),
    )
    if _proof_count(repo) != 0:
        raise AssertionError("receipt seller identity hash mismatch must fail closed")


def _case_idempotency_digest_mismatch_rejected(root: Path) -> None:
    _settings, repo, _context, _boundary, confirmation_id = _seed_exact_case(
        root,
        "idempotency-digest-mismatch",
    )
    _require_exact_baseline(repo, "idempotency digest")
    _mutate_execution_result(
        repo,
        confirmation_id,
        lambda result: result["audit"]["idempotency"].update(
            {"duplicate_prevention_key": hashlib.sha256(b"wrong-idempotency-boundary").hexdigest()}
        ),
    )
    if _proof_count(repo) != 0:
        raise AssertionError("wrong tenant/action-bound duplicate digest must fail closed")


def _case_execution_payload_digest_mismatch_rejected(root: Path) -> None:
    _settings, repo, _context, _boundary, confirmation_id = _seed_exact_case(
        root,
        "execution-payload-digest-mismatch",
    )
    _require_exact_baseline(repo, "execution payload digest")
    _mutate_execution_result(
        repo,
        confirmation_id,
        lambda result: result["audit"]["idempotency"].update(
            {"payload_hash": hashlib.sha256(b"wrong-execution-payload").hexdigest()}
        ),
    )
    if _proof_count(repo) != 0:
        raise AssertionError("wrong execution request payload digest must fail closed")


def _case_execution_intent_mismatch_rejected(root: Path) -> None:
    _settings, repo, _context, _boundary, confirmation_id = _seed_exact_case(
        root,
        "execution-intent-mismatch",
    )
    _require_exact_baseline(repo, "execution intent")
    _mutate_execution_result(
        repo,
        confirmation_id,
        lambda result: result["audit"]["execution_intent"].update(
            {"intent_id": hashlib.sha256(b"wrong-execution-intent").hexdigest()}
        ),
    )
    if _proof_count(repo) != 0:
        raise AssertionError("execution intent detached from the duplicate digest must fail closed")


def _case_legacy_minimal_execution_intent_verified(root: Path) -> None:
    _settings, repo, _context, _boundary, confirmation_id = _seed_exact_case(
        root,
        "legacy-minimal-execution-intent",
    )
    _require_exact_baseline(repo, "legacy minimal execution intent")

    def remove_extended_fields(result: dict[str, Any]) -> None:
        intent = result["audit"]["execution_intent"]
        for key in (
            "creates_public_listing",
            "writes_to_ebay",
            "requires_publish_offer_call",
            "stores_internal_draft_only",
            "confirmation_center_required_before_public_publish",
        ):
            intent.pop(key, None)

    _mutate_execution_result(repo, confirmation_id, remove_extended_fields)
    if _proof_count(repo) != 1:
        raise AssertionError("the deployed minimal intent contract must remain valid without repeating an eBay write")


def _case_extended_execution_intent_publish_flag_rejected(root: Path) -> None:
    _settings, repo, _context, _boundary, confirmation_id = _seed_exact_case(
        root,
        "extended-intent-publish-flag",
    )
    _require_exact_baseline(repo, "extended execution intent publish flag")
    _mutate_execution_result(
        repo,
        confirmation_id,
        lambda result: result["audit"]["execution_intent"].update({"creates_public_listing": True}),
    )
    if _proof_count(repo) != 0:
        raise AssertionError("an extended execution intent that permits public listing creation must fail closed")


def _case_read_only_upgrade_never_falls_back(root: Path) -> None:
    _settings, repo, _context, boundary, _confirmation_id = _seed_exact_case(
        root,
        "read-only-upgrade",
        upgrade_from_read_only=True,
    )
    if _proof_count(repo) != 1:
        raise AssertionError("same-seller read-only to exact draft upgrade must preserve one valid proof")
    exact_connection = boundary.get("connection") if isinstance(boundary.get("connection"), dict) else {}
    with repo._connect() as conn:
        conn.execute(
            "update platform_connections set status = 'read_only_authorized' where connection_id = ?",
            (exact_connection.get("connection_id"),),
        )
    if _proof_count(repo) != 0:
        raise AssertionError("after draft upgrade, readiness must not fall back to read_only aggregation")


def main() -> int:
    old = dict(os.environ)
    try:
        os.environ.update(
            {
                "JIEJING_SAAS_ENV": "staging",
                "JIEJING_EBAY_CLIENT_ID": "READINESS-CLIENT-ID",
                "JIEJING_EBAY_CLIENT_SECRET": "READINESS-CLIENT-SECRET-DO-NOT-LEAK",
                "JIEJING_EBAY_RU_NAME": "Jiejing_Auth_RuName",
                "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE": "true",
                "JIEJING_VAULT_ENABLED": "true",
                "JIEJING_VAULT_PROVIDER": "vault",
                "JIEJING_VAULT_LIVE_RESOLVE_ENABLED": "true",
                "JIEJING_VAULT_ADDR": "https://vault.example.test",
                "JIEJING_VAULT_TOKEN": "READINESS-VAULT-TOKEN-DO-NOT-LEAK",
                "JIEJING_VAULT_MOUNT": "secret",
                "JIEJING_VAULT_KEYSPACE": "readiness",
                "JIEJING_VAULT_KV_VERSION": "v2",
                "JIEJING_EBAY_DRAFT_SAVE_LIVE": "true",
                "JIEJING_EBAY_READ_ONLY_LIVE": "true",
                "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "true",
                "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
                "JIEJING_EBAY_WRITE_LIVE": "false",
            }
        )
        with tempfile.TemporaryDirectory(prefix="jiejing-draft-readiness-", ignore_cleanup_errors=True) as temp:
            root = Path(temp)
            before_settings, before_repo, _before_context = _new_case(root, "no-receipt")
            before = _execution_item(before_settings, before_repo)
            if before["status"] != "ebay_draft_save_live_proof_pending":
                return fail(f"enabled draft switch without receipt must remain pending: {before}")

            cases = (
                ("exact callback chain", _case_exact_callback_chain),
                ("fake publish plus random secret", _case_fake_publish_random_secret_rejected),
                ("second active connection", _case_second_active_connection_rejected),
                ("malformed execution JSON", _case_malformed_json_fails_closed),
                ("rotated secret", _case_rotated_secret_rejected),
                ("receipt credential hash mismatch", _case_receipt_hash_mismatch_rejected),
                ("receipt seller hash mismatch", _case_seller_hash_mismatch_rejected),
                ("idempotency digest mismatch", _case_idempotency_digest_mismatch_rejected),
                ("execution payload digest mismatch", _case_execution_payload_digest_mismatch_rejected),
                ("execution intent mismatch", _case_execution_intent_mismatch_rejected),
                ("legacy minimal execution intent", _case_legacy_minimal_execution_intent_verified),
                ("extended execution intent publish flag", _case_extended_execution_intent_publish_flag_rejected),
                ("read-only upgrade no fallback", _case_read_only_upgrade_never_falls_back),
            )
            failures: list[str] = []
            for label, case in cases:
                try:
                    case(root)
                except Exception as exc:  # noqa: BLE001 - every corruption case must report instead of masking later cases
                    failures.append(f"{label}: {type(exc).__name__}: {exc}")
            if failures:
                return fail("; ".join(failures))
    finally:
        os.environ.clear()
        os.environ.update(old)
    print("PASS jiejing_ebay_draft_save_readiness")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

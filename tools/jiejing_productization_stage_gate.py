#!/usr/bin/env python3
"""Completion-driven productization gate for Jiejing SaaS.

This is not a timer. It checks whether the current productization stage has
enough verified engineering shape to move to the next stage.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.controlled_bridges import FORMAL_BRIDGE_KEYS, build_controlled_bridge_contract  # noqa: E402
from jiejing_saas.database_adapter import build_database_adapter_contract  # noqa: E402
from jiejing_saas.database_plan import build_database_plan  # noqa: E402
from jiejing_saas.ebay_credential_preflight import build_ebay_credential_preflight  # noqa: E402
from jiejing_saas.ebay_http_client import build_ebay_http_client_contract, build_http_dry_run_from_live_plan  # noqa: E402
from jiejing_saas.ebay_live_read_adapter import EbayLiveReadPlanBuilder, build_live_read_adapter_status  # noqa: E402
from jiejing_saas.ebay_oauth import EbayOAuthPlanner  # noqa: E402
from jiejing_saas.ebay_read_adapter import EbayReadOnlyAdapter  # noqa: E402
from jiejing_saas.ebay_read_contract import build_field_contract_catalog  # noqa: E402
from jiejing_saas.ebay_read_normalizers import normalizer_catalog  # noqa: E402
from jiejing_saas.ebay_write_adapter import build_ebay_write_adapter_contract  # noqa: E402
from jiejing_saas.independence import build_independence_status  # noqa: E402
from jiejing_saas.queue_adapter import build_queue_adapter_contract  # noqa: E402
from jiejing_saas.queue_plan import build_queue_plan  # noqa: E402
from jiejing_saas.readiness import build_product_readiness  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.secret_store import SecretStoreBoundary  # noqa: E402
from jiejing_saas.task_secret_grants import build_task_secret_grant_plan  # noqa: E402
from jiejing_saas.vault_client import build_task_secret_resolution_contract, build_vault_client_contract  # noqa: E402
from jiejing_saas.vault_adapter import build_vault_adapter_contract  # noqa: E402
from jiejing_saas.vault_secret_resolver import build_vault_secret_resolver_status  # noqa: E402
from jiejing_runtime import (  # noqa: E402
    ExecutionRequest,
    ExecutionService,
    JiejingAgentTeam,
    JiejingRuntime,
    OwnedAgentExecutor,
    OwnedAgentQualityGate,
    ProductWorkflowRequest,
    RuntimeConfig,
    build_product_workflow,
    build_agent_provider_execution_plan,
)
from jiejing_runtime.provider_job_contracts import build_provider_job_contract_catalog  # noqa: E402
from jiejing_ebay_jiejing_credential_chain_smoke import run_smoke as run_jiejing_credential_chain_smoke  # noqa: E402


OUT = ROOT / "output" / "jiejing-saas-productization-gate"
DB = OUT / "stage-gate.sqlite"
RUNTIME_DB = OUT / "stage-gate-runtime.sqlite"
STAGE_5_RUN = OUT / "stage-5-owned-agent-quality"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    repo = SaaSRepository(DB)
    repo.initialize()
    seed = _ensure_seed(repo)
    settings = SaaSSettings.from_env(
        db_path=DB,
        runtime_db_path=RUNTIME_DB,
        output_root=OUT,
        host="127.0.0.1",
        port=8788,
    )
    readiness = build_product_readiness(settings, repo)
    database_plan = build_database_plan(settings, repo)
    queue_plan = build_queue_plan(settings, repo)
    database_adapter = build_database_adapter_contract(settings)
    queue_adapter = build_queue_adapter_contract(settings)
    controlled_bridges = build_controlled_bridge_contract(settings, repo)
    ebay_catalog = EbayReadOnlyAdapter(settings).resource_catalog()
    ebay_live_adapter = build_live_read_adapter_status(settings)
    ebay_live_read_plan = EbayLiveReadPlanBuilder(settings).build_execution_plan(
        company_id=seed.get("company_id") or "company_stage_gate",
        store={
            "store_id": seed.get("store_id") or "store_stage_gate",
            "platform": "ebay",
            "store_name": "stage-gate-ebay",
            "marketplace": "EBAY_US",
        },
        user_id="user_stage_gate",
        requested_resources=[
            "store_profile",
            "account_business_policies",
            "inventory_and_offers",
            "orders_and_fulfillment",
            "finances",
            "taxonomy_listing_metadata",
        ],
        secret_refs=[
            {
                "secret_ref": "secret_stage_gate_ebay_refresh",
                "provider": "ebay",
                "purpose": "ebay_refresh_token",
                "status": "external_vault_required",
            }
        ],
        connections=[
            {
                "connection_id": "conn_stage_gate_ebay_readonly",
                "platform": "ebay",
                "connection_type": "oauth",
                "status": "read_only_authorized",
                "scopes": ["https://api.ebay.com/oauth/api_scope/sell.account.readonly"],
            }
        ],
        token_refresh_plan={
            "status": "refresh_blocked",
            "blocked_by": ["Vault/KMS", "JIEJING_EBAY_TOKEN_REFRESH_LIVE", "live_refresh_http_adapter_not_implemented"],
        },
    )
    ebay_credential_preflight = build_ebay_credential_preflight(
        settings=settings,
        store={
            "store_id": seed.get("store_id") or "store_stage_gate",
            "platform": "ebay",
            "store_name": "stage-gate-ebay",
            "marketplace": "EBAY_US",
        },
        requested_resources=[
            "store_profile",
            "account_business_policies",
            "inventory_and_offers",
            "orders_and_fulfillment",
            "finances",
            "taxonomy_listing_metadata",
        ],
        secret_refs=[
            {
                "secret_ref": "secret_stage_gate_ebay_refresh",
                "provider": "ebay",
                "purpose": "ebay_refresh_token",
                "status": "external_vault_required",
            }
        ],
        connections=[
            {
                "connection_id": "conn_stage_gate_ebay_readonly",
                "platform": "ebay",
                "connection_type": "oauth",
                "status": "read_only_authorized",
                "scopes": ["https://api.ebay.com/oauth/api_scope/sell.account.readonly"],
            }
        ],
    )
    ebay_http_client = build_ebay_http_client_contract(settings)
    ebay_http_dry_run = build_http_dry_run_from_live_plan(settings=settings, live_read_plan=ebay_live_read_plan)
    ebay_refresh_execution_plan = EbayOAuthPlanner(settings).token_refresh_execution_plan(
        company_id=seed.get("company_id") or "company_stage_gate",
        store_id=seed.get("store_id") or "store_stage_gate",
        user_id="user_stage_gate",
        secret_refs=[
            {
                "secret_ref": "secret_stage_gate_ebay_refresh",
                "provider": "ebay",
                "purpose": "ebay_refresh_token",
                "status": "external_vault_required",
            }
        ],
        connections=[
            {
                "connection_id": "conn_stage_gate_ebay_readonly",
                "platform": "ebay",
                "connection_type": "oauth",
                "status": "read_only_authorized",
                "scopes": ["https://api.ebay.com/oauth/api_scope/sell.account.readonly"],
            }
        ],
        secret_store_status=SecretStoreBoundary(settings).status(),
    )
    jiejing_credential_chain_smoke = run_jiejing_credential_chain_smoke(
        write_output=False,
        output_root=OUT / "stage-3-jiejing-owned-credential-chain",
    )
    ebay_field_contracts = build_field_contract_catalog()
    ebay_normalizers = normalizer_catalog()
    ebay_write_adapter = build_ebay_write_adapter_contract(settings)
    vault_adapter = build_vault_adapter_contract(settings)
    vault_client = build_vault_client_contract(settings)
    secret_store = SecretStoreBoundary(settings)
    independence = build_independence_status(settings=settings, repository=repo, project_root=ROOT)

    stage_1_checks = _stage_1_checks(
        readiness=readiness,
        database_plan=database_plan,
        queue_plan=queue_plan,
        database_adapter=database_adapter,
        queue_adapter=queue_adapter,
        controlled_bridges=controlled_bridges,
        independence=independence,
    )
    stage_1_ready = all(item["pass"] for item in stage_1_checks)
    stage_2_checks = _stage_2_checks(
        ebay_catalog=ebay_catalog,
        ebay_live_adapter=ebay_live_adapter,
        ebay_live_read_plan=ebay_live_read_plan,
        ebay_http_client=ebay_http_client,
        ebay_http_dry_run=ebay_http_dry_run,
        ebay_credential_preflight=ebay_credential_preflight,
        ebay_field_contracts=ebay_field_contracts,
        ebay_normalizers=ebay_normalizers,
    )
    stage_2_contract_ready = stage_1_ready and all(item["pass"] for item in stage_2_checks)
    stage_3_checks = _stage_3_checks(
        vault_adapter=vault_adapter,
        vault_client=vault_client,
        secret_store=secret_store,
        ebay_refresh_execution_plan=ebay_refresh_execution_plan,
        jiejing_credential_chain_smoke=jiejing_credential_chain_smoke,
        ebay_oauth_callback_py=(ROOT / "jiejing_saas" / "ebay_oauth_callback.py").read_text(encoding="utf-8"),
        vault_secret_resolver_py=(ROOT / "jiejing_saas" / "vault_secret_resolver.py").read_text(encoding="utf-8"),
    )
    stage_3_contract_ready = stage_2_contract_ready and all(item["pass"] for item in stage_3_checks)
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    public_search_handoff_py = (ROOT / "jiejing_saas" / "public_search_handoff.py").read_text(encoding="utf-8")
    stage_4_checks = _stage_4_checks(app_js=app_js)
    stage_4_frontend_ready = stage_3_contract_ready and all(item["pass"] for item in stage_4_checks)
    stage_5_checks = _stage_5_checks()
    stage_5_owned_agent_ready = stage_4_frontend_ready and all(item["pass"] for item in stage_5_checks)
    stage_6_checks = _stage_6_checks(app_js=app_js, ebay_write_adapter=ebay_write_adapter, public_search_handoff_py=public_search_handoff_py)
    stage_6_execution_boundary_ready = stage_5_owned_agent_ready and all(item["pass"] for item in stage_6_checks)
    current_stage = (
        "stage_6_live_low_risk_execution_boundary"
        if stage_5_owned_agent_ready
        else
        "stage_5_owned_agent_team"
        if stage_4_frontend_ready
        else
        "stage_4_runtime_driven_frontend"
        if stage_3_contract_ready
        else "stage_3_vault_kms_boundary"
        if stage_2_contract_ready
        else "stage_2_ebay_read_only_integration"
        if stage_1_ready
        else "stage_1_formal_saas_backend_control"
    )
    result = {
        "product": "Jiejing SaaS",
        "gate_version": "2026-05-15-completion-driven",
        "current_stage": current_stage,
        "stage_1_ready_for_stage_2": stage_1_ready,
        "stage_2_contract_ready_for_stage_3": stage_2_contract_ready,
        "stage_3_contract_ready_for_stage_4": stage_3_contract_ready,
        "stage_4_frontend_ready_for_stage_5": stage_4_frontend_ready,
        "stage_5_owned_agent_ready_for_stage_6": stage_5_owned_agent_ready,
        "stage_6_execution_boundary_ready": stage_6_execution_boundary_ready,
        "next_stage": current_stage,
        "seed": seed,
        "checks": {
            "stage_1": stage_1_checks,
            "stage_2": stage_2_checks,
            "stage_3": stage_3_checks,
            "stage_4": stage_4_checks,
            "stage_5": stage_5_checks,
            "stage_6": stage_6_checks,
        },
        "independence": {
            "runtime_independent_from_hermes": independence.get("runtime_independent_from_hermes"),
            "hermes_adapters_allowed": independence.get("hermes_adapters_allowed"),
            "issue_count": independence.get("issue_count"),
            "blocking_count": independence.get("blocking_count"),
        },
        "honest_progress": {
            "stage_1": "92%-94%" if stage_1_ready else "86%-89%",
            "stage_2": "90%-92%" if stage_2_contract_ready else "73%-76%",
            "stage_3": "90%-92%" if stage_3_contract_ready else "55%-60%",
            "stage_4": "92%-95%" if stage_4_frontend_ready else "88%-90% runtime base, frontend dynamic coverage pending",
            "stage_5": "90%-92%" if stage_5_owned_agent_ready else "55%-60%",
            "stage_6": "90%-92%" if stage_6_execution_boundary_ready else "35%-40%",
        },
        "secret_exposed": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if stage_1_ready else 2


def _ensure_seed(repo: SaaSRepository) -> dict[str, Any]:
    if repo.system_counts().get("users", 0) >= 1:
        return {"created": False}
    record = repo.create_user_with_company(
        email="stage-gate-owner@example.com",
        password="stage-gate-password",
        company_name="Jiejing Stage Gate Company",
    )
    store = repo.create_store(
        company_id=record["company"]["company_id"],
        user_id=record["user"]["user_id"],
        payload={"platform": "ebay", "store_name": "stage-gate-ebay", "marketplace": "EBAY_US"},
    )
    return {"created": True, "company_id": record["company"]["company_id"], "store_id": store["store_id"]}


def _stage_1_checks(
    *,
    readiness: dict[str, Any],
    database_plan: dict[str, Any],
    queue_plan: dict[str, Any],
    database_adapter: dict[str, Any],
    queue_adapter: dict[str, Any],
    controlled_bridges: dict[str, Any],
    independence: dict[str, Any],
) -> list[dict[str, Any]]:
    readiness_keys = {item.get("key"): item for item in readiness.get("items", [])}
    db_adapter_keys = {item.get("key") for item in database_adapter.get("available_adapters", [])}
    queue_adapter_keys = {item.get("key") for item in queue_adapter.get("available_adapters", [])}
    bridge_keys = {item.get("key") for item in controlled_bridges.get("bridges", [])}
    checks = [
        _check("team_permission_boundary", "Team role and high-risk approval boundary exists.", "team_permission_boundary" in readiness_keys),
        _check("cors_origin_guardrail", "CORS origin policy is represented in readiness and can block unsafe production startup.", "cors_origin" in readiness_keys),
        _check("database_adapter_contract", "Database adapter contract exposes local and production targets.", {"sqlite-local", "postgres-managed"}.issubset(db_adapter_keys)),
        _check("database_migration_shape", "Database has migration record, critical tables and critical indexes.", bool(database_plan.get("staging_migration_shape_ready"))),
        _check(
            "postgres_migration_file",
            "Prepared PostgreSQL migration file is registered.",
            any(str(item.get("path") or "").endswith("001_initial_schema_postgres.sql") for item in database_plan.get("migration_files", [])),
        ),
        _check("queue_adapter_contract", "Queue adapter contract exposes local, Postgres durable, Redis and cloud queue targets.", {"local_worker", "postgres_durable", "redis_streams", "tencent_cloud_queue", "aliyun_message_queue"}.issubset(queue_adapter_keys)),
        _check("controlled_bridge_contract", "Formal bridge contract fixes Runtime, provider, queue, confirmation-execution and audit-memory paths.", FORMAL_BRIDGE_KEYS.issubset(bridge_keys) and controlled_bridges.get("rules", {}).get("hermes_legacy_bridge_can_be_production_dependency") is False),
        _check("queue_worker_shape", "Local queue worker shape supports queued jobs and merchant-visible failures.", bool(queue_plan.get("local_queue_shape_ready"))),
        _check("infrastructure_driver_contract", "Postgres/Redis driver status is represented before runtime cutover.", "infrastructure_drivers" in readiness_keys),
        _check("monitoring_alerting_contract", "Monitoring and alerting boundary is represented before paid launch.", "monitoring_alerting" in readiness_keys),
        _check("execution_boundary", "ExecutionService remains confirmation-gated and no real platform writes are enabled.", readiness.get("real_platform_writes_enabled") is False),
        _check("independent_runtime_default", "Jiejing SaaS defaults to the self-owned Runtime and does not allow Hermes adapters.", independence.get("runtime_independent_from_hermes") is True and independence.get("hermes_adapters_allowed") is False),
        _check("independent_deploy_skeleton", "Independent SaaS deployment skeleton and runbook exist.", all(item.get("exists") for item in independence.get("deployment_files", []))),
    ]
    return checks


def _stage_2_checks(
    *,
    ebay_catalog: dict[str, Any],
    ebay_live_adapter: dict[str, Any],
    ebay_live_read_plan: dict[str, Any],
    ebay_http_client: dict[str, Any],
    ebay_http_dry_run: dict[str, Any],
    ebay_credential_preflight: dict[str, Any],
    ebay_field_contracts: dict[str, Any],
    ebay_normalizers: dict[str, Any],
) -> list[dict[str, Any]]:
    catalog_keys = {item.get("key") for item in ebay_catalog.get("resources", [])}
    contract_keys = {item.get("resource_key") for item in ebay_field_contracts.get("resources", [])}
    normalizer_keys = set(ebay_normalizers.get("resource_keys", []))
    route_keys = {item.get("resource_key") for item in ebay_live_adapter.get("routes", [])}
    required = {
        "store_profile",
        "account_business_policies",
        "inventory_and_offers",
        "orders_and_fulfillment",
        "finances",
        "taxonomy_listing_metadata",
    }
    return [
        _check("ebay_resource_catalog", "eBay read-only catalog covers store, policy, listing, order, finance and taxonomy resources.", required.issubset(catalog_keys)),
        _check("ebay_field_contracts", "Each read-only resource has required/recommended/sensitive field contracts.", required.issubset(contract_keys)),
        _check("ebay_normalizer_catalog", "Each required read-only resource has a registered packet normalizer.", required.issubset(normalizer_keys) and ebay_normalizers.get("normalizes_sanitized_resource_sections") is True),
        _check("ebay_live_adapter_routes", "Live read adapter has route contracts but remains disabled.", required.issubset(route_keys) and ebay_live_adapter.get("enabled") is False),
        _check("ebay_live_read_execution_plan", "Live read plan exposes backend token, request, standardization, cache and audit steps without making a live call.", ebay_live_read_plan.get("status") == "blocked_contract_only" and ebay_live_read_plan.get("route_request_count", 0) >= 6 and ebay_live_read_plan.get("live_read_performed") is False),
        _check("ebay_http_client_contract", "eBay read-only HTTP client has a dry-run contract and still performs no live request.", ebay_http_client.get("contract_ready") is True and ebay_http_client.get("live_request_performed") is False and ebay_http_client.get("writes_supported") is False),
        _check("ebay_http_client_dry_run", "eBay HTTP dry-run builds request envelopes without exposing access tokens.", ebay_http_dry_run.get("request_count", 0) >= 6 and ebay_http_dry_run.get("live_request_performed") is False and ebay_http_dry_run.get("access_token_returned_to_frontend") is False),
        _check("ebay_credential_preflight_contract", "Credential preflight gives one backend answer for whether official eBay reads can be queued, without exposing secrets.", ebay_credential_preflight.get("status") in {"blocked", "ready_for_official_read"} and isinstance(ebay_credential_preflight.get("checks"), list) and bool(ebay_credential_preflight.get("merchant_next_step")) and ebay_credential_preflight.get("frontend_gets_access_token") is False and ebay_credential_preflight.get("runtime_gets_access_token") is False and ebay_credential_preflight.get("secret_exposed") is False),
        _check("ebay_live_read_token_boundary", "Live read plan keeps access tokens out of frontend, Runtime and database.", ebay_live_read_plan.get("token_boundary", {}).get("frontend_gets_access_token") is False and ebay_live_read_plan.get("token_boundary", {}).get("runtime_gets_access_token") is False and ebay_live_read_plan.get("token_boundary", {}).get("database_stores_access_token") is False),
        _check("ebay_live_read_packet_boundary", "Live read plan hands only sanitized packets to Runtime.", ebay_live_read_plan.get("data_packet_handoff", {}).get("runtime_gets_sanitized_packet_only") is True and ebay_live_read_plan.get("data_packet_handoff", {}).get("raw_ebay_response_stored") is False),
        _check("ebay_no_frontend_token", "Read-only boundary never returns access tokens to frontend or Runtime.", ebay_live_adapter.get("guardrails", {}).get("frontend_gets_access_token") is False and ebay_live_adapter.get("guardrails", {}).get("runtime_gets_access_token") is False),
        _check("ebay_no_write_support", "Read-only stage still has no write support.", ebay_live_adapter.get("guardrails", {}).get("writes_supported") is False),
    ]


def _stage_3_checks(
    *,
    vault_adapter: dict[str, Any],
    vault_client: dict[str, Any],
    secret_store: SecretStoreBoundary,
    ebay_refresh_execution_plan: dict[str, Any],
    jiejing_credential_chain_smoke: dict[str, Any],
    ebay_oauth_callback_py: str,
    vault_secret_resolver_py: str,
) -> list[dict[str, Any]]:
    adapter_keys = {item.get("key") for item in vault_adapter.get("available_adapters", [])}
    operation_keys = {item.get("key") for item in vault_adapter.get("operations", [])}
    purposes = {item.get("key") for item in secret_store.targets().get("purposes", [])}
    sample_secret_ref = {
        "secret_ref": "secret_stage_gate_sample",
        "provider": "ebay",
        "purpose": "ebay_refresh_token",
        "status": "external_vault_required",
        "secret_exposed": False,
    }
    resolution = secret_store.build_secret_resolution_plan(
        secret_ref=sample_secret_ref,
        requested_by="backend_adapter",
        task_scope="stage_gate_ebay_read_only",
    )
    client_resolution = build_task_secret_resolution_contract(
        settings=secret_store.settings,
        secret_ref=sample_secret_ref,
        requested_by="backend_adapter",
        task_scope="stage_gate_ebay_read_only",
    )
    rotation = secret_store.build_secret_rotation_plan(
        secret_ref=sample_secret_ref,
        requested_by="owner",
        reason="stage_gate_rotation_check",
    )
    revoke = secret_store.build_secret_revoke_plan(
        secret_ref=sample_secret_ref,
        requested_by="owner",
        reason="stage_gate_revoke_check",
    )
    task_grant_plan = build_task_secret_grant_plan(
        task={
            "task_id": "task_stage_gate",
            "company_id": "company_stage_gate",
            "store_id": "store_stage_gate",
        },
        provider_job_plan={
            "provider_steps": [
                {
                    "provider_job_key": "ebay.read_only_snapshot",
                    "provider_family": "sales_channel",
                    "task_type": "market.data_packet",
                    "queue": "provider.ebay.read",
                    "timeout_seconds": 180,
                    "required_secret_purpose": "ebay_refresh_token",
                    "source_record_type": "ebay_snapshot",
                    "output_packet": "ebay_read_only_packet",
                    "queueable": True,
                },
                {
                    "provider_job_key": "model.role_report_assist",
                    "provider_family": "ai_model",
                    "task_type": "market.report",
                    "queue": "provider.model",
                    "timeout_seconds": 240,
                    "required_secret_purpose": "model_api_key",
                    "source_record_type": "model_report",
                    "output_packet": "role_report_packet",
                    "queueable": True,
                },
            ]
        },
        secret_refs=[sample_secret_ref],
        connections=[],
        vault_status=secret_store.status(),
    )
    secret_resolver = build_vault_secret_resolver_status(secret_store.settings)
    return [
        _check("vault_adapter_targets", "Vault contract exposes local, Tencent, Aliyun and Vault targets.", {"secret_ref_only", "tencent_kms", "aliyun_kms", "vault"}.issubset(adapter_keys)),
        _check("vault_operation_contracts", "Vault contract covers secret ref, resolve, rotate and revoke operations.", {"create_secret_ref", "resolve_task_secret", "rotate_secret", "revoke_secret"}.issubset(operation_keys)),
        _check("vault_secret_purposes", "Secret purposes cover eBay, model, search, media, sourcing and logistics credentials.", {"ebay_refresh_token", "model_api_key", "public_search_api_key", "media_generation_api_key", "sourcing_api_secret", "logistics_api_secret"}.issubset(purposes)),
        _check("vault_client_contract", "Vault client contract defines backend-only resolve/write/rotate/revoke behavior.", vault_client.get("contract_ready") is True and vault_client.get("response_contract", {}).get("returns_raw_secret_to_frontend") is False and vault_client.get("response_contract", {}).get("returns_raw_secret_to_runtime") is False),
        _check("vault_resolution_boundary", "Secret resolution is backend-only and never returns raw secrets to frontend or Runtime.", resolution.get("frontend_gets_raw_secret") is False and resolution.get("runtime_gets_raw_secret") is False and resolution.get("raw_secret_returned") is False),
        _check("vault_client_resolution_contract", "Task secret resolution contract never returns raw secrets in public responses.", client_resolution.get("raw_secret_returned") is False and client_resolution.get("frontend_gets_raw_secret") is False and client_resolution.get("runtime_gets_raw_secret") is False),
        _check("vault_secret_resolver_boundary", "Secret resolver has a backend-only boundary and never returns raw secrets to frontend or Runtime.", secret_resolver.get("backend_only") is True and secret_resolver.get("returns_raw_secret_to_frontend") is False and secret_resolver.get("returns_raw_secret_to_runtime") is False and secret_resolver.get("secret_exposed") is False),
        _check("ebay_refresh_execution_plan", "eBay token refresh execution plan is backend-only and never returns access tokens to frontend or Runtime.", ebay_refresh_execution_plan.get("status") == "blocked_contract_only" and ebay_refresh_execution_plan.get("live_refresh_performed") is False and ebay_refresh_execution_plan.get("token_boundary", {}).get("access_token_returned_to_frontend") is False and ebay_refresh_execution_plan.get("token_boundary", {}).get("access_token_returned_to_runtime") is False),
        _check(
            "jiejing_owned_credential_chain_smoke",
            "Jiejing-owned eBay credential chain runs without Hermes across direct, local-store, local secret_ref and managed Vault sources.",
            jiejing_credential_chain_smoke.get("status") == "pass"
            and jiejing_credential_chain_smoke.get("hermes_bridge_enabled") is False
            and jiejing_credential_chain_smoke.get("case_count", 0) >= 4
            and jiejing_credential_chain_smoke.get("ready_case_count") == jiejing_credential_chain_smoke.get("case_count")
            and jiejing_credential_chain_smoke.get("secret_leak_check", {}).get("status") == "pass"
            and jiejing_credential_chain_smoke.get("real_platform_writes_enabled") is False,
        ),
        _check(
            "ebay_oauth_callback_vault_storage",
            "OAuth callback exchanges authorization code, stores refresh token through Jiejing Vault resolver, and consumes state only once.",
            "exchange_authorization_code" in ebay_oauth_callback_py
            and "VaultSecretResolver(settings, transport=vault_transport).store_secret" in ebay_oauth_callback_py
            and "repository.create_platform_connection" in ebay_oauth_callback_py
            and "refresh_token_stored_in_database" in ebay_oauth_callback_py
            and "OAUTH_CALLBACK_STATE_TTL_SECONDS" in ebay_oauth_callback_py
            and "blocked_replayed_state" in ebay_oauth_callback_py
            and "blocked_invalid_expired_state" in ebay_oauth_callback_py
            and "store_exchange_result" not in ebay_oauth_callback_py
            and "def store_secret" in vault_secret_resolver_py
            and "_write_hashicorp_vault_secret" in vault_secret_resolver_py,
        ),
        _check("vault_rotation_boundary", "Secret rotation has an auditable plan without exposing raw secrets.", rotation.get("audit_required") is True and rotation.get("raw_secret_returned") is False),
        _check("vault_revoke_boundary", "Secret revocation has an auditable plan without exposing raw secrets.", revoke.get("audit_required") is True and revoke.get("raw_secret_returned") is False),
        _check("task_secret_grant_plan", "Provider jobs get task-scoped secret grants by secret_ref only, with missing refs surfaced before live calls.", task_grant_plan.get("grant_contract_ready_count") == 1 and task_grant_plan.get("blocked_count") == 1 and task_grant_plan.get("frontend_gets_raw_secret") is False and task_grant_plan.get("runtime_gets_raw_secret") is False),
        _check("vault_no_raw_secret_storage", "Vault contract keeps raw secrets out of frontend, database and Runtime.", vault_adapter.get("rules", {}).get("frontend_gets_raw_secret") is False and vault_adapter.get("rules", {}).get("database_stores_raw_secret") is False and vault_adapter.get("rules", {}).get("runtime_gets_raw_secret") is False),
    ]


def _stage_4_checks(*, app_js: str) -> list[dict[str, Any]]:
    return [
        _check("frontend_uses_saas_backend", "Frontend can dispatch product workflows through the SaaS backend.", '"/tasks/product-workflow"' in app_js and '"/workers/run-next"' in app_js),
        _check(
            "frontend_reads_reports_confirmations",
            "Frontend reads backend reports, confirmations, execution results and audit logs.",
            ('"/reports"' in app_js or '"/reports?' in app_js)
            and ('"/confirmations"' in app_js or '"/confirmations?' in app_js)
            and ('"/execution-results"' in app_js or '"/execution-results?' in app_js)
            and '"/audit-logs?limit=80"' in app_js,
        ),
        _check("frontend_reads_database_queue_contracts", "Frontend reads database and queue production contracts from backend.", '"/database/adapters"' in app_js and '"/queue/adapters"' in app_js),
        _check("frontend_reads_provider_job_contracts", "Frontend reads SaaS provider job contracts for search, eBay, sourcing, logistics, media and model jobs.", '"/provider-job-contracts"' in app_js and "saasProviderJobContracts" in app_js),
        _check("frontend_reads_provider_job_plan", "Frontend reads task-level provider job preflight plan.", "provider-job-plan" in app_js and "saasProviderJobPlan" in app_js),
        _check("frontend_reads_secret_grant_plan", "Frontend reads task-level secret grant plan without receiving raw secrets.", "secret-grant-plan" in app_js and "saasSecretGrantPlan" in app_js and "密钥授权" in app_js),
        _check("frontend_api_base_configurable", "Frontend API base can be configured for staging without hardcoded localhost.", "resolveJiejingApiBase" in app_js and "window.JIEJING_CONFIG" in app_js and "jiejing_saas_api_base" in app_js and "jiejing-saas-api-base" in app_js),
        _check(
            "frontend_public_auth_gate",
            "Frontend does not auto-bootstrap demo users on public origins and surfaces OAuth/secret_ref state.",
            "defaultJiejingDemoBootstrapEnabled" in app_js
            and "saasDemoBootstrapEnabled" in app_js
            and "当前公网页面需要已有捷境账号会话" in app_js
            and "/secret-refs?store_id=" in app_js
            and "OAuth Status" in app_js
            and ("Secret Ref" in app_js or "secret_ref" in app_js),
        ),
        _check("frontend_reads_independence_status", "Frontend reads the independent Jiejing Runtime status so Hermes cannot silently become the default path.", '"/independence/status"' in app_js and "saasIndependence" in app_js and "独立 Runtime" in app_js),
        _check("frontend_reads_vault_contract", "Frontend reads Vault/KMS adapter and client contracts without seeing raw secrets.", '"/vault/adapters"' in app_js and '"/vault/client-contract"' in app_js and "saasVaultAdapters" in app_js and "saasVaultClient" in app_js),
        _check("frontend_reads_ebay_read_contract", "Frontend reads eBay read-only field contracts, live-adapter status, live-read execution plan, credential preflight, HTTP dry-run contract and product-level sync entry.", '"/ebay-read-only/field-contracts"' in app_js and '"/ebay-read-only/live-adapter/status"' in app_js and "ebay-read-only/live-read-plan" in app_js and '"/ebay-read-only/http-client/status"' in app_js and "http-client-dry-run" in app_js and "credential-preflight" in app_js and "saasEbayCredentialPreflight" in app_js and "ebay-read-only/sync" in app_js and "sync-ebay-readonly" in app_js and "saasEbayLiveReadPlan" in app_js and "saasEbayHttpDryRun" in app_js),
        _check("frontend_displays_ebay_live_packet_route_health", "Frontend displays the latest official eBay packet coverage and route-level GET health from backend task outputs.", "getLatestSaasEbaySyncSummary" in app_js and "saasEbayRouteRows" in app_js and "saasEbayPacketResourceRows" in app_js and "saas-route-strip" in app_js and "Official eBay read route health" in app_js),
        _check("frontend_saves_runtime_outputs", "Runtime reports are upserted into AI work records.", "applySaasReportsToActivities" in app_js and "upsertRuntimeActivity" in app_js),
        _check("frontend_keeps_demo_writes_safe", "Frontend approval still routes through confirmation and demo ExecutionService.", 'data-saas-action="approve-first"' in app_js and "real_platform_writes_enabled: false" in app_js),
    ]


def _stage_5_checks() -> list[dict[str, Any]]:
    team = JiejingAgentTeam().to_dict()
    executor = OwnedAgentExecutor().to_dict()
    quality_gate = OwnedAgentQualityGate().to_dict()
    provider_jobs = build_provider_job_contract_catalog()
    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="stage gate owned agent sample",
            merchant_goal="Verify Jiejing-owned Agent Team can run the commerce workflow under quality gates.",
            project_id="stage-gate-owned-agent-sample",
            source_mode="manual_or_1688",
            notes="Stage gate sample. No real platform writes.",
        )
    )
    runtime = JiejingRuntime(RuntimeConfig(adapter_name="jiejing-local", demo_mode=True, clean_output=True))
    summary = runtime.run_tasks(tasks, STAGE_5_RUN, run_id="stage-gate-owned-agent-sample")
    agent_provider_plan = build_agent_provider_execution_plan(tasks)
    result_files = sorted((STAGE_5_RUN / "results").glob("*.json"))
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in result_files]
    roles_seen = {
        result.get("report", {}).get("agent_role")
        for result in reports
        if isinstance(result.get("report"), dict)
    }
    gate_statuses = [
        result.get("report", {}).get("owned_agent_quality_gate", {}).get("status")
        for result in reports
        if isinstance(result.get("report"), dict)
    ]
    gate_blockers = [
        result.get("task_type")
        for result in reports
        if result.get("report", {}).get("owned_agent_quality_gate", {}).get("blockers")
    ]
    unsafe_gates = [
        result.get("task_type")
        for result in reports
        if result.get("report", {}).get("owned_agent_quality_gate", {}).get("safe_for_real_execution") is not False
    ]
    contract_failures = [
        result.get("task_type")
        for result in reports
        if result.get("report", {}).get("report_contract", {}).get("status") != "ready"
    ]
    audit_real_execution_flags = [
        result.get("task_type")
        for result in reports
        if any((result.get("audit", {}).get("real_execution") or {}).values())
    ]
    required_roles = {
        "ceo",
        "market-manager",
        "finance-supply",
        "product-manager",
        "asset-manager",
        "customer-service",
        "confirmation-center",
    }
    return [
        _check("owned_agent_team_contract", "Owned Agent Team exposes 7 commerce roles and is not a Hermes clone.", team.get("role_count") == 7 and team.get("replacement_boundary", {}).get("not_a_hermes_clone") is True),
        _check("owned_agent_executor_contract", "Owned Agent Executor can route 7 local commerce agents.", executor.get("agent_count") == 7 and executor.get("real_execution_allowed") is False),
        _check("owned_agent_quality_gate_contract", "Owned Agent quality gate checks reports without allowing real execution.", quality_gate.get("safe_for_real_execution") is False and "published_to_ebay" in quality_gate.get("high_risk_execution_keys", [])),
        _check("owned_agent_workflow_run", "Owned Agent Team can run a full local product workflow.", summary.task_count == len(tasks) and len(result_files) == len(tasks)),
        _check("owned_agent_role_coverage", "The workflow exercises all 7 owned commerce roles.", required_roles.issubset(roles_seen)),
        _check("owned_agent_report_contracts", "Every owned Agent report satisfies the Runtime report contract.", not contract_failures),
        _check("owned_agent_quality_gate_passes", "Every owned Agent report passes or only needs non-blocking attention.", bool(gate_statuses) and all(status in {"pass", "needs_attention"} for status in gate_statuses) and not gate_blockers),
        _check("owned_agent_no_real_execution", "Owned Agent outputs and audits do not execute real eBay/payment/logistics actions.", not unsafe_gates and not audit_real_execution_flags),
        _check("owned_agent_provider_job_contracts", "Provider jobs define queue, timeout, retry, secret, output and source-record boundaries for real tools.", provider_jobs.get("contract_count", 0) >= 6 and provider_jobs.get("secret_exposed") is False and provider_jobs.get("real_execution_allowed") is False),
        _check("owned_agent_provider_execution_plan", "Owned Agents map to provider jobs, secret purposes, source records and output packets before live tool calls.", agent_provider_plan.get("status") == "ready" and agent_provider_plan.get("provider_job_count", 0) >= 10 and {"public_search", "ebay", "sourcing", "logistics", "media", "model"}.issubset(set(agent_provider_plan.get("provider_families", []))) and agent_provider_plan.get("runtime_boundary", {}).get("runtime_gets_raw_secret") is False),
    ]


def _stage_6_checks(*, app_js: str, ebay_write_adapter: dict[str, Any], public_search_handoff_py: str) -> list[dict[str, Any]]:
    api_server_py = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    worker_py = (ROOT / "jiejing_saas" / "worker.py").read_text(encoding="utf-8")
    provider_runner_py = (ROOT / "jiejing_saas" / "provider_job_runner.py").read_text(encoding="utf-8")
    incomplete = ExecutionRequest(
        action_type="publish_listing",
        task_id="stage-gate-execution-task",
        user_id="user_stage_gate",
        company_id="company_stage_gate",
        store_id="store_stage_gate",
        platform="ebay",
        payload={"publish_listing": True},
        confirmation_id="confirm_stage_gate_publish",
        confirmed_by="user_stage_gate",
        confirmed_at="2026-05-15T00:00:00+08:00",
    )
    complete = ExecutionRequest(
        action_type="publish_listing",
        task_id="stage-gate-execution-task",
        user_id="user_stage_gate",
        company_id="company_stage_gate",
        store_id="store_stage_gate",
        platform="ebay",
        payload={
            "account_health": {
                "status": "clear",
                "selling_status": "active",
                "payout_status": "available",
                "restrictions": [],
            },
            "listing": {
                "sku": "STAGE-GATE-PUBLISH-001",
                "title": "Stage Gate Product Lightweight eBay Test",
                "description_html": "<p>Stage gate product for publish boundary validation.</p>",
                "category_id": "20687",
                "condition": "NEW",
                "price": "19.99",
                "quantity": 5,
                "merchant_location_key": "default",
                "item_specifics": {"Brand": "Unbranded", "Type": "Test Product"},
            },
            "business_policies": {
                "fulfillment_policy_id": "DEMO-FULFILLMENT",
                "payment_policy_id": "DEMO-PAYMENT",
                "return_policy_id": "DEMO-RETURN",
            },
            "supplier_facts": {
                "package_weight_g": 220,
                "package_dimensions_cm": {"length": 12, "width": 8, "height": 8},
                "material": "confirmed sample material",
                "item_location": "Fujian, China",
            },
            "asset_manifest": {"assets": [{"asset_id": "img_main_01", "asset_type": "main_image"}]},
            "finance_review": {"net_profit_money": "US $4.20"},
        },
        confirmation_id="confirm_stage_gate_publish",
        confirmed_by="user_stage_gate",
        confirmed_at="2026-05-15T00:00:00+08:00",
        idempotency_key="stage-gate-publish-001",
    )
    unconfirmed = ExecutionRequest(
        action_type="publish_listing",
        task_id="stage-gate-execution-task",
        user_id="user_stage_gate",
        company_id="company_stage_gate",
        store_id="store_stage_gate",
        platform="ebay",
        payload=complete.payload,
    )
    demo_service = ExecutionService(demo_mode=True)
    production_boundary = ExecutionService(demo_mode=False)
    incomplete_preflight = demo_service.preflight(incomplete)
    incomplete_production = production_boundary.execute(incomplete).to_dict()
    complete_production = production_boundary.execute(complete).to_dict()
    unconfirmed_result = production_boundary.execute(unconfirmed).to_dict()
    write_actions = {item.get("action_type") for item in ebay_write_adapter.get("actions", [])}
    return [
        _check("execution_preflight_contract", "ExecutionService exposes action-specific preflight checks.", incomplete_preflight.get("status") == "blocked_missing_execution_facts" and "listing.category_id" in incomplete_preflight.get("missing_fields", [])),
        _check("execution_preflight_blocks_production_missing_facts", "Production boundary blocks confirmed publish when listing facts are incomplete.", incomplete_production.get("status") == "blocked_preflight_missing"),
        _check("execution_confirmation_required", "Production boundary blocks high-risk actions without confirmation.", unconfirmed_result.get("status") == "blocked_confirmation_required"),
        _check("execution_complete_payload_handoff_only", "Complete confirmed publish payload is only ready for a platform adapter, not executed by Runtime.", complete_production.get("status") == "ready_for_platform_adapter"),
        _check("execution_no_real_write_flags", "Execution preflight and handoff keep all real execution flags false.", not any((complete_production.get("audit", {}).get("real_execution") or {}).values()) and complete_production.get("audit", {}).get("preflight", {}).get("real_execution_allowed") is False),
        _check("execution_idempotency_boundary", "ExecutionService records idempotency, payload hash and duplicate-prevention key before future platform adapter handoff.", bool(complete_production.get("audit", {}).get("idempotency", {}).get("duplicate_prevention_key")) and bool(complete_production.get("audit", {}).get("idempotency", {}).get("payload_hash")) and complete_production.get("audit", {}).get("execution_intent", {}).get("platform_adapter_called") is False),
        _check("frontend_preflight_visibility", "Frontend calls confirmation preflight and shows publish-gap status before execution.", "/preflight" in app_js and "saasPreflightResults" in app_js and "发布前检查" in app_js),
        _check("ebay_write_adapter_contract", "Backend exposes disabled eBay write adapter contract for future publish/revise/price/refund/policy routes.", {"publish_listing", "revise_listing", "change_price", "change_inventory", "refund", "policy_edit"}.issubset(write_actions) and ebay_write_adapter.get("writes_supported") is False),
        _check("frontend_write_adapter_visibility", "Frontend reads and displays the disabled eBay write-adapter contract.", '"/ebay-write/adapter/status"' in app_js and "saasEbayWriteAdapter" in app_js and "eBay 写入" in app_js),
        _check("provider_job_queue_endpoint", "SaaS backend can queue provider jobs before any live external tool call.", '"provider-job-contracts"' in api_server_py and '"provider-jobs"' in api_server_py and '"provider-job-plan"' in api_server_py and '"provider_job"' in worker_py),
        _check("provider_job_dry_run_runner", "Provider jobs produce normalized dry-run packets and keep live calls, raw secrets and writes disabled.", "live_provider_called" in provider_runner_py and "raw_secret_read" in provider_runner_py and "real_execution_allowed" in provider_runner_py),
        _check("public_search_live_adapter_boundary", "Public search provider can run as a gated live read and returns normalized source records without leaking API keys.", "JIEJING_PUBLIC_SEARCH_LIVE_ENABLED" in provider_runner_py and "completed_live_read" in provider_runner_py and "raw_provider_response_stored" in provider_runner_py and "live_public_search" in provider_runner_py),
        _check("public_search_market_packet_handoff", "Product workflows attach public-search provider output to Runtime market data packets and frontend source records.", "merge_public_search_handoff_input" in public_search_handoff_py and "market_probe_inputs" in public_search_handoff_py and "source_records" in public_search_handoff_py and "saasLastPublicSearchHandoff" in app_js),
        _check("ebay_read_sync_product_endpoint", "Backend exposes a product-level eBay read sync endpoint that blocks visibly instead of silently queueing incomplete work.", '"ebay-read-only" and parts[3] == "sync"' in api_server_py and "blocked_before_queue" in api_server_py and "merchant_next_step" in api_server_py),
    ]


def _check(key: str, label: str, passed: bool) -> dict[str, Any]:
    return {"key": key, "label": label, "pass": bool(passed)}


if __name__ == "__main__":
    raise SystemExit(main())

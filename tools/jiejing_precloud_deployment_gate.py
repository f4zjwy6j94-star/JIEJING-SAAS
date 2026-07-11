#!/usr/bin/env python3
"""Pre-cloud deployment gate for Jiejing SaaS.

This is the last local gate before moving to a public staging domain. It checks
that the repo is ready for the first real eBay OAuth/read-only validation loop:
frontend staging config, public demo-auth guardrail, OAuth/Vault boundaries,
eBay read-only preflight, backend MVP, and productization stage gate.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-precloud-deployment-gate"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


CHECKS: list[tuple[str, list[str]]] = [
    ("frontend_js_syntax", ["node", "--check", "app.js"]),
    ("current_state_guard", [sys.executable, "tools/test_jiejing_current_state_guard.py"]),
    ("frontend_staging_config", [sys.executable, "tools/test_jiejing_frontend_staging_config.py"]),
    ("product_grade_journey_contract", [sys.executable, "tools/test_jiejing_product_grade_journey_contract.py"]),
    ("ai_ceo_browser_streaming", [sys.executable, "tools/test_jiejing_ai_ceo_browser_streaming_contract.py"]),
    ("ai_ceo_source_quality", [sys.executable, "tools/test_jiejing_ai_ceo_source_quality.py"]),
    ("ai_ceo_listing_fact_boundary", [sys.executable, "tools/test_jiejing_ai_ceo_listing_fact_boundary.py"]),
    ("ai_ceo_product_label_extraction", [sys.executable, "tools/test_jiejing_ai_ceo_product_label_extraction.py"]),
    ("ai_ceo_listing_import_target", [sys.executable, "tools/test_jiejing_ai_ceo_listing_import_target.py"]),
    ("listing_progressive_disclosure", [sys.executable, "tools/test_jiejing_listing_progressive_disclosure.py"]),
    ("media_version_rework_ui", [sys.executable, "tools/test_jiejing_media_version_rework_ui.py"]),
    ("media_asset_jobs", [sys.executable, "tools/test_jiejing_media_asset_jobs.py"]),
    ("ai_ceo_cross_device_history", [sys.executable, "tools/test_jiejing_ai_ceo_cross_device_history.py"]),
    ("ai_ceo_scroll_retention", [sys.executable, "tools/test_jiejing_ai_ceo_scroll_retention.py"]),
    ("ai_ceo_history_pagination", [sys.executable, "tools/test_jiejing_ai_ceo_history_pagination.py"]),
    ("ai_ceo_cross_device_refresh", [sys.executable, "tools/test_jiejing_ai_ceo_cross_device_refresh_contract.py"]),
    ("bulk_partial_success", [sys.executable, "tools/test_jiejing_bulk_partial_success_contract.py"]),
    ("external_launch_blocker_gate", [sys.executable, "tools/test_jiejing_external_launch_blocker_gate.py"]),
    ("readiness_incident_ui", [sys.executable, "tools/test_jiejing_readiness_incident_ui.py"]),
    ("first_day_account_smoke", [sys.executable, "tools/test_jiejing_first_day_account_smoke.py"]),
    ("oauth_staging_deploy_contract", [sys.executable, "tools/test_jiejing_oauth_staging_deploy_contract.py"]),
    ("public_staging_proxy_contract", [sys.executable, "tools/test_jiejing_public_staging_proxy_contract.py"]),
    ("staging_oauth_operator_flow_tool", [sys.executable, "tools/test_jiejing_staging_ebay_oauth_flow_tool.py"]),
    ("p0_security_guardrails", [sys.executable, "tools/test_jiejing_saas_p0_security_guardrails.py"]),
    ("shared_expensive_api_rate_limit", [sys.executable, "tools/test_jiejing_expensive_api_rate_limit.py"]),
    ("billing_quota_guardrail", [sys.executable, "tools/test_jiejing_billing_quota_guardrail.py"]),
    ("session_revocation", [sys.executable, "tools/test_jiejing_session_revocation.py"]),
    ("monitoring_runbook_gate", [sys.executable, "tools/test_jiejing_monitoring_runbook_gate.py"]),
    ("oauth_callback_vault", [sys.executable, "tools/test_jiejing_ebay_oauth_callback_vault.py"]),
    ("vault_secret_resolver", [sys.executable, "tools/test_jiejing_vault_secret_resolver.py"]),
    ("ebay_credential_preflight", [sys.executable, "tools/test_jiejing_ebay_credential_preflight.py"]),
    ("ebay_live_read_http_client", [sys.executable, "tools/test_jiejing_ebay_live_read_http_client.py"]),
    ("saas_backend_mvp", [sys.executable, "tools/test_jiejing_saas_backend_mvp.py"]),
    ("infrastructure_drivers", [sys.executable, "tools/test_jiejing_infrastructure_drivers.py"]),
    ("postgres_repository_cutover", [sys.executable, "tools/test_jiejing_postgres_repository_cutover.py"]),
    ("redis_worker_cutover", [sys.executable, "tools/test_jiejing_redis_worker_cutover.py"]),
    ("worker_cli_contract", [sys.executable, "tools/test_jiejing_worker_cli_contract.py"]),
    ("agent_model_assist", [sys.executable, "tools/test_jiejing_agent_model_assist.py"]),
    ("infra_cutover_rehearsal", [sys.executable, "tools/test_jiejing_infra_cutover_rehearsal.py"]),
    ("sqlite_to_postgres_rehearsal", [sys.executable, "tools/test_jiejing_sqlite_to_postgres_rehearsal.py"]),
    ("infrastructure_stage_gate", [sys.executable, "tools/jiejing_infrastructure_stage_gate.py"]),
    ("deploy_channel_doctor_parser", [sys.executable, "tools/test_jiejing_deploy_channel_doctor.py"]),
    ("staging_deploy_channel_contract", [sys.executable, "tools/test_jiejing_staging_deploy_channel_contract.py"]),
    ("staging_patch_apply_contract", [sys.executable, "tools/test_jiejing_staging_patch_apply_contract.py"]),
    ("agents_md_guardrails", [sys.executable, "tools/test_jiejing_agents_md_guardrails.py"]),
    ("github_actions_deploy_guardrails", [sys.executable, "tools/test_jiejing_github_actions_deploy_guardrails.py"]),
    ("github_runner_doctor_guardrails", [sys.executable, "tools/test_jiejing_github_runner_doctor_guardrails.py"]),
    ("github_runner_maintenance_guardrails", [sys.executable, "tools/test_jiejing_github_runner_maintenance_guardrails.py"]),
    ("local_first_cloud_fallback_guardrails", [sys.executable, "tools/test_jiejing_local_first_cloud_fallback_guardrails.py"]),
    ("mainland_payment_strategy", [sys.executable, "tools/test_jiejing_mainland_payment_strategy.py"]),
    ("manual_beta_payment_flow", [sys.executable, "tools/test_jiejing_manual_beta_payment_flow.py"]),
    ("billing_provider_rehearsal", [sys.executable, "tools/test_jiejing_billing_provider_rehearsal.py"]),
    ("billing_provider_evidence_register", [sys.executable, "tools/test_jiejing_billing_provider_evidence_register.py"]),
    ("production_release_gate", [sys.executable, "tools/test_jiejing_production_release_gate.py"]),
    ("production_evidence_ledger", [sys.executable, "tools/test_jiejing_production_evidence_ledger.py"]),
    ("owner_launch_control_access", [sys.executable, "tools/test_jiejing_owner_launch_control_access.py"]),
    ("billing_provider_webhook", [sys.executable, "tools/test_jiejing_billing_provider_webhook.py"]),
    ("billing_webhook_subscription_state", [sys.executable, "tools/test_jiejing_billing_webhook_subscription_state.py"]),
    ("jiejing_owned_credential_chain", [sys.executable, "tools/jiejing_ebay_jiejing_credential_chain_smoke.py"]),
    ("productization_stage_gate", [sys.executable, "tools/jiejing_productization_stage_gate.py"]),
]


def main() -> int:
    started = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    results = [_run_check(key, command) for key, command in CHECKS]
    docker_path = shutil.which("docker")
    local_pass = all(item["pass"] for item in results)
    external_blockers = []
    if not docker_path:
        external_blockers.append("docker_cli_not_available_on_this_machine")
    staging_verification = _latest_staging_verification()
    summary: dict[str, Any] = {
        "product": "Jiejing SaaS",
        "gate": "precloud_deployment_gate",
        "status": "pass_local_checks" if local_pass else "failed_local_checks",
        "ready_for_public_staging_code_handoff": local_pass,
        "ready_for_paid_commercial_launch": False,
        "checks": results,
        "external_blockers": external_blockers,
        "docker_available": bool(docker_path),
        "docker_path": docker_path or "",
        "latest_public_staging_verification": staging_verification,
        "next_external_steps": _next_external_steps(staging_verification),
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
        "elapsed_seconds": round(time.time() - started, 2),
    }
    output_path = OUT / "latest.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"OUTPUT={output_path}")
    return 0 if local_pass else 1


def _latest_staging_verification() -> dict[str, Any]:
    path = ROOT / "output" / "jiejing-deploy-channel-doctor" / "latest.json"
    if not path.exists():
        return {"status": "not_checked", "public_staging_reachable": False, "deploy_channel_ready": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "invalid_doctor_output", "public_staging_reachable": False, "deploy_channel_ready": False}
    return {
        "status": "verified" if payload.get("deploy_channel_ready") and payload.get("public_staging_reachable") else "blocked",
        "deploy_channel_ready": payload.get("deploy_channel_ready") is True,
        "public_staging_reachable": payload.get("public_staging_reachable") is True,
        "public_health_service": (payload.get("public_health") or {}).get("service"),
        "real_platform_writes_enabled": (payload.get("public_health") or {}).get("real_platform_writes_enabled"),
        "secret_exposed": False,
    }


def _next_external_steps(staging_verification: dict[str, Any]) -> list[str]:
    steps = [
        "use_current_state_guard_before_any_future_oauth_sync_or_deploy_action",
        "provision_managed_postgres_and_redis_when_the_operator_approves_paid_infra",
        "configure_production_vault_kms_monitoring_backups_domain_and_billing_before_paid_launch",
        "do_not_repeat_seller_oauth_or_live_sync_unless_current_state_guard_says_the_artifact_is_missing_or_stale",
    ]
    if staging_verification.get("status") == "verified":
        return [
            "public_staging_is_reachable_keep_using_agentuser_ssh_for_future_patch_deploys",
            *steps,
        ]
    return [
        "deploy_verified_patch_to_existing_public_staging_over_the_known_agentuser_ssh_channel",
        *steps,
    ]


def _run_check(key: str, command: list[str]) -> dict[str, Any]:
    started = time.time()
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=180,
            check=False,
        )
    except FileNotFoundError as exc:
        return {
            "key": key,
            "pass": False,
            "returncode": 127,
            "elapsed_seconds": round(time.time() - started, 2),
            "error": f"command_not_found: {exc.filename}",
        }
    except subprocess.TimeoutExpired:
        return {
            "key": key,
            "pass": False,
            "returncode": 124,
            "elapsed_seconds": round(time.time() - started, 2),
            "error": "timeout",
        }
    return {
        "key": key,
        "pass": completed.returncode == 0,
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.time() - started, 2),
        "stdout_tail": completed.stdout[-1200:],
        "stderr_tail": completed.stderr[-1200:],
    }


if __name__ == "__main__":
    raise SystemExit(main())

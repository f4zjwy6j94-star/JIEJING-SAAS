#!/usr/bin/env python3
"""Product-grade guardrail checks for Jiejing SaaS backend startup."""

from __future__ import annotations

import os
import copy
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-saas-backend" / "guardrail-test"
sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import (
    SaaSBackendServer,
    _production_controlled_unpublished_draft_boot_allowed,
    _readiness_has_startup_blockers,
)
from jiejing_saas import api_server
from jiejing_saas.config import SaaSSettings


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def expired_recovery_readiness() -> dict:
    """Full 38-item frozen 456/R6 schema; not the working tree's extra trial item."""
    statuses = {
        "environment": "ready", "session_secret": "ready", "cors_origin": "ready",
        "team_permission_boundary": "role_boundary_ready", "database": "ready",
        "database_adapter_contract": "managed_adapter_live",
        "database_migration_plan": "migration_shape_ready", "queue": "postgres_durable_queue_ready",
        "queue_adapter_contract": "managed_queue_live", "queue_worker_plan": "ready",
        "database_live_probe": "ready", "queue_runtime_health": "ready", "worker_runtime_health": "ready",
        "infrastructure_drivers": "ready", "independent_runtime": "ready", "controlled_bridges": "ready",
        "vault": "ready", "vault_adapter_contract": "adapter_contract_ready", "runtime_workers": "ready",
        "monitoring_alerting": "cloud_monitoring_ready", "tenant_audit": "ready", "billing_quota": "ready",
        "provider_job_runner": "dry_run_contract_ready", "model_provider": "merchant_byok_secret_ref_ready",
        "model_value_proof": "ready", "platform_registry": "reserved_contract_ready",
        "ebay_account_deletion_notifications": "operational_ready", "ebay_oauth_readonly": "read_only_authorized",
        "ebay_token_refresh": "vault_backed_refresh_adapter_ready", "ebay_read_only_adapter": "official_read_completed",
        "ebay_live_read_adapter": "ready", "platform_data_packets": "exercised",
        "real_saas_loop_evidence": "official_packet_reports_confirmations", "ebay_read": "official_packet_ready",
        "account_health_incident_mode": "packet_backed_gate_ready", "ebay_business_policies": "official_policy_packet_ready",
        "execution_service": "unpublished_ebay_draft_save_proven",
    }
    items = [dict(key=key, label=key, status=status, severity="info", detail="Verified fixture.",
                  next_action="Keep monitoring.") for key, status in statuses.items()]
    items.append(dict(key="backup_restore", label="Backup and restore", status="blocked_backup_restore_not_ready",
                      severity="blocker", detail="Vault restore evidence is overdue.", next_action="Run the real drill."))
    health = {
        "contract_version": "2026-06-17-deep-operational-health", "environment": "production",
        "status": "ready", "blockers": [], "warnings": [], "secret_exposed": False,
        "database_live_probe": {"status": "ready", "secret_exposed": False},
        "redis_live_probe": {"status": "ready", "secret_exposed": False},
        "vault_live_probe": {"status": "ready", "secret_exposed": False},
    }
    return {
        "environment": "production", "production_ready": False, "beta_ready": False,
        "can_accept_real_customers": False, "reason": "readiness_blocked", "secret_exposed": False,
        "real_platform_writes_enabled": False, "requested_real_platform_writes": False,
        "blocker_count": 1, "warning_count": 0, "items": items, "operational_health": health,
        "provider_status": {"backup": {
            "contract_version": "2026-05-18-backup-restore-boundary", "backup_ready_for_paid_launch": False,
            "blockers": ["vault_restore_drill_overdue"], "secret_exposed": False,
        }},
    }


def check_expired_recovery_http_boot() -> None:
    """Exercise the real serve_forever branch and real loopback HTTP server."""
    readiness = expired_recovery_readiness()
    original = copy.deepcopy(readiness)
    servers = []
    errors = []
    listening = threading.Event()
    real_server = api_server.JiejingSafeThreadingHTTPServer

    def capture_server(address, handler):
        server = real_server(address, handler)
        servers.append(server)
        listening.set()
        return server

    test_env = {
        "JIEJING_SAAS_ENV": "production",
        "JIEJING_SAAS_SESSION_SECRET": "isolated-recovery-http-fixture-secret-long-enough",
        "JIEJING_PRODUCTION_CANDIDATE_BOOT_ALLOWED": "false",
        "JIEJING_PRODUCTION_CONTROLLED_DRAFT_BOOT_ALLOWED": "false",
        "JIEJING_WECHAT_PAY_CHARGE_ALLOWED": "true", "JIEJING_WECHAT_PAY_REFUND_ALLOWED": "true",
        "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false", "JIEJING_EBAY_WRITE_LIVE": "false",
    }
    # Real local SQLite isolates persistence. Only production dependency evidence
    # is substituted; no real provider credentials, request or startup bypass.
    with patch.dict(os.environ, test_env, clear=True), \
            patch.object(api_server, "build_product_readiness_or_degraded", return_value=readiness), \
            patch.object(api_server, "build_operational_health", return_value=readiness["operational_health"]), \
            patch.object(api_server, "JiejingSafeThreadingHTTPServer", side_effect=capture_server):
        backend = SaaSBackendServer(db_path=OUT / "expired-recovery.sqlite", runtime_db_path=OUT / "expired-runtime.sqlite",
                                    output_root=OUT, host="127.0.0.1", port=0)

        def run():
            try:
                backend.serve_forever()
            except Exception as exc:
                errors.append(exc)
                listening.set()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            assert listening.wait(10), "expired evidence boot did not reach a terminal startup result"
            if errors:
                expected_refusal = all(isinstance(exc, RuntimeError) and str(exc) == (
                    "Refusing to start a blocked production candidate without "
                    "JIEJING_PRODUCTION_CANDIDATE_BOOT_ALLOWED=true."
                ) for exc in errors)
                assert expected_refusal, "unexpected startup exception category: " + ",".join(type(exc).__name__ for exc in errors)
                raise AssertionError("expired evidence hit the exact blocked-production-candidate startup refusal")
            assert servers, "expired evidence must reach real HTTP bind"
            base = "http://127.0.0.1:" + str(servers[0].server_port)
            for path in ("/health", "/health/startup", "/readiness/product-saas"):
                with urllib.request.urlopen(base + path, timeout=2) as response:
                    payload = json.load(response)
                    assert response.status == 200, path
                if path == "/readiness/product-saas":
                    view = payload["readiness"]
                    assert all(view[key] is False for key in ("production_ready", "beta_ready", "can_accept_real_customers"))
                    assert view["blocker_count"] == 1 and view["items"][0]["key"] == "backup_restore"
            assert readiness == original, "boot must not mutate readiness or fabricate recovery evidence"
            assert os.environ["JIEJING_WECHAT_PAY_CHARGE_ALLOWED"] == "true"
            assert os.environ["JIEJING_WECHAT_PAY_REFUND_ALLOWED"] == "true"
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            thread.join(timeout=5)
            assert not thread.is_alive(), "isolated HTTP startup test leaked its server thread"


def check_expired_recovery_rejections() -> None:
    baseline = expired_recovery_readiness()
    assert len(baseline["items"]) == 38
    assert not _readiness_has_startup_blockers(baseline)
    cases = []

    def changed(path, value):
        packet = copy.deepcopy(baseline)
        target = packet
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        cases.append(packet)

    for key in ("blocker_count", "warning_count"):
        for bad in (None, True, "1", -1, 2):
            changed((key,), bad)
    for key in ("production_ready", "beta_ready", "can_accept_real_customers", "secret_exposed",
                "requested_real_platform_writes", "real_platform_writes_enabled"):
        for bad in (True, None, 0, "false"):
            changed((key,), bad)
    changed(("environment",), "staging")
    changed(("reason",), "ready")
    changed(("degraded",), True)
    for bad in (None, {}, False, [], "items"):
        changed(("items",), bad)
    changed(("items",), baseline["items"] + [copy.deepcopy(baseline["items"][0])])
    changed(("items",), baseline["items"] + [dict(key="other", label="Other", status="blocked", severity="blocker",
                                                detail="Other fault.", next_action="Repair it.")])
    required_safety_keys = {
        "environment", "session_secret", "cors_origin", "team_permission_boundary", "database",
        "database_adapter_contract", "database_migration_plan", "queue", "queue_adapter_contract", "queue_worker_plan",
        "database_live_probe", "queue_runtime_health", "worker_runtime_health", "infrastructure_drivers",
        "independent_runtime", "controlled_bridges", "vault", "vault_adapter_contract", "runtime_workers",
        "monitoring_alerting", "tenant_audit", "billing_quota", "backup_restore",
    }
    for index, item in enumerate(baseline["items"]):
        if item["key"] in required_safety_keys:
            changed(("items",), [entry for position, entry in enumerate(baseline["items"]) if position != index])
            changed(("items", index, "status"), "blocked_unknown")
        for field in ("key", "label", "status", "severity", "detail", "next_action"):
            changed(("items", index, field), "")
        changed(("items", index, "severity"), "warning")
    changed(("provider_status",), None)
    changed(("provider_status", "backup"), None)
    for field in ("contract_version", "backup_ready_for_paid_launch", "secret_exposed"):
        changed(("provider_status", "backup", field), None)
    for blockers in ([], None, {}, "vault_restore_drill_overdue", ["restore_drill_overdue"],
                     ["backup_policy_not_configured"], ["vault_offline_share_custody_distribution_unsafe"],
                     ["vault_restore_drill_overdue", "missing_database_url"],
                     ["vault_restore_drill_overdue", "vault_restore_drill_overdue"]):
        changed(("provider_status", "backup", "blockers"), blockers)
    changed(("operational_health",), None)
    for field, value in (("status", "blocked"), ("environment", "staging"), ("secret_exposed", True),
                         ("contract_version", None), ("blockers", ["database_failed"]), ("warnings", ["worker_failed"])):
        changed(("operational_health", field), value)
    for probe in ("database_live_probe", "redis_live_probe", "vault_live_probe"):
        changed(("operational_health", probe), None)
        changed(("operational_health", probe, "status"), "blocked")
        changed(("operational_health", probe, "secret_exposed"), True)
    for index, packet in enumerate(cases):
        assert _readiness_has_startup_blockers(packet), f"unsafe/malformed recovery case {index} bypassed cold-start guard"
    informational = copy.deepcopy(baseline)
    informational["items"].append(dict(key="registration_trial_challenge", label="Trial", status="ready", severity="info",
                                        detail="Future optional guard evidence.", next_action="Keep auditing."))
    assert not _readiness_has_startup_blockers(informational), "new informational keys may coexist without becoming a cold-start dependency"
    informational["items"][-1].update(status="blocked_platform_trial_activation_challenge_not_ready", severity="blocker")
    assert _readiness_has_startup_blockers(informational), "an extra future blocker must never receive the expiry exception"
    print(f"PASS expired_recovery_boundary_negative_cases={len(cases)}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        check_expired_recovery_http_boot()
        check_expired_recovery_rejections()
    except AssertionError as exc:
        return fail(str(exc))

    controlled_draft_env = {
        "JIEJING_SAAS_ENV": "production",
        "JIEJING_SAAS_SESSION_SECRET": "production-controlled-draft-test-secret-that-is-long-enough",
        "JIEJING_PRODUCTION_CANDIDATE_BOOT_ALLOWED": "false",
        "JIEJING_PRODUCTION_CONTROLLED_DRAFT_BOOT_ALLOWED": "true",
        "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
        "JIEJING_EBAY_WRITE_LIVE": "false",
        "JIEJING_EBAY_DRAFT_SAVE_LIVE": "true",
        "JIEJING_EBAY_CONTROLLED_PUBLISH_LIVE": "false",
        "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "true",
        "JIEJING_EBAY_READ_ONLY_LIVE": "true",
        "JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY": "controlled_unpublished_draft_only",
        "JIEJING_WECHAT_PAY_CHARGE_ALLOWED": "false",
        "JIEJING_WECHAT_PAY_REFUND_ALLOWED": "false",
    }
    with patch.dict(os.environ, controlled_draft_env, clear=False):
        controlled_draft_settings = SaaSSettings.from_env(
            db_path=OUT / "controlled-draft.sqlite",
            runtime_db_path=OUT / "controlled-draft-runtime.sqlite",
            output_root=OUT,
            host="127.0.0.1",
            port=8793,
        )
        if not _production_controlled_unpublished_draft_boot_allowed(controlled_draft_settings):
            return fail("an exact unpublished-draft-only production lane must be allowed to boot despite commercial blockers")
        os.environ["JIEJING_EBAY_WRITE_LIVE"] = "true"
        unsafe_write_settings = SaaSSettings.from_env(
            db_path=OUT / "controlled-draft.sqlite",
            runtime_db_path=OUT / "controlled-draft-runtime.sqlite",
            output_root=OUT,
            host="127.0.0.1",
            port=8793,
        )
        if _production_controlled_unpublished_draft_boot_allowed(unsafe_write_settings):
            return fail("the controlled draft boot lane must fail closed when broad eBay writes are requested")
        os.environ["JIEJING_EBAY_WRITE_LIVE"] = "false"
        os.environ["JIEJING_EBAY_CONTROLLED_PUBLISH_LIVE"] = "true"
        os.environ["JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY"] = "controlled_existing_draft_publish"
        controlled_publish_settings = SaaSSettings.from_env(
            db_path=OUT / "controlled-draft.sqlite",
            runtime_db_path=OUT / "controlled-draft-runtime.sqlite",
            output_root=OUT,
            host="127.0.0.1",
            port=8793,
        )
        if not _production_controlled_unpublished_draft_boot_allowed(controlled_publish_settings):
            return fail("an exact existing-draft publish lane must boot without enabling broad writes")
        if controlled_publish_settings.effective_real_platform_writes_enabled is not False:
            return fail("the existing-draft publish lane must keep broad writes disabled")
        controlled_process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
                "serve",
                "--db",
                str(OUT / "controlled-draft-boot.sqlite"),
                "--runtime-db",
                str(OUT / "controlled-draft-boot-runtime.sqlite"),
                "--output-root",
                str(OUT),
                "--host",
                "127.0.0.1",
                "--port",
                "8793",
            ],
            cwd=str(ROOT),
            env=os.environ.copy(),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        controlled_boot_ready = False
        controlled_boot_output = ""
        try:
            for _ in range(40):
                if controlled_process.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8793/health", timeout=0.25) as response:
                        controlled_boot_ready = response.status == 200
                        if controlled_boot_ready:
                            break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.1)
            if not controlled_boot_ready:
                controlled_process.terminate()
                stdout, stderr = controlled_process.communicate(timeout=5)
                controlled_boot_output = (stdout or "") + (stderr or "")
        finally:
            if controlled_process.poll() is None:
                controlled_process.terminate()
                try:
                    controlled_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    controlled_process.kill()
        if not controlled_boot_ready:
            return fail(
                "the exact controlled draft lane must boot a blocker-held production process: "
                + controlled_boot_output[-500:].encode("ascii", "backslashreplace").decode("ascii")
            )

    warning_only_readiness = {
        "production_ready": False,
        "blocker_count": 0,
        "warning_count": 1,
        "items": [{"severity": "warning", "status": "blocked_provider_monitoring_evidence"}],
    }
    if _readiness_has_startup_blockers(warning_only_readiness):
        return fail("warning-only readiness must not turn a production restart into an outage")
    if not _readiness_has_startup_blockers({"production_ready": False, "blocker_count": 1}):
        return fail("a real readiness blocker must still refuse normal production startup")
    if not _readiness_has_startup_blockers({"production_ready": False}):
        return fail("missing blocker counts must fail closed")
    if not _readiness_has_startup_blockers({"production_ready": False, "blocker_count": True}):
        return fail("malformed blocker counts must fail closed")

    env = os.environ.copy()
    env["JIEJING_SAAS_ENV"] = "production"
    env["JIEJING_SAAS_SESSION_SECRET"] = "production-like-test-secret-that-is-long-enough"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(OUT / "prod-guard.sqlite"),
            "--runtime-db",
            str(OUT / "prod-runtime.sqlite"),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            "8794",
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=15,
        check=False,
    )
    combined = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        return fail("production backend should refuse to start with local sqlite/queue/vault blockers")
    if "Refusing to start a blocked production candidate" not in combined:
        return fail("production refusal should explain readiness blockers")

    env = os.environ.copy()
    env["JIEJING_ENABLE_REAL_PLATFORM_WRITES"] = "true"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(OUT / "write-guard.sqlite"),
            "--runtime-db",
            str(OUT / "write-runtime.sqlite"),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            "8795",
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=15,
        check=False,
    )
    combined = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        return fail("backend should refuse requested real platform writes in MVP")
    if "Refusing to enable real platform writes" not in combined:
        return fail("real write refusal should be explicit")

    env = os.environ.copy()
    env.update(
        {
            "JIEJING_SAAS_ENV": "production",
            "JIEJING_SAAS_SESSION_SECRET": "production-like-test-secret-that-is-long-enough",
            "JIEJING_CORS_ORIGIN": "https://app.jiejing.example",
            "JIEJING_DATABASE_ENGINE": "postgres",
            "JIEJING_DATABASE_ADAPTER": "postgres-managed",
            "JIEJING_DATABASE_URL": "postgresql://jiejing:placeholder@postgres:5432/jiejing",
            "JIEJING_QUEUE_PROVIDER": "redis_streams",
            "JIEJING_QUEUE_URL": "redis://redis:6379/0",
            "JIEJING_VAULT_ENABLED": "true",
            "JIEJING_VAULT_PROVIDER": "vault",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(OUT / "managed-prod-guard.sqlite"),
            "--runtime-db",
            str(OUT / "managed-prod-runtime.sqlite"),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            "8796",
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=15,
        check=False,
    )
    combined = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        return fail("production backend should still refuse managed DB/queue config until drivers are implemented")
    if not any(
        marker in combined
        for marker in (
            "Refusing to start a blocked production candidate",
            "Refusing to start production Jiejing SaaS backend while repository readiness has blockers",
        )
    ):
        return fail("managed driver-pending production refusal should be explicit")

    candidate_env = os.environ.copy()
    candidate_env.update(
        {
            "JIEJING_SAAS_ENV": "production",
            "JIEJING_SAAS_SESSION_SECRET": "production-candidate-test-secret-that-is-long-enough",
            "JIEJING_PRODUCTION_CANDIDATE_BOOT_ALLOWED": "true",
            "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "true",
            "JIEJING_EBAY_READ_ONLY_LIVE": "true",
            "JIEJING_EBAY_DRAFT_SAVE_LIVE": "true",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(OUT / "candidate-draft-guard.sqlite"),
            "--runtime-db",
            str(OUT / "candidate-draft-runtime.sqlite"),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            "8797",
        ],
        cwd=str(ROOT),
        env=candidate_env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=15,
        check=False,
    )
    combined = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        return fail("production candidate boot must refuse the controlled eBay draft-save write lane")
    if "requires payment and platform writes to remain disabled" not in combined:
        return fail("production candidate draft-save refusal should be explicit")

    print("PASS jiejing_saas_production_guardrails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""CLI regression for tenant/store-scoped new eBay account evidence."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jiejing_new_ebay_account_low_risk_check import (
    _authenticated_origin_allowed,
    _get_json,
    _safe_base_url,
    _safe_endpoint_summary,
    _validated_base_url,
)


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "jiejing_new_ebay_account_low_risk_check.py"
STORE_ID = "store-current-sentinel"
COMPANY_ID = "company-current-sentinel"
CONNECTION_ID = "connection-current-sentinel"
STRONG_OAUTH_STATUS = {
    "authorized": True,
    "pending": False,
    "strong_identity_ready": True,
    "backend_provenance_ready": True,
    "connection_id_sha256": hashlib.sha256(CONNECTION_ID.encode("utf-8")).hexdigest(),
}
REQUIRED_RESOURCES = [
    "store_profile",
    "account_business_policies",
    "inventory_and_offers",
    "orders_and_fulfillment",
    "finances",
    "taxonomy_listing_metadata",
]
OPERATOR_FLAGS = [
    "JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN",
    "JIEJING_NEW_EBAY_OLD_FROZEN_ACCOUNT_REJECTED",
    "JIEJING_NEW_EBAY_OAUTH_OPERATOR_APPROVED",
    "JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED",
    "JIEJING_NEW_EBAY_FRESH_PRODUCT_DECLARED",
    "JIEJING_NEW_EBAY_FRESH_SKU_DECLARED",
    "JIEJING_NEW_EBAY_FRESH_ASSETS_DECLARED",
    "JIEJING_NEW_EBAY_NO_OLD_LISTING_OR_REPORT_REUSE",
    "JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED",
    "JIEJING_NEW_EBAY_PUBLISH_HEALTH_CONFIRMATION_READY",
    "JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED",
    "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED",
    "JIEJING_NEW_EBAY_CLEANUP_CONFIRMATION_APPROVED",
    "JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED",
]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


class FixtureHandler(BaseHTTPRequestHandler):
    health: dict[str, object] = {"status": "ok", "database_startup_status": "ready"}
    deep_health: dict[str, object] = {
        "status": "ready",
        "database": {"status": "ready"},
        "queue": {"status": "ready"},
        "worker": {"status": "ready"},
        "secret_exposed": False,
    }
    account_health: dict[str, object] = {
        "company_id": COMPANY_ID,
        "store_id": STORE_ID,
        "platform": "ebay",
        "status": "normal",
        "incident_mode": False,
        "can_execute_real_writes": True,
    }
    connections: list[dict[str, object]] = []
    data_packets: list[dict[str, object]] = []
    queue_jobs: list[dict[str, object]] = []
    audit_logs: list[dict[str, object]] = []
    oauth_status: dict[str, object] = {
        "authorized": False,
        "pending": False,
        "strong_identity_ready": False,
        "backend_provenance_ready": False,
    }
    commercial_gate: dict[str, object] = {
        "current_store_ebay_evidence": {
            "new_account_action_evidence": {
                "contract_version": "2026-06-18-new-ebay-account-low-risk-smoke",
                "company_store_bound": True,
                "publish_health_confirmation_ready": False,
                "controlled_real_publish_ready": False,
                "post_publish_cleanup_ready": False,
                "secret_exposed": False,
            }
        }
    }
    readiness: object = {}
    requests: list[tuple[str, str, bool]] = []

    def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
        type(self).requests.append(("GET", self.path, bool(self.headers.get("authorization"))))
        path = self.path.split("?", 1)[0]
        if path == "/redirect":
            self.send_response(302)
            self.send_header("location", "/health")
            self.end_headers()
            return
        if path == "/health":
            payload = type(self).health
        elif path == "/health/deep":
            payload = {"operational_health": type(self).deep_health}
        elif path == "/readiness/product-saas":
            payload = {"readiness": type(self).readiness}
        elif path == "/stores":
            payload = {"stores": [{"store_id": STORE_ID, "company_id": COMPANY_ID, "platform": "ebay"}]}
        elif path == f"/stores/{STORE_ID}/account-health":
            payload = {"account_health": type(self).account_health}
        elif path == f"/stores/{STORE_ID}/ebay-oauth/read-only-status":
            payload = {"ebay_oauth_read_only_status": type(self).oauth_status}
        elif path == "/connections":
            payload = {"connections": type(self).connections}
        elif path == "/data-packets":
            payload = {"data_packets": type(self).data_packets}
        elif path == "/queue-jobs":
            payload = {"queue_jobs": type(self).queue_jobs}
        elif path == "/audit-logs":
            payload = {"audit_logs": type(self).audit_logs}
        elif path == "/commercial/launch-gate":
            payload = {"commercial_launch_gate": type(self).commercial_gate}
        elif path == "/queue/health":
            payload = {"queue_health": {"status": "ready"}}
        elif path == "/billing/usage":
            payload = {"billing_usage": {"status": "ready"}}
        else:
            self.send_response(404)
            self.end_headers()
            return
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def run_checker(
    *,
    account_health: dict[str, object] | None = None,
    connections: list[dict[str, object]] | None = None,
    data_packets: list[dict[str, object]] | None = None,
    queue_jobs: list[dict[str, object]] | None = None,
    audit_logs: list[dict[str, object]] | None = None,
    oauth_status: dict[str, object] | None = None,
    health: dict[str, object] | None = None,
    deep_health: dict[str, object] | None = None,
    readiness: object | None = None,
    commercial_gate: dict[str, object] | None = None,
    oauth_flags_enabled: bool = True,
) -> tuple[subprocess.CompletedProcess[str], list[tuple[str, str, bool]]]:
    FixtureHandler.account_health = account_health or {
        "company_id": COMPANY_ID,
        "store_id": STORE_ID,
        "platform": "ebay",
        "status": "normal",
        "incident_mode": False,
        "can_execute_real_writes": True,
    }
    FixtureHandler.connections = list(connections or [])
    FixtureHandler.data_packets = list(data_packets or [])
    FixtureHandler.queue_jobs = list(queue_jobs or [])
    FixtureHandler.audit_logs = list(audit_logs or [])
    FixtureHandler.oauth_status = oauth_status or {
        "authorized": False,
        "pending": False,
        "strong_identity_ready": False,
        "backend_provenance_ready": False,
    }
    FixtureHandler.health = health or {"status": "ok", "database_startup_status": "ready"}
    FixtureHandler.deep_health = deep_health or {
        "status": "ready",
        "database": {"status": "ready"},
        "queue": {"status": "ready"},
        "worker": {"status": "ready"},
        "secret_exposed": False,
    }
    FixtureHandler.readiness = readiness if readiness is not None else {
        "beta_ready": True,
        "blocker_count": 0,
        "warning_count": 0,
        "can_accept_real_customers": False,
        "items": [
            {"key": "database_live_probe", "status": "ready"},
            {"key": "queue_runtime_health", "status": "ready"},
            {"key": "worker_runtime_health", "status": "ready"},
            {"key": "account_health_incident_mode", "status": "ready"},
            {"key": "publish_safety_system", "status": "ready"},
            {"key": "post_publish_cockpit", "status": "ready"},
        ],
        "product_evidence": {
            "latest_ebay_packet_id": "global-historical-packet-sentinel",
            "latest_ebay_packet_present_resource_keys": REQUIRED_RESOURCES,
            "ebay_token_refresh_success_count": 99,
        },
    }
    FixtureHandler.commercial_gate = commercial_gate or {
        "current_store_ebay_evidence": {
            "new_account_action_evidence": {
                "contract_version": "2026-06-18-new-ebay-account-low-risk-smoke",
                "company_store_bound": True,
                "publish_health_confirmation_ready": False,
                "controlled_real_publish_ready": False,
                "post_publish_cleanup_ready": False,
                "secret_exposed": False,
            }
        }
    }
    FixtureHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = os.environ.copy()
    env["JIEJING_SAAS_TOKEN"] = "test-token-must-not-leak"
    for name in OPERATOR_FLAGS:
        env[name] = "true"
    if not oauth_flags_enabled:
        env.pop("JIEJING_NEW_EBAY_OAUTH_OPERATOR_APPROVED", None)
        env.pop("JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED", None)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(CHECKER),
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--store-id",
                STORE_ID,
            ],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return completed, list(FixtureHandler.requests)


def main() -> int:
    safe_url = _safe_base_url("https://user-sentinel:password-sentinel@example.test:8443/private/path?token=sentinel")
    if safe_url != "https://example.test:8443":
        return fail(f"safe base URL must discard userinfo, path and query: {safe_url}")
    for unsafe_url in (
        "https://user:password@example.test",
        "https://example.test/private/path",
        "https://example.test?token=sentinel",
    ):
        try:
            _validated_base_url(unsafe_url)
        except ValueError:
            pass
        else:
            return fail("configured base URL must reject userinfo, path and query input")
    if _authenticated_origin_allowed("http://example.test") is not False:
        return fail("authenticated requests must reject non-HTTPS non-loopback origins")
    if _authenticated_origin_allowed("https://example.test") is not True or _authenticated_origin_allowed("http://127.0.0.1:8123") is not True:
        return fail("authenticated requests should allow HTTPS and explicit loopback test origins")

    FixtureHandler.requests = []
    redirect_server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    redirect_thread = threading.Thread(target=redirect_server.serve_forever, daemon=True)
    redirect_thread.start()
    try:
        redirected = _get_json(
            f"http://127.0.0.1:{redirect_server.server_port}/redirect",
            token="redirect-test-token",
        )
    finally:
        redirect_server.shutdown()
        redirect_server.server_close()
        redirect_thread.join(timeout=5)
    if redirected.get("request_failed") is not True or redirected.get("http_status") != 302:
        return fail("checker HTTP client must refuse redirects instead of forwarding authenticated requests")
    if any(path == "/health" for _method, path, _authenticated in FixtureHandler.requests):
        return fail("redirect refusal must prevent any follow-up request")

    upstream_sentinel = "upstream-classification-must-not-leak"
    malicious_summary = _safe_endpoint_summary(
        "/readiness/product-saas",
        {
            "readiness": {
                "blocker_count": "not-an-int",
                "warning_count": "not-an-int",
                "items": [{"key": upstream_sentinel, "status": upstream_sentinel, "severity": upstream_sentinel}],
            }
        },
    )
    if upstream_sentinel in json.dumps(malicious_summary) or malicious_summary.get("blocker_count") != 0:
        return fail("upstream classifications must be allowlisted and integer fields parsed fail-closed")

    completed, _requests = run_checker(
        account_health={
            "company_id": COMPANY_ID,
            "store_id": STORE_ID,
            "platform": "ebay",
            "status": upstream_sentinel,
            "incident_mode": True,
            "can_execute_real_writes": False,
        },
        readiness={
            "beta_ready": True,
            "blocker_count": "not-an-int",
            "warning_count": "not-an-int",
            "can_accept_real_customers": False,
            "items": [
                {"key": "database_live_probe", "status": upstream_sentinel, "severity": "blocker"},
                {"key": "queue_runtime_health", "status": "ready"},
                {"key": "worker_runtime_health", "status": "ready"},
                {"key": "account_health_incident_mode", "status": "ready"},
            ],
        }
    )
    if not completed.stdout:
        return fail("malformed upstream integer fields must not crash the checker")
    malicious_payload = json.loads(completed.stdout)
    if upstream_sentinel in completed.stdout or any(upstream_sentinel in str(item) for item in malicious_payload.get("blockers") or []):
        return fail("checker output and blockers must not echo untrusted upstream classifications")

    malformed_readiness_sentinel = "malformed-readiness-value-must-not-leak"
    for malformed_readiness in (
        [malformed_readiness_sentinel],
        malformed_readiness_sentinel,
        {
            "beta_ready": True,
            "blocker_count": {"nested": malformed_readiness_sentinel},
            "warning_count": [malformed_readiness_sentinel],
            "items": {"nested": malformed_readiness_sentinel},
        },
    ):
        completed, _requests = run_checker(readiness=malformed_readiness)
        try:
            malformed_payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return fail("malformed readiness shapes must return stable fail-closed JSON")
        malformed_phases = {
            item.get("key"): item
            for item in malformed_payload.get("phases", [])
            if isinstance(item, dict)
        }
        if completed.returncode == 0 or (malformed_phases.get("public_preflight_ready") or {}).get("status") != "blocked":
            return fail("malformed readiness shapes must fail closed")
        if "readiness_count_invalid" not in (malformed_payload.get("blockers") or []):
            return fail("malformed readiness shapes must report the fixed readiness blocker")
        combined_output = completed.stdout + completed.stderr
        if malformed_readiness_sentinel in combined_output:
            return fail("malformed readiness values must not be reflected in checker output")
        if "traceback" in completed.stderr.lower():
            return fail("malformed readiness shapes must fail closed without a traceback")

    completed, _requests = run_checker(health={"status": "ok"})
    payload = json.loads(completed.stdout)
    phases = {item.get("key"): item for item in payload.get("phases", []) if isinstance(item, dict)}
    if (phases.get("public_preflight_ready") or {}).get("status") != "blocked":
        return fail("public health must require database_startup_status=ready instead of accepting a missing field")

    completed, _requests = run_checker(
        deep_health={
            "status": "degraded",
            "database": {"status": "ready"},
            "queue": {"status": "ready"},
            "worker": {"status": "degraded"},
            "secret_exposed": False,
        }
    )
    payload = json.loads(completed.stdout)
    phases = {item.get("key"): item for item in payload.get("phases", []) if isinstance(item, dict)}
    if (phases.get("public_preflight_ready") or {}).get("status") != "blocked":
        return fail("public preflight must GET health/deep and require database, queue and worker readiness")

    completed, _requests = run_checker()
    payload = json.loads(completed.stdout)
    phases = {item.get("key"): item for item in payload.get("phases", []) if isinstance(item, dict)}
    current_scope_phase = phases.get("official_packet_account_health_snapshot") or {}
    if current_scope_phase.get("status") != "blocked":
        return fail("global historical packet/refresh evidence must not pass the current-store evidence phase")

    packet_id = "current-packet-sentinel"
    account_health = {
        "company_id": COMPANY_ID,
        "store_id": STORE_ID,
        "platform": "ebay",
        "status": "normal",
        "incident_mode": False,
        "can_execute_real_writes": True,
        "evidence_package": {
            "packet_id": packet_id,
            "official_packet_present": True,
        },
    }
    data_packets = [
        {
            "packet_id": packet_id,
            "company_id": COMPANY_ID,
            "store_id": STORE_ID,
            "platform": "ebay",
            "source_mode": "official_api",
            "packet": {
                "present_resource_keys": REQUIRED_RESOURCES,
                "sections": {
                    "store_profile": {
                        "data": {"seller_username": "seller-private-value-must-not-leak"}
                    }
                },
            },
        }
    ]
    wrong_company_connections = [
        {
            "company_id": "wrong-company-sentinel",
            "store_id": STORE_ID,
            "platform": "ebay",
            "status": "read_only_authorized",
        }
    ]
    completed, _requests = run_checker(
        account_health=account_health,
        connections=wrong_company_connections,
        data_packets=data_packets,
    )
    payload = json.loads(completed.stdout)
    phases = {item.get("key"): item for item in payload.get("phases", []) if isinstance(item, dict)}
    if (phases.get("official_packet_account_health_snapshot") or {}).get("status") != "blocked":
        return fail("an authorized connection from another company must not pass current-company evidence")

    current_connection = [
        {
            "connection_id": CONNECTION_ID,
            "company_id": COMPANY_ID,
            "store_id": STORE_ID,
            "platform": "ebay",
            "connection_type": "oauth",
            "status": "read_only_authorized",
            "secret_ref": "vault-secret-ref-must-not-leak",
            "metadata": {
                "credential_source": "jiejing_vault_secret_ref",
                "account_deletion_identity_mapping_status": "identity_mapping_ready",
            },
        }
    ]
    wrong_store_packets = [
        {
            **data_packets[0],
            "store_id": "wrong-store-sentinel",
        }
    ]
    completed, _requests = run_checker(
        account_health=account_health,
        connections=current_connection,
        data_packets=wrong_store_packets,
    )
    payload = json.loads(completed.stdout)
    phases = {item.get("key"): item for item in payload.get("phases", []) if isinstance(item, dict)}
    if (phases.get("official_packet_account_health_snapshot") or {}).get("status") != "blocked":
        return fail("an official packet from another store must not pass current-store evidence")

    frozen_health = {
        **account_health,
        "status": "suspended",
        "incident_mode": True,
        "can_execute_real_writes": False,
    }
    completed, _requests = run_checker(
        account_health=frozen_health,
        connections=current_connection,
        data_packets=data_packets,
    )
    payload = json.loads(completed.stdout)
    phases = {item.get("key"): item for item in payload.get("phases", []) if isinstance(item, dict)}
    if (phases.get("official_packet_account_health_snapshot") or {}).get("status") != "blocked":
        return fail("a frozen/suspended account-health snapshot must remain blocked")

    suspended_but_write_flags_safe = {
        **account_health,
        "status": "suspended",
        "incident_mode": False,
        "can_execute_real_writes": True,
    }
    completed, _requests = run_checker(
        account_health=suspended_but_write_flags_safe,
        connections=current_connection,
        data_packets=data_packets,
    )
    payload = json.loads(completed.stdout)
    phases = {item.get("key"): item for item in payload.get("phases", []) if isinstance(item, dict)}
    if (phases.get("official_packet_account_health_snapshot") or {}).get("status") != "blocked":
        return fail("suspended account health must be rejected even when the write-safety booleans look safe")

    missing_safety_fields_health = {
        "company_id": COMPANY_ID,
        "store_id": STORE_ID,
        "platform": "ebay",
        "status": "normal",
        "evidence_package": account_health["evidence_package"],
    }
    completed, _requests = run_checker(
        account_health=missing_safety_fields_health,
        connections=current_connection,
        data_packets=data_packets,
    )
    payload = json.loads(completed.stdout)
    phases = {item.get("key"): item for item in payload.get("phases", []) if isinstance(item, dict)}
    if (phases.get("official_packet_account_health_snapshot") or {}).get("status") != "blocked":
        return fail("account health with missing incident/write safety fields must fail closed")

    completed, requests = run_checker(
        account_health=account_health,
        connections=current_connection,
        data_packets=data_packets,
        oauth_flags_enabled=False,
    )
    payload = json.loads(completed.stdout)
    phases = {item.get("key"): item for item in payload.get("phases", []) if isinstance(item, dict)}
    if (phases.get("official_packet_account_health_snapshot") or {}).get("status") != "blocked":
        return fail("caller-supplied official_api packet and generic connection metadata must not prove backend provenance")
    if (phases.get("new_account_oauth_authorization_gate") or {}).get("status") != "blocked":
        return fail("merchant-writable generic connection status must not satisfy the OAuth phase")
    next_actions = " ".join(str(item) for item in payload.get("next_actions") or []).lower()
    if "only when this exact step has explicit owner approval" not in next_actions:
        return fail("unproven OAuth evidence must keep any new plan behind exact-step approval")

    now = datetime.now(timezone.utc).isoformat()
    trusted_packet = {
        **data_packets[0],
        "created_at": now,
        "packet": {
            **data_packets[0]["packet"],
            "company_id": COMPANY_ID,
            "store_id": STORE_ID,
            "platform": "ebay",
            "source_mode": "official_api",
            "source_label": "official_api",
            "freshness": {
                "snapshot_created_at": now,
                "stale_after_seconds": 21600,
                "official_request_count": 5,
                "route_success_count": 5,
                "route_failure_count": 0,
            },
            "lineage": {
                "probe_live_read_performed": True,
                "access_token_used": True,
                "access_token_returned_to_frontend": False,
                "raw_ebay_response_stored": False,
            },
        },
    }
    trusted_job_id = "worker-job-current-sentinel"
    trusted_queue_jobs = [
        {
            "job_id": trusted_job_id,
            "company_id": COMPANY_ID,
            "status": "completed",
            "updated_at": now,
            "job": {
                "kind": "ebay_read_only_live_plan",
                "store_id": STORE_ID,
                "live_read_plan": {
                    "token_boundary": {"connection_id": current_connection[0]["connection_id"]}
                },
                "updates": [
                    {
                        "created_at": now,
                        "live_read_performed": True,
                        "request_count": 5,
                        "data_packet_id": packet_id,
                    }
                ],
            },
        }
    ]
    trusted_audits = [
        {
            "company_id": COMPANY_ID,
            "store_id": STORE_ID,
            "actor_type": "system",
            "action_type": "ebay.read_only.live.completed",
            "target_type": "queue_job",
            "target_id": trusted_job_id,
            "created_at": now,
            "details": {
                "request_count": 5,
                "data_packet_id": packet_id,
                "raw_response_stored": False,
            },
        }
    ]
    generic_first_connections = [
        {
            "connection_id": "generic-stale-connection-sentinel",
            "company_id": COMPANY_ID,
            "store_id": STORE_ID,
            "platform": "ebay",
            "connection_type": "oauth",
            "status": "read_only_authorized",
            "secret_ref": "generic-secret-ref-must-not-leak",
            "metadata": {},
        },
        current_connection[0],
    ]
    completed, _requests = run_checker(
        account_health=account_health,
        connections=generic_first_connections,
        data_packets=[trusted_packet],
        queue_jobs=trusted_queue_jobs,
        audit_logs=trusted_audits,
        oauth_status=STRONG_OAUTH_STATUS,
        oauth_flags_enabled=False,
    )
    dual_connection_payload = json.loads(completed.stdout)
    dual_connection_phases = {
        item.get("key"): item
        for item in dual_connection_payload.get("phases", [])
        if isinstance(item, dict)
    }
    if (dual_connection_phases.get("new_account_oauth_authorization_gate") or {}).get("status") != "ready":
        return fail("checker must match the status connection hash before validating connection metadata")

    completed, trusted_requests = run_checker(
        account_health=account_health,
        connections=current_connection,
        data_packets=[trusted_packet],
        queue_jobs=trusted_queue_jobs,
        audit_logs=trusted_audits,
        oauth_status=STRONG_OAUTH_STATUS,
        oauth_flags_enabled=False,
    )
    trusted_payload = json.loads(completed.stdout)
    trusted_phases = {
        item.get("key"): item
        for item in trusted_payload.get("phases", [])
        if isinstance(item, dict)
    }
    if (trusted_phases.get("official_packet_account_health_snapshot") or {}).get("status") != "ready":
        return fail("backend worker queue-job and system-audit provenance should pass when fully bound and fresh")
    if (trusted_phases.get("new_account_oauth_authorization_gate") or {}).get("status") != "ready":
        return fail("backend-proven current-store OAuth identity should satisfy OAuth without environment flags")
    for phase_key in (
        "publish_health_confirmation_gate",
        "controlled_real_publish_probe",
        "post_publish_cockpit_cleanup_gate",
    ):
        if (trusted_phases.get(phase_key) or {}).get("status") != "blocked":
            return fail(f"global/env evidence must not satisfy current-store action phase: {phase_key}")
    trusted_next_actions = " ".join(str(item) for item in trusted_payload.get("next_actions") or []).lower()
    if "do not create a new oauth plan" not in trusted_next_actions or "do not repeat oauth" not in trusted_next_actions:
        return fail("strong authorized current-store output must forbid a new plan and repeated OAuth")

    for unsafe_count in (True, 5.0, float("nan"), float("inf"), "5"):
        unsafe_count_packet = {
            **trusted_packet,
            "packet": {
                **trusted_packet["packet"],
                "freshness": {
                    **trusted_packet["packet"]["freshness"],
                    "official_request_count": unsafe_count,
                },
            },
        }
        completed, _requests = run_checker(
            account_health=account_health,
            connections=current_connection,
            data_packets=[unsafe_count_packet],
            queue_jobs=trusted_queue_jobs,
            audit_logs=trusted_audits,
            oauth_status=STRONG_OAUTH_STATUS,
            oauth_flags_enabled=False,
        )
        try:
            unsafe_count_payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return fail("malformed positive counts must return stable JSON without a traceback")
        unsafe_count_phases = {
            item.get("key"): item
            for item in unsafe_count_payload.get("phases", [])
            if isinstance(item, dict)
        }
        if (unsafe_count_phases.get("official_packet_account_health_snapshot") or {}).get("status") != "blocked":
            return fail("only genuine JSON integers may satisfy positive official request counts")
        if "traceback" in completed.stderr.lower():
            return fail("malformed positive counts must fail closed without a traceback")

    completed, _requests = run_checker(
        account_health=account_health,
        connections=current_connection,
        data_packets=[trusted_packet],
        queue_jobs=trusted_queue_jobs,
        audit_logs=trusted_audits,
        oauth_status={**STRONG_OAUTH_STATUS, "connection_id_sha256": "wrong-connection-binding"},
        oauth_flags_enabled=False,
    )
    wrong_binding_payload = json.loads(completed.stdout)
    wrong_binding_phases = {item.get("key"): item for item in wrong_binding_payload.get("phases", []) if isinstance(item, dict)}
    if (wrong_binding_phases.get("new_account_oauth_authorization_gate") or {}).get("status") != "blocked":
        return fail("backend OAuth status must bind the exact current-store connection identity")

    stale_time = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    stale_self_reported_packet = {
        **trusted_packet,
        "created_at": stale_time,
        "packet": {
            **trusted_packet["packet"],
            "freshness": {
                **trusted_packet["packet"]["freshness"],
                "snapshot_created_at": stale_time,
                "stale_after_seconds": 365 * 24 * 60 * 60,
            },
        },
    }
    stale_jobs = [{**trusted_queue_jobs[0], "updated_at": stale_time, "job": {**trusted_queue_jobs[0]["job"], "updates": [{**trusted_queue_jobs[0]["job"]["updates"][0], "created_at": stale_time}]}}]
    stale_audits = [{**trusted_audits[0], "created_at": stale_time}]
    completed, _requests = run_checker(
        account_health=account_health,
        connections=current_connection,
        data_packets=[stale_self_reported_packet],
        queue_jobs=stale_jobs,
        audit_logs=stale_audits,
        oauth_status=STRONG_OAUTH_STATUS,
        oauth_flags_enabled=False,
    )
    stale_payload = json.loads(completed.stdout)
    stale_phases = {item.get("key"): item for item in stale_payload.get("phases", []) if isinstance(item, dict)}
    if (stale_phases.get("official_packet_account_health_snapshot") or {}).get("status") != "blocked":
        return fail("packet freshness must use a fixed maximum age instead of trusting packet-reported TTL")

    blank_id_jobs = [{**trusted_queue_jobs[0], "job_id": ""}]
    blank_id_audits = [{**trusted_audits[0], "target_id": ""}]
    completed, _requests = run_checker(
        account_health=account_health,
        connections=current_connection,
        data_packets=[trusted_packet],
        queue_jobs=blank_id_jobs,
        audit_logs=blank_id_audits,
        oauth_status=STRONG_OAUTH_STATUS,
        oauth_flags_enabled=False,
    )
    blank_id_payload = json.loads(completed.stdout)
    blank_id_phases = {item.get("key"): item for item in blank_id_payload.get("phases", []) if isinstance(item, dict)}
    if (blank_id_phases.get("official_packet_account_health_snapshot") or {}).get("status") != "blocked":
        return fail("blank queue job and audit target IDs must never satisfy provenance")

    zero_request_jobs = [
        {
            **trusted_queue_jobs[0],
            "job": {
                **trusted_queue_jobs[0]["job"],
                "updates": [{**trusted_queue_jobs[0]["job"]["updates"][0], "request_count": 0}],
            },
        }
    ]
    completed, _requests = run_checker(
        account_health=account_health,
        connections=current_connection,
        data_packets=[trusted_packet],
        queue_jobs=zero_request_jobs,
        audit_logs=trusted_audits,
        oauth_status=STRONG_OAUTH_STATUS,
        oauth_flags_enabled=False,
    )
    zero_request_payload = json.loads(completed.stdout)
    zero_request_phases = {item.get("key"): item for item in zero_request_payload.get("phases", []) if isinstance(item, dict)}
    if (zero_request_phases.get("official_packet_account_health_snapshot") or {}).get("status") != "blocked":
        return fail("worker completion provenance must record a positive official request count")

    old_update_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    mistimed_jobs = [
        {
            **trusted_queue_jobs[0],
            "job": {
                **trusted_queue_jobs[0]["job"],
                "updates": [{**trusted_queue_jobs[0]["job"]["updates"][0], "created_at": old_update_time}],
            },
        }
    ]
    completed, _requests = run_checker(
        account_health=account_health,
        connections=current_connection,
        data_packets=[trusted_packet],
        queue_jobs=mistimed_jobs,
        audit_logs=trusted_audits,
        oauth_status=STRONG_OAUTH_STATUS,
        oauth_flags_enabled=False,
    )
    mistimed_payload = json.loads(completed.stdout)
    mistimed_phases = {item.get("key"): item for item in mistimed_payload.get("phases", []) if isinstance(item, dict)}
    if (mistimed_phases.get("official_packet_account_health_snapshot") or {}).get("status") != "blocked":
        return fail("worker completion timestamp must be reasonably close to packet and audit evidence")

    mismatched_packet_body = {
        **trusted_packet,
        "packet": {**trusted_packet["packet"], "store_id": "wrong-store-inside-packet-sentinel"},
    }
    completed, _requests = run_checker(
        account_health=account_health,
        connections=current_connection,
        data_packets=[mismatched_packet_body],
        queue_jobs=trusted_queue_jobs,
        audit_logs=trusted_audits,
        oauth_flags_enabled=False,
    )
    mismatched_payload = json.loads(completed.stdout)
    mismatched_phases = {
        item.get("key"): item
        for item in mismatched_payload.get("phases", [])
        if isinstance(item, dict)
    }
    if (mismatched_phases.get("official_packet_account_health_snapshot") or {}).get("status") != "blocked":
        return fail("packet body tenant/store identity must match the authenticated packet record")
    if any("read-only-plan" in path or method != "GET" for method, path, _authenticated in trusted_requests):
        return fail("trusted existing evidence must remain read-only and must not create a new OAuth plan")
    if any("read-only-plan" in path or method != "GET" for method, path, _authenticated in requests):
        return fail("completed OAuth evidence must not create a new OAuth plan or issue non-GET requests")
    readiness_auth_modes = {
        authenticated
        for method, path, authenticated in requests
        if method == "GET" and path == "/readiness/product-saas"
    }
    if readiness_auth_modes != {False, True}:
        return fail("checker must distinguish public readiness from authenticated readiness evidence")
    for forbidden in [
        "test-token-must-not-leak",
        COMPANY_ID,
        STORE_ID,
        packet_id,
        "vault-secret-ref-must-not-leak",
        "seller-private-value-must-not-leak",
        trusted_job_id,
        current_connection[0]["connection_id"],
    ]:
        if forbidden in completed.stdout:
            return fail(f"checker output leaked a tenant, store, packet, secret-ref or merchant value sentinel: {forbidden}")
    print("PASS jiejing_new_ebay_account_evidence_scope")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

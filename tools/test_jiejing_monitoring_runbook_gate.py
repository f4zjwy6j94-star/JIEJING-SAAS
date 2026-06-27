#!/usr/bin/env python3
"""Regression for monitoring, alerting, and incident runbook launch gates."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.monitoring import build_monitoring_status  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-monitoring-runbook-gate-test"
ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_SAAS_SESSION_SECRET",
    "JIEJING_CLS_ENABLED",
    "JIEJING_CLS_REGION",
    "JIEJING_CLS_LOGSET_ID",
    "JIEJING_CLS_TOPIC_ID",
    "JIEJING_CLS_ALERT_POLICY_CONFIGURED",
    "JIEJING_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED",
    "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
    "JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED",
    "JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_CLOUD_BILLING_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    db_path = OUT / "monitoring-runbook.sqlite"
    db_path.unlink(missing_ok=True)
    try:
        _clear_env()
        os.environ.update(
            {
                "JIEJING_SAAS_ENV": "staging",
                "JIEJING_SAAS_SESSION_SECRET": "staging-monitoring-runbook-secret-long-enough",
                "JIEJING_CLS_ENABLED": "true",
                "JIEJING_CLS_REGION": "ap-guangzhou",
                "JIEJING_CLS_LOGSET_ID": "logset-jiejing",
                "JIEJING_CLS_TOPIC_ID": "topic-saas-backend",
                "JIEJING_CLS_ALERT_POLICY_CONFIGURED": "true",
            }
        )
        settings = _settings(db_path)
        repo = SaaSRepository(settings.db_path, database_engine="sqlite")
        repo.initialize()
        blocked = build_monitoring_status(settings, repo)
        runbook_blockers = blocked.get("incident_runbooks", {}).get("blocked_by", [])
        if "incident_runbook_published" not in runbook_blockers or "oncall_alert_route_configured" not in runbook_blockers:
            return fail(f"production-like monitoring must block without published runbooks and alert route: {runbook_blockers}")
        if blocked.get("production_monitoring_ready") is not False:
            return fail("monitoring must not be production-ready before runbook evidence exists")

        os.environ.update(
            {
                "JIEJING_INCIDENT_RUNBOOK_PUBLISHED": "true",
                "JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED": "true",
                "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED": "true",
                "JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED": "true",
                "JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED": "true",
                "JIEJING_CLOUD_BILLING_INCIDENT_RUNBOOK_PUBLISHED": "true",
                "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED": "true",
            }
        )
        ready = build_monitoring_status(settings, repo)
        if ready.get("production_monitoring_ready") is not True:
            return fail(f"monitoring should be ready with CLS and runbook evidence: {ready.get('current_blockers')}")
        alert_keys = {item.get("key") for item in ready.get("alert_contracts", []) if isinstance(item, dict)}
        for key in {
            "billing_webhook_failure",
            "platform_write_failure",
            "backup_restore_drill_overdue",
            "cloud_billing_or_resource_suspension",
            "database_endpoint_or_dns_unreachable",
        }:
            if key not in alert_keys:
                return fail(f"missing paid-launch alert contract: {key}")
        runbook_dump = json.dumps(ready.get("incident_runbooks", {}), ensure_ascii=False)
        for required in ("cloud billing arrears", "managed database endpoint"):
            if required not in runbook_dump:
                return fail(f"runbook coverage should mention {required}: {runbook_dump}")
        dumped = json.dumps(ready, ensure_ascii=False)
        for forbidden in ("access_token", "refresh_token", "client_secret", "password"):
            if forbidden in dumped:
                return fail(f"monitoring status leaked forbidden marker: {forbidden}")
        print("PASS jiejing_monitoring_runbook_gate")
        return 0
    finally:
        _restore_env(previous)


def _settings(db_path: Path) -> SaaSSettings:
    return SaaSSettings.from_env(
        db_path=db_path,
        runtime_db_path=OUT / "runtime.sqlite",
        output_root=OUT,
        host="127.0.0.1",
        port=8788,
    )


def _clear_env() -> None:
    for key in ENV_KEYS:
        os.environ.pop(key, None)


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())

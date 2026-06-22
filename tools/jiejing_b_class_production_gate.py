#!/usr/bin/env python3
"""Unattended B-class productionization gate for Jiejing SaaS.

This gate checks production-readiness contracts that can be completed without
operator clicks, paid cloud provisioning, DNS changes, eBay OAuth repeats, or
real platform writes.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-b-class-production-gate"

CHECKS: list[tuple[str, list[str], str]] = [
    (
        "b_class_modules_compile",
        [
            sys.executable,
            "-m",
            "py_compile",
            "jiejing_saas/backup_plan.py",
            "jiejing_saas/billing_plan.py",
            "jiejing_saas/model_value_gate.py",
            "jiejing_saas/readiness.py",
            "jiejing_saas/api_server.py",
        ],
        "contracts",
    ),
    ("backend_contracts", [sys.executable, "tools/test_jiejing_saas_backend_mvp.py"], "api"),
    ("driver_contracts", [sys.executable, "tools/test_jiejing_infrastructure_drivers.py"], "infra"),
    ("infrastructure_stage_gate", [sys.executable, "tools/jiejing_infrastructure_stage_gate.py"], "infra"),
    ("precloud_deployment_gate", [sys.executable, "tools/jiejing_precloud_deployment_gate.py"], "deploy"),
    ("staging_patch_contract", [sys.executable, "tools/test_jiejing_staging_patch_apply_contract.py"], "deploy"),
]


def main() -> int:
    _configure_stdout()
    started = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    results = [_run_check(key, command, group) for key, command, group in CHECKS]
    groups = _group_summary(results)
    failed = [item for item in results if not item["pass"]]
    summary = {
        "product": "Jiejing SaaS",
        "gate": "b_class_productionization_gate",
        "status": "pass" if not failed else "failed",
        "scope": "B-class only: backup/restore, billing/quota, model value, Postgres/Redis cutover contracts, and staging deploy safety.",
        "checks": results,
        "groups": groups,
        "b_class_completion": _completion(groups),
        "still_requires_operator_or_paid_infra": [
            "provision_managed_postgres_and_run_restore_drill",
            "provision_redis_or_cloud_queue_and_run_live_probe",
            "configure_managed_vault_or_kms_for_production",
            "choose_billing_provider_and_publish_real_plan_ids",
            "approve_paid_live_model_provider_usage_and_quality_review",
            "configure_stable_domain_dns_and_icp_if_using_mainland_china",
        ],
        "real_platform_writes_enabled": False,
        "repeats_oauth": False,
        "secret_exposed": False,
        "elapsed_seconds": round(time.time() - started, 2),
    }
    output = OUT / "latest.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"OUTPUT={output}")
    return 0 if not failed else 1


def _configure_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")


def _run_check(key: str, command: list[str], group: str) -> dict[str, Any]:
    started = time.time()
    result = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, timeout=240, check=False)
    return {
        "key": key,
        "group": group,
        "pass": result.returncode == 0,
        "returncode": result.returncode,
        "command": command,
        "stdout_tail": "\n".join(result.stdout.splitlines()[-18:]),
        "stderr_tail": "\n".join(result.stderr.splitlines()[-12:]),
        "elapsed_seconds": round(time.time() - started, 2),
    }


def _group_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    for item in results:
        group = item["group"]
        groups.setdefault(group, {"total": 0, "passed": 0, "failed": []})
        groups[group]["total"] += 1
        if item["pass"]:
            groups[group]["passed"] += 1
        else:
            groups[group]["failed"].append(item["key"])
    for group in groups.values():
        group["pass"] = group["passed"] == group["total"]
    return groups


def _completion(groups: dict[str, Any]) -> dict[str, Any]:
    completed = sum(1 for item in groups.values() if item.get("pass"))
    total = len(groups)
    return {
        "completed_groups": completed,
        "total_groups": total,
        "percent": round((completed / total) * 100, 1) if total else 0.0,
    }


if __name__ == "__main__":
    raise SystemExit(main())

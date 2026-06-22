#!/usr/bin/env python3
"""Unattended C-class gate for Jiejing SaaS.

C-class starts the paid-SaaS path by proving production cutover readiness and
model-backed Agent value where this can be done without buying cloud resources,
changing DNS, repeating eBay OAuth, or enabling real platform writes.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-c-class-production-gate"

CHECKS: list[tuple[str, list[str], str]] = [
    (
        "c_class_modules_compile",
        [
            sys.executable,
            "-m",
            "py_compile",
            "jiejing_saas/commercial_launch_gate.py",
            "jiejing_saas/model_value_rehearsal.py",
            "jiejing_saas/model_value_gate.py",
            "jiejing_saas/api_server.py",
        ],
        "contracts",
    ),
    ("model_value_rehearsal", [sys.executable, "tools/test_jiejing_model_value_rehearsal.py"], "agent_value"),
    ("backend_contracts", [sys.executable, "tools/test_jiejing_saas_backend_mvp.py"], "api"),
    ("b_class_regression", [sys.executable, "tools/jiejing_b_class_production_gate.py"], "regression"),
    ("precloud_deployment_gate", [sys.executable, "tools/jiejing_precloud_deployment_gate.py"], "deploy"),
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
        "gate": "c_class_production_gate",
        "status": "pass" if not failed else "failed",
        "scope": "C-class unattended: commercial launch gate, model-backed Agent value rehearsal, and AB regression without paid cloud mutation.",
        "checks": results,
        "groups": groups,
        "c_class_unattended_completion": _completion(groups),
        "still_requires_operator_or_paid_infra": [
            "provision_managed_postgres_and_run_live_cutover_probe",
            "provision_redis_or_cloud_queue_and_run_worker_probe",
            "configure_managed_vault_or_kms_with_restore_policy",
            "choose_billing_provider_publish_plan_ids_and_configure_webhook",
            "approve_real_live_model_provider_usage_and_quality_sampling",
            "configure_stable_domain_dns_tls_and_icp_if_using_mainland_china",
        ],
        "repeats_oauth": False,
        "real_platform_writes_enabled": False,
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
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=360,
        check=False,
    )
    return {
        "key": key,
        "group": group,
        "pass": completed.returncode == 0,
        "returncode": completed.returncode,
        "command": command,
        "stdout_tail": "\n".join(completed.stdout.splitlines()[-18:]),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-12:]),
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

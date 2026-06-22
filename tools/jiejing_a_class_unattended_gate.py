#!/usr/bin/env python3
"""Unattended A-class gate for Jiejing SaaS.

Runs only checks and rehearsals that do not need the operator to touch the
browser, pay for cloud resources, scan QR codes, or approve eBay OAuth.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-a-class-unattended-gate"


CHECKS: list[tuple[str, list[str], str]] = [
    ("frontend_js_syntax", ["node", "--check", "app.js"], "frontend"),
    ("current_state_guard", [sys.executable, "tools/test_jiejing_current_state_guard.py"], "state_guard"),
    ("frontend_real_workbench_guard", [sys.executable, "tools/test_jiejing_frontend_staging_config.py"], "frontend"),
    ("oauth_prepare_idempotency", [sys.executable, "tools/test_jiejing_staging_ebay_oauth_flow_tool.py"], "state_guard"),
    ("ebay_live_read_packet_contract", [sys.executable, "tools/test_jiejing_ebay_live_read_http_client.py"], "ebay_packet"),
    ("saas_backend_real_results_contract", [sys.executable, "tools/test_jiejing_saas_backend_mvp.py"], "workbench_results"),
    ("agent_model_assist_contract", [sys.executable, "tools/test_jiejing_agent_model_assist.py"], "agents"),
    ("provider_jobs_contract", [sys.executable, "tools/test_jiejing_saas_provider_jobs.py"], "provider_jobs"),
    ("public_search_provider_contract", [sys.executable, "tools/test_jiejing_public_search_provider_job.py"], "provider_jobs"),
    ("infra_cutover_rehearsal", [sys.executable, "tools/test_jiejing_infra_cutover_rehearsal.py"], "infra_rehearsal"),
    ("infrastructure_stage_gate", [sys.executable, "tools/jiejing_infrastructure_stage_gate.py"], "infra_rehearsal"),
]


def main() -> int:
    started = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    results = [_run_check(key, command, group) for key, command, group in CHECKS]
    groups = _group_summary(results)
    failed = [item for item in results if not item["pass"]]
    current_state = _current_state()
    summary = {
        "product": "Jiejing SaaS",
        "gate": "a_class_unattended_gate",
        "status": "pass" if not failed else "failed",
        "scope": "A-class only: no browser handoff, no cloud payment, no eBay OAuth approval, no live infra mutation.",
        "checks": results,
        "groups": groups,
        "current_state": current_state,
        "a_class_completion": _a_class_completion(groups),
        "still_requires_operator": [
            "buy_or_provision_managed_postgres_redis_vault_kms",
            "configure_stable_domain_dns_icp_if_using_mainland_china",
            "approve_paid_model_and_search_media_provider_quotas",
            "set_pricing_plans_and_billing_provider",
            "approve_any_future_real_platform_write_scope",
        ],
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
        "elapsed_seconds": round(time.time() - started, 2),
    }
    output = OUT / "latest.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"OUTPUT={output}")
    return 0 if not failed else 1


def _run_check(key: str, command: list[str], group: str) -> dict[str, Any]:
    started = time.time()
    result = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, timeout=180, check=False)
    stdout_tail = "\n".join(result.stdout.splitlines()[-14:])
    stderr_tail = "\n".join(result.stderr.splitlines()[-10:])
    return {
        "key": key,
        "group": group,
        "pass": result.returncode == 0,
        "returncode": result.returncode,
        "command": command,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
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


def _a_class_completion(groups: dict[str, Any]) -> dict[str, Any]:
    completed = sum(1 for item in groups.values() if item.get("pass"))
    total = len(groups)
    return {
        "completed_groups": completed,
        "total_groups": total,
        "percent": round((completed / total) * 100, 1) if total else 0.0,
    }


def _current_state() -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "tools/jiejing_current_state_guard.py", "--json"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return {"status": "unavailable", "stderr_tail": result.stderr[-500:]}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "invalid_json"}
    return {
        "status": data.get("status"),
        "callback_completed": data.get("callback_completed"),
        "sync_completed": data.get("sync_completed"),
        "official_packet": data.get("official_packet"),
        "data_packet_id": data.get("data_packet_id"),
        "missing_resource_keys": data.get("missing_resource_keys"),
        "deploy_channel_ready": data.get("deploy_channel_ready"),
        "no_repeat_actions": data.get("no_repeat_actions"),
    }


if __name__ == "__main__":
    raise SystemExit(main())

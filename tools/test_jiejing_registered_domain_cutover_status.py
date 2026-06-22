#!/usr/bin/env python3
"""Regression for registered-domain DNS/WAF cutover status."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "jiejing_registered_domain_cutover_status.py"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    tool_text = TOOL.read_text(encoding="utf-8")
    for marker in (
        "cloudflare-dns.com/dns-query",
        "dns.google/resolve",
        "application/dns-json",
        "_probe_robots_txt",
        "_probe_scanner_block_rule",
        "_probe_scripted_expensive_api_challenge",
        "_probe_backend_expensive_api_rate_limit",
        "_probe_root_redirect",
        "_probe_direct_origin",
        "_probe_cors",
        "root_bare_domain_redirect_ready",
        "managed_robots_ai_crawler_control_ready",
        "scanner_path_block_rule_ready",
        "scripted_expensive_api_challenge_ready",
        "backend_expensive_api_rate_limit_ready",
        "cloudflare_free_waf_baseline_ready",
        "origin_direct_lock_ready",
        "cors_stable_origin_ready",
    ):
        if marker not in tool_text:
            return fail(f"registered-domain tool should use DNS-over-HTTPS marker: {marker}")

    placeholder = _run("--root-ip-fixture", "198.18.0.20", "--app-ip-fixture", "198.18.0.21", "--skip-https-probe")
    if placeholder.get("domain_registered") is not True:
        return fail("registered fixture should mark the domain as registered")
    if placeholder.get("app_dns", {}).get("status") != "placeholder_dns":
        return fail(f"198.18 app fixture should be placeholder DNS: {placeholder.get('app_dns')}")
    if placeholder.get("root_dns", {}).get("status") != "placeholder_dns":
        return fail(f"198.18 root fixture should be placeholder DNS: {placeholder.get('root_dns')}")
    if placeholder.get("safe_to_update_ebay_callback_now") is not False:
        return fail("placeholder DNS must not allow eBay callback cutover")
    if "app_dns_placeholder_or_benchmark_range" not in placeholder.get("blocked_reasons", []):
        return fail(f"placeholder blocker missing: {placeholder.get('blocked_reasons')}")
    if "root_dns_placeholder_or_benchmark_range" not in placeholder.get("blocked_reasons", []):
        return fail(f"root placeholder blocker missing: {placeholder.get('blocked_reasons')}")
    if "scanner_path_block_rule_not_verified" not in placeholder.get("blocked_reasons", []):
        return fail("skipped scanner probe should stay blocked without evidence")
    if "auth_rate_limit_rule_not_verified" not in placeholder.get("blocked_reasons", []):
        return fail("auth rate-limit console evidence should be required")
    if placeholder.get("triggers_real_charge") is not False or placeholder.get("triggers_ebay_oauth") is not False:
        return fail("domain cutover status must remain no-charge and no-OAuth")

    direct = _run("--root-ip-fixture", "203.0.113.10", "--app-ip-fixture", "43.129.205.244", "--skip-https-probe")
    if direct.get("app_dns", {}).get("status") != "direct_origin_dns":
        return fail(f"origin fixture should be detected as direct origin DNS: {direct.get('app_dns')}")
    if "app_dns_points_to_origin_without_confirmed_proxy" not in direct.get("blocked_reasons", []):
        return fail("direct-origin DNS should stay blocked before WAF proxy evidence")

    edge = _run("--root-ip-fixture", "104.16.10.10", "--app-ip-fixture", "104.16.10.11", "--skip-https-probe")
    if edge.get("app_dns", {}).get("status") != "public_edge_or_unknown_dns":
        return fail(f"public edge fixture should be classed as public edge/unknown: {edge.get('app_dns')}")
    if "stable_https_health_not_ready" not in edge.get("blocked_reasons", []):
        return fail("skipped HTTPS probe should keep stable HTTPS blocked")

    serialized = json.dumps([placeholder, direct, edge], ensure_ascii=False).lower()
    for forbidden in ("refresh_token=", "client_secret=", "api_key=", "sk_live_", "whsec_"):
        if forbidden in serialized:
            return fail(f"registered-domain packet leaked forbidden marker: {forbidden}")

    print("PASS jiejing_registered_domain_cutover_status")
    return 0


def _run(*args: str) -> dict[str, object]:
    output = subprocess.check_output(
        [
            sys.executable,
            str(TOOL),
            "--domain",
            "jiejing.shop",
            "--registration-status",
            "registered",
            "--provider",
            "cloudflare",
            "--skip-robots-probe",
            "--skip-scanner-block-probe",
            "--skip-scripted-challenge-probe",
            "--skip-backend-rate-limit-probe",
            "--skip-root-redirect-probe",
            "--skip-origin-direct-probe",
            "--skip-cors-probe",
            *args,
        ],
        cwd=ROOT,
        text=True,
    )
    return json.loads(output).get("registered_domain_cutover_status") or {}


if __name__ == "__main__":
    raise SystemExit(main())

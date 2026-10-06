#!/usr/bin/env python3
"""Validate repository-level Codex/agent instructions preserve JIEJING boundaries."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
RUNBOOK = ROOT / "docs" / "JIEJING_GITHUB_SELF_HOSTED_RUNNER_DEPLOY_RUNBOOK_20260622.md"
PREPARE_BUNDLE = ROOT / "tools" / "jiejing_prepare_public_staging_bundle.py"
PATCH_SCRIPT = ROOT / "deploy" / "apply-staging-patch.sh"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if not AGENTS.exists():
        return fail("AGENTS.md missing")
    text = AGENTS.read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8") if RUNBOOK.exists() else ""
    prepare_bundle = PREPARE_BUNDLE.read_text(encoding="utf-8") if PREPARE_BUNDLE.exists() else ""
    patch_script = PATCH_SCRIPT.read_text(encoding="utf-8") if PATCH_SCRIPT.exists() else ""

    required = [
        "JIEJING is an eBay-first AI CEO SaaS",
        "Do not reframe it as a generic ERP",
        "https://app.jiejing.shop/health",
        "https://app.jiejing.shop/health/deep",
        "https://app.jiejing.shop/readiness/product-saas",
        "Do not run or repeat eBay OAuth",
        "Historical eBay account restrictions are not current proof",
        "Inspect the specific account's current status when relevant",
        "Do not run Stripe live payment cutover",
        "Do not read, print, commit, or write secrets",
        "Never use `git credential fill`",
        "Run `Jiejing Staging Runner Doctor`",
        "Run `Jiejing Staging Manual Deploy` in `dry_run` first",
        "Use `Jiejing Staging Manual Rollback` dry-run",
        "Do not use `docker compose down -v`",
        "python tools/jiejing_secret_scan.py",
        "node --check app.js",
        "python tools/jiejing_precloud_deployment_gate.py",
        "Report launch flags as calculated from current evidence",
        "do not hardcode a desired true or false value into the report",
        "docs/JIEJING_CURRENT_EXECUTION_STATE.md",
        "dated handoffs are historical evidence, not automatic next-step instructions",
        "Code review, local test success, production health, paid availability, and real eBay execution are distinct evidence",
        "Proactive Principal Audit",
        "Do not wait for the operator to ask for an audit",
        "SaaS product fit",
        "beginner merchant UX",
        "merchant-facing copy quality",
        "Professional Prompt Auto-Trigger",
        "docs/JIEJING_PROFESSIONAL_PROMPT_PLAYBOOK_20260628.md",
        "Trigger the relevant prompts autonomously",
        "AI CEO Routing Review",
        "Listing Expert Review",
        "Billing And Pricing Review",
        "Tenant Isolation Audit",
        "Reliability And Launch Readiness Review",
        "do not grant permission to bypass confirmation gates",
    ]
    missing = [marker for marker in required if marker not in text]
    if missing:
        return fail("AGENTS.md missing markers: " + ",".join(missing))

    integration_missing = []
    for marker, content, label in [
        ("AGENTS.md", runbook, "runbook"),
        ('"AGENTS.md"', patch_script, "patch_script"),
        ("public_staging_patch_whitelist_v1", prepare_bundle, "bundle_scope"),
        ("_apply_patch_file_list", prepare_bundle, "bundle_whitelist_reader"),
    ]:
        if marker not in content:
            integration_missing.append(label)
    if integration_missing:
        return fail("AGENTS.md not wired into: " + ",".join(integration_missing))

    forbidden = [
        "The old eBay account is frozen",
        "ready_for_paid_commercial_launch=false",
        "JIEJING_EBAY_REFRESH_TOKEN=",
        "STRIPE_SECRET_KEY=",
        "OPENAI_API_KEY=",
        "sk-",
        "ghp_",
        "github_pat_",
        "docker compose down -v\n",
        "docker volume rm\n",
        "git reset --hard\n",
        "这是主理人内部面板",
    ]
    present = [marker for marker in forbidden if marker in text]
    if present:
        return fail("AGENTS.md contains forbidden marker: " + ",".join(present))

    print("PASS jiejing_agents_md_guardrails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

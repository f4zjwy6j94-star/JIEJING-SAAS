#!/usr/bin/env python3
"""Validate local-first Codex and cloud fallback rules stay explicit and safe."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "JIEJING_LOCAL_FIRST_CLOUD_FALLBACK_RUNBOOK_20260622.md"
WORKFLOW = ROOT / ".github" / "workflows" / "jiejing-cloud-fallback-self-check.yml"
AGENTS = ROOT / "AGENTS.md"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def main() -> int:
    try:
        runbook = read(RUNBOOK)
        workflow = read(WORKFLOW)
        agents = read(AGENTS)
    except FileNotFoundError as exc:
        return fail(f"missing local-first cloud fallback file: {exc}")

    required_runbook = [
        "Local Windows Codex remains the primary operating mode.",
        "Codex Cloud is a fallback route",
        "JIEJING-SAAS",
        "Jiejing Cloud Fallback Self Check",
        "Jiejing Staging Manual Deploy",
        "Jiejing Staging Runner Doctor",
        "Jiejing Staging Runner Maintenance",
        "apply to staging explicitly",
        "Do not repeat eBay OAuth.",
        "Do not store Stripe live keys, eBay refresh tokens, model keys, client secrets, or SSH private keys in GitHub.",
        "Current state remains beta/public-staging oriented, not paid commercial launch.",
    ]
    required_workflow = [
        "workflow_dispatch:",
        "permissions:",
        "contents: read",
        "concurrency:",
        "cancel-in-progress: false",
        "runs-on: ubuntu-latest",
        "JIEJING_ENABLE_REAL_PLATFORM_WRITES: \"0\"",
        "python tools/jiejing_secret_scan.py",
        "node --check app.js",
        "python tools/test_jiejing_local_first_cloud_fallback_guardrails.py",
        "python tools/test_jiejing_github_actions_deploy_guardrails.py",
        "python tools/test_jiejing_github_runner_doctor_guardrails.py",
        "python tools/test_jiejing_github_runner_maintenance_guardrails.py",
    ]
    required_agents = [
        "Local Windows Codex is the primary operating mode.",
        "Codex Cloud is a fallback route",
        "Jiejing Cloud Fallback Self Check",
        "Do not treat Codex Cloud as having local-only files, browser login state, or local secrets.",
    ]

    missing: list[str] = []
    for marker in required_runbook:
        if marker not in runbook:
            missing.append(f"runbook:{marker}")
    for marker in required_workflow:
        if marker not in workflow:
            missing.append(f"workflow:{marker}")
    for marker in required_agents:
        if marker not in agents:
            missing.append(f"agents:{marker}")
    if missing:
        return fail("local-first cloud fallback guardrail missing markers: " + ",".join(missing))

    forbidden_workflow = [
        "schedule:",
        "pull_request_target",
        "deploy_mode:",
        "confirm_staging_deploy",
        "JIEJING_EBAY_ACCESS_TOKEN",
        "JIEJING_EBAY_REFRESH_TOKEN",
        "STRIPE_SECRET_KEY",
        "OPENAI_API_KEY",
        "git credential",
    ]
    forbidden_runbook = [
        "JIEJING_EBAY_REFRESH_TOKEN=",
        "STRIPE_SECRET_KEY=",
        "OPENAI_API_KEY=",
        "docker compose down -v\n",
        "docker volume rm\n",
        "DROP DATABASE",
    ]
    present: list[str] = []
    for marker in forbidden_workflow:
        if marker in workflow:
            present.append(f"workflow:{marker}")
    for marker in forbidden_runbook:
        if marker in runbook:
            present.append(f"runbook:{marker}")
    if present:
        return fail("local-first cloud fallback contains forbidden marker: " + ",".join(present))

    print("PASS jiejing_local_first_cloud_fallback_guardrails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

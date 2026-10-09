#!/usr/bin/env python3
"""Guard current two-endpoint continuity and the retained manual self-check.

The historical filename/workflow name is retained for existing callers. It must
not reinstate the superseded local-primary policy or widen deployment authority.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "JIEJING_LOCAL_FIRST_CLOUD_FALLBACK_RUNBOOK_20260622.md"
WORKFLOW = ROOT / ".github" / "workflows" / "jiejing-cloud-fallback-self-check.yml"
AGENTS = ROOT / "AGENTS.md"
WORK_SYNC = ROOT / "docs" / "continuity" / "11.0" / "WORK_SYNC.md"


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
        work_sync = read(WORK_SYNC)
    except FileNotFoundError as exc:
        return fail(f"missing continuity/manual-self-check file: {exc}")

    required_runbook = [
        "The old local-primary/cloud-fallback preference is superseded.",
        "docs/JIEJING_CURRENT_EXECUTION_STATE.md",
        "docs/continuity/11.0/WORK_SYNC.md",
        "video/jiejing-11-continuity-20261006",
        "Source/progress synchronization is not deployment authorization.",
        "Do not infer current launch status from this historical runbook.",
        "JIEJING-SAAS",
        "Jiejing Cloud Fallback Self Check",
        "Jiejing Staging Manual Deploy",
        "Jiejing Staging Runner Doctor",
        "Jiejing Staging Runner Maintenance",
        "apply to staging explicitly",
        "Do not repeat eBay OAuth.",
        "Do not store Stripe live keys, eBay refresh tokens, model keys, client secrets, or SSH private keys in GitHub.",
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
        "The earlier local-first/fallback preference has been superseded",
        "docs/continuity/11.0/WORK_SYNC.md",
        "video/jiejing-11-continuity-20261006",
        "Preserve dirty work, unexpected branches or divergence",
        "Never push main, force-push, dispatch deployment or upload private material as part of this workflow.",
        "It does not prove that the other endpoint has received it.",
        "Source/progress synchronization is not deployment authorization.",
        "Do not treat Codex Cloud as having local-only files, browser login state, or local secrets.",
    ]
    required_work_sync = [
        "docs/JIEJING_CURRENT_EXECUTION_STATE.md",
        "video/jiejing-11-continuity-20261006",
        "work_sync.py status --repo .",
        "work_sync.py receive --repo .",
        "work_sync.py save --repo .",
        "不会切换分支、stash、reset、clean",
        "不上传历史正文、图片/音视频/ZIP",
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
    for marker in required_work_sync:
        if marker not in work_sync:
            missing.append(f"work_sync:{marker}")
    if missing:
        return fail("continuity/manual-self-check guardrail missing markers: " + ",".join(missing))

    forbidden_workflow = [
        "schedule:",
        "pull_request_target",
        "contents: write",
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
    for marker in (
        "Local Windows Codex is the primary operating mode.",
        "Local Windows Codex remains the primary operating mode.",
        "Codex Cloud is a fallback route",
        "Current state remains beta/public-staging oriented, not paid commercial launch.",
    ):
        for label, content in (("agents", agents), ("runbook", runbook)):
            if marker in content:
                present.append(f"{label}:superseded_policy:{marker}")
    if present:
        return fail("local-first cloud fallback contains forbidden marker: " + ",".join(present))

    print("PASS jiejing_local_first_cloud_fallback_guardrails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

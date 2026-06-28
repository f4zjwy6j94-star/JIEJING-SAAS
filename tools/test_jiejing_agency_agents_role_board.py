#!/usr/bin/env python3
"""Validate the Agency Agents reference is absorbed behind JIEJING guardrails."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "JIEJING_AGENCY_AGENTS_ROLE_BOARD_20260628.md"
PLAYBOOK = ROOT / "docs" / "JIEJING_PROFESSIONAL_PROMPT_PLAYBOOK_20260628.md"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if not DOC.exists():
        return fail("role board document missing")
    if not PLAYBOOK.exists():
        return fail("professional prompt playbook missing")

    text = DOC.read_text(encoding="utf-8")
    playbook = PLAYBOOK.read_text(encoding="utf-8")
    required_markers = [
        "https://github.com/msitarzewski/agency-agents",
        "1189f0f9bc79a1883fee958fed627c6d11581eb7",
        "MIT",
        "do not install all external agents",
        "External role prompts are only reference material",
        "Do not repeat eBay OAuth",
        "confirmation center",
        "Product Owner",
        "Behavioral Nudge",
        "UX Researcher",
        "UI Designer",
        "Cross-Border E-Commerce",
        "Pricing Analyst",
        "AppSec Engineer",
        "Security Architect",
        "Data Privacy Officer",
        "Reality Checker",
        "Test Results Analyzer",
        "Accessibility Auditor",
        "Settings is the control room",
        "Tenant isolation audit",
        "Secret scan",
        "Public health, deep health, and product readiness verification",
    ]
    missing = [marker for marker in required_markers if marker not in text]
    if missing:
        return fail("role board missing markers: " + ",".join(missing))

    playbook_required_markers = [
        "JIEJING Professional Prompt Playbook",
        "Universal Safety Wrapper",
        "Product Owner Review",
        "AI CEO Routing Review",
        "Beginner UX Walkthrough",
        "UI Design Polish",
        "Listing Expert Review",
        "Billing And Pricing Review",
        "Security Threat Model",
        "Tenant Isolation Audit",
        "Customer Support And Order Reply Review",
        "Reliability And Launch Readiness Review",
        "Reality Checker",
        "Safe Growth And Public Page Review",
        "Owner Chief Of Staff Review",
        "Do not repeat eBay OAuth",
        "confirmation center",
        "Do not expose tokens",
        "do not grant permission to bypass confirmation gates",
    ]
    playbook_missing = [marker for marker in playbook_required_markers if marker not in playbook]
    if playbook_missing:
        return fail("prompt playbook missing markers: " + ",".join(playbook_missing))

    forbidden_markers = [
        "JIEJING_EBAY_REFRESH_TOKEN=",
        "STRIPE_SECRET_KEY=",
        "OPENAI_API_KEY=",
        "github_pat_",
        "ghp_",
        "sk-",
        "install.sh --tool codex",
        "./scripts/install.sh",
        "./scripts/convert.sh",
        "real eBay writes outside the confirmation center",
    ]
    combined = text + "\n" + playbook
    present = [marker for marker in forbidden_markers if marker in combined]
    if present:
        return fail("agency agent docs contain forbidden marker: " + ",".join(present))

    print("PASS jiejing_agency_agents_role_board")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

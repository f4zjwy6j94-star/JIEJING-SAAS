#!/usr/bin/env python3
"""Static deployment contract checks for first real eBay OAuth staging."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    compose = (ROOT / "deploy" / "docker-compose.oauth-staging.yml").read_text(encoding="utf-8")
    env_example = (ROOT / "deploy" / "jiejing-saas.staging-oauth.env.example").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "JIEJING_INDEPENDENT_SAAS_DEPLOYMENT_RUNBOOK.md").read_text(encoding="utf-8")

    if "jiejing-saas.staging-oauth.env" not in compose:
        return fail("oauth staging compose should use the private staging-oauth env file")
    if "postgres:" in compose or "redis:" in compose:
        return fail("oauth staging compose should not imply Postgres/Redis are wired for the first OAuth validation")
    if "JIEJING_VAULT_PROVIDER=vault" not in env_example:
        return fail("staging OAuth env example should use the implemented Vault resolver")
    if "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE=true" not in env_example:
        return fail("staging OAuth env example should enable live OAuth exchange")
    if "JIEJING_EBAY_REFRESH_TOKEN=" not in env_example:
        return fail("staging OAuth env example should explicitly keep env refresh token empty")
    if "JIEJING_ENABLE_HERMES_EBAY_BRIDGE=false" not in env_example:
        return fail("staging OAuth env example should keep Hermes bridge disabled")
    if "docker-compose.oauth-staging.yml" not in runbook:
        return fail("runbook should mention the OAuth staging compose profile")
    if "jiejing_staging_ebay_oauth_readonly_flow.py doctor" not in runbook:
        return fail("runbook should include the staging backend doctor before seller OAuth")
    if "not the final paid SaaS deployment" not in runbook:
        return fail("runbook should state that OAuth staging is not final paid SaaS deployment")
    print("PASS jiejing_oauth_staging_deploy_contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

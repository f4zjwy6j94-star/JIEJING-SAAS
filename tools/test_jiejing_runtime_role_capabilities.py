#!/usr/bin/env python3
"""Regression for Hermes-to-Jiejing Runtime role capability mapping."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import RuntimeRoleCapabilityMap

TEST_DB = ROOT / "output" / "jiejing-agent-runtime-samples" / "runtime-generated-workflows" / "role-capability-test.sqlite"


EXPECTED_ROLES = {
    "ceo",
    "market-manager",
    "product-manager",
    "customer-service",
    "finance-supply",
    "team-repair",
    "web-engineer",
    "desktop-engineer",
    "mobile-engineer",
}


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    role_map = RuntimeRoleCapabilityMap().to_dict()
    roles = role_map.get("roles", [])
    role_names = {role.get("role") for role in roles}
    if role_names != EXPECTED_ROLES:
        return fail(f"role set mismatch: {sorted(role_names)}")
    if role_map.get("summary", {}).get("role_count") != 9:
        return fail("role capability map should contain 9 Hermes/Jiejing roles")
    if role_map.get("merchant_model", "").find("Merchant faces AI CEO") < 0:
        return fail("merchant model should keep AI CEO as merchant-facing layer")
    market = next(role for role in roles if role.get("role") == "market-manager")
    if "market.data_packet" not in market.get("task_types", []):
        return fail("market-manager should own market.data_packet")
    if "live eBay probe" not in market.get("gaps", []):
        return fail("market-manager should expose live eBay probe gap")
    product = next(role for role in roles if role.get("role") == "product-manager")
    if not any("Do not publish" in item for item in product.get("safety_boundary", [])):
        return fail("product-manager must preserve publish safety boundary")

    result = validate_api()
    if result:
        return result

    print("PASS runtime_role_capability_regression")
    return 0


def validate_api() -> int:
    port = 8768
    command = [
        sys.executable,
        str(ROOT / "tools" / "jiejing_runtime_cli.py"),
        "serve",
        "--db",
        str(TEST_DB),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    process = subprocess.Popen(command, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        base_url = f"http://127.0.0.1:{port}"
        for _ in range(30):
            try:
                health = fetch_json(f"{base_url}/health")
                if health.get("status") == "ok":
                    break
            except Exception:
                time.sleep(0.1)
        else:
            return fail("api server did not become healthy")
        capabilities = fetch_json(f"{base_url}/capabilities")
        keys = {item.get("key") for item in capabilities.get("capability_profile", {}).get("capabilities", [])}
        if "role_capability_map" not in keys:
            return fail("capabilities endpoint should expose role_capability_map")
        if "owned_agent_team" not in keys:
            return fail("capabilities endpoint should expose owned_agent_team")
        if "hermes_asset_migration" not in keys:
            return fail("capabilities endpoint should expose hermes_asset_migration")
        role_capabilities = fetch_json(f"{base_url}/role-capabilities")
        if role_capabilities.get("role_capability_map", {}).get("summary", {}).get("role_count") != 9:
            return fail("role-capabilities endpoint should return 9 roles")
        agent_team = fetch_json(f"{base_url}/agent-team")
        if agent_team.get("owned_agent_team", {}).get("role_count") != 7:
            return fail("agent-team endpoint should return 7 commerce roles")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())

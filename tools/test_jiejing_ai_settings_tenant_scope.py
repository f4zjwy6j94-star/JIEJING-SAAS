#!/usr/bin/env python3
"""Keep merchant AI settings scoped to the signed-in account."""

from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")


def function_body(name: str, next_name: str) -> str:
    start = APP_JS.index(f"function {name}(")
    end = APP_JS.index(f"function {next_name}(", start)
    return APP_JS[start:end]


def main() -> None:
    configured = function_body("isSaasMerchantModelConfigured", "isSaasPlatformTrialModelAvailable")
    if "state.saasModelSettings?.configured" not in configured:
        raise AssertionError("merchant AI status must use account-scoped model settings")
    if "saasActiveModelSecretRef()" not in configured:
        raise AssertionError("merchant AI status must accept the account's ready secret reference")
    if "saasModelValueGate" in configured or "merchant_byok_model" in configured:
        raise AssertionError("global readiness evidence must not mark the current merchant account as configured")

    panel = function_body("renderSaasMerchantModelProviderPanel", "renderSaasMerchantMemoryPanel")
    if "const merchantModelConfigured = isSaasMerchantModelConfigured();" not in panel:
        raise AssertionError("AI settings summary must use the account-scoped configured state")
    if 'merchantModelConfigured ? "账号 AI 已连接"' not in panel:
        raise AssertionError("AI settings summary needs one truthful connected label")

    subprocess.run(["node", str(ROOT / "tools/test_jiejing_ai_settings_hierarchy.js")], cwd=ROOT, check=True)
    print("PASS jiejing_ai_settings_tenant_scope")


if __name__ == "__main__":
    main()

"""Regression test for platform-managed AI CEO model readiness."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.model_value_gate import build_model_value_gate  # noqa: E402
from jiejing_saas.readiness import build_product_readiness  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_MODEL_PROVIDER",
    "JIEJING_MODEL_API_KEY",
    "JIEJING_MODEL_BASE_URL",
    "JIEJING_MODEL",
    "JIEJING_MODEL_DISABLE_LIVE",
    "DEEPSEEK_API_KEY",
    "JIEJING_AI_CEO_PLATFORM_MODEL_ENABLED",
    "JIEJING_AI_CEO_PLATFORM_MODEL_PROVIDER",
    "JIEJING_AI_CEO_PLATFORM_MODEL_API_KEY",
    "JIEJING_AI_CEO_PLATFORM_MODEL_BASE_URL",
    "JIEJING_AI_CEO_PLATFORM_MODEL",
)


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def main() -> None:
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    secret_marker = "unit-platform-model-secret-must-not-be-returned"
    try:
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update(
            {
                "JIEJING_SAAS_ENV": "staging",
                "JIEJING_AI_CEO_PLATFORM_MODEL_ENABLED": "true",
                "JIEJING_AI_CEO_PLATFORM_MODEL_PROVIDER": "deepseek",
                "JIEJING_AI_CEO_PLATFORM_MODEL_API_KEY": secret_marker,
                "JIEJING_AI_CEO_PLATFORM_MODEL_BASE_URL": "https://api.deepseek.com",
                "JIEJING_AI_CEO_PLATFORM_MODEL": "deepseek-v4-pro",
            }
        )

        root = Path(tempfile.mkdtemp(prefix="jiejing-platform-model-readiness-"))
        repo = SaaSRepository(root / "saas.sqlite", database_engine="sqlite")
        repo.initialize()
        user_company = repo.create_user_with_company(
            email="platform-model@example.com",
            password="password123",
            company_name="Platform Model Co",
        )
        user = user_company["user"]
        company = user_company["company"]
        repo.create_store(
            company_id=company["company_id"],
            user_id=user["user_id"],
            payload={
                "platform": "ebay",
                "store_name": "Platform Model Store",
                "marketplace": "EBAY_US",
                "stage": "store_opened",
            },
        )
        settings = SaaSSettings.from_env(
            db_path=root / "saas.sqlite",
            runtime_db_path=root / "runtime.sqlite",
            output_root=root,
            host="127.0.0.1",
            port=8788,
        )

        gate = build_model_value_gate(settings, repo)
        assert gate["platform_default_model"]["configured"] is True
        assert gate["platform_default_model"]["provider"] == "deepseek"
        assert gate["platform_default_model"]["model"] == "deepseek-v4-pro"
        assert "model_provider_not_configured" not in gate["blockers"]

        readiness = build_product_readiness(settings, repo)
        model_item = {item["key"]: item for item in readiness["items"]}["model_provider"]
        model_status = readiness["provider_status"]["model"]
        model_value = readiness["provider_status"]["model_value"]
        assert model_item["status"] == "platform_default_model_ready"
        assert model_item["severity"] == "info"
        assert model_status["configured"] is True
        assert model_status["platform_default_configured"] is True
        assert model_status["mode"] == "platform_managed_default"
        assert model_value["model_configured"] is True
        assert model_value["platform_default_configured"] is True

        public_payload = json.dumps({"gate": gate, "readiness": readiness}, ensure_ascii=False)
        assert secret_marker not in public_payload
        assert '"secret_exposed": true' not in public_payload.lower()

        os.environ.pop("JIEJING_AI_CEO_PLATFORM_MODEL_API_KEY", None)
        missing_key_gate = build_model_value_gate(settings, repo)
        assert missing_key_gate["platform_default_model"]["configured"] is False
        assert "model_provider_not_configured" in missing_key_gate["blockers"]
    finally:
        _restore_env(previous)

    print("PASS jiejing_platform_model_readiness")


if __name__ == "__main__":
    main()

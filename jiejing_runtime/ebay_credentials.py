"""Backend-only eBay credential and policy snapshot helpers.

These helpers let Runtime adapters discover that the local Hermes environment
has eBay read capability without copying tokens into reports, frontend state, or
knowledge packs.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


class EbayCredentialResolver:
    """Resolve eBay tokens and sanitized snapshots for backend adapter use."""

    version = "0.1.0"

    def resolve_access_token(self, explicit_token: str | None = None, env_names: tuple[str, ...] = ()) -> tuple[str, str]:
        if explicit_token:
            return explicit_token, "constructor"
        for name in env_names or ("JIEJING_EBAY_READ_TOKEN", "JIEJING_EBAY_ACCOUNT_READ_TOKEN", "EBAY_ACCESS_TOKEN"):
            value = os.environ.get(name)
            if value:
                return value, f"env:{name}"
        if self._env_enabled("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", default=True):
            token, source = self._token_from_wsl_files()
            if token:
                return token, source
            if source.endswith("_token_expired") and self._env_enabled("JIEJING_EBAY_AUTO_REFRESH", default=False):
                refresh = self.refresh_with_hermes_policy_adapter()
                if refresh.get("status") == "success":
                    token, refreshed_source = self._token_from_wsl_files()
                    if token:
                        return token, f"{refreshed_source}_after_auto_refresh"
            if source != "missing":
                return "", source
        return "", "missing"

    def credential_presence(self) -> dict[str, Any]:
        token, source = self.resolve_access_token()
        return {
            "credential_present": bool(token),
            "credential_source": source,
            "secret_exposed": False,
        }

    def policy_snapshot_responses(self) -> dict[str, dict[str, Any]]:
        if not self._env_enabled("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", default=True):
            return {
                "fulfillment_policy_response": {},
                "payment_policy_response": {},
                "return_policy_response": {},
            }
        data = self._read_json(self._wsl_home() / "output" / "ebay-account" / "business_policies_latest.json")
        policies = data.get("policies") if isinstance(data, dict) else {}
        policies = policies if isinstance(policies, dict) else {}
        return {
            "fulfillment_policy_response": self._policy_response(policies.get("fulfillment"), "fulfillmentPolicies"),
            "payment_policy_response": self._policy_response(policies.get("payment"), "paymentPolicies"),
            "return_policy_response": self._policy_response(policies.get("return"), "returnPolicies"),
        }

    def policy_snapshot_summary(self) -> dict[str, Any]:
        responses = self.policy_snapshot_responses()
        return {
            "policy_snapshot_present": any(responses.values()),
            "counts": {
                "fulfillment": len(responses.get("fulfillment_policy_response", {}).get("fulfillmentPolicies", []) or []),
                "payment": len(responses.get("payment_policy_response", {}).get("paymentPolicies", []) or []),
                "return": len(responses.get("return_policy_response", {}).get("returnPolicies", []) or []),
            },
            "source": "wsl_hermes_business_policy_snapshot" if any(responses.values()) else "missing",
            "secret_exposed": False,
        }

    def oauth_refresh_status(self) -> dict[str, Any]:
        wsl_lookup_enabled = self._env_enabled("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", default=True)
        token_data, token_source = self._best_token_data() if wsl_lookup_enabled else ({}, "missing")
        app_credentials = (
            self._read_json(self._wsl_home() / "credentials" / "ebay_production_app_keyset.json")
            if wsl_lookup_enabled else {}
        )
        refresh_token_present = bool(token_data.get("refresh_token")) if isinstance(token_data, dict) else False
        client_id_present = bool(
            os.environ.get("JIEJING_EBAY_CLIENT_ID")
            or os.environ.get("EBAY_CLIENT_ID")
            or app_credentials.get("client_id")
            or app_credentials.get("app_id")
            or (token_data.get("app_id") if isinstance(token_data, dict) else "")
        )
        client_secret_present = bool(
            os.environ.get("JIEJING_EBAY_CLIENT_SECRET")
            or os.environ.get("EBAY_CLIENT_SECRET")
            or app_credentials.get("cert_id")
            or app_credentials.get("client_secret")
        )
        return {
            "refresh_token_present": refresh_token_present,
            "client_id_present": client_id_present,
            "client_secret_present": client_secret_present,
            "refresh_ready": refresh_token_present and client_id_present and client_secret_present,
            "auto_refresh_enabled": self._env_enabled("JIEJING_EBAY_AUTO_REFRESH", default=False),
            "hermes_refresh_adapter": self.hermes_refresh_adapter_status(),
            "credential_source": token_source if refresh_token_present else "missing",
            "secret_exposed": False,
        }

    def hermes_refresh_adapter_status(self) -> dict[str, Any]:
        available = self._env_enabled("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", default=True) and (
            self._wsl_home() / "scripts" / "ebay_business_policies.py"
        ).exists()
        return {
            "available": available,
            "path": "/home/hermes/.hermes/scripts/ebay_business_policies.py" if available else "",
            "mode": "read_only_policy_refresh",
            "secret_exposed": False,
        }

    def refresh_with_hermes_policy_adapter(self, timeout_seconds: int = 90) -> dict[str, Any]:
        if not self._env_enabled("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", default=True):
            return {"status": "disabled", "summary": "Hermes WSL credential lookup is disabled.", "secret_exposed": False}
        if os.name != "nt":
            return {"status": "unsupported_host", "summary": "Hermes WSL refresh bridge is only enabled from Windows host.", "secret_exposed": False}
        script = "/home/hermes/.hermes/scripts/ebay_business_policies.py"
        command = (
            "python3 "
            f"{script} --environment production --marketplace-id EBAY_US --proxy ''"
        )
        try:
            completed = subprocess.run(
                ["wsl.exe", "-e", "bash", "-lc", command],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except Exception as exc:
            return {"status": "failed", "summary": str(exc)[:500], "secret_exposed": False}
        output = (completed.stdout or completed.stderr or "").strip()
        return {
            "status": "success" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "summary": self._sanitize_refresh_output(output),
            "secret_exposed": False,
        }

    def listing_rules_snapshot_present(self) -> bool:
        if not self._env_enabled("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", default=True):
            return False
        return (self._wsl_home() / "output" / "ebay-account" / "northvalesource_listing_rules_latest.json").exists()

    def policy_snapshot_present(self) -> bool:
        if not self._env_enabled("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", default=True):
            return False
        return (self._wsl_home() / "output" / "ebay-account" / "business_policies_latest.json").exists()

    def _policy_response(self, section: Any, array_key: str) -> dict[str, Any]:
        if not isinstance(section, dict):
            return {}
        policies = section.get("policies")
        if not isinstance(policies, list):
            return {}
        return {array_key: [item for item in policies if isinstance(item, dict)]}

    def _token_from_wsl_files(self) -> tuple[str, str]:
        saw_expired_source = ""
        for path, source in self._token_file_candidates():
            data = self._read_json(path)
            token = str(data.get("access_token") or "") if isinstance(data, dict) else ""
            if not token:
                continue
            expires_at = data.get("expires_at")
            try:
                if expires_at and float(expires_at) <= time.time() + 60:
                    saw_expired_source = f"{source}_token_expired"
                    continue
            except (TypeError, ValueError):
                pass
            return token, source
        return "", saw_expired_source or "missing"

    def _best_token_data(self) -> tuple[dict[str, Any], str]:
        best_expired: tuple[dict[str, Any], str] | None = None
        for path, source in self._token_file_candidates():
            data = self._read_json(path)
            if not isinstance(data, dict) or not data.get("access_token"):
                continue
            expires_at = data.get("expires_at")
            try:
                if expires_at and float(expires_at) <= time.time() + 60:
                    best_expired = (data, f"{source}_token_expired")
                    continue
            except (TypeError, ValueError):
                pass
            return data, source
        return best_expired or ({}, "missing")

    def _token_file_candidates(self) -> list[tuple[Path, str]]:
        home = self._wsl_home()
        return [
            (home / "credentials" / "ebay_production_user_token.json", "wsl_hermes_root_credential_file"),
            (
                home / "profiles" / "market-manager" / "credentials" / "ebay_production_user_token.json",
                "wsl_hermes_market_manager_credential_file",
            ),
        ]

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            if not path.exists():
                return {}
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _sanitize_refresh_output(self, output: str) -> str:
        text = output[-1000:]
        for marker in ["access_token", "refresh_token", "client_secret", "cert_id", "Authorization", "Basic", "Bearer"]:
            text = text.replace(marker, f"{marker[0]}***")
        return text

    def _wsl_home(self) -> Path:
        return Path(os.environ.get("JIEJING_HERMES_WSL_HOME") or r"\\wsl.localhost\Ubuntu\home\hermes\.hermes")

    def _env_enabled(self, name: str, default: bool = False) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

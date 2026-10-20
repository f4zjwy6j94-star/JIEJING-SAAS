#!/usr/bin/env python3
"""Hermes lookup-off isolation using synthetic data and public resolver APIs."""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.ebay_credentials import EbayCredentialResolver  # noqa: E402
from jiejing_runtime.ebay_provider_status import EbayProviderStatus  # noqa: E402


class EbayCredentialLookupIsolationTests(unittest.TestCase):
    def test_enabled_lookup_preserves_synthetic_file_resolution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jiejing-enabled-lookup-") as temp_dir:
            fake_home = Path(temp_dir)
            (fake_home / "credentials").mkdir()
            (fake_home / "output" / "ebay-account").mkdir(parents=True)
            (fake_home / "scripts").mkdir()
            synthetic_files = {
                "credentials/ebay_production_user_token.json": {
                    "access_token": "SYNTHETIC-ENABLED-ACCESS",
                    "refresh_token": "SYNTHETIC-ENABLED-REFRESH",
                    "expires_at": 4102444800,
                },
                "credentials/ebay_production_app_keyset.json": {
                    "client_id": "SYNTHETIC-ENABLED-ID",
                    "client_secret": "SYNTHETIC-ENABLED-SECRET",
                },
                "output/ebay-account/business_policies_latest.json": {
                    "policies": {"payment": {"policies": [{"paymentPolicyId": "SYNTHETIC-POLICY"}]}}
                },
                "output/ebay-account/northvalesource_listing_rules_latest.json": {},
            }
            for relative_path, data in synthetic_files.items():
                (fake_home / relative_path).write_text(json.dumps(data), encoding="utf-8")
            (fake_home / "scripts" / "ebay_business_policies.py").write_text("# Never executed.\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {
                    "JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": "1",
                    "JIEJING_HERMES_WSL_HOME": str(fake_home),
                    "JIEJING_EBAY_AUTO_REFRESH": "0",
                }, clear=True),
                patch.object(subprocess, "Popen", side_effect=AssertionError("launch forbidden")) as launch,
                patch.object(socket, "socket", side_effect=AssertionError("network forbidden")) as network,
            ):
                resolver = EbayCredentialResolver()
                self.assertEqual(resolver.resolve_access_token(), ("SYNTHETIC-ENABLED-ACCESS", "wsl_hermes_root_credential_file"))
                status = EbayProviderStatus().to_dict()
                summary = resolver.policy_snapshot_summary()
            launch.assert_not_called()
            network.assert_not_called()
            self.assertTrue(status["credential_present"])
            self.assertTrue(status["policy_snapshot_present"])
            self.assertTrue(status["listing_rules_snapshot_present"])
            self.assertTrue(status["oauth_refresh"]["refresh_ready"])
            self.assertTrue(status["oauth_refresh"]["hermes_refresh_adapter"]["available"])
            self.assertEqual(summary["counts"]["payment"], 1)
            public_status = json.dumps(status)
            for secret in ("SYNTHETIC-ENABLED-ACCESS", "SYNTHETIC-ENABLED-REFRESH", "SYNTHETIC-ENABLED-SECRET"):
                self.assertNotIn(secret, public_status)

    def test_disabled_lookup_keeps_explicit_and_environment_tokens(self) -> None:
        with (
            patch.dict(os.environ, {"JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": "0", "JIEJING_EBAY_READ_TOKEN": "SYNTHETIC-ENV-TOKEN"}, clear=True),
            patch.object(os, "stat", side_effect=FileNotFoundError(2, "synthetic boundary")) as stat,
            patch.object(io, "open", side_effect=PermissionError("file access forbidden")) as opened,
        ):
            resolver = EbayCredentialResolver()
            self.assertEqual(resolver.resolve_access_token("SYNTHETIC-CONSTRUCTOR-TOKEN"), ("SYNTHETIC-CONSTRUCTOR-TOKEN", "constructor"))
            self.assertEqual(resolver.resolve_access_token(), ("SYNTHETIC-ENV-TOKEN", "env:JIEJING_EBAY_READ_TOKEN"))
            self.assertEqual(resolver.credential_presence(), {"credential_present": True, "credential_source": "env:JIEJING_EBAY_READ_TOKEN", "secret_exposed": False})
        stat.assert_not_called()
        opened.assert_not_called()

    def test_all_false_switch_spellings_are_isolated(self) -> None:
        for raw_value in ("0", "false", "off", "no", "", " FALSE "):
            with (
                self.subTest(value=raw_value),
                patch.dict(os.environ, {"JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": raw_value}, clear=True),
                patch.object(os, "stat", side_effect=FileNotFoundError(2, "synthetic boundary")) as stat,
                patch.object(io, "open", side_effect=PermissionError("file access forbidden")) as opened,
                patch.object(subprocess, "Popen", side_effect=AssertionError("launch forbidden")) as launch,
            ):
                resolver = EbayCredentialResolver()
                self.assertFalse(EbayProviderStatus().to_dict()["credential_present"])
                self.assertEqual(resolver.policy_snapshot_summary()["source"], "missing")
                self.assertEqual(resolver.refresh_with_hermes_policy_adapter()["status"], "disabled")
                for boundary in (stat, opened, launch):
                    boundary.assert_not_called()

    def test_disabled_lookup_cannot_start_refresh_subprocess(self) -> None:
        with (
            patch.dict(os.environ, {"JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": "0"}, clear=True),
            patch.object(subprocess, "Popen", side_effect=AssertionError("launch forbidden")) as launch,
            patch.object(socket, "socket", side_effect=AssertionError("network forbidden")) as network,
        ):
            status = EbayCredentialResolver().refresh_with_hermes_policy_adapter()
        launch.assert_not_called()
        network.assert_not_called()
        self.assertEqual(status["status"], "disabled")
        self.assertFalse(status["secret_exposed"])

    def test_disabled_lookup_direct_adapter_status_does_not_probe_files(self) -> None:
        with (
            patch.dict(os.environ, {"JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": "0"}, clear=True),
            patch.object(os, "stat", side_effect=FileNotFoundError(2, "synthetic boundary")) as stat,
        ):
            status = EbayCredentialResolver().hermes_refresh_adapter_status()
        stat.assert_not_called()
        self.assertEqual(status, {"available": False, "path": "", "mode": "read_only_policy_refresh", "secret_exposed": False})

    def test_disabled_lookup_provider_summary_does_not_probe_files(self) -> None:
        with (
            patch.dict(os.environ, {"JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": "0"}, clear=True),
            patch.object(os, "stat", side_effect=FileNotFoundError(2, "synthetic boundary")) as stat,
            patch.object(io, "open", side_effect=PermissionError("file access forbidden")) as opened,
            patch.object(socket, "socket", side_effect=AssertionError("network forbidden")) as network,
            patch.object(subprocess, "Popen", side_effect=AssertionError("launch forbidden")) as launch,
        ):
            status = EbayProviderStatus().to_dict()
        for boundary in (stat, opened, network, launch):
            boundary.assert_not_called()
        self.assertFalse(status["credential_present"])
        self.assertFalse(status["policy_snapshot_present"])
        self.assertFalse(status["listing_rules_snapshot_present"])
        self.assertFalse(status["oauth_refresh"]["refresh_ready"])
        self.assertEqual(status["surfaces"]["write_execution"]["status"], "blocked_until_confirmation_service")

    def test_disabled_lookup_status_never_accesses_fake_wsl_home(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jiejing-lookup-isolation-") as temp_dir:
            fake_home = Path(temp_dir) / "synthetic-wsl-home"
            credentials = fake_home / "credentials"
            credentials.mkdir(parents=True)
            (credentials / "ebay_production_user_token.json").write_text(
                json.dumps({
                    "access_token": "SYNTHETIC-NOT-A-VALID-ACCESS-TOKEN",
                    "refresh_token": "SYNTHETIC-NOT-A-VALID-REFRESH-TOKEN",
                    "expires_at": 4102444800,
                }),
                encoding="utf-8",
            )
            synthetic_env = {
                "JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": "0",
                "JIEJING_HERMES_WSL_HOME": str(fake_home),
                "JIEJING_EBAY_AUTO_REFRESH": "0",
                "JIEJING_EBAY_CLIENT_ID": "SYNTHETIC-ENV-CLIENT-ID",
                "JIEJING_EBAY_CLIENT_SECRET": "SYNTHETIC-ENV-CLIENT-SECRET",
            }
            # Observe physical boundaries, not resolver-private collaborators.
            # FileNotFoundError lets old exists() callers finish, so a swallowed
            # read failure cannot turn forbidden access into a passing result.
            with (
                patch.dict(os.environ, synthetic_env, clear=True),
                patch.object(os, "stat", side_effect=FileNotFoundError(2, "synthetic I/O boundary")) as stat,
                patch.object(io, "open", side_effect=PermissionError("synthetic I/O boundary")) as io_open,
                patch("builtins.open", side_effect=PermissionError("synthetic I/O boundary")) as builtin_open,
                patch.object(socket, "socket", side_effect=AssertionError("network forbidden")) as network,
                patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")) as dns,
                patch.object(subprocess, "Popen", side_effect=AssertionError("process launch forbidden")) as launch,
            ):
                status = EbayCredentialResolver().oauth_refresh_status()

            for boundary in (stat, io_open, builtin_open, network, dns, launch):
                boundary.assert_not_called()
            self.assertEqual(status, {
                "refresh_token_present": False,
                "client_id_present": True,
                "client_secret_present": True,
                "refresh_ready": False,
                "auto_refresh_enabled": False,
                "hermes_refresh_adapter": {
                    "available": False,
                    "path": "",
                    "mode": "read_only_policy_refresh",
                    "secret_exposed": False,
                },
                "credential_source": "missing",
                "secret_exposed": False,
            })


if __name__ == "__main__":
    unittest.main(verbosity=2)

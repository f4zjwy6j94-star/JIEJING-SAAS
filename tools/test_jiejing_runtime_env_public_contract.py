#!/usr/bin/env python3
"""Validate the public staging Compose and env-example ownership contract."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jiejing_runtime_env_overlap_guard import check_runtime_env_ownership


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
COMPOSE_CANDIDATES = (
    DEPLOY / "docker-compose.public-https-staging.yml",
    DEPLOY / "docker-compose.public-staging.yml",
)
MANAGED_TEMPLATE = DEPLOY / "jiejing-saas.tencent-managed.env.example"
SECRET_TEMPLATE = DEPLOY / "jiejing-saas.staging-oauth.env.example"
POSTGRES_TEMPLATE = ROOT / "deploy" / "jiejing-saas.postgres-localqueue.env.example"


def _env_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, _value = stripped.partition("=")
        if not separator:
            raise AssertionError(f"malformed env example line in {path.name}")
        keys.add(key)
    return keys


class RuntimeEnvPublicContractTest(unittest.TestCase):
    def test_postgres_localqueue_template_defines_the_runtime_connection_schema(self) -> None:
        self.assertTrue(POSTGRES_TEMPLATE.is_file())
        keys = _env_keys(POSTGRES_TEMPLATE)
        self.assertEqual(
            keys,
            {
                "JIEJING_DATABASE_ENGINE",
                "JIEJING_DATABASE_ADAPTER",
                "JIEJING_DATABASE_URL",
                "JIEJING_POSTGRES_DRIVER_CHECK_LIVE",
                "JIEJING_QUEUE_PROVIDER",
                "JIEJING_QUEUE_URL",
                "JIEJING_REDIS_STREAM",
                "JIEJING_REDIS_CONSUMER_GROUP",
                "JIEJING_REDIS_DEAD_LETTER_STREAM",
                "JIEJING_REDIS_WORKER_BLOCK_MS",
                "JIEJING_REDIS_DRIVER_CHECK_LIVE",
            },
        )

    def test_both_public_staging_compose_candidates_pass_the_ownership_guard(self) -> None:
        for source_compose in COMPOSE_CANDIDATES:
            with self.subTest(compose=source_compose.name), TemporaryDirectory() as temp_dir:
                temp_root = Path(temp_dir)
                candidate_deploy = temp_root / "workspace" / "deploy"
                private_root = temp_root / "private"
                candidate_deploy.mkdir(parents=True)
                private_root.mkdir()

                compose_path = candidate_deploy / source_compose.name
                managed_path = private_root / "tencent-managed.env"
                secret_path = private_root / "jiejing-saas.staging-oauth.env"
                postgres_path = private_root / "postgres-localqueue.env"
                compose_path.write_text(source_compose.read_text(encoding="utf-8"), encoding="utf-8")
                managed_path.write_text(MANAGED_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
                secret_path.write_text(SECRET_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
                postgres_path.write_text(POSTGRES_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")

                report = check_runtime_env_ownership(
                    compose_path=compose_path,
                    managed_env_path=managed_path,
                    secret_env_path=secret_path,
                    postgres_env_path=postgres_path,
                )

                self.assertTrue(report["ok"], report["blockers"])
                self.assertEqual(report["blockers"], [])
                self.assertFalse(report["secret_exposed"])
                self.assertEqual(report["summary"]["unauthorized_duplicate_count"], 0)

    def test_public_templates_have_unique_key_ownership(self) -> None:
        managed_keys = _env_keys(MANAGED_TEMPLATE)
        secret_keys = _env_keys(SECRET_TEMPLATE)
        postgres_keys = _env_keys(POSTGRES_TEMPLATE)

        self.assertEqual(managed_keys & secret_keys, set())
        self.assertEqual(managed_keys & postgres_keys, set())
        self.assertEqual(secret_keys & postgres_keys, set())
        self.assertTrue(
            {
                "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
                "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED",
            }
            <= managed_keys
        )
        self.assertTrue(
            {
                "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED",
                "JIEJING_MEDIA_LIVE_VIDEO_ENABLED",
            }
            <= secret_keys
        )

    def test_fallback_compose_loads_postgres_last_and_pins_no_charge_billing(self) -> None:
        text = (DEPLOY / "docker-compose.public-staging.yml").read_text(encoding="utf-8")
        env_file_contract = """    env_file:
      - ../../private/tencent-managed.env
      - ../../private/jiejing-saas.staging-oauth.env
      - ../../private/postgres-localqueue.env
"""
        self.assertEqual(text.count(env_file_contract), 2)
        self.assertEqual(text.count('JIEJING_BILLING_PROVIDER: "stripe_test_mock"'), 2)

    def test_media_and_runbook_keys_are_absent_from_compose_overrides(self) -> None:
        forbidden_compose_keys = (
            "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED:",
            "JIEJING_MEDIA_LIVE_VIDEO_ENABLED:",
            "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED:",
            "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED:",
        )
        for compose_path in COMPOSE_CANDIDATES:
            with self.subTest(compose=compose_path.name):
                text = compose_path.read_text(encoding="utf-8")
                for key in forbidden_compose_keys:
                    self.assertNotIn(key, text)

    def test_public_compose_candidates_own_non_secret_staging_static_config(self) -> None:
        for compose_path in COMPOSE_CANDIDATES:
            with self.subTest(compose=compose_path.name):
                text = compose_path.read_text(encoding="utf-8")
                for marker in (
                    'JIEJING_SAAS_ENV: "staging"',
                    'JIEJING_ALLOW_HERMES_ADAPTERS: "false"',
                ):
                    self.assertEqual(text.count(marker), 2, marker)
                self.assertEqual(text.count("JIEJING_CORS_ORIGIN:"), 2)


if __name__ == "__main__":
    unittest.main()

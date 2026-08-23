#!/usr/bin/env python3
"""Product-grade guardrail checks for Jiejing SaaS backend startup."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-saas-backend" / "guardrail-test"
sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import _readiness_has_startup_blockers


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    warning_only_readiness = {
        "production_ready": False,
        "blocker_count": 0,
        "warning_count": 1,
        "items": [{"severity": "warning", "status": "blocked_provider_monitoring_evidence"}],
    }
    if _readiness_has_startup_blockers(warning_only_readiness):
        return fail("warning-only readiness must not turn a production restart into an outage")
    if not _readiness_has_startup_blockers({"production_ready": False, "blocker_count": 1}):
        return fail("a real readiness blocker must still refuse normal production startup")
    if not _readiness_has_startup_blockers({"production_ready": False}):
        return fail("missing blocker counts must fail closed")
    if not _readiness_has_startup_blockers({"production_ready": False, "blocker_count": True}):
        return fail("malformed blocker counts must fail closed")

    env = os.environ.copy()
    env["JIEJING_SAAS_ENV"] = "production"
    env["JIEJING_SAAS_SESSION_SECRET"] = "production-like-test-secret-that-is-long-enough"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(OUT / "prod-guard.sqlite"),
            "--runtime-db",
            str(OUT / "prod-runtime.sqlite"),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            "8794",
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=15,
        check=False,
    )
    combined = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        return fail("production backend should refuse to start with local sqlite/queue/vault blockers")
    if "Refusing to start a blocked production candidate" not in combined:
        return fail("production refusal should explain readiness blockers")

    env = os.environ.copy()
    env["JIEJING_ENABLE_REAL_PLATFORM_WRITES"] = "true"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(OUT / "write-guard.sqlite"),
            "--runtime-db",
            str(OUT / "write-runtime.sqlite"),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            "8795",
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=15,
        check=False,
    )
    combined = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        return fail("backend should refuse requested real platform writes in MVP")
    if "Refusing to enable real platform writes" not in combined:
        return fail("real write refusal should be explicit")

    env = os.environ.copy()
    env.update(
        {
            "JIEJING_SAAS_ENV": "production",
            "JIEJING_SAAS_SESSION_SECRET": "production-like-test-secret-that-is-long-enough",
            "JIEJING_CORS_ORIGIN": "https://app.jiejing.example",
            "JIEJING_DATABASE_ENGINE": "postgres",
            "JIEJING_DATABASE_ADAPTER": "postgres-managed",
            "JIEJING_DATABASE_URL": "postgresql://jiejing:placeholder@postgres:5432/jiejing",
            "JIEJING_QUEUE_PROVIDER": "redis_streams",
            "JIEJING_QUEUE_URL": "redis://redis:6379/0",
            "JIEJING_VAULT_ENABLED": "true",
            "JIEJING_VAULT_PROVIDER": "vault",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(OUT / "managed-prod-guard.sqlite"),
            "--runtime-db",
            str(OUT / "managed-prod-runtime.sqlite"),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            "8796",
        ],
        cwd=str(ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=15,
        check=False,
    )
    combined = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        return fail("production backend should still refuse managed DB/queue config until drivers are implemented")
    if not any(
        marker in combined
        for marker in (
            "Refusing to start a blocked production candidate",
            "Refusing to start production Jiejing SaaS backend while repository readiness has blockers",
        )
    ):
        return fail("managed driver-pending production refusal should be explicit")

    candidate_env = os.environ.copy()
    candidate_env.update(
        {
            "JIEJING_SAAS_ENV": "production",
            "JIEJING_SAAS_SESSION_SECRET": "production-candidate-test-secret-that-is-long-enough",
            "JIEJING_PRODUCTION_CANDIDATE_BOOT_ALLOWED": "true",
            "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "true",
            "JIEJING_EBAY_READ_ONLY_LIVE": "true",
            "JIEJING_EBAY_DRAFT_SAVE_LIVE": "true",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(OUT / "candidate-draft-guard.sqlite"),
            "--runtime-db",
            str(OUT / "candidate-draft-runtime.sqlite"),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            "8797",
        ],
        cwd=str(ROOT),
        env=candidate_env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=15,
        check=False,
    )
    combined = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode == 0:
        return fail("production candidate boot must refuse the controlled eBay draft-save write lane")
    if "requires payment and platform writes to remain disabled" not in combined:
        return fail("production candidate draft-save refusal should be explicit")

    print("PASS jiejing_saas_production_guardrails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

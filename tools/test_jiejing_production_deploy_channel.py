#!/usr/bin/env python3
"""Contract checks for the confirmation-gated production deploy channel."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "tools" / "jiejing_production_deploy.py"
APPLY = ROOT / "deploy" / "jiejing-production-release-apply.sh"
COMPOSE = ROOT / "deploy" / "docker-compose.production-pilot.yml"
PATCH_APPLY = ROOT / "deploy" / "apply-staging-patch.sh"
CI = ROOT / ".github" / "workflows" / "jiejing-ci.yml"
RUNBOOK = ROOT / "docs" / "JIEJING_PRODUCTION_DEPLOY_RUNBOOK_20260823.md"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def main() -> int:
    try:
        client = read(CLIENT)
        apply = read(APPLY)
        compose = read(COMPOSE)
        patch_apply = read(PATCH_APPLY)
        ci = read(CI)
        runbook = read(RUNBOOK)
    except FileNotFoundError as exc:
        return fail(f"missing production deploy channel file: {exc}")

    required_client = [
        'DEFAULT_HOST = "43.129.169.223"',
        "DEFAULT_PORT = 22",
        'Path.home() / ".ssh" / "jiejing_production_hk_ed25519"',
        'choices=("dry_run", "apply")',
        'EXPECTED_CONFIRM = "deploy app.jiejing.shop production"',
        "bundle_sha256_mismatch",
        "manifest_scope_invalid",
        "validate_bundle_javascript(bundle)",
        "local_node_unavailable",
        "bundle_javascript_invalid",
        '"jiejing_saas/migrations/002_media_credit_buckets_postgres.sql"',
        '"jiejing_saas/migrations/003_runtime_schema_reconciliation_postgres.sql"',
        "StrictHostKeyChecking=yes",
        "IdentitiesOnly=yes",
        "BatchMode=yes",
        "JIEJING_PRODUCTION_DEPLOY_CONFIRM",
        "JIEJING_PRODUCTION_DEPLOY_DRY_RUN",
        "jiejing-production-release-apply.sh",
        '"secret_exposed": False',
    ]
    required_apply = [
        'EXPECTED_CONFIRM="deploy app.jiejing.shop production"',
        'PRODUCTION_ROOT="/opt/jiejing-production"',
        'ACTIVE_LINK="$PRODUCTION_ROOT/app"',
        'RELEASE_ROOT="$PRODUCTION_ROOT/releases"',
        "REFUSE_PRODUCTION_CONFIRMATION_MISMATCH",
        "REFUSE_INVALID_PRODUCTION_DRY_RUN",
        "REFUSE_PATCH_DIR_OUTSIDE_TMP",
        "REFUSE_ACTIVE_RELEASE_OUTSIDE_ROOT",
        "REFUSE_PRIVATE_DIR_OUTSIDE_ROOT",
        "com.docker.compose.project.environment_file",
        "JIEJING_PRODUCTION_PRIVATE_DIR",
        "docker compose",
        "--project-name deploy",
        "build jiejing-saas jiejing-worker",
        "up -d --no-deps jiejing-saas",
        "up -d --no-deps jiejing-worker",
        "up -d --no-deps --force-recreate jiejing-frontend",
        "up -d --no-deps --force-recreate jiejing-edge",
        'PUBLIC_URL="https://app.jiejing.shop"',
        'wait_public_json "/health"',
        'wait_public_json "/health/deep"',
        'wait_public_json "/readiness/product-saas"',
        'data.get("status") == "ok"',
        'health.get("status") == "ready"',
        'readiness = data.get("readiness") or {}',
        'readiness.get("environment") == "production"',
        'readiness.get("public_contract_version")',
        'PRODUCTION_PUBLIC_CHECK_FAILED=',
        "JIEJING_PRODUCTION_DEPLOY_DRY_RUN=1",
        "JIEJING_PRODUCTION_DEPLOY_APPLIED=1",
        "JIEJING_PRODUCTION_ROLLBACK_APPLIED=1",
        "ln -sfn",
        "trap rollback_on_error ERR",
        "chmod -R go-w",
        "JIEJING_PRODUCTION_RELEASE_MANIFEST.txt",
    ]
    required_compose = [
        "${JIEJING_PRODUCTION_PRIVATE_DIR:-../../private}/jiejing-saas.production.env",
        "${JIEJING_PRODUCTION_PRIVATE_DIR:-../../private}/jiejing-vault-token.d/jiejing-vault-token",
        "${JIEJING_PRODUCTION_PRIVATE_DIR:-../../private}/jiejing-vault-token.d:/run/jiejing-vault-token-output",
    ]
    required_patch_whitelist = [
        '"deploy/jiejing-production-release-apply.sh"',
        '"tools/jiejing_production_deploy.py"',
        '"tools/test_jiejing_production_deploy_channel.py"',
        '"docs/JIEJING_PRODUCTION_DEPLOY_RUNBOOK_20260823.md"',
        '"jiejing_saas/migrations/002_media_credit_buckets_postgres.sql"',
        '"jiejing_saas/migrations/003_runtime_schema_reconciliation_postgres.sql"',
    ]
    required_ci = ["python tools/test_jiejing_production_deploy_channel.py"]
    required_runbook = [
        "正式生产主机",
        "dry_run",
        "deploy app.jiejing.shop production",
        "不复制任何密钥",
        "失败自动回滚",
        "production_ready",
        "can_accept_real_customers",
        "warning_count",
        "真实扣款、退款或 eBay 写入",
    ]

    missing: list[str] = []
    for prefix, text, markers in (
        ("client", client, required_client),
        ("apply", apply, required_apply),
        ("compose", compose, required_compose),
        ("patch", patch_apply, required_patch_whitelist),
        ("ci", ci, required_ci),
        ("runbook", runbook, required_runbook),
    ):
        missing.extend(f"{prefix}:{marker}" for marker in markers if marker not in text)
    if missing:
        return fail("production deploy channel missing markers: " + ",".join(missing))

    forbidden = [
        "StrictHostKeyChecking=no",
        "docker compose down -v",
        "docker volume rm",
        "DROP DATABASE",
        "JIEJING_EBAY_ACCESS_TOKEN",
        "JIEJING_EBAY_REFRESH_TOKEN",
        "JIEJING_WECHAT_PAY_API_V3_KEY",
        "OPENAI_API_KEY",
        "rm -rf /",
    ]
    combined = client + "\n" + apply
    present = [marker for marker in forbidden if marker in combined]
    if present:
        return fail("production deploy channel contains forbidden marker: " + ",".join(present))

    print("PASS jiejing_production_deploy_channel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

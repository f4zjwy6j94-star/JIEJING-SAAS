#!/usr/bin/env python3
"""Regression for the staging eBay OAuth/read-only operator tool."""

from __future__ import annotations

import json
import importlib.util
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "test-staging-ebay-oauth-flow-tool"
PASSWORD_SENTINEL = "FLOW-TOOL-PASSWORD-MUST-NOT-PERSIST"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    placeholder_error = _test_placeholder_detection()
    if placeholder_error:
        return fail(placeholder_error)

    multisource_error = _test_multisource_env_checks()
    if multisource_error:
        return fail(multisource_error)

    idempotent_error = _test_prepare_reuses_completed_oauth_without_new_authorization()
    if idempotent_error:
        return fail(idempotent_error)

    OUT.mkdir(parents=True, exist_ok=True)
    for path in (OUT / "saas.sqlite", OUT / "runtime.sqlite", OUT / "context.json"):
        path.unlink(missing_ok=True)
    port = _free_port()
    env = os.environ.copy()
    env["JIEJING_EBAY_CLIENT_ID"] = "FLOW-TOOL-CLIENT-ID"
    env["JIEJING_EBAY_RU_NAME"] = "FLOW_TOOL_RU_NAME"
    env["JIEJING_ENABLE_HERMES_EBAY_BRIDGE"] = "false"
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(OUT / "saas.sqlite"),
            "--runtime-db",
            str(OUT / "runtime.sqlite"),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        _wait_for_health(f"http://127.0.0.1:{port}")
        doctor = _run_tool(port=port, command="doctor", extra_args=["--register-if-needed"])
        if doctor.returncode == 0:
            return fail("doctor should block when the backend is not running in staging with managed Vault")
        doctor_stdout = doctor.stdout or ""
        doctor_stderr = doctor.stderr or ""
        if "DOCTOR_STATUS=blocked" not in doctor_stdout or "JIEJING_SAAS_ENV_should_be_staging" not in doctor_stdout:
            return fail("doctor should surface staging/Vault blockers before seller OAuth")
        if "vault_status_requires_platform_internal_admin" not in doctor_stdout:
            return fail("doctor should block seller OAuth when platform Vault evidence is not visible to the operator session")
        if PASSWORD_SENTINEL in doctor_stdout or PASSWORD_SENTINEL in doctor_stderr:
            return fail("doctor leaked the operator password")

        prepare = _run_tool(
            port=port,
            command="prepare",
            extra_args=["--register-if-needed"],
        )
        prepare_stdout = prepare.stdout or ""
        prepare_stderr = prepare.stderr or ""
        if prepare.returncode != 0:
            return fail(f"prepare should succeed with client_id and RuName: {prepare_stderr[:500]}")
        if "AUTHORIZATION_URL=https://auth.ebay.com/oauth2/authorize" not in prepare_stdout:
            return fail("prepare should print an eBay authorization URL")
        if PASSWORD_SENTINEL in prepare_stdout or PASSWORD_SENTINEL in prepare_stderr:
            return fail("prepare leaked the operator password")
        context = json.loads((OUT / "context.json").read_text(encoding="utf-8"))
        if not context.get("store_id") or not context.get("state_nonce"):
            return fail("prepare should persist store_id and state_nonce in context")
        if PASSWORD_SENTINEL in json.dumps(context, ensure_ascii=False):
            return fail("context file must not persist the operator password")

        status = _run_tool(port=port, command="status", extra_args=[])
        status_stdout = status.stdout or ""
        status_stderr = status.stderr or ""
        if status.returncode == 0:
            return fail("status should remain blocked before a real eBay callback")
        if "PREFLIGHT_STATUS=blocked" not in status_stdout:
            return fail("status should surface a blocked preflight before callback")
        if PASSWORD_SENTINEL in status_stdout or PASSWORD_SENTINEL in status_stderr:
            return fail("status leaked the operator password")
        env_check = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "jiejing_staging_ebay_oauth_readonly_flow.py"),
                "--env-file",
                str(ROOT / "deploy" / "jiejing-saas.staging-oauth.env.example"),
                "--output-root",
                str(OUT),
                "check-env",
            ],
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
            check=False,
        )
        if env_check.returncode == 0:
            return fail("example env file should not pass because placeholders are not real staging secrets")
        if "placeholder" not in (env_check.stdout or ""):
            return fail("env check should identify placeholder values")
        print("PASS jiejing_staging_ebay_oauth_flow_tool")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _test_placeholder_detection() -> str:
    spec = importlib.util.spec_from_file_location(
        "jiejing_staging_ebay_oauth_readonly_flow_placeholder_test",
        ROOT / "tools" / "jiejing_staging_ebay_oauth_readonly_flow.py",
    )
    if not spec or not spec.loader:
        return "could not load OAuth flow tool module for placeholder checks"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for placeholder in (
        "<inject-from-secret-manager>",
        "<inject-private-postgres-url>",
        "<ebay-ru-name>",
        "<provider-name>",
    ):
        if module._is_placeholder_value(placeholder) is not True:
            return f"angle-bracket placeholder should fail closed: {placeholder}"
    for real_value in (
        "https://app.jiejing.shop",
        "deepseek-chat",
        "tencent_ssm",
        "plain-runtime-value",
        "prefix<inject-from-secret-manager>",
        "<invalid placeholder>",
    ):
        if module._is_placeholder_value(real_value) is not False:
            return f"real or malformed value must not be classified as a placeholder: {real_value}"
    return ""


def _test_multisource_env_checks() -> str:
    safe_process_env = {
        key: os.environ[key]
        for key in ("PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP")
        if key in os.environ
    }
    safe_process_env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_CORS_ORIGIN": "https://app.jiejing.shop",
            "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
            "JIEJING_EBAY_WRITE_LIVE": "false",
            "JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY": "disabled_public_staging",
            "JIEJING_BILLING_PROVIDER": "stripe_test_mock",
        }
    )
    with TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        output_root = temp_root / "output"
        template_check = _run_env_check(
            env_files=(
                ROOT / "deploy" / "jiejing-saas.tencent-managed.env.example",
                ROOT / "deploy" / "jiejing-saas.staging-oauth.env.example",
                ROOT / "deploy" / "jiejing-saas.postgres-localqueue.env.example",
            ),
            output_root=output_root,
            process_env=safe_process_env,
        )
        if template_check.returncode == 0:
            return "three public env templates must remain blocked until private placeholders are filled"
        if "placeholder" not in (template_check.stdout or ""):
            return "multi-source template check should identify placeholder values"

        managed_path = temp_root / "tencent-managed.env"
        secret_path = temp_root / "jiejing-saas.staging-oauth.env"
        postgres_path = temp_root / "postgres-localqueue.env"
        managed_path.write_text(
            "JIEJING_VAULT_ENABLED=true\n"
            "JIEJING_VAULT_PROVIDER=tencent_ssm\n"
            "JIEJING_TENCENT_REGION=ap-guangzhou\n"
            "JIEJING_TENCENT_SSM_LIVE_RESOLVE_ENABLED=true\n"
            "JIEJING_TENCENT_SSM_KEYSPACE=jiejing-staging\n"
            "JIEJING_TENCENT_SECRET_ID=UNIT-TENCENT-ID-MUST-NOT-LEAK\n"
            "JIEJING_TENCENT_SECRET_KEY=UNIT-TENCENT-KEY-MUST-NOT-LEAK\n",
            encoding="utf-8",
        )
        secret_path.write_text(
            "JIEJING_VAULT_LIVE_RESOLVE_ENABLED=true\n"
            "JIEJING_EBAY_CLIENT_ID=UNIT-EBAY-CLIENT-ID-MUST-NOT-LEAK\n"
            "JIEJING_EBAY_RU_NAME=UNIT-EBAY-RUNAME-MUST-NOT-LEAK\n"
            "JIEJING_EBAY_CLIENT_SECRET=UNIT-EBAY-CLIENT-SECRET-MUST-NOT-LEAK\n"
            "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE=true\n"
            "JIEJING_EBAY_TOKEN_REFRESH_LIVE=true\n"
            "JIEJING_EBAY_READ_ONLY_LIVE=true\n"
            "JIEJING_ENABLE_HERMES_EBAY_BRIDGE=false\n"
            "JIEJING_EBAY_ACCESS_TOKEN=\n"
            "JIEJING_EBAY_REFRESH_TOKEN=\n",
            encoding="utf-8",
        )
        postgres_path.write_text(
            "JIEJING_DATABASE_ENGINE=postgres\n"
            "JIEJING_DATABASE_ADAPTER=postgres-managed\n"
            "JIEJING_DATABASE_URL=postgresql://unit-test.invalid/jiejing\n"
            "JIEJING_QUEUE_PROVIDER=redis_streams\n"
            "JIEJING_QUEUE_URL=redis://unit-test.invalid/0\n",
            encoding="utf-8",
        )
        configured_check = _run_env_check(
            env_files=(managed_path, secret_path, postgres_path),
            output_root=output_root,
            process_env=safe_process_env,
        )
        report_path = output_root / "staging_env_check_latest.json"
        report_text = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
        combined = (configured_check.stdout or "") + (configured_check.stderr or "") + report_text
        if configured_check.returncode != 0:
            return f"configured three-source env check should pass: {combined[:500]}"
        for sentinel in (
            "UNIT-TENCENT-ID-MUST-NOT-LEAK",
            "UNIT-TENCENT-KEY-MUST-NOT-LEAK",
            "UNIT-EBAY-CLIENT-ID-MUST-NOT-LEAK",
            "UNIT-EBAY-RUNAME-MUST-NOT-LEAK",
            "UNIT-EBAY-CLIENT-SECRET-MUST-NOT-LEAK",
        ):
            if sentinel in combined:
                return "multi-source env check exposed a backend-only value"
    return ""


def _run_env_check(
    *,
    env_files: tuple[Path, ...],
    output_root: Path,
    process_env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    env_args: list[str] = []
    for env_file in env_files:
        env_args.extend(("--env-file", str(env_file)))
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_staging_ebay_oauth_readonly_flow.py"),
            *env_args,
            "--output-root",
            str(output_root),
            "check-env",
        ],
        cwd=str(ROOT),
        env=process_env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )


def _test_prepare_reuses_completed_oauth_without_new_authorization() -> str:
    out = OUT / "idempotent-completed"
    out.mkdir(parents=True, exist_ok=True)
    for path in (out / "context.json", out / "staging_oauth_prepare_latest.json"):
        path.unlink(missing_ok=True)

    spec = importlib.util.spec_from_file_location(
        "jiejing_staging_ebay_oauth_readonly_flow_under_test",
        ROOT / "tools" / "jiejing_staging_ebay_oauth_readonly_flow.py",
    )
    if not spec or not spec.loader:
        return "could not load OAuth flow tool module"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module._login_or_register = lambda args: "test-token"
    module._get_or_create_store = lambda args, token: {
        "store_id": "store_completed",
        "store_name": "Already Authorized Store",
    }
    module._status = lambda *, args, token, context, resources: {
        "status": "callback_completed_ready_for_sync",
        "store_id": "store_completed",
        "oauth_request_id": "oauth_done",
        "state_nonce": "state_done",
        "oauth_latest_status": "callback_exchange_completed",
        "callback_completed": True,
        "preflight": {
            "status": "ready_for_official_read",
            "can_queue_sync": True,
            "token_mode": "backend_jiejing_secret_ref_resolver",
            "blocked_by": [],
            "secret_exposed": False,
        },
    }

    def forbidden_post_json(*args, **kwargs):
        raise AssertionError("prepare must not request a new OAuth authorization URL after callback completion")

    module._post_json = forbidden_post_json
    old_argv = sys.argv
    old_stdout = sys.stdout
    try:
        from io import StringIO

        captured = StringIO()
        sys.stdout = captured
        sys.argv = [
            str(ROOT / "tools" / "jiejing_staging_ebay_oauth_readonly_flow.py"),
            "--base-url",
            "https://staging.example.test",
            "--context",
            str(out / "context.json"),
            "--output-root",
            str(out),
            "prepare",
        ]
        code = module.main()
        stdout = captured.getvalue()
    finally:
        sys.argv = old_argv
        sys.stdout = old_stdout
    if code != 0:
        return "idempotent prepare should succeed after completed callback"
    if "AUTHORIZATION_URL=" in stdout:
        return "idempotent prepare must not print a new authorization URL"
    if "authorization_already_completed_ready_for_sync" not in stdout:
        return "idempotent prepare should say authorization is already completed"
    context = json.loads((out / "context.json").read_text(encoding="utf-8"))
    if context.get("reused_completed_oauth") is not True:
        return "context should record that completed OAuth was reused"
    return ""


def _run_tool(*, port: int, command: str, extra_args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_staging_ebay_oauth_readonly_flow.py"),
            "--base-url",
            f"http://127.0.0.1:{port}",
            "--email",
            "flow-tool@example.com",
            "--password",
            PASSWORD_SENTINEL,
            "--company-name",
            "Flow Tool Company",
            "--store-name",
            "Flow Tool eBay Store",
            "--context",
            str(OUT / "context.json"),
            "--output-root",
            str(OUT),
            *extra_args,
            command,
        ],
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=60,
        check=False,
    )


def _wait_for_health(base_url: str) -> None:
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2) as response:
                if json.loads(response.read().decode("utf-8")).get("status") == "ok":
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("backend did not become healthy")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    raise SystemExit(main())

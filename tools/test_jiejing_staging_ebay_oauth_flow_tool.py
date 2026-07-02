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


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "test-staging-ebay-oauth-flow-tool"
PASSWORD_SENTINEL = "FLOW-TOOL-PASSWORD-MUST-NOT-PERSIST"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
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

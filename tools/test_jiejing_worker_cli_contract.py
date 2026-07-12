#!/usr/bin/env python3
"""Contract checks for the standalone Jiejing SaaS worker process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-worker-cli-contract-test"
WORKER = ROOT / "tools" / "jiejing_worker_cli.py"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("saas.sqlite", "runtime.sqlite"):
        path = OUT / name
        if path.exists():
            path.unlink()
    compile_result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(WORKER)],
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if compile_result.returncode != 0:
        return fail("worker CLI does not compile: " + compile_result.stderr[-400:])

    status = _run_worker("status")
    if status.returncode != 0:
        return fail("worker status command failed: " + status.stderr[-400:])
    try:
        payload = json.loads(status.stdout)
    except json.JSONDecodeError as exc:
        return fail(f"worker status did not return JSON: {exc}")
    if payload.get("process") != "background_worker":
        return fail("worker status must identify the background worker process")
    if payload.get("real_platform_writes_enabled") is not False:
        return fail("worker status must keep real platform writes disabled")
    if "secret" in status.stdout.lower() and "secret_exposed" not in status.stdout:
        return fail("worker status may only mention secrets through the secret_exposed safety flag")

    once = _run_worker("run-once")
    if once.returncode != 0:
        return fail("worker run-once should exit cleanly when queue is idle: " + once.stderr[-400:])
    idle_payload = json.loads(once.stdout)
    if idle_payload.get("status") != "idle":
        return fail("worker run-once with an empty local queue should return idle")
    if idle_payload.get("real_platform_writes_enabled") is not False:
        return fail("worker run-once must keep real platform writes disabled")

    for compose_name in (
        "deploy/docker-compose.public-staging.yml",
        "deploy/docker-compose.public-https-staging.yml",
        "deploy/docker-compose.staging-infra.yml",
    ):
        text = (ROOT / compose_name).read_text(encoding="utf-8")
        if "jiejing-worker:" not in text:
            return fail(f"{compose_name} must define a jiejing-worker service")
        block = _service_block(text, "jiejing-worker")
        required = [
            "tools/jiejing_worker_cli.py",
            "run-loop",
            "--idle-sleep",
            "restart: unless-stopped",
            "env_file:",
            "volumes:",
        ]
        missing = [marker for marker in required if marker not in block]
        if missing:
            return fail(f"{compose_name} worker service missing markers: {','.join(missing)}")
        if "ports:" in block or "expose:" in block:
            return fail(f"{compose_name} worker service must not expose public ports")
        if "--json-lines" in block:
            return fail(f"{compose_name} worker service must not print idle JSON lines forever")
    for compose_name in (
        "deploy/docker-compose.public-staging.yml",
        "deploy/docker-compose.public-https-staging.yml",
    ):
        text = (ROOT / compose_name).read_text(encoding="utf-8")
        for service in ("jiejing-saas", "jiejing-worker"):
            block = _service_block(text, service)
            for marker in (
                'JIEJING_MEDIA_LIVE_PROVIDER_ENABLED: "true"',
                'JIEJING_MEDIA_LIVE_VIDEO_ENABLED: "true"',
            ):
                if marker not in block:
                    return fail(f"{compose_name} {service} must share the explicit staging media gate: {marker}")
    print(
        json.dumps(
            {
                "worker_cli_contract": "pass",
                "compose_worker_services": 3,
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("PASS jiejing_worker_cli_contract")
    return 0


def _run_worker(command: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["JIEJING_SAAS_ENV"] = "local_dev"
    env["JIEJING_DATABASE_ENGINE"] = "sqlite"
    env["JIEJING_DATABASE_ADAPTER"] = "sqlite"
    env["JIEJING_QUEUE_PROVIDER"] = "local_worker"
    env.pop("JIEJING_DATABASE_URL", None)
    env.pop("JIEJING_QUEUE_URL", None)
    return subprocess.run(
        [
            sys.executable,
            str(WORKER),
            "--db",
            str(OUT / "saas.sqlite"),
            "--runtime-db",
            str(OUT / "runtime.sqlite"),
            "--output-root",
            str(OUT),
            command,
        ],
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
        check=False,
        timeout=60,
    )


def _service_block(text: str, service: str) -> str:
    lines = text.splitlines()
    marker = f"  {service}:"
    start_index = None
    for index, line in enumerate(lines):
        if line == marker:
            start_index = index
            break
    if start_index is None:
        return ""
    block = [lines[start_index]]
    for line in lines[start_index + 1 :]:
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            break
        block.append(line)
    return "\n".join(block)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Contract checks for the standalone Jiejing SaaS worker process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "output" / "jiejing-worker-cli-contract-test"
WORKER = ROOT / "tools" / "jiejing_worker_cli.py"

from jiejing_saas.monitoring import (  # noqa: E402
    ProviderMonitoringScheduler,
    export_provider_monitoring_aggregate_to_cls,
)
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from tools.jiejing_worker_cli import ProviderMonitoringBackgroundRunner  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


class _Repeated:
    def __init__(self, factory):  # noqa: ANN001
        self.factory = factory
        self.items = []

    def add(self):  # noqa: ANN201
        item = self.factory()
        self.items.append(item)
        return item


class _FakeContent:
    key = ""
    value = ""


class _FakeLog:
    def __init__(self) -> None:
        self.time = 0
        self.contents = _Repeated(_FakeContent)


class _FakeGroup:
    def __init__(self) -> None:
        self.logs = _Repeated(_FakeLog)


class _FakeGroupList:
    def __init__(self) -> None:
        self.logGroupList = _Repeated(_FakeGroup)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    disabled_scheduler = ProviderMonitoringScheduler(
        repository=None,
        environment="test",
        enabled=False,
    )
    if disabled_scheduler.run_once() != {
        "status": "disabled",
        "external_provider_action_triggered": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }:
        return fail("disabled passive provider scheduler must do no repository or network work")
    for name in (
        "saas.sqlite",
        "runtime.sqlite",
        "provider-monitor.sqlite",
        "provider-monitor-query-failure.sqlite",
        "provider-monitor-background.sqlite",
    ):
        path = OUT / name
        if path.exists():
            path.unlink()
    monitor_repo = SaaSRepository(OUT / "provider-monitor.sqlite")
    exported_events: list[dict] = []
    scheduler = ProviderMonitoringScheduler(
        repository=monitor_repo,
        environment="test",
        exporter=lambda event: exported_events.append(event) or True,
        enabled=True,
        interval_seconds=300,
        reliability_window_minutes=30,
        cost_window_hours=24,
        warning_minor=10_000,
        critical_minor=20_000,
        owner_nonce="worker-a",
    )
    scheduled = scheduler.run_once(
        now_utc=datetime(2026, 7, 17, tzinfo=timezone.utc),
        now_epoch=1000,
    )
    if scheduled.get("status") != "exported":
        return fail(f"passive provider scheduler did not complete one aggregate export: {scheduled}")
    if scheduled.get("reliability_status") != "insufficient_data" or scheduled.get("cost_status") != "healthy":
        return fail(f"empty provider telemetry must stay insufficient_data with zero covered cost: {scheduled}")
    if len(exported_events) != 1 or exported_events[0].get("probe") is not False:
        return fail(f"provider scheduler must export exactly one real aggregate event: {exported_events}")
    competing_scheduler = ProviderMonitoringScheduler(
        repository=monitor_repo,
        environment="test",
        exporter=lambda event: exported_events.append(event) or True,
        enabled=True,
        interval_seconds=300,
        warning_minor=10_000,
        critical_minor=20_000,
        owner_nonce="worker-b",
    )
    contended = competing_scheduler.run_once(
        now_utc=datetime(2026, 7, 17, tzinfo=timezone.utc),
        now_epoch=1001,
    )
    if contended.get("status") != "skipped_lease_contended" or len(exported_events) != 1:
        return fail(f"two workers must not duplicate one monitoring interval: {contended}")
    def failing_exporter(_event):  # noqa: ANN001, ANN202
        raise TimeoutError("raw CLS error must not escape")

    failing_scheduler = ProviderMonitoringScheduler(
        repository=monitor_repo,
        environment="test",
        exporter=failing_exporter,
        enabled=True,
        interval_seconds=300,
        warning_minor=10_000,
        critical_minor=20_000,
        owner_nonce="worker-c",
    )
    export_failed = failing_scheduler.run_once(
        now_utc=datetime(2026, 7, 17, 0, 5, 1, tzinfo=timezone.utc),
        now_epoch=1301,
    )
    if export_failed.get("status") != "export_failed" or "raw CLS error" in str(export_failed):
        return fail(f"CLS export failure must be contained and sanitized: {export_failed}")
    failed_state = monitor_repo.provider_monitoring_state()
    if failed_state.get("last_evaluated_at") != "2026-07-17T00:05:01+00:00":
        return fail(f"successful evaluation timestamp was not retained after export failure: {failed_state}")
    if failed_state.get("last_exported_at") != "2026-07-17T00:00:00+00:00":
        return fail(f"failed export must not fabricate fresh export evidence: {failed_state}")
    broken_repo = SaaSRepository(OUT / "provider-monitor-query-failure.sqlite")
    broken_repo.initialize()
    with broken_repo._connect() as connection:
        connection.execute("alter table provider_cost_ledger rename column cost_json to broken_cost_json")
    query_failure_scheduler = ProviderMonitoringScheduler(
        repository=broken_repo,
        environment="test",
        exporter=lambda _event: True,
        enabled=True,
        warning_minor=10_000,
        critical_minor=20_000,
        owner_nonce="worker-query-failure",
    )
    query_failed = query_failure_scheduler.run_once(
        now_utc=datetime(2026, 7, 17, 0, 10, tzinfo=timezone.utc),
        now_epoch=2000,
    )
    if query_failed.get("status") != "query_failed":
        return fail(f"monitoring query failure must not escape the scheduler: {query_failed}")
    query_failure_state = broken_repo.provider_monitoring_state()
    if query_failure_state.get("last_evaluated_at") or query_failure_state.get("last_exported_at"):
        return fail(f"query failure must not fabricate evaluation or export freshness: {query_failure_state}")
    if query_failure_state.get("last_outcome") != "query_failed":
        return fail(f"query failure outcome was not persisted safely: {query_failure_state}")

    release_export = threading.Event()
    export_started = threading.Event()

    def slow_exporter(_event):  # noqa: ANN001, ANN202
        export_started.set()
        release_export.wait(timeout=5)
        return True

    background_scheduler = ProviderMonitoringScheduler(
        repository=SaaSRepository(OUT / "provider-monitor-background.sqlite"),
        environment="test",
        exporter=slow_exporter,
        enabled=True,
        warning_minor=10_000,
        critical_minor=20_000,
        owner_nonce="worker-background",
    )
    background = ProviderMonitoringBackgroundRunner(background_scheduler)
    started = time.monotonic()
    submitted = background.tick()
    elapsed = time.monotonic() - started
    if submitted.get("status") != "submitted" or elapsed >= 0.2:
        release_export.set()
        background.shutdown()
        return fail(f"monitoring evaluation must be submitted without blocking queue work: {submitted}, {elapsed}")
    if not export_started.wait(timeout=2):
        release_export.set()
        background.shutdown()
        return fail("background provider evaluation did not reach the CLS boundary")
    if background.tick().get("status") != "in_progress":
        release_export.set()
        background.shutdown()
        return fail("worker must not submit a second monitoring future while one is active")
    release_export.set()
    deadline = time.monotonic() + 2
    finished = {}
    while time.monotonic() < deadline:
        finished = background.tick()
        if finished.get("status") == "completed":
            break
        time.sleep(0.01)
    background.shutdown()
    if finished.get("result", {}).get("status") != "exported":
        return fail(f"background provider evaluation did not complete safely: {finished}")
    cls_env = {
        "JIEJING_CLS_ENABLED": "true",
        "JIEJING_CLS_REGION": "ap-guangzhou",
        "JIEJING_CLS_TOPIC_ID": "fixture-topic",
        "JIEJING_TENCENT_SECRET_ID": "fixture-id",
        "JIEJING_TENCENT_SECRET_KEY": "fixture-value",
    }
    previous_cls_env = {key: os.environ.get(key) for key in cls_env}
    captured_cls: dict = {}

    class FakeLogClient:
        def put_log_raw(self, topic_id, packet):  # noqa: ANN001, ANN201
            captured_cls["topic_id"] = topic_id
            captured_cls["packet"] = packet
            return object()

    def fake_client_factory(endpoint, region, _access_id, _access_key):  # noqa: ANN001, ANN202
        captured_cls["endpoint"] = endpoint
        captured_cls["region"] = region
        captured_cls["client"] = FakeLogClient()
        return captured_cls["client"]

    try:
        os.environ.update(cls_env)
        exported = export_provider_monitoring_aggregate_to_cls(
            exported_events[0],
            client_factory=fake_client_factory,
            message_factory=_FakeGroupList,
        )
    finally:
        for key, value in previous_cls_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    if getattr(captured_cls.get("client"), "timeout", None) != 5:
        return fail(f"CLS uploader must use a bounded request timeout: {captured_cls}")
    if (
        exported is not True
        or captured_cls.get("endpoint") != "https://cls.tencentcloudapi.com"
        or captured_cls.get("region") != "ap-guangzhou"
    ):
        return fail(f"official CLS upload adapter did not separate the CloudAPI endpoint and region: {captured_cls}")
    packet = captured_cls.get("packet")
    groups = packet.logGroupList.items if packet is not None else []
    logs = groups[0].logs.items if groups else []
    contents = {item.key: item.value for item in (logs[0].contents.items if logs else [])}
    if contents.get("event_type") != "jiejing_provider_monitor_aggregate" or contents.get("probe") != "false":
        return fail(f"CLS upload did not preserve the flat aggregate contract: {contents}")
    if set(contents) != set(exported_events[0]):
        return fail(f"CLS upload added or dropped aggregate keys: {contents}")
    requirements = (ROOT / "requirements.saas.txt").read_text(encoding="utf-8")
    if "tencentcloud-cls-sdk-python" in requirements:
        return fail("runtime must not retain the legacy CLS SDK that pins vulnerable protobuf 3.x")
    if "tencentcloud-sdk-python-cls>=3.0,<4" not in requirements or "protobuf>=5.29.5,<6" not in requirements:
        return fail("runtime must use Tencent CloudAPI CLS with a patched protobuf runtime")
    dockerfile = (ROOT / "Dockerfile.saas").read_text(encoding="utf-8")
    runtime_stage = dockerfile.find(" AS jiejing-runtime")
    if min(
        dockerfile.find(" AS jiejing-wheel-builder"),
        dockerfile.find("apt-get install -y --no-install-recommends build-essential"),
        dockerfile.find("pip wheel --use-pep517 --no-build-isolation --require-hashes --no-cache-dir --wheel-dir /wheels -r requirements.saas.lock.txt"),
        dockerfile.find("COPY --from=jiejing-wheel-builder /wheels /wheels"),
        runtime_stage,
    ) < 0:
        return fail("Docker image must build the CLS SDK source dependency in a disposable wheel stage")
    if "build-essential" in dockerfile[runtime_stage:]:
        return fail("runtime image must not retain the compiler toolchain used for the CLS SDK")
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
    maintenance = payload.get("domestic_billing_maintenance") or {}
    if maintenance.get("enabled") is not True or maintenance.get("query_only") is not True:
        return fail(f"worker status must expose query-only billing maintenance: {maintenance}")
    if maintenance.get("triggers_real_charge") is not False or maintenance.get("triggers_real_refund") is not False:
        return fail(f"billing maintenance must never move money: {maintenance}")
    if maintenance.get("max_queries_per_run") != 50:
        return fail(f"billing maintenance must expose the bounded global query budget: {maintenance}")
    provider_monitoring_status = payload.get("provider_monitoring") or {}
    if provider_monitoring_status.get("enabled") is not True or provider_monitoring_status.get("interval_seconds") != 300:
        return fail(f"worker status must expose the bounded passive monitoring schedule: {provider_monitoring_status}")
    if provider_monitoring_status.get("calls_business_provider") is not False:
        return fail(f"passive provider scheduler must never call a business provider: {provider_monitoring_status}")
    if "secret" in status.stdout.lower() and "secret_exposed" not in status.stdout:
        return fail("worker status may only mention secrets through the secret_exposed safety flag")
    worker_source = WORKER.read_text(encoding="utf-8")
    for marker in (
        "ProviderMonitoringBackgroundRunner(",
        "ProviderMonitoringScheduler(",
        "provider_monitoring.tick()",
        "provider_monitoring.shutdown()",
        "MediaSourceAssetStore(",
        "media_source_asset_store=media_source_assets",
    ):
        if marker not in worker_source:
            return fail(f"worker loop is missing passive monitoring background wiring: {marker}")

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
            'JIEJING_DOMESTIC_BILLING_MAINTENANCE_ENABLED: "true"',
            'JIEJING_DOMESTIC_BILLING_AUTO_RECONCILE_ENABLED: "true"',
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
    secret_env_template = (ROOT / "deploy/jiejing-saas.staging-oauth.env.example").read_text(encoding="utf-8")
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
                if marker in block:
                    return fail(f"{compose_name} {service} must not override the secret-owned staging media gate: {marker}")
    for marker in (
        "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED=true",
        "JIEJING_MEDIA_LIVE_VIDEO_ENABLED=true",
    ):
        if marker not in secret_env_template:
            return fail(f"secret runtime env template must preserve the explicit staging media gate: {marker}")
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
    env["JIEJING_DOMESTIC_BILLING_MAINTENANCE_ENABLED"] = "true"
    env["JIEJING_DOMESTIC_BILLING_AUTO_RECONCILE_ENABLED"] = "false"
    env["JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED"] = "true"
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

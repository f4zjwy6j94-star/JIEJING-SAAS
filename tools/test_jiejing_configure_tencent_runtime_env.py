#!/usr/bin/env python3
"""Regression checks for the private Tencent runtime env configurator."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-configure-tencent-runtime-env-test"
TOOL = ROOT / "tools" / "jiejing_configure_tencent_runtime_env.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.jiejing_configure_tencent_runtime_env import (  # noqa: E402
    PROVIDER_ALARM_INDEX_KEYS,
    PROVIDER_COST_ALARM_NAME,
    PROVIDER_LATENCY_ALARM_NAME,
    operate_provider_cls_alarms,
    operate_provider_cls_index,
    provider_alarm_verification_updates,
    provider_alarm_specs,
    verify_provider_cls_probe,
    _provider_control_values,
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    index_contract_error = _test_provider_index_operator()
    if index_contract_error:
        return fail(index_contract_error)
    alarm_contract_error = _test_provider_alarm_operator()
    if alarm_contract_error:
        return fail(alarm_contract_error)
    env_example = (ROOT / "deploy" / "jiejing-saas.tencent-managed.env.example").read_text(encoding="utf-8")
    for marker in (
        "JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED=false",
        "JIEJING_PROVIDER_MONITOR_INTERVAL_SECONDS=300",
        "JIEJING_PROVIDER_MONITOR_WINDOW_MINUTES=30",
        "JIEJING_PROVIDER_MONITOR_COST_WINDOW_HOURS=24",
        "JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR=\n",
        "JIEJING_PROVIDER_DAILY_COST_CRITICAL_MINOR=\n",
        "JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT=\n",
        "JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT=\n",
    ):
        if marker not in env_example:
            return fail(f"Tencent env example must preserve blocked passive-monitoring defaults: {marker.strip()}")
    OUT.mkdir(parents=True, exist_ok=True)
    env_path = OUT / "tencent-managed.env"
    env_path.write_text(
        "\n".join(
            [
                "JIEJING_DATABASE_ENGINE=postgres",
                "JIEJING_DATABASE_URL=postgresql://jiejing:DB_SECRET_SHOULD_NOT_LEAK@172.16.0.12:5432/jiejing",
                "JIEJING_QUEUE_URL=redis://:REDIS_SECRET_SHOULD_NOT_LEAK@172.16.0.15:6379/0",
                "JIEJING_VAULT_PROVIDER=vault",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["JIEJING_TEST_TENCENT_ID"] = "TENCENT_ID_SHOULD_NOT_LEAK"
    env["JIEJING_TEST_TENCENT_KEY"] = "TENCENT_KEY_SHOULD_NOT_LEAK"

    apply_cmd = [
        sys.executable,
        str(TOOL),
        "--env-file",
        str(env_path),
        "--apply",
        "--enable-ssm",
        "--tencent-secret-id-env",
        "JIEJING_TEST_TENCENT_ID",
        "--tencent-secret-key-env",
        "JIEJING_TEST_TENCENT_KEY",
        "--enable-cos",
        "--cos-bucket",
        "jiejing-staging-backup-1423900563",
        "--record-cos-probe-now",
        "--enable-cls",
        "--cls-logset-id",
        "logset-jiejing-staging",
        "--cls-topic-id",
        "topic-saas-backend",
        "--cls-alert-policy-configured",
        "--record-cls-probe-now",
        "--cls-probe-max-age-hours",
        "24",
        "--backup-policy-configured",
        "--backup-alerts-configured",
        "--vault-backup-policy-configured",
        "--record-restore-drill-now",
        "--production-release-charge-flag-reviewed",
        "--production-release-real-write-flag-reviewed",
        "--production-support-refund-policy-reviewed",
        "--production-merchant-surface-copy-scan-passed",
        "--enable-managed-db-queue-live-checks",
    ]
    applied = subprocess.run(apply_cmd, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    if applied.returncode != 0:
        return fail(applied.stderr or applied.stdout)
    backup_paths = list(OUT.glob("tencent-managed.env.bak.*"))
    if not backup_paths:
        return fail("configurator must create a private rollback copy before replacing the env file")
    if list(OUT.glob(".tencent-managed.env.tmp.*")):
        return fail("configurator must not leave private temporary env files behind")
    if os.name != "nt":
        for private_path in [env_path, *backup_paths]:
            if private_path.stat().st_mode & 0o077:
                return fail(f"private env and rollback copies must be mode 0600: {private_path.name}")
    combined = applied.stdout + applied.stderr
    for forbidden in (
        "TENCENT_ID_SHOULD_NOT_LEAK",
        "TENCENT_KEY_SHOULD_NOT_LEAK",
        "DB_SECRET_SHOULD_NOT_LEAK",
        "REDIS_SECRET_SHOULD_NOT_LEAK",
    ):
        if forbidden in combined:
            return fail(f"configurator leaked secret marker {forbidden}")

    text = env_path.read_text(encoding="utf-8")
    if "JIEJING_VAULT_PROVIDER=vault" not in text:
        return fail("configurator must not switch Vault provider unless explicitly requested")
    if "JIEJING_TENCENT_SECRET_ID=TENCENT_ID_SHOULD_NOT_LEAK" not in text:
        return fail("configurator did not write Tencent SecretId to private env")
    if "JIEJING_COS_BUCKET=jiejing-staging-backup-1423900563" not in text:
        return fail("configurator did not write COS bucket")
    if "JIEJING_CLS_LOGSET_ID=logset-jiejing-staging" not in text:
        return fail("configurator did not write CLS logset")
    if "JIEJING_CLS_PROBE_MAX_AGE_HOURS=24" not in text:
        return fail("configurator did not persist the explicit CLS evidence freshness threshold")
    if "JIEJING_POSTGRES_DRIVER_CHECK_LIVE=true" not in text or "JIEJING_REDIS_DRIVER_CHECK_LIVE=true" not in text:
        return fail("configurator did not write managed database/queue live-check flags")
    for reviewed_key in (
        "JIEJING_PRODUCTION_RELEASE_CHARGE_FLAG_REVIEWED",
        "JIEJING_PRODUCTION_RELEASE_REAL_WRITE_FLAG_REVIEWED",
        "JIEJING_PRODUCTION_SUPPORT_REFUND_POLICY_REVIEWED",
        "JIEJING_PRODUCTION_MERCHANT_SURFACE_COPY_SCAN_PASSED",
    ):
        if f"{reviewed_key}=true" not in text:
            return fail(f"configurator did not persist reviewed production evidence: {reviewed_key}")

    vault_artifact_id = "vault-backups/20260814/isolated-restore-proof.enc"
    env["JIEJING_TEST_VAULT_BACKUP_ARTIFACT_ID"] = vault_artifact_id
    vault_evidence = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--env-file",
            str(env_path),
            "--apply",
            "--record-vault-recovery-evidence",
            "--vault-backup-artifact-id-env",
            "JIEJING_TEST_VAULT_BACKUP_ARTIFACT_ID",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if vault_evidence.returncode != 0:
        return fail(vault_evidence.stderr or vault_evidence.stdout)
    vault_evidence_output = vault_evidence.stdout + vault_evidence.stderr
    if vault_artifact_id in vault_evidence_output:
        return fail("Vault recovery evidence recording must not print the private backup artifact identifier")
    vault_text = env_path.read_text(encoding="utf-8")
    for marker in (
        f"JIEJING_VAULT_BACKUP_ARTIFACT_ID={vault_artifact_id}",
        "JIEJING_VAULT_BACKUP_POLICY_CONFIGURED=true",
        "JIEJING_VAULT_RESTORE_MANUAL_UNSEAL_VERIFIED=true",
        "JIEJING_VAULT_RESTORE_SENTINEL_RESOLVE_VERIFIED=true",
        "JIEJING_VAULT_RESTORE_DRILL_LAST_AT=",
    ):
        if marker not in vault_text:
            return fail(f"configurator did not persist completed Vault recovery evidence: {marker}")

    before_invalid_cli = env_path.read_text(encoding="utf-8")
    invalid_cli = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--env-file",
            str(env_path),
            "--apply",
            "--record-cls-probe-now",
            "--cls-probe-max-age-hours",
            "nan",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if invalid_cli.returncode == 0:
        return fail("configurator must reject a non-finite CLI freshness threshold")
    if env_path.read_text(encoding="utf-8") != before_invalid_cli:
        return fail("invalid CLS freshness CLI input must not modify the private env")

    before_unconfirmed_alarm_apply = env_path.read_text(encoding="utf-8")
    unconfirmed_alarm_apply = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--env-file",
            str(env_path),
            "--apply-provider-alarms",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if unconfirmed_alarm_apply.returncode == 0:
        return fail("provider alarm apply must require the separate --apply confirmation")
    try:
        unconfirmed_payload = json.loads(unconfirmed_alarm_apply.stdout)
    except json.JSONDecodeError:
        return fail("unconfirmed provider alarm apply must return a safe structured blocker")
    if unconfirmed_payload != {
        "status": "blocked",
        "blockers": ["provider_alarm_apply_confirmation_missing"],
        "secret_exposed": False,
    }:
        return fail(f"unconfirmed provider alarm apply returned an unsafe blocker: {unconfirmed_payload}")
    if env_path.read_text(encoding="utf-8") != before_unconfirmed_alarm_apply:
        return fail("unconfirmed provider alarm apply must not modify the private env")

    before_unconfirmed_index_apply = env_path.read_text(encoding="utf-8")
    unconfirmed_index_apply = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--env-file",
            str(env_path),
            "--apply-provider-index",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if unconfirmed_index_apply.returncode == 0:
        return fail("provider index apply must require the separate --apply confirmation")
    try:
        unconfirmed_index_payload = json.loads(unconfirmed_index_apply.stdout)
    except json.JSONDecodeError:
        return fail("unconfirmed provider index apply must return a safe structured blocker")
    if unconfirmed_index_payload != {
        "status": "blocked",
        "blockers": ["provider_index_apply_confirmation_missing"],
        "secret_exposed": False,
    }:
        return fail(f"unconfirmed provider index apply returned an unsafe blocker: {unconfirmed_index_payload}")
    if env_path.read_text(encoding="utf-8") != before_unconfirmed_index_apply:
        return fail("unconfirmed provider index apply must not modify the private env")

    conflicting_control_modes = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--env-file",
            str(env_path),
            "--provider-index-status",
            "--provider-alarm-status",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if conflicting_control_modes.returncode == 0:
        return fail("provider control operations must be mutually exclusive")
    try:
        conflicting_payload = json.loads(conflicting_control_modes.stdout)
    except json.JSONDecodeError:
        return fail("conflicting provider control operations must return a safe structured blocker")
    if conflicting_payload != {
        "status": "blocked",
        "blockers": ["select_one_provider_control_mode"],
        "secret_exposed": False,
    }:
        return fail(f"conflicting provider control operations returned an unsafe blocker: {conflicting_payload}")

    status = subprocess.run(
        [sys.executable, str(TOOL), "--env-file", str(env_path), "--status"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if status.returncode != 0:
        return fail(status.stderr or status.stdout)
    for forbidden in (
        "TENCENT_ID_SHOULD_NOT_LEAK",
        "TENCENT_KEY_SHOULD_NOT_LEAK",
        "DB_SECRET_SHOULD_NOT_LEAK",
        "REDIS_SECRET_SHOULD_NOT_LEAK",
    ):
        if forbidden in status.stdout + status.stderr:
            return fail(f"status leaked secret marker {forbidden}")
    payload = json.loads(status.stdout)
    if "vault_provider_not_switched_to_tencent_ssm" not in payload.get("blockers", []):
        return fail("status should keep Tencent SSM switch blocked until explicit migration")
    if "tencent_cls_ingestion_live_probe_not_passed" not in payload.get("blockers", []):
        return fail("control-plane CLS probe must not be reported as successful log ingestion")

    ingestion_probe = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--env-file",
            str(env_path),
            "--apply",
            "--record-cls-ingestion-probe-now",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if ingestion_probe.returncode != 0:
        return fail(ingestion_probe.stderr or ingestion_probe.stdout)
    ingested_status = subprocess.run(
        [sys.executable, str(TOOL), "--env-file", str(env_path), "--status"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    ingested_payload = json.loads(ingested_status.stdout)
    if "tencent_cls_ingestion_live_probe_not_passed" in ingested_payload.get("blockers", []):
        return fail("verified CLS ingestion evidence should clear the data-plane probe blocker")
    evidence = ingested_payload.get("cls_probe_evidence", {})
    if evidence.get("max_age_hours") != 24.0:
        return fail(f"redacted status must expose the CLS freshness threshold: {evidence}")
    if evidence.get("control_plane", {}).get("fresh") is not True:
        return fail(f"recent control-plane evidence must be fresh: {evidence}")
    if evidence.get("ingestion", {}).get("fresh") is not True:
        return fail(f"recent ingestion evidence must be fresh: {evidence}")
    for forbidden_field in (
        "JIEJING_CLS_LIVE_PROBE_LAST_AT",
        "JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT",
        "JIEJING_CLS_LOGSET_ID",
        "JIEJING_CLS_TOPIC_ID",
    ):
        if forbidden_field in json.dumps(evidence, ensure_ascii=False):
            return fail(f"derived CLS evidence status must not include raw field {forbidden_field}")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    source_text = env_path.read_text(encoding="utf-8")
    stale_path = OUT / "tencent-managed-stale.env"
    _write_env_variant(
        source_text,
        stale_path,
        {"JIEJING_CLS_LIVE_PROBE_LAST_AT": (now - timedelta(hours=25)).isoformat()},
    )
    stale_result = _status_result(stale_path)
    if stale_result.returncode != 0:
        return fail(stale_result.stderr or stale_result.stdout)
    stale_payload = json.loads(stale_result.stdout)
    if "tencent_cls_live_probe_stale" not in stale_payload.get("blockers", []):
        return fail(f"stale control-plane evidence must block the configurator status: {stale_payload}")

    invalid_path = OUT / "tencent-managed-invalid.env"
    _write_env_variant(
        source_text,
        invalid_path,
        {"JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT": "not-an-iso-timestamp"},
    )
    invalid_result = _status_result(invalid_path)
    if invalid_result.returncode != 0:
        return fail(invalid_result.stderr or invalid_result.stdout)
    invalid_payload = json.loads(invalid_result.stdout)
    if "tencent_cls_ingestion_live_probe_timestamp_invalid" not in invalid_payload.get("blockers", []):
        return fail(f"invalid ingestion evidence must block the configurator status: {invalid_payload}")

    future_path = OUT / "tencent-managed-future.env"
    _write_env_variant(
        source_text,
        future_path,
        {"JIEJING_CLS_LIVE_PROBE_LAST_AT": (now + timedelta(minutes=6)).isoformat()},
    )
    future_result = _status_result(future_path)
    if future_result.returncode != 0:
        return fail(future_result.stderr or future_result.stdout)
    future_payload = json.loads(future_result.stdout)
    if "tencent_cls_live_probe_timestamp_in_future" not in future_payload.get("blockers", []):
        return fail(f"future control-plane evidence must block the configurator status: {future_payload}")

    for invalid_threshold in ("0", "-1", "nan", "inf", "garbage"):
        fallback_path = OUT / f"tencent-managed-fallback-{invalid_threshold.replace('-', 'negative')}.env"
        _write_env_variant(
            source_text,
            fallback_path,
            {
                "JIEJING_CLS_PROBE_MAX_AGE_HOURS": invalid_threshold,
                "JIEJING_CLS_LIVE_PROBE_LAST_AT": (now - timedelta(hours=23)).isoformat(),
                "JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT": (now - timedelta(hours=23)).isoformat(),
            },
        )
        fallback_result = _status_result(fallback_path)
        if fallback_result.returncode != 0:
            return fail(fallback_result.stderr or fallback_result.stdout)
        fallback_payload = json.loads(fallback_result.stdout)
        fallback_evidence = fallback_payload.get("cls_probe_evidence", {})
        if fallback_evidence.get("max_age_hours") != 24.0:
            return fail(f"invalid CLS threshold must fall back to 24 hours: {fallback_evidence}")
        if fallback_evidence.get("control_plane", {}).get("fresh") is not True:
            return fail(f"fallback CLS threshold must keep 23-hour evidence fresh: {fallback_evidence}")

    switch = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--env-file",
            str(env_path),
            "--apply",
            "--switch-vault-provider",
            "--tencent-secret-id-env",
            "JIEJING_TEST_TENCENT_ID",
            "--tencent-secret-key-env",
            "JIEJING_TEST_TENCENT_KEY",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if switch.returncode != 0:
        return fail(switch.stderr or switch.stdout)
    if "JIEJING_VAULT_PROVIDER=tencent_ssm" not in env_path.read_text(encoding="utf-8"):
        return fail("explicit switch should set Tencent SSM provider")

    print("PASS jiejing_configure_tencent_runtime_env")
    return 0


class _FakeClsClient:
    def __init__(
        self,
        *,
        index: dict[str, object],
        alarms: list[dict[str, object]] | None = None,
        persist_writes: bool = True,
        search_results: list[dict[str, object]] | None = None,
    ) -> None:
        self.index = deepcopy(index)
        self.alarms = deepcopy(alarms or [])
        self.persist_writes = persist_writes
        self.search_results = deepcopy(search_results or [])
        self.calls: list[tuple[str, dict[str, object]]] = []

    def DescribeIndex(self, request):  # noqa: ANN001, N802, ANN201
        self.calls.append(("DescribeIndex", deepcopy(request)))
        return deepcopy(self.index)

    def DescribeAlarms(self, request):  # noqa: ANN001, N802, ANN201
        self.calls.append(("DescribeAlarms", deepcopy(request)))
        offset = int(request.get("Offset") or 0)
        limit = int(request.get("Limit") or 100)
        return {"Alarms": deepcopy(self.alarms[offset : offset + limit]), "TotalCount": len(self.alarms)}

    def CreateAlarm(self, request):  # noqa: ANN001, N802, ANN201
        self.calls.append(("CreateAlarm", deepcopy(request)))
        if self.persist_writes:
            alarm = deepcopy(request)
            alarm["AlarmId"] = f"private-alarm-{len(self.alarms) + 1}"
            self.alarms.append(alarm)
        return {"AlarmId": "private-response-id"}

    def ModifyAlarm(self, request):  # noqa: ANN001, N802, ANN201
        self.calls.append(("ModifyAlarm", deepcopy(request)))
        if self.persist_writes:
            alarm_id = request.get("AlarmId")
            for index, alarm in enumerate(self.alarms):
                if alarm.get("AlarmId") == alarm_id:
                    self.alarms[index] = deepcopy(request)
                    break
        return {}

    def ModifyIndex(self, request):  # noqa: ANN001, N802, ANN201
        self.calls.append(("ModifyIndex", deepcopy(request)))
        if self.persist_writes:
            self.index["Status"] = request.get("Status")
            self.index["Rule"] = deepcopy(request.get("Rule") or {})
        return {}

    def SearchLog(self, request):  # noqa: ANN001, N802, ANN201
        self.calls.append(("SearchLog", deepcopy(request)))
        return {"Results": deepcopy(self.search_results)}


def _provider_index(*, missing: set[str] | None = None) -> dict[str, object]:
    configured = sorted(PROVIDER_ALARM_INDEX_KEYS - (missing or set()))
    return {
        "Status": True,
        "Rule": {
            "FullText": None,
            "KeyValue": {"KeyValues": [{"Key": key, "Value": {"Type": "text"}} for key in configured]},
        },
    }


def _request_factory(_model_name: str, payload: dict[str, object]) -> dict[str, object]:
    return deepcopy(payload)


def _test_provider_index_operator() -> str:
    process_topic = "PROCESS_TOPIC_SHOULD_NOT_PRINT"
    previous_topic = os.environ.get("JIEJING_CLS_TOPIC_ID")
    previous_database_url = os.environ.get("JIEJING_DATABASE_URL")
    try:
        os.environ["JIEJING_CLS_TOPIC_ID"] = process_topic
        os.environ["JIEJING_DATABASE_URL"] = "DATABASE_SECRET_SHOULD_NOT_COPY"
        control_values = _provider_control_values({"JIEJING_CLS_LOGSET_ID": "file-logset"})
    finally:
        if previous_topic is None:
            os.environ.pop("JIEJING_CLS_TOPIC_ID", None)
        else:
            os.environ["JIEJING_CLS_TOPIC_ID"] = previous_topic
        if previous_database_url is None:
            os.environ.pop("JIEJING_DATABASE_URL", None)
        else:
            os.environ["JIEJING_DATABASE_URL"] = previous_database_url
    if control_values.get("JIEJING_CLS_TOPIC_ID") != process_topic:
        return "container control mode must accept the allowlisted process environment"
    if control_values.get("JIEJING_CLS_LOGSET_ID") != "file-logset":
        return "private env-file values must remain authoritative when present"
    if "JIEJING_DATABASE_URL" in control_values:
        return "provider control mode must not copy unrelated process environment secrets"

    existing_keys = ["event", "environment", "scope", "status"]
    index = {
        "Status": True,
        "Rule": {
            "FullText": None,
            "KeyValue": {
                "CaseSensitive": False,
                "KeyValues": [
                    {"Key": key, "Value": {"Type": "text", "Tokenizer": "@&?|#=()"}}
                    for key in existing_keys
                ],
            },
        },
    }
    client = _FakeClsClient(index=index)
    status_client = _FakeClsClient(index=index)
    status = operate_provider_cls_index(
        client=status_client,
        request_factory=_request_factory,
        topic_id="private-topic-id",
        mode="status",
    )
    if status.get("status") != "blocked" or "provider_index_required_keys_missing" not in (status.get("blockers") or []):
        return f"provider index status must report missing aggregate keys as blocked: {status}"
    if [name for name, _ in status_client.calls] != ["DescribeIndex"]:
        return f"provider index status must remain read-only: {status_client.calls}"

    result = operate_provider_cls_index(
        client=client,
        request_factory=_request_factory,
        topic_id="private-topic-id",
        mode="dry_run",
    )
    if result.get("status") != "planned" or result.get("add_key_count") != len(PROVIDER_ALARM_INDEX_KEYS):
        return f"provider index dry-run should plan exactly the missing aggregate keys: {result}"
    if result.get("existing_key_count") != len(existing_keys) or result.get("preserves_existing_fields") is not True:
        return f"provider index dry-run must preserve every existing field: {result}"
    if result.get("fulltext_enabled") is not False or result.get("fulltext_will_change") is not False:
        return f"provider index dry-run must keep full-text indexing disabled: {result}"
    if [name for name, _ in client.calls] != ["DescribeIndex"]:
        return f"provider index dry-run must be read-only: {client.calls}"

    apply_client = _FakeClsClient(index=index)
    applied = operate_provider_cls_index(
        client=apply_client,
        request_factory=_request_factory,
        topic_id="private-topic-id",
        mode="apply",
    )
    if applied.get("status") != "verified" or applied.get("index_readback_verified") is not True:
        return f"provider index apply must verify the additive merge by read-back: {applied}"
    call_names = [name for name, _ in apply_client.calls]
    if call_names != ["DescribeIndex", "ModifyIndex", "DescribeIndex"]:
        return f"provider index apply must perform one write followed by one read-back: {call_names}"
    merged_rows = apply_client.index["Rule"]["KeyValue"]["KeyValues"]
    if merged_rows[: len(existing_keys)] != index["Rule"]["KeyValue"]["KeyValues"]:
        return f"provider index apply changed an existing key contract: {merged_rows}"
    if {item.get("Key") for item in merged_rows} != set(existing_keys) | PROVIDER_ALARM_INDEX_KEYS:
        return f"provider index apply must add only the five aggregate keys: {merged_rows}"
    if apply_client.index["Rule"].get("FullText") is not None:
        return "provider index apply must keep full-text indexing disabled"

    wrong_type_index = _provider_index()
    wrong_type_index["Rule"]["KeyValue"]["KeyValues"][0]["Value"]["Type"] = "long"
    wrong_type_client = _FakeClsClient(index=wrong_type_index)
    wrong_type = operate_provider_cls_index(
        client=wrong_type_client,
        request_factory=_request_factory,
        topic_id="private-topic-id",
        mode="apply",
    )
    if "provider_index_required_key_type_mismatch" not in (wrong_type.get("blockers") or []):
        return f"a required provider index key with the wrong type must fail closed: {wrong_type}"
    if any(name == "ModifyIndex" for name, _ in wrong_type_client.calls):
        return f"type drift must block provider index writes: {wrong_type_client.calls}"

    fulltext_index = deepcopy(index)
    fulltext_index["Rule"]["FullText"] = {"Tokenizer": "private-fulltext-contract"}
    fulltext_client = _FakeClsClient(index=fulltext_index)
    fulltext = operate_provider_cls_index(
        client=fulltext_client,
        request_factory=_request_factory,
        topic_id="private-topic-id",
        mode="apply",
    )
    if "provider_index_fulltext_must_remain_disabled" not in (fulltext.get("blockers") or []):
        return f"provider index operator must not silently change full-text state: {fulltext}"
    if any(name == "ModifyIndex" for name, _ in fulltext_client.calls):
        return f"full-text drift must block provider index writes: {fulltext_client.calls}"

    duplicate_index = deepcopy(index)
    duplicate_index["Rule"]["KeyValue"]["KeyValues"].append(
        deepcopy(duplicate_index["Rule"]["KeyValue"]["KeyValues"][0])
    )
    duplicate_client = _FakeClsClient(index=duplicate_index)
    duplicate = operate_provider_cls_index(
        client=duplicate_client,
        request_factory=_request_factory,
        topic_id="private-topic-id",
        mode="apply",
    )
    if "provider_index_duplicate_key_names" not in (duplicate.get("blockers") or []):
        return f"duplicate existing index keys must fail closed: {duplicate}"
    if any(name == "ModifyIndex" for name, _ in duplicate_client.calls):
        return f"duplicate index keys must block provider index writes: {duplicate_client.calls}"

    failed_readback_client = _FakeClsClient(index=index, persist_writes=False)
    failed_readback = operate_provider_cls_index(
        client=failed_readback_client,
        request_factory=_request_factory,
        topic_id="private-topic-id",
        mode="apply",
    )
    if failed_readback.get("status") != "blocked" or failed_readback.get("index_readback_verified") is not False:
        return f"failed provider index read-back must never report verification: {failed_readback}"
    safe_dump = json.dumps(failed_readback, ensure_ascii=False)
    if "private-topic-id" in safe_dump or failed_readback.get("resource_ids_exposed") is not False:
        return f"provider index output exposed a private cloud identifier: {safe_dump}"
    return ""


def _test_provider_alarm_operator() -> str:
    logset_id = "private-logset-id"
    topic_id = "private-topic-id"
    notice_id = "private-notice-id"
    specs = provider_alarm_specs(logset_id=logset_id, topic_id=topic_id, notice_id=notice_id)
    for key, alarm in specs.items():
        query = alarm["AlarmTargets"][0]["Query"]
        if 'probe:"false"' not in query:
            return f"{key} alarm must explicitly exclude probe events"
        expected_status = "reliability_status" if key == "latency" else "cost_status"
        if expected_status not in query or "attention" not in query or "critical" not in query:
            return f"{key} alarm query is missing its attention/critical contract"

    read_client = _FakeClsClient(index=_provider_index())
    status = operate_provider_cls_alarms(
        client=read_client,
        request_factory=_request_factory,
        logset_id=logset_id,
        topic_id=topic_id,
        mode="status",
    )
    if any(name not in {"DescribeIndex", "DescribeAlarms"} for name, _ in read_client.calls):
        return f"provider alarm status must be read-only: {read_client.calls}"
    if status.get("cloud_write_performed") is not False:
        return f"provider alarm status must not report a write: {status}"

    dry_client = _FakeClsClient(index=_provider_index())
    dry_run = operate_provider_cls_alarms(
        client=dry_client,
        request_factory=_request_factory,
        logset_id=logset_id,
        topic_id=topic_id,
        notice_id=notice_id,
        mode="dry_run",
    )
    if {item.get("action") for item in dry_run.get("alarms", [])} != {"create"}:
        return f"empty alarm inventory should plan two creates: {dry_run}"
    if any(name not in {"DescribeIndex", "DescribeAlarms"} for name, _ in dry_client.calls):
        return f"provider alarm dry-run must be read-only: {dry_client.calls}"

    apply_client = _FakeClsClient(index=_provider_index())
    applied = operate_provider_cls_alarms(
        client=apply_client,
        request_factory=_request_factory,
        logset_id=logset_id,
        topic_id=topic_id,
        notice_id=notice_id,
        mode="apply",
    )
    if applied.get("status") != "verified" or applied.get("alarm_readback_verified") is not True:
        return f"provider alarms must be read back after create: {applied}"
    call_names = [name for name, _ in apply_client.calls]
    if call_names.count("CreateAlarm") != 2 or call_names[-1] != "DescribeAlarms":
        return f"apply must create two alarms and then read them back: {call_names}"
    safe_dump = json.dumps(applied, ensure_ascii=False)
    for forbidden in (logset_id, topic_id, notice_id, "private-alarm-1", 'event_type:"'):
        if forbidden in safe_dump:
            return f"provider alarm operator output exposed private cloud/query data: {forbidden}"
    if applied.get("notification_test_sent") is not False or applied.get("index_modified") is not False:
        return f"provider alarm apply must not send notifications or rewrite the index: {applied}"
    evidence_updates = provider_alarm_verification_updates(applied, verified_at="2026-07-17T00:00:00+00:00")
    if set(evidence_updates) != {
        "JIEJING_CLS_ALERT_POLICY_CONFIGURED",
        "JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT",
        "JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT",
    }:
        return f"verified readback should produce only the approved env evidence keys: {evidence_updates}"

    apply_client.alarms[1]["Status"] = False
    modify_start = len(apply_client.calls)
    modified = operate_provider_cls_alarms(
        client=apply_client,
        request_factory=_request_factory,
        logset_id=logset_id,
        topic_id=topic_id,
        notice_id=notice_id,
        mode="apply",
    )
    modify_calls = [name for name, _ in apply_client.calls[modify_start:]]
    if modify_calls.count("ModifyAlarm") != 1 or modified.get("alarm_readback_verified") is not True:
        return f"one drifted alarm should produce one verified modify: {modify_calls} {modified}"

    monitor_notice_alarms = deepcopy(apply_client.alarms)
    monitor_notice_alarms[0].pop("AlarmNoticeIds", None)
    monitor_notice_alarms[0]["MonitorNotice"] = {"NoticeId": "private-monitor-notice"}
    monitor_notice_alarms[0]["Status"] = False
    monitor_notice_client = _FakeClsClient(index=_provider_index(), alarms=monitor_notice_alarms)
    monitor_notice_result = operate_provider_cls_alarms(
        client=monitor_notice_client,
        request_factory=_request_factory,
        logset_id=logset_id,
        topic_id=topic_id,
        notice_id=notice_id,
        mode="apply",
    )
    monitor_notice_modifies = [request for name, request in monitor_notice_client.calls if name == "ModifyAlarm"]
    if monitor_notice_result.get("alarm_readback_verified") is not True or len(monitor_notice_modifies) != 1:
        return f"existing MonitorNotice route should be preserved during modify: {monitor_notice_result}"
    if "MonitorNotice" not in monitor_notice_modifies[0] or "AlarmNoticeIds" in monitor_notice_modifies[0]:
        return f"modify must preserve the existing notice route type: {monitor_notice_modifies[0]}"

    duplicate_client = _FakeClsClient(index=_provider_index(), alarms=apply_client.alarms)
    duplicate_client.alarms.append(deepcopy(duplicate_client.alarms[0]))
    duplicate = operate_provider_cls_alarms(
        client=duplicate_client,
        request_factory=_request_factory,
        logset_id=logset_id,
        topic_id=topic_id,
        notice_id=notice_id,
        mode="apply",
    )
    if "provider_latency_alarm_duplicate_name" not in (duplicate.get("blockers") or []):
        return f"duplicate exact alarm names must block apply: {duplicate}"
    if any(name in {"CreateAlarm", "ModifyAlarm"} for name, _ in duplicate_client.calls):
        return f"duplicate alarm inventory must remain read-only: {duplicate_client.calls}"

    missing_index_client = _FakeClsClient(index=_provider_index(missing={"probe"}))
    missing_index = operate_provider_cls_alarms(
        client=missing_index_client,
        request_factory=_request_factory,
        logset_id=logset_id,
        topic_id=topic_id,
        notice_id=notice_id,
        mode="apply",
    )
    if missing_index.get("index", {}).get("missing_keys") != ["probe"]:
        return f"missing index keys must be named without rewriting the index: {missing_index}"
    if any(name in {"CreateAlarm", "ModifyAlarm"} for name, _ in missing_index_client.calls):
        return f"incomplete index contract must block alarm writes: {missing_index_client.calls}"

    failed_readback_client = _FakeClsClient(index=_provider_index(), persist_writes=False)
    failed_readback = operate_provider_cls_alarms(
        client=failed_readback_client,
        request_factory=_request_factory,
        logset_id=logset_id,
        topic_id=topic_id,
        notice_id=notice_id,
        mode="apply",
    )
    if failed_readback.get("alarm_readback_verified") is not False or failed_readback.get("status") != "blocked":
        return f"failed alarm readback must never verify evidence: {failed_readback}"
    if provider_alarm_verification_updates(failed_readback):
        return "failed alarm readback must never produce verification timestamps"

    probe_client = _FakeClsClient(index=_provider_index(), search_results=[{"private": "ignored"}])
    captured_probe: dict[str, object] = {}

    def _probe_uploader(event: dict[str, object]) -> bool:
        captured_probe.update(deepcopy(event))
        return True

    probe = verify_provider_cls_probe(
        client=probe_client,
        request_factory=_request_factory,
        uploader=_probe_uploader,
        topic_id=topic_id,
        environment="staging",
        now_epoch_ms=1_750_000_000_000,
        waiter=lambda _seconds: None,
    )
    if probe.get("status") != "verified" or captured_probe.get("probe") is not True:
        return f"safe provider CLS probe should upload and become searchable: {probe} {captured_probe}"
    if probe.get("alarm_queries_exclude_probe") is not True or probe.get("notification_test_sent") is not False:
        return f"provider probe must be excluded from alarms and send no notification: {probe}"
    search_requests = [request for name, request in probe_client.calls if name == "SearchLog"]
    if len(search_requests) != 1:
        return f"provider probe should use one successful SearchLog readback: {probe_client.calls}"
    search_request = search_requests[0]
    if "QueryString" not in search_request or search_request.get("QuerySyntax") != 1:
        return f"SearchLog must use documented QueryString and QuerySyntax fields: {search_request}"
    if "Query" in search_request or "SyntaxRule" in search_request:
        return f"SearchLog must not use compatibility query fields: {search_request}"
    probe_dump = json.dumps(probe, ensure_ascii=False)
    for forbidden in (topic_id, logset_id, notice_id, "private"):
        if forbidden in probe_dump:
            return f"provider probe status exposed cloud/log result data: {forbidden}"
    return ""


def _write_env_variant(source_text: str, target: Path, updates: dict[str, str]) -> None:
    pending = dict(updates)
    rendered: list[str] = []
    for line in source_text.splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in pending:
            rendered.append(f"{key}={pending.pop(key)}")
        else:
            rendered.append(line)
    for key, value in pending.items():
        rendered.append(f"{key}={value}")
    target.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")


def _status_result(env_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), "--env-file", str(env_path), "--status"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())

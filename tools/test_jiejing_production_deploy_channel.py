#!/usr/bin/env python3
"""Contract checks for the confirmation-gated production deploy channel."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "tools" / "jiejing_production_deploy.py"
APPLY = ROOT / "deploy" / "jiejing-production-release-apply.sh"
COMPOSE = ROOT / "deploy" / "docker-compose.production-pilot.yml"
PATCH_APPLY = ROOT / "deploy" / "apply-staging-patch.sh"
CI = ROOT / ".github" / "workflows" / "jiejing-ci.yml"
RUNBOOK = ROOT / "docs" / "JIEJING_PRODUCTION_DEPLOY_RUNBOOK_20260823.md"
PRECLOUD_GATE = ROOT / "tools" / "jiejing_precloud_deployment_gate.py"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

PHASE3_BUNDLE_FILES = {
    "deploy/jiejing-production-evidence-auto-refresh.sh",
    "deploy/systemd/jiejing-production-evidence-refresh.service",
    "deploy/systemd/jiejing-production-evidence-refresh.timer",
    "tools/test_jiejing_production_evidence_auto_refresh_guardrails.py",
    "docs/superpowers/specs/2026-08-26-production-evidence-auto-refresh-design.md",
    "docs/superpowers/plans/2026-08-26-production-evidence-auto-refresh-implementation-plan.md",
}

BASE_BUNDLE_FILES = {
    "app.js",
    "Dockerfile.saas",
    "deploy/docker-compose.production-pilot.yml",
    "deploy/jiejing-production-release-apply.sh",
    "jiejing_saas/migrations/002_media_credit_buckets_postgres.sql",
    "jiejing_saas/migrations/003_runtime_schema_reconciliation_postgres.sql",
    "tools/jiejing_secret_scan.py",
}


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def load_deploy_module():
    spec = importlib.util.spec_from_file_location("jiejing_production_deploy", CLIENT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load production deploy module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_required_bundle_files() -> list[str]:
    module = load_deploy_module()
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="jiejing-production-bundle-contract-") as temp_dir:
        temp = Path(temp_dir)
        complete = BASE_BUNDLE_FILES | PHASE3_BUNDLE_FILES
        complete_zip = temp / "complete.zip"
        with zipfile.ZipFile(complete_zip, "w") as archive:
            for name in sorted(complete):
                archive.writestr(name, "placeholder\n")
        try:
            module.validate_zip(complete_zip)
        except ValueError as exc:
            failures.append(f"complete phase3 bundle rejected: {exc}")

        for omitted in sorted(PHASE3_BUNDLE_FILES):
            bundle = temp / (omitted.replace("/", "_") + ".zip")
            with zipfile.ZipFile(bundle, "w") as archive:
                for name in sorted(complete - {omitted}):
                    archive.writestr(name, "placeholder\n")
            try:
                module.validate_zip(bundle)
            except ValueError as exc:
                if omitted not in str(exc):
                    failures.append(f"missing {omitted} produced imprecise error: {exc}")
            else:
                failures.append(f"bundle missing {omitted} was accepted")
    return failures


def extract_bash_functions(source: str, names: tuple[str, ...]) -> str:
    matches = list(re.finditer(r"(?m)^([a-zA-Z_][a-zA-Z0-9_]*)\(\) \{\n", source))
    by_name = {match.group(1): match for match in matches}
    extracted: list[str] = []
    for name in names:
        if name not in by_name:
            raise ValueError(f"missing bash function:{name}")
        match = by_name[name]
        closing = re.search(r"(?m)^}\r?$", source[match.end() :])
        if closing is None:
            raise ValueError(f"unterminated bash function:{name}")
        end = match.end() + closing.end()
        extracted.append(source[match.start() : end].rstrip())
    return "\n\n".join(extracted) + "\n"


def run_bash_fixture(script: str, temp: Path, name: str) -> subprocess.CompletedProcess[str]:
    harness = temp / name
    harness.write_text(script, encoding="utf-8", newline="\n")
    try:
        harness.chmod(0o755)
    except OSError:
        pass
    relative = harness.relative_to(ROOT).as_posix()
    return subprocess.run(
        ["bash", relative],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=30,
    )


def fixture_bash_path_exists(path: str, temp: Path, name: str) -> bool:
    if re.fullmatch(r"/tmp/jiejing-production-dry-run-[A-Za-z0-9]{8}\.d", path) is None:
        return False
    result = run_bash_fixture(
        f"""#!/usr/bin/env bash
set -euo pipefail
candidate='{path}'
[[ -e "$candidate" || -L "$candidate" ]]
""",
        temp,
        name,
    )
    return result.returncode == 0


def cleanup_fixture_bash_path(
    path: str, temp: Path, name: str
) -> subprocess.CompletedProcess[str]:
    if re.fullmatch(r"/tmp/jiejing-production-dry-run-[A-Za-z0-9]{8}\.d", path) is None:
        return subprocess.CompletedProcess(["bash", name], 2, "", "invalid fixture path")
    return run_bash_fixture(
        f"""#!/usr/bin/env bash
set -euo pipefail
candidate='{path}'
case "$candidate" in
  /tmp/jiejing-production-dry-run-????????.d) ;;
  *) exit 2 ;;
esac
resolved="$(readlink -f -- "$candidate" 2>/dev/null || true)"
owner="$(stat -c %u -- "$candidate" 2>/dev/null || true)"
[[ "$resolved" == "$candidate" && -d "$resolved" && ! -L "$resolved" ]]
[[ "$owner" == "$(id -u)" ]]
rm -rf --one-file-system -- "$resolved"
[[ ! -e "$resolved" && ! -L "$resolved" ]]
""",
        temp,
        name,
    )


def validate_bash_runtime_fixture(apply: str) -> list[str]:
    if shutil.which("bash") is None:
        return []
    failures: list[str] = []
    functions = extract_bash_functions(
        apply,
        (
            "refuse",
            "require_flock",
            "acquire_deploy_lock",
            "restore_root_file",
            "restore_evidence_refresh_units",
            "restore_evidence_refresh_timer_activity",
            "verify_no_evidence_refresh_dropins",
            "create_dry_run_candidate",
            "cleanup_dry_run_candidate",
            "dry_run_cleanup_handler",
            "arm_dry_run_cleanup_traps",
        ),
    )
    with tempfile.TemporaryDirectory(
        prefix="phase3-bash-fixture-", dir=ROOT
    ) as temp_dir:
        temp = Path(temp_dir)
        relative_temp = temp.relative_to(ROOT).as_posix()
        helper_probe = run_bash_fixture(
            """#!/usr/bin/env bash
set -euo pipefail
probe="$(mktemp -d --tmpdir=/tmp 'jiejing-production-dry-run-XXXXXXXX.d')"
printf 'HELPER_PROBE=%s\n' "$probe"
""",
            temp,
            "path-helper-probe.sh",
        )
        helper_matches = re.findall(
            r"/tmp/jiejing-production-dry-run-[^/\r\n]{8}\.d",
            helper_probe.stdout,
        )
        helper_candidate = helper_matches[-1] if helper_matches else ""
        if not helper_candidate:
            failures.append("cross-WSL path helper probe did not create a candidate")
        elif not fixture_bash_path_exists(
            helper_candidate, temp, "path-helper-exists.sh"
        ):
            failures.append("cross-WSL path exists helper returned a false negative")
        if helper_candidate:
            helper_cleanup = cleanup_fixture_bash_path(
                helper_candidate, temp, "path-helper-cleanup.sh"
            )
            if helper_cleanup.returncode != 0:
                failures.append(
                    "cross-WSL cleanup helper failed rc="
                    + str(helper_cleanup.returncode)
                    + " stderr="
                    + helper_cleanup.stderr[-500:]
                )
            if fixture_bash_path_exists(
                helper_candidate, temp, "path-helper-absent.sh"
            ):
                failures.append("cross-WSL cleanup helper did not remove its probe")
        fixture = f"""#!/usr/bin/env bash
set -euo pipefail
{functions}
TEST_ROOT="$PWD/{relative_temp}"
CALL_LOG="$TEST_ROOT/systemctl.log"
DEPLOY_LOCK="$TEST_ROOT/deploy.lock"
deploy_lock_held=0
FAKE_FLOCK_RC=0
FAKE_ENABLED_STATE=disabled
FAKE_ACTIVE_STATE=inactive
FAKE_SERVICE_DROPIN_PROPERTY="DropInPaths="
FAKE_TIMER_DROPIN_PROPERTY="DropInPaths="
flock() {{
  if [[ "${{1:-}}" == "-n" ]]; then return "$FAKE_FLOCK_RC"; fi
  return 0
}}
systemctl() {{
  printf 'SYSTEMCTL:%s\n' "$*" >>"$CALL_LOG"
  if [[ "$*" == *"-p DropInPaths"* ]]; then
    case "${{2:-}}" in
      refresh.service) printf '%s\n' "$FAKE_SERVICE_DROPIN_PROPERTY" ;;
      refresh.timer) printf '%s\n' "$FAKE_TIMER_DROPIN_PROPERTY" ;;
      *) return 3 ;;
    esac
    return 0
  fi
  case "${{1:-}}" in
    is-enabled) printf '%s\n' "$FAKE_ENABLED_STATE" ;;
    is-active) printf '%s\n' "$FAKE_ACTIVE_STATE" ;;
  esac
  return 0
}}

set +e
lock_busy_output="$(FAKE_FLOCK_RC=1 acquire_deploy_lock 2>&1)"
lock_busy_rc=$?
lock_error_output="$(FAKE_FLOCK_RC=7 acquire_deploy_lock 2>&1)"
lock_error_rc=$?
set -e
[[ "$lock_busy_rc" == "34" && "$lock_busy_output" == *"REFUSE_PRODUCTION_DEPLOY_LOCK_BUSY=1"* ]]
[[ "$lock_error_rc" == "35" && "$lock_error_output" == *"REFUSE_LOCK_ACQUIRE_FAILED=deploy:7"* ]]

: >"$CALL_LOG"
unit_snapshot_complete=0
unit_mutation_started=0
restore_evidence_refresh_units
[[ ! -s "$CALL_LOG" ]]

first="$TEST_ROOT/first"
mkdir -p "$first/backups"
EVIDENCE_REFRESH_WRAPPER="$first/wrapper"
EVIDENCE_REFRESH_SERVICE_PATH="$first/service"
EVIDENCE_REFRESH_TIMER_PATH="$first/timer"
EVIDENCE_REFRESH_SERVICE="refresh.service"
EVIDENCE_REFRESH_TIMER="refresh.timer"
wrapper_backup="$first/backups/wrapper"
service_backup="$first/backups/service"
timer_backup="$first/backups/timer"
printf new >"$EVIDENCE_REFRESH_WRAPPER"
printf new >"$EVIDENCE_REFRESH_SERVICE_PATH"
printf new >"$EVIDENCE_REFRESH_TIMER_PATH"
old_wrapper_present=0
old_service_present=0
old_timer_present=0
old_timer_enabled=not-found
old_timer_active=inactive
old_timer_should_be_enabled=0
old_timer_should_be_active=0
unit_snapshot_complete=1
unit_mutation_started=1
FAKE_ENABLED_STATE=not-found
FAKE_ACTIVE_STATE=inactive
: >"$CALL_LOG"
restore_evidence_refresh_units
printf '%s\n' RELEASE_MAINTENANCE >>"$CALL_LOG"
restore_evidence_refresh_timer_activity
[[ ! -e "$EVIDENCE_REFRESH_WRAPPER" && ! -e "$EVIDENCE_REFRESH_SERVICE_PATH" && ! -e "$EVIDENCE_REFRESH_TIMER_PATH" ]]
! grep -Fq 'SYSTEMCTL:start refresh.timer' "$CALL_LOG"

upgrade="$TEST_ROOT/upgrade"
mkdir -p "$upgrade/backups"
EVIDENCE_REFRESH_WRAPPER="$upgrade/wrapper"
EVIDENCE_REFRESH_SERVICE_PATH="$upgrade/service"
EVIDENCE_REFRESH_TIMER_PATH="$upgrade/timer"
wrapper_backup="$upgrade/backups/wrapper"
service_backup="$upgrade/backups/service"
timer_backup="$upgrade/backups/timer"
printf old-wrapper >"$wrapper_backup"; chmod 0755 "$wrapper_backup"
printf old-service >"$service_backup"; chmod 0644 "$service_backup"
printf old-timer >"$timer_backup"; chmod 0644 "$timer_backup"
printf new-wrapper >"$EVIDENCE_REFRESH_WRAPPER"
printf new-service >"$EVIDENCE_REFRESH_SERVICE_PATH"
printf new-timer >"$EVIDENCE_REFRESH_TIMER_PATH"
chmod 0600 "$EVIDENCE_REFRESH_WRAPPER"
chmod 0700 "$EVIDENCE_REFRESH_SERVICE_PATH"
chmod 0600 "$EVIDENCE_REFRESH_TIMER_PATH"
case "$PWD" in
  /mnt/[a-zA-Z]/*) ;;
  *)
    [[ "$(stat -c %a "$EVIDENCE_REFRESH_WRAPPER")" != "$(stat -c %a "$wrapper_backup")" ]]
    [[ "$(stat -c %a "$EVIDENCE_REFRESH_SERVICE_PATH")" != "$(stat -c %a "$service_backup")" ]]
    [[ "$(stat -c %a "$EVIDENCE_REFRESH_TIMER_PATH")" != "$(stat -c %a "$timer_backup")" ]]
    ;;
esac
old_wrapper_present=1
old_service_present=1
old_timer_present=1
old_timer_enabled=enabled
old_timer_active=active
old_timer_should_be_enabled=1
old_timer_should_be_active=1
unit_snapshot_complete=1
unit_mutation_started=1
FAKE_ENABLED_STATE=enabled
FAKE_ACTIVE_STATE=active
: >"$CALL_LOG"
restore_evidence_refresh_units
printf '%s\n' RELEASE_MAINTENANCE >>"$CALL_LOG"
restore_evidence_refresh_timer_activity
cmp -s "$wrapper_backup" "$EVIDENCE_REFRESH_WRAPPER"
cmp -s "$service_backup" "$EVIDENCE_REFRESH_SERVICE_PATH"
cmp -s "$timer_backup" "$EVIDENCE_REFRESH_TIMER_PATH"
[[ "$(stat -c %a "$EVIDENCE_REFRESH_WRAPPER")" == "$(stat -c %a "$wrapper_backup")" ]]
[[ "$(stat -c %a "$EVIDENCE_REFRESH_SERVICE_PATH")" == "$(stat -c %a "$service_backup")" ]]
[[ "$(stat -c %a "$EVIDENCE_REFRESH_TIMER_PATH")" == "$(stat -c %a "$timer_backup")" ]]
release_line="$(grep -n '^RELEASE_MAINTENANCE$' "$CALL_LOG" | cut -d: -f1)"
start_line="$(grep -n '^SYSTEMCTL:start refresh.timer$' "$CALL_LOG" | cut -d: -f1)"
[[ -n "$release_line" && -n "$start_line" && "$release_line" -lt "$start_line" ]]
grep -Fqx 'SYSTEMCTL:enable refresh.timer' "$CALL_LOG"

FAKE_SERVICE_DROPIN_PROPERTY=DropInPaths=
FAKE_TIMER_DROPIN_PROPERTY=DropInPaths=
verify_no_evidence_refresh_dropins
FAKE_SERVICE_DROPIN_PROPERTY=""
FAKE_TIMER_DROPIN_PROPERTY=""
set +e
verify_no_evidence_refresh_dropins
dropin_unsupported_rc=$?
set -e
[[ "$dropin_unsupported_rc" != "0" ]]
FAKE_SERVICE_DROPIN_PROPERTY=DropInPaths=
FAKE_TIMER_DROPIN_PROPERTY=DropInPaths=/etc/systemd/system/refresh.timer.d/override.conf
set +e
verify_no_evidence_refresh_dropins
dropin_nonempty_rc=$?
set -e
[[ "$dropin_nonempty_rc" != "0" ]]

dry_run_candidate=""
release_dir=""
create_dry_run_candidate
[[ -d "$dry_run_candidate" ]]
touch "$dry_run_candidate/proof"
cleanup_dry_run_candidate "$dry_run_candidate"
[[ ! -e "$dry_run_candidate" ]]
printf '%s\n' FIXTURE_PASS
"""
        result = run_bash_fixture(fixture, temp, "runtime-fixture.sh")
        if result.returncode != 0 or "FIXTURE_PASS" not in result.stdout:
            failures.append(
                "runtime fixture failed rc="
                + str(result.returncode)
                + " stdout="
                + result.stdout[-1000:]
                + " stderr="
                + result.stderr[-1000:]
            )

        dry_signal_functions = extract_bash_functions(
            apply,
            (
                "create_dry_run_candidate",
                "cleanup_dry_run_candidate",
                "dry_run_cleanup_handler",
                "arm_dry_run_cleanup_traps",
            ),
        )
        for signal_name, expected_rc in (("TERM", 143), ("HUP", 129)):
            dry_signal = f"""#!/usr/bin/env bash
set -euo pipefail
{dry_signal_functions}
dry_run_candidate=""
release_dir=""
dry_run_cleanup_active=0
arm_dry_run_cleanup_traps
create_dry_run_candidate
printf 'CANDIDATE=%s\n' "$dry_run_candidate"
touch "$dry_run_candidate/proof"
kill -{signal_name} $$
printf '%s\n' SHOULD_NOT_REACH
"""
            result = run_bash_fixture(
                dry_signal, temp, f"dry-signal-{signal_name.lower()}.sh"
            )
            candidate_matches = re.findall(
                r"/tmp/jiejing-production-dry-run-[^/\r\n]{8}\.d", result.stdout
            )
            candidate = candidate_matches[-1] if candidate_matches else ""
            if result.returncode != expected_rc:
                failures.append(
                    f"dry-run {signal_name} fixture wrong rc:{result.returncode}"
                )
            if not candidate:
                failures.append(f"dry-run {signal_name} fixture did not expose candidate")
            elif fixture_bash_path_exists(
                candidate, temp, f"dry-{signal_name.lower()}-exists.sh"
            ):
                failures.append(f"dry-run {signal_name} fixture left candidate:{candidate}")
                cleanup_result = cleanup_fixture_bash_path(
                    candidate, temp, f"dry-{signal_name.lower()}-cleanup.sh"
                )
                if cleanup_result.returncode != 0:
                    failures.append(
                        f"dry-run {signal_name} fixture cleanup failed rc:"
                        f"{cleanup_result.returncode}"
                    )
            if "SHOULD_NOT_REACH" in result.stdout + result.stderr:
                failures.append(f"dry-run {signal_name} fixture crossed signal boundary")

        cleanup_call = (
            '    cleanup_dry_run_candidate "$dry_run_candidate" || exit_code=39'
        )
        mutated_dry_functions = dry_signal_functions.replace(
            cleanup_call,
            "    : # MUTATION: intentionally skip candidate cleanup",
            1,
        )
        if mutated_dry_functions == dry_signal_functions:
            failures.append("dry-run cleanup mutation target was not found")
        else:
            mutation_fixture = f"""#!/usr/bin/env bash
set -euo pipefail
{mutated_dry_functions}
dry_run_candidate=""
release_dir=""
dry_run_cleanup_active=0
arm_dry_run_cleanup_traps
create_dry_run_candidate
printf 'CANDIDATE=%s\n' "$dry_run_candidate"
touch "$dry_run_candidate/proof"
kill -TERM $$
"""
            mutation_result = run_bash_fixture(
                mutation_fixture, temp, "dry-signal-cleanup-mutation.sh"
            )
            mutation_matches = re.findall(
                r"/tmp/jiejing-production-dry-run-[^/\r\n]{8}\.d",
                mutation_result.stdout,
            )
            mutation_candidate = mutation_matches[-1] if mutation_matches else ""
            mutation_detected = bool(mutation_candidate) and fixture_bash_path_exists(
                mutation_candidate, temp, "dry-mutation-exists.sh"
            )
            if not mutation_detected:
                failures.append(
                    "dry-run dynamic fixture did not detect a no-op cleanup mutation"
                )
            if mutation_candidate and mutation_detected:
                mutation_cleanup = cleanup_fixture_bash_path(
                    mutation_candidate, temp, "dry-mutation-cleanup.sh"
                )
                if mutation_cleanup.returncode != 0:
                    failures.append(
                        "dry-run mutation leftover cleanup failed rc:"
                        + str(mutation_cleanup.returncode)
                    )
                elif fixture_bash_path_exists(
                    mutation_candidate, temp, "dry-mutation-absent.sh"
                ):
                    failures.append("dry-run mutation cleanup left its fixture candidate")

        interrupt_functions = extract_bash_functions(
            apply,
            (
                "restore_root_file",
                "restore_evidence_refresh_units",
                "restore_evidence_refresh_timer_activity",
                "fail_unit_transaction",
                "unit_transaction_signal_handler",
                "unit_transaction_exit_handler",
                "arm_unit_transaction_traps",
            ),
        )
        interrupt = f"""#!/usr/bin/env bash
set -euo pipefail
{interrupt_functions}
TEST_ROOT="$PWD/{relative_temp}/interrupt"
mkdir -p "$TEST_ROOT/backups"
EVIDENCE_REFRESH_WRAPPER="$TEST_ROOT/wrapper"
EVIDENCE_REFRESH_SERVICE_PATH="$TEST_ROOT/service"
EVIDENCE_REFRESH_TIMER_PATH="$TEST_ROOT/timer"
EVIDENCE_REFRESH_SERVICE=refresh.service
EVIDENCE_REFRESH_TIMER=refresh.timer
wrapper_backup="$TEST_ROOT/backups/wrapper"
service_backup="$TEST_ROOT/backups/service"
timer_backup="$TEST_ROOT/backups/timer"
printf new >"$EVIDENCE_REFRESH_WRAPPER"
printf new >"$EVIDENCE_REFRESH_SERVICE_PATH"
printf new >"$EVIDENCE_REFRESH_TIMER_PATH"
old_wrapper_present=0
old_service_present=0
old_timer_present=0
old_timer_enabled=not-found
old_timer_active=inactive
old_timer_should_be_enabled=0
old_timer_should_be_active=0
unit_snapshot_complete=1
unit_mutation_started=1
unit_transaction_active=0
unit_transaction_failure_in_progress=0
current_stage=fixture_interrupt
second_signal_sent=0
systemctl() {{
  if [[ "$second_signal_sent" == "0" ]]; then
    second_signal_sent=1
    kill -INT $$
  fi
  case "${{1:-}}" in
    is-enabled) printf '%s\n' not-found ;;
    is-active) printf '%s\n' inactive ;;
  esac
  return 0
}}
release_maintenance_lock() {{ printf '%s\n' RELEASE_MAINTENANCE; }}
release_deploy_lock() {{ printf '%s\n' RELEASE_DEPLOY; }}
arm_unit_transaction_traps
kill -TERM $$
printf '%s\n' SHOULD_NOT_REACH
"""
        result = run_bash_fixture(interrupt, temp, "interrupt-fixture.sh")
        combined = result.stdout + result.stderr
        if result.returncode != 143:
            failures.append(f"TERM fixture wrong rc:{result.returncode}")
        for marker in (
            "TIMER_INSTALL_ROLLED_BACK=1",
            "APPLICATION_RELEASE_RETAINED=1",
            "RELEASE_MAINTENANCE",
            "RELEASE_DEPLOY",
        ):
            if marker not in combined:
                failures.append(f"TERM fixture missing:{marker}")
        if "JIEJING_PRODUCTION_ROLLBACK_APPLIED=1" in combined or "SHOULD_NOT_REACH" in combined:
            failures.append("TERM fixture crossed the application rollback/success boundary")
        interrupt_root = temp / "interrupt"
        for name in ("wrapper", "service", "timer"):
            if (interrupt_root / name).exists():
                failures.append(f"TERM fixture left first-install target:{name}")

        unexpected_exit = interrupt.replace(
            f"{relative_temp}/interrupt", f"{relative_temp}/unexpected-exit"
        ).replace("kill -TERM $$", "exit 9")
        result = run_bash_fixture(unexpected_exit, temp, "exit-fixture.sh")
        combined = result.stdout + result.stderr
        if result.returncode != 9:
            failures.append(f"EXIT fixture wrong rc:{result.returncode}")
        for marker in (
            "TIMER_INSTALL_ROLLED_BACK=1",
            "APPLICATION_RELEASE_RETAINED=1",
            "RELEASE_MAINTENANCE",
            "RELEASE_DEPLOY",
        ):
            if marker not in combined:
                failures.append(f"EXIT fixture missing:{marker}")
        if "JIEJING_PRODUCTION_ROLLBACK_APPLIED=1" in combined:
            failures.append("EXIT fixture crossed the application rollback boundary")
        exit_root = temp / "unexpected-exit"
        for name in ("wrapper", "service", "timer"):
            if (exit_root / name).exists():
                failures.append(f"EXIT fixture left first-install target:{name}")
    return failures


def main() -> int:
    try:
        client = read(CLIENT)
        apply = read(APPLY)
        compose = read(COMPOSE)
        patch_apply = read(PATCH_APPLY)
        ci = read(CI)
        runbook = read(RUNBOOK)
        precloud_gate = read(PRECLOUD_GATE)
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
        "PRODUCTION_REMOTE_APPLY_TIMEOUT_SECONDS",
        "PHASE3_REQUIRED_BUNDLE_FILES",
        *[f'"{name}"' for name in sorted(PHASE3_BUNDLE_FILES)],
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
        "JIEJING_PRODUCTION_DEPLOY_FAILED_STAGE=",
        "build_candidate_images_with_retry",
        "JIEJING_PRODUCTION_BUILD_RETRY=",
        "ln -sfn",
        "trap rollback_on_error ERR",
        "chmod -R go-w",
        "JIEJING_PRODUCTION_RELEASE_MANIFEST.txt",
        'DEPLOY_LOCK="/run/lock/jiejing-production-deploy.lock"',
        'MAINTENANCE_LOCK="/run/lock/jiejing-production-maintenance.lock"',
        "REFUSE_PRODUCTION_DEPLOY_LOCK_BUSY=1",
        "REFUSE_PRODUCTION_MAINTENANCE_LOCK_BUSY=1",
        "REFUSE_FLOCK_UNAVAILABLE=1",
        "REFUSE_LOCK_OPEN_FAILED=",
        "REFUSE_LOCK_ACQUIRE_FAILED=",
        "validate_evidence_refresh_candidate",
        "bash -n",
        "systemd-analyze verify",
        "TIMER_INSTALL_APPLIED=1",
        "TIMER_FIRST_ONESHOT_VERIFIED=1",
        "TIMER_INSTALL_ROLLED_BACK=1",
        "APPLICATION_RELEASE_RETAINED=1",
        "InvocationID",
        "ExecMainStatus",
        "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=success",
        "NextElapseUSecRealtime",
        "restore_evidence_refresh_units",
        "restore_evidence_refresh_timer_activity",
        "cmp -s",
        '[[ "$after_invocation" =~ ^[0-9a-f]{32}$ ]]',
        "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=skipped",
        "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=blocked",
        "JIEJING_PRODUCTION_EVIDENCE_REFRESH_BLOCKER=",
        "SECRET_EXPOSED=true",
        "SECRET_EXPOSED=false",
        "JIEJING_PRODUCTION_UNIT_TRANSACTION_FAILED_STAGE=",
        "unit_transaction_active=0",
        "unit_transaction_failure_in_progress=0",
        "unit_transaction_signal_handler",
        "unit_transaction_exit_handler",
        "arm_unit_transaction_traps",
        "disarm_unit_transaction_traps",
        "DropInPaths",
        "REFUSE_EVIDENCE_REFRESH_DROPINS=1",
        "create_dry_run_candidate",
        "cleanup_dry_run_candidate",
        "arm_dry_run_cleanup_traps",
        "REFUSE_DRY_RUN_CANDIDATE_UNTRUSTED=1",
        "CANDIDATE_RELEASE_PERSISTED=0",
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
        *[f'"{name}"' for name in sorted(PHASE3_BUNDLE_FILES)],
        '"jiejing_saas/migrations/002_media_credit_buckets_postgres.sql"',
        '"jiejing_saas/migrations/003_runtime_schema_reconciliation_postgres.sql"',
    ]
    required_ci = [
        "python tools/test_jiejing_production_deploy_channel.py",
        "python tools/test_jiejing_production_evidence_auto_refresh_guardrails.py",
    ]
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
        "/run/lock/jiejing-production-deploy.lock",
        "/run/lock/jiejing-production-maintenance.lock",
        "`dry_run` 不获取任何锁",
        "TIMER_INSTALL_ROLLED_BACK=1",
        "APPLICATION_RELEASE_RETAINED=1",
        "InvocationID",
        "NextElapseUSecRealtime",
        "DropInPaths",
        "3600",
        "SIGKILL",
    ]

    missing: list[str] = []
    for prefix, text, markers in (
        ("client", client, required_client),
        ("apply", apply, required_apply),
        ("compose", compose, required_compose),
        ("patch", patch_apply, required_patch_whitelist),
        ("ci", ci, required_ci),
        ("runbook", runbook, required_runbook),
        (
            "precloud",
            precloud_gate,
            ["production_evidence_auto_refresh_guardrails"],
        ),
    ):
        missing.extend(f"{prefix}:{marker}" for marker in markers if marker not in text)
    if missing:
        return fail("production deploy channel missing markers: " + ",".join(missing))

    bundle_failures = validate_required_bundle_files()
    if bundle_failures:
        return fail("; ".join(bundle_failures))

    deploy_module = load_deploy_module()
    timeout_budget = getattr(deploy_module, "PRODUCTION_REMOTE_APPLY_TIMEOUT_SECONDS", 0)
    if timeout_budget < 2700:
        return fail("production apply timeout does not cover oneshot, health, and build budget")
    timeout_start = client.index("remote_timeout =")
    timeout_end = client.index("completed = run(", timeout_start)
    timeout_section = client[timeout_start:timeout_end]
    if 'if args.mode == "apply"' not in timeout_section or "PRODUCTION_REMOTE_APPLY_TIMEOUT_SECONDS" not in timeout_section:
        return fail("long remote timeout is not scoped to apply mode")
    runtime_failures = validate_bash_runtime_fixture(apply)
    if runtime_failures:
        return fail("; ".join(runtime_failures))

    candidate_select = apply.index('if [[ "$DRY_RUN" == "1" ]]')
    candidate_else = apply.index("\nelse\n", candidate_select)
    candidate_select_end = apply.index("\nfi\n", candidate_else) + len("\nfi\n")
    dry_candidate_branch = apply[candidate_select:candidate_else]
    apply_candidate_branch = apply[candidate_else:candidate_select_end]
    forbidden_dry_candidate = ["acquire_deploy_lock", "acquire_maintenance_lock", "$RELEASE_ROOT", "systemctl", "journalctl"]
    present_dry_candidate = [
        marker for marker in forbidden_dry_candidate if marker in dry_candidate_branch
    ]
    if present_dry_candidate:
        return fail("dry-run candidate branch has production side effect: " + ",".join(present_dry_candidate))
    arm_dry_cleanup = dry_candidate_branch.index("arm_dry_run_cleanup_traps")
    create_dry_candidate = dry_candidate_branch.index(
        "create_dry_run_candidate", arm_dry_cleanup
    )
    if arm_dry_cleanup >= create_dry_candidate:
        return fail("dry-run cleanup traps must be armed before candidate creation")
    live_snapshot_start = apply.index('active_app="$(readlink -f -- "$ACTIVE_LINK"')
    docker_live_read = apply.index("docker inspect deploy-jiejing-saas-1", live_snapshot_start)
    lock_gate_start = apply.rindex(
        'if [[ "$DRY_RUN" == "0" ]]',
        apply.index('validate_evidence_refresh_candidate "$resolved_patch_dir"'),
        live_snapshot_start,
    )
    lock_gate_end = apply.index("\nfi\n", lock_gate_start) + len("\nfi\n")
    lock_gate = apply[lock_gate_start:lock_gate_end]
    if "else" in lock_gate:
        return fail("dry-run lock gate must not contain a locking else branch")
    deploy_lock = apply.index("acquire_deploy_lock", lock_gate_start, lock_gate_end)
    maintenance_lock = apply.index("acquire_maintenance_lock", deploy_lock)
    permanent_release = apply.index('release_dir="$RELEASE_ROOT/', docker_live_read)
    create_permanent_release = apply.index(
        'install -d -m 0750 -o root -g root "$release_dir"', permanent_release
    )
    if not (
        lock_gate_start
        < deploy_lock
        < maintenance_lock
        < lock_gate_end
        < live_snapshot_start
        < docker_live_read
        < permanent_release
        < create_permanent_release
        < candidate_select_end
    ):
        return fail("apply must acquire both locks before creating a permanent release")

    dry_run_exit = apply.index('if [[ "$DRY_RUN" == "1" ]]', candidate_select_end)
    dry_run_end = apply.index("\nfi\n", dry_run_exit) + len("\nfi\n")
    build_stage = apply.index('current_stage="build_candidate_images"')
    if not (candidate_select_end < dry_run_exit < dry_run_end < build_stage):
        return fail("dry-run must exit before container or active-link mutation")
    if "systemctl" in apply[:dry_run_end] or "journalctl" in apply[:dry_run_end]:
        return fail("dry-run preflight invokes systemd instead of remaining read-only")

    unit_install = apply.index('current_stage="install_evidence_refresh_units"')
    active_switch = apply.index('current_stage="activate_release"')
    disable_app_rollback = apply.index("trap - ERR", active_switch)
    install_call = apply.index("install_evidence_refresh_units", unit_install)
    release_maintenance = apply.index("release_maintenance_lock", install_call)
    start_oneshot = apply.index("verify_first_evidence_refresh_oneshot", release_maintenance)
    verify_invocation = apply.index("TIMER_FIRST_ONESHOT_VERIFIED=1", start_oneshot)
    start_timer = apply.index("start_and_verify_evidence_refresh_timer", verify_invocation)
    release_deploy = apply.index("release_deploy_lock", start_timer)
    if not (
        active_switch
        < disable_app_rollback
        < unit_install
        < install_call
        < release_maintenance
        < start_oneshot
        < verify_invocation
        < start_timer
        < release_deploy
    ):
        return fail("unit transaction or lock release order is unsafe")

    install_function = apply[
        apply.index("install_evidence_refresh_units()") : apply.index(
            "verify_first_evidence_refresh_oneshot()"
        )
    ]
    install_verify = install_function.index("systemd-analyze verify")
    daemon_reload = install_function.index("systemctl daemon-reload", install_verify)
    enable_timer = install_function.index(
        'systemctl enable "$EVIDENCE_REFRESH_TIMER"', daemon_reload
    )
    if not install_verify < daemon_reload < enable_timer:
        return fail("unit install must verify, reload, then enable without starting timer")
    if 'systemctl start "$EVIDENCE_REFRESH_TIMER"' in install_function:
        return fail("unit install starts timer while maintenance lock is held")

    oneshot_function = apply[
        apply.index("verify_first_evidence_refresh_oneshot()") : apply.index(
            "start_and_verify_evidence_refresh_timer()"
        )
    ]
    oneshot_start = oneshot_function.index('systemctl start "$EVIDENCE_REFRESH_SERVICE"')
    oneshot_invocation = oneshot_function.index("InvocationID", oneshot_start)
    oneshot_result = oneshot_function.index("ExecMainStatus", oneshot_invocation)
    oneshot_journal = oneshot_function.index(
        "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=success", oneshot_result
    )
    if not oneshot_start < oneshot_invocation < oneshot_result < oneshot_journal:
        return fail("first oneshot is not bound to its verified invocation journal")
    if "grep -Fxc 'SECRET_EXPOSED=false'" not in oneshot_function:
        return fail("first oneshot does not require the value-free safety marker exactly once")

    dry_run_block = apply[dry_run_exit:dry_run_end]
    forbidden_dry_run = ["systemctl", "journalctl", "flock", "evidence-auto-refresh.sh"]
    present_dry_run = [marker for marker in forbidden_dry_run if marker in dry_run_block]
    if present_dry_run:
        return fail("dry-run contains side effect: " + ",".join(present_dry_run))

    rollback_start = apply.index("restore_evidence_refresh_units()")
    rollback_end = apply.index("restore_evidence_refresh_timer_activity()", rollback_start)
    rollback_body = apply[rollback_start:rollback_end]
    for marker in ("old_wrapper_present", "old_service_present", "old_timer_present"):
        if marker not in rollback_body:
            return fail(f"unit rollback does not cover first-install/upgrade state: {marker}")
    no_snapshot_guard = (
        '[[ "$unit_snapshot_complete" != "1" || "$unit_mutation_started" != "1" ]]'
    )
    if no_snapshot_guard not in rollback_body:
        return fail("unit rollback may mutate systemd before a complete snapshot and mutation")
    restore_stop = rollback_body.index('systemctl stop "$EVIDENCE_REFRESH_TIMER"')
    restore_guard = rollback_body.index(no_snapshot_guard)
    if restore_guard > restore_stop:
        return fail("unit rollback guard must precede every systemctl mutation")
    if 'systemctl start "$EVIDENCE_REFRESH_TIMER"' in rollback_body:
        return fail("unit files rollback starts old timer while maintenance lock is held")

    failed_transaction = apply[
        apply.index("fail_unit_transaction()") : apply.index("rollback_on_error()")
    ]
    fail_handler_end = failed_transaction.index("unit_transaction_signal_handler()")
    fail_handler = failed_transaction[:fail_handler_end]
    recursion_guard = fail_handler.index(
        'if [[ "$unit_transaction_failure_in_progress" == "1" ]]'
    )
    recursion_guard_end = fail_handler.index("fi", recursion_guard)
    ignore_secondary_signals = fail_handler.index("trap '' HUP INT TERM")
    set_failure_guard = fail_handler.index("unit_transaction_failure_in_progress=1")
    if not recursion_guard_end < ignore_secondary_signals < set_failure_guard:
        return fail("unit rollback must ignore secondary signals immediately after recursion guard")
    restore_files = failed_transaction.index("restore_evidence_refresh_units")
    release_failed_maintenance = failed_transaction.index(
        "release_maintenance_lock", restore_files
    )
    restore_activity = failed_transaction.index(
        "restore_evidence_refresh_timer_activity", release_failed_maintenance
    )
    release_failed_deploy = failed_transaction.index("release_deploy_lock", restore_activity)
    if not (
        restore_files
        < release_failed_maintenance
        < restore_activity
        < release_failed_deploy
    ):
        return fail("failed unit transaction restores timer activity before releasing maintenance lock")

    dropin_check = apply[
        apply.index("verify_no_evidence_refresh_dropins()") : apply.index(
            "install_evidence_refresh_units()"
        )
    ]
    if "--value" in dropin_check or dropin_check.count('!= "DropInPaths="') != 2:
        return fail("DropInPaths must be present and exactly empty for both fixed units")

    atomic_install = apply[
        apply.index("atomic_install_root_file()") : apply.index("restore_root_file()")
    ]
    if "cmp -s" not in atomic_install:
        return fail("atomic root install does not verify candidate bytes")

    timer_verify = apply[
        apply.index("start_and_verify_evidence_refresh_timer()") : apply.index(
            "fail_unit_transaction()"
        )
    ]
    for invalid in ('""', '"n/a"', '"0"'):
        if invalid not in timer_verify:
            return fail(f"timer NextElapse validation does not reject {invalid}")

    build_call = apply.index("build_candidate_images_with_retry", build_stage)
    mutation_start = apply.index("mutation_started=1", build_stage)
    if build_call > mutation_start:
        return fail("candidate images must finish building before rollback-requiring service mutation starts")

    forbidden = [
        "StrictHostKeyChecking=no",
        "systemctl enable --now",
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

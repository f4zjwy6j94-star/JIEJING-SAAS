#!/usr/bin/env python3
"""Guard the production-only COS/CLS evidence refresh entrypoint."""

from __future__ import annotations

from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import textwrap


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "jiejing-production-evidence-auto-refresh.sh"
SERVICE = ROOT / "deploy" / "systemd" / "jiejing-production-evidence-refresh.service"
TIMER = ROOT / "deploy" / "systemd" / "jiejing-production-evidence-refresh.timer"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def run_executable_fixture(bash: str) -> subprocess.CompletedProcess[bytes]:
    fixture = textwrap.dedent(
        r'''
        set -euo pipefail
        source deploy/jiejing-production-evidence-auto-refresh.sh

        fixture_root="$(mktemp -d)"
        trap 'test -n "$fixture_root" && rm -r -- "$fixture_root"' EXIT
        mkdir -p "$fixture_root/releases/release-a/app/deploy"
        touch "$fixture_root/releases/release-a/app/deploy/docker-compose.production-pilot.yml"
        ln -s "$fixture_root/releases/release-a/app" "$fixture_root/app"
        canonical_path_equals \
          "$fixture_root/app/deploy/docker-compose.production-pilot.yml" \
          "$fixture_root/releases/release-a/app/deploy/docker-compose.production-pilot.yml"

        lock_path="$fixture_root/maintenance.lock"
        exec 8>"$lock_path"
        flock -n 8
        set +e
        acquire_nonblocking_lock "$lock_path"
        lock_rc=$?
        set -e
        [[ "$lock_rc" -eq 10 ]]
        exec 8>&-

        set +e
        acquire_nonblocking_lock "$fixture_root/missing/maintenance.lock"
        lock_rc=$?
        set -e
        [[ "$lock_rc" -eq 11 ]]

        set +e
        (PATH=/definitely-missing; acquire_nonblocking_lock "$lock_path")
        lock_rc=$?
        set -e
        [[ "$lock_rc" -eq 11 ]]

        set +e
        printf '{invalid-json' | json_contract_verified cos
        json_rc=$?
        set -e
        [[ "$json_rc" -ne 0 ]]

        events=""
        recreate_api() { return 1; }
        verify_recreated_api() { return 0; }
        recreate_worker() { events="${events}worker"; return 0; }
        verify_recreated_worker() { return 0; }
        set +e
        reload_api_then_worker
        reload_rc=$?
        set -e
        [[ "$reload_rc" -ne 0 && -z "$events" ]]

        events=""
        run_cos_probe() {
          printf '{invalid-json' | json_contract_verified cos
        }
        run_cls_probe() {
          events="${events}cls"
        }
        reload_api_then_worker() {
          events="${events}reload"
        }
        set +e
        run_refresh_phases
        phase_rc=$?
        set -e
        [[ "$phase_rc" -ne 0 && -z "$events" ]]

        events=""
        run_cos_probe() { return 0; }
        run_cls_probe() {
          printf '{invalid-json' | json_contract_verified cls
        }
        reload_api_then_worker() {
          events="${events}reload"
        }
        set +e
        run_refresh_phases
        phase_rc=$?
        set -e
        [[ "$phase_rc" -ne 0 && -z "$events" ]]
        '''
    )
    return subprocess.run(
        [bash, "-s"],
        cwd=ROOT,
        input=fixture.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_runtime_image_fixture(
    bash: str, script: str
) -> subprocess.CompletedProcess[bytes]:
    with tempfile.TemporaryDirectory(prefix=".evidence-image-fixture-", dir=ROOT) as temp:
        script_path = Path(temp) / "wrapper.sh"
        script_path.write_bytes(script.encode("utf-8"))
        source_path = script_path.relative_to(ROOT).as_posix()
        fixture = textwrap.dedent(
            rf'''
            set -euo pipefail
            source {shlex.quote(source_path)}

            fixture_root="$(mktemp -d)"
            trap 'test -n "$fixture_root" && rm -r -- "$fixture_root"' EXIT
            active_app="$fixture_root/releases/release-a/app"
            runtime_compose="$active_app/deploy/docker-compose.production-pilot.yml"
            environment_file="$fixture_root/private/production-compose.env"
            mkdir -p "$active_app/deploy" "$(dirname "$environment_file")"
            touch "$runtime_compose" "$environment_file"

            api_image="sha256:$(printf 'a%.0s' {{1..64}})"
            worker_image="sha256:$(printf 'b%.0s' {{1..64}})"
            api_ref=deploy-jiejing-saas
            worker_ref=deploy-jiejing-worker
            api_container=api-old
            worker_container=worker-old
            missing_api_image=0
            missing_worker_image=0
            api_ref_drift=0
            worker_ref_drift=0
            swap_captured_images=0
            swap_recreated_api=0
            swap_recreated_worker=0
            drift_api_label=0
            drift_worker_label=0
            drift_worker_config=0
            drift_worker_workdir=0
            drift_worker_environment=0
            unhealthy_api=0
            stopped_worker=0
            worker_operational_unhealthy=0

            public_deep_health_ready() {{
              [[ "$worker_operational_unhealthy" == 0 ]]
            }}

            docker() {{
              if [[ "${{1:-}}" == ps ]]; then
                if [[ "$*" == *jiejing-saas* ]]; then
                  printf '%s\n' "$api_container"
                else
                  printf '%s\n' "$worker_container"
                fi
                return 0
              fi
              if [[ "${{1:-}} ${{2:-}}" == "image inspect" ]]; then
                local format="${{4:-}}" ref="${{5:-${{3:-}}}}" resolved=""
                case "$ref" in
                  "$api_ref")
                    if [[ "$api_ref_drift" == 1 ]]; then resolved="$worker_image"; else resolved="$api_image"; fi
                    ;;
                  "$worker_ref")
                    if [[ "$worker_ref_drift" == 1 ]]; then resolved="$api_image"; else resolved="$worker_image"; fi
                    ;;
                  "$api_image") resolved="$api_image" ;;
                  "$worker_image") resolved="$worker_image" ;;
                  *) return 1 ;;
                esac
                [[ "${{3:-}}" == --format ]] && printf '%s\n' "$resolved"
                return 0
              fi
              if [[ "${{1:-}}" == inspect && "${{2:-}}" == --format ]]; then
                local format="${{3:-}}" container="${{4:-}}" service image ref
                if [[ "$container" == "$api_container" ]]; then
                  service=jiejing-saas; image="$api_image"; ref="$api_ref"
                elif [[ "$container" == "$worker_container" ]]; then
                  service=jiejing-worker; image="$worker_image"; ref="$worker_ref"
                else
                  return 1
                fi
                if [[ "$swap_captured_images" == 1 ]]; then
                  if [[ "$service" == jiejing-saas ]]; then image="$worker_image"; else image="$api_image"; fi
                fi
                if [[ "$service" == jiejing-saas && "$container" == api-new && "$swap_recreated_api" == 1 ]]; then
                  image="$worker_image"
                fi
                if [[ "$service" == jiejing-worker \
                  && "$container" == worker-new \
                  && "$swap_recreated_worker" == 1 ]]; then
                  image="$api_image"
                fi
                case "$format" in
                  *compose.project\"*)
                    if [[ "$service" == jiejing-saas && "$drift_api_label" == 1 ]]; then
                      printf '%s\n' other
                    else
                      printf '%s\n' deploy
                    fi
                    ;;
                  *compose.service\"*)
                    if [[ "$service" == jiejing-worker && "$drift_worker_label" == 1 ]]; then
                      printf '%s\n' jiejing-saas
                    else
                      printf '%s\n' "$service"
                    fi
                    ;;
                  *project.config_files*)
                    if [[ "$service" == jiejing-worker && "$drift_worker_config" == 1 ]]; then
                      printf '%s\n' "$fixture_root/wrong-compose.yml"
                    else
                      printf '%s\n' "$runtime_compose"
                    fi
                    ;;
                  *project.working_dir*)
                    if [[ "$service" == jiejing-worker && "$drift_worker_workdir" == 1 ]]; then
                      printf '%s\n' "$fixture_root/wrong-workdir"
                    else
                      printf '%s\n' "$active_app/deploy"
                    fi
                    ;;
                  *project.environment_file*)
                    if [[ "$service" == jiejing-worker && "$drift_worker_environment" == 1 ]]; then
                      printf '%s\n' "$fixture_root/private/wrong.env"
                    else
                      printf '%s\n' "$environment_file"
                    fi
                    ;;
                  '{{{{.Image}}}}')
                    if [[ "$service" == jiejing-saas && "$missing_api_image" == 1 ]]; then
                      printf '\n'
                    elif [[ "$service" == jiejing-worker && "$missing_worker_image" == 1 ]]; then
                      printf '\n'
                    else
                      printf '%s\n' "$image"
                    fi
                    ;;
                  '{{{{.Config.Image}}}}') printf '%s\n' "$ref" ;;
                  '{{{{.State.Status}}}}')
                    if [[ "$service" == jiejing-worker && "$stopped_worker" == 1 ]]; then
                      printf '%s\n' exited
                    else
                      printf '%s\n' running
                    fi
                    ;;
                  *State.Health*)
                    if [[ "$service" == jiejing-saas && "$unhealthy_api" == 1 ]]; then
                      printf '%s\n' unhealthy
                    else
                      printf '%s\n' healthy
                    fi
                    ;;
                  *) return 2 ;;
                esac
                return 0
              fi
              if [[ "${{1:-}}" == compose ]]; then
                local service="${{@: -1}}"
                if [[ "$*" == *" up "* ]]; then
                  printf 'compose-up:%s\n' "$service" >>"$fixture_root/side-effects"
                  if [[ "$service" == jiejing-saas ]]; then
                    api_container=api-new
                  else
                    worker_container=worker-new
                  fi
                  return 0
                fi
                if [[ "$*" == *" ps -q "* ]]; then
                  if [[ "$service" == jiejing-saas ]]; then
                    printf '%s\n' "$api_container"
                  else
                    printf '%s\n' "$worker_container"
                  fi
                  return 0
                fi
              fi
              if [[ "${{1:-}}" == run ]]; then
                printf '%s\n' probe >>"$fixture_root/side-effects"
                if [[ " $* " == *" $api_image "* ]]; then
                  printf '%s\n' api >>"$fixture_root/probe-images"
                elif [[ " $* " == *" $worker_image "* ]]; then
                  printf '%s\n' worker >>"$fixture_root/probe-images"
                else
                  return 3
                fi
                printf '%s\n' '{{}}'
                return 0
              fi
              return 2
            }}

            private_dir="$(dirname "$environment_file")"
            APP_ENV="$fixture_root/private/jiejing-saas.production.env"
            touch "$APP_ENV"
            env_digest_before=digest
            json_contract_verified() {{ return 0; }}
            trusted_private_file() {{ return 0; }}
            evidence_excluded_env_digest() {{ printf '%s\n' digest; }}
            COMPOSE_ARGS=()
            wait_for_api_health() {{ return 0; }}
            wait_for_worker_health() {{ return 0; }}

            worker_operational_unhealthy=1
            set +e
            unhealthy_output="$(
              capture_and_validate_runtime_images
              run_refresh_phases
            )"
            unhealthy_rc=$?
            set -e
            [[ "$unhealthy_rc" -ne 0 ]]
            [[ "$unhealthy_output" == *"JIEJING_PRODUCTION_EVIDENCE_REFRESH_BLOCKER=runtime_worker_operational_unhealthy"* ]]
            [[ ! -e "$fixture_root/side-effects" ]]
            worker_operational_unhealthy=0

            capture_and_validate_runtime_images
            [[ "$runtime_api_image_id" == "$api_image" ]]
            [[ "$runtime_worker_image_id" == "$worker_image" ]]
            [[ "$runtime_api_image_id" != "$runtime_worker_image_id" ]]
            run_cos_probe
            run_cls_probe
            [[ "$(<"$fixture_root/probe-images")" == $'api\napi' ]]
            recreate_api
            verify_recreated_api
            recreate_worker
            verify_recreated_worker

            assert_capture_fails() {{
              set +e
              (capture_and_validate_runtime_images) >/dev/null 2>&1
              local rc=$?
              set -e
              [[ "$rc" -ne 0 ]]
            }}

            api_container=api-old
            worker_container=worker-old
            missing_api_image=1
            assert_capture_fails
            missing_api_image=0
            missing_worker_image=1
            assert_capture_fails
            missing_worker_image=0
            api_ref_drift=1
            assert_capture_fails
            api_ref_drift=0
            worker_ref_drift=1
            assert_capture_fails
            worker_ref_drift=0
            swap_captured_images=1
            assert_capture_fails
            swap_captured_images=0
            drift_api_label=1
            assert_capture_fails
            drift_api_label=0
            drift_worker_label=1
            assert_capture_fails
            drift_worker_label=0
            drift_worker_config=1
            assert_capture_fails
            drift_worker_config=0
            drift_worker_workdir=1
            assert_capture_fails
            drift_worker_workdir=0
            drift_worker_environment=1
            assert_capture_fails
            drift_worker_environment=0
            unhealthy_api=1
            assert_capture_fails
            unhealthy_api=0
            stopped_worker=1
            assert_capture_fails
            stopped_worker=0

            capture_and_validate_runtime_images
            COMPOSE_ARGS=()
            recreate_api
            swap_recreated_api=1
            set +e
            verify_recreated_api >/dev/null 2>&1
            swapped_api_rc=$?
            set -e
            [[ "$swapped_api_rc" -ne 0 ]]
            swap_recreated_api=0
            recreate_worker
            swap_recreated_worker=1
            set +e
            verify_recreated_worker >/dev/null 2>&1
            swapped_worker_rc=$?
            set -e
            [[ "$swapped_worker_rc" -ne 0 ]]
            printf '%s\n' RUNTIME_IMAGE_FIXTURE_PASS
            '''
        )
        return subprocess.run(
            [bash, "-s"],
            cwd=ROOT,
            input=fixture.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )


def main() -> int:
    required = (SCRIPT, SERVICE, TIMER)
    if any(not path.is_file() for path in required):
        return fail("production evidence refresh script and fixed systemd units must exist")

    script = SCRIPT.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")

    required_timer = (
        "[Timer]",
        "OnCalendar=*-*-* 00,12:17:00",
        "RandomizedDelaySec=9m",
        "Persistent=true",
        "Unit=jiejing-production-evidence-refresh.service",
        "[Install]",
        "WantedBy=timers.target",
    )
    missing_timer = [item for item in required_timer if item not in timer]
    if missing_timer:
        return fail("production timer contract missing markers: " + ",".join(missing_timer))

    required_service = (
        "[Service]",
        "Type=oneshot",
        "User=root",
        "Group=root",
        "UMask=0077",
        "ExecStart=/usr/local/libexec/jiejing/jiejing-production-evidence-auto-refresh.sh",
        "TimeoutStartSec=20min",
        "NoNewPrivileges=true",
    )
    missing_service = [item for item in required_service if item not in service]
    if missing_service:
        return fail("production service contract missing markers: " + ",".join(missing_service))
    forbidden_unit = ("EnvironmentFile=", "ExecStart=/bin/bash -c", "%i", "%I")
    unsafe_unit = [item for item in forbidden_unit if item in service or item in timer]
    if unsafe_unit:
        return fail("production units accept dynamic or secret-bearing input: " + ",".join(unsafe_unit))

    required_script = (
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then',
        'main "$@"',
        'PRODUCTION_ROOT="/opt/jiejing-production"',
        'ACTIVE_LINK="$PRODUCTION_ROOT/app"',
        'RELEASE_ROOT="$PRODUCTION_ROOT/releases"',
        'COMPOSE_NAME="docker-compose.production-pilot.yml"',
        'LOCK_FILE="/run/lock/jiejing-production-maintenance.lock"',
        '[[ "$#" -eq 0 ]] || fail_closed "unexpected_arguments"',
        "command -v flock",
        'acquire_nonblocking_lock "$LOCK_FILE"',
        'exec 9>"$path"',
        "flock -n 9",
        '[[ -L "$ACTIVE_LINK" ]]',
        '[[ "$(stat -c \'%U:%G\' -- "$ACTIVE_LINK" 2>/dev/null || true)" == "root:root" ]]',
        'active_app="$(readlink -f -- "$ACTIVE_LINK"',
        '"$RELEASE_ROOT"/*/app)',
        "com.docker.compose.project=deploy",
        "com.docker.compose.service=jiejing-saas",
        'com.docker.compose.project.config_files',
        'com.docker.compose.project.working_dir',
        'com.docker.compose.project.environment_file',
        'environment_file_label="$environment_file"',
        '[[ "$environment_file_label" == "$environment_file" ]]',
        "{{.Image}}",
        'canonical_path_equals "$runtime_api_config_files" "$runtime_compose"',
        'canonical_path_equals "$runtime_api_project_dir" "$active_app/deploy"',
        'capture_and_validate_runtime_images',
        '[[ "$runtime_api_image_id" =~ ^sha256:[0-9a-f]{64}$ ]]',
        '[[ "$runtime_worker_image_id" =~ ^sha256:[0-9a-f]{64}$ ]]',
        'docker image inspect "$runtime_api_image_id"',
        'docker image inspect "$runtime_worker_image_id"',
        'canonical_path_equals "$runtime_worker_config_files" "$runtime_compose"',
        'canonical_path_equals "$runtime_worker_project_dir" "$active_app/deploy"',
        '[[ "$runtime_worker_environment_file" == "$runtime_api_environment_file" ]]',
        '[[ "$environment_file" == "$private_dir/production-compose.env" ]]',
        'APP_ENV="$private_dir/jiejing-saas.production.env"',
        'trusted_private_directory "$private_dir"',
        '(( (8#$mode & 0022) == 0 ))',
        "stat -c '%U:%G %a'",
        '[[ "$metadata" == "root:root 600" ]]',
        '[[ -f "$path" && ! -L "$path" ]]',
        "EVIDENCE_FIELDS = {",
        '"JIEJING_COS_BACKUP_LAST_SUCCESS_AT"',
        '"JIEJING_CLS_LIVE_PROBE_LAST_AT"',
        '"JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED"',
        '"JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"',
        'env_digest_before="$(evidence_excluded_env_digest "$APP_ENV")"',
        'env_digest_after="$(evidence_excluded_env_digest "$APP_ENV")"',
        '[[ "$env_digest_after" != "$env_digest_before" ]]',
        'LIVE_RELEASE_GUARD_STATUS=ready',
        'docker run --rm --network bridge',
        '"$runtime_api_image_id" python tools/jiejing_configure_tencent_runtime_env.py',
        "--verify-cos-backup-probe --apply",
        'payload.get("status") == "verified"',
        'payload.get("probe_verified") is True',
        'payload.get("verification_evidence_recorded") is True',
        'COS_PROBE_STATUS=verified',
        "--verify-provider-cls-probe --apply",
        'payload.get("probe_uploaded") is True',
        'payload.get("probe_searchable") is True',
        'payload.get("alarm_queries_exclude_probe") is True',
        'payload.get("event_field_count") == 12',
        'payload.get("event_allowlist_exact") is True',
        'payload.get("notification_test_sent") is False',
        'CLS_PROBE_STATUS=verified',
        'COMPOSE_ARGS=(--project-name deploy --env-file "$COMPOSE_ENV" -f "$runtime_compose")',
        'docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps --force-recreate jiejing-saas',
        '[[ "$new_api_container_id" != "$approved_api_container_id" ]]',
        '[[ "$new_api_image_id" == "$runtime_api_image_id" ]]',
        'API_RELOAD_STATUS=ready',
        'docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps --force-recreate jiejing-worker',
        '[[ "$new_worker_container_id" != "$approved_worker_container_id" ]]',
        '[[ "$new_worker_image_id" == "$runtime_worker_image_id" ]]',
        'WORKER_RELOAD_STATUS=ready',
        'PUBLIC_BASE_URL="https://app.jiejing.shop"',
        '"$PUBLIC_BASE_URL/health"',
        '"$PUBLIC_BASE_URL/health/deep"',
        '"$PUBLIC_BASE_URL/readiness/product-saas"',
        'backup.get("backup_ready_for_paid_launch") is True',
        '"backup_restore" not in item_by_key',
        '"monitoring_alerting" not in item_by_key',
        'billing.get("public_charging_allowed") is False',
        'readiness.get("real_platform_writes_enabled") is False',
        'readiness.get("secret_exposed") is False',
        'READINESS_STATUS=verified',
        'JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=success',
        'SECRET_EXPOSED=false',
    )
    missing_script = [item for item in required_script if item not in script]
    if missing_script:
        return fail("production evidence refresh missing markers: " + ",".join(missing_script))

    failure_markers = (
        "lock_busy",
        "maintenance_lock_failed",
        "api_image_reference_drift",
        "worker_image_reference_drift",
        "unexpected_arguments",
        "active_release_untrusted",
        "runtime_api_container_not_unique",
        "runtime_api_image_untrusted",
        "runtime_worker_image_untrusted",
        "runtime_worker_compose_label_mismatch",
        "runtime_compose_label_mismatch",
        "private_env_permissions_untrusted",
        "cos_probe_failed",
        "cos_probe_contract_rejected",
        "cls_probe_failed",
        "cls_probe_contract_rejected",
        "environment_drift_detected",
        "api_recreate_failed",
        "api_identity_mismatch",
        "api_health_failed",
        "worker_recreate_failed",
        "worker_identity_mismatch",
        "worker_health_failed",
        "public_readiness_contract_failed",
    )
    missing_failures = [item for item in failure_markers if item not in script]
    if missing_failures:
        return fail("failure short-circuit contract missing markers: " + ",".join(missing_failures))

    refresh_flow = script[
        script.index("run_refresh_phases() {") : script.index("\n}\n\nmain()", script.index("run_refresh_phases() {"))
    ]
    if not (
        refresh_flow.index("run_cos_probe")
        < refresh_flow.index("run_cls_probe")
        < refresh_flow.index("reload_api_then_worker")
    ):
        return fail("COS, CLS and reload phases must be strictly ordered")
    reload_flow = script[
        script.index("reload_api_then_worker() {") : script.index(
            "\n}\n\nrun_refresh_phases", script.index("reload_api_then_worker() {")
        )
    ]
    if not (
        reload_flow.index("recreate_api")
        < reload_flow.index("verify_recreated_api")
        < reload_flow.index("API_RELOAD_STATUS=ready")
        < reload_flow.index("recreate_worker")
        < reload_flow.index("verify_recreated_worker")
        < reload_flow.index("WORKER_RELOAD_STATUS=ready")
    ):
        return fail("API health must short-circuit before Worker reload")

    forbidden_script = (
        "docker compose down",
        "docker volume rm",
        "docker compose restart",
        "rm -rf",
        "set -x",
        "printenv",
        "env |",
        'source "$APP_ENV"',
        'cat "$APP_ENV"',
        "JIEJING_EBAY_",
        "WECHAT_PAY",
        "STRIPE_",
        "OPENAI_API_KEY",
        "DEEPSEEK",
        "TAVILY",
        "FAL_",
        "--record-cos-probe-now",
        '"$runtime_image_id"',
        "force-recreate jiejing-vault",
        "force-recreate jiejing-frontend",
        "force-recreate jiejing-edge",
    )
    unsafe_script = [item for item in forbidden_script if item in script]
    if unsafe_script:
        return fail("production evidence refresh contains forbidden markers: " + ",".join(unsafe_script))

    if "json.load(sys.stdin)" not in script or "except (json.JSONDecodeError" not in script:
        return fail("captured provider output must fail closed on invalid JSON without being logged")
    if 'echo "$cos_output"' in script or 'echo "$cls_output"' in script:
        return fail("raw provider output must never be emitted")
    if script.count('-w /app "$runtime_api_image_id" python') != 3:
        return fail("COS, CLS and probe-tool checks must use the captured API image")
    if '-w /app "$runtime_worker_image_id" python' in script:
        return fail("provider probe tooling must not depend on the Worker image")

    bash = shutil.which("bash")
    if bash:
        syntax = subprocess.run(
            [bash, "-n", "deploy/jiejing-production-evidence-auto-refresh.sh"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if syntax.returncode != 0:
            return fail("production evidence refresh shell syntax must be valid")
        fixture = run_executable_fixture(bash)
        if fixture.returncode != 0:
            fixture_error = fixture.stderr.decode("utf-8", errors="replace").splitlines()
            detail = fixture_error[-1][:200] if fixture_error else f"exit_{fixture.returncode}"
            return fail("production evidence refresh executable failure fixture must pass: " + detail)
        runtime_fixture = run_runtime_image_fixture(bash, script)
        if runtime_fixture.returncode != 0:
            runtime_error = runtime_fixture.stderr.decode("utf-8", errors="replace").splitlines()
            detail = runtime_error[-1][:200] if runtime_error else f"exit_{runtime_fixture.returncode}"
            return fail("production evidence refresh dual-image fixture must pass: " + detail)
        if b"RUNTIME_IMAGE_FIXTURE_PASS" not in runtime_fixture.stdout:
            return fail("production evidence refresh dual-image fixture did not reach completion")
        for identity_check in (
            '    || ! [[ "$new_api_image_id" == "$runtime_api_image_id" ]]; then',
            '    || ! [[ "$new_worker_image_id" == "$runtime_worker_image_id" ]]; then',
        ):
            if script.count(identity_check) != 1:
                return fail("recreated service image check must be unique: " + identity_check.strip())
            mutated_script = script.replace(identity_check, "    || false; then", 1)
            mutation_fixture = run_runtime_image_fixture(bash, mutated_script)
            if mutation_fixture.returncode == 0:
                return fail("dual-image fixture did not detect deleted image check: " + identity_check.strip())
            if b"COS_PROBE_STATUS=verified" not in mutation_fixture.stdout:
                return fail("dual-image mutation fixture failed before exercising runtime behavior")

    print("PASS jiejing_production_evidence_auto_refresh_guardrails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

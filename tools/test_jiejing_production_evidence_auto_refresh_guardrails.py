#!/usr/bin/env python3
"""Guard the production-only COS/CLS evidence refresh entrypoint."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import textwrap
from typing import Any


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


def run_public_readiness_json_fixture(bash: str, serialized_payload: str) -> subprocess.CompletedProcess[bytes]:
    fixture = textwrap.dedent(
        f'''
        set -euo pipefail
        source deploy/jiejing-production-evidence-auto-refresh.sh
        PUBLIC_BASE_URL=https://public-readiness.fixture.invalid
        curl() {{
          printf '%s\\n' {shlex.quote(serialized_payload)}
        }}
        public_readiness_ready
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


def run_public_readiness_fixture(bash: str, payload: dict[str, object]) -> subprocess.CompletedProcess[bytes]:
    return run_public_readiness_json_fixture(
        bash,
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
    )


def run_public_readiness_wait_fixture(bash: str, *, becomes_ready: bool) -> subprocess.CompletedProcess[bytes]:
    terminal_status = "return 0" if becomes_ready else "return 1"
    fixture = textwrap.dedent(
        f'''
        set -euo pipefail
        source deploy/jiejing-production-evidence-auto-refresh.sh
        PUBLIC_READINESS_MAX_ATTEMPTS=4
        PUBLIC_READINESS_RETRY_SECONDS=0
        attempts=0
        public_readiness_ready() {{
          attempts=$((attempts + 1))
          if [[ "$attempts" -ge 3 ]]; then
            {terminal_status}
          fi
          return 1
        }}
        wait_for_public_readiness
        [[ "$attempts" -eq 3 ]]
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


def current_public_readiness_payload() -> dict[str, object]:
    return {
        "readiness": {
            "service": "jiejing-saas-backend",
            "readiness_version": "2026-05-15-product-saas",
            "public_contract_version": "2026-07-15-public-readiness-current-ebay-evidence",
            "detail_scope": "public_summary",
            "internal_detail_required": True,
            "authenticated_summary": False,
            "environment": "production",
            "production_ready": False,
            "beta_ready": True,
            "can_accept_real_customers": False,
            "real_platform_writes_enabled": False,
            "requested_real_platform_writes": False,
            "blocker_count": 0,
            "warning_count": 1,
            "items": [
                {
                    "key": "billing_quota",
                    "label": "Billing and quota",
                    "status": "private_beta_ready_paid_launch_pending",
                    "severity": "warning",
                    "detail": "Public charging remains closed.",
                    "next_action": "Complete the controlled payment gate.",
                }
            ],
            "product_evidence": {
                "latest_ebay_packet_status": "packet_cached_sanitized",
                "latest_ebay_packet_source_mode": "official_api",
                "latest_ebay_packet_present_resource_keys": [
                    "store_profile",
                    "account_business_policies",
                    "inventory_and_offers",
                    "orders_and_fulfillment",
                    "finances",
                    "taxonomy_listing_metadata",
                ],
                "latest_ebay_packet_missing_resource_keys": [],
                "latest_ebay_packet_current_connection": True,
                "historical_ebay_packet_present": False,
                "ebay_token_refresh_success_count": 2,
                "secret_exposed": False,
            },
            "provider_status": {
                "billing": {
                    "provider": "wechat_pay_native",
                    "checkout_mode": "native_qr",
                    "billing_mode": "one_time_30_day_plan",
                    "provider_configured": True,
                    "payment_path_status": "refund_controls_pending",
                    "mainland_payment_ready_for_owner_approval": False,
                    "billing_ready_for_private_beta": True,
                    "billing_ready_for_paid_launch": False,
                    "configured_component_count": 9,
                    "required_component_count": 9,
                    "verified_paid_order_count": 1,
                    "quota_enforcement_enabled": True,
                    "paid_launch_blocker_count": 1,
                    "next_paid_launch_blocker": "merchant_payment_refund_not_ready",
                    "merchant_launch_path": {
                        "contract_version": "2026-07-27-merchant-mainland-payment-path-v1",
                        "current_stage": "refund_controls_pending",
                        "current_charge_status": "no_real_charge_now",
                        "public_paid_launch_allowed": False,
                        "charge_now_allowed": False,
                        "triggers_real_charge": False,
                        "backend_confirmation_required_before_entitlement": True,
                        "frontend_can_grant_entitlement": False,
                        "frontend_can_grant_quota": False,
                        "quota_grant_source": "backend_subscription_state",
                        "secret_exposed": False,
                    },
                    "domestic_payment": {
                        "provider": "wechat_pay_native",
                        "checkout_mode": "native_qr",
                        "billing_mode": "one_time_30_day_plan",
                        "status": "refund_controls_pending",
                        "configured_component_count": 9,
                        "required_component_count": 9,
                        "verified_paid_order_count": 1,
                        "public_charging_allowed": False,
                        "charge_now_allowed": False,
                        "triggers_real_charge": False,
                        "triggers_real_refund": False,
                        "calls_external_payment_api": False,
                        "frontend_gets_payment_secret": False,
                        "secret_exposed": False,
                    },
                    "public_charging_allowed": False,
                    "charge_now_allowed": False,
                    "triggers_real_charge": False,
                    "triggers_real_refund": False,
                    "calls_external_payment_api": False,
                    "real_platform_writes_enabled": False,
                    "frontend_gets_payment_secret": False,
                    "frontend_can_grant_quota": False,
                    "secret_exposed": False,
                },
                "model_value": {
                    "status": "ready",
                    "ready": True,
                    "live_model_report_types": ["listing.package", "market.report"],
                    "blocker_count": 0,
                    "secret_exposed": False,
                },
                "ai_ceo_platform_model": {
                    "enabled": True,
                    "configured": True,
                    "status": "ready",
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "trial_request_limit": 20,
                    "trial_duration_days": 7,
                    "trial_quota_scope": "account_trial_window",
                    "usage_owner": "jiejing_platform_trial",
                    "quota_checked_by_backend": True,
                    "hard_stop_on_exhaustion": True,
                    "exhaustion_blocker": "platform_default_model_trial_exhausted",
                    "merchant_byok_preferred": True,
                    "merchant_byok_not_counted_against_platform_trial": True,
                    "byok_bypasses_platform_trial": True,
                    "customer_visible_next_action": "save_account_ai_or_upgrade_plan",
                    "operator_cost_monitoring_required": True,
                    "frontend_can_grant_quota": False,
                    "frontend_gets_model_api_key": False,
                    "runtime_gets_model_api_key": False,
                    "secret_exposed": False,
                },
                "public_search": {
                    "provider": "tavily",
                    "configured": True,
                    "endpoint_host": "api.tavily.com",
                    "credential_present": True,
                    "ai_ceo_realtime_search_enabled": True,
                    "builtin_public_web_fallback_enabled": True,
                    "builtin_stock_quote_fallback_enabled": True,
                    "frontend_gets_search_api_key": False,
                    "runtime_gets_search_api_key": False,
                    "secret_exposed": False,
                },
                "media_generation": {
                    "contract_version": "2026-07-05-media-generation-readiness",
                    "configured": True,
                    "status": "live_generation_ready_waiting_asset_review",
                    "live_generation_enabled": True,
                    "live_image_generation_enabled": True,
                    "live_video_generation_enabled": True,
                    "live_provider_calls_allowed": True,
                    "asset_manifest_required": True,
                    "asset_review_required": True,
                    "fact_review_required": True,
                    "human_review_required_before_listing": True,
                    "cost_guard_required": True,
                    "spend_now_allowed": False,
                    "listing_use_requires_review": True,
                    "customer_visible_summary": "Assets remain review-gated.",
                    "next_action": "Review assets before listing use.",
                    "frontend_gets_media_api_key": False,
                    "runtime_gets_raw_secret": False,
                    "reports_get_raw_provider_response": False,
                    "raw_provider_response_stored": False,
                    "secret_exposed": False,
                },
            },
            "operational_health": {
                "status": "ready",
                "detail_scope": "summary_only",
                "secret_exposed": False,
            },
            "secret_exposed": False,
        }
    }


def mutated_public_readiness(path: tuple[str | int, ...], value: object) -> dict[str, object]:
    payload = current_public_readiness_payload()
    cursor: Any = payload
    for segment in path[:-1]:
        cursor = cursor[segment]
    cursor[path[-1]] = value
    return payload


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
            deep_health_payload='{{}}'

            curl() {{
              printf '%s\n' "$deep_health_payload"
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

            assert_worker_operational_health_rejected() {{
              deep_health_payload="$1"
              rm -f "$fixture_root/side-effects" "$fixture_root/probe-images"
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
            }}

            assert_worker_operational_health_rejected \
              '{{"operational_health":{{"status":"ready","database":{{"status":"ready"}},"queue":{{"status":"ready"}},"worker":{{"status":"ready","ready":false}},"secret_exposed":false}}}}'
            assert_worker_operational_health_rejected \
              '{{"operational_health":{{"status":"ready","database":{{"status":"ready"}},"queue":{{"status":"ready"}},"worker":{{"status":"ready"}},"secret_exposed":false}}}}'
            assert_worker_operational_health_rejected \
              '{{"operational_health":{{"status":"ready","database":{{"status":"ready"}},"queue":{{"status":"ready"}},"worker":{{"status":"ready","ready":"true"}},"secret_exposed":false}}}}'
            assert_worker_operational_health_rejected \
              '{{"operational_health":{{"status":"ready","database":{{"status":"ready"}},"queue":{{"status":"ready"}},"worker":{{"status":"ready","ready":1}},"secret_exposed":false}}}}'
            assert_worker_operational_health_rejected \
              '{{"operational_health":{{"status":"ready","database":{{"status":"ready"}},"queue":{{"status":"ready"}},"worker":{{"status":"ready","ready":null}},"secret_exposed":false}}}}'

            deep_health_payload='{{"operational_health":{{"status":"ready","database":{{"status":"ready"}},"queue":{{"status":"ready"}},"worker":{{"status":"ready","ready":true}},"secret_exposed":false}}}}'

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
        "object_pairs_hook=unique_object",
        "set(payload) != PUBLIC_ROOT_FIELDS",
        "set(readiness) != READINESS_PUBLIC_FIELDS",
        "set(item) != ITEM_PUBLIC_FIELDS",
        "set(providers) != PROVIDER_PUBLIC_FIELDS",
        "set(provider_value) != PROVIDER_SUBFIELDS[provider_key]",
        "has_unapproved_sensitive_field(payload)",
        'readiness.get("public_contract_version") == "2026-07-15-public-readiness-current-ebay-evidence"',
        'readiness.get("detail_scope") == "public_summary"',
        'readiness.get("internal_detail_required") is True',
        'readiness.get("environment") == "production"',
        'type(blocker_count) is int',
        'blocker_count == len(blockers) == 0',
        'type(warning_count) is int',
        'warning_count == len(warnings)',
        'set(item_by_key) == {"billing_quota"}',
        '"backup_restore" not in item_by_key',
        '"monitoring_alerting" not in item_by_key',
        '"private_beta_ready_paid_launch_pending"',
        '"mainland_payment_ready_for_owner_approval"',
        '"backup" not in providers',
        'billing.get("billing_ready_for_private_beta") is True',
        'billing.get("billing_ready_for_paid_launch") is False',
        'billing.get("quota_enforcement_enabled") is True',
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
        readiness_fixture = run_public_readiness_fixture(bash, current_public_readiness_payload())
        if readiness_fixture.returncode != 0:
            return fail(
                "current public readiness summary without internal backup details must pass: "
                f"exit_{readiness_fixture.returncode}"
            )
        delayed_readiness_fixture = run_public_readiness_wait_fixture(bash, becomes_ready=True)
        if delayed_readiness_fixture.returncode != 0:
            return fail("public readiness wait must tolerate bounded asynchronous evidence convergence")
        never_ready_fixture = run_public_readiness_wait_fixture(bash, becomes_ready=False)
        if never_ready_fixture.returncode == 0:
            return fail("public readiness wait must fail closed after its bounded attempts")
        owner_approval_payload = current_public_readiness_payload()
        owner_approval_payload["readiness"]["items"][0][  # type: ignore[index]
            "status"
        ] = "mainland_payment_ready_for_owner_approval"
        owner_approval_payload["readiness"]["provider_status"]["billing"][  # type: ignore[index]
            "mainland_payment_ready_for_owner_approval"
        ] = True
        owner_approval_payload["readiness"]["provider_status"]["billing"][  # type: ignore[index]
            "payment_path_status"
        ] = "controlled_acceptance_proven_public_charging_closed"
        owner_approval_payload["readiness"]["provider_status"]["billing"][  # type: ignore[index]
            "next_paid_launch_blocker"
        ] = "merchant_payment_public_cutover_not_approved"
        owner_approval_payload["readiness"]["provider_status"]["billing"]["merchant_launch_path"][  # type: ignore[index]
            "current_stage"
        ] = "controlled_acceptance_proven_public_charging_closed"
        owner_approval_payload["readiness"]["provider_status"]["billing"]["domestic_payment"][  # type: ignore[index]
            "status"
        ] = "controlled_acceptance_proven"
        owner_approval_fixture = run_public_readiness_fixture(bash, owner_approval_payload)
        if owner_approval_fixture.returncode != 0:
            return fail(
                "safe owner-approval billing warning must pass: "
                f"exit_{owner_approval_fixture.returncode}"
            )
        private_status_owner_marker_payload = mutated_public_readiness(
            ("readiness", "provider_status", "billing", "mainland_payment_ready_for_owner_approval"),
            True,
        )
        private_status_owner_marker_fixture = run_public_readiness_fixture(
            bash, private_status_owner_marker_payload
        )
        if private_status_owner_marker_fixture.returncode == 0:
            return fail("private-beta billing status must require owner-approval marker false")
        owner_status_private_marker_payload = copy.deepcopy(owner_approval_payload)
        owner_status_private_marker_payload["readiness"]["provider_status"]["billing"][  # type: ignore[index]
            "mainland_payment_ready_for_owner_approval"
        ] = False
        owner_status_private_marker_fixture = run_public_readiness_fixture(
            bash, owner_status_private_marker_payload
        )
        if owner_status_private_marker_fixture.returncode == 0:
            return fail("owner-approval billing status must require owner-approval marker true")
        backend_safety_warning_payload = current_public_readiness_payload()
        backend_safety_billing = backend_safety_warning_payload["readiness"]["provider_status"][  # type: ignore[index]
            "billing"
        ]
        backend_safety_billing["payment_path_status"] = "backend_safety_controls_in_progress"  # type: ignore[index]
        backend_safety_billing["next_paid_launch_blocker"] = (  # type: ignore[index]
            "merchant_payment_backend_safety_controls_incomplete"
        )
        backend_safety_billing["merchant_launch_path"][  # type: ignore[index]
            "current_stage"
        ] = "backend_safety_controls_in_progress"
        backend_safety_billing["domestic_payment"][  # type: ignore[index]
            "status"
        ] = "backend_safety_controls_in_progress"
        backend_safety_warning_fixture = run_public_readiness_fixture(
            bash, backend_safety_warning_payload
        )
        if backend_safety_warning_fixture.returncode == 0:
            return fail("private-beta billing warning must reject backend safety incomplete stage")
        for invalid_verified_count in (0, -1, 1.5, True, "1"):
            invalid_owner_count_payload = copy.deepcopy(owner_approval_payload)
            invalid_owner_count_payload["readiness"]["provider_status"]["billing"][  # type: ignore[index]
                "verified_paid_order_count"
            ] = invalid_verified_count
            invalid_owner_count_payload["readiness"]["provider_status"]["billing"]["domestic_payment"][  # type: ignore[index]
                "verified_paid_order_count"
            ] = invalid_verified_count
            invalid_owner_count_fixture = run_public_readiness_fixture(
                bash, invalid_owner_count_payload
            )
            if invalid_owner_count_fixture.returncode == 0:
                return fail("owner-approval status requires strict positive verified order count")
        mismatched_owner_count_payload = copy.deepcopy(owner_approval_payload)
        mismatched_owner_count_payload["readiness"]["provider_status"]["billing"]["domestic_payment"][  # type: ignore[index]
            "verified_paid_order_count"
        ] = 2
        mismatched_owner_count_fixture = run_public_readiness_fixture(
            bash, mismatched_owner_count_payload
        )
        if mismatched_owner_count_fixture.returncode == 0:
            return fail("owner-approval verified order counts must match across billing summaries")
        repeated_key_json = json.dumps(
            current_public_readiness_payload(), ensure_ascii=True, separators=(",", ":")
        ).replace('"blocker_count":0', '"blocker_count":0,"blocker_count":0', 1)
        repeated_key_fixture = run_public_readiness_json_fixture(bash, repeated_key_json)
        if repeated_key_fixture.returncode == 0:
            return fail("public readiness JSON must reject repeated object keys")
        for field, invalid_value in (
            ("public_contract_version", "stale-contract"),
            ("detail_scope", "internal_detail"),
            ("internal_detail_required", False),
            ("environment", "staging"),
        ):
            invalid_payload = current_public_readiness_payload()
            invalid_payload["readiness"][field] = invalid_value  # type: ignore[index]
            invalid_fixture = run_public_readiness_fixture(bash, invalid_payload)
            if invalid_fixture.returncode == 0:
                return fail(f"public readiness must reject invalid {field}")
        blocker_item_payload = current_public_readiness_payload()
        blocker_item_payload["readiness"]["items"].append(  # type: ignore[index,union-attr]
            {"key": "unexpected_blocker", "status": "blocked", "severity": "blocker"}
        )
        false_blocker_count_payload = current_public_readiness_payload()
        false_blocker_count_payload["readiness"]["blocker_count"] = False  # type: ignore[index]
        wrong_warning_count_payload = current_public_readiness_payload()
        wrong_warning_count_payload["readiness"]["warning_count"] = 0  # type: ignore[index]
        boolean_warning_count_payload = current_public_readiness_payload()
        boolean_warning_count_payload["readiness"]["warning_count"] = True  # type: ignore[index]
        negative_blocker_count_payload = current_public_readiness_payload()
        negative_blocker_count_payload["readiness"]["blocker_count"] = -1  # type: ignore[index]
        negative_warning_count_payload = current_public_readiness_payload()
        negative_warning_count_payload["readiness"]["warning_count"] = -1  # type: ignore[index]
        fraction_blocker_count_payload = current_public_readiness_payload()
        fraction_blocker_count_payload["readiness"]["blocker_count"] = 0.0  # type: ignore[index]
        fraction_warning_count_payload = current_public_readiness_payload()
        fraction_warning_count_payload["readiness"]["warning_count"] = 1.0  # type: ignore[index]
        for label, invalid_payload in (
            ("blocker item with zero count", blocker_item_payload),
            ("boolean blocker count", false_blocker_count_payload),
            ("warning count mismatch", wrong_warning_count_payload),
            ("boolean warning count", boolean_warning_count_payload),
            ("negative blocker count", negative_blocker_count_payload),
            ("negative warning count", negative_warning_count_payload),
            ("fractional blocker count", fraction_blocker_count_payload),
            ("fractional warning count", fraction_warning_count_payload),
        ):
            invalid_fixture = run_public_readiness_fixture(bash, invalid_payload)
            if invalid_fixture.returncode == 0:
                return fail(f"public readiness must reject {label}")
        non_list_items_payload = current_public_readiness_payload()
        non_list_items_payload["readiness"]["items"] = "not-a-list"  # type: ignore[index]
        duplicate_item_payload = current_public_readiness_payload()
        duplicate_item_payload["readiness"]["items"].append(  # type: ignore[index,union-attr]
            {
                "key": "billing_quota",
                "status": "private_beta_ready_paid_launch_pending",
                "severity": "warning",
            }
        )
        duplicate_item_payload["readiness"]["warning_count"] = 2  # type: ignore[index]
        unknown_severity_payload = current_public_readiness_payload()
        unknown_severity_payload["readiness"]["items"][0]["severity"] = "notice"  # type: ignore[index]
        unknown_severity_payload["readiness"]["warning_count"] = 0  # type: ignore[index]
        for label, invalid_payload in (
            ("non-list items", non_list_items_payload),
            ("duplicate item key", duplicate_item_payload),
            ("unknown item severity", unknown_severity_payload),
        ):
            invalid_fixture = run_public_readiness_fixture(bash, invalid_payload)
            if invalid_fixture.returncode == 0:
                return fail(f"public readiness must reject {label}")
        for forbidden_key in ("backup_restore", "monitoring_alerting"):
            invalid_payload = current_public_readiness_payload()
            invalid_payload["readiness"]["items"].append(  # type: ignore[index,union-attr]
                {"key": forbidden_key, "status": "blocked", "severity": "warning"}
            )
            invalid_payload["readiness"]["warning_count"] = 2  # type: ignore[index]
            invalid_fixture = run_public_readiness_fixture(bash, invalid_payload)
            if invalid_fixture.returncode == 0:
                return fail(f"public readiness must reject internal item {forbidden_key}")
        unknown_warning_payload = current_public_readiness_payload()
        unknown_warning_payload["readiness"]["items"].append(  # type: ignore[index,union-attr]
            {"key": "unknown_public_warning", "status": "pending", "severity": "warning"}
        )
        unknown_warning_payload["readiness"]["warning_count"] = 2  # type: ignore[index]
        unknown_warning_fixture = run_public_readiness_fixture(bash, unknown_warning_payload)
        if unknown_warning_fixture.returncode == 0:
            return fail("fixed public readiness contract must reject unknown warnings")
        extra_root_payload = current_public_readiness_payload()
        extra_root_payload["internal_debug"] = {"status": "must-not-be-public"}
        extra_readiness_payload = current_public_readiness_payload()
        extra_readiness_payload["readiness"]["internal_state"] = "must-not-be-public"  # type: ignore[index]
        nested_secret_payload = current_public_readiness_payload()
        nested_secret_payload["readiness"]["readiness_version"] = {  # type: ignore[index]
            "raw_secret": "must-not-be-public"
        }
        unknown_provider_payload = current_public_readiness_payload()
        unknown_provider_payload["readiness"]["provider_status"]["unknown_provider"] = {}  # type: ignore[index]
        raw_token_payload = current_public_readiness_payload()
        raw_token_payload["readiness"]["provider_status"]["billing"][  # type: ignore[index]
            "raw_token"
        ] = "must-not-be-public"
        unknown_provider_field_payload = current_public_readiness_payload()
        unknown_provider_field_payload["readiness"]["provider_status"]["billing"][  # type: ignore[index]
            "future_public_field"
        ] = False
        item_secret_payload = current_public_readiness_payload()
        item_secret_payload["readiness"]["items"][0]["raw_secret"] = "must-not-be-public"  # type: ignore[index]
        for label, invalid_payload in (
            ("unknown response field", extra_root_payload),
            ("unknown readiness internal field", extra_readiness_payload),
            ("nested raw secret field", nested_secret_payload),
            ("unknown provider", unknown_provider_payload),
            ("provider raw token field", raw_token_payload),
            ("unknown provider subfield", unknown_provider_field_payload),
            ("item raw secret field", item_secret_payload),
        ):
            invalid_fixture = run_public_readiness_fixture(bash, invalid_payload)
            if invalid_fixture.returncode == 0:
                return fail(f"fixed public readiness schema must reject {label}")
        search_runtime_key_payload = current_public_readiness_payload()
        search_runtime_key_payload["readiness"]["provider_status"]["public_search"][  # type: ignore[index]
            "runtime_gets_search_api_key"
        ] = "LEAK"
        search_runtime_key_fixture = run_public_readiness_fixture(bash, search_runtime_key_payload)
        if search_runtime_key_fixture.returncode == 0:
            return fail("public search runtime API key exposure must fail closed")
        readiness_service_object_payload = current_public_readiness_payload()
        readiness_service_object_payload["readiness"]["service"] = {  # type: ignore[index]
            "unknown_debug_schema": "x"
        }
        model_status_object_payload = current_public_readiness_payload()
        model_status_object_payload["readiness"]["provider_status"]["model_value"][  # type: ignore[index]
            "status"
        ] = {"unknown_debug_schema": "x"}
        packet_status_object_payload = current_public_readiness_payload()
        packet_status_object_payload["readiness"]["product_evidence"][  # type: ignore[index]
            "latest_ebay_packet_status"
        ] = {"unknown_debug_schema": "x"}
        for label, invalid_payload in (
            ("object-valued readiness service", readiness_service_object_payload),
            ("object-valued model status", model_status_object_payload),
            ("object-valued packet status", packet_status_object_payload),
        ):
            invalid_fixture = run_public_readiness_fixture(bash, invalid_payload)
            if invalid_fixture.returncode == 0:
                return fail(f"public readiness leaf schema must reject {label}")
        false_safety_paths = (
            ("readiness", "authenticated_summary"),
            ("readiness", "product_evidence", "secret_exposed"),
            ("readiness", "operational_health", "secret_exposed"),
            ("readiness", "provider_status", "model_value", "secret_exposed"),
            ("readiness", "provider_status", "ai_ceo_platform_model", "frontend_can_grant_quota"),
            ("readiness", "provider_status", "ai_ceo_platform_model", "frontend_gets_model_api_key"),
            ("readiness", "provider_status", "ai_ceo_platform_model", "runtime_gets_model_api_key"),
            ("readiness", "provider_status", "ai_ceo_platform_model", "secret_exposed"),
            ("readiness", "provider_status", "public_search", "frontend_gets_search_api_key"),
            ("readiness", "provider_status", "public_search", "runtime_gets_search_api_key"),
            ("readiness", "provider_status", "public_search", "secret_exposed"),
            ("readiness", "provider_status", "media_generation", "spend_now_allowed"),
            ("readiness", "provider_status", "media_generation", "frontend_gets_media_api_key"),
            ("readiness", "provider_status", "media_generation", "runtime_gets_raw_secret"),
            ("readiness", "provider_status", "media_generation", "reports_get_raw_provider_response"),
            ("readiness", "provider_status", "media_generation", "raw_provider_response_stored"),
            ("readiness", "provider_status", "media_generation", "secret_exposed"),
            ("readiness", "provider_status", "billing", "calls_external_payment_api"),
            ("readiness", "provider_status", "billing", "frontend_gets_payment_secret"),
            ("readiness", "provider_status", "billing", "frontend_can_grant_quota"),
            ("readiness", "provider_status", "billing", "merchant_launch_path", "public_paid_launch_allowed"),
            ("readiness", "provider_status", "billing", "merchant_launch_path", "charge_now_allowed"),
            ("readiness", "provider_status", "billing", "merchant_launch_path", "triggers_real_charge"),
            ("readiness", "provider_status", "billing", "merchant_launch_path", "frontend_can_grant_entitlement"),
            ("readiness", "provider_status", "billing", "merchant_launch_path", "frontend_can_grant_quota"),
            ("readiness", "provider_status", "billing", "merchant_launch_path", "secret_exposed"),
            ("readiness", "provider_status", "billing", "domestic_payment", "public_charging_allowed"),
            ("readiness", "provider_status", "billing", "domestic_payment", "charge_now_allowed"),
            ("readiness", "provider_status", "billing", "domestic_payment", "triggers_real_charge"),
            ("readiness", "provider_status", "billing", "domestic_payment", "triggers_real_refund"),
            ("readiness", "provider_status", "billing", "domestic_payment", "calls_external_payment_api"),
            ("readiness", "provider_status", "billing", "domestic_payment", "frontend_gets_payment_secret"),
            ("readiness", "provider_status", "billing", "domestic_payment", "secret_exposed"),
        )
        for path in false_safety_paths:
            invalid_fixture = run_public_readiness_fixture(
                bash, mutated_public_readiness(path, True)
            )
            if invalid_fixture.returncode == 0:
                return fail("public readiness safety field must remain strict false: " + ".".join(path))
        true_readiness_paths = (
            ("readiness", "product_evidence", "latest_ebay_packet_current_connection"),
            ("readiness", "provider_status", "model_value", "ready"),
            ("readiness", "provider_status", "ai_ceo_platform_model", "configured"),
            ("readiness", "provider_status", "public_search", "credential_present"),
            ("readiness", "provider_status", "media_generation", "configured"),
            ("readiness", "provider_status", "billing", "provider_configured"),
            ("readiness", "provider_status", "billing", "merchant_launch_path", "backend_confirmation_required_before_entitlement"),
        )
        for path in true_readiness_paths:
            invalid_fixture = run_public_readiness_fixture(
                bash, mutated_public_readiness(path, "true")
            )
            if invalid_fixture.returncode == 0:
                return fail("public readiness true marker must be strict bool: " + ".".join(path))
        for invalid_count in (-1, True, 1.5):
            invalid_fixture = run_public_readiness_fixture(
                bash,
                mutated_public_readiness(
                    ("readiness", "product_evidence", "ebay_token_refresh_success_count"),
                    invalid_count,
                ),
            )
            if invalid_fixture.returncode == 0:
                return fail("eBay refresh count must be a strict nonnegative integer")
        leaf_quality_cases = (
            (
                "invalid eBay packet source enum",
                ("readiness", "product_evidence", "latest_ebay_packet_source_mode"),
                "unknown_source",
            ),
            (
                "string historical packet marker",
                ("readiness", "product_evidence", "historical_ebay_packet_present"),
                "false",
            ),
            (
                "string product secret marker",
                ("readiness", "product_evidence", "secret_exposed"),
                "false",
            ),
            (
                "boolean model blocker count",
                ("readiness", "provider_status", "model_value", "blocker_count"),
                False,
            ),
            (
                "unknown platform model provider",
                ("readiness", "provider_status", "ai_ceo_platform_model", "provider"),
                "unknown_model_provider",
            ),
            (
                "unknown media readiness status",
                ("readiness", "provider_status", "media_generation", "status"),
                "unknown",
            ),
            (
                "string billing public charging marker",
                ("readiness", "provider_status", "billing", "public_charging_allowed"),
                "false",
            ),
            (
                "string launch public paid marker",
                ("readiness", "provider_status", "billing", "merchant_launch_path", "public_paid_launch_allowed"),
                "false",
            ),
            (
                "string domestic public charging marker",
                ("readiness", "provider_status", "billing", "domestic_payment", "public_charging_allowed"),
                "false",
            ),
            (
                "unknown operational status",
                ("readiness", "operational_health", "status"),
                "unknown",
            ),
        )
        for label, path, invalid_value in leaf_quality_cases:
            invalid_fixture = run_public_readiness_fixture(
                bash, mutated_public_readiness(path, invalid_value)
            )
            if invalid_fixture.returncode == 0:
                return fail(f"public readiness leaf contract must reject {label}")
        internal_backup_payload = current_public_readiness_payload()
        internal_backup_payload["readiness"]["provider_status"]["backup"] = {  # type: ignore[index]
            "backup_ready_for_paid_launch": True,
            "internal_evidence": "must-not-be-public",
        }
        internal_backup_fixture = run_public_readiness_fixture(bash, internal_backup_payload)
        if internal_backup_fixture.returncode == 0:
            return fail("public readiness must reject exposed internal backup provider details")
        billing_private_beta_payload = current_public_readiness_payload()
        billing_private_beta_payload["readiness"]["provider_status"]["billing"][  # type: ignore[index]
            "billing_ready_for_private_beta"
        ] = False
        billing_paid_launch_payload = current_public_readiness_payload()
        billing_paid_launch_payload["readiness"]["provider_status"]["billing"][  # type: ignore[index]
            "billing_ready_for_paid_launch"
        ] = True
        billing_quota_payload = current_public_readiness_payload()
        billing_quota_payload["readiness"]["provider_status"]["billing"][  # type: ignore[index]
            "quota_enforcement_enabled"
        ] = False
        billing_item_payload = current_public_readiness_payload()
        billing_item_payload["readiness"]["items"][0]["status"] = "ready"  # type: ignore[index]
        for label, invalid_payload in (
            ("billing private beta not ready", billing_private_beta_payload),
            ("billing paid launch unexpectedly ready", billing_paid_launch_payload),
            ("billing quota enforcement disabled", billing_quota_payload),
            ("billing warning status drift", billing_item_payload),
        ):
            invalid_fixture = run_public_readiness_fixture(bash, invalid_payload)
            if invalid_fixture.returncode == 0:
                return fail(f"public readiness must reject {label}")
        for field, unsafe_value in (
            ("production_ready", True),
            ("beta_ready", False),
            ("can_accept_real_customers", True),
            ("real_platform_writes_enabled", True),
            ("requested_real_platform_writes", True),
            ("secret_exposed", True),
        ):
            invalid_payload = current_public_readiness_payload()
            invalid_payload["readiness"][field] = unsafe_value  # type: ignore[index]
            invalid_fixture = run_public_readiness_fixture(bash, invalid_payload)
            if invalid_fixture.returncode == 0:
                return fail(f"public readiness must reject unsafe {field}")
        for field in (
            "public_charging_allowed",
            "charge_now_allowed",
            "triggers_real_charge",
            "triggers_real_refund",
            "real_platform_writes_enabled",
            "secret_exposed",
        ):
            invalid_payload = current_public_readiness_payload()
            invalid_payload["readiness"]["provider_status"]["billing"][field] = True  # type: ignore[index]
            invalid_fixture = run_public_readiness_fixture(bash, invalid_payload)
            if invalid_fixture.returncode == 0:
                return fail(f"public readiness must reject unsafe billing {field}")
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

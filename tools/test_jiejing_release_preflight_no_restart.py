"""Offline Bash fault injection: rejected preflight must not restart live services."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APPLY = ROOT / "deploy/jiejing-production-release-apply.sh"


def function(source: str, name: str) -> str:
    match = re.search(r"^" + re.escape(name) + r"\(\) \{\n.*?^\}", source, re.M | re.S)
    if not match:
        raise AssertionError("missing deployment function: " + name)
    return match.group(0)


def run_bash(script: str, cwd: Path):
    return subprocess.run(["/bin/bash", "--noprofile", "--norc", "-s"],
        input=script, text=True, capture_output=True, cwd=cwd,
        env={"PATH": "/usr/bin:/bin", "HOME": str(cwd)}, timeout=20)


def run_release_fault(mode: str):
    source = APPLY.read_text(encoding="utf-8")
    names = ["image_ref_id", "rollback_application_release", "disarm_unit_transaction_traps", "rollback_on_error",
             "build_candidate_images_with_retry", "capture_candidate_runtime_images"]
    if "restore_previous_runtime_image_tags()" in source:
        names.append("restore_previous_runtime_image_tags")
    functions = "\n".join(function(source, name) for name in names)
    start = source.index('current_stage="capture_previous_runtime_images"')
    end = source.index('current_stage="start_candidate_frontend"', start)
    stages = source[start:end]
    # Only Docker, existing health/lock observations and evidence export are
    # substituted. The deployment stage ordering, trap and rollback are real.
    with tempfile.TemporaryDirectory(prefix="jiejing-preflight-fault-") as temp:
        root = Path(temp)
        header = r'''
set -euo pipefail
events="$PWD/events"
mode=MODE
mutation_started=0
runtime_mutation_started=0
active_switched=0
unit_transaction_active=0
rollback_image_holds_ready=1
previous_ops_supported=1
previous_api_image_id="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
previous_worker_image_id="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
previous_api_image_ref=deploy-jiejing-saas
previous_worker_image_ref=deploy-jiejing-worker
ROLLBACK_API_HOLD_REF=rollback-api
ROLLBACK_WORKER_HOLD_REF=rollback-worker
candidate_api_image_id="sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
candidate_worker_image_id="sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
active_app=/synthetic/previous/app
candidate_app=/synthetic/candidate/app
ACTIVE_LINK=/synthetic/active
private_dir=/synthetic/private
candidate_compose=(docker compose -p candidate)
previous_compose=(docker compose -p previous)
docker() {
  printf '%s\n' "$*" >>"$events"
  if [[ "$1 $2" == 'image inspect' ]]; then
    case "$3" in
      rollback-api) printf '%s\n' "$previous_api_image_id" ;;
      rollback-worker) printf '%s\n' "$previous_worker_image_id" ;;
      deploy-jiejing-saas) if [[ -f api-restored ]]; then printf '%s\n' "$previous_api_image_id"; else printf '%s\n' "$candidate_api_image_id"; fi ;;
      deploy-jiejing-worker) if [[ -f worker-restored ]]; then printf '%s\n' "$previous_worker_image_id"; else printf '%s\n' "$candidate_worker_image_id"; fi ;;
      *) printf '%s\n' "$3" ;;
    esac
  elif [[ "$1 $2" == 'image tag' ]]; then
    [[ "$mode" != tag_restore_fails ]] || return 17
    case "$4" in deploy-jiejing-saas) touch api-restored ;; deploy-jiejing-worker) touch worker-restored ;; esac
  elif [[ "$1" == run ]]; then
    [[ "$mode" != preflight_rejected && "$mode" != tag_restore_fails ]] || return 2
  elif [[ "$1 $2 $3 $4 $5" == 'compose -p candidate up -d' ]]; then
    [[ "$mode" != replacement_fails ]] || return 73
  fi
  return 0
}
capture_previous_runtime_images() { return 0; }
initialize_runtime_evidence_snapshot() { return 0; }
wait_container_healthy() { return 0; }
verify_candidate_runtime_image_coherence() { return 0; }
verify_previous_runtime_restored() { return 0; }
verify_ops_surface() { return 0; }
wait_public_json() { return 0; }
ops_dns_points_to_old_host() { return 0; }
acquire_maintenance_lock_for_rollback() { return 0; }
release_maintenance_lock() { return 0; }
release_deploy_lock() { return 0; }
readlink() { printf '%s\n' "$active_app"; }
'''.replace("MODE", shlex.quote(mode))
        result = run_bash(header + functions + "\ntrap rollback_on_error ERR\n" + stages, root)
        events = (root / "events").read_text() if (root / "events").exists() else ""
        return result, events


class ReleasePreflightNoRestart(unittest.TestCase):
    def test_rejected_backup_preflight_restores_tags_without_compose_up(self):
        result, events = run_release_fault("preflight_rejected")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn(" up ", events, "preflight refusal must not restart the still-running old API/worker")
        self.assertIn("image tag rollback-api deploy-jiejing-saas", events)
        self.assertIn("image tag rollback-worker deploy-jiejing-worker", events)

    def test_actual_replacement_failure_still_rolls_back_old_services(self):
        result, events = run_release_fault("replacement_fails")
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertIn("compose -p candidate up -d --no-deps jiejing-saas", events)
        self.assertIn("compose -p previous up -d --no-build --no-deps --force-recreate jiejing-saas", events)
        self.assertIn("compose -p previous up -d --no-build --no-deps --force-recreate jiejing-worker", events)
        self.assertIn("JIEJING_PRODUCTION_ROLLBACK_APPLIED=1", result.stderr)

    def test_tag_restore_failure_does_not_restart_or_claim_rollback_success(self):
        result, events = run_release_fault("tag_restore_fails")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn(" up ", events)
        self.assertIn("JIEJING_PRODUCTION_IMAGE_TAG_RESTORE_INCOMPLETE=1", result.stderr)
        self.assertNotIn("JIEJING_PRODUCTION_ROLLBACK_APPLIED=1", result.stderr)

    def test_missing_shared_route_is_rejected_before_any_docker_action(self):
        source = APPLY.read_text(encoding="utf-8")
        self.assertLess(source.index('verify_pindd_notification_templates "$resolved_patch_dir" "$active_app"'),
                        source.index('current_stage="capture_previous_runtime_images"'))
        for missing in ("route_directory", "socket_directory", "enabled_marker", "route_file", "route_symlink"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory(prefix="jiejing-route-preflight-") as temp:
                root = Path(temp)
                route, socket = root / "route", root / "socket"
                if missing != "route_directory":
                    route.mkdir()
                    if missing != "enabled_marker": (route / "enabled.json").write_text("{}")
                    if missing != "route_file": (route / "Caddyfile.notify").write_text("# synthetic public route\n")
                if missing != "socket_directory": socket.mkdir()
                if missing == "route_symlink":
                    alias = root / "route-alias"
                    alias.symlink_to(route, target_is_directory=True)
                    route = alias
                guard = function(source, "verify_pindd_notification_templates")
                guard = guard.replace("/opt/pindd/shared-ingress", str(route))
                guard = guard.replace("/var/lib/pindd/staging/notify-socket", str(socket))
                script = 'set -euo pipefail\n' + function(source, "refuse") + '\n' + guard + r'''
docker() { printf '%s\n' "$*" >>events; }
verify_pindd_notification_templates /synthetic/candidate /synthetic/previous || refuse "REFUSE_PINDD_NOTIFICATION_PERSISTENCE=1" 41
docker compose -p candidate build
'''
                result = run_bash(script, root)
                self.assertEqual(result.returncode, 41, result.stderr)
                self.assertIn("REFUSE_PINDD_NOTIFICATION_DEPENDENCY_MISSING=1", result.stderr)
                self.assertFalse((root / "events").exists(), "missing route must stop before Docker build or replacement")


def main():
    if os.name == "nt":
        source = Path(__file__).resolve()
        linux_source = "/mnt/" + source.drive[0].lower() + source.as_posix()[2:]
        command = ["wsl", "-d", "Ubuntu", "--exec", "env", "-i", "PATH=/usr/bin:/bin",
                   "PYTHONDONTWRITEBYTECODE=1", "python3", "-B", linux_source, *sys.argv[1:]]
        return subprocess.run(command, timeout=120).returncode
    unittest.main(verbosity=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

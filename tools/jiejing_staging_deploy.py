#!/usr/bin/env python3
"""Upload and apply a Jiejing SaaS staging patch over stable SSH."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LEGACY_DEFAULT_KEY = ROOT / "output" / "route-a-edge-ssh" / "jiejing_route_a_edge_ed25519"
WORKING_DEFAULT_KEY = Path.home() / ".ssh" / "jiejing_43_ubuntu_ed25519"
DEFAULT_KEY = WORKING_DEFAULT_KEY if WORKING_DEFAULT_KEY.exists() else LEGACY_DEFAULT_KEY
DEFAULT_KNOWN_HOSTS = ROOT / "output" / "deploy-keys" / "known_hosts"
DEFAULT_PUBLIC_URL = "https://app.jiejing.shop"
DEFAULT_PORT = 2222
SSH_STABILITY_OPTIONS = [
    ("KexAlgorithms", "ecdh-sha2-nistp256"),
    ("Ciphers", "aes128-ctr"),
    ("MACs", "hmac-sha2-256"),
    ("IPQoS", "none"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy a whitelisted Jiejing staging patch through SSH.")
    parser.add_argument("--host", default="43.129.205.244")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--user", default="ubuntu")
    parser.add_argument("--ssh-key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--known-hosts", type=Path, default=DEFAULT_KNOWN_HOSTS)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--app-path", default="/opt/jiejing-staging/app")
    parser.add_argument("--public-url", default=DEFAULT_PUBLIC_URL)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--skip-doctor", action="store_true")
    parser.add_argument("--disk-warning-percent", type=int, default=80)
    parser.add_argument("--disk-block-percent", type=int, default=92)
    parser.add_argument("--disk-min-free-gib", type=int, default=2)
    parser.add_argument(
        "--transfer-mode",
        choices=("auto", "scp", "ssh-stdin"),
        default="auto",
        help="Upload bundle with scp first by default, then fall back to ssh stdin when the server closes scp/sftp.",
    )
    parser.add_argument(
        "--remote-temp-keep",
        type=int,
        default=4,
        help="Keep this many newest /tmp/jiejing-public-staging-* upload/extract artifacts after a successful deploy.",
    )
    parser.add_argument("--remote-patch-backup-keep", type=int, default=8)
    parser.add_argument("--remote-runner-backup-keep", type=int, default=5)
    parser.add_argument("--remote-runner-release-keep", type=int, default=5)
    parser.add_argument("--remote-build-cache-until-hours", type=int, default=1)
    parser.add_argument("--skip-remote-temp-cleanup", action="store_true")
    parser.add_argument("--skip-remote-deploy-artifact-cleanup", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    patch = args.patch.resolve()
    if not patch.exists():
        return fail(f"patch_not_found: {patch}")
    if not args.ssh_key.exists():
        return fail(f"ssh_key_not_found: {args.ssh_key}")
    if args.remote_temp_keep < 1:
        return fail("remote_temp_keep_must_be_positive")
    if min(args.remote_patch_backup_keep, args.remote_runner_backup_keep, args.remote_runner_release_keep) < 1:
        return fail("remote_deploy_artifact_keep_must_be_positive")
    if not 1 <= args.remote_build_cache_until_hours <= 168:
        return fail("remote_build_cache_until_hours_out_of_range")
    if not 1 <= args.disk_warning_percent < args.disk_block_percent <= 99:
        return fail("remote_disk_thresholds_invalid")
    if args.disk_min_free_gib < 1:
        return fail("remote_disk_min_free_gib_must_be_positive")

    if not args.skip_doctor:
        doctor = _run_doctor(args)
        if not doctor.get("deploy_channel_ready"):
            print(json.dumps({"status": "blocked", "deploy_channel": doctor, "secret_exposed": False}, ensure_ascii=False, indent=2))
            return 2

    disk_preflight = _remote_disk_preflight(args)
    if disk_preflight.get("deploy_allowed") is not True:
        print(
            json.dumps(
                {"status": "blocked", "step": "remote_disk_preflight", "disk_preflight": disk_preflight, "secret_exposed": False},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    remote_zip = f"/tmp/{patch.name}"
    remote_dir = f"/tmp/{patch.stem}"
    args.known_hosts.parent.mkdir(parents=True, exist_ok=True)
    upload_result = _upload_patch(args, patch, remote_zip)

    remote_script = " && ".join(
        [
            f"rm -rf {shlex.quote(remote_dir)}",
            f"mkdir -p {shlex.quote(remote_dir)}",
            f"unzip -q -o {shlex.quote(remote_zip)} -d {shlex.quote(remote_dir)}",
            f"cd {shlex.quote(args.app_path)}",
            f"sudo -n JIEJING_APP_DIR={shlex.quote(args.app_path)} bash {shlex.quote(remote_dir)}/deploy/apply-staging-patch.sh {shlex.quote(remote_dir)}",
        ]
    )
    ssh_cmd = _ssh_base(args) + [remote_script]
    result = _run(ssh_cmd, label="apply_patch", timeout=_operation_timeout_seconds(args))
    cleanup_result = {}
    if not args.skip_remote_temp_cleanup:
        cleanup_result = _cleanup_remote_staging_tmp(args)
    artifact_cleanup_result = {}
    if not args.skip_remote_deploy_artifact_cleanup:
        artifact_cleanup_result = _cleanup_remote_deploy_artifacts(args)
    print(
        json.dumps(
            {
                "status": "deployed",
                "patch": str(patch),
                "host": args.host,
                "port": args.port,
                "user": args.user,
                "app_path": args.app_path,
                "disk_preflight": disk_preflight,
                "upload": upload_result,
                "stdout_tail": result.stdout[-2000:],
                "stderr_tail": result.stderr[-2000:],
                "remote_temp_cleanup": cleanup_result,
                "remote_deploy_artifact_cleanup": artifact_cleanup_result,
                "secret_exposed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _remote_disk_preflight(args: argparse.Namespace) -> dict[str, Any]:
    command = (
        "LC_ALL=C df -Pk -- "
        + shlex.quote(args.app_path)
        + " /tmp"
    )
    completed = _run(
        _ssh_base(args) + [command],
        label="remote_disk_preflight",
        timeout=_operation_timeout_seconds(args),
    )
    classified = classify_remote_disk_report(
        parse_remote_disk_report(completed.stdout),
        warning_percent=args.disk_warning_percent,
        block_percent=args.disk_block_percent,
        min_free_bytes=args.disk_min_free_gib * 1024**3,
    )
    return {
        **classified,
        "checked_paths": [args.app_path, "/tmp"],
        "warning_percent": args.disk_warning_percent,
        "block_percent": args.disk_block_percent,
        "min_free_gib": args.disk_min_free_gib,
    }


def parse_remote_disk_report(output: str) -> list[dict[str, Any]]:
    mounts: dict[str, dict[str, Any]] = {}
    for raw_line in str(output or "").splitlines():
        parts = raw_line.split()
        if len(parts) < 6 or not parts[1].isdigit() or not parts[3].isdigit():
            continue
        percent_text = parts[4].rstrip("%")
        if not percent_text.isdigit():
            continue
        mount = " ".join(parts[5:]).strip()
        if not mount:
            continue
        mounts[mount] = {
            "mount": mount,
            "total_bytes": int(parts[1]) * 1024,
            "free_bytes": int(parts[3]) * 1024,
            "use_percent": int(percent_text),
        }
    return list(mounts.values())


def classify_remote_disk_report(
    report: list[dict[str, Any]],
    *,
    warning_percent: int,
    block_percent: int,
    min_free_bytes: int,
) -> dict[str, Any]:
    if not report:
        return {
            "status": "blocked",
            "reason": "remote_disk_report_unavailable",
            "deploy_allowed": False,
            "mounts": [],
            "secret_exposed": False,
        }
    safe_mounts = [
        {
            "mount": str(item.get("mount") or ""),
            "use_percent": int(item.get("use_percent") or 0),
            "free_bytes": int(item.get("free_bytes") or 0),
            "free_gib": round(int(item.get("free_bytes") or 0) / 1024**3, 2),
        }
        for item in report
    ]
    max_use = max(item["use_percent"] for item in safe_mounts)
    min_free = min(item["free_bytes"] for item in safe_mounts)
    if min_free < int(min_free_bytes):
        status = "blocked"
        reason = "remote_disk_free_space_below_minimum"
    elif max_use >= int(block_percent):
        status = "blocked"
        reason = "remote_disk_usage_block_threshold_reached"
    elif max_use >= int(warning_percent):
        status = "warning"
        reason = "remote_disk_usage_warning_threshold_reached"
    else:
        status = "ready"
        reason = "remote_disk_capacity_ready"
    return {
        "status": status,
        "reason": reason,
        "deploy_allowed": status != "blocked",
        "max_use_percent": max_use,
        "minimum_free_bytes": min_free,
        "mounts": safe_mounts,
        "secret_exposed": False,
    }


def _upload_patch(args: argparse.Namespace, patch: Path, remote_zip: str) -> dict[str, Any]:
    if args.transfer_mode != "ssh-stdin":
        scp_result = _try_upload_patch_with_scp(args, patch, remote_zip)
        if scp_result["returncode"] == 0:
            return {"mode": "scp", "secret_exposed": False}
        if args.transfer_mode == "scp":
            raise SystemExit(
                json.dumps(
                    {
                        "status": "failed",
                        "step": "scp_patch",
                        "returncode": scp_result["returncode"],
                        "stdout_tail": scp_result["stdout_tail"],
                        "stderr_tail": scp_result["stderr_tail"],
                        "secret_exposed": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )

    stdin_result = _upload_patch_with_ssh_stdin(args, patch, remote_zip)
    return {
        "mode": "ssh-stdin",
        "bytes": patch.stat().st_size,
        "scp_fallback_used": args.transfer_mode == "auto",
        "scp_failure": scp_result if args.transfer_mode == "auto" else None,
        "stdout_tail": stdin_result.stdout[-500:],
        "stderr_tail": stdin_result.stderr[-500:],
        "secret_exposed": False,
    }


def _try_upload_patch_with_scp(args: argparse.Namespace, patch: Path, remote_zip: str) -> dict[str, Any]:
    target = f"{args.user}@{args.host}"
    command = [
        "scp",
        "-O",
        "-P",
        str(args.port),
        "-i",
        str(args.ssh_key),
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={args.timeout}",
        *_known_hosts_option_args(args.known_hosts),
        *_ssh_stability_option_args(),
        str(patch),
        f"{target}:{remote_zip}",
    ]
    timeout_seconds = _upload_timeout_seconds(args, patch)
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": 124,
            "stdout_tail": _text_tail(exc.stdout, 1000),
            "stderr_tail": f"scp_timeout_after_{timeout_seconds}s\n{_text_tail(exc.stderr, 1000)}",
            "secret_exposed": False,
        }
    return {
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-1000:],
        "stderr_tail": completed.stderr[-1000:],
        "secret_exposed": False,
    }


def _upload_patch_with_ssh_stdin(args: argparse.Namespace, patch: Path, remote_zip: str) -> subprocess.CompletedProcess[str]:
    command = _ssh_base(args) + [f"cat > {shlex.quote(remote_zip)}"]
    timeout_seconds = _upload_timeout_seconds(args, patch)
    with patch.open("rb") as stdin:
        try:
            completed = subprocess.run(
                command,
                cwd=str(ROOT),
                stdin=stdin,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise SystemExit(
                json.dumps(
                    {
                        "status": "failed",
                        "step": "ssh_stdin_patch",
                        "returncode": 124,
                        "stdout_tail": _text_tail(exc.stdout, 2000),
                        "stderr_tail": f"ssh_stdin_timeout_after_{timeout_seconds}s\n{_text_tail(exc.stderr, 2000)}",
                        "secret_exposed": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
    if completed.returncode != 0:
        raise SystemExit(
            json.dumps(
                {
                    "status": "failed",
                    "step": "ssh_stdin_patch",
                    "returncode": completed.returncode,
                    "stdout_tail": completed.stdout[-2000:],
                    "stderr_tail": completed.stderr[-2000:],
                    "secret_exposed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return completed


def _cleanup_remote_staging_tmp(args: argparse.Namespace) -> dict[str, Any]:
    """Remove old uploaded staging bundles from /tmp without touching app data."""

    script = f"""
set -euo pipefail
keep={int(args.remote_temp_keep)}
mapfile -t artifacts < <(find /tmp -maxdepth 1 \\( \\( -type f -name 'jiejing-public-staging-*.zip' \\) -o \\( -type d -name 'jiejing-public-staging-*' \\) \\) -printf '%T@ %p\\n' 2>/dev/null | sort -n | awk '{{ $1=\"\"; sub(/^ /,\"\"); print }}')
count="${{#artifacts[@]}}"
deleted=0
freed_candidates=0
if (( count > keep )); then
  delete_count=$((count - keep))
  for ((i=0; i<delete_count; i++)); do
    p="${{artifacts[$i]}}"
    real="$(readlink -f -- "$p" || true)"
    case "$real" in
      /tmp/jiejing-public-staging-*) ;;
      *) echo "REFUSE_UNSAFE_PATH=$p REAL=$real" >&2; exit 20 ;;
    esac
    if [[ "$real" == "/tmp" || "$real" == "/" || "$real" == "/tmp/jiejing-public-staging-" ]]; then
      echo "REFUSE_DANGEROUS_PATH=$real" >&2
      exit 21
    fi
    if [[ -e "$real" ]]; then
      size="$(du -sb -- "$real" 2>/dev/null | awk '{{print $1}}')"
      freed_candidates=$((freed_candidates + ${{size:-0}}))
      rm -rf -- "$real"
      deleted=$((deleted+1))
    fi
  done
fi
printf 'REMOTE_TMP_CLEANUP_ARTIFACTS_BEFORE=%s\\n' "$count"
printf 'REMOTE_TMP_CLEANUP_KEEP=%s\\n' "$keep"
printf 'REMOTE_TMP_CLEANUP_DELETED=%s\\n' "$deleted"
printf 'REMOTE_TMP_CLEANUP_BYTES_CANDIDATE=%s\\n' "$freed_candidates"
df -hPT / /tmp
"""
    result = _run(
        _ssh_base(args) + [f"bash -lc {shlex.quote(script)}"],
        label="remote_tmp_cleanup",
        timeout=_operation_timeout_seconds(args),
    )
    return {
        "enabled": True,
        "keep": args.remote_temp_keep,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-1000:],
        "secret_exposed": False,
    }


def build_remote_deploy_artifact_cleanup_script(args: argparse.Namespace) -> str:
    """Build a fail-closed cleanup script for disposable staging deploy artifacts."""

    app_path = str(args.app_path or "").rstrip("/")
    if app_path != "/opt/jiejing-staging/app":
        raise ValueError("remote deploy artifact cleanup only supports the canonical staging app path")
    patch_root = f"{app_path}/output/staging-patch-backups"
    runner_backup_root = "/opt/jiejing-staging/github-action-backups"
    runner_release_root = "/opt/jiejing-staging/github-action-releases"
    patch_keep = int(args.remote_patch_backup_keep)
    runner_backup_keep = int(args.remote_runner_backup_keep)
    runner_release_keep = int(args.remote_runner_release_keep)
    cache_hours = int(args.remote_build_cache_until_hours)
    if min(patch_keep, runner_backup_keep, runner_release_keep, cache_hours) < 1 or cache_hours > 168:
        raise ValueError("remote deploy artifact cleanup limits are invalid")

    return f"""
set -euo pipefail

retain_newest() {{
  label="$1"
  root="$2"
  name_pattern="$3"
  keep="$4"
  if [[ ! -d "$root" ]]; then
    printf 'REMOTE_DEPLOY_CLEANUP_%s_TOTAL=0\\n' "$label"
    printf 'REMOTE_DEPLOY_CLEANUP_%s_DELETED=0\\n' "$label"
    return 0
  fi
  resolved_root="$(readlink -f -- "$root" 2>/dev/null || true)"
  case "$resolved_root" in
    {patch_root}|{runner_backup_root}|{runner_release_root}) ;;
    *) echo "REFUSE_DEPLOY_CLEANUP_ROOT=$resolved_root" >&2; exit 31 ;;
  esac
  mapfile -t entries < <(find "$resolved_root" -mindepth 1 -maxdepth 1 -type d -name "$name_pattern" -printf '%T@ %p\\n' 2>/dev/null | sort -nr | awk '{{ $1=""; sub(/^ /,""); print }}')
  count="${{#entries[@]}}"
  deleted=0
  bytes_candidate=0
  if (( count > keep )); then
    for ((i=keep; i<count; i++)); do
      candidate="${{entries[$i]}}"
      candidate_real="$(readlink -f -- "$candidate" 2>/dev/null || true)"
      case "$label:$candidate_real" in
        patch_backups:"$resolved_root"/[0-9]*) ;;
        runner_backups:"$resolved_root"/pre-github-*) ;;
        runner_releases:"$resolved_root"/github-*) ;;
        *) echo "REFUSE_DEPLOY_CLEANUP_CANDIDATE=$label:$candidate_real" >&2; exit 32 ;;
      esac
      if [[ "$candidate_real" == "$resolved_root" || -z "$candidate_real" ]]; then
        echo "REFUSE_DEPLOY_CLEANUP_DANGEROUS_PATH=$candidate_real" >&2
        exit 33
      fi
      size="$(du -sb -- "$candidate_real" 2>/dev/null | awk '{{print $1}}')"
      bytes_candidate=$((bytes_candidate + ${{size:-0}}))
      rm -rf -- "$candidate_real"
      deleted=$((deleted + 1))
    done
  fi
  printf 'REMOTE_DEPLOY_CLEANUP_%s_TOTAL=%s\\n' "$label" "$count"
  printf 'REMOTE_DEPLOY_CLEANUP_%s_KEEP=%s\\n' "$label" "$keep"
  printf 'REMOTE_DEPLOY_CLEANUP_%s_DELETED=%s\\n' "$label" "$deleted"
  printf 'REMOTE_DEPLOY_CLEANUP_%s_BYTES_CANDIDATE=%s\\n' "$label" "$bytes_candidate"
}}

echo "REMOTE_DEPLOY_CLEANUP_DISK_BEFORE"
df -hPT -- / /tmp {app_path}
retain_newest "patch_backups" "{patch_root}" "[0-9]*" "{patch_keep}"
retain_newest "runner_backups" "{runner_backup_root}" "pre-github-*" "{runner_backup_keep}"
retain_newest "runner_releases" "{runner_release_root}" "github-*" "{runner_release_keep}"
if command -v docker >/dev/null 2>&1; then
  docker builder prune --all --force --filter 'until={cache_hours}h'
  echo "REMOTE_DEPLOY_CLEANUP_BUILD_CACHE=pruned_unused_older_than_{cache_hours}h"
else
  echo "REMOTE_DEPLOY_CLEANUP_BUILD_CACHE=skipped_docker_unavailable"
fi
echo "REMOTE_DEPLOY_CLEANUP_DISK_AFTER"
df -hPT -- / /tmp {app_path}
echo "REMOTE_DEPLOY_CLEANUP_STATUS=completed"
"""


def _cleanup_remote_deploy_artifacts(args: argparse.Namespace) -> dict[str, Any]:
    """Apply bounded retention after a healthy deploy without changing deploy success."""

    try:
        script = build_remote_deploy_artifact_cleanup_script(args)
    except (TypeError, ValueError) as exc:
        return {
            "status": "warning",
            "reason": str(exc),
            "secret_exposed": False,
        }
    command = _ssh_base(args) + [f"sudo -n bash -lc {shlex.quote(script)}"]
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=_operation_timeout_seconds(args),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "warning",
            "reason": "remote_deploy_artifact_cleanup_timeout",
            "stdout_tail": _text_tail(exc.stdout, 3000),
            "stderr_tail": _text_tail(exc.stderr, 1500),
            "secret_exposed": False,
        }
    return {
        "status": "completed" if completed.returncode == 0 else "warning",
        "returncode": completed.returncode,
        "patch_backup_keep": args.remote_patch_backup_keep,
        "runner_backup_keep": args.remote_runner_backup_keep,
        "runner_release_keep": args.remote_runner_release_keep,
        "build_cache_until_hours": args.remote_build_cache_until_hours,
        "stdout_tail": completed.stdout[-5000:],
        "stderr_tail": completed.stderr[-2000:],
        "secret_exposed": False,
    }


def _run_doctor(args: argparse.Namespace) -> dict[str, Any]:
    output = ROOT / "output" / "jiejing-deploy-channel-doctor" / "staging-deploy-latest.json"
    command = [
        sys.executable,
        str(ROOT / "tools" / "jiejing_deploy_channel_doctor.py"),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--user",
        args.user,
        "--ssh-key",
        str(args.ssh_key),
        "--known-hosts",
        str(args.known_hosts),
        "--public-url",
        args.public_url,
        "--timeout",
        str(args.timeout),
        "--out",
        str(output),
    ]
    completed = subprocess.run(command, cwd=str(ROOT), text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if output.exists():
        return json.loads(output.read_text(encoding="utf-8"))
    return {
        "deploy_channel_ready": False,
        "status": "doctor_failed",
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-1000:],
        "stderr_tail": completed.stderr[-1000:],
        "secret_exposed": False,
    }


def _ssh_base(args: argparse.Namespace) -> list[str]:
    return [
        "ssh",
        "-T",
        "-p",
        str(args.port),
        "-i",
        str(args.ssh_key),
        "-o",
        "BatchMode=yes",
        "-o",
        "LogLevel=ERROR",
        "-o",
        f"ConnectTimeout={args.timeout}",
        *_known_hosts_option_args(args.known_hosts),
        *_ssh_stability_option_args(),
        f"{args.user}@{args.host}",
    ]


def _known_hosts_option_args(path: Path) -> list[str]:
    return [
        "-o",
        f"UserKnownHostsFile={path}",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]


def _ssh_stability_option_args() -> list[str]:
    args: list[str] = []
    for key, value in SSH_STABILITY_OPTIONS:
        args.extend(["-o", f"{key}={value}"])
    return args


def _upload_timeout_seconds(args: argparse.Namespace, patch: Path) -> int:
    size_mib = max(1, patch.stat().st_size // (1024 * 1024))
    return max(args.timeout * 8, 180, size_mib * 4)


def _operation_timeout_seconds(args: argparse.Namespace) -> int:
    # The official CLS uploader currently compiles its constrained lz4 release
    # during no-cache image builds on Python 3.12. Keep SSH connect timeouts
    # short while allowing the remote build and health-gated rollout to finish.
    return max(args.timeout * 6, 600)


def _text_tail(value: str | bytes | None, length: int) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[-length:]
    return value[-length:]


def _run(command: list[str], *, label: str, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(
            json.dumps(
                {
                    "status": "failed",
                    "step": label,
                    "returncode": 124,
                    "stdout_tail": _text_tail(exc.stdout, 2000),
                    "stderr_tail": f"{label}_timeout_after_{timeout}s\n{_text_tail(exc.stderr, 2000)}",
                    "secret_exposed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    if completed.returncode != 0:
        raise SystemExit(
            json.dumps(
                {
                    "status": "failed",
                    "step": label,
                    "returncode": completed.returncode,
                    "stdout_tail": completed.stdout[-2000:],
                    "stderr_tail": completed.stderr[-2000:],
                    "secret_exposed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return completed


def fail(message: str) -> int:
    print(json.dumps({"status": "failed", "error": message, "secret_exposed": False}, ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Diagnose the Jiejing staging deployment channel without exposing secrets."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "output" / "jiejing-deploy-channel-doctor" / "latest.json"
LEGACY_DEFAULT_HK_KEY = ROOT / "output" / "route-a-edge-ssh" / "jiejing_route_a_edge_ed25519"
WORKING_DEFAULT_HK_KEY = Path.home() / ".ssh" / "jiejing_43_ubuntu_ed25519"
DEFAULT_HK_KEY = WORKING_DEFAULT_HK_KEY if WORKING_DEFAULT_HK_KEY.exists() else LEGACY_DEFAULT_HK_KEY
DEFAULT_KNOWN_HOSTS = ROOT / "output" / "deploy-keys" / "known_hosts"
DEFAULT_PUBLIC_URL = "https://app.jiejing.shop"
DEFAULT_PORT = 2222
SSH_STABILITY_OPTIONS = [
    ("KexAlgorithms", "ecdh-sha2-nistp256"),
    ("Ciphers", "aes128-ctr"),
    ("MACs", "hmac-sha2-256"),
    ("IPQoS", "none"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose SSH and public health for Jiejing staging.")
    parser.add_argument("--host", default="43.129.205.244", help="Staging server host or IP.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="SSH port.")
    parser.add_argument("--user", default="ubuntu", help="SSH user.")
    parser.add_argument("--ssh-key", type=Path, default=DEFAULT_HK_KEY, help="Private SSH key path.")
    parser.add_argument("--known-hosts", type=Path, default=DEFAULT_KNOWN_HOSTS, help="Deploy-specific known_hosts path.")
    parser.add_argument("--app-path", default="/opt/jiejing-staging/app", help="Remote app path.")
    parser.add_argument("--public-url", default=DEFAULT_PUBLIC_URL, help="Public staging URL.")
    parser.add_argument("--timeout", type=int, default=8, help="Network timeout in seconds.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Summary JSON output path.")
    args = parser.parse_args()

    summary = run_doctor(
        host=args.host,
        port=args.port,
        user=args.user,
        ssh_key=args.ssh_key,
        known_hosts=args.known_hosts,
        app_path=args.app_path,
        public_url=args.public_url,
        timeout_seconds=args.timeout,
        out_path=args.out,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"OUTPUT={args.out}")
    return 0 if summary.get("deploy_channel_ready") else 2


def run_doctor(
    *,
    host: str,
    port: int,
    user: str,
    ssh_key: Path | None,
    known_hosts: Path | None,
    app_path: str,
    public_url: str,
    timeout_seconds: int,
    out_path: Path = DEFAULT_OUT,
) -> dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    key_exists = bool(ssh_key and ssh_key.exists())
    tcp_check = _tcp_check(host=host, port=port, timeout_seconds=timeout_seconds)
    ssh_check = _ssh_check(
        host=host,
        port=port,
        user=user,
        ssh_key=ssh_key,
        known_hosts=known_hosts,
        app_path=app_path,
        timeout_seconds=timeout_seconds,
        can_attempt=key_exists and tcp_check.get("open") is True,
    )
    public_health = _public_health(public_url=public_url, timeout_seconds=timeout_seconds)
    deploy_channel_ready = ssh_check.get("status") == "usable"
    summary = {
        "product": "Jiejing SaaS",
        "task": "deploy_channel_doctor",
        "deploy_channel_ready": deploy_channel_ready,
        "public_staging_reachable": public_health.get("reachable") is True,
        "host": host,
        "ssh_port": port,
        "ssh_user": user,
        "ssh_key_path_configured": bool(ssh_key),
        "ssh_key_exists": key_exists,
        "tcp_ssh": tcp_check,
        "ssh": ssh_check,
        "public_health": public_health,
        "recommended_next_actions": _recommended_actions(ssh_check),
        "secret_exposed": False,
    }
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def classify_ssh_result(*, returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
    combined = f"{stdout}\n{stderr}"
    qcloud_security_login = "请使用微信扫码安全登录" in combined or "up.yd.qcloud.com/qr/" in combined
    permission_denied = "Permission denied" in combined
    host_key_changed = "REMOTE HOST IDENTIFICATION HAS CHANGED" in combined
    if host_key_changed:
        return {
            "status": "blocked",
            "blocker": "ssh_host_key_changed",
            "qcloud_security_login_seen": qcloud_security_login,
            "permission_denied": permission_denied,
        }
    if returncode == 0:
        return {
            "status": "usable",
            "blocker": None,
            "qcloud_security_login_seen": qcloud_security_login,
            "permission_denied": False,
        }
    if qcloud_security_login and permission_denied:
        return {
            "status": "blocked",
            "blocker": "qcloud_security_login_and_ssh_key_rejected",
            "qcloud_security_login_seen": True,
            "permission_denied": True,
        }
    if permission_denied:
        return {
            "status": "blocked",
            "blocker": "ssh_key_rejected",
            "qcloud_security_login_seen": qcloud_security_login,
            "permission_denied": True,
        }
    if "Connection timed out" in combined or "Operation timed out" in combined:
        return {
            "status": "blocked",
            "blocker": "ssh_network_timeout",
            "qcloud_security_login_seen": qcloud_security_login,
            "permission_denied": False,
        }
    return {
        "status": "blocked",
        "blocker": "ssh_unknown_failure",
        "qcloud_security_login_seen": qcloud_security_login,
        "permission_denied": permission_denied,
    }


def _tcp_check(*, host: str, port: int, timeout_seconds: int) -> dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return {"open": True, "port": port}
    except OSError as exc:
        return {"open": False, "port": port, "error": str(exc)}


def _ssh_check(
    *,
    host: str,
    port: int,
    user: str,
    ssh_key: Path | None,
    known_hosts: Path | None,
    app_path: str,
    timeout_seconds: int,
    can_attempt: bool,
) -> dict[str, Any]:
    if not ssh_key:
        return {"status": "blocked", "blocker": "missing_ssh_key_path", "attempted": False}
    if not ssh_key.exists():
        return {"status": "blocked", "blocker": "ssh_key_file_missing", "attempted": False}
    if not can_attempt:
        return {"status": "blocked", "blocker": "tcp_22_not_open", "attempted": False}

    known_hosts_args: list[str] = []
    if known_hosts:
        known_hosts.parent.mkdir(parents=True, exist_ok=True)
        known_hosts_args = [
            "-o",
            f"UserKnownHostsFile={known_hosts}",
            "-o",
            "StrictHostKeyChecking=accept-new",
        ]

    command = [
        "ssh",
        "-T",
        "-p",
        str(port),
        "-i",
        str(ssh_key),
        "-o",
        "BatchMode=yes",
        "-o",
        "LogLevel=ERROR",
        *known_hosts_args,
        "-o",
        f"ConnectTimeout={timeout_seconds}",
        *_ssh_stability_option_args(),
        f"{user}@{host}",
        f"cd {app_path} && printf 'remote_app_path=' && pwd && printf '\\ncontainers=' && docker ps --format '{{{{.Names}}}} {{{{.Status}}}}' | head -n 5",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds + 6,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "blocked",
            "blocker": "ssh_command_timeout",
            "attempted": True,
            "qcloud_security_login_seen": False,
            "permission_denied": False,
            "error": str(exc),
        }

    classified = classify_ssh_result(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    classified.update(
        {
            "attempted": True,
            "returncode": completed.returncode,
            "stdout_tail": _tail(completed.stdout),
            "stderr_tail": _tail(completed.stderr),
        }
    )
    return classified


def _public_health(*, public_url: str, timeout_seconds: int) -> dict[str, Any]:
    if not public_url:
        return {"reachable": False, "status": "not_configured"}
    health_url = public_url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(health_url, timeout=timeout_seconds) as response:
            body = response.read(1200).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        curl_result = _public_health_with_curl(health_url=health_url, timeout_seconds=timeout_seconds)
        if curl_result.get("reachable") is True:
            curl_result["urllib_error"] = str(exc)
            return curl_result
        return {"reachable": False, "url": health_url, "error": str(exc), "curl_error": curl_result.get("error"), "secret_exposed": False}
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = {}
    return {
        "reachable": True,
        "url": health_url,
        "http_status": 200,
        "service": parsed.get("service"),
        "production_ready": parsed.get("production_ready"),
        "real_platform_writes_enabled": parsed.get("real_platform_writes_enabled"),
        "secret_exposed": False,
    }


def _public_health_with_curl(*, health_url: str, timeout_seconds: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["curl", "-sS", "--max-time", str(timeout_seconds), health_url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds + 3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"reachable": False, "url": health_url, "error": str(exc), "secret_exposed": False}
    if completed.returncode != 0:
        return {"reachable": False, "url": health_url, "error": _tail(completed.stderr or completed.stdout), "secret_exposed": False}
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError:
        parsed = {}
    return {
        "reachable": True,
        "url": health_url,
        "http_status": 200,
        "service": parsed.get("service"),
        "production_ready": parsed.get("production_ready"),
        "real_platform_writes_enabled": parsed.get("real_platform_writes_enabled"),
        "secret_exposed": False,
        "transport": "curl_fallback",
    }


def _recommended_actions(ssh_check: dict[str, Any]) -> list[str]:
    if ssh_check.get("status") == "usable":
        return [
            "deploy_patch_over_ubuntu_2222_ssh_when_code_changes_are_ready",
            "verify_public_health_after_each_staging_deploy",
        ]
    blocker = ssh_check.get("blocker")
    if blocker == "qcloud_security_login_and_ssh_key_rejected":
        return [
            "reinstall_stable_public_key_through_tencent_orcaterm_or_console",
            "disable_or_bypass_interactive_qcloud_security_login_for_batch_deploy_user",
            "verify_batchmode_ssh_before_next_deploy",
        ]
    if blocker in {"ssh_key_rejected", "ssh_key_file_missing", "missing_ssh_key_path"}:
        return [
            "install_stable_deploy_key_on_server",
            "verify_authorized_keys_contains_matching_public_key",
            "rerun_deploy_channel_doctor",
        ]
    if blocker == "ssh_host_key_changed":
        return [
            "refresh_project_known_hosts_for_this_staging_host",
            "rerun_ubuntu_2222_deploy_channel_doctor",
        ]
    if blocker in {"ssh_network_timeout", "tcp_22_not_open"}:
        return [
            "check_tencent_security_group_allows_ssh_from_current_ip",
            "check_server_firewall_and_public_ip",
            "rerun_deploy_channel_doctor",
        ]
    return ["inspect_unknown_ssh_blocker_then_rerun_deploy_channel_doctor"]


def _ssh_stability_option_args() -> list[str]:
    args: list[str] = []
    for key, value in SSH_STABILITY_OPTIONS:
        args.extend(["-o", f"{key}={value}"])
    return args


def _tail(text: str, limit: int = 1200) -> str:
    if text is None:
        return ""
    sanitized = text.replace("\r", "")
    return sanitized[-limit:]


if __name__ == "__main__":
    raise SystemExit(main())

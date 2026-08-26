#!/usr/bin/env python3
"""Deploy a verified Jiejing release candidate to the production host."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST = "43.129.169.223"
DEFAULT_PORT = 22
DEFAULT_USER = "ubuntu"
DEFAULT_KEY = Path.home() / ".ssh" / "jiejing_production_hk_ed25519"
DEFAULT_KNOWN_HOSTS = Path.home() / ".ssh" / "known_hosts"
EXPECTED_CONFIRM = "deploy app.jiejing.shop production"
ALLOWED_SCOPE = "public_staging_patch_whitelist_v1"
PRODUCTION_REMOTE_APPLY_TIMEOUT_SECONDS = 3600
PHASE3_REQUIRED_BUNDLE_FILES = {
    "deploy/jiejing-production-evidence-auto-refresh.sh",
    "deploy/systemd/jiejing-production-evidence-refresh.service",
    "deploy/systemd/jiejing-production-evidence-refresh.timer",
    "tools/test_jiejing_production_evidence_auto_refresh_guardrails.py",
    "docs/superpowers/specs/2026-08-26-production-evidence-auto-refresh-design.md",
    "docs/superpowers/plans/2026-08-26-production-evidence-auto-refresh-implementation-plan.md",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Confirmation-gated atomic deploy to the Jiejing production host."
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--mode", choices=("dry_run", "apply"), default="dry_run")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--ssh-key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--known-hosts", type=Path, default=DEFAULT_KNOWN_HOSTS)
    parser.add_argument("--timeout", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle = args.bundle.resolve()
    manifest_path = args.manifest.resolve()
    if not bundle.is_file():
        return fail(f"bundle_not_found: {bundle}")
    if not manifest_path.is_file():
        return fail(f"manifest_not_found: {manifest_path}")
    if not args.ssh_key.is_file():
        return fail(f"ssh_key_not_found: {args.ssh_key}")
    if not args.known_hosts.is_file():
        return fail(f"known_hosts_not_found: {args.known_hosts}")
    if args.mode == "apply" and args.confirm != EXPECTED_CONFIRM:
        return fail("production_confirmation_mismatch")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return fail(f"manifest_invalid: {type(exc).__name__}")
    bundle_sha256 = sha256(bundle)
    manifest_sha256 = sha256(manifest_path)
    if str(manifest.get("zip_sha256") or "").lower() != bundle_sha256:
        return fail("bundle_sha256_mismatch")
    if manifest.get("scope") != ALLOWED_SCOPE:
        return fail("manifest_scope_invalid")
    if manifest.get("real_platform_writes_enabled") is not False:
        return fail("manifest_real_write_state_unsafe")
    try:
        validate_zip(bundle)
        validate_bundle_javascript(bundle)
    except ValueError as exc:
        return fail(f"bundle_archive_invalid: {exc}")

    source_sha = git_value("rev-parse", "HEAD")
    dirty = git_value("status", "--porcelain")
    if dirty:
        return fail("deploy_requires_clean_git_worktree")
    if len(source_sha) != 40 or any(ch not in "0123456789abcdef" for ch in source_sha):
        return fail("source_commit_invalid")

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    remote_base = f"/tmp/jiejing-production-{stamp}-{source_sha[:12]}"
    remote_zip = remote_base + ".zip"
    remote_dir = remote_base + ".d"
    upload(args, bundle, remote_zip)

    dry_run = "1" if args.mode == "dry_run" else "0"
    confirm = EXPECTED_CONFIRM if args.mode == "dry_run" else args.confirm
    remote_script = "\n".join(
        [
            "set -euo pipefail",
            f"rm -rf -- {shlex.quote(remote_dir)}",
            f"mkdir -m 0700 -p {shlex.quote(remote_dir)}",
            f"unzip -q {shlex.quote(remote_zip)} -d {shlex.quote(remote_dir)}",
            (
                "sudo -n env "
                f"JIEJING_PRODUCTION_DEPLOY_CONFIRM={shlex.quote(confirm)} "
                f"JIEJING_PRODUCTION_DEPLOY_DRY_RUN={dry_run} "
                f"bash {shlex.quote(remote_dir + '/deploy/jiejing-production-release-apply.sh')} "
                f"{shlex.quote(remote_dir)} {shlex.quote(bundle_sha256)} "
                f"{shlex.quote(manifest_sha256)} {shlex.quote(source_sha)}"
            ),
            f"rm -f -- {shlex.quote(remote_zip)}",
            f"rm -rf -- {shlex.quote(remote_dir)}",
        ]
    )
    remote_timeout = (
        PRODUCTION_REMOTE_APPLY_TIMEOUT_SECONDS
        if args.mode == "apply"
        else max(args.timeout * 20, 1200)
    )
    completed = run(
        ssh_base(args) + [f"bash -lc {shlex.quote(remote_script)}"],
        timeout=remote_timeout,
    )
    print(
        json.dumps(
            {
                "status": "dry_run_passed" if args.mode == "dry_run" else "deployed",
                "mode": args.mode,
                "host": DEFAULT_HOST,
                "source_sha": source_sha,
                "bundle_sha256": bundle_sha256,
                "manifest_sha256": manifest_sha256,
                "stdout_tail": completed.stdout[-5000:],
                "stderr_tail": completed.stderr[-2000:],
                "secret_exposed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def validate_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        if not names:
            raise ValueError("empty")
        required = {
            "app.js",
            "Dockerfile.saas",
            "deploy/docker-compose.production-pilot.yml",
            "deploy/jiejing-production-release-apply.sh",
            "jiejing_saas/migrations/002_media_credit_buckets_postgres.sql",
            "jiejing_saas/migrations/003_runtime_schema_reconciliation_postgres.sql",
            "tools/jiejing_secret_scan.py",
        } | PHASE3_REQUIRED_BUNDLE_FILES
        missing = sorted(required.difference(names))
        if missing:
            raise ValueError("missing_required:" + ",".join(missing))
        for info in archive.infolist():
            posix = PurePosixPath(info.filename)
            if posix.is_absolute() or ".." in posix.parts or not posix.parts:
                raise ValueError(f"unsafe_path:{info.filename}")
            name = posix.name.lower()
            if name == ".env" or (name.endswith(".env") and not name.endswith(".env.example")):
                raise ValueError(f"secret_file:{info.filename}")
            if name.endswith((".pem", ".key")) or name.startswith("id_"):
                raise ValueError(f"key_file:{info.filename}")
            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise ValueError(f"symlink:{info.filename}")


def validate_bundle_javascript(path: Path) -> None:
    """Syntax-check the exact bundled frontend before any production upload."""
    node = shutil.which("node")
    if not node:
        raise ValueError("local_node_unavailable")
    with tempfile.TemporaryDirectory(prefix="jiejing-production-js-") as temp_dir:
        app_js = Path(temp_dir) / "app.js"
        with zipfile.ZipFile(path, "r") as archive:
            app_js.write_bytes(archive.read("app.js"))
        completed = subprocess.run(
            [node, "--check", str(app_js)],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=60,
        )
        if completed.returncode != 0:
            raise ValueError("bundle_javascript_invalid")


def upload(args: argparse.Namespace, source: Path, remote_path: str) -> None:
    target = f"{DEFAULT_USER}@{DEFAULT_HOST}:{remote_path}"
    command = [
        "scp",
        "-O",
        "-P",
        str(DEFAULT_PORT),
        "-i",
        str(args.ssh_key),
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={args.known_hosts}",
        "-o",
        f"ConnectTimeout={args.timeout}",
        str(source),
        target,
    ]
    run(command, timeout=max(args.timeout * 8, 240))


def ssh_base(args: argparse.Namespace) -> list[str]:
    return [
        "ssh",
        "-T",
        "-p",
        str(DEFAULT_PORT),
        "-i",
        str(args.ssh_key),
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={args.known_hosts}",
        "-o",
        f"ConnectTimeout={args.timeout}",
        f"{DEFAULT_USER}@{DEFAULT_HOST}",
    ]


def run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
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
                    "reason": "command_timeout",
                    "stdout_tail": text_tail(exc.stdout, 1500),
                    "stderr_tail": text_tail(exc.stderr, 1500),
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
                    "reason": "remote_command_failed",
                    "returncode": completed.returncode,
                    "stdout_tail": completed.stdout[-3000:],
                    "stderr_tail": completed.stderr[-3000:],
                    "secret_exposed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return completed


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"git_command_failed:{' '.join(args)}")
    return completed.stdout.strip()


def text_tail(value: str | bytes | None, length: int) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[-length:]
    return value[-length:]


def fail(message: str) -> int:
    print(
        json.dumps(
            {"status": "failed", "reason": message, "secret_exposed": False},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

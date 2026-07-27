#!/usr/bin/env python3
"""Regression checks for the staging deploy disk-capacity guard."""

from __future__ import annotations

import importlib.util
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "jiejing_staging_deploy.py"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    spec = importlib.util.spec_from_file_location("jiejing_staging_deploy", TOOL)
    if spec is None or spec.loader is None:
        return fail("could not import the staging deploy tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    warning = module.classify_remote_disk_report(
        module.parse_remote_disk_report(
            "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/vda1 41943040 35232153 6710887 84% /\n"
        ),
        warning_percent=80,
        block_percent=92,
        min_free_bytes=2 * 1024**3,
    )
    if warning.get("status") != "warning" or warning.get("deploy_allowed") is not True:
        return fail(f"84 percent with 6.4 GiB free should warn but deploy: {warning}")

    full = module.classify_remote_disk_report(
        module.parse_remote_disk_report(
            "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/vda1 41943040 39426458 2516582 94% /\n"
        ),
        warning_percent=80,
        block_percent=92,
        min_free_bytes=2 * 1024**3,
    )
    if full.get("status") != "blocked" or full.get("deploy_allowed") is not False:
        return fail(f"92 percent threshold must block deployment: {full}")

    low_free = module.classify_remote_disk_report(
        module.parse_remote_disk_report(
            "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/vda1 104857600 94371840 1048576 90% /\n"
        ),
        warning_percent=80,
        block_percent=92,
        min_free_bytes=2 * 1024**3,
    )
    if low_free.get("reason") != "remote_disk_free_space_below_minimum":
        return fail(f"low free space must block even below the percent threshold: {low_free}")

    malformed = module.classify_remote_disk_report(
        module.parse_remote_disk_report("unexpected output"),
        warning_percent=80,
        block_percent=92,
        min_free_bytes=2 * 1024**3,
    )
    if malformed.get("reason") != "remote_disk_report_unavailable":
        return fail(f"malformed remote disk output must fail closed: {malformed}")

    source = TOOL.read_text(encoding="utf-8")
    preflight_index = source.find("disk_preflight = _remote_disk_preflight(args)")
    upload_index = source.find("upload_result = _upload_patch(args, patch, remote_zip)")
    if preflight_index < 0 or upload_index < 0 or preflight_index > upload_index:
        return fail("disk preflight must run before any patch upload")
    if '"disk_preflight": disk_preflight' not in source:
        return fail("successful deploy output must preserve the disk preflight evidence")
    if '"--remote-build-cache-until-hours", type=int, default=1' not in source:
        return fail("staging deploy must prune unused build cache older than one hour by default")
    if module._operation_timeout_seconds(Namespace(timeout=30)) < 600:
        return fail("remote no-cache image builds must have at least ten minutes without weakening the SSH connect timeout")

    cleanup_script = module.build_remote_deploy_artifact_cleanup_script(
        Namespace(
            app_path="/opt/jiejing-staging/app",
            remote_patch_backup_keep=8,
            remote_runner_backup_keep=5,
            remote_runner_release_keep=5,
            remote_build_cache_until_hours=1,
        )
    )
    required_cleanup_markers = [
        "/opt/jiejing-staging/app/output/staging-patch-backups",
        "/opt/jiejing-staging/github-action-backups",
        "/opt/jiejing-staging/github-action-releases",
        'retain_newest "patch_backups"',
        'retain_newest "runner_backups"',
        'retain_newest "runner_releases"',
        "docker builder prune --all --force --filter 'until=1h'",
        "REMOTE_DEPLOY_CLEANUP_STATUS=completed",
        "REMOTE_DEPLOY_CLEANUP_DISK_AFTER",
    ]
    missing_cleanup_markers = [marker for marker in required_cleanup_markers if marker not in cleanup_script]
    if missing_cleanup_markers:
        return fail("deploy artifact cleanup is incomplete: " + ",".join(missing_cleanup_markers))
    forbidden_cleanup_markers = [
        "docker system prune",
        "docker volume prune",
        "docker image prune -a",
        "/opt/jiejing-staging/backups",
        "/var/lib/docker/volumes",
    ]
    present_cleanup_markers = [marker for marker in forbidden_cleanup_markers if marker in cleanup_script]
    if present_cleanup_markers:
        return fail("deploy artifact cleanup crosses the safe boundary: " + ",".join(present_cleanup_markers))
    try:
        module.build_remote_deploy_artifact_cleanup_script(
            Namespace(
                app_path="/",
                remote_patch_backup_keep=8,
                remote_runner_backup_keep=5,
                remote_runner_release_keep=5,
                remote_build_cache_until_hours=1,
            )
        )
    except ValueError:
        pass
    else:
        return fail("deploy artifact cleanup must refuse a non-canonical app root")
    apply_index = source.find('result = _run(ssh_cmd, label="apply_patch"')
    cleanup_index = source.find("artifact_cleanup_result = _cleanup_remote_deploy_artifacts(args)")
    if apply_index < 0 or cleanup_index < 0 or apply_index > cleanup_index:
        return fail("deploy artifact cleanup must run only after the patch and health check succeed")
    if '"remote_deploy_artifact_cleanup": artifact_cleanup_result' not in source:
        return fail("successful deploy output must expose bounded artifact cleanup evidence")
    print("PASS jiejing_staging_deploy_disk_guard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

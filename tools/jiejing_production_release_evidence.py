"""Deployment-owned safe receipts and a no-network backup cold-start preflight.

An applied receipt is written ONLY by the release script after its actual
postflight succeeds. It is not backup evidence and does not refresh any probe.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def trusted_owner(metadata) -> bool:
    return os.name == "nt" or (metadata.st_uid == 0 and not metadata.st_mode & 0o022)


def write_receipt(target: Path, source_sha: str, *, applied: bool) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("source_identity_invalid")
    expected_name = "deployment.safe.json" if applied else "JIEJING_RUNTIME_BUILD.safe.json"
    if not target.is_absolute() or target.name != expected_name or target.parent.resolve() != target.parent:
        raise ValueError("receipt_path_invalid")
    parent = target.parent.stat()
    if not stat.S_ISDIR(parent.st_mode) or not trusted_owner(parent):
        raise ValueError("receipt_directory_not_trusted")
    previous = None
    if target.exists() or target.is_symlink():
        previous = target.lstat()
        if not stat.S_ISREG(previous.st_mode) or previous.st_size > 4096 or not trusted_owner(previous):
            raise ValueError("existing_receipt_not_trusted")
        if not applied:
            raise ValueError("build_identity_already_exists")
    receipt = {"contract_version": "jiejing_applied_release_v1" if applied else "jiejing_runtime_build_v1", "source_commit": source_sha}
    if applied:
        receipt.update(verified_at=datetime.now(timezone.utc).isoformat(), applied=True,
                       public_health_verified=True, secret_exposed=False)
    payload = (json.dumps(receipt, sort_keys=True) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=".release-receipt-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        if previous is not None:
            current = target.lstat()
            if (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size) != (previous.st_dev, previous.st_ino, previous.st_mtime_ns, previous.st_size):
                raise ValueError("receipt_changed_concurrently")
            # Preserve the prior tiny safe receipt. Never overwrite the backup.
            backup = target.with_name("deployment.previous-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".safe.json")
            with backup.open("xb") as stream:
                stream.write(target.read_bytes())
            os.chmod(backup, 0o644)
        elif target.exists() or target.is_symlink():
            raise ValueError("receipt_created_concurrently")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)  # Only the exact temporary file created above.


def backup_cold_start_preflight() -> dict:
    from jiejing_saas.backup_plan import build_backup_plan
    from jiejing_saas.config import SaaSSettings
    class NoBusinessInventory:
        def system_counts(self):
            return {}  # Inventory is not part of this evidence-only check.
    settings = SaaSSettings.from_env(db_path=Path('/nonexistent/preflight.sqlite'),
        runtime_db_path=Path('/nonexistent/preflight-runtime.sqlite'),
        output_root=Path('/nonexistent/preflight-output'), host='127.0.0.1', port=8788)
    plan = build_backup_plan(settings, NoBusinessInventory())
    money_enabled = any(os.environ.get(key, "").strip().lower() in {"true", "1", "yes", "on"} for key in (
        "JIEJING_WECHAT_PAY_CHARGE_ALLOWED", "JIEJING_WECHAT_PAY_REFUND_ALLOWED"))
    passed = settings.is_production_like and (not money_enabled or plan.get("backup_ready_for_paid_launch") is True)
    return {"contract_version": "jiejing_backup_cold_start_preflight_v1", "passed": passed,
            "money_enabled": money_enabled, "backup_ready": plan.get("backup_ready_for_paid_launch") is True,
            "blockers": [item for item in plan.get("blockers", []) if isinstance(item, str) and re.fullmatch(r"[a-z0-9_]+", item)],
            "business_database_accessed": False, "evidence_refreshed": False, "secret_exposed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["build", "applied", "preflight"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-sha")
    args = parser.parse_args()
    if args.mode == "preflight":
        if args.output or args.source_sha:
            raise ValueError("unexpected_arguments")
        result = backup_cold_start_preflight()
        print(json.dumps(result))
        return 0 if result["passed"] else 2
    if not args.output or not args.source_sha:
        raise ValueError("missing_arguments")
    write_receipt(args.output, args.source_sha, applied=args.mode == "applied")
    print(json.dumps({"status": "written", "kind": args.mode, "source_commit": args.source_sha, "secret_exposed": False}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print(json.dumps({"status": "blocked", "reason": "release_evidence_operation_failed", "secret_exposed": False}))
        raise SystemExit(2)

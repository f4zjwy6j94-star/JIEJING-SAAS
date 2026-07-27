#!/usr/bin/env python3
"""Read-only current-state guard for Jiejing SaaS.

This tool never opens eBay OAuth, never runs a sync, never deploys, and never
touches cloud resources. It reads local status artifacts and returns the next
safe action so resumed work does not repeat completed operator steps.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.json_safe import json_default  # noqa: E402


DEFAULT_ARTIFACTS = {
    "staging_oauth": Path("output/jiejing-saas-backend/staging-ebay-oauth-readonly/staging_oauth_status_latest.json"),
    "staging_sync": Path("output/jiejing-saas-backend/staging-ebay-oauth-readonly/staging_readonly_sync_latest.json"),
    "deploy_doctor": Path("output/jiejing-deploy-channel-doctor/latest.json"),
    "precloud_gate": Path("output/jiejing-precloud-deployment-gate/latest.json"),
    "infra_gate": Path("output/jiejing-infrastructure-stage-gate/latest.json"),
    "runtime_self_check": Path("output/jiejing-agent-runtime-samples/self-check/jiejing_runtime_self_check_latest.json"),
}

CORE_EBAY_RESOURCES = [
    "store_profile",
    "account_business_policies",
    "inventory_and_offers",
    "orders_and_fulfillment",
    "finances",
    "taxonomy_listing_metadata",
]

ACCOUNT_EVIDENCE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect the current Jiejing SaaS state without side effects.")
    parser.add_argument("--workspace", default=str(ROOT), help="Jiejing software-demo workspace root.")
    parser.add_argument(
        "--output-root",
        default="",
        help="Runtime output root. Use this on staging when artifacts live outside the source tree, for example /data/output.",
    )
    parser.add_argument("--db", default="", help="Optional SaaS database path for DB-backed current-state fallback.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    output_root = Path(args.output_root).resolve() if args.output_root else None
    db_path = Path(args.db).resolve() if args.db else None
    result = build_state(workspace, output_root=output_root, db_path=db_path)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=json_default))
    else:
        _print_human(result)
    return 0 if result["status"] in {"ready_to_continue", "partial_evidence"} else 2


def build_state(workspace: Path, *, output_root: Path | None = None, db_path: Path | None = None) -> dict[str, Any]:
    artifacts = {name: _read_json(_artifact_path(workspace, rel_path, output_root)) for name, rel_path in DEFAULT_ARTIFACTS.items()}
    db_evidence = _read_db_evidence(db_path)
    oauth_artifact = artifacts["staging_oauth"]
    sync_artifact = artifacts["staging_sync"]
    oauth = oauth_artifact.get("data") or {}
    sync = sync_artifact.get("data") or {}
    deploy = artifacts["deploy_doctor"].get("data") or {}
    infra = artifacts["infra_gate"].get("data") or {}

    db_authorized = int(db_evidence.get("read_only_authorized_connections") or 0) > 0
    db_packet_id = str(db_evidence.get("latest_ebay_packet_id") or "")
    db_packet_source_mode = str(db_evidence.get("latest_ebay_packet_source_mode") or "")
    db_present_resources = db_evidence.get("latest_ebay_packet_present_resource_keys") or []
    db_missing_resources = db_evidence.get("latest_ebay_packet_missing_resource_keys") or []

    historical_callback_completed = bool(oauth.get("callback_completed")) or oauth.get("oauth_latest_status") == "callback_exchange_completed"
    oauth_artifact_fresh = _artifact_is_fresh(oauth_artifact)
    sync_artifact_fresh = _artifact_is_fresh(sync_artifact)
    callback_completed = bool(historical_callback_completed and oauth_artifact_fresh) or db_authorized
    can_queue_sync = bool((oauth.get("preflight") or {}).get("can_queue_sync")) or db_authorized
    if not callback_completed:
        can_queue_sync = False
    historical_sync_completed = sync.get("status") == "completed" or sync.get("sync_status") == "completed"
    historical_live_read_completed = sync.get("live_read_status") == "completed_live_read"
    historical_official_packet = sync.get("source_mode") == "official_api" or bool(sync.get("live_request_performed"))
    artifact_sync_completed = bool(historical_sync_completed and sync_artifact_fresh)
    artifact_live_read_completed = bool(historical_live_read_completed and sync_artifact_fresh)
    present_resources = (
        (sync.get("present_resource_keys") or _present_resources_from_routes(sync))
        if sync_artifact_fresh
        else []
    ) or db_present_resources
    missing_resources = [key for key in CORE_EBAY_RESOURCES if key not in set(present_resources)]
    if db_packet_id and isinstance(db_missing_resources, list) and not db_missing_resources and not missing_resources:
        missing_resources = []
    official_packet = bool(historical_official_packet and sync_artifact_fresh) or db_packet_source_mode == "official_api"
    sync_completed = artifact_sync_completed or bool(db_packet_id and official_packet)
    live_read_completed = artifact_live_read_completed or bool(db_packet_id and official_packet)
    historical_account_evidence_stale = bool(
        (historical_callback_completed and not oauth_artifact_fresh)
        or ((historical_sync_completed or historical_official_packet) and not sync_artifact_fresh)
    )
    active_data_packet_id = (sync.get("data_packet_id") if sync_artifact_fresh else "") or db_packet_id
    historical_data_packet_id = sync.get("data_packet_id") if historical_account_evidence_stale else ""
    deploy_channel_ready = bool(deploy.get("deploy_channel_ready") and deploy.get("ssh", {}).get("status") == "usable") or _env_flag(
        "JIEJING_DEPLOY_CHANNEL_READY"
    )

    no_repeat = []
    safe_next = []
    blockers = []

    if historical_account_evidence_stale and not callback_completed:
      no_repeat.append(
          "Do not start OAuth from historical local artifacts alone; verify active staging readiness and wait for explicit operator confirmation."
      )
      safe_next.append("Compare active public readiness with the intended clean seller account before any authorization action.")
      blockers.append("Historical eBay account evidence is stale and cannot prove the current active seller connection.")
    elif callback_completed and can_queue_sync:
      no_repeat.append("Do not run OAuth prepare or open a new eBay authorization URL; callback exchange is already complete.")
      safe_next.append("Read status artifacts or run frontend/backend work that consumes the existing secret_ref connection.")
    else:
      blockers.append("OAuth callback is not proven complete in local artifacts; only then should a new seller authorization be considered.")

    if sync_completed and live_read_completed and official_packet and not missing_resources:
      no_repeat.append("Do not run a fresh eBay read-only sync just to check progress; read data packets and sync status first.")
      safe_next.append("Use the existing official API data packet for AI CEO reports, confirmation center, and frontend workbench.")
    elif callback_completed and can_queue_sync:
      safe_next.append("Run one explicit eBay read-only sync only if no completed official packet exists or the operator asks for a refresh.")
    else:
      blockers.append("Official read-only data packet is not proven complete.")

    if deploy_channel_ready:
      no_repeat.append("Do not start with Tencent browser QR login; use agentuser SSH deploy channel first if deployment is needed.")
    else:
      blockers.append("Stable SSH deploy channel is not proven usable by latest deploy doctor artifact.")

    if not _infra_paid_ready(infra):
      safe_next.append("Keep Postgres/Redis/Vault/KMS work in rehearsal/contract mode until managed resources are provisioned.")

    progress = {
      "frontend_productization": "continue",
      "ebay_oauth": "completed" if callback_completed else "blocked",
      "ebay_official_sync": "completed" if sync_completed and official_packet else "blocked_or_stale",
      "standard_data_packet": "completed" if not missing_resources and official_packet else "partial",
      "deploy_channel": "usable" if deploy_channel_ready else "blocked",
      "production_infrastructure": "rehearsal_only" if not _infra_paid_ready(infra) else "ready_for_cutover",
    }

    status = "partial_evidence" if blockers else "ready_to_continue"
    return {
      "product": "Jiejing SaaS",
      "status": status,
      "checked_at": datetime.now(timezone.utc).isoformat(),
      "workspace": str(workspace),
      "output_root": str(output_root) if output_root else str(workspace / "output"),
      "callback_completed": callback_completed,
      "historical_callback_completed": historical_callback_completed,
      "can_queue_sync": can_queue_sync,
      "sync_completed": sync_completed,
      "historical_sync_completed": historical_sync_completed,
      "live_read_completed": live_read_completed,
      "official_packet": official_packet,
      "historical_official_packet": historical_official_packet,
      "historical_account_evidence_stale": historical_account_evidence_stale,
      "account_evidence_max_age_seconds": ACCOUNT_EVIDENCE_MAX_AGE_SECONDS,
      "data_packet_id": active_data_packet_id,
      "historical_data_packet_id": historical_data_packet_id,
      "present_resource_keys": present_resources,
      "missing_resource_keys": missing_resources,
      "deploy_channel_ready": deploy_channel_ready,
      "progress": progress,
      "no_repeat_actions": no_repeat,
      "safe_next_actions": safe_next,
      "blockers": blockers,
      "artifacts": {
          name: {
              "path": item["path"],
              "exists": item["exists"],
              "age_seconds": item.get("age_seconds"),
              "fresh": _artifact_is_fresh(item),
          }
          for name, item in artifacts.items()
      },
      "db_evidence": db_evidence,
      "real_platform_writes_enabled": False,
      "secret_exposed": False,
    }


def _artifact_path(workspace: Path, rel_path: Path, output_root: Path | None) -> Path:
    if output_root and rel_path.parts and rel_path.parts[0] == "output":
        return output_root.joinpath(*rel_path.parts[1:])
    return workspace / rel_path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "data": None}
    try:
        modified_at = path.stat().st_mtime
        return {
            "path": str(path),
            "exists": True,
            "modified_at": datetime.fromtimestamp(modified_at, timezone.utc).isoformat(),
            "age_seconds": max(0, int(time.time() - modified_at)),
            "data": json.loads(path.read_text(encoding="utf-8")),
        }
    except Exception as exc:
        return {"path": str(path), "exists": True, "error": str(exc), "data": None}


def _artifact_is_fresh(item: dict[str, Any]) -> bool:
    return bool(
        item.get("exists")
        and item.get("data") is not None
        and int(item.get("age_seconds") or 0) <= ACCOUNT_EVIDENCE_MAX_AGE_SECONDS
    )


def _read_db_evidence(db_path: Path | None) -> dict[str, Any]:
    selected_db = db_path or Path(os.environ.get("JIEJING_SAAS_DB_PATH") or "/data/saas.sqlite")
    if not selected_db.exists() and not os.environ.get("JIEJING_DATABASE_URL"):
        return {"status": "not_configured", "secret_exposed": False}
    try:
        from jiejing_saas.repository import SaaSRepository

        repo = SaaSRepository(
            selected_db,
            database_engine=os.environ.get("JIEJING_DATABASE_ENGINE"),
            database_url=os.environ.get("JIEJING_DATABASE_URL", ""),
        )
        evidence = repo.product_readiness_evidence()
        evidence["status"] = "ready"
        evidence["secret_exposed"] = False
        return evidence
    except Exception as exc:
        return {"status": "failed", "error_type": exc.__class__.__name__, "error": str(exc)[:240], "secret_exposed": False}


def _present_resources_from_routes(sync: dict[str, Any]) -> list[str]:
    rows = []
    for route in sync.get("route_results") or []:
        if route.get("data_present") and route.get("resource_key"):
            rows.append(route["resource_key"])
    return rows


def _infra_paid_ready(infra: dict[str, Any]) -> bool:
    if not infra:
        return False
    return bool(infra.get("ready_for_paid_commercial_launch") or infra.get("paid_commercial_ready"))


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _print_human(result: dict[str, Any]) -> None:
    print(f"STATUS={result['status']}")
    print(f"CALLBACK_COMPLETED={result['callback_completed']}")
    print(f"SYNC_COMPLETED={result['sync_completed']}")
    print(f"OFFICIAL_PACKET={result['official_packet']}")
    print(f"HISTORICAL_ACCOUNT_EVIDENCE_STALE={result.get('historical_account_evidence_stale', False)}")
    print(f"DATA_PACKET_ID={result.get('data_packet_id') or '-'}")
    print(f"PRESENT_RESOURCES={','.join(result.get('present_resource_keys') or []) or '-'}")
    print(f"MISSING_RESOURCES={','.join(result.get('missing_resource_keys') or []) or '-'}")
    print(f"DEPLOY_CHANNEL_READY={result['deploy_channel_ready']}")
    print("NO_REPEAT_ACTIONS=" + " | ".join(result.get("no_repeat_actions") or ["-"]))
    print("SAFE_NEXT_ACTIONS=" + " | ".join(result.get("safe_next_actions") or ["-"]))
    print("BLOCKERS=" + " | ".join(result.get("blockers") or ["-"]))


if __name__ == "__main__":
    raise SystemExit(main())

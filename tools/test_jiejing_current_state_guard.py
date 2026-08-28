#!/usr/bin/env python3
"""Regression for the read-only Jiejing current-state guard."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.jiejing_current_state_guard import build_state  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_current_state_guard.py"),
            "--offline",
            "--json",
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return fail(f"guard should be readable without side effects: {result.stderr[:500]}")
    payload = json.loads(result.stdout)
    if payload.get("real_platform_writes_enabled") is not False:
        return fail("guard must keep real platform writes disabled")
    text = json.dumps(payload, ensure_ascii=False)
    for forbidden in ["AUTHORIZATION_URL=", "access_token", "refresh_token", "client_secret"]:
        if forbidden in text:
            return fail(f"guard leaked or produced a forbidden operator value: {forbidden}")
    if payload.get("callback_completed") and not any("Do not run OAuth prepare" in item for item in payload.get("no_repeat_actions", [])):
        return fail("completed OAuth state must block repeated prepare/open authorization actions")
    if payload.get("sync_completed") and not any("Do not run a fresh eBay read-only sync" in item for item in payload.get("no_repeat_actions", [])):
        return fail("completed sync state must block repeated progress-check syncs")
    safe_next_actions = payload.get("safe_next_actions", [])
    if any("Redis" in item for item in safe_next_actions):
        return fail("current-state guidance must not recommend paid Redis after the production queue moved to Postgres durable")
    if not any("Postgres durable" in item for item in safe_next_actions):
        return fail("current-state guidance must name the selected Postgres durable production queue")
    with tempfile.TemporaryDirectory(prefix="jiejing-current-state-stale-") as tmp:
        workspace = Path(tmp)
        artifact_root = workspace / "output" / "jiejing-saas-backend" / "staging-ebay-oauth-readonly"
        artifact_root.mkdir(parents=True)
        oauth_path = artifact_root / "staging_oauth_status_latest.json"
        sync_path = artifact_root / "staging_readonly_sync_latest.json"
        deploy_path = workspace / "output" / "jiejing-deploy-channel-doctor" / "latest.json"
        deploy_path.parent.mkdir(parents=True)
        deploy_path.write_text(
            json.dumps({"deploy_channel_ready": True, "ssh": {"status": "usable"}}),
            encoding="utf-8",
        )
        oauth_path.write_text(
            json.dumps(
                {
                    "callback_completed": True,
                    "oauth_latest_status": "callback_exchange_completed",
                    "preflight": {"can_queue_sync": True},
                }
            ),
            encoding="utf-8",
        )
        sync_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "sync_status": "completed",
                    "live_read_status": "completed_live_read",
                    "live_request_performed": True,
                    "source_mode": "official_api",
                    "data_packet_id": "packet_historical_frozen_account",
                    "present_resource_keys": [
                        "store_profile",
                        "account_business_policies",
                        "inventory_and_offers",
                        "orders_and_fulfillment",
                        "finances",
                        "taxonomy_listing_metadata",
                    ],
                }
            ),
            encoding="utf-8",
        )
        old_timestamp = time.time() - (45 * 24 * 60 * 60)
        os.utime(oauth_path, (old_timestamp, old_timestamp))
        os.utime(sync_path, (old_timestamp, old_timestamp))
        stale = build_state(workspace)
        if stale.get("historical_account_evidence_stale") is not True:
            return fail("45-day-old account artifacts must be identified as stale historical evidence")
        if stale.get("callback_completed") is not False or stale.get("sync_completed") is not False:
            return fail("stale historical account artifacts must not be treated as an active current connection")
        if stale.get("data_packet_id"):
            return fail("stale account packet id must not be exposed as the active data packet")
        if stale.get("historical_data_packet_id") != "packet_historical_frozen_account":
            return fail("stale packet id should remain available only as labeled historical audit evidence")
        if not any("historical" in item.lower() for item in stale.get("blockers", [])):
            return fail("stale account evidence must produce an explicit historical-evidence blocker")
        if any("consumes the existing secret_ref" in item for item in stale.get("safe_next_actions", [])):
            return fail("stale account evidence must never recommend consuming an old secret reference")
        if not any("Do not start OAuth" in item for item in stale.get("no_repeat_actions", [])):
            return fail("stale evidence must still prevent automatic repeat OAuth before active-state verification")

        current_public_readiness = {
            "status": "ready",
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
            "ebay_token_refresh_success_count": 3,
            "secret_exposed": False,
        }
        current = build_state(workspace, public_readiness=current_public_readiness)
        if current.get("status") != "ready_to_continue":
            return fail("current public readiness must supersede stale local account evidence")
        if current.get("evidence_source") != "public_readiness":
            return fail("guard must identify public readiness as the current account evidence source")
        if not all(
            current.get(key) is True
            for key in ("callback_completed", "can_queue_sync", "sync_completed", "live_read_completed", "official_packet")
        ):
            return fail("current official 6/6 public readiness must prove the existing eBay connection and packet")
        if current.get("missing_resource_keys"):
            return fail("current official 6/6 public readiness must not report missing resources")
        if any("Historical eBay account evidence" in item for item in current.get("blockers", [])):
            return fail("stale local evidence must not block a verified current public connection")
        if not any("Do not run OAuth prepare" in item for item in current.get("no_repeat_actions", [])):
            return fail("current public readiness must prevent repeated OAuth")
        if not any("Do not run a fresh eBay read-only sync" in item for item in current.get("no_repeat_actions", [])):
            return fail("current public readiness must prevent a progress-check sync")

        unsafe_public_readiness = dict(current_public_readiness, secret_exposed=True)
        unsafe = build_state(workspace, public_readiness=unsafe_public_readiness)
        if unsafe.get("callback_completed") is not False or unsafe.get("status") != "partial_evidence":
            return fail("unsafe public readiness input must never override stale local evidence")

        unproven_public_connection = dict(
            current_public_readiness,
            ebay_token_refresh_success_count=0,
        )
        unproven = build_state(workspace, public_readiness=unproven_public_connection)
        if unproven.get("callback_completed") is not False or unproven.get("status") != "partial_evidence":
            return fail("a public current-connection marker without refresh proof must fail closed")
    print("PASS jiejing_current_state_guard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

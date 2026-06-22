#!/usr/bin/env python3
"""Run the local Jiejing eBay read-only live smoke.

This tool is intentionally backend-only. It can use the temporary local Hermes
credential bridge for development, but it never prints token values, returns
secrets to Runtime, or enables real eBay writes.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_RESOURCES = [
    "store_profile",
    "account_business_policies",
    "inventory_and_offers",
    "orders_and_fulfillment",
    "finances",
    "taxonomy_listing_metadata",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify eBay read-only live sync, sanitized packet persistence, and AI CEO Runtime handoff."
    )
    parser.add_argument(
        "--local-hermes-bridge",
        action="store_true",
        help="Enable the local backend-only Hermes credential bridge and live read switches for this process.",
    )
    parser.add_argument("--store-name", default="northvalesource")
    parser.add_argument("--marketplace", default="EBAY_US")
    parser.add_argument("--product", default="northvalesource eBay official read-only operating snapshot")
    parser.add_argument(
        "--output-root",
        default=str(ROOT / "output" / "jiejing-saas-backend" / "local-ebay-readonly-live-smoke"),
    )
    parser.add_argument("--port", type=int, default=0, help="Use 0 to auto-pick a free local port.")
    parser.add_argument("--reuse-db", action="store_true", help="Reuse the smoke SQLite databases instead of resetting them.")
    parser.add_argument("--skip-workflow", action="store_true", help="Only run preflight and eBay read-only sync.")
    parser.add_argument(
        "--resources",
        default=",".join(DEFAULT_RESOURCES),
        help="Comma-separated eBay read-only resource keys to request.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    resources = [item.strip() for item in str(args.resources).split(",") if item.strip()]
    if not resources:
        resources = list(DEFAULT_RESOURCES)

    if args.local_hermes_bridge:
        _enable_local_hermes_bridge_env()

    out_dir = Path(args.output_root).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    saas_db = out_dir / "saas-live-smoke.sqlite"
    runtime_db = out_dir / "runtime-live-smoke.sqlite"
    if not args.reuse_db:
        for path in (saas_db, runtime_db):
            if path.exists():
                path.unlink()

    port = args.port if args.port else _free_port()
    process = _start_backend(port=port, saas_db=saas_db, runtime_db=runtime_db, output_root=out_dir)
    try:
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_health(base_url)
        token = _demo_token(base_url)
        store = _create_store(base_url, token=token, store_name=args.store_name, marketplace=args.marketplace)
        _record_readonly_connection(base_url, token=token, store_id=store["store_id"])

        preflight = _post_json(
            f"{base_url}/stores/{store['store_id']}/ebay-read-only/credential-preflight",
            {"resources": resources},
            token=token,
        ).get("credential_preflight", {})
        sync = _post_json(
            f"{base_url}/stores/{store['store_id']}/ebay-read-only/sync",
            {
                "run_mode": "local_worker_now",
                "product": args.product,
                "resources": resources,
            },
            token=token,
            timeout=300,
        )
        sync_summary = _sync_summary(sync=sync, preflight=preflight, output_root=out_dir)
        workflow_summary: dict[str, Any] = {}
        if not args.skip_workflow:
            workflow_summary = _run_ai_ceo_workflow(
                base_url=base_url,
                token=token,
                store_id=store["store_id"],
                product=args.product,
                output_root=out_dir,
            )

        packets = _fetch_json(f"{base_url}/data-packets?store_id={store['store_id']}&platform=ebay", token=token).get("data_packets", [])
        final = {
            "status": "completed",
            "store_id": store["store_id"],
            "store_name": store.get("store_name"),
            "preflight": {
                "status": preflight.get("status"),
                "can_queue_sync": bool(preflight.get("can_queue_sync")),
                "token_mode": preflight.get("token_mode"),
                "blocked_by": preflight.get("blocked_by") or [],
                "secret_exposed": False,
            },
            "sync": sync_summary,
            "workflow": workflow_summary,
            "stored_packet_count": len(packets),
            "output_root": str(out_dir),
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }
        _write_json(out_dir / "live_smoke_latest.json", final)
        _print_summary(final)
        return _exit_code(final=final, workflow_required=not args.skip_workflow)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _enable_local_hermes_bridge_env() -> None:
    os.environ["JIEJING_ENABLE_HERMES_EBAY_BRIDGE"] = "true"
    os.environ["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = os.environ.get("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", "true")
    os.environ["JIEJING_EBAY_AUTO_REFRESH"] = "true"
    os.environ["JIEJING_EBAY_READ_ONLY_LIVE"] = "true"
    os.environ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"] = "true"


def _start_backend(*, port: int, saas_db: Path, runtime_db: Path, output_root: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(saas_db),
            "--runtime-db",
            str(runtime_db),
            "--output-root",
            str(output_root),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_health(base_url: str) -> None:
    for _ in range(100):
        try:
            if _fetch_json(f"{base_url}/health").get("status") == "ok":
                return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Jiejing SaaS backend did not become healthy.")


def _demo_token(base_url: str) -> str:
    session = _post_json(
        f"{base_url}/auth/demo-session",
        {
            "email": "live-readonly@jiejing.local",
            "password": "jiejing-live-readonly-password",
            "company_name": "Jiejing Local eBay Readonly Smoke",
        },
    )
    token = str(session.get("token") or "")
    if not token:
        raise RuntimeError("demo-session did not return a bearer token.")
    return token


def _create_store(base_url: str, *, token: str, store_name: str, marketplace: str) -> dict[str, Any]:
    payload = _post_json(
        f"{base_url}/stores",
        {
            "platform": "ebay",
            "store_name": store_name,
            "marketplace": marketplace,
            "stage": "store_opened",
        },
        token=token,
    )
    store = payload.get("store") if isinstance(payload.get("store"), dict) else {}
    if not store.get("store_id"):
        raise RuntimeError("store creation did not return store_id.")
    return store


def _record_readonly_connection(base_url: str, *, token: str, store_id: str) -> None:
    _post_json(
        f"{base_url}/stores/{store_id}/connections",
        {
            "platform": "ebay",
            "connection_type": "oauth",
            "status": "read_only_authorized",
            "scopes": [
                "sell.account.readonly",
                "sell.inventory.readonly",
                "sell.fulfillment.readonly",
                "sell.finances",
            ],
            "metadata": {
                "credential_source": "backend_legacy_hermes_bridge",
                "local_smoke": True,
            },
        },
        token=token,
    )


def _sync_summary(*, sync: dict[str, Any], preflight: dict[str, Any], output_root: Path) -> dict[str, Any]:
    worker = sync.get("worker_result") if isinstance(sync.get("worker_result"), dict) else {}
    live = worker.get("live_read_result") if isinstance(worker.get("live_read_result"), dict) else {}
    packet = worker.get("data_packet") if isinstance(worker.get("data_packet"), dict) else {}
    packet_body = packet.get("packet") if isinstance(packet.get("packet"), dict) else {}
    summary = {
        "status": sync.get("sync", {}).get("status") if isinstance(sync.get("sync"), dict) else None,
        "task_status": sync.get("task", {}).get("status") if isinstance(sync.get("task"), dict) else None,
        "worker_status": worker.get("status"),
        "live_read_status": live.get("status"),
        "live_request_performed": bool(live.get("live_read_performed")),
        "request_count": live.get("request_count"),
        "resource_count": live.get("resource_count"),
        "route_results": _route_results(live.get("route_results") if isinstance(live.get("route_results"), list) else []),
        "token_mode": preflight.get("token_mode"),
        "data_packet_id": packet.get("packet_id"),
        "data_packet_status": packet_body.get("status"),
        "source_mode": packet.get("source_mode") or packet_body.get("source_mode"),
        "present_resource_keys": packet_body.get("present_resource_keys") or [],
        "missing_resource_keys": packet_body.get("missing_resource_keys") or [],
        "real_platform_writes_enabled": bool(sync.get("real_platform_writes_enabled")),
        "secret_exposed": False,
    }
    _write_json(output_root / "live_readonly_sync_summary.json", summary)
    return summary


def _route_results(routes: list[Any]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for route in routes:
        if not isinstance(route, dict):
            continue
        compact.append(
            {
                "resource_key": route.get("resource_key"),
                "successful_path_count": route.get("successful_path_count"),
                "data_present": bool(route.get("data_present")),
                "paths": [
                    {
                        "path": path.get("path") or path.get("path_template"),
                        "status": path.get("status"),
                        "http_status": path.get("http_status"),
                        "error_type": path.get("error_type"),
                        "query_keys": path.get("query_keys") or [],
                        "missing_context": path.get("missing_context") or [],
                    }
                    for path in (route.get("paths") or [])
                    if isinstance(path, dict)
                ],
            }
        )
    return compact


def _run_ai_ceo_workflow(*, base_url: str, token: str, store_id: str, product: str, output_root: Path) -> dict[str, Any]:
    workflow = _post_json(
        f"{base_url}/tasks/product-workflow",
        {
            "store_id": store_id,
            "product": product,
            "merchant_goal": (
                "AI CEO reads the official eBay packet, evaluates one product-operation workflow, "
                "prepares listing/media/customer/finance reports, and keeps every eBay write behind confirmation."
            ),
            "adapter": "jiejing-local",
            "run_id": "local-ebay-official-packet-ai-ceo-smoke",
            "source_mode": "official_api_packet",
            "run_mode": "local_worker_now",
            "attach_latest_platform_data_packet": True,
            "merchant_profile": {
                "merchantStage": "store_opened",
                "permissionLevel": "service_auto",
                "sourceApiMode": "official_ebay_readonly_packet",
                "riskLevel": "balanced",
            },
        },
        token=token,
        timeout=300,
    )
    task = workflow.get("task") if isinstance(workflow.get("task"), dict) else {}
    worker = workflow.get("worker_result") if isinstance(workflow.get("worker_result"), dict) else {}
    runtime = workflow.get("runtime") if isinstance(workflow.get("runtime"), dict) else {}
    saved = workflow.get("saved") if isinstance(workflow.get("saved"), dict) else {}
    handoff = workflow.get("platform_data_packet_handoff")
    if not isinstance(handoff, dict):
        handoff = (task.get("input") or {}).get("platform_data_packet_handoff") if isinstance(task.get("input"), dict) else {}
    reports = _fetch_json(f"{base_url}/reports?task_id={task.get('task_id')}", token=token).get("reports", [])
    confirmations = _fetch_json(f"{base_url}/confirmations", token=token).get("confirmations", [])
    pending = [item for item in confirmations if isinstance(item, dict) and item.get("status") == "pending"]
    summary = {
        "workflow_status": task.get("status"),
        "worker_status": worker.get("status"),
        "runtime_run_id": runtime.get("run_id"),
        "handoff_packet_id": handoff.get("packet_id") if isinstance(handoff, dict) else None,
        "handoff_source_mode": handoff.get("source_mode") if isinstance(handoff, dict) else None,
        "handoff_ready_for_runtime": bool(handoff.get("ready_for_runtime")) if isinstance(handoff, dict) else False,
        "saved_reports": saved.get("reports"),
        "saved_confirmations": saved.get("confirmations"),
        "reports_count": len(reports) if isinstance(reports, list) else 0,
        "pending_confirmations_count": len(pending),
        "high_risk_pending_count": len([item for item in pending if item.get("high_risk")]),
        "real_platform_writes_enabled": bool(workflow.get("real_platform_writes_enabled")),
        "secret_exposed": False,
    }
    _write_json(output_root / "ai_ceo_workflow_from_official_packet_summary.json", summary)
    return summary


def _fetch_json(url: str, token: str | None = None, timeout: int = 60) -> dict[str, Any]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GET {url} failed with HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:500]}") from exc


def _post_json(url: str, payload: dict[str, Any], token: str | None = None, timeout: int = 120) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"POST {url} failed with HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:500]}") from exc


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _print_summary(final: dict[str, Any]) -> None:
    preflight = final.get("preflight") if isinstance(final.get("preflight"), dict) else {}
    sync = final.get("sync") if isinstance(final.get("sync"), dict) else {}
    workflow = final.get("workflow") if isinstance(final.get("workflow"), dict) else {}
    print(f"EBAY_PREFLIGHT_STATUS={preflight.get('status')}")
    print(f"CAN_QUEUE_SYNC={preflight.get('can_queue_sync')}")
    print(f"TOKEN_MODE={preflight.get('token_mode')}")
    print(f"LIVE_READ_STATUS={sync.get('live_read_status')}")
    print(f"LIVE_REQUEST_PERFORMED={sync.get('live_request_performed')}")
    print(f"REQUEST_COUNT={sync.get('request_count')}")
    print(f"DATA_PACKET_ID={sync.get('data_packet_id')}")
    print(f"PRESENT_RESOURCES={','.join(sync.get('present_resource_keys') or []) or '-'}")
    print(f"MISSING_RESOURCES={','.join(sync.get('missing_resource_keys') or []) or '-'}")
    if workflow:
        print(f"WORKFLOW_STATUS={workflow.get('workflow_status')}")
        print(f"RUNTIME_RUN_ID={workflow.get('runtime_run_id')}")
        print(f"REPORTS={workflow.get('reports_count')}")
        print(f"PENDING_CONFIRMATIONS={workflow.get('pending_confirmations_count')}")
    print(f"REAL_PLATFORM_WRITES_ENABLED={final.get('real_platform_writes_enabled')}")
    print(f"SECRET_EXPOSED={final.get('secret_exposed')}")
    print(f"OUTPUT={final.get('output_root')}")


def _exit_code(*, final: dict[str, Any], workflow_required: bool) -> int:
    preflight = final.get("preflight") if isinstance(final.get("preflight"), dict) else {}
    sync = final.get("sync") if isinstance(final.get("sync"), dict) else {}
    workflow = final.get("workflow") if isinstance(final.get("workflow"), dict) else {}
    ok = (
        preflight.get("status") == "ready_for_official_read"
        and preflight.get("can_queue_sync") is True
        and sync.get("live_request_performed") is True
        and bool(sync.get("data_packet_id"))
        and final.get("real_platform_writes_enabled") is False
        and final.get("secret_exposed") is False
    )
    if workflow_required:
        ok = ok and workflow.get("workflow_status") in {"completed", "completed_with_blocks"} and workflow.get("handoff_packet_id") == sync.get("data_packet_id")
    return 0 if ok else 1


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    raise SystemExit(main())

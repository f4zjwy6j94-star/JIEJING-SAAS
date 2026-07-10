#!/usr/bin/env python3
"""Run a controlled model-value proof over an existing sanitized eBay packet.

The command defaults to a read-only preflight. ``--execute`` permits the live
model call and report persistence, but never enables eBay writes or returns
packet contents, tenant identifiers, credentials, or model responses.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1] if "__file__" in globals() else Path.cwd()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.model_provider_catalog import (  # noqa: E402
    build_model_client_from_byok_secret,
    get_model_provider,
    normalize_model_api_base_url,
)
from jiejing_saas.model_value_gate import build_model_value_gate  # noqa: E402
from jiejing_saas.model_value_rehearsal import run_model_value_rehearsal  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Controlled JIEJING model-value proof")
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("JIEJING_SAAS_DB_PATH") or "/data/saas.sqlite"))
    parser.add_argument("--runtime-db", type=Path, default=Path(os.environ.get("JIEJING_RUNTIME_DB_PATH") or "/data/runtime.sqlite"))
    parser.add_argument("--output-root", type=Path, default=Path(os.environ.get("JIEJING_OUTPUT_ROOT") or "/data/output"))
    parser.add_argument("--packet-id", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = SaaSSettings.from_env(
        db_path=args.db,
        runtime_db_path=args.runtime_db,
        output_root=args.output_root,
        host="127.0.0.1",
        port=8788,
    )
    repository = SaaSRepository(
        args.db,
        database_engine=settings.database_engine,
        database_url=os.environ.get("JIEJING_DATABASE_URL", ""),
    )
    repository.initialize()

    packet = _select_latest_safe_packet(repository, requested_packet_id=args.packet_id)
    if not packet:
        return _fail("sanitized_official_packet_not_found")
    if settings.requested_real_platform_writes or settings.ebay_write_live_enabled:
        return _fail("real_platform_write_flags_must_be_disabled")

    preflight = {
        "status": "ready_for_controlled_execution",
        "packet_id": packet["packet_id"],
        "source_mode": "official_api_sanitized",
        "would_call_live_model": bool(args.execute),
        "would_persist_reports": bool(args.execute),
        "runtime_gets_sanitized_packet_only": True,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }
    if not args.execute:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0

    try:
        model_client = _platform_model_client(model=args.model)
        result = run_model_value_rehearsal(
            settings=settings,
            repository=repository,
            company_id=packet["company_id"],
            store_id=packet["store_id"],
            user_id=packet["created_by"],
            packet_id=packet["packet_id"],
            product="\u5e97\u94fa\u7ea7 eBay \u520a\u767b\u51c6\u5907\u5ea6\uff08\u672a\u9009\u5b9a\u5177\u4f53 SKU\uff09",
            merchant_goal=(
                "\u57fa\u4e8e\u5df2\u8131\u654f\u7684 eBay \u5b98\u65b9\u53ea\u8bfb\u6570\u636e\u5305\uff0c"
                "\u751f\u6210\u4e2d\u6587\u5e02\u573a\u7ecf\u8425\u62a5\u544a\u548c Listing Package\u3002"
                "\u53ea\u8bc4\u4f30\u5e97\u94fa\u7ea7\u51c6\u5907\u5ea6\uff1b\u6ca1\u6709\u4f9b\u5e94\u5546\u548c"
                "\u5177\u4f53\u5546\u54c1\u4e8b\u5b9e\u65f6\u5fc5\u987b\u6807\u4e3a\u5f85\u8865\u8d44\u6599\uff0c"
                "\u4e0d\u5f97\u5f15\u7528\u65e7\u6d4b\u8bd5\u5546\u54c1\uff0c\u4e0d\u5f97\u89e6\u53d1\u4efb\u4f55 eBay \u5199\u5165\u3002"
            ),
            allow_live_model=True,
            model_client=model_client,
        )
        gate = build_model_value_gate(settings, repository)
    except Exception as exc:  # Keep provider or database details out of operator output.
        return _fail(f"controlled_execution_failed:{exc.__class__.__name__}")

    evidence = gate.get("evidence") if isinstance(gate.get("evidence"), dict) else {}
    output = {
        **preflight,
        "status": str(result.get("status") or "unknown"),
        "blockers": [str(item) for item in result.get("blockers") or []],
        "report_types": [str(item) for item in result.get("report_types") or []],
        "live_model_report_types": [str(item) for item in result.get("live_model_report_types") or []],
        "model_value_ready": bool(gate.get("ready_for_paid_value_claim")),
        "model_value_blockers": [str(item) for item in gate.get("blockers") or []],
        "source_packet_linked_live_report_types": [
            str(item) for item in evidence.get("source_packet_linked_live_report_types") or []
        ],
        "sanitized_official_packet_count_sampled": int(evidence.get("sanitized_official_packet_count_sampled") or 0),
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["status"] == "completed" and output["model_value_ready"] else 2


def _select_latest_safe_packet(repository: SaaSRepository, *, requested_packet_id: str = "") -> dict[str, Any] | None:
    params: tuple[Any, ...] = ()
    where = "where platform = 'ebay'"
    if requested_packet_id:
        where += " and packet_id = ?"
        params = (requested_packet_id,)
    with repository._connect() as conn:
        rows = conn.execute(
            f"""
            select packet_id, company_id, store_id, created_by, source_mode, status,
                   created_at, packet_json
            from platform_data_packets
            {where}
            order by created_at desc
            limit 200
            """,
            params,
        ).fetchall()
    for row in rows:
        payload = _json_object(row["packet_json"])
        source_mode = str(row["source_mode"] or payload.get("source_mode") or "").lower()
        present = payload.get("present_resource_keys")
        missing = payload.get("missing_resource_keys")
        if (
            "official_api" in source_mode
            and payload.get("secret_exposed") is False
            and isinstance(present, list)
            and bool(present)
            and (not isinstance(missing, list) or not missing)
        ):
            return {
                "packet_id": str(row["packet_id"]),
                "company_id": str(row["company_id"]),
                "store_id": str(row["store_id"]),
                "created_by": str(row["created_by"]),
            }
    return None


def _platform_model_client(*, model: str = "") -> Any:
    provider_key = (
        os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL_PROVIDER")
        or os.environ.get("JIEJING_MODEL_PROVIDER")
        or ("deepseek" if os.environ.get("DEEPSEEK_API_KEY") else "openai")
    ).strip()
    definition = get_model_provider(provider_key)
    if not definition or not definition.supported_live_adapter:
        raise RuntimeError("platform_model_provider_not_supported")
    secret_value = (os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL_API_KEY") or "").strip()
    if not secret_value and definition.provider_key == "deepseek":
        secret_value = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not secret_value:
        secret_value = (os.environ.get("JIEJING_MODEL_API_KEY") or "").strip()
    if not secret_value:
        raise RuntimeError("platform_model_not_configured")
    selected_model = (
        model.strip()
        or (os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL") or "").strip()
        or (os.environ.get("JIEJING_MODEL") or "").strip()
        or definition.default_model
    )
    base_url = normalize_model_api_base_url(
        provider_key=definition.provider_key,
        base_url=(
            os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL_BASE_URL")
            or os.environ.get("JIEJING_MODEL_BASE_URL")
            or definition.default_base_url
        ),
    )
    return build_model_client_from_byok_secret(
        provider_key=definition.provider_key,
        api_key=secret_value,
        model=selected_model,
        base_url=base_url,
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _fail(code: str) -> int:
    print(
        json.dumps(
            {
                "status": "blocked",
                "blocked_by": [code],
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

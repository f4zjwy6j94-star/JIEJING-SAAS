"""Public-search handoff for SaaS product workflows.

The SaaS backend owns provider execution. Runtime receives only normalized
source records and packet summaries, never API keys or raw provider responses.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .config import SaaSSettings
from .provider_job_runner import ProviderJobRunner


def build_public_search_market_handoff(
    *,
    settings: SaaSSettings,
    company_id: str,
    store: dict[str, Any],
    user_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Run the bounded public-search provider job and build Runtime inputs."""

    product = str(body.get("product") or body.get("product_context") or "eBay product").strip()
    marketplace = str(body.get("marketplace") or store.get("marketplace") or "EBAY_US").strip()
    category_hint = str(body.get("category_hint") or body.get("category") or product or "eBay product").strip()
    query = str(
        body.get("public_search_query")
        or body.get("search_query")
        or f"{product} {marketplace} eBay price reviews competitors supplier"
    ).strip()
    provider_output = ProviderJobRunner(settings=settings).run(
        company_id=company_id,
        store_id=str(store.get("store_id") or body.get("store_id") or ""),
        user_id=user_id,
        task_id=str(body.get("run_id") or body.get("task_id") or "product_workflow_public_search"),
        job_id=str(body.get("run_id") or "inline_public_search_market_research"),
        job_body={
            "provider_job_key": "public_search.market_research",
            "secret_ref": str(body.get("public_search_secret_ref") or body.get("search_secret_ref") or ""),
            "inputs": {
                "query": query,
                "marketplace": marketplace,
                "category_hint": category_hint,
                "max_results": body.get("public_search_max_results") or 5,
                "search_depth": body.get("public_search_depth") or "basic",
            },
        },
    )
    runtime_probe = _runtime_probe_from_provider_output(provider_output=provider_output)
    return {
        "status": runtime_probe.get("status"),
        "provider_job_key": "public_search.market_research",
        "provider_status": provider_output.get("status"),
        "source_mode": _source_mode(provider_output),
        "query": query,
        "marketplace": marketplace,
        "category_hint": category_hint,
        "result_count": len(runtime_probe.get("source_records") or []),
        "runtime_probe": runtime_probe,
        "provider_job": _safe_provider_summary(provider_output),
        "runtime_gets_raw_secret": False,
        "frontend_gets_raw_secret": False,
        "raw_provider_response_stored": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def merge_public_search_handoff_input(body: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any]:
    """Merge public-search handoff into Runtime input without overwriting user data."""

    if not handoff:
        return body
    merged = dict(body)
    summary = {
        key: handoff.get(key)
        for key in [
            "status",
            "provider_job_key",
            "provider_status",
            "source_mode",
            "query",
            "marketplace",
            "category_hint",
            "result_count",
            "runtime_gets_raw_secret",
            "frontend_gets_raw_secret",
            "raw_provider_response_stored",
            "real_platform_writes_enabled",
            "secret_exposed",
        ]
    }
    merged.setdefault("public_search_provider_handoff", summary)
    existing_market = merged.get("market_probe_inputs") if isinstance(merged.get("market_probe_inputs"), dict) else {}
    market_probe_inputs = dict(existing_market)
    if "public_search" not in market_probe_inputs and isinstance(handoff.get("runtime_probe"), dict):
        market_probe_inputs["public_search"] = handoff["runtime_probe"]
    merged["market_probe_inputs"] = market_probe_inputs
    return merged


def _runtime_probe_from_provider_output(*, provider_output: dict[str, Any]) -> dict[str, Any]:
    output_packet = provider_output.get("output_packet") if isinstance(provider_output.get("output_packet"), dict) else {}
    records = output_packet.get("records") if isinstance(output_packet.get("records"), list) else []
    source_records = [_source_record_from_provider_record(item, index) for index, item in enumerate(records, start=1) if isinstance(item, dict)]
    source_records = [item for item in source_records if item.get("title") or item.get("url") or item.get("note")]
    provider_status = str(provider_output.get("status") or "")
    live_provider_called = bool((provider_output.get("safety") or {}).get("live_provider_called")) if isinstance(provider_output.get("safety"), dict) else False
    is_ready = bool(source_records) and provider_status in {"completed_live_read", "completed_dry_run"}
    source_mode = _source_mode(provider_output)
    return {
        "status": "ready" if is_ready else provider_status or "pending_tool",
        "source_type": "public_page" if live_provider_called else "ai_inference",
        "confidence": "medium" if live_provider_called and source_records else "low",
        "summary": _probe_summary(provider_output=provider_output, source_records=source_records, source_mode=source_mode),
        "provider": output_packet.get("provider") or "public_search",
        "source_mode": source_mode,
        "query": output_packet.get("query") or (provider_output.get("inputs") or {}).get("query"),
        "metrics": {
            "result_count": len(source_records),
            "provider_status": provider_status,
            "live_provider_called": live_provider_called,
            "raw_provider_response_stored": False,
            "secret_exposed": False,
        },
        "source_records": source_records,
        "results": [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "snippet": item.get("note"),
                "captured_at": item.get("captured_at"),
                "source_type": item.get("provider_source_type"),
                "confidence": item.get("confidence"),
            }
            for item in source_records[:10]
        ],
        "next_action": provider_output.get("next_action"),
        "raw_provider_response_stored": False,
        "secret_exposed": False,
        "real_platform_writes_enabled": False,
    }


def _source_record_from_provider_record(item: dict[str, Any], index: int) -> dict[str, Any]:
    title = str(item.get("title") or f"Public search source {index}").strip()[:300]
    url = str(item.get("url") or "").strip()[:1000]
    snippet = str(item.get("snippet") or item.get("content") or "").strip()[:1200]
    provider_source_type = str(item.get("source_type") or "public_search").strip()
    digest = hashlib.sha1(f"{url}|{title}|{index}".encode("utf-8", errors="ignore")).hexdigest()[:12]
    return {
        "source_id": f"src_public_search_{digest}",
        "source_type": "public_page" if provider_source_type == "live_public_search" else "ai_inference",
        "provider_source_type": provider_source_type,
        "title": title,
        "url": url or None,
        "captured_at": item.get("captured_at") or "",
        "confidence": str(item.get("confidence") or "low"),
        "used_for": ["market.data_packet", "market.report"],
        "note": snippet,
        "raw_provider_response_stored": False,
        "secret_exposed": False,
    }


def _safe_provider_summary(provider_output: dict[str, Any]) -> dict[str, Any]:
    output_packet = provider_output.get("output_packet") if isinstance(provider_output.get("output_packet"), dict) else {}
    safety = provider_output.get("safety") if isinstance(provider_output.get("safety"), dict) else {}
    return {
        "status": provider_output.get("status"),
        "provider_family": provider_output.get("provider_family"),
        "merchant_visible_summary": provider_output.get("merchant_visible_summary"),
        "output_packet_type": output_packet.get("packet_type"),
        "result_count": output_packet.get("result_count") if output_packet.get("result_count") is not None else len(output_packet.get("records") or []),
        "source_record": provider_output.get("source_record") if isinstance(provider_output.get("source_record"), dict) else {},
        "safety": {
            "live_provider_called": bool(safety.get("live_provider_called")),
            "raw_provider_response_stored": False,
            "secret_exposed": False,
            "real_execution_allowed": False,
        },
        "secret_exposed": False,
    }


def _source_mode(provider_output: dict[str, Any]) -> str:
    source_record = provider_output.get("source_record") if isinstance(provider_output.get("source_record"), dict) else {}
    return str(source_record.get("source_mode") or "dry_run_contract_only")


def _probe_summary(*, provider_output: dict[str, Any], source_records: list[dict[str, Any]], source_mode: str) -> str:
    if source_records:
        return (
            f"Public search provider handoff produced {len(source_records)} normalized source records "
            f"for the market data packet. Source mode: {source_mode}; raw provider response and secrets were not stored."
        )
    return str(provider_output.get("merchant_visible_summary") or "Public search did not produce source records yet.")

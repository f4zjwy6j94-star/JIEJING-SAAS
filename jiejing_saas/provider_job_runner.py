"""SaaS-side runner for Jiejing provider jobs.

Provider jobs are the safe bridge between merchant-facing SaaS tasks and real
external capabilities such as public search, eBay read-only data, sourcing,
logistics, media generation, and model calls. Live providers are disabled by
default; each one must be explicitly enabled and must keep raw secrets and raw
provider responses out of public records.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
import urllib.parse
import urllib.request
from typing import Any, Callable

from jiejing_runtime.provider_job_contracts import build_provider_job_contract_catalog

from .config import SaaSSettings
from .vault_secret_resolver import VaultSecretResolver


SECRET_KEY_MARKERS = ("secret", "token", "password", "api_key", "apikey", "refresh", "authorization")
ProviderTransport = Callable[[urllib.request.Request, float], tuple[int, dict[str, str], bytes]]


class ProviderJobRunner:
    """Run provider jobs in a local, auditable, no-live-call mode."""

    def __init__(self, settings: SaaSSettings | None = None, *, transport: ProviderTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport or _urlopen_transport
        self.catalog = build_provider_job_contract_catalog()
        self.contracts_by_key = {item["key"]: item for item in self.catalog.get("contracts", [])}

    def run(
        self,
        *,
        company_id: str,
        store_id: str,
        user_id: str,
        task_id: str,
        job_id: str,
        job_body: dict[str, Any],
    ) -> dict[str, Any]:
        key = str(job_body.get("provider_job_key") or job_body.get("contract_key") or "")
        contract = self.contracts_by_key.get(key)
        if not contract:
            raise ValueError(f"unknown provider job contract: {key or '<empty>'}")

        raw_inputs = job_body.get("inputs") if isinstance(job_body.get("inputs"), dict) else {}
        effective_inputs = {
            "company_id": company_id,
            "store_id": store_id,
            "user_id": user_id,
            **raw_inputs,
        }
        required_inputs = [str(item) for item in contract.get("required_inputs", [])]
        missing_inputs = [name for name in required_inputs if _is_missing(effective_inputs.get(name))]
        captured_at = _now_iso()
        live_result = self._maybe_run_live_provider(
            key=key,
            contract=contract,
            inputs=effective_inputs,
            missing_inputs=missing_inputs,
            job_body=job_body,
            captured_at=captured_at,
        )
        if live_result:
            return live_result

        status = "blocked_missing_input" if missing_inputs else "completed_dry_run"
        output_packet = self._build_output_packet(
            key=key,
            contract=contract,
            inputs=effective_inputs,
            missing_inputs=missing_inputs,
            captured_at=captured_at,
        )
        return {
            "status": status,
            "provider_job_key": key,
            "contract_version": self.catalog.get("contract_version"),
            "provider_family": contract.get("provider_family"),
            "queue": contract.get("queue"),
            "task_id": task_id,
            "job_id": job_id,
            "store_id": store_id,
            "required_secret_purpose": contract.get("required_secret_purpose"),
            "secret_ref_required": bool(contract.get("required_secret_purpose")),
            "secret_ref_provided": bool(job_body.get("secret_ref")),
            "timeout_seconds": contract.get("timeout_seconds"),
            "max_attempts": contract.get("max_attempts"),
            "inputs": _redact_secret_like(effective_inputs),
            "missing_inputs": missing_inputs,
            "output_packet": output_packet,
            "source_record": {
                "source_record_type": contract.get("source_record_type"),
                "source_mode": "dry_run_contract_only",
                "captured_at": captured_at,
                "raw_provider_response_stored": False,
                "normalized_output_stored": True,
            },
            "merchant_visible_summary": _merchant_summary(contract=contract, status=status, missing_inputs=missing_inputs),
            "blocked_actions": list(contract.get("blocked_actions", [])),
            "safety": {
                "live_provider_called": False,
                "raw_secret_read": False,
                "raw_provider_response_stored": False,
                "secret_exposed": False,
                "real_execution_allowed": False,
                "frontend_gets_raw_secret": False,
                "runtime_gets_raw_secret": False,
            },
            "next_action": _next_action(status=status, missing_inputs=missing_inputs),
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }

    def _maybe_run_live_provider(
        self,
        *,
        key: str,
        contract: dict[str, Any],
        inputs: dict[str, Any],
        missing_inputs: list[str],
        job_body: dict[str, Any],
        captured_at: str,
    ) -> dict[str, Any] | None:
        if key != "public_search.market_research":
            return None
        if _env_bool("JIEJING_PUBLIC_SEARCH_LIVE_ENABLED", default=False) is not True:
            return None
        if missing_inputs:
            return None
        return self._run_public_search_live(
            contract=contract,
            inputs=inputs,
            job_body=job_body,
            captured_at=captured_at,
        )

    def _run_public_search_live(
        self,
        *,
        contract: dict[str, Any],
        inputs: dict[str, Any],
        job_body: dict[str, Any],
        captured_at: str,
    ) -> dict[str, Any]:
        secret = self._resolve_public_search_secret(job_body=job_body, inputs=inputs)
        if not secret.get("ok"):
            missing = secret.get("blocked_by") if isinstance(secret.get("blocked_by"), list) else ["public_search_api_key"]
            output_packet = {
                "packet_type": contract.get("output_packet"),
                "provider_family": contract.get("provider_family"),
                "source_record_type": contract.get("source_record_type"),
                "status": "blocked_missing_secret",
                "captured_at": captured_at,
                "records": [],
                "missing_inputs": missing,
                "live_provider_called": False,
                "secret_exposed": False,
            }
            return self._provider_result(
                contract=contract,
                status="blocked_missing_secret",
                inputs=inputs,
                missing_inputs=missing,
                output_packet=output_packet,
                source_record={
                    "source_record_type": contract.get("source_record_type"),
                    "source_mode": "blocked_before_live_provider",
                    "captured_at": captured_at,
                    "raw_provider_response_stored": False,
                    "normalized_output_stored": False,
                },
                merchant_visible_summary="Public search cannot run yet. A backend search API key or secret_ref is missing.",
                live_provider_called=False,
                raw_secret_read=bool(secret.get("raw_secret_read")),
                next_action="Configure public_search_api_key in Vault/KMS or backend environment, then retry the provider job.",
            )
        query = str(inputs.get("query") or "").strip()
        max_results = _safe_int(inputs.get("max_results"), default=5)
        max_results = max(1, min(max_results, 10))
        body = {
            "query": query,
            "search_depth": str(inputs.get("search_depth") or "basic"),
            "topic": str(inputs.get("topic") or "general"),
            "max_results": max_results,
            "include_answer": bool(inputs.get("include_answer") or False),
            "include_raw_content": False,
        }
        request = urllib.request.Request(
            "https://api.tavily.com/search",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {secret['secret_value']}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            status_code, _headers, raw = self.transport(request, 20)
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as exc:  # pragma: no cover - live provider dependent
            return self._provider_error_result(
                contract=contract,
                inputs=inputs,
                captured_at=captured_at,
                error_type=type(exc).__name__,
                blocked_by=["public_search_http_error"],
                raw_secret_read=bool(secret.get("raw_secret_read")),
            )
        if status_code >= 400 or not isinstance(payload, dict):
            return self._provider_error_result(
                contract=contract,
                inputs=inputs,
                captured_at=captured_at,
                error_type="HTTPError",
                blocked_by=["public_search_provider_error"],
                raw_secret_read=bool(secret.get("raw_secret_read")),
                http_status=status_code,
            )
        records = _normalize_tavily_results(payload=payload, captured_at=captured_at)
        output_packet = {
            "packet_type": contract.get("output_packet"),
            "provider_family": contract.get("provider_family"),
            "source_record_type": contract.get("source_record_type"),
            "status": "live_ready",
            "provider": "tavily",
            "query": payload.get("query") or query,
            "marketplace": inputs.get("marketplace"),
            "category_hint": inputs.get("category_hint"),
            "captured_at": captured_at,
            "normalized_outputs": list(contract.get("normalized_outputs", [])),
            "records": records,
            "result_count": len(records),
            "live_provider_called": True,
            "raw_provider_response_stored": False,
            "secret_exposed": False,
        }
        return self._provider_result(
            contract=contract,
            status="completed_live_read",
            inputs=inputs,
            missing_inputs=[],
            output_packet=output_packet,
            source_record={
                "source_record_type": contract.get("source_record_type"),
                "source_mode": "live_public_search",
                "provider": "tavily",
                "captured_at": captured_at,
                "result_count": len(records),
                "raw_provider_response_stored": False,
                "normalized_output_stored": True,
            },
            merchant_visible_summary=f"Public search returned {len(records)} normalized market source records. Raw provider response and API key were not stored.",
            live_provider_called=True,
            raw_secret_read=bool(secret.get("raw_secret_read")),
            next_action="Use these source records in the market data packet and keep missing facts marked pending.",
        )

    def _provider_error_result(
        self,
        *,
        contract: dict[str, Any],
        inputs: dict[str, Any],
        captured_at: str,
        error_type: str,
        blocked_by: list[str],
        raw_secret_read: bool,
        http_status: int | None = None,
    ) -> dict[str, Any]:
        output_packet = {
            "packet_type": contract.get("output_packet"),
            "provider_family": contract.get("provider_family"),
            "source_record_type": contract.get("source_record_type"),
            "status": "provider_error",
            "captured_at": captured_at,
            "records": [],
            "blocked_by": blocked_by,
            "http_status": http_status,
            "live_provider_called": True,
            "raw_provider_response_stored": False,
            "secret_exposed": False,
        }
        return self._provider_result(
            contract=contract,
            status="failed_live_provider",
            inputs=inputs,
            missing_inputs=blocked_by,
            output_packet=output_packet,
            source_record={
                "source_record_type": contract.get("source_record_type"),
                "source_mode": "live_public_search_failed",
                "captured_at": captured_at,
                "http_status": http_status,
                "raw_provider_response_stored": False,
                "normalized_output_stored": False,
            },
            merchant_visible_summary="Public search provider failed. The failure is visible in the work record and no raw response was stored.",
            live_provider_called=True,
            raw_secret_read=raw_secret_read,
            next_action=f"Check provider configuration and retry. Error type: {error_type}.",
        )

    def _provider_result(
        self,
        *,
        contract: dict[str, Any],
        status: str,
        inputs: dict[str, Any],
        missing_inputs: list[str],
        output_packet: dict[str, Any],
        source_record: dict[str, Any],
        merchant_visible_summary: str,
        live_provider_called: bool,
        raw_secret_read: bool,
        next_action: str,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "provider_job_key": contract.get("key"),
            "contract_version": self.catalog.get("contract_version"),
            "provider_family": contract.get("provider_family"),
            "queue": contract.get("queue"),
            "required_secret_purpose": contract.get("required_secret_purpose"),
            "secret_ref_required": bool(contract.get("required_secret_purpose")),
            "secret_ref_provided": False,
            "timeout_seconds": contract.get("timeout_seconds"),
            "max_attempts": contract.get("max_attempts"),
            "inputs": _redact_secret_like(inputs),
            "missing_inputs": missing_inputs,
            "output_packet": output_packet,
            "source_record": source_record,
            "merchant_visible_summary": merchant_visible_summary,
            "blocked_actions": list(contract.get("blocked_actions", [])),
            "safety": {
                "live_provider_called": live_provider_called,
                "raw_secret_read": raw_secret_read,
                "raw_provider_response_stored": False,
                "secret_exposed": False,
                "real_execution_allowed": False,
                "frontend_gets_raw_secret": False,
                "runtime_gets_raw_secret": False,
            },
            "next_action": next_action,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }

    def _resolve_public_search_secret(self, *, job_body: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
        direct = os.environ.get("JIEJING_PUBLIC_SEARCH_API_KEY") or os.environ.get("TAVILY_API_KEY") or ""
        if direct:
            return {"ok": True, "source": "backend_env_public_search_api_key", "secret_value": direct, "raw_secret_read": False}
        secret_ref_id = str(job_body.get("secret_ref") or "").strip()
        if not (secret_ref_id and self.settings):
            return {"ok": False, "blocked_by": ["public_search_api_key"], "raw_secret_read": False, "secret_exposed": False}
        resolved = VaultSecretResolver(self.settings, transport=self.transport).resolve_secret(
            secret_ref={
                "secret_ref": secret_ref_id,
                "company_id": inputs.get("company_id"),
                "store_id": inputs.get("store_id"),
                "provider": "public_search",
                "purpose": "public_search_api_key",
            },
            requested_by="queued_worker",
            task_scope="public_search_market_research",
            allowed_purposes=["public_search_api_key"],
        )
        if not resolved.get("ok"):
            return {"ok": False, "blocked_by": resolved.get("blocked_by") or ["public_search_api_key"], "raw_secret_read": False, "secret_exposed": False}
        return {"ok": True, "source": resolved.get("source"), "secret_value": str(resolved.get("secret_value") or ""), "raw_secret_read": True}

    def _build_output_packet(
        self,
        *,
        key: str,
        contract: dict[str, Any],
        inputs: dict[str, Any],
        missing_inputs: list[str],
        captured_at: str,
    ) -> dict[str, Any]:
        base = {
            "packet_type": contract.get("output_packet"),
            "provider_family": contract.get("provider_family"),
            "source_record_type": contract.get("source_record_type"),
            "status": "incomplete" if missing_inputs else "dry_run_ready",
            "captured_at": captured_at,
            "normalized_outputs": list(contract.get("normalized_outputs", [])),
            "missing_inputs": missing_inputs,
            "live_provider_called": False,
            "secret_exposed": False,
        }
        if missing_inputs:
            return {**base, "records": [], "merchant_note": "Provider job is queued in the right shape but still lacks required inputs."}

        if key == "public_search.market_research":
            query = str(inputs.get("query") or "merchant product")
            marketplace = str(inputs.get("marketplace") or "EBAY_US")
            return {
                **base,
                "records": [
                    {
                        "title": f"Public search signal for {query}",
                        "url": "dry-run://public-search/result-1",
                        "snippet": f"Dry-run market signal prepared for {marketplace}; replace with Tavily/SerpApi/Bing output in production.",
                        "source_type": "dry_run_public_search",
                        "confidence": "contract_ready",
                        "captured_at": captured_at,
                    }
                ],
            }
        if key == "ebay.read_only_snapshot":
            resources = inputs.get("resource_keys") if isinstance(inputs.get("resource_keys"), list) else []
            return {
                **base,
                "marketplace_id": str(inputs.get("marketplace_id") or "EBAY_US"),
                "resource_keys": resources,
                "sections": {resource: {"status": "dry_run_placeholder", "safe_for_runtime": True} for resource in resources},
                "writes_supported": False,
            }
        if key == "sourcing.1688_availability":
            keyword = str(inputs.get("product_keyword_or_url") or "product")
            filters = inputs.get("risk_filters") if isinstance(inputs.get("risk_filters"), dict) else {}
            return {
                **base,
                "candidates": [
                    {
                        "source_url": "dry-run://1688/candidate-1",
                        "title": f"{keyword} candidate from authorized sourcing adapter",
                        "unit_cost": "pending_live_source",
                        "moq": "pending_live_source",
                        "stock": "pending_live_source",
                        "ship_from": "pending_live_source",
                        "package_weight_g": "pending_live_source",
                        "material": "pending_live_source",
                        "matched_risk_filters": sorted(filters.keys()),
                    }
                ],
                "procurement_order_allowed": False,
            }
        if key == "logistics.orange_connex_quote":
            return {
                **base,
                "quotes": [
                    {
                        "carrier": "Orange Connex / SpeedPAK",
                        "service_name": str(inputs.get("service_hint") or "pending_service_selection"),
                        "cost": "pending_live_quote",
                        "currency": "USD",
                        "eta_min_days": "pending_live_quote",
                        "eta_max_days": "pending_live_quote",
                        "tracking": "not_created",
                    }
                ],
                "buy_label_allowed": False,
            }
        if key == "media.fal_asset_generation":
            image_count = int(inputs.get("image_count") or 0)
            scene_types = inputs.get("scene_types") if isinstance(inputs.get("scene_types"), list) else []
            return {
                **base,
                "asset_manifest": [
                    {
                        "asset_type": "image",
                        "url": "dry-run://media/image-placeholder",
                        "dimensions": inputs.get("image_sizes") or "pending",
                        "prompt": "pending_live_media_generation",
                        "provider": "fal_or_configured_media_provider",
                        "cost_estimate": "pending_quota_check",
                        "review_status": "needs_human_review_before_listing",
                    }
                    for _ in range(max(1, min(image_count, 3)))
                ],
                "scene_types": scene_types,
                "video_script_status": "received" if inputs.get("video_script") else "missing",
            }
        if key == "model.role_report_assist":
            return {
                **base,
                "merchant_readable_summary": "Dry-run role report packet is ready; production replaces this with a model response.",
                "sections": inputs.get("required_sections") if isinstance(inputs.get("required_sections"), list) else [],
                "limits": ["No live model call was made by the SaaS local worker."],
                "risk_flags": ["real platform writes remain blocked"],
            }
        return {**base, "records": [{"status": "dry_run_ready"}]}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _merchant_summary(*, contract: dict[str, Any], status: str, missing_inputs: list[str]) -> str:
    if status == "blocked_missing_input":
        return f"{contract.get('label')} cannot run yet. Missing: {', '.join(missing_inputs)}."
    return f"{contract.get('label')} passed the SaaS job contract dry-run. No live provider was called."


def _next_action(*, status: str, missing_inputs: list[str]) -> str:
    if status == "blocked_missing_input":
        return "Collect the missing inputs, then retry this queued provider job."
    return "Replace dry-run provider with the production adapter behind Vault/KMS, quota controls and audit logging."


def _redact_secret_like(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in SECRET_KEY_MARKERS):
                output[key] = "[REDACTED]"
            else:
                output[key] = _redact_secret_like(item)
        return output
    if isinstance(value, list):
        return [_redact_secret_like(item) for item in value]
    return value


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_tavily_results(*, payload: dict[str, Any], captured_at: str) -> list[dict[str, Any]]:
    raw_results = payload.get("results") if isinstance(payload.get("results"), list) else []
    records: list[dict[str, Any]] = []
    for item in raw_results[:10]:
        if not isinstance(item, dict):
            continue
        records.append(
            {
                "title": str(item.get("title") or "")[:300],
                "url": str(item.get("url") or "")[:1000],
                "snippet": str(item.get("content") or item.get("snippet") or "")[:1200],
                "source_type": "live_public_search",
                "provider": "tavily",
                "confidence": item.get("score") if item.get("score") is not None else "provider_ranked",
                "captured_at": captured_at,
            }
        )
    return records


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _urlopen_transport(request: urllib.request.Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        headers = {key: value for key, value in response.headers.items()}
        return int(response.status), headers, response.read()

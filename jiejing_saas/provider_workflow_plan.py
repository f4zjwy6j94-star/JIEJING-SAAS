"""Provider job preflight plan for a SaaS product workflow.

This turns workflow steps into a merchant-visible and backend-visible provider
execution plan. It does not enqueue work and does not call providers. Its job is
to make missing inputs and future tool boundaries explicit before real adapters
are connected.
"""

from __future__ import annotations

from typing import Any

from jiejing_runtime.media_capability_router import build_media_capability_router
from jiejing_runtime.provider_job_contracts import build_provider_job_contract_catalog


def build_provider_workflow_plan(
    *,
    task: dict[str, Any],
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    task_input = task.get("input") if isinstance(task.get("input"), dict) else {}
    catalog = build_provider_job_contract_catalog()
    contracts = {item["key"]: item for item in catalog.get("contracts", [])}
    provider_steps: list[dict[str, Any]] = []
    for step in steps:
        step_contract_keys = _step_provider_keys(step)
        for key in step_contract_keys:
            contract = contracts.get(key)
            if not contract:
                provider_steps.append(
                    {
                        "step_order": step.get("step_order"),
                        "task_type": step.get("task_type"),
                        "merchant_label": step.get("merchant_label"),
                        "provider_job_key": key,
                        "status": "blocked_unknown_contract",
                        "missing_inputs": [],
                        "queueable": False,
                        "secret_exposed": False,
                    }
                )
                continue
            inputs = _derive_provider_inputs(contract_key=key, step=step, task=task, task_input=task_input)
            missing_inputs = [
                name
                for name in contract.get("required_inputs", [])
                if _is_missing(inputs.get(str(name)))
            ]
            provider_steps.append(
                {
                    "step_order": step.get("step_order"),
                    "task_type": step.get("task_type"),
                    "role_key": step.get("role_key"),
                    "merchant_label": step.get("merchant_label"),
                    "provider_job_key": key,
                    "provider_family": contract.get("provider_family"),
                    "label": contract.get("label"),
                    "queue": contract.get("queue"),
                    "timeout_seconds": contract.get("timeout_seconds"),
                    "max_attempts": contract.get("max_attempts"),
                    "status": "ready_to_queue" if not missing_inputs else "blocked_missing_input",
                    "queueable": not missing_inputs,
                    "required_secret_purpose": contract.get("required_secret_purpose"),
                    "secret_ref_required": bool(contract.get("required_secret_purpose")),
                    "required_inputs": list(contract.get("required_inputs", [])),
                    "prepared_inputs": _redact_secret_like(inputs),
                    "missing_inputs": missing_inputs,
                    "output_packet": contract.get("output_packet"),
                    "source_record_type": contract.get("source_record_type"),
                    "blocked_actions": list(contract.get("blocked_actions", [])),
                    "real_execution_allowed": False,
                    "live_provider_called": False,
                    "secret_exposed": False,
                }
            )
    ready_count = sum(1 for item in provider_steps if item.get("status") == "ready_to_queue")
    blocked_count = sum(1 for item in provider_steps if item.get("status") != "ready_to_queue")
    provider_families = sorted({str(item.get("provider_family")) for item in provider_steps if item.get("provider_family")})
    return {
        "task_id": task.get("task_id"),
        "store_id": task.get("store_id"),
        "contract_version": catalog.get("contract_version"),
        "provider_step_count": len(provider_steps),
        "ready_to_queue_count": ready_count,
        "blocked_count": blocked_count,
        "provider_families": provider_families,
        "provider_steps": provider_steps,
        "summary": _summary(ready_count=ready_count, blocked_count=blocked_count, provider_steps=provider_steps),
        "queue_policy": {
            "provider_jobs_are_child_work_units": True,
            "do_not_overwrite_parent_product_workflow": True,
            "real_provider_calls_require_vault_and_adapter": True,
            "high_risk_actions_stay_confirmation_gated": True,
        },
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _step_provider_keys(step: dict[str, Any]) -> list[str]:
    if isinstance(step.get("provider_job_keys"), list):
        return [str(item) for item in step.get("provider_job_keys", []) if item]
    nested = step.get("step") if isinstance(step.get("step"), dict) else {}
    if isinstance(nested.get("provider_job_keys"), list):
        return [str(item) for item in nested.get("provider_job_keys", []) if item]
    return []


def _derive_provider_inputs(
    *,
    contract_key: str,
    step: dict[str, Any],
    task: dict[str, Any],
    task_input: dict[str, Any],
) -> dict[str, Any]:
    product = str(task_input.get("product") or task_input.get("product_context") or task.get("title") or "")
    merchant_goal = str(task_input.get("merchant_goal") or task.get("title") or "")
    merchant_profile = task_input.get("merchant_profile") if isinstance(task_input.get("merchant_profile"), dict) else {}
    market_probe = task_input.get("market_probe_inputs") if isinstance(task_input.get("market_probe_inputs"), dict) else {}
    supplier_facts = task_input.get("supplier_facts") if isinstance(task_input.get("supplier_facts"), dict) else {}
    package_dimensions = (
        supplier_facts.get("package_dimensions_cm")
        or supplier_facts.get("package_dimensions")
        or task_input.get("package_dimensions_cm")
    )
    marketplace = str(task_input.get("marketplace_id") or task_input.get("marketplace") or "EBAY_US")
    source_mode = str(task_input.get("source_mode") or merchant_profile.get("sourceApiMode") or "manual_or_1688")
    risk_filters = task_input.get("risk_filters") if isinstance(task_input.get("risk_filters"), dict) else {}
    if not risk_filters:
        risk_filters = {
            "risk_level": merchant_profile.get("riskLevel") or "balanced",
            "source_mode": source_mode,
        }

    if contract_key == "public_search.market_research":
        return {
            "query": product or merchant_goal,
            "marketplace": marketplace,
            "category_hint": task_input.get("category_hint") or market_probe.get("category_hint") or product,
        }
    if contract_key == "ebay.read_only_snapshot":
        return {
            "store_id": task.get("store_id"),
            "marketplace_id": marketplace,
            "resource_keys": _ebay_resources_for_step(str(step.get("task_type") or "")),
        }
    if contract_key == "sourcing.1688_availability":
        return {
            "product_keyword_or_url": task_input.get("source_url") or task_input.get("product_keyword_or_url") or product,
            "merchant_source_mode": source_mode,
            "risk_filters": risk_filters,
        }
    if contract_key == "logistics.orange_connex_quote":
        return {
            "origin": supplier_facts.get("ship_from") or supplier_facts.get("origin") or task_input.get("origin"),
            "destination": task_input.get("destination") or "US",
            "package_weight_g": supplier_facts.get("package_weight_g") or task_input.get("package_weight_g"),
            "package_dimensions_cm": package_dimensions,
            "service_hint": task_input.get("service_hint") or "SpeedPAK Economy",
        }
    if contract_key in {"media.asset_generation", "media.fal_asset_generation"}:
        router = build_media_capability_router(
            preferred_model_provider=str(task_input.get("model_provider") or task_input.get("ai_model_provider") or ""),
            media_provider=str(task_input.get("media_provider") or ""),
            image_provider_configured=False,
            video_provider_configured=False,
            voice_provider_configured=False,
        )
        return {
            "creative_job_spec": router.get("creative_job_spec"),
            "product_facts": {
                "product": product,
                "supplier_facts": supplier_facts,
                "listing_context": market_probe,
                "forbidden_claims": router.get("creative_job_spec", {}).get("blocked_claims", []),
            },
            "image_count": task_input.get("image_count") or 6,
            "image_sizes": task_input.get("image_sizes") or ["1:1", "4:5", "16:9"],
            "scene_types": task_input.get("scene_types") or ["white_background", "lifestyle_scene", "detail_page", "size_chart"],
            "video_script": task_input.get("video_script") or f"15-30 second eBay product demo for {product or 'this product'}",
        }
    if contract_key == "model.role_report_assist":
        return {
            "task_type": step.get("task_type"),
            "required_sections": step.get("required_sections") or (step.get("step") or {}).get("required_sections") or [],
            "sanitized_context": {
                "product": product,
                "merchant_goal": merchant_goal,
                "source_mode": source_mode,
                "market_probe_inputs": market_probe,
            },
            "merchant_goal": merchant_goal,
        }
    return {}


def _ebay_resources_for_step(task_type: str) -> list[str]:
    if task_type == "market.data_packet":
        return ["store_profile", "inventory_and_offers", "orders_and_fulfillment", "finances", "taxonomy_listing_metadata"]
    if task_type == "listing.package":
        return ["account_business_policies", "taxonomy_listing_metadata"]
    if task_type == "customer.learn_product":
        return ["inventory_and_offers", "orders_and_fulfillment", "account_business_policies"]
    return ["store_profile"]


def _summary(*, ready_count: int, blocked_count: int, provider_steps: list[dict[str, Any]]) -> str:
    if not provider_steps:
        return "No provider jobs are required for this task yet."
    if blocked_count:
        blocked_names = [
            f"{item.get('provider_job_key')} missing {', '.join(item.get('missing_inputs') or [])}"
            for item in provider_steps
            if item.get("missing_inputs")
        ]
        return f"{ready_count} provider jobs are ready; {blocked_count} are blocked by missing inputs: {'; '.join(blocked_names[:3])}."
    return f"All {ready_count} provider jobs are ready to queue in dry-run mode."


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _redact_secret_like(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("secret", "token", "password", "api_key", "apikey", "refresh", "authorization")):
                output[key] = "[REDACTED]"
            else:
                output[key] = _redact_secret_like(item)
        return output
    if isinstance(value, list):
        return [_redact_secret_like(item) for item in value]
    return value

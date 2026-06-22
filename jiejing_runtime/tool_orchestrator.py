"""Tool orchestration layer for Jiejing-owned Agent Runtime.

The owned agents should not call external providers ad hoc. This orchestrator
plans the tool slots for each commerce task, applies timeout/retry boundaries,
and returns a safe report payload that can be written back to the SaaS work
records.
"""

from __future__ import annotations

import concurrent.futures
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from .ebay_listing_metadata import EbayListingMetadataAdapter, EbayListingMetadataConfig
from .logistics_estimate import LogisticsEstimateAdapter, LogisticsEstimateConfig
from .market_data_packet import MarketDataPacketBuilder
from .media_generation import MediaGenerationAdapter, MediaGenerationConfig
from .models import JiejingTask
from .sourcing_availability import SourcingAvailabilityAdapter, SourcingAvailabilityConfig


@dataclass(slots=True)
class ToolPlan:
    name: str
    label: str
    timeout_seconds: int
    max_attempts: int
    runner: Callable[[], dict[str, Any]]


class JiejingToolOrchestrator:
    """Runs provider tools behind a uniform runtime boundary."""

    version = "2026-05-15.1"

    def execute_for_task(self, task: JiejingTask) -> dict[str, Any]:
        plans = self.plan_for_task(task)
        executions = [self._run_plan(plan, task) for plan in plans]
        return {
            "orchestrator": "jiejing-tool-orchestrator",
            "orchestrator_version": self.version,
            "task_type": task.task_type,
            "planned_count": len(plans),
            "executed_count": len(executions),
            "ready_count": len([item for item in executions if item.get("tool_status") in {"ready", "success"}]),
            "blocked_count": len([item for item in executions if self._is_blocked(item.get("tool_status"))]),
            "executions": executions,
            "secret_exposed": False,
            "real_execution_allowed": False,
        }

    def plan_for_task(self, task: JiejingTask) -> list[ToolPlan]:
        if task.task_type == "market.report" and self._has_any_probe(
            task,
            [
                "market_probe_inputs",
                "ebay_read_only_probe",
                "public_search_probe",
                "cross_platform_reference_probe",
                "sourcing_availability_probe",
                "logistics_estimate_probe",
            ],
        ):
            return [
                ToolPlan(
                    name="market_data_packet",
                    label="Market data packet",
                    timeout_seconds=self._timeout(task, 30),
                    max_attempts=self._attempts(task),
                    runner=lambda: MarketDataPacketBuilder().build(task),
                )
            ]
        if task.task_type == "source.match":
            probe_config = self._dict_input(task, "sourcing_availability_probe")
            if probe_config:
                return [
                    ToolPlan(
                        name="sourcing_availability",
                        label="Sourcing availability",
                        timeout_seconds=self._timeout(task, 20),
                        max_attempts=self._attempts(task),
                        runner=lambda: SourcingAvailabilityAdapter().probe(self._sourcing_config(task, probe_config)),
                    )
                ]
        if task.task_type == "listing.package":
            probe_config = self._dict_input(task, "listing_metadata_probe")
            if probe_config or self._env_enabled("JIEJING_EBAY_LISTING_METADATA_LIVE"):
                return [
                    ToolPlan(
                        name="ebay_listing_metadata",
                        label="eBay listing metadata",
                        timeout_seconds=self._timeout(task, 30),
                        max_attempts=self._attempts(task),
                        runner=lambda: EbayListingMetadataAdapter().probe(self._listing_metadata_config(task, probe_config)),
                    )
                ]
        if task.task_type == "asset.brief":
            probe_config = self._dict_input(task, "media_generation_probe")
            if probe_config or self._env_enabled("JIEJING_MEDIA_GENERATION_LIVE"):
                return [
                    ToolPlan(
                        name="media_generation",
                        label="Image/video generation manifest",
                        timeout_seconds=self._timeout(task, 45),
                        max_attempts=1,
                        runner=lambda: MediaGenerationAdapter().generate(self._media_generation_config(task, probe_config)),
                    )
                ]
        if task.task_type == "finance.review":
            probe_config = self._dict_input(task, "logistics_estimate_probe")
            if probe_config:
                return [
                    ToolPlan(
                        name="logistics_estimate",
                        label="Logistics estimate",
                        timeout_seconds=self._timeout(task, 20),
                        max_attempts=self._attempts(task),
                        runner=lambda: LogisticsEstimateAdapter().probe(self._logistics_config(task, probe_config)),
                    )
                ]
        return []

    def _run_plan(self, plan: ToolPlan, task: JiejingTask) -> dict[str, Any]:
        started = time.perf_counter()
        errors: list[str] = []
        output: dict[str, Any] = {}
        status = "failed_tool"
        for attempt in range(1, max(1, plan.max_attempts) + 1):
            try:
                output = self._run_with_timeout(plan.runner, plan.timeout_seconds)
                status = str(output.get("status") or "success")
                break
            except TimeoutError as exc:
                status = "timeout"
                errors.append(str(exc))
            except Exception as exc:  # pragma: no cover - provider dependent
                status = "failed_tool"
                errors.append(self._safe_error(exc))
        duration_ms = int((time.perf_counter() - started) * 1000)
        return {
            "tool_name": plan.name,
            "tool_label": plan.label,
            "task_type": task.task_type,
            "tool_status": status,
            "attempt_count": max(1, len(errors) + (1 if output else 0)),
            "max_attempts": plan.max_attempts,
            "timeout_seconds": plan.timeout_seconds,
            "duration_ms": duration_ms,
            "summary": self._safe_text(output.get("summary") or (errors[-1] if errors else "")),
            "output": self._safe_output(output),
            "errors": errors,
            "real_execution_allowed": False,
            "secret_exposed": False,
        }

    def _run_with_timeout(self, runner: Callable[[], dict[str, Any]], timeout_seconds: int) -> dict[str, Any]:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(runner)
        try:
            result = future.result(timeout=max(1, timeout_seconds))
            return result if isinstance(result, dict) else {"status": "failed_tool", "summary": "Tool returned non-object output."}
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"tool timed out after {timeout_seconds}s") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _sourcing_config(self, task: JiejingTask, probe_config: dict[str, Any]) -> SourcingAvailabilityConfig:
        return SourcingAvailabilityConfig(
            product=str(probe_config.get("product") or task.input.get("product") or "current product"),
            route=str(probe_config.get("route") or task.input.get("source_mode") or "manual_or_1688"),
            candidates=probe_config.get("candidates") if isinstance(probe_config.get("candidates"), list) else None,
        )

    def _listing_metadata_config(self, task: JiejingTask, probe_config: dict[str, Any]) -> EbayListingMetadataConfig:
        return EbayListingMetadataConfig(
            marketplace_id=str(probe_config.get("marketplace_id") or self._marketplace_id(str(task.input.get("marketplace") or "eBay US"))),
            category_id=str(probe_config.get("category_id") or task.input.get("category_id") or ""),
            category_tree_id=str(probe_config.get("category_tree_id") or "0"),
            base_url=str(probe_config.get("base_url") or "https://api.ebay.com"),
            access_token=str(probe_config.get("access_token")) if probe_config.get("access_token") else None,
            live_enabled=probe_config.get("live_enabled") is True,
            taxonomy_response=probe_config.get("taxonomy_response") if isinstance(probe_config.get("taxonomy_response"), dict) else None,
            fulfillment_policy_response=probe_config.get("fulfillment_policy_response")
            if isinstance(probe_config.get("fulfillment_policy_response"), dict)
            else None,
            payment_policy_response=probe_config.get("payment_policy_response") if isinstance(probe_config.get("payment_policy_response"), dict) else None,
            return_policy_response=probe_config.get("return_policy_response") if isinstance(probe_config.get("return_policy_response"), dict) else None,
            timeout_seconds=self._int(probe_config.get("timeout_seconds"), 20),
        )

    def _media_generation_config(self, task: JiejingTask, probe_config: dict[str, Any]) -> MediaGenerationConfig:
        product = str(probe_config.get("product") or task.input.get("product") or "current product")
        return MediaGenerationConfig(
            product=product,
            image_prompt=str(probe_config.get("image_prompt") or ""),
            video_prompt=str(probe_config.get("video_prompt") or ""),
            detail_page_prompt=str(probe_config.get("detail_page_prompt") or ""),
            image_count=self._int(probe_config.get("image_count"), 4),
            image_sizes=[
                str(item)
                for item in (
                    probe_config.get("image_sizes")
                    if isinstance(probe_config.get("image_sizes"), list)
                    else ["1600x1600", "1200x1600", "1200x3600"]
                )
            ],
            scene_types=[
                str(item)
                for item in (
                    probe_config.get("scene_types")
                    if isinstance(probe_config.get("scene_types"), list)
                    else ["main_white_bg", "lifestyle_scene", "detail_page", "dimension_image"]
                )
            ],
            asset_manifest=probe_config.get("asset_manifest") if isinstance(probe_config.get("asset_manifest"), dict) else None,
            live_enabled=probe_config.get("live_enabled") is True,
            provider=str(probe_config.get("provider") or ""),
            image_endpoint=str(probe_config.get("image_endpoint")) if probe_config.get("image_endpoint") else None,
            video_endpoint=str(probe_config.get("video_endpoint")) if probe_config.get("video_endpoint") else None,
            api_key=str(probe_config.get("api_key")) if probe_config.get("api_key") else None,
            proxy_url=str(probe_config.get("proxy_url")) if probe_config.get("proxy_url") else None,
            image_model=str(probe_config.get("image_model") or "openai/gpt-image-2"),
            video_model=str(probe_config.get("video_model") or "fal-ai/wan-i2v"),
            reference_image_url=str(probe_config.get("reference_image_url") or ""),
            timeout_seconds=self._int(probe_config.get("timeout_seconds"), 45),
        )

    def _logistics_config(self, task: JiejingTask, probe_config: dict[str, Any]) -> LogisticsEstimateConfig:
        return LogisticsEstimateConfig(
            product=str(probe_config.get("product") or task.input.get("product") or "current product"),
            origin=str(probe_config.get("origin") or "China"),
            destination=str(probe_config.get("destination") or "United States"),
            package_weight_g=self._number(probe_config.get("package_weight_g") or probe_config.get("weight_g")),
            package_dimensions_cm=str(probe_config.get("package_dimensions_cm") or probe_config.get("dimensions_cm") or ""),
            route=str(probe_config.get("route") or "SpeedPAK/Orange Connex estimate"),
            estimates=probe_config.get("estimates") if isinstance(probe_config.get("estimates"), list) else None,
        )

    def _safe_output(self, output: dict[str, Any]) -> dict[str, Any]:
        if not output:
            return {}
        blocked_keys = {"access_token", "refresh_token", "api_key", "client_secret", "authorization", "cookie"}
        return self._redact(output, blocked_keys)

    def _redact(self, value: Any, blocked_keys: set[str]) -> Any:
        if isinstance(value, dict):
            clean = {}
            for key, item in value.items():
                if str(key).lower() in blocked_keys:
                    clean[key] = "[REDACTED]"
                else:
                    clean[key] = self._redact(item, blocked_keys)
            return clean
        if isinstance(value, list):
            return [self._redact(item, blocked_keys) for item in value]
        if isinstance(value, str):
            return self._safe_text(value)
        return value

    def _safe_text(self, value: Any) -> str:
        text = str(value or "")
        if len(text) > 1000:
            return text[:997] + "..."
        return text

    def _safe_error(self, exc: Exception) -> str:
        text = str(exc)
        for marker in ["access_token", "refresh_token", "api_key", "client_secret", "authorization", "cookie"]:
            text = text.replace(marker, "[REDACTED_FIELD]")
        return text[:500]

    def _has_any_probe(self, task: JiejingTask, keys: list[str]) -> bool:
        return any(bool(self._dict_input(task, key)) for key in keys)

    def _dict_input(self, task: JiejingTask, key: str) -> dict[str, Any]:
        value = task.input.get(key)
        return value if isinstance(value, dict) else {}

    def _timeout(self, task: JiejingTask, fallback: int) -> int:
        return min(self._int(task.timeout_seconds, fallback), fallback)

    def _attempts(self, task: JiejingTask) -> int:
        retry = task.raw.get("retry_policy", {}) if isinstance(task.raw.get("retry_policy"), dict) else {}
        return max(1, min(2, self._int(retry.get("max_retries"), 1) + 1))

    def _marketplace_id(self, marketplace: str) -> str:
        value = marketplace.strip().lower().replace("-", "_")
        mapping = {
            "ebay us": "EBAY_US",
            "us": "EBAY_US",
            "united states": "EBAY_US",
            "ebay uk": "EBAY_GB",
            "uk": "EBAY_GB",
            "ebay au": "EBAY_AU",
            "australia": "EBAY_AU",
        }
        return mapping.get(value, "EBAY_US")

    def _is_blocked(self, status: Any) -> bool:
        text = str(status or "").lower()
        return any(marker in text for marker in ["blocked", "missing", "pending", "failed", "timeout"])

    def _env_enabled(self, name: str) -> bool:
        return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}

    def _int(self, value: Any, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    def _number(self, value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return int(number) if number.is_integer() else number

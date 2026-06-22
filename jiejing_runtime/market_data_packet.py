"""Market data packet builder for the Jiejing Runtime.

This module keeps market-data collection as a controlled Runtime step instead
of asking one Hermes role to do open-ended research, browsing, sourcing, and
judgement in a single prompt.
"""

from __future__ import annotations

import os
import hashlib
from dataclasses import dataclass
from typing import Any

from .cross_platform_reference import CrossPlatformReferenceAdapter, CrossPlatformReferenceConfig
from .ebay_read_only import EbayReadOnlyProbeAdapter, EbayReadOnlyProbeConfig
from .logistics_estimate import LogisticsEstimateAdapter, LogisticsEstimateConfig
from .models import JiejingTask, now_iso
from .public_search import PublicSearchProbeAdapter, PublicSearchProbeConfig
from .sourcing_availability import SourcingAvailabilityAdapter, SourcingAvailabilityConfig


@dataclass(slots=True)
class ProbeResult:
    key: str
    label: str
    status: str
    source_type: str
    confidence: str
    summary: str
    next_action: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "source_type": self.source_type,
            "confidence": self.confidence,
            "summary": self.summary,
            "next_action": self.next_action,
        }


class MarketDataPacketBuilder:
    """Builds a merchant-readable market data packet without real writes."""

    version = "0.1.0"

    def build(self, task: JiejingTask) -> dict[str, Any]:
        product = str(task.input.get("product") or task.context.get("sample_name") or "current product")
        marketplace = str(task.input.get("marketplace") or "eBay US")
        source_mode = str(task.input.get("source_mode") or "manual_or_1688")
        probe_inputs = task.input.get("market_probe_inputs")
        probe_inputs = probe_inputs if isinstance(probe_inputs, dict) else {}
        ebay_probe_config = task.input.get("ebay_read_only_probe")
        ebay_probe_config = ebay_probe_config if isinstance(ebay_probe_config, dict) else {}
        public_probe_config = task.input.get("public_search_probe")
        public_probe_config = public_probe_config if isinstance(public_probe_config, dict) else {}
        cross_platform_probe_config = task.input.get("cross_platform_reference_probe")
        cross_platform_probe_config = cross_platform_probe_config if isinstance(cross_platform_probe_config, dict) else {}
        sourcing_probe_config = task.input.get("sourcing_availability_probe")
        sourcing_probe_config = sourcing_probe_config if isinstance(sourcing_probe_config, dict) else {}
        logistics_probe_config = task.input.get("logistics_estimate_probe")
        logistics_probe_config = logistics_probe_config if isinstance(logistics_probe_config, dict) else {}
        if not ebay_probe_config and self._env_enabled("JIEJING_EBAY_READ_LIVE"):
            ebay_probe_config = {"live_enabled": True, "keyword": product, "category_id": task.input.get("category_id")}
        if not public_probe_config and self._env_enabled("JIEJING_SEARCH_LIVE"):
            public_probe_config = {
                "live_enabled": True,
                "provider": os.environ.get("JIEJING_SEARCH_PROVIDER") or "snapshot",
                "query": f"{product} {marketplace} eBay price reviews supplier",
            }
        if "ebay_read_only" not in probe_inputs and ebay_probe_config:
            probe_inputs = dict(probe_inputs)
            probe_inputs["ebay_read_only"] = self._run_ebay_probe(product, marketplace, ebay_probe_config)
        if "public_search" not in probe_inputs and public_probe_config:
            probe_inputs = dict(probe_inputs)
            probe_inputs["public_search"] = self._run_public_search_probe(product, marketplace, public_probe_config)
        if "cross_platform_reference" not in probe_inputs and cross_platform_probe_config:
            probe_inputs = dict(probe_inputs)
            probe_inputs["cross_platform_reference"] = self._run_cross_platform_reference_probe(product, cross_platform_probe_config)
        if "sourcing_availability" not in probe_inputs and sourcing_probe_config:
            probe_inputs = dict(probe_inputs)
            probe_inputs["sourcing_availability"] = self._run_sourcing_availability_probe(product, source_mode, sourcing_probe_config)
        if "logistics_estimate" not in probe_inputs and logistics_probe_config:
            probe_inputs = dict(probe_inputs)
            probe_inputs["logistics_estimate"] = self._run_logistics_estimate_probe(product, logistics_probe_config)
        probes = self._probes(product, marketplace, source_mode, probe_inputs)
        captured_at = now_iso()
        missing_inputs = self._missing_inputs(probes)
        status = "blocked_missing_input" if missing_inputs else "success"
        return {
            "status": status,
            "summary": self._summary(product, marketplace, probes),
            "report": {
                "mode": "market_data_packet",
                "packet_version": self.version,
                "product": product,
                "marketplace": marketplace,
                "source_mode": source_mode,
                "manual_or_adapter_inputs": sorted(probe_inputs),
                "adapter_probe_inputs": sorted(
                    key
                    for key, value in {
                        "ebay_read_only_probe": ebay_probe_config,
                        "public_search_probe": public_probe_config,
                        "cross_platform_reference_probe": cross_platform_probe_config,
                        "sourcing_availability_probe": sourcing_probe_config,
                        "logistics_estimate_probe": logistics_probe_config,
                    }.items()
                    if value
                ),
                "required_sections": task.output_contract.get("required_sections", []),
                "sections": {
                    "source_health": self._source_health(probes),
                    "ebay_signal": self._probe_section(probes, "ebay_read_only", probe_inputs),
                    "public_search_signal": self._probe_section(probes, "public_search", probe_inputs),
                    "cross_platform_reference": self._probe_section(probes, "cross_platform_reference", probe_inputs),
                    "source_availability": self._probe_section(probes, "sourcing_availability", probe_inputs),
                    "logistics_signal": self._probe_section(probes, "logistics_estimate", probe_inputs),
                    "source_records": self._source_records(probes, probe_inputs, captured_at),
                    "unavailable_sources": [probe.to_dict() for probe in probes if probe.status != "ready"],
                    "handoff_to_market_manager": self._handoff(product, marketplace),
                },
                "probes": [probe.to_dict() for probe in probes],
            },
            "source_records": self._source_records(probes, probe_inputs, captured_at),
            "missing_inputs": missing_inputs,
            "risk_flags": self._risk_flags(probes),
        }

    def _probes(self, product: str, marketplace: str, source_mode: str, probe_inputs: dict[str, Any]) -> list[ProbeResult]:
        ebay = self._snapshot(probe_inputs, "ebay_read_only")
        public = self._snapshot(probe_inputs, "public_search")
        cross_platform = self._snapshot(probe_inputs, "cross_platform_reference")
        sourcing = self._snapshot(probe_inputs, "sourcing_availability")
        logistics = self._snapshot(probe_inputs, "logistics_estimate")
        return [
            ProbeResult(
                key="ebay_read_only",
                label=f"{marketplace} read-only market signal",
                status=self._status_from_snapshot(ebay, "pending_connector"),
                source_type=self._source_type(ebay, "restricted_unavailable"),
                confidence=self._confidence(ebay, "low"),
                summary=self._summary_from_snapshot(
                    ebay,
                    "No live eBay read-only market probe ran in this Runtime mode. "
                    "Do not treat listing count, sold signal, price band, or competitor rank as official yet.",
                ),
                next_action="Connect eBay read-only/Browse/Taxonomy-capable probe or provide exported listing samples.",
            ),
            ProbeResult(
                key="public_search",
                label="Public web search signal",
                status=self._status_from_snapshot(public, "pending_tool"),
                source_type=self._source_type(public, "restricted_unavailable"),
                confidence=self._confidence(public, "low"),
                summary=self._summary_from_snapshot(
                    public,
                    "Public search was not executed here. Runtime has defined the slot but still needs a search provider "
                    "or browser worker to collect public pages safely.",
                ),
                next_action="Run search-provider or browser worker queries, then save URLs, titles, snippets, and timestamps.",
            ),
            ProbeResult(
                key="cross_platform_reference",
                label="Cross-platform public reference",
                status=self._status_from_snapshot(cross_platform, "pending_tool"),
                source_type=self._source_type(cross_platform, "restricted_unavailable"),
                confidence=self._confidence(cross_platform, "low"),
                summary=self._summary_from_snapshot(
                    cross_platform,
                    "Amazon, 1688, Taobao, Pinduoduo, Shopify, and similar references are not internal platform data unless "
                    "authorized. They must be labeled as public reference or merchant-provided data.",
                ),
                next_action="Collect only public or authorized reference pages and keep platform limits visible.",
            ),
            ProbeResult(
                key="sourcing_availability",
                label="Sourcing availability",
                status=self._status_from_snapshot(sourcing, "pending_connector" if "1688" in source_mode else "pending_manual_input"),
                source_type=self._source_type(sourcing, "manual_input"),
                confidence=self._confidence(sourcing, "medium" if "1688" in source_mode else "low"),
                summary=self._summary_from_snapshot(
                    sourcing,
                    f"Source route is `{source_mode}`. Runtime can continue with manual links, image/table input, or an authorized "
                    "source connector, but it has not verified supplier price, MOQ, origin, stock, or packaging yet.",
                ),
                next_action="Provide 1688 link/image/table or connect an authorized sourcing read connector.",
            ),
            ProbeResult(
                key="logistics_estimate",
                label="Logistics and package signal",
                status=self._status_from_snapshot(logistics, "pending_facts"),
                source_type=self._source_type(logistics, "tool_estimate"),
                confidence=self._confidence(logistics, "low"),
                summary=self._summary_from_snapshot(
                    logistics,
                    "No verified package weight, dimensions, SpeedPAK/Orange Connex route, fuel surcharge, or tracking promise "
                    "was calculated in this step.",
                ),
                next_action="Add confirmed package weight, dimensions, ship-from city, destination, and logistics service level.",
            ),
        ]

    def _run_ebay_probe(self, product: str, marketplace: str, probe_config: dict[str, Any]) -> dict[str, Any]:
        adapter = EbayReadOnlyProbeAdapter()
        browse_response = probe_config.get("browse_response")
        taxonomy_response = probe_config.get("taxonomy_response")
        keyword = str(probe_config.get("keyword") or product)
        marketplace_id = str(probe_config.get("marketplace_id") or self._marketplace_id(marketplace))
        if isinstance(browse_response, dict):
            return adapter.snapshot_from_responses(
                keyword=keyword,
                marketplace_id=marketplace_id,
                browse_response=browse_response,
                taxonomy_response=taxonomy_response if isinstance(taxonomy_response, dict) else None,
            )
        return adapter.probe(
            EbayReadOnlyProbeConfig(
                keyword=keyword,
                marketplace_id=marketplace_id,
                limit=self._int(probe_config.get("limit"), 10),
                category_id=str(probe_config.get("category_id")) if probe_config.get("category_id") else None,
                category_tree_id=str(probe_config.get("category_tree_id") or "0"),
                base_url=str(probe_config.get("base_url") or "https://api.ebay.com"),
                access_token=str(probe_config.get("access_token")) if probe_config.get("access_token") else None,
                live_enabled=probe_config.get("live_enabled") is True,
                timeout_seconds=self._int(probe_config.get("timeout_seconds"), 20),
            )
        )

    def _run_public_search_probe(self, product: str, marketplace: str, probe_config: dict[str, Any]) -> dict[str, Any]:
        adapter = PublicSearchProbeAdapter()
        results = probe_config.get("results")
        return adapter.probe(
            PublicSearchProbeConfig(
                query=str(probe_config.get("query") or f"{product} {marketplace} eBay price reviews supplier"),
                provider=str(probe_config.get("provider") or "snapshot"),
                marketplace_context=marketplace,
                results=results if isinstance(results, list) else None,
                endpoint=str(probe_config.get("endpoint")) if probe_config.get("endpoint") else None,
                api_key=str(probe_config.get("api_key")) if probe_config.get("api_key") else None,
                live_enabled=probe_config.get("live_enabled") is True,
                timeout_seconds=self._int(probe_config.get("timeout_seconds"), 20),
                max_results=self._int(probe_config.get("max_results"), 8),
                search_depth=str(probe_config.get("search_depth") or "basic"),
                include_images=probe_config.get("include_images") is True,
                country=str(probe_config.get("country")) if probe_config.get("country") else None,
            )
        )

    def _run_cross_platform_reference_probe(self, product: str, probe_config: dict[str, Any]) -> dict[str, Any]:
        adapter = CrossPlatformReferenceAdapter()
        references = probe_config.get("references")
        return adapter.probe(
            CrossPlatformReferenceConfig(
                product=str(probe_config.get("product") or product),
                references=references if isinstance(references, list) else None,
                context=str(probe_config.get("context") or "market.data_packet"),
            )
        )

    def _run_sourcing_availability_probe(self, product: str, source_mode: str, probe_config: dict[str, Any]) -> dict[str, Any]:
        adapter = SourcingAvailabilityAdapter()
        candidates = probe_config.get("candidates")
        return adapter.probe(
            SourcingAvailabilityConfig(
                product=str(probe_config.get("product") or product),
                route=str(probe_config.get("route") or source_mode),
                candidates=candidates if isinstance(candidates, list) else None,
            )
        )

    def _run_logistics_estimate_probe(self, product: str, probe_config: dict[str, Any]) -> dict[str, Any]:
        adapter = LogisticsEstimateAdapter()
        estimates = probe_config.get("estimates")
        return adapter.probe(
            LogisticsEstimateConfig(
                product=str(probe_config.get("product") or product),
                origin=str(probe_config.get("origin") or "China"),
                destination=str(probe_config.get("destination") or "United States"),
                package_weight_g=self._number_or_none(probe_config.get("package_weight_g")),
                package_dimensions_cm=str(probe_config.get("package_dimensions_cm") or ""),
                route=str(probe_config.get("route") or "SpeedPAK/Orange Connex estimate"),
                estimates=estimates if isinstance(estimates, list) else None,
            )
        )

    def _marketplace_id(self, marketplace: str) -> str:
        normalized = marketplace.strip().upper().replace(" ", "_").replace("-", "_")
        if normalized in {"EBAY_US", "EBAY_GB", "EBAY_DE", "EBAY_AU", "EBAY_CA"}:
            return normalized
        if normalized in {"US", "EBAYUS"}:
            return "EBAY_US"
        return "EBAY_US"

    def _int(self, value: Any, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    def _env_enabled(self, name: str) -> bool:
        return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}

    def _number_or_none(self, value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _snapshot(self, probe_inputs: dict[str, Any], key: str) -> dict[str, Any]:
        value = probe_inputs.get(key)
        return value if isinstance(value, dict) else {}

    def _source_type(self, snapshot: dict[str, Any], fallback: str) -> str:
        return str(snapshot.get("source_type") or fallback)

    def _status_from_snapshot(self, snapshot: dict[str, Any], empty_fallback: str) -> str:
        if not snapshot:
            return empty_fallback
        status = str(snapshot.get("status") or "").strip()
        if status:
            return status
        return "ready"

    def _confidence(self, snapshot: dict[str, Any], fallback: str) -> str:
        value = str(snapshot.get("confidence") or fallback)
        return value if value in {"low", "medium", "high"} else fallback

    def _summary_from_snapshot(self, snapshot: dict[str, Any], fallback: str) -> str:
        if not snapshot:
            return fallback
        summary = str(snapshot.get("summary") or "").strip()
        if summary:
            return summary
        metrics = snapshot.get("metrics")
        if isinstance(metrics, dict) and metrics:
            return "Snapshot supplied with metrics: " + ", ".join(f"{key}={value}" for key, value in metrics.items())
        return "Snapshot supplied by Runtime input or a future read-only adapter."

    def _summary(self, product: str, marketplace: str, probes: list[ProbeResult]) -> str:
        ready = len([probe for probe in probes if probe.status == "ready"])
        pending = len(probes) - ready
        return (
            f"Market data packet for {product} on {marketplace} is structured, but {pending} data probes still need "
            "live tools, authorized connectors, or merchant input before the market report can be treated as source-backed."
        )

    def _source_health(self, probes: list[ProbeResult]) -> dict[str, Any]:
        return {
            "ready_count": len([probe for probe in probes if probe.status == "ready"]),
            "pending_count": len([probe for probe in probes if probe.status != "ready"]),
            "overall_confidence": "low" if any(probe.confidence == "low" for probe in probes) else "medium",
            "items": [probe.to_dict() for probe in probes],
        }

    def _probe_section(self, probes: list[ProbeResult], key: str, probe_inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        for probe in probes:
            if probe.key == key:
                section: dict[str, Any] = probe.to_dict()
                snapshot = self._snapshot(probe_inputs or {}, key)
                if isinstance(snapshot.get("metrics"), dict):
                    section["metrics"] = snapshot["metrics"]
                if isinstance(snapshot.get("results"), list):
                    section["results"] = snapshot["results"][:10]
                if isinstance(snapshot.get("source_records"), list):
                    section["source_records"] = snapshot["source_records"][:10]
                return section
        return {
            "key": key,
            "label": key,
            "status": "missing",
            "source_type": "restricted_unavailable",
            "confidence": "low",
            "summary": "Probe was not configured.",
            "next_action": "Add probe configuration.",
        }

    def _source_records(self, probes: list[ProbeResult], probe_inputs: dict[str, Any], captured_at: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for probe in probes:
            records.append(
                {
                    "source_id": f"src_market_packet_{probe.key}",
                    "source_type": probe.source_type,
                    "title": probe.label,
                    "url": None,
                    "captured_at": captured_at,
                    "confidence": probe.confidence,
                    "used_for": ["market.data_packet"],
                    "note": probe.summary,
                }
            )
        public = self._snapshot(probe_inputs, "public_search")
        supplied_records = public.get("source_records") if isinstance(public.get("source_records"), list) else []
        for index, item in enumerate(supplied_records, start=1):
            if not isinstance(item, dict):
                continue
            records.append(self._public_source_record(item=item, index=index, captured_at=captured_at))
        if not supplied_records:
            public_results = public.get("results") if isinstance(public.get("results"), list) else []
            for index, item in enumerate(public_results[:10], start=1):
                if not isinstance(item, dict):
                    continue
                records.append(self._public_source_record(item=item, index=index, captured_at=captured_at))
        return records

    def _public_source_record(self, *, item: dict[str, Any], index: int, captured_at: str) -> dict[str, Any]:
        title = str(item.get("title") or f"Public search source {index}").strip()[:300]
        url = str(item.get("url") or "").strip()[:1000]
        note = str(item.get("note") or item.get("snippet") or item.get("summary") or "").strip()[:1200]
        source_type = str(item.get("source_type") or "public_page")
        if source_type not in {"public_page", "ai_inference", "merchant_provided", "restricted_unavailable"}:
            source_type = "public_page"
        digest = hashlib.sha1(f"{url}|{title}|{index}".encode("utf-8", errors="ignore")).hexdigest()[:12]
        return {
            "source_id": str(item.get("source_id") or f"src_market_packet_public_search_{digest}"),
            "source_type": source_type,
            "title": title,
            "url": url or None,
            "captured_at": str(item.get("captured_at") or captured_at),
            "confidence": str(item.get("confidence") or "medium"),
            "used_for": ["market.data_packet", "market.report"],
            "note": note,
            "provider_source_type": item.get("provider_source_type") or item.get("source_mode"),
            "raw_provider_response_stored": False,
            "secret_exposed": False,
        }

    def _handoff(self, product: str, marketplace: str) -> dict[str, str]:
        return {
            "target_role": "market-manager",
            "instruction": (
                f"Do not perform open-ended collection. Use the market data packet for {product} on {marketplace}; "
                "write only the judgement, label source gaps, and keep missing data as blocking."
            ),
            "allowed_next_status": "blocked_missing_input until live eBay/source/logistics facts are available",
        }

    def _missing_inputs(self, probes: list[ProbeResult]) -> list[dict[str, str]]:
        mapping = {
            "ebay_read_only": "live_market_data",
            "public_search": "public_search_results",
            "cross_platform_reference": "cross_platform_reference",
            "sourcing_availability": "supplier_or_source_candidates",
            "logistics_estimate": "logistics_quote",
        }
        return [
            {
                "input_id": mapping.get(probe.key, probe.key),
                "reason": probe.next_action,
                "severity": "blocking" if probe.key in {"ebay_read_only", "sourcing_availability"} else "warning",
            }
            for probe in probes
            if probe.status != "ready"
        ]

    def _risk_flags(self, probes: list[ProbeResult]) -> list[dict[str, str]]:
        risks = []
        if any(probe.key == "ebay_read_only" and probe.status != "ready" for probe in probes):
            risks.append(
                {
                    "risk_id": "market_report_not_source_backed",
                    "severity": "high",
                    "message": "Market report must not be treated as source-backed until eBay read-only market signal is available.",
                }
            )
        if any(probe.key == "sourcing_availability" and probe.status != "ready" for probe in probes):
            risks.append(
                {
                    "risk_id": "source_availability_unverified",
                    "severity": "high",
                    "message": "Sourcing availability, purchase cost, stock, origin, and packaging are not verified.",
                }
            )
        return risks

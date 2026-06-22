"""Bridge from the SaaS backend boundary to the Jiejing Runtime."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jiejing_runtime import JiejingRuntime, RuntimeConfig, SQLiteRuntimeRepository
from jiejing_runtime.saas_snapshot import build_saas_snapshot
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow


class RuntimeBridge:
    """Runs low-risk Jiejing Runtime workflows behind the SaaS backend.

    This is intentionally not a direct front-end boundary. The SaaS backend owns
    user identity, store permission, report persistence, confirmation decisions,
    and execution gates before/after this bridge.
    """

    def __init__(self, *, runtime_db_path: Path, output_root: Path, allow_hermes_adapters: bool = False) -> None:
        self.runtime_repo = SQLiteRuntimeRepository(runtime_db_path)
        self.output_root = output_root
        self.allow_hermes_adapters = allow_hermes_adapters

    def run_product_workflow(
        self,
        *,
        task_id: str,
        user_id: str,
        company_id: str,
        store_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        adapter = str(body.get("adapter") or "jiejing-local")
        allowed_adapters = {"mock", "jiejing-local", "jiejing-llm", "jiejing-deepseek"}
        if self.allow_hermes_adapters:
            allowed_adapters.update({"hermes-plan", "hermes-shadow", "hermes-file"})
        if adapter not in allowed_adapters:
            raise ValueError(f"unsupported runtime adapter: {adapter}")
        run_id = str(body.get("run_id") or f"saas-{_safe_id(body.get('product') or 'product')}-{_stamp()}")
        output_dir = self.output_root / "runtime-runs" / run_id
        request = ProductWorkflowRequest(
            product=str(body.get("product") or "Untitled eBay product"),
            merchant_goal=str(body.get("merchant_goal") or "Run a Jiejing eBay product workflow."),
            project_id=run_id,
            stage=str(body.get("stage") or "store_opened"),
            platform=str(body.get("platform") or "ebay"),
            user_id=user_id,
            company_id=company_id,
            store_id=store_id,
            marketplace=str(body.get("marketplace") or "eBay US"),
            source_mode=str(body.get("source_mode") or "manual_or_1688"),
            notes=str(body.get("notes") or ""),
            market_probe_inputs=body.get("market_probe_inputs") if isinstance(body.get("market_probe_inputs"), dict) else None,
            ebay_read_only_probe=body.get("ebay_read_only_probe") if isinstance(body.get("ebay_read_only_probe"), dict) else None,
            public_search_probe=body.get("public_search_probe") if isinstance(body.get("public_search_probe"), dict) else None,
            cross_platform_reference_probe=body.get("cross_platform_reference_probe")
            if isinstance(body.get("cross_platform_reference_probe"), dict)
            else None,
            sourcing_availability_probe=body.get("sourcing_availability_probe")
            if isinstance(body.get("sourcing_availability_probe"), dict)
            else None,
            logistics_estimate_probe=body.get("logistics_estimate_probe") if isinstance(body.get("logistics_estimate_probe"), dict) else None,
            listing_metadata_probe=body.get("listing_metadata_probe") if isinstance(body.get("listing_metadata_probe"), dict) else None,
            media_generation_probe=body.get("media_generation_probe") if isinstance(body.get("media_generation_probe"), dict) else None,
            merchant_profile=body.get("merchant_profile") if isinstance(body.get("merchant_profile"), dict) else None,
        )
        runtime = JiejingRuntime(
            RuntimeConfig(
                adapter_name=adapter,
                demo_mode=True,
                stop_on_failure=False,
                clean_output=True,
            )
        )
        summary = runtime.run_tasks(build_product_workflow(request), output_dir, run_id=run_id)
        imported = self.runtime_repo.save_run_directory(summary.run_dir)
        run = self.runtime_repo.get_run(imported["run_id"])
        results = self.runtime_repo.get_results(imported["run_id"])
        confirmations = self.runtime_repo.get_confirmations(imported["run_id"])
        validation_summary = self.runtime_repo.get_validation_summary(imported["run_id"])
        snapshot = build_saas_snapshot(
            run=run,
            results=results,
            confirmations=confirmations,
            validation_summary=validation_summary,
        )
        return {
            "task_id": task_id,
            "run": run,
            "run_id": imported["run_id"],
            "imported": imported,
            "results": results,
            "confirmations": confirmations,
            "validation_summary": validation_summary,
            "saas_snapshot": snapshot,
            "runtime_output_dir": str(summary.run_dir),
            "runtime_independent_from_hermes": adapter not in {"hermes-plan", "hermes-shadow", "hermes-file"},
            "real_execution_allowed": False,
        }


def _safe_id(value: object) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", str(value).strip().lower()).strip("-")
    return normalized[:40] or "product"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

"""Local HTTP API for the Jiejing Runtime MVP.

This is a dependency-free development server, not the final production backend.
It proves the SaaS front end can query runs, task results, confirmations, audit
events, and tool capability metadata through an API boundary.
"""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timezone

from .runtime import JiejingRuntime, RuntimeConfig
from .agent_team import JiejingAgentTeam
from .repository import SQLiteRuntimeRepository
from .tools_registry import ToolRegistry
from .knowledge import load_default_knowledge_base
from .workflow_templates import ProductWorkflowRequest, build_product_workflow
from .capabilities import RuntimeCapabilityProfile
from .role_capabilities import RuntimeRoleCapabilityMap
from .model_clients import model_client_status_from_env
from .public_search import PublicSearchProbeAdapter
from .media_generation import MediaGenerationAdapter
from .ebay_provider_status import EbayProviderStatus
from .merchant_profile import merchant_profile_defaults
from .saas_snapshot import build_saas_snapshot
from .creative_capabilities import CreativeCapabilityProfile
from .progress_scorecard import build_progress_scorecard
from .replacement_readiness import build_replacement_readiness
from .provider_job_contracts import build_provider_job_contract_catalog


class RuntimeApiServer:
    def __init__(self, db_path: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.db_path = db_path
        self.host = host
        self.port = port

    def serve_forever(self) -> None:
        repository = SQLiteRuntimeRepository(self.db_path)
        repository.initialize()
        tools = ToolRegistry()

        class Handler(RuntimeApiHandler):
            repo = repository
            tool_registry = tools

        server = ThreadingHTTPServer((self.host, self.port), Handler)
        print(f"Jiejing Runtime API listening on http://{self.host}:{self.port}")
        server.serve_forever()


class RuntimeApiHandler(BaseHTTPRequestHandler):
    repo: SQLiteRuntimeRepository
    tool_registry: ToolRegistry

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib API
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlparse(self.path)
        path = parsed.path.strip("/")
        parts = path.split("/") if path else []
        query = parse_qs(parsed.query)

        if path in {"", "health"}:
            self._send_json({"status": "ok", "service": "jiejing-runtime-api"})
            return

        if path == "tools":
            self._send_json({"tools": self.tool_registry.list_tools()})
            return

        if path == "knowledge":
            knowledge = load_default_knowledge_base()
            self._send_json({"knowledge": knowledge.summary()})
            return

        if path == "memories":
            limit = int(query.get("limit", ["80"])[0] or 80)
            self._send_json(
                {
                    "memory_summary": self.repo.get_memory_summary(),
                    "memories": self.repo.list_memories(
                        scope_type=query.get("scope_type", [None])[0],
                        role=query.get("role", [None])[0],
                        task_type=query.get("task_type", [None])[0],
                        product=query.get("product", [None])[0],
                        limit=limit,
                    ),
                }
            )
            return

        if path == "memories/summary":
            self._send_json({"memory_summary": self.repo.get_memory_summary()})
            return

        if path == "capabilities":
            self._send_json({"capability_profile": RuntimeCapabilityProfile(self.repo.db_path).to_dict()})
            return

        if path == "creative-capabilities":
            self._send_json({"creative_capability_profile": CreativeCapabilityProfile().to_dict()})
            return

        if path == "model-status":
            self._send_json({"model_status": model_client_status_from_env()})
            return

        if path == "provider-status":
            self._send_json(
                {
                    "model_status": model_client_status_from_env(),
                    "providers": {
                        "public_search_tavily": PublicSearchProbeAdapter().provider_status("tavily"),
                        "media_fal": MediaGenerationAdapter().provider_status("fal"),
                        "ebay": EbayProviderStatus().to_dict(),
                    },
                    "secret_exposed": False,
                }
            )
            return

        if path == "provider-job-contracts":
            self._send_json({"provider_job_contracts": build_provider_job_contract_catalog()})
            return

        if path == "progress-scorecard":
            self._send_json({"progress_scorecard": build_progress_scorecard(self.repo)})
            return

        if path == "replacement-readiness":
            self._send_json({"replacement_readiness": build_replacement_readiness(self.repo)})
            return

        if path == "merchant-profiles/defaults":
            self._send_json({"merchant_profiles": merchant_profile_defaults()})
            return

        if path == "role-capabilities":
            self._send_json({"role_capability_map": RuntimeRoleCapabilityMap().to_dict()})
            return

        if path == "agent-team":
            self._send_json({"owned_agent_team": JiejingAgentTeam().to_dict()})
            return

        if path == "agent-job-specs":
            team = JiejingAgentTeam().to_dict()
            self._send_json(
                {
                    "agent_job_specs": {
                        "version": team.get("version"),
                        "merchant_model": team.get("merchant_model"),
                        "role_count": team.get("role_count"),
                        "roles": team.get("roles", []),
                        "task_to_role": team.get("task_to_role", {}),
                        "real_execution_requires_confirmation": True,
                    },
                    "secret_exposed": False,
                }
            )
            return

        if path == "runs":
            self._send_json({"runs": self.repo.list_runs()})
            return

        if len(parts) >= 2 and parts[0] == "runs":
            run_id = parts[1]
            if len(parts) == 2:
                run = self.repo.get_run(run_id)
                if run is None:
                    self._send_error(HTTPStatus.NOT_FOUND, "run not found")
                    return
                self._send_json(run)
                return
            if len(parts) == 3 and parts[2] == "tasks":
                self._send_json({"run_id": run_id, "tasks": self.repo.get_tasks(run_id)})
                return
            if len(parts) == 3 and parts[2] == "results":
                self._send_json({"run_id": run_id, "results": self.repo.get_results(run_id)})
                return
            if len(parts) == 3 and parts[2] == "validation-summary":
                self._send_json(self.repo.get_validation_summary(run_id))
                return
            if len(parts) == 3 and parts[2] == "confirmations":
                self._send_json({"run_id": run_id, "confirmations": self.repo.get_confirmations(run_id)})
                return
            if len(parts) == 3 and parts[2] == "confirmation-decisions":
                self._send_json({"run_id": run_id, "decisions": self.repo.get_confirmation_decisions(run_id)})
                return
            if len(parts) == 3 and parts[2] == "execution-results":
                self._send_json({"run_id": run_id, "execution_results": self.repo.get_execution_results(run_id)})
                return
            if len(parts) == 3 and parts[2] == "audit":
                self._send_json({"run_id": run_id, "audit_events": self.repo.get_audit_events(run_id)})
                return
            if len(parts) == 3 and parts[2] == "saas-snapshot":
                run = self.repo.get_run(run_id)
                if run is None:
                    self._send_error(HTTPStatus.NOT_FOUND, "run not found")
                    return
                snapshot = build_saas_snapshot(
                    run=run,
                    results=self.repo.get_results(run_id),
                    confirmations=self.repo.get_confirmations(run_id),
                    validation_summary=self.repo.get_validation_summary(run_id),
                )
                self._send_json({"run_id": run_id, "saas_snapshot": snapshot})
                return

        if path == "confirmations":
            run_id = query.get("run_id", [""])[0]
            if not run_id:
                self._send_error(HTTPStatus.BAD_REQUEST, "run_id is required")
                return
            self._send_json({"run_id": run_id, "confirmations": self.repo.get_confirmations(run_id)})
            return

        self._send_error(HTTPStatus.NOT_FOUND, "endpoint not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/") if parsed.path.strip("/") else []
        if len(parts) == 1 and parts[0] == "runs":
            body = self._read_json_body()
            tasks_dir = Path(str(body.get("tasks_dir", ""))).resolve()
            output_dir = Path(str(body.get("output_dir", ""))).resolve()
            adapter = str(body.get("adapter", "jiejing-local"))
            run_id = body.get("run_id")
            if not tasks_dir.exists():
                self._send_error(HTTPStatus.BAD_REQUEST, "tasks_dir does not exist")
                return
            task_files = sorted(tasks_dir.glob("*.json"))
            if not task_files:
                self._send_error(HTTPStatus.BAD_REQUEST, "tasks_dir has no json task files")
                return
            try:
                runtime = JiejingRuntime(
                    RuntimeConfig(
                        adapter_name=adapter,
                        demo_mode=True,
                        stop_on_failure=False,
                        clean_output=True,
                    )
                )
                summary = runtime.run_task_files(task_files, output_dir, run_id=run_id)
                imported = self.repo.save_run_directory(summary.run_dir)
                run = self.repo.get_run(imported["run_id"])
            except Exception as exc:  # pragma: no cover - defensive local API boundary
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                return
            self._send_json({"run": run, "imported": imported}, status=HTTPStatus.CREATED)
            return

        if len(parts) == 1 and parts[0] == "memories":
            body = self._read_json_body()
            try:
                record = self.repo.create_memory(body)
            except Exception as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json({"memory": record, "memory_summary": self.repo.get_memory_summary()}, status=HTTPStatus.CREATED)
            return

        if len(parts) == 2 and parts[0] == "workflows" and parts[1] == "product-test":
            body = self._read_json_body()
            adapter = str(body.get("adapter", "jiejing-local"))
            run_id = body.get("run_id") or f"product-workflow-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            output_dir = Path(str(body.get("output_dir", ""))).resolve() if body.get("output_dir") else (
                self.repo.db_path.parent / "runtime-api-workflows" / str(run_id)
            )
            request = ProductWorkflowRequest(
                product=str(body.get("product") or "Untitled eBay product"),
                merchant_goal=str(body.get("merchant_goal") or "Run a Jiejing eBay product workflow."),
                project_id=str(run_id),
                stage=str(body.get("stage") or "store_opened"),
                platform=str(body.get("platform") or "ebay"),
                user_id=str(body.get("user_id") or "user_demo"),
                company_id=str(body.get("company_id") or "company_demo"),
                store_id=str(body.get("store_id") or "store_demo_northvalesource"),
                marketplace=str(body.get("marketplace") or "eBay US"),
                source_mode=str(body.get("source_mode") or "manual_or_1688"),
                notes=str(body.get("notes") or ""),
                market_probe_inputs=body.get("market_probe_inputs") if isinstance(body.get("market_probe_inputs"), dict) else None,
                ebay_read_only_probe=body.get("ebay_read_only_probe")
                if isinstance(body.get("ebay_read_only_probe"), dict)
                else self._default_ebay_read_only_probe(body),
                public_search_probe=body.get("public_search_probe")
                if isinstance(body.get("public_search_probe"), dict)
                else self._default_public_search_probe(body),
                cross_platform_reference_probe=body.get("cross_platform_reference_probe")
                if isinstance(body.get("cross_platform_reference_probe"), dict)
                else None,
                sourcing_availability_probe=body.get("sourcing_availability_probe")
                if isinstance(body.get("sourcing_availability_probe"), dict)
                else None,
                logistics_estimate_probe=body.get("logistics_estimate_probe") if isinstance(body.get("logistics_estimate_probe"), dict) else None,
                listing_metadata_probe=body.get("listing_metadata_probe")
                if isinstance(body.get("listing_metadata_probe"), dict)
                else self._default_listing_metadata_probe(body),
                media_generation_probe=body.get("media_generation_probe")
                if isinstance(body.get("media_generation_probe"), dict)
                else self._default_media_generation_probe(body),
                merchant_profile=body.get("merchant_profile") if isinstance(body.get("merchant_profile"), dict) else None,
            )
            try:
                runtime = JiejingRuntime(
                    RuntimeConfig(
                        adapter_name=adapter,
                        demo_mode=True,
                        stop_on_failure=False,
                        clean_output=True,
                    )
                )
                summary = runtime.run_tasks(build_product_workflow(request), output_dir, run_id=str(run_id))
                imported = self.repo.save_run_directory(summary.run_dir)
                run = self.repo.get_run(imported["run_id"])
                snapshot = build_saas_snapshot(
                    run=run,
                    results=self.repo.get_results(imported["run_id"]),
                    confirmations=self.repo.get_confirmations(imported["run_id"]),
                    validation_summary=self.repo.get_validation_summary(imported["run_id"]),
                )
            except Exception as exc:  # pragma: no cover - defensive local API boundary
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                return
            self._send_json({"run": run, "imported": imported, "saas_snapshot": snapshot}, status=HTTPStatus.CREATED)
            return

        if len(parts) == 5 and parts[0] == "runs" and parts[2] == "confirmations" and parts[4] == "decision":
            run_id = parts[1]
            confirmation_id = parts[3]
            body = self._read_json_body()
            decision = body.get("decision")
            decided_by = body.get("decided_by") or "merchant_demo"
            decided_at = body.get("decided_at") or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            note = body.get("note")
            try:
                record = self.repo.record_confirmation_decision(
                    run_id=run_id,
                    confirmation_id=confirmation_id,
                    decision=decision,
                    decided_by=decided_by,
                    decided_at=decided_at,
                    note=note,
                )
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except KeyError as exc:
                self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                return
            self._send_json(record, status=HTTPStatus.CREATED)
            return

        if len(parts) == 5 and parts[0] == "runs" and parts[2] == "confirmations" and parts[4] == "execute":
            run_id = parts[1]
            confirmation_id = parts[3]
            body = self._read_json_body()
            requested_by = str(body.get("requested_by") or "merchant_demo")
            demo_mode = body.get("demo_mode")
            demo_mode = True if demo_mode is None else bool(demo_mode)
            payload = body.get("payload") if isinstance(body.get("payload"), dict) else None
            try:
                record = self.repo.execute_confirmation_decision(
                    run_id=run_id,
                    confirmation_id=confirmation_id,
                    requested_by=requested_by,
                    demo_mode=demo_mode,
                    payload=payload,
                )
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except KeyError as exc:
                self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                return
            self._send_json(record, status=HTTPStatus.CREATED)
            return

        if len(parts) == 3 and parts[0] == "runs" and parts[2] == "listing-facts":
            run_id = parts[1]
            body = self._read_json_body()
            facts = body.get("facts") if isinstance(body.get("facts"), dict) else body
            updated_by = str(body.get("updated_by") or "merchant_demo")
            try:
                result = self.repo.apply_listing_facts(run_id=run_id, facts=facts, updated_by=updated_by)
            except KeyError as exc:
                self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                return
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(result, status=HTTPStatus.CREATED)
            return
        self._send_error(HTTPStatus.NOT_FOUND, "endpoint not found")

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _default_ebay_read_only_probe(self, body: dict[str, Any]) -> dict[str, Any] | None:
        if not self._safe_live_read_enabled(body):
            return None
        return {
            "live_enabled": True,
            "keyword": str(body.get("product") or "eBay product"),
            "marketplace_id": self._marketplace_id(str(body.get("marketplace") or "eBay US")),
            "limit": 10,
        }

    def _default_public_search_probe(self, body: dict[str, Any]) -> dict[str, Any] | None:
        if not self._safe_live_read_enabled(body):
            return None
        product = str(body.get("product") or "eBay product")
        marketplace = str(body.get("marketplace") or "eBay US")
        return {
            "live_enabled": True,
            "provider": str(body.get("search_provider") or "tavily"),
            "query": str(body.get("public_search_query") or f"{product} {marketplace} eBay 1688 Amazon reviews price supplier"),
            "marketplace_context": marketplace,
            "max_results": 8,
            "search_depth": "basic",
        }

    def _default_listing_metadata_probe(self, body: dict[str, Any]) -> dict[str, Any] | None:
        if not self._safe_live_read_enabled(body):
            return None
        return {
            "live_enabled": True,
            "marketplace_id": self._marketplace_id(str(body.get("marketplace") or "eBay US")),
            "category_id": str(body.get("category_id") or ""),
            "category_tree_id": str(body.get("category_tree_id") or "0"),
        }

    def _default_media_generation_probe(self, body: dict[str, Any]) -> dict[str, Any] | None:
        media_mode = str(body.get("media_tool_mode") or body.get("media_generation_mode") or "").strip().lower()
        if media_mode not in {"live_provider", "fal", "generate"}:
            return None
        product = str(body.get("product") or "eBay product")
        return {
            "live_enabled": True,
            "provider": "fal" if media_mode in {"live_provider", "fal"} else str(body.get("media_provider") or ""),
            "product": product,
            "image_prompt": str(
                body.get("image_prompt")
                or f"Create eBay-ready main image, scene image, detail page and dimension image for {product}."
            ),
            "video_prompt": str(body.get("video_prompt") or ""),
            "image_count": int(body.get("image_count") or 4),
        }

    def _safe_live_read_enabled(self, body: dict[str, Any]) -> bool:
        mode = str(body.get("tool_mode") or body.get("runtime_tool_mode") or "").strip().lower()
        return mode in {"safe_live_read", "read_only", "live_read", "provider_read"}

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

    def _send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self) -> None:
        origin = self._resolved_cors_origin()
        if origin:
            self.send_header("access-control-allow-origin", origin)
            self.send_header("vary", "Origin")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")

    def _resolved_cors_origin(self) -> str | None:
        configured = [item.strip() for item in str(os.environ.get("JIEJING_CORS_ORIGIN") or "*").split(",") if item.strip()]
        if not configured:
            return None
        environment = str(os.environ.get("JIEJING_RUNTIME_ENV") or os.environ.get("JIEJING_SAAS_ENV") or "local_dev").strip().lower()
        production_like = environment in {"staging", "production"}
        request_origin = self.headers.get("origin", "")
        if "*" in configured and not production_like:
            return "*"
        if request_origin and request_origin in configured:
            return request_origin
        if not request_origin and "*" not in configured:
            return configured[0]
        return None

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message, "status": int(status)}, status=status)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

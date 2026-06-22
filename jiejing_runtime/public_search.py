"""Public-search probe boundary for Jiejing Runtime.

The adapter normalizes public search snapshots into market.data_packet input.
It is intentionally provider-neutral: production can feed results from Bing,
Google CSE, Tavily, SerpApi, browser workers, or manually exported search
records without changing the downstream market report contract.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PublicSearchProbeConfig:
    query: str
    provider: str = "snapshot"
    marketplace_context: str = "eBay US"
    results: list[dict[str, Any]] | None = None
    endpoint: str | None = None
    api_key: str | None = None
    live_enabled: bool = False
    timeout_seconds: int = 20
    max_results: int = 8
    search_depth: str = "basic"
    include_images: bool = False
    country: str | None = None


class PublicSearchProbeAdapter:
    """Normalizes public-search results without treating them as official data."""

    version = "0.1.0"

    def probe(self, config: PublicSearchProbeConfig) -> dict[str, Any]:
        provider = self._provider(config.provider)
        if config.results:
            return self.snapshot_from_results(
                query=config.query,
                provider=provider,
                marketplace_context=config.marketplace_context,
                results=config.results,
            )
        if not config.live_enabled:
            return self.pending_snapshot(
                "Public search probe is disabled. Provide a search snapshot or enable a backend search provider.",
                query=config.query,
                provider=provider,
            )
        endpoint, api_key, credential_source = self._resolve_connection(config, provider)
        if not endpoint or not api_key:
            return self.pending_snapshot(
                f"Public search probe needs backend endpoint and API key; no live `{provider}` provider is configured.",
                query=config.query,
                provider=provider,
            )
        try:
            if provider == "tavily":
                results = self._run_tavily_provider(endpoint, api_key, config)
            else:
                results = self._run_provider(endpoint, api_key, config)
            return self.snapshot_from_results(
                query=config.query,
                provider=provider,
                marketplace_context=config.marketplace_context,
                results=results,
                credential_source=credential_source,
            )
        except Exception as exc:  # pragma: no cover - provider/network dependent
            safe_error = self._safe_error(exc, api_key)
            return {
                "source_type": "public_page",
                "confidence": "low",
                "summary": f"Public search probe failed: {safe_error[:240]}",
                "status": "failed_tool",
                "error": safe_error[:500],
                "query": config.query,
                "provider": provider,
            }

    def provider_status(self, provider: str = "tavily") -> dict[str, Any]:
        probe_config = PublicSearchProbeConfig(query="provider status", provider=provider, live_enabled=True)
        endpoint, api_key, credential_source = self._resolve_connection(probe_config, self._provider(provider))
        return {
            "provider": self._provider(provider),
            "configured": bool(endpoint and api_key),
            "endpoint_host": self._domain(endpoint),
            "credential_present": bool(api_key),
            "credential_source": credential_source if api_key else "missing",
            "secret_exposed": False,
        }

    def pending_snapshot(self, reason: str, query: str = "", provider: str = "snapshot") -> dict[str, Any]:
        return {
            "source_type": "restricted_unavailable",
            "confidence": "low",
            "summary": reason,
            "status": "pending_tool",
            "query": query,
            "provider": provider,
        }

    def snapshot_from_results(
        self,
        query: str,
        provider: str,
        marketplace_context: str,
        results: list[dict[str, Any]],
        credential_source: str = "snapshot",
    ) -> dict[str, Any]:
        normalized = [self._normalize_result(item) for item in results if isinstance(item, dict)]
        normalized = [item for item in normalized if item.get("title") or item.get("url") or item.get("snippet")]
        domains = self._domain_counts(normalized)
        metrics = {
            "query": query,
            "provider": provider,
            "marketplace_context": marketplace_context,
            "result_count": len(normalized),
            "domain_distribution": domains,
            "commercial_result_count": len([item for item in normalized if item.get("commerce_hint")]),
            "credential_source": credential_source if provider != "snapshot" else "snapshot",
            "secret_exposed": False,
        }
        return {
            "source_type": "public_page",
            "confidence": "medium" if normalized else "low",
            "summary": self._summary(query, provider, metrics),
            "status": "ready" if normalized else "partial",
            "provider": provider,
            "metrics": metrics,
            "results": normalized[:12],
            "notes": [
                "Public search is directional context, not official eBay marketplace data.",
                "Search results can be personalized, stale, blocked, or incomplete; keep source time and URL in later production adapters.",
            ],
        }

    def _normalize_result(self, item: dict[str, Any]) -> dict[str, Any]:
        title = str(item.get("title") or item.get("name") or "").strip()
        url = str(item.get("url") or item.get("link") or "").strip()
        snippet = str(item.get("snippet") or item.get("summary") or item.get("description") or item.get("content") or "").strip()
        source_time = str(item.get("captured_at") or item.get("date") or "").strip()
        domain = self._domain(url)
        commerce_hint = self._commerce_hint(title, url, snippet)
        return {
            "title": title,
            "url": url,
            "domain": domain,
            "snippet": snippet[:500],
            "captured_at": source_time,
            "commerce_hint": commerce_hint,
            "score": item.get("score") if isinstance(item.get("score"), (int, float)) else None,
        }

    def _run_tavily_provider(self, endpoint: str, api_key: str, config: PublicSearchProbeConfig) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "query": config.query,
            "search_depth": config.search_depth if config.search_depth in {"advanced", "basic", "fast", "ultra-fast"} else "basic",
            "max_results": max(1, min(int(config.max_results or 8), 20)),
            "include_answer": False,
            "include_raw_content": False,
            "include_images": bool(config.include_images),
        }
        if config.country:
            payload["country"] = config.country
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - provider/network dependent
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"tavily HTTP {exc.code}: {detail[:300]}") from exc
        results = data.get("results")
        return results if isinstance(results, list) else []

    def _run_provider(self, endpoint: str, api_key: str, config: PublicSearchProbeConfig) -> list[dict[str, Any]]:
        # Generic GET provider shape. Production can swap this with a provider-
        # specific adapter while keeping snapshot_from_results unchanged.
        params = urllib.parse.urlencode({"q": config.query})
        separator = "&" if "?" in endpoint else "?"
        request = urllib.request.Request(
            f"{endpoint}{separator}{params}",
            method="GET",
            headers={"accept": "application/json", "authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
        for key in ["results", "items", "webPages"]:
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict) and isinstance(value.get("value"), list):
                return value["value"]
        return []

    def _resolve_connection(self, config: PublicSearchProbeConfig, provider: str) -> tuple[str, str, str]:
        endpoint = config.endpoint or os.environ.get("JIEJING_SEARCH_ENDPOINT") or ""
        api_key = config.api_key or os.environ.get("JIEJING_SEARCH_API_KEY") or ""
        source = "constructor" if config.api_key else "jiejing_search_env" if os.environ.get("JIEJING_SEARCH_API_KEY") else ""
        if provider == "tavily":
            endpoint = endpoint or os.environ.get("TAVILY_SEARCH_ENDPOINT") or "https://api.tavily.com/search"
            if not api_key:
                api_key = os.environ.get("TAVILY_API_KEY") or ""
                source = "tavily_env" if api_key else ""
            if not api_key and self._env_enabled("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", default=True):
                api_key = self._tavily_key_from_wsl()
                source = "wsl_hermes_env:TAVILY_API_KEY" if api_key else ""
        return endpoint, api_key, source or "missing"

    def _tavily_key_from_wsl(self) -> str:
        if os.name != "nt":
            return ""
        script = r"""
from pathlib import Path
path = Path('/home/hermes/.hermes/.env')
if not path.exists():
    raise SystemExit(0)
value = ''
for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith('#') or '=' not in stripped:
        continue
    key, raw = stripped.split('=', 1)
    if key.strip() == 'TAVILY_API_KEY':
        value = raw.strip().strip('"').strip("'")
if value:
    print(value)
"""
        try:
            completed = subprocess.run(
                ["wsl.exe", "-e", "python3", "-c", script],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=8,
                check=False,
            )
        except Exception:
            return ""
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""

    def _provider(self, provider: str) -> str:
        value = (provider or "snapshot").strip().lower().replace("_", "-")
        aliases = {"tavily-search": "tavily", "public-search": "generic"}
        return aliases.get(value, value)

    def _env_enabled(self, name: str, default: bool = False) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    def _safe_error(self, exc: Exception, api_key: str) -> str:
        message = str(exc)
        if api_key:
            message = message.replace(api_key, "[redacted]")
        return message

    def _domain_counts(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for item in results:
            domain = item.get("domain")
            if not domain:
                continue
            counts[domain] = counts.get(domain, 0) + 1
        return [{"domain": domain, "count": count} for domain, count in sorted(counts.items(), key=lambda row: (-row[1], row[0]))[:10]]

    def _domain(self, url: str) -> str:
        if not url:
            return ""
        parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
        return parsed.netloc.lower().removeprefix("www.")

    def _commerce_hint(self, title: str, url: str, snippet: str) -> str:
        text = f"{title} {url} {snippet}".lower()
        if "ebay" in text:
            return "ebay_public"
        if "amazon" in text:
            return "amazon_public"
        if "1688" in text:
            return "1688_public"
        if "alibaba" in text:
            return "alibaba_public"
        if "shopify" in text:
            return "shopify_public"
        if any(word in text for word in ["buy", "price", "wholesale", "supplier", "review"]):
            return "commerce_public"
        return ""

    def _summary(self, query: str, provider: str, metrics: dict[str, Any]) -> str:
        count = metrics.get("result_count") or 0
        if not count:
            return f"Public search snapshot for `{query}` returned no normalized results."
        return (
            f"Public search snapshot for `{query}` normalized {count} results from `{provider}`; "
            f"{metrics.get('commercial_result_count', 0)} results have commerce-related hints."
        )

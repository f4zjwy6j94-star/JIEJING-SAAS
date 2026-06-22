"""Provider-neutral media generation adapter for the Asset Agent.

The adapter does not bind Jiejing to one image/video vendor. It accepts an
already-generated asset manifest, or calls explicitly configured backend
providers. It never claims real files exist unless a provider or supplied
manifest returns them.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(slots=True)
class MediaGenerationConfig:
    product: str
    image_prompt: str = ""
    video_prompt: str = ""
    detail_page_prompt: str = ""
    image_count: int = 4
    image_sizes: list[str] = field(default_factory=lambda: ["1600x1600", "1200x1600", "1200x3600"])
    scene_types: list[str] = field(default_factory=lambda: ["main_white_bg", "lifestyle_scene", "detail_page", "dimension_image"])
    asset_manifest: dict[str, Any] | None = None
    live_enabled: bool = False
    provider: str = ""
    image_endpoint: str | None = None
    video_endpoint: str | None = None
    api_key: str | None = None
    proxy_url: str | None = None
    image_model: str = "openai/gpt-image-2"
    video_model: str = "fal-ai/wan-i2v"
    reference_image_url: str = ""
    timeout_seconds: int = 45


class MediaGenerationAdapter:
    """Creates or normalizes product image/video asset manifests."""

    version = "0.2.0"

    def generate(self, config: MediaGenerationConfig) -> dict[str, Any]:
        if isinstance(config.asset_manifest, dict):
            return self.snapshot_from_manifest(config.product, config.asset_manifest)
        if not config.live_enabled:
            return self.pending_snapshot(config.product, "Media generation is disabled. Provide a manifest or enable a configured provider.")

        image_connection = self._resolve_connection(config, "image")
        video_connection = self._resolve_connection(config, "video")
        image_endpoint = image_connection["endpoint"]
        video_endpoint = video_connection["endpoint"]
        api_key = image_connection["credential"] or video_connection["credential"]
        if not image_endpoint and not video_endpoint:
            status = self.provider_status("fal")
            if status.get("configured"):
                return self.pending_snapshot(
                    config.product,
                    "FAL media credential is available, but media generation needs explicit provider=fal or a configured endpoint before spending credits.",
                )
            return self.pending_snapshot(config.product, "No image/video provider endpoint is configured.")
        if not api_key:
            return self.pending_snapshot(config.product, "Media provider credential is not configured.")

        provider_results: dict[str, Any] = {"assets": []}
        errors: list[str] = []
        if image_endpoint and self._should_generate_image(config):
            image_summaries: list[dict[str, Any]] = []
            for batch_config in self._image_batches(config, image_connection["provider"]):
                try:
                    image_result = self._post_json(
                        image_endpoint,
                        image_connection["authorization"],
                        self._image_payload(batch_config, provider=image_connection["provider"]),
                        batch_config.timeout_seconds,
                        image_connection["proxy_url"],
                    )
                    image_summaries.append(self._provider_summary(image_result))
                    provider_results["assets"].extend(self._assets_from_provider(image_result, "image"))
                except Exception as exc:  # pragma: no cover - provider dependent
                    errors.append(f"image_provider: {self._safe_error(exc, api_key)[:240]}")
            if image_summaries:
                provider_results["image_provider"] = {
                    "status": "returned",
                    "provider": image_summaries[0].get("provider"),
                    "batch_count": len(image_summaries),
                    "asset_count": sum(int(item.get("asset_count") or 0) for item in image_summaries),
                    "batches": image_summaries,
                }
        if video_endpoint and self._should_generate_video(config):
            try:
                video_result = self._post_json(video_endpoint, video_connection["authorization"], self._video_payload(config), config.timeout_seconds, video_connection["proxy_url"])
                provider_results["video_provider"] = self._provider_summary(video_result)
                provider_results["assets"].extend(self._assets_from_provider(video_result, "video"))
            except Exception as exc:  # pragma: no cover - provider dependent
                errors.append(f"video_provider: {self._safe_error(exc, api_key)[:240]}")

        snapshot = self.snapshot_from_manifest(config.product, provider_results)
        snapshot["provider_status"] = self._safe_connection_status(image_connection, video_connection)
        if errors:
            snapshot["provider_errors"] = errors
            if not snapshot.get("assets"):
                snapshot["status"] = "failed_tool"
                snapshot["confidence"] = "low"
                snapshot["summary"] = f"Media provider call failed for {config.product}; no generated assets were returned."
        return snapshot

    def pending_snapshot(self, product: str, reason: str) -> dict[str, Any]:
        return {
            "status": "pending_provider",
            "source_type": "restricted_unavailable",
            "confidence": "low",
            "summary": reason,
            "product": product,
            "required_before_claiming_generated": [
                "provider response or supplied manifest",
                "asset URL or local file path",
                "asset type",
                "dimensions or duration",
                "commercial-use status",
            ],
            "real_execution_allowed": False,
        }

    def provider_status(self, provider: str = "fal") -> dict[str, Any]:
        provider = self._provider(provider)
        if provider == "fal":
            credential, credential_source = self._resolve_fal_credential()
            proxy = self._proxy_url(None)
            return {
                "provider": "fal",
                "configured": bool(credential),
                "image_endpoint_host": self._host(self._fal_endpoint(os.environ.get("JIEJING_FAL_IMAGE_MODEL") or "openai/gpt-image-2")),
                "video_endpoint_host": self._host(self._fal_endpoint(os.environ.get("JIEJING_FAL_VIDEO_MODEL") or "fal-ai/wan-i2v")),
                "credential_present": bool(credential),
                "credential_source": credential_source if credential else "missing",
                "proxy_configured": bool(proxy),
                "proxy_host": self._host(proxy),
                "secret_exposed": False,
            }
        credential = os.environ.get("JIEJING_MEDIA_GENERATION_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        endpoint = os.environ.get("JIEJING_IMAGE_GENERATION_ENDPOINT") or os.environ.get("JIEJING_VIDEO_GENERATION_ENDPOINT") or ""
        return {
            "provider": provider or "generic",
            "configured": bool(credential and endpoint),
            "endpoint_host": self._host(endpoint),
            "credential_present": bool(credential),
            "credential_source": "jiejing_media_env" if credential else "missing",
            "secret_exposed": False,
        }

    def snapshot_from_manifest(self, product: str, manifest: dict[str, Any]) -> dict[str, Any]:
        raw_assets = manifest.get("assets")
        if not isinstance(raw_assets, list):
            raw_assets = []
        assets = [asset for asset in (self._normalize_asset(item) for item in raw_assets) if asset]
        missing = []
        if not assets:
            missing.append("generated_asset_manifest")
        asset_types = sorted({asset["asset_type"] for asset in assets})
        return {
            "status": "ready" if assets else "partial",
            "source_type": "media_provider" if assets else "restricted_unavailable",
            "confidence": "medium" if assets else "low",
            "summary": (
                f"Media manifest for {product} contains {len(assets)} assets: {', '.join(asset_types)}."
                if assets
                else f"Media manifest for {product} has no usable assets yet."
            ),
            "product": product,
            "assets": assets,
            "asset_types": asset_types,
            "missing": missing,
            "provider": manifest.get("provider") or manifest.get("provider_name") or None,
            "real_execution_allowed": False,
            "notes": [
                "Generated media must be reviewed against confirmed product facts before listing publish.",
                "No unsupported performance, certification, medical, or material claims may be added to images or video.",
                "Videos using people or voice must respect likeness, script, and commercial-use rights.",
            ],
        }

    def _post_json(self, endpoint: str, authorization: str, payload: dict[str, Any], timeout_seconds: int, proxy_url: str = "") -> dict[str, Any]:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "content-type": "application/json",
                "authorization": authorization,
            },
        )
        try:
            opener = self._opener(proxy_url)
            with opener.open(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - provider dependent
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"media provider HTTP {exc.code}: {detail[:300]}") from exc

    def _image_payload(self, config: MediaGenerationConfig, *, provider: str = "") -> dict[str, Any]:
        if self._provider(provider) == "fal":
            return {
                "prompt": config.image_prompt or f"Generate eBay-safe product images for {config.product}.",
                "image_size": _fal_image_size(config.image_sizes[0] if config.image_sizes else ""),
                "quality": os.environ.get("JIEJING_FAL_IMAGE_QUALITY") or "low",
                "num_images": max(1, min(int(config.image_count or 1), 4)),
                "output_format": "jpeg",
            }
        return {
            "product": config.product,
            "prompt": config.image_prompt or f"Generate eBay-safe product images for {config.product}.",
            "detail_page_prompt": config.detail_page_prompt,
            "count": config.image_count,
            "sizes": config.image_sizes,
            "scene_types": config.scene_types,
            "safety": {
                "do_not_invent_facts": True,
                "commercial_manifest_required": True,
            },
        }

    def _video_payload(self, config: MediaGenerationConfig) -> dict[str, Any]:
        return {
            "product": config.product,
            "prompt": config.video_prompt or f"Create a 20-30 second eBay product demo video plan/assets for {config.product}.",
            "image_url": config.reference_image_url or None,
            "safety": {
                "no_fake_testimonial": True,
                "do_not_claim_unverified_performance": True,
            },
        }

    def _provider_summary(self, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": result.get("status") or result.get("state") or "returned",
            "provider": result.get("provider") or result.get("provider_name"),
            "asset_count": len(result.get("assets") or result.get("images") or result.get("videos") or []),
        }

    def _assets_from_provider(self, result: dict[str, Any], fallback_type: str) -> list[dict[str, Any]]:
        source_assets = result.get("assets")
        if not isinstance(source_assets, list):
            source_assets = []
        if not source_assets and isinstance(result.get("images"), list):
            source_assets = result["images"]
        if not source_assets and isinstance(result.get("videos"), list):
            source_assets = result["videos"]
        if not source_assets and isinstance(result.get("video"), dict):
            source_assets = [result["video"]]
        return [asset for asset in (self._normalize_asset(item, fallback_type) for item in source_assets) if asset]

    def _normalize_asset(self, item: Any, fallback_type: str = "asset") -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        url_or_path = item.get("url") or item.get("path") or item.get("file_path")
        asset_type = item.get("asset_type") or item.get("type") or fallback_type
        if not url_or_path or not asset_type:
            return None
        dimensions = item.get("dimensions") or item.get("size") or ""
        if not dimensions and item.get("width") and item.get("height"):
            dimensions = f"{item.get('width')}x{item.get('height')}"
        normalized = {
            "asset_id": item.get("asset_id") or item.get("id") or _asset_id_from_url(str(asset_type), str(url_or_path)),
            "asset_type": str(asset_type),
            "url": url_or_path,
            "dimensions": dimensions,
            "duration_seconds": item.get("duration_seconds") or item.get("duration") or None,
            "source": item.get("source") or item.get("provider") or "media_generation_provider",
            "commercial_use_status": item.get("commercial_use_status") or "needs_review",
            "status": item.get("status") or "generated",
        }
        return normalized

    def _resolve_connection(self, config: MediaGenerationConfig, asset_kind: str) -> dict[str, str]:
        provider = self._provider(config.provider or os.environ.get("JIEJING_MEDIA_GENERATION_PROVIDER") or "")
        explicit_endpoint = config.image_endpoint if asset_kind == "image" else config.video_endpoint
        env_endpoint = os.environ.get("JIEJING_IMAGE_GENERATION_ENDPOINT") if asset_kind == "image" else os.environ.get("JIEJING_VIDEO_GENERATION_ENDPOINT")
        endpoint = explicit_endpoint or env_endpoint or ""
        credential = config.api_key or os.environ.get("JIEJING_MEDIA_GENERATION_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        authorization = f"Bearer {credential}" if credential else ""
        credential_source = "constructor" if config.api_key else "jiejing_media_env" if credential else "missing"
        proxy_url = config.proxy_url or os.environ.get("JIEJING_MEDIA_PROXY_URL") or ""
        if provider == "fal":
            credential, credential_source = self._resolve_fal_credential(config.api_key)
            if asset_kind == "image":
                endpoint = endpoint or self._fal_endpoint(config.image_model or os.environ.get("JIEJING_FAL_IMAGE_MODEL") or "openai/gpt-image-2")
            else:
                endpoint = endpoint or self._fal_endpoint(config.video_model or os.environ.get("JIEJING_FAL_VIDEO_MODEL") or "fal-ai/wan-i2v")
            authorization = f"Key {credential}" if credential else ""
            proxy_url = self._proxy_url(config.proxy_url)
        return {
            "provider": provider or "generic",
            "endpoint": endpoint,
            "credential": credential,
            "authorization": authorization,
            "credential_source": credential_source,
            "proxy_url": proxy_url,
        }

    def _resolve_fal_credential(self, explicit_key: str | None = None) -> tuple[str, str]:
        if explicit_key:
            return explicit_key, "constructor"
        key = os.environ.get("JIEJING_FAL_KEY") or os.environ.get("FAL_KEY") or ""
        if key:
            return key, "fal_env"
        key_id = os.environ.get("JIEJING_FAL_KEY_ID") or os.environ.get("FAL_KEY_ID") or ""
        key_secret = os.environ.get("JIEJING_FAL_KEY_SECRET") or os.environ.get("FAL_KEY_SECRET") or ""
        if key_id and key_secret:
            return f"{key_id}:{key_secret}", "fal_env_pair"
        if self._env_enabled("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", default=True):
            key = self._fal_key_from_wsl()
            if key:
                return key, "wsl_hermes_env:FAL_KEY_ID/FAL_KEY_SECRET"
        return "", "missing"

    def _fal_key_from_wsl(self) -> str:
        if os.name != "nt":
            return ""
        script = r"""
from pathlib import Path
path = Path('/home/hermes/.hermes/.env')
if not path.exists():
    raise SystemExit(0)
values = {}
for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith('#') or '=' not in stripped:
        continue
    key, raw = stripped.split('=', 1)
    key = key.strip()
    if key in {'FAL_KEY', 'FAL_KEY_ID', 'FAL_KEY_SECRET'}:
        values[key] = raw.strip().strip('"').strip("'")
if values.get('FAL_KEY'):
    print(values['FAL_KEY'])
elif values.get('FAL_KEY_ID') and values.get('FAL_KEY_SECRET'):
    print(values['FAL_KEY_ID'] + ':' + values['FAL_KEY_SECRET'])
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

    def _fal_endpoint(self, model_id: str) -> str:
        model_id = (model_id or "openai/gpt-image-2").strip().strip("/")
        return f"https://fal.run/{model_id}"

    def _proxy_url(self, explicit_proxy: str | None) -> str:
        return (
            explicit_proxy
            or os.environ.get("JIEJING_FAL_PROXY_URL")
            or os.environ.get("FAL_PROXY_URL")
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("HTTP_PROXY")
            or ""
        )

    def _opener(self, proxy_url: str) -> urllib.request.OpenerDirector:
        if not proxy_url:
            return urllib.request.build_opener()
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))

    def _provider(self, provider: str) -> str:
        normalized = (provider or "").strip().lower().replace("_", "-")
        aliases = {"fal-ai": "fal", "falai": "fal", "fal-run": "fal"}
        return aliases.get(normalized, normalized)

    def _safe_connection_status(self, image_connection: dict[str, str], video_connection: dict[str, str]) -> dict[str, Any]:
        return {
            "image_provider": image_connection.get("provider"),
            "video_provider": video_connection.get("provider"),
            "image_endpoint_host": self._host(image_connection.get("endpoint", "")),
            "video_endpoint_host": self._host(video_connection.get("endpoint", "")),
            "credential_present": bool(image_connection.get("credential") or video_connection.get("credential")),
            "credential_source": image_connection.get("credential_source") or video_connection.get("credential_source") or "missing",
            "proxy_configured": bool(image_connection.get("proxy_url") or video_connection.get("proxy_url")),
            "secret_exposed": False,
        }

    def _should_generate_image(self, config: MediaGenerationConfig) -> bool:
        return config.image_count > 0 and bool(config.image_prompt or config.detail_page_prompt or config.scene_types)

    def _image_batches(self, config: MediaGenerationConfig, provider: str) -> list[MediaGenerationConfig]:
        count = max(1, int(config.image_count or 1))
        if self._provider(provider) != "fal" or count <= 4:
            return [config]
        batches: list[MediaGenerationConfig] = []
        remaining = count
        while remaining > 0:
            batch_count = min(remaining, 4)
            batches.append(replace(config, image_count=batch_count))
            remaining -= batch_count
        return batches

    def _should_generate_video(self, config: MediaGenerationConfig) -> bool:
        return bool(
            config.video_prompt
            or config.reference_image_url
            or config.video_endpoint
            or self._env_enabled("JIEJING_MEDIA_GENERATE_VIDEO_BY_DEFAULT")
        )

    def _safe_error(self, exc: Exception, credential: str) -> str:
        message = str(exc)
        if credential:
            message = message.replace(credential, "[redacted]")
        return message

    def _host(self, url: str) -> str:
        if not url:
            return ""
        parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
        return parsed.netloc.lower()

    def _env_enabled(self, name: str, default: bool = False) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}


def _fal_image_size(value: str) -> str | dict[str, int]:
    text = str(value or "").strip().lower()
    presets = {
        "1600x1600": "square_hd",
        "1200x1200": "square_hd",
        "1024x1024": "square_hd",
        "512x512": "square",
        "1200x1600": "portrait_4_3",
        "768x1024": "portrait_4_3",
        "1600x1200": "landscape_4_3",
        "1024x768": "landscape_4_3",
        "1024x576": "landscape_16_9",
        "576x1024": "portrait_16_9",
    }
    if text in presets:
        return presets[text]
    if "x" in text:
        left, right = text.split("x", 1)
        try:
            width = int(left.strip())
            height = int(right.strip())
        except ValueError:
            return "square_hd"
        if width > 0 and height > 0 and width % 16 == 0 and height % 16 == 0:
            return {"width": width, "height": height}
    return "square_hd"


def _asset_id_from_url(asset_type: str, url_or_path: str) -> str:
    digest = hashlib.sha1(url_or_path.encode("utf-8", errors="ignore")).hexdigest()[:10]
    normalized_type = "".join(ch if ch.isalnum() else "_" for ch in asset_type.lower()).strip("_") or "asset"
    return f"{normalized_type}_{digest}"

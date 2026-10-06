"""Provider-neutral media generation adapter for the Asset Agent.

The adapter does not bind Jiejing to one image/video vendor. It accepts an
already-generated asset manifest, or calls explicitly configured backend
providers. It never claims real files exist unless a provider or supplied
manifest returns them.
"""

from __future__ import annotations

import hashlib
import base64
import json
import os
import struct
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


DEFAULT_FAL_VIDEO_MODEL = "fal-ai/minimax/hailuo-2.3/standard/image-to-video"
LEGACY_FAL_VIDEO_MODELS = {"fal-ai/minimax/video-01/image-to-video"}


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
    image_model: str = ""
    image_quality: str = ""
    video_model: str = DEFAULT_FAL_VIDEO_MODEL
    video_duration_seconds: int = 0
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
                        self._image_payload(
                            batch_config,
                            provider=image_connection["provider"],
                            model=image_connection.get("model", ""),
                        ),
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
                video_config = config
                if not video_config.reference_image_url:
                    reference_image_url = next(
                        (
                            str(asset.get("url") or "").strip()
                            for asset in provider_results["assets"]
                            if isinstance(asset, dict)
                            and "video" not in str(asset.get("asset_type") or "").lower()
                            and str(asset.get("url") or "").strip().startswith(("http://", "https://"))
                        ),
                        "",
                    )
                    if reference_image_url:
                        video_config = replace(config, reference_image_url=reference_image_url)
                video_payload = self._video_payload(
                    video_config,
                    provider=video_connection["provider"],
                    model=video_connection.get("model", ""),
                )
                if video_connection["provider"] == "fal" and self._env_enabled("JIEJING_FAL_VIDEO_USE_QUEUE", default=True):
                    video_result = self._fal_queue_result(
                        model_id=video_connection.get("model", ""),
                        authorization=video_connection["authorization"],
                        payload=video_payload,
                        timeout_seconds=config.timeout_seconds,
                        proxy_url=video_connection["proxy_url"],
                    )
                else:
                    video_result = self._post_json(
                        video_endpoint,
                        video_connection["authorization"],
                        video_payload,
                        config.timeout_seconds,
                        video_connection["proxy_url"],
                    )
                video_assets = self._assets_from_provider(video_result, "video")
                if video_connection["provider"] == "fal":
                    for asset in video_assets:
                        if asset.get("duration_seconds"):
                            continue
                        duration = self._probe_fal_video_duration(
                            str(asset.get("url") or ""),
                            proxy_url=video_connection["proxy_url"],
                            timeout_seconds=min(30, config.timeout_seconds),
                        )
                        if duration:
                            asset["duration_seconds"] = duration
                provider_results["video_provider"] = self._provider_summary(video_result)
                provider_results["assets"].extend(video_assets)
            except Exception as exc:  # pragma: no cover - provider dependent
                errors.append(f"video_provider: {self._safe_error(exc, api_key)[:240]}")

        snapshot = self.snapshot_from_manifest(config.product, provider_results)
        if isinstance(provider_results.get("image_provider"), dict):
            snapshot["image_provider"] = provider_results["image_provider"]
        if isinstance(provider_results.get("video_provider"), dict):
            snapshot["video_provider"] = provider_results["video_provider"]
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
                "video_endpoint_host": self._host(self._fal_endpoint(self._fal_video_model(os.environ.get("JIEJING_FAL_VIDEO_MODEL") or ""))),
                "credential_present": bool(credential),
                "credential_source": credential_source if credential else "missing",
                "proxy_configured": bool(proxy),
                "proxy_host": self._host(proxy),
                "secret_exposed": False,
            }
        if provider == "openai":
            credential, credential_source = self._resolve_openai_credential()
            image_endpoint = self._openai_image_endpoint()
            video_endpoint = os.environ.get("JIEJING_OPENAI_VIDEO_GENERATION_ENDPOINT") or ""
            return {
                "provider": "openai",
                "configured": bool(credential and image_endpoint),
                "image_endpoint_host": self._host(image_endpoint),
                "video_endpoint_host": self._host(video_endpoint),
                "image_model": os.environ.get("JIEJING_OPENAI_IMAGE_MODEL") or "gpt-image-1",
                "credential_present": bool(credential),
                "credential_source": credential_source if credential else "missing",
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

    def _image_payload(self, config: MediaGenerationConfig, *, provider: str = "", model: str = "") -> dict[str, Any]:
        normalized_provider = self._provider(provider)
        if normalized_provider == "fal":
            payload: dict[str, Any] = {
                "prompt": config.image_prompt or f"Generate eBay-safe product images for {config.product}.",
                "image_size": _fal_image_size(config.image_sizes[0] if config.image_sizes else ""),
                "quality": config.image_quality or os.environ.get("JIEJING_FAL_IMAGE_QUALITY") or "low",
                "num_images": max(1, min(int(config.image_count or 1), 4)),
                "output_format": "jpeg",
            }
            if config.reference_image_url and str(model or "").rstrip("/").endswith("/edit"):
                payload["image_urls"] = [config.reference_image_url]
            return payload
        if normalized_provider == "openai":
            payload: dict[str, Any] = {
                "model": os.environ.get("JIEJING_OPENAI_IMAGE_MODEL") or config.image_model or "gpt-image-1",
                "prompt": config.image_prompt or f"Generate eBay-safe product images for {config.product}.",
                "size": _openai_image_size(config.image_sizes[0] if config.image_sizes else ""),
                "n": max(1, min(int(config.image_count or 1), 4)),
            }
            quality = os.environ.get("JIEJING_OPENAI_IMAGE_QUALITY")
            if quality:
                payload["quality"] = quality
            return payload
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

    def _video_payload(self, config: MediaGenerationConfig, *, provider: str = "", model: str = "") -> dict[str, Any]:
        prompt = config.video_prompt or f"Create a concise eBay product demo video for {config.product}. Use only confirmed product facts and avoid unverified claims."
        if self._provider(provider) == "fal":
            image_url = str(config.reference_image_url or "").strip()
            if not image_url:
                raise ValueError("FAL image-to-video generation requires a real reference image URL.")
            normalized_model = str(model or config.video_model or "").lower()
            if "stable-video" in normalized_model:
                return {
                    "image_url": image_url,
                    "motion_bucket_id": 96,
                    "cond_aug": 0.02,
                    "fps": 25,
                }
            image_field = "start_image_url" if "kling-video/v2.6" in normalized_model else "image_url"
            payload: dict[str, Any] = {
                "prompt": prompt[:1500],
                image_field: image_url,
                "prompt_optimizer": True,
            }
            if "minimax/hailuo-02" in normalized_model or "minimax/hailuo-2.3" in normalized_model:
                payload["duration"] = "10" if int(config.video_duration_seconds or 0) >= 10 else "6"
            return payload
        return {
            "product": config.product,
            "prompt": prompt,
            "image_url": config.reference_image_url or None,
            "safety": {
                "no_fake_testimonial": True,
                "do_not_claim_unverified_performance": True,
            },
        }

    def _provider_summary(self, result: dict[str, Any]) -> dict[str, Any]:
        assets = result.get("assets") or result.get("images") or result.get("videos") or result.get("data") or []
        if not assets and isinstance(result.get("video"), dict):
            assets = [result["video"]]
        return {
            "status": result.get("status") or result.get("state") or "returned",
            "provider": result.get("provider") or result.get("provider_name"),
            "asset_count": len(assets) if isinstance(assets, list) else 0,
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
        if not source_assets and isinstance(result.get("data"), list):
            source_assets = self._assets_from_openai_data(result["data"], fallback_type)
        return [asset for asset in (self._normalize_asset(item, fallback_type) for item in source_assets) if asset]

    def _assets_from_openai_data(self, items: list[Any], fallback_type: str) -> list[dict[str, Any]]:
        assets: list[dict[str, Any]] = []
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            file_path = ""
            if not url and item.get("b64_json"):
                file_path = self._store_base64_asset(str(item.get("b64_json") or ""), fallback_type=fallback_type)
            file_reference = url or file_path
            if not file_reference:
                continue
            assets.append(
                {
                    "asset_id": item.get("asset_id") or f"openai_{fallback_type}_{index:02d}",
                    "asset_type": "product_image" if fallback_type == "image" else fallback_type,
                    "url": url,
                    "file_path": file_path,
                    "path": file_path,
                    "dimensions": _openai_image_size(os.environ.get("JIEJING_OPENAI_IMAGE_SIZE") or ""),
                    "source": "openai_image_generation",
                    "provider": "openai",
                    "mime_type": _normalized_mime_type(item),
                    "commercial_use_status": "needs_rights_review",
                    "status": "generated",
                }
            )
        return assets

    def _normalize_asset(self, item: Any, fallback_type: str = "asset") -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        url_or_path = item.get("url") or item.get("path") or item.get("file_path")
        mime_type = _normalized_mime_type(item)
        asset_type = item.get("asset_type") or item.get("type")
        if not asset_type and mime_type.startswith("video/"):
            asset_type = "product_video"
        elif not asset_type and mime_type.startswith("image/"):
            asset_type = "product_image"
        asset_type = asset_type or fallback_type
        if not url_or_path or not asset_type:
            return None
        dimensions = item.get("dimensions") or item.get("size") or ""
        if not dimensions and item.get("width") and item.get("height"):
            dimensions = f"{item.get('width')}x{item.get('height')}"
        normalized = {
            "asset_id": item.get("asset_id") or item.get("id") or _asset_id_from_url(str(asset_type), str(url_or_path)),
            "asset_type": str(asset_type),
            "mime_type": mime_type,
            "url": url_or_path,
            "file_path": item.get("file_path") or item.get("path") or "",
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
        model = ""
        if provider == "fal":
            credential, credential_source = self._resolve_fal_credential(config.api_key)
            if asset_kind == "image":
                model = config.image_model or os.environ.get("JIEJING_FAL_IMAGE_MODEL") or "openai/gpt-image-2"
                normalized_image_model = model.rstrip("/").lower()
                supports_reference_image = normalized_image_model.endswith("/edit") or any(
                    marker in normalized_image_model for marker in ("image-to-image", "image2image", "subject-reference")
                )
                if config.reference_image_url and not supports_reference_image:
                    model = "openai/gpt-image-2/edit"
            else:
                model = self._fal_video_model(os.environ.get("JIEJING_FAL_VIDEO_MODEL") or config.video_model)
            endpoint = endpoint or self._fal_endpoint(model)
            authorization = f"Key {credential}" if credential else ""
            proxy_url = self._proxy_url(config.proxy_url)
        elif provider == "openai":
            credential, credential_source = self._resolve_openai_credential(config.api_key)
            if asset_kind == "image":
                endpoint = endpoint or self._openai_image_endpoint()
            else:
                endpoint = endpoint or os.environ.get("JIEJING_OPENAI_VIDEO_GENERATION_ENDPOINT") or ""
            authorization = f"Bearer {credential}" if credential else ""
        return {
            "provider": provider or "generic",
            "endpoint": endpoint,
            "credential": credential,
            "authorization": authorization,
            "credential_source": credential_source,
            "proxy_url": proxy_url,
            "model": model,
        }

    def _get_json(self, endpoint: str, authorization: str, timeout_seconds: int, proxy_url: str = "") -> dict[str, Any]:
        request = urllib.request.Request(
            endpoint,
            method="GET",
            headers={"authorization": authorization},
        )
        try:
            opener = self._opener(proxy_url)
            with opener.open(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - provider dependent
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"media provider HTTP {exc.code}: {detail[:300]}") from exc

    def _probe_fal_video_duration(self, url: str, *, proxy_url: str = "", timeout_seconds: int = 20) -> float | None:
        parsed = urllib.parse.urlparse(str(url or ""))
        host = parsed.netloc.lower()
        if parsed.scheme != "https" or not (host == "fal.media" or host.endswith(".fal.media") or host == "storage.googleapis.com"):
            return None
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Range": "bytes=0-4194303", "User-Agent": "Jiejing media metadata probe"},
        )
        try:
            opener = self._opener(proxy_url)
            with opener.open(request, timeout=max(5, int(timeout_seconds or 0))) as response:
                return _mp4_duration_seconds(response.read(4 * 1024 * 1024))
        except Exception:  # pragma: no cover - provider CDN dependent
            return None

    def _fal_queue_result(
        self,
        *,
        model_id: str,
        authorization: str,
        payload: dict[str, Any],
        timeout_seconds: int,
        proxy_url: str = "",
    ) -> dict[str, Any]:
        normalized_model = str(model_id or "").strip().strip("/")
        if not normalized_model:
            raise ValueError("FAL video model is not configured.")
        timeout_seconds = max(30, int(timeout_seconds or 0))
        submitted = self._post_json(
            f"https://queue.fal.run/{normalized_model}",
            authorization,
            payload,
            min(timeout_seconds, 30),
            proxy_url,
        )
        status_url = str(submitted.get("status_url") or "").strip()
        response_url = str(submitted.get("response_url") or "").strip()
        if not status_url or not response_url:
            raise RuntimeError("FAL queue response did not include status and result URLs.")
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("FAL video generation did not finish before the backend timeout.")
            status_packet = self._get_json(status_url, authorization, min(30, max(1, int(remaining))), proxy_url)
            queue_status = str(status_packet.get("status") or "").strip().upper()
            if queue_status == "COMPLETED":
                break
            if queue_status in {"FAILED", "CANCELLED", "ERROR"}:
                raise RuntimeError(f"FAL video queue ended with status {queue_status}.")
            time.sleep(min(2.0, max(0.2, remaining)))
        result = self._get_json(response_url, authorization, min(30, max(1, int(deadline - time.monotonic()))), proxy_url)
        if isinstance(result.get("data"), dict) and not any(key in result for key in ("video", "videos", "assets", "images")):
            result = dict(result["data"])
        result.setdefault("provider", "fal")
        return result

    def _resolve_openai_credential(self, explicit_key: str | None = None) -> tuple[str, str]:
        if explicit_key:
            return explicit_key, "constructor"
        credential = (
            os.environ.get("JIEJING_MEDIA_OPENAI_API_KEY")
            or os.environ.get("JIEJING_OPENAI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )
        if credential:
            return credential, "openai_env"
        return "", "missing"

    def _openai_image_endpoint(self) -> str:
        return (
            os.environ.get("JIEJING_OPENAI_IMAGE_GENERATION_ENDPOINT")
            or os.environ.get("JIEJING_IMAGE_GENERATION_ENDPOINT")
            or "https://api.openai.com/v1/images/generations"
        )

    def _store_base64_asset(self, raw: str, *, fallback_type: str) -> str:
        try:
            data = base64.b64decode(raw, validate=True)
        except Exception:
            return ""
        if not data:
            return ""
        digest = hashlib.sha1(data).hexdigest()[:16]
        root = Path(os.environ.get("JIEJING_MEDIA_GENERATED_ASSET_DIR") or "output/jiejing-media-assets")
        root.mkdir(parents=True, exist_ok=True)
        suffix = ".mp4" if "video" in fallback_type else ".png"
        path = root / f"{fallback_type}_{digest}{suffix}"
        if not path.exists():
            path.write_bytes(data)
        return str(path.resolve())

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

    def _fal_video_model(self, configured_model: str | None) -> str:
        model = str(configured_model or DEFAULT_FAL_VIDEO_MODEL).strip().strip("/")
        return DEFAULT_FAL_VIDEO_MODEL if model in LEGACY_FAL_VIDEO_MODELS else model

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
        aliases = {
            "fal-ai": "fal",
            "falai": "fal",
            "fal-run": "fal",
            "openai-images": "openai",
            "openai-image": "openai",
            "gpt-image": "openai",
        }
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


def _normalized_mime_type(asset: dict[str, Any]) -> str:
    value = str(
        asset.get("mime_type")
        or asset.get("content_type")
        or asset.get("content-type")
        or ""
    ).strip().lower()
    return value.split(";", 1)[0].strip()


def _mp4_duration_seconds(data: bytes) -> float | None:
    marker = data.find(b"mvhd")
    if marker < 0 or len(data) < marker + 24:
        return None
    version = data[marker + 4]
    try:
        if version == 1:
            if len(data) < marker + 36:
                return None
            timescale = struct.unpack(">I", data[marker + 24 : marker + 28])[0]
            duration = struct.unpack(">Q", data[marker + 28 : marker + 36])[0]
        else:
            timescale = struct.unpack(">I", data[marker + 16 : marker + 20])[0]
            duration = struct.unpack(">I", data[marker + 20 : marker + 24])[0]
    except (IndexError, struct.error):
        return None
    if timescale <= 0 or duration <= 0:
        return None
    return round(duration / timescale, 3)


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


def _openai_image_size(value: str) -> str:
    text = str(value or "").strip().lower()
    presets = {
        "1:1": "1024x1024",
        "4:5": "1024x1536",
        "3:4": "1024x1536",
        "9:16": "1024x1536",
        "16:9": "1536x1024",
        "4:3": "1536x1024",
        "1024x1024": "1024x1024",
        "1024x1536": "1024x1536",
        "1536x1024": "1536x1024",
        "1600x1600": "1024x1024",
        "1200x1200": "1024x1024",
        "1200x1600": "1024x1536",
        "768x1024": "1024x1536",
        "1600x1200": "1536x1024",
        "1024x768": "1536x1024",
    }
    return presets.get(text, "1024x1024")


def _asset_id_from_url(asset_type: str, url_or_path: str) -> str:
    digest = hashlib.sha1(url_or_path.encode("utf-8", errors="ignore")).hexdigest()[:10]
    normalized_type = "".join(ch if ch.isalnum() else "_" for ch in asset_type.lower()).strip("_") or "asset"
    return f"{normalized_type}_{digest}"

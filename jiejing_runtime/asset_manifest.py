"""Asset manifest validation for Jiejing Runtime.

The asset workflow has two valid states:

- brief_only: an asset manager returned a task package or production brief.
- manifest_ready: actual generated assets are listed with file references.

This prevents Jiejing from treating "image/video requirements" as finished
media files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class AssetManifestValidator:
    """Validates asset-manager output against the Jiejing media handoff contract."""

    version = "0.1.0"

    IMAGE_TYPES = {
        "main_image",
        "white_background_image",
        "scene_image",
        "lifestyle_image",
        "detail_page",
        "size_chart",
        "dimension_image",
        "cover_image",
        "infographic",
        "thumbnail",
    }
    VIDEO_TYPES = {"video", "product_video", "talking_head_video", "short_video"}

    GENERATED_CLAIM_PATTERN = re.compile(
        r"(?i)(generated|created|ready|complete|completed|exported|rendered|files?\s+ready|"
        r"\u5df2\u751f\u6210|\u5df2\u5b8c\u6210|\u51fa\u56fe\u5b8c\u6210|"
        r"\u89c6\u9891\u5df2\u751f\u6210|\u7d20\u6750\u5df2\u751f\u6210|\u6587\u4ef6\u5df2\u751f\u6210)"
    )

    def validate_text(self, text: str) -> dict[str, Any]:
        generated_claim_present = self._generated_claim_present(text)
        manifest = self._extract_manifest(text)
        raw_assets = self._assets_from_manifest(manifest)
        assets = [self._normalize_asset(asset) for asset in raw_assets]
        for index, asset in enumerate(assets, start=1):
            asset["_asset_index"] = index
        asset_checks = [self._check_asset(asset) for asset in assets]
        missing_fields = [
            {
                "asset_index": check["asset_index"],
                "asset_id": check.get("asset_id") or f"asset_{check['asset_index']}",
                "missing": missing,
            }
            for check in asset_checks
            for missing in check["missing"]
        ]

        if not assets:
            status = "blocked_missing_manifest" if generated_claim_present else "brief_only"
        elif missing_fields:
            status = "blocked_incomplete_manifest"
        else:
            status = "manifest_ready"

        return {
            "validator": "asset-manifest-validator",
            "validator_version": self.version,
            "status": status,
            "manifest_found": manifest is not None,
            "generated_claim_present": generated_claim_present,
            "asset_count": len(assets),
            "assets": asset_checks,
            "missing_asset_fields": missing_fields,
            "summary": self._summary(status, len(assets), missing_fields),
        }

    def missing_inputs_from_validation(self, validation: dict[str, Any]) -> list[dict[str, str]]:
        status = validation.get("status")
        if status == "brief_only":
            return []
        if status == "blocked_missing_manifest":
            return [
                {
                    "input_id": "asset_manifest",
                    "reason": "Asset output claims generated files, but no asset manifest was provided.",
                    "severity": "blocking",
                }
            ]
        missing: list[dict[str, str]] = []
        field_map = {
            "asset_type": "asset_manifest_fields",
            "file_reference": "asset_file_reference",
            "source": "asset_manifest_source",
            "commercial_use_status": "asset_commercial_use_status",
            "dimensions": "asset_dimensions",
            "duration_seconds": "asset_duration",
            "file_exists": "asset_file_missing",
        }
        for item in validation.get("missing_asset_fields", []):
            field = str(item.get("missing", "asset_manifest_fields"))
            input_id = field_map.get(field, "asset_manifest_fields")
            missing.append(
                {
                    "input_id": input_id,
                    "reason": f"Asset manifest entry {item.get('asset_id')} is missing {field}.",
                    "severity": "blocking",
                }
            )
        return self._dedupe(missing)

    def _extract_manifest(self, text: str) -> Any:
        for block in re.finditer(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL):
            parsed = self._try_parse_json(block.group(1).strip())
            if self._looks_like_manifest(parsed):
                return parsed
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char not in "[{":
                continue
            try:
                parsed, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if self._looks_like_manifest(parsed):
                return parsed
        return None

    def _generated_claim_present(self, text: str) -> bool:
        if not self.GENERATED_CLAIM_PATTERN.search(text):
            return False
        negated_patterns = [
            r"(?i)no\s+generated\s+files?\s+(?:are\s+)?claimed",
            r"(?i)no\s+actual\s+generated\s+files?",
            r"(?i)not\s+claim(?:ing)?\s+generated\s+files?",
            r"(?i)brief\s+only",
        ]
        if any(re.search(pattern, text) for pattern in negated_patterns):
            return False
        return True

    def _try_parse_json(self, raw: str) -> Any:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _looks_like_manifest(self, parsed: Any) -> bool:
        if isinstance(parsed, list):
            return any(isinstance(item, dict) for item in parsed)
        if not isinstance(parsed, dict):
            return False
        if isinstance(parsed.get("assets"), list):
            return True
        return any(key in parsed for key in ["asset_id", "asset_type", "file_path", "url"])

    def _assets_from_manifest(self, manifest: Any) -> list[dict[str, Any]]:
        if isinstance(manifest, dict) and isinstance(manifest.get("assets"), list):
            return [item for item in manifest["assets"] if isinstance(item, dict)]
        if isinstance(manifest, list):
            return [item for item in manifest if isinstance(item, dict)]
        if isinstance(manifest, dict):
            return [manifest]
        return []

    def _normalize_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        normalized = {self._safe_key(key): value for key, value in asset.items()}
        return {
            "asset_id": self._first(normalized, "asset_id", "id", "name"),
            "asset_type": self._normalize_type(self._first(normalized, "asset_type", "type", "kind")),
            "file_path": self._first(normalized, "file_path", "path", "local_path"),
            "url": self._first(normalized, "url", "public_url", "preview_url"),
            "dimensions": self._first(normalized, "dimensions", "size", "resolution"),
            "width": self._first(normalized, "width"),
            "height": self._first(normalized, "height"),
            "duration_seconds": self._first(normalized, "duration_seconds", "duration", "seconds"),
            "source": self._first(normalized, "source", "source_type", "generator"),
            "commercial_use_status": self._first(
                normalized,
                "commercial_use_status",
                "license",
                "usage_rights",
                "commercial_status",
            ),
            "status": self._first(normalized, "status", "state"),
        }

    def _check_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        missing: list[str] = []
        if not asset.get("asset_type"):
            missing.append("asset_type")
        if not asset.get("file_path") and not asset.get("url"):
            missing.append("file_reference")
        if not asset.get("source"):
            missing.append("source")
        if not asset.get("commercial_use_status"):
            missing.append("commercial_use_status")
        asset_type = str(asset.get("asset_type") or "")
        if self._is_video(asset_type):
            if not asset.get("duration_seconds"):
                missing.append("duration_seconds")
        else:
            if not asset.get("dimensions") and not (asset.get("width") and asset.get("height")):
                missing.append("dimensions")
        file_path = str(asset.get("file_path") or "")
        if file_path and self._is_local_path(file_path) and not Path(file_path).exists():
            missing.append("file_exists")
        return {
            "asset_index": asset.get("_asset_index", 0),
            "asset_id": asset.get("asset_id"),
            "asset_type": asset.get("asset_type"),
            "file_path": asset.get("file_path"),
            "url": asset.get("url"),
            "dimensions": asset.get("dimensions"),
            "width": asset.get("width"),
            "height": asset.get("height"),
            "duration_seconds": asset.get("duration_seconds"),
            "source": asset.get("source"),
            "commercial_use_status": asset.get("commercial_use_status"),
            "status": asset.get("status"),
            "missing": missing,
        }

    def _normalize_type(self, value: Any) -> str:
        return self._safe_key(str(value)) if value is not None else ""

    def _is_video(self, asset_type: str) -> bool:
        return asset_type in self.VIDEO_TYPES or "video" in asset_type

    def _is_local_path(self, file_path: str) -> bool:
        if re.match(r"^[a-zA-Z]:[\\/]", file_path):
            return True
        return file_path.startswith("\\\\") or file_path.startswith("/")

    def _first(self, data: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in data and data[key] not in (None, ""):
                return data[key]
        return None

    def _safe_key(self, value: Any) -> str:
        return re.sub(r"[^a-zA-Z0-9_]+", "_", str(value).strip().lower()).strip("_")

    def _dedupe(self, items: list[dict[str, str]]) -> list[dict[str, str]]:
        seen: set[str] = set()
        deduped: list[dict[str, str]] = []
        for item in items:
            input_id = item["input_id"]
            if input_id in seen:
                continue
            seen.add(input_id)
            deduped.append(item)
        return deduped

    def _summary(self, status: str, asset_count: int, missing_fields: list[dict[str, Any]]) -> str:
        if status == "brief_only":
            return "Asset output is a production brief only; no generated file manifest was claimed."
        if status == "blocked_missing_manifest":
            return "Asset output claims generated files but does not provide an asset manifest."
        if status == "blocked_incomplete_manifest":
            return f"Asset manifest has {asset_count} asset(s), but {len(missing_fields)} required field(s) are missing."
        return f"Asset manifest has {asset_count} traceable asset(s) and can move to review, not real publish."

"""Tenant-scoped source image uploads for grounded media generation."""

from __future__ import annotations

import errno
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode


MAX_MEDIA_SOURCE_BYTES = 5 * 1024 * 1024
SIGNED_URL_TTL_SECONDS = 60 * 60
SOURCE_RETENTION_SECONDS = 24 * 60 * 60
MAX_ACTIVE_ASSETS_PER_COMPANY = 50
MAX_ACTIVE_BYTES_PER_COMPANY = 100 * 1024 * 1024
MAX_IMAGE_EDGE_PIXELS = 12_000
MAX_IMAGE_TOTAL_PIXELS = 80_000_000
_ASSET_ID_PATTERN = re.compile(r"^media_src_[A-Za-z0-9_-]{16,80}$")
_UPLOAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,96}$")


class MediaSourceAssetError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class MediaSourceAsset:
    asset_id: str
    content_type: str
    size_bytes: int
    sha256: str
    original_filename: str
    created_at: int
    retention_expires_at: int
    width: int
    height: int
    file_path: Path

    def public_dict(self, *, source_url: str) -> dict[str, Any]:
        return {
            "contract_version": "2026-07-12-grounded-media-source-upload-v1",
            "asset_id": self.asset_id,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "original_filename": self.original_filename,
            "source_url": source_url,
            "created_at": self.created_at,
            "retention_expires_at": self.retention_expires_at,
            "width": self.width,
            "height": self.height,
            "tenant_scoped": True,
            "signed_url_required": True,
            "triggers_real_platform_write": False,
            "triggers_real_charge": False,
            "secret_exposed": False,
        }


class MediaSourceAssetStore:
    def __init__(
        self,
        *,
        root: Path,
        signing_secret: bytes | None,
        public_base_url: str,
        now: Callable[[], float] = time.time,
        max_assets_per_company: int = MAX_ACTIVE_ASSETS_PER_COMPANY,
        max_bytes_per_company: int = MAX_ACTIVE_BYTES_PER_COMPANY,
    ) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.signing_secret = signing_secret or b""
        self.public_base_url = public_base_url.rstrip("/")
        self.now = now
        self.max_assets_per_company = max(1, int(max_assets_per_company))
        self.max_bytes_per_company = max(MAX_MEDIA_SOURCE_BYTES, int(max_bytes_per_company))
        self._lock = threading.Lock()

    def create(
        self,
        *,
        company_id: str,
        store_id: str,
        user_id: str,
        content_type: str,
        filename: str,
        content: bytes,
        upload_id: str = "",
    ) -> tuple[MediaSourceAsset, str]:
        if not company_id or not store_id or not user_id:
            raise MediaSourceAssetError("identity_missing", "upload identity is incomplete")
        if not content:
            raise MediaSourceAssetError("empty_file", "source image is empty")
        if len(content) > MAX_MEDIA_SOURCE_BYTES:
            raise MediaSourceAssetError("file_too_large", "source image exceeds the 5 MB limit")
        normalized_type, extension, width, height = _validated_image_type(content_type=content_type, content=content)

        upload_id = str(upload_id or "")
        created_at = int(self.now())
        asset_id = self._upload_asset_id(company_id=company_id, store_id=store_id, user_id=user_id,
                                         upload_id=upload_id) if upload_id else f"media_src_{secrets.token_urlsafe(18)}"
        # Fail before any blob/metadata write, not after a source was saved without a usable receipt.
        source_url = self.signed_url(asset_id)
        directory = self.root / asset_id[-2:]
        directory.mkdir(parents=True, exist_ok=True)
        file_path = directory / f"{asset_id}.{extension}"
        metadata_path = directory / f"{asset_id}.json"
        metadata = {
            "asset_id": asset_id,
            "company_id": company_id,
            "store_id": store_id,
            "user_id": user_id,
            "upload_id": upload_id,
            "content_type": normalized_type,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "original_filename": _safe_filename(filename, extension),
            "created_at": created_at,
            "retention_expires_at": created_at + SOURCE_RETENTION_SECONDS,
            "width": width,
            "height": height,
            "file_name": file_path.name,
            "secret_exposed": False,
        }
        with self._company_write_lock(company_id):
            if upload_id and metadata_path.exists():
                existing, existing_url = self.get_by_upload_id(company_id=company_id, store_id=store_id,
                    user_id=user_id, upload_id=upload_id)
                if not hmac.compare_digest(existing.sha256, metadata["sha256"]):
                    raise MediaSourceAssetError("upload_id_conflict", "upload attempt already belongs to different image bytes")
                return existing, existing_url
            if upload_id and any(directory.joinpath(f"{asset_id}.{suffix}").exists() for suffix in ("png", "jpg", "webp")):
                raise MediaSourceAssetError("upload_receipt_incomplete", "upload data exists without a complete receipt; do not resubmit")
            self._cleanup_expired_locked(now=created_at)
            active_count, active_bytes = self._company_usage_locked(company_id=company_id, now=created_at)
            if active_count >= self.max_assets_per_company or active_bytes + len(content) > self.max_bytes_per_company:
                raise MediaSourceAssetError(
                    "tenant_upload_quota_exceeded",
                    "source image upload limit reached; wait for older temporary files to expire",
                )
            _atomic_write(file_path, content)
            _atomic_write(metadata_path, json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        asset = _asset_from_metadata(metadata, file_path=file_path)
        return asset, source_url

    def get_by_upload_id(
        self, *, company_id: str, store_id: str, user_id: str, upload_id: str,
    ) -> tuple[MediaSourceAsset, str]:
        """Read only this authenticated uploader's exact attempt; never list or create assets."""
        asset_id = self._upload_asset_id(company_id=company_id, store_id=store_id, user_id=user_id,
                                         upload_id=upload_id)
        metadata_path = self._metadata_path(asset_id)
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            if any(metadata_path.with_suffix(f".{suffix}").exists() for suffix in ("png", "jpg", "webp")):
                raise MediaSourceAssetError("upload_receipt_incomplete", "upload data exists without a complete receipt; do not resubmit") from exc
            raise MediaSourceAssetError("upload_not_found", "upload receipt is not available; do not automatically resubmit") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise MediaSourceAssetError("asset_unavailable", "upload receipt is unavailable") from exc
        if not isinstance(metadata, dict) or any(not hmac.compare_digest(str(metadata.get(key) or ""), expected)
            for key, expected in (("company_id", company_id), ("store_id", store_id), ("user_id", user_id),
                                  ("upload_id", upload_id), ("asset_id", asset_id))):
            raise MediaSourceAssetError("upload_not_found", "upload receipt is not available; do not automatically resubmit")
        asset, _ = self.read_for_provider(asset_id=asset_id, company_id=company_id, store_id=store_id)
        return asset, self.signed_url(asset.asset_id)

    def recover_owned_asset(self, *, company_id: str, store_id: str, user_id: str,
                            asset_id: str) -> tuple[MediaSourceAsset, str, str]:
        """Recover a known job's source, never enumerate uploads or widen ownership."""
        try:
            metadata = json.loads(self._metadata_path(asset_id).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise MediaSourceAssetError("upload_not_found", "original source receipt unavailable") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise MediaSourceAssetError("asset_unavailable", "original source receipt unavailable") from exc
        if not isinstance(metadata, dict) or any(not hmac.compare_digest(str(metadata.get(key) or ""), expected)
            for key, expected in (("company_id", company_id), ("store_id", store_id), ("user_id", user_id), ("asset_id", asset_id))):
            raise MediaSourceAssetError("upload_not_found", "original source receipt unavailable")
        upload_id = str(metadata.get("upload_id") or "")
        asset, url = self.get_by_upload_id(company_id=company_id, store_id=store_id,
                                          user_id=user_id, upload_id=upload_id)
        if asset.asset_id != asset_id:
            raise MediaSourceAssetError("upload_not_found", "original source receipt unavailable")
        return asset, url, upload_id

    @staticmethod
    def _upload_asset_id(*, company_id: str, store_id: str, user_id: str, upload_id: str) -> str:
        if not company_id or not store_id or not user_id:
            raise MediaSourceAssetError("identity_missing", "upload identity is incomplete")
        if not _UPLOAD_ID_PATTERN.fullmatch(str(upload_id or "")):
            raise MediaSourceAssetError("invalid_upload_id", "upload attempt id must be 16 to 96 URL-safe characters")
        scope = json.dumps(["media-source-upload-v1", company_id, store_id, user_id, upload_id], separators=(",", ":"))
        return "media_src_" + hashlib.sha256(scope.encode("utf-8")).hexdigest()

    @contextmanager
    def _company_write_lock(self, company_id: str):
        """OS-owned lock covers this company's quota check and write, including legacy uploads.

        Lock files deliberately persist: file existence never means lock ownership. Closing the
        descriptor or terminating a process releases the lock on Windows and POSIX. Never unlink
        the lock file, which could split concurrent callers onto different locked inodes.
        """
        lock_directory = self.root / ".source-upload-locks"
        lock_directory.mkdir(parents=True, exist_ok=True)
        lock_path = lock_directory / (hashlib.sha256(company_id.encode("utf-8")).hexdigest() + ".lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        deadline = time.monotonic() + 2.0
        acquired = False
        try:
            if os.fstat(descriptor).st_size == 0:
                try:
                    os.write(descriptor, b"\0")  # Windows byte-range lock uses a stable first byte.
                except OSError as exc:
                    # Another creator can initialize and lock that byte after our size check.
                    if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
            while not acquired:
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    if time.monotonic() >= deadline:
                        raise MediaSourceAssetError("upload_in_progress", "upload attempt is still being reconciled; query its receipt")
                    time.sleep(0.02)
            with self._lock:
                yield
        finally:
            try:
                if acquired:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def signed_url(self, asset_id: str, *, ttl_seconds: int = SIGNED_URL_TTL_SECONDS) -> str:
        if not self.signing_secret:
            raise MediaSourceAssetError("signing_unavailable", "media source signing is unavailable")
        if not _ASSET_ID_PATTERN.fullmatch(asset_id):
            raise MediaSourceAssetError("invalid_asset_id", "invalid media source asset id")
        expires = int(self.now()) + max(60, min(int(ttl_seconds), SIGNED_URL_TTL_SECONDS))
        signature = self._signature(asset_id=asset_id, expires=expires)
        query = urlencode({"expires": expires, "signature": signature})
        return f"{self.public_base_url}/media-source-assets/{asset_id}/content?{query}"

    def resolve(self, *, asset_id: str, expires: Any, signature: str) -> MediaSourceAsset:
        if not self.signing_secret:
            raise MediaSourceAssetError("signing_unavailable", "media source signing is unavailable")
        if not _ASSET_ID_PATTERN.fullmatch(asset_id):
            raise MediaSourceAssetError("invalid_asset_id", "invalid media source asset id")
        try:
            expires_value = int(str(expires))
        except (TypeError, ValueError) as exc:
            raise MediaSourceAssetError("invalid_expiry", "invalid media source expiry") from exc
        if expires_value < int(self.now()):
            raise MediaSourceAssetError("signed_url_expired", "media source link expired")
        expected = self._signature(asset_id=asset_id, expires=expires_value)
        if not signature or not hmac.compare_digest(signature, expected):
            raise MediaSourceAssetError("invalid_signature", "invalid media source signature")
        metadata_path = self._metadata_path(asset_id)
        if not metadata_path.exists():
            raise MediaSourceAssetError("asset_not_found", "media source asset not found")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MediaSourceAssetError("asset_unavailable", "media source asset is unavailable") from exc
        if int(metadata.get("retention_expires_at") or 0) < int(self.now()):
            raise MediaSourceAssetError("asset_expired", "media source asset retention expired")
        file_path = metadata_path.with_name(str(metadata.get("file_name") or ""))
        if not file_path.is_file() or file_path.parent != metadata_path.parent:
            raise MediaSourceAssetError("asset_unavailable", "media source asset file is unavailable")
        return _asset_from_metadata(metadata, file_path=file_path)

    def read_for_provider(
        self,
        *,
        asset_id: str,
        company_id: str,
        store_id: str,
    ) -> tuple[MediaSourceAsset, bytes]:
        """Read one retained source image for an in-memory provider request."""
        if not _ASSET_ID_PATTERN.fullmatch(asset_id):
            raise MediaSourceAssetError("invalid_asset_id", "invalid media source asset id")
        metadata_path = self._metadata_path(asset_id)
        if not metadata_path.exists():
            raise MediaSourceAssetError("asset_not_found", "media source asset not found")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MediaSourceAssetError("asset_unavailable", "media source asset is unavailable") from exc
        if not hmac.compare_digest(str(metadata.get("company_id") or ""), str(company_id or "")):
            raise MediaSourceAssetError("asset_scope_mismatch", "media source asset is not available to this company")
        if not hmac.compare_digest(str(metadata.get("store_id") or ""), str(store_id or "")):
            raise MediaSourceAssetError("asset_scope_mismatch", "media source asset is not available to this store")
        if int(metadata.get("retention_expires_at") or 0) < int(self.now()):
            raise MediaSourceAssetError("asset_expired", "media source asset retention expired")
        file_path = metadata_path.with_name(str(metadata.get("file_name") or ""))
        if not file_path.is_file() or file_path.parent != metadata_path.parent:
            raise MediaSourceAssetError("asset_unavailable", "media source asset file is unavailable")
        asset = _asset_from_metadata(metadata, file_path=file_path)
        try:
            content = file_path.read_bytes()
        except OSError as exc:
            raise MediaSourceAssetError("asset_unavailable", "media source asset file is unavailable") from exc
        if hashlib.sha256(content).hexdigest() != asset.sha256:
            raise MediaSourceAssetError("asset_integrity_failed", "media source asset integrity check failed")
        return asset, content

    def purge_store(self, *, company_id: str, store_id: str) -> dict[str, Any]:
        """Delete every retained source asset owned by one store."""

        removed_files = 0
        removed_metadata = 0
        with self._lock:
            for metadata_path in self.root.glob("*/*.json"):
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if str(metadata.get("company_id") or "") != str(company_id or ""):
                    continue
                if str(metadata.get("store_id") or "") != str(store_id or ""):
                    continue
                file_path = metadata_path.with_name(str(metadata.get("file_name") or ""))
                if file_path.is_file() and file_path.parent == metadata_path.parent:
                    file_path.unlink(missing_ok=True)
                    removed_files += 1
                metadata_path.unlink(missing_ok=True)
                removed_metadata += 1
        return {
            "removed_files": removed_files,
            "removed_metadata": removed_metadata,
            "other_stores_mutated": False,
            "secret_exposed": False,
        }

    def _signature(self, *, asset_id: str, expires: int) -> str:
        payload = f"{asset_id}:{expires}".encode("utf-8")
        return hmac.new(self.signing_secret, payload, hashlib.sha256).hexdigest()

    def _metadata_path(self, asset_id: str) -> Path:
        return self.root / asset_id[-2:] / f"{asset_id}.json"

    def _cleanup_expired_locked(self, *, now: int) -> None:
        for metadata_path in self.root.glob("*/*.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if int(metadata.get("retention_expires_at") or 0) >= now:
                continue
            file_path = metadata_path.with_name(str(metadata.get("file_name") or ""))
            for target in (file_path, metadata_path):
                try:
                    if target.is_file() and target.parent == metadata_path.parent:
                        target.unlink()
                except OSError:
                    pass

    def _company_usage_locked(self, *, company_id: str, now: int) -> tuple[int, int]:
        count = 0
        size_bytes = 0
        for metadata_path in self.root.glob("*/*.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if str(metadata.get("company_id") or "") != company_id:
                continue
            if int(metadata.get("retention_expires_at") or 0) < now:
                continue
            count += 1
            size_bytes += max(0, int(metadata.get("size_bytes") or 0))
        return count, size_bytes


def _validated_image_type(*, content_type: str, content: bytes) -> tuple[str, str, int, int]:
    claimed = str(content_type or "").split(";", 1)[0].strip().lower()
    detected = ""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = "image/png"
    elif content.startswith(b"\xff\xd8\xff"):
        detected = "image/jpeg"
    elif len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        detected = "image/webp"
    if detected not in {"image/png", "image/jpeg", "image/webp"}:
        raise MediaSourceAssetError("unsupported_image", "only verified PNG, JPEG and WEBP source images are accepted")
    if claimed and claimed not in {detected, "application/octet-stream"}:
        raise MediaSourceAssetError("content_type_mismatch", "source image type does not match its file content")
    dimensions = _image_dimensions(detected, content)
    if not dimensions:
        raise MediaSourceAssetError("invalid_image_structure", "source image structure is invalid")
    width, height = dimensions
    if width > MAX_IMAGE_EDGE_PIXELS or height > MAX_IMAGE_EDGE_PIXELS or width * height > MAX_IMAGE_TOTAL_PIXELS:
        raise MediaSourceAssetError("image_dimensions_too_large", "source image dimensions exceed the safe processing limit")
    return detected, {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[detected], width, height


def _image_dimensions(content_type: str, content: bytes) -> tuple[int, int] | None:
    if content_type == "image/png":
        if len(content) < 33 or content[12:16] != b"IHDR":
            return None
        return int.from_bytes(content[16:20], "big"), int.from_bytes(content[20:24], "big")
    if content_type == "image/jpeg":
        index = 2
        while index + 9 < len(content):
            if content[index] != 0xFF:
                index += 1
                continue
            marker = content[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(content):
                return None
            segment_length = int.from_bytes(content[index : index + 2], "big")
            if segment_length < 2 or index + segment_length > len(content):
                return None
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if segment_length < 7:
                    return None
                return int.from_bytes(content[index + 5 : index + 7], "big"), int.from_bytes(content[index + 3 : index + 5], "big")
            index += segment_length
        return None
    if content_type == "image/webp":
        chunk = content[12:16]
        if chunk == b"VP8X" and len(content) >= 30:
            width = 1 + int.from_bytes(content[24:27], "little")
            height = 1 + int.from_bytes(content[27:30], "little")
            return width, height
        if chunk == b"VP8L" and len(content) >= 25 and content[20] == 0x2F:
            bits = int.from_bytes(content[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        marker = content.find(b"\x9d\x01\x2a", 20, min(len(content), 96))
        if chunk == b"VP8 " and marker >= 0 and marker + 7 <= len(content):
            width = int.from_bytes(content[marker + 3 : marker + 5], "little") & 0x3FFF
            height = int.from_bytes(content[marker + 5 : marker + 7], "little") & 0x3FFF
            return width, height
    return None


def _safe_filename(filename: str, extension: str) -> str:
    base = os.path.basename(str(filename or "source-image"))
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(base).stem).strip(".-")[:80] or "source-image"
    return f"{stem}.{extension}"


def _asset_from_metadata(metadata: dict[str, Any], *, file_path: Path) -> MediaSourceAsset:
    return MediaSourceAsset(
        asset_id=str(metadata.get("asset_id") or ""),
        content_type=str(metadata.get("content_type") or "application/octet-stream"),
        size_bytes=int(metadata.get("size_bytes") or 0),
        sha256=str(metadata.get("sha256") or ""),
        original_filename=str(metadata.get("original_filename") or "source-image"),
        created_at=int(metadata.get("created_at") or 0),
        retention_expires_at=int(metadata.get("retention_expires_at") or 0),
        width=int(metadata.get("width") or 0),
        height=int(metadata.get("height") or 0),
        file_path=file_path,
    )


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)

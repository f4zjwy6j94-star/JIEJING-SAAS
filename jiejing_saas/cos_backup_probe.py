"""Synthetic COS upload/readback/delete proof for backup readiness.

The probe never uploads application or merchant data. Its result deliberately
omits credentials, bucket names and object keys so it is safe for operator logs.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any


CONTRACT_VERSION = "jiejing_cos_backup_probe_v1"
DEFAULT_PREFIX = "jiejing/staging/backups"


def execute_cos_backup_probe(
    *,
    env: Mapping[str, str] | None = None,
    client_factory: Callable[..., Any] | None = None,
    now_utc: datetime | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Run one private synthetic COS probe and return redacted evidence."""

    values = os.environ if env is None else env
    enabled = values.get("JIEJING_COS_BACKUP_ENABLED", "").strip().lower() == "true"
    region = values.get("JIEJING_COS_REGION", "").strip() or values.get("JIEJING_TENCENT_REGION", "").strip()
    bucket = values.get("JIEJING_COS_BUCKET", "").strip()
    secret_id = values.get("JIEJING_TENCENT_SECRET_ID", "").strip()
    secret_key = values.get("JIEJING_TENCENT_SECRET_KEY", "").strip()
    token = values.get("JIEJING_TENCENT_TOKEN", "").strip() or None
    blockers = []
    if not enabled:
        blockers.append("cos_backup_not_enabled")
    if not region:
        blockers.append("cos_region_missing")
    if not bucket:
        blockers.append("cos_bucket_missing")
    if not secret_id or not secret_key:
        blockers.append("tencent_api_credentials_missing")
    if blockers:
        return _result(status="blocked", blockers=blockers)

    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    probe_nonce = nonce or uuid.uuid4().hex
    prefix = values.get("JIEJING_COS_PREFIX", "").strip().strip("/") or DEFAULT_PREFIX
    object_key = f"{prefix}/probes/cos-backup-{now:%Y%m%dT%H%M%SZ}-{probe_nonce}.json"
    payload = json.dumps(
        {
            "contract_version": CONTRACT_VERSION,
            "generated_at": now.isoformat(),
            "nonce": probe_nonce,
            "probe": True,
            "synthetic_data_only": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    factory = client_factory or _default_client_factory
    put_attempted = False
    sha256_match = False
    object_deleted = False
    error_type: str | None = None

    try:
        client = factory(region=region, secret_id=secret_id, secret_key=secret_key, token=token)
        put_attempted = True
        client.put_object(
            Bucket=bucket,
            Body=payload,
            Key=object_key,
            ContentType="application/json",
            EnableMD5=True,
            ServerSideEncryption="AES256",
        )
        response = client.get_object(Bucket=bucket, Key=object_key)
        body = response["Body"].get_raw_stream().read()
        sha256_match = hashlib.sha256(body).hexdigest() == expected_sha256
        if not sha256_match:
            error_type = "ReadbackHashMismatch"
    except Exception as exc:  # SDK failures are redacted to their type only.
        error_type = type(exc).__name__
    finally:
        if put_attempted:
            try:
                client.delete_object(Bucket=bucket, Key=object_key)
                object_deleted = True
            except Exception as exc:  # Keep the known object key out of logs.
                object_deleted = False
                error_type = error_type or type(exc).__name__

    verified = sha256_match and object_deleted and error_type is None
    return _result(
        status="verified" if verified else "blocked",
        blockers=[] if verified else ["cos_backup_probe_failed"],
        payload_bytes=len(payload),
        sha256_match=sha256_match,
        object_deleted=object_deleted,
        success_at=now.isoformat() if verified else None,
        error_type=error_type,
    )


def _default_client_factory(*, region: str, secret_id: str, secret_key: str, token: str | None) -> Any:
    from qcloud_cos import CosConfig, CosS3Client

    config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token, Scheme="https")
    return CosS3Client(config)


def _result(
    *,
    status: str,
    blockers: list[str],
    payload_bytes: int = 0,
    sha256_match: bool = False,
    object_deleted: bool = False,
    success_at: str | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "contract_version": CONTRACT_VERSION,
        "probe": True,
        "synthetic_data_only": True,
        "server_side_encryption_requested": True,
        "payload_bytes": payload_bytes,
        "sha256_match": sha256_match,
        "object_deleted": object_deleted,
        "success_at": success_at,
        "blockers": blockers,
        "error_type": error_type,
        "secret_exposed": False,
    }

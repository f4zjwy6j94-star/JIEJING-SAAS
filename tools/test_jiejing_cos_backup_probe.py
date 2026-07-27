#!/usr/bin/env python3
"""Behavior checks for the non-secret COS backup probe."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "jiejing_cos_backup_probe.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.cos_backup_probe import execute_cos_backup_probe  # noqa: E402


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def get_raw_stream(self) -> io.BytesIO:
        return io.BytesIO(self._payload)


class _RecordingCosClient:
    def __init__(self) -> None:
        self.payload = b""
        self.put_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []

    def put_object(self, **kwargs: object) -> dict[str, str]:
        self.put_calls.append(kwargs)
        self.payload = kwargs["Body"]  # type: ignore[assignment]
        return {"ETag": "synthetic-etag"}

    def get_object(self, **_kwargs: object) -> dict[str, _Body]:
        return {"Body": _Body(self.payload)}

    def delete_object(self, **kwargs: object) -> dict[str, str]:
        self.delete_calls.append(kwargs)
        return {"status": "deleted"}


class _TamperedReadbackClient(_RecordingCosClient):
    def get_object(self, **_kwargs: object) -> dict[str, _Body]:
        return {"Body": _Body(b"tampered")}


class _DeleteFailureClient(_RecordingCosClient):
    def delete_object(self, **kwargs: object) -> dict[str, str]:
        self.delete_calls.append(kwargs)
        raise RuntimeError("sensitive provider detail must not be logged")


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    client = _RecordingCosClient()
    env = {
        "JIEJING_COS_BACKUP_ENABLED": "true",
        "JIEJING_COS_REGION": "ap-guangzhou",
        "JIEJING_COS_BUCKET": "private-bucket-should-not-leak",
        "JIEJING_COS_PREFIX": "jiejing/staging/backups",
        "JIEJING_TENCENT_SECRET_ID": "secret-id-should-not-leak",
        "JIEJING_TENCENT_SECRET_KEY": "secret-key-should-not-leak",
    }
    result = execute_cos_backup_probe(
        env=env,
        client_factory=lambda **_kwargs: client,
        now_utc=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        nonce="0123456789abcdef0123456789abcdef",
    )
    if result.get("status") != "verified":
        return fail(f"successful upload/readback/delete should verify: {result}")
    if result.get("sha256_match") is not True or result.get("object_deleted") is not True:
        return fail(f"verified result must prove readback and deletion: {result}")
    if result.get("success_at") != "2026-07-27T12:00:00+00:00":
        return fail(f"verified result must expose a recordable UTC success time: {result}")
    if len(client.put_calls) != 1 or len(client.delete_calls) != 1:
        return fail("probe must upload and delete exactly one synthetic object")
    put = client.put_calls[0]
    if put.get("ServerSideEncryption") != "AES256":
        return fail("probe object must request server-side encryption")
    if not isinstance(put.get("Body"), bytes) or b"probe" not in put["Body"]:  # type: ignore[operator]
        return fail("probe must upload a synthetic payload")
    dumped = json.dumps(result, sort_keys=True)
    for forbidden in (
        env["JIEJING_COS_BUCKET"],
        env["JIEJING_TENCENT_SECRET_ID"],
        env["JIEJING_TENCENT_SECRET_KEY"],
        "0123456789abcdef0123456789abcdef",
    ):
        if forbidden in dumped:
            return fail("probe result must not expose credentials, bucket names, object keys, or nonces")

    tampered_client = _TamperedReadbackClient()
    tampered = execute_cos_backup_probe(
        env=env,
        client_factory=lambda **_kwargs: tampered_client,
        now_utc=datetime(2026, 7, 27, 12, 1, tzinfo=timezone.utc),
        nonce="fedcba9876543210fedcba9876543210",
    )
    if tampered.get("status") != "blocked" or tampered.get("success_at") is not None:
        return fail(f"hash mismatch must fail closed without recordable evidence: {tampered}")
    if tampered.get("object_deleted") is not True or len(tampered_client.delete_calls) != 1:
        return fail("hash mismatch must still delete the synthetic object")

    delete_failure_client = _DeleteFailureClient()
    delete_failed = execute_cos_backup_probe(
        env=env,
        client_factory=lambda **_kwargs: delete_failure_client,
        now_utc=datetime(2026, 7, 27, 12, 2, tzinfo=timezone.utc),
        nonce="abcdef0123456789abcdef0123456789",
    )
    if delete_failed.get("status") != "blocked" or delete_failed.get("success_at") is not None:
        return fail(f"cleanup failure must fail closed without recordable evidence: {delete_failed}")
    if "sensitive provider detail" in json.dumps(delete_failed):
        return fail("provider exception messages must be redacted from probe output")

    cli_env = os.environ.copy()
    for key in (
        "JIEJING_COS_BACKUP_ENABLED",
        "JIEJING_COS_REGION",
        "JIEJING_COS_BUCKET",
        "JIEJING_TENCENT_SECRET_ID",
        "JIEJING_TENCENT_SECRET_KEY",
    ):
        cli_env.pop(key, None)
    blocked = subprocess.run(
        [sys.executable, str(TOOL)],
        cwd=ROOT,
        env=cli_env,
        text=True,
        capture_output=True,
        check=False,
    )
    if blocked.returncode != 2:
        return fail(f"unconfigured CLI probe must fail closed: {blocked.stdout} {blocked.stderr}")
    try:
        blocked_result = json.loads(blocked.stdout)
    except json.JSONDecodeError:
        return fail("CLI probe must emit one machine-readable redacted result")
    if blocked_result.get("status") != "blocked" or blocked_result.get("success_at") is not None:
        return fail(f"blocked CLI probe must never emit recordable success evidence: {blocked_result}")
    if blocked_result.get("secret_exposed") is not False:
        return fail("CLI probe must explicitly attest that output is redacted")
    print("PASS jiejing_cos_backup_probe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

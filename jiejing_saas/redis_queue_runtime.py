"""Redis Streams runtime queue for Jiejing SaaS workers.

The database remains the system of record for merchant-visible task state,
reports, confirmations and audit logs. Redis is the distributed delivery layer:
API requests create a DB queue row, then publish the job reference to Redis.
Workers consume the Redis stream, claim the DB row atomically, run the same
safe worker logic, and acknowledge or dead-letter the stream message.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .config import SaaSSettings
from .runtime_bridge import RuntimeBridge
from .repository import SaaSRepository
from .worker import LocalQueueWorker


DEFAULT_STREAM = "jiejing:queue"
DEFAULT_DEAD_LETTER_STREAM = "jiejing:queue:dead"
DEFAULT_GROUP = "jiejing-workers"


def publish_redis_queue_job_if_configured(job: dict[str, Any]) -> dict[str, Any]:
    provider = os.environ.get("JIEJING_QUEUE_PROVIDER", "local_worker").strip().lower() or "local_worker"
    if provider != "redis_streams":
        return {"status": "skipped_local_queue_provider", "required": False, "secret_exposed": False}
    queue_url = os.environ.get("JIEJING_QUEUE_URL") or ""
    if not queue_url:
        return {
            "status": "failed",
            "required": True,
            "error": "missing_queue_url",
            "queue_url_public": "",
            "secret_exposed": False,
        }
    try:
        client = _redis_client(queue_url)
        stream = _stream_name()
        _ensure_consumer_group(client, stream)
        message_id = client.xadd(
            stream,
            {
                "job_id": str(job.get("job_id") or ""),
                "company_id": str(job.get("company_id") or ""),
                "task_id": str(job.get("task_id") or ""),
                "kind": str((job.get("job") if isinstance(job.get("job"), dict) else {}).get("kind") or "saas_task"),
            },
        )
    except Exception as exc:  # pragma: no cover - needs live Redis
        return {
            "status": "failed",
            "required": True,
            "error_type": exc.__class__.__name__,
            "message": str(exc)[:240],
            "queue_url_public": _redact_url(queue_url),
            "secret_exposed": False,
        }
    return {
        "status": "published",
        "required": True,
        "stream": stream,
        "message_id": _decode(message_id),
        "queue_url_public": _redact_url(queue_url),
        "secret_exposed": False,
    }


class RedisStreamQueueWorker(LocalQueueWorker):
    def __init__(self, *, repository: SaaSRepository, runtime_bridge: RuntimeBridge, settings: SaaSSettings | None = None) -> None:
        super().__init__(repository=repository, runtime_bridge=runtime_bridge, settings=settings)
        self.queue_url = os.environ.get("JIEJING_QUEUE_URL") or ""
        self.stream = _stream_name()
        self.dead_letter_stream = os.environ.get("JIEJING_REDIS_DEAD_LETTER_STREAM", DEFAULT_DEAD_LETTER_STREAM)
        self.group = os.environ.get("JIEJING_REDIS_CONSUMER_GROUP", DEFAULT_GROUP)
        self.consumer = os.environ.get("JIEJING_REDIS_CONSUMER", f"jiejing-worker-{os.getpid()}")

    def run_next(self, *, company_id: str | None = None, job_id: str | None = None) -> dict[str, Any]:
        if not self.queue_url:
            return {
                "status": "failed",
                "error": "Redis queue provider selected but JIEJING_QUEUE_URL is not configured.",
                "queue_provider": "redis_streams",
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
        try:
            client = _redis_client(self.queue_url)
            _ensure_consumer_group(client, self.stream, group=self.group)
            message = self._read_stream_message(client)
        except Exception as exc:  # pragma: no cover - needs live Redis
            return {
                "status": "failed",
                "error_type": exc.__class__.__name__,
                "error": str(exc)[:240],
                "queue_provider": "redis_streams",
                "queue_url_public": _redact_url(self.queue_url),
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
        if not message:
            return {
                "status": "idle",
                "message": "No Redis stream job is waiting for the Jiejing worker.",
                "queue_provider": "redis_streams",
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
        message_id, fields = message
        stream_job_id = str(fields.get("job_id") or "")
        stream_company_id = str(fields.get("company_id") or "")
        if job_id and stream_job_id != job_id:
            self._dead_letter(client, message_id, fields, reason="unexpected_job_id_for_manual_run")
            client.xack(self.stream, self.group, message_id)
            return {
                "status": "failed",
                "error": "Redis stream returned a different job_id for this manual worker run.",
                "expected_job_id": job_id,
                "actual_job_id": stream_job_id,
                "queue_provider": "redis_streams",
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
        if company_id and stream_company_id != company_id:
            self._dead_letter(client, message_id, fields, reason="unexpected_company_id_for_worker")
            client.xack(self.stream, self.group, message_id)
            return {
                "status": "failed",
                "error": "Redis stream returned a job for another company.",
                "queue_provider": "redis_streams",
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
        claimed = self.repository.claim_next_queue_job(company_id=stream_company_id or company_id, job_id=stream_job_id or job_id)
        if not claimed:
            self._dead_letter(client, message_id, fields, reason="db_queue_job_not_claimable")
            client.xack(self.stream, self.group, message_id)
            return {
                "status": "failed",
                "error": "Redis stream job could not be claimed from the SaaS database queue table.",
                "queue_provider": "redis_streams",
                "redis_message_id": _decode(message_id),
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
        result = self.run_claimed_job(claimed)
        if result.get("status") == "failed":
            self._dead_letter(client, message_id, fields, reason=str(result.get("error") or "worker_failed")[:120])
        client.xack(self.stream, self.group, message_id)
        result["queue_provider"] = "redis_streams"
        result["redis_message_id"] = _decode(message_id)
        result["secret_exposed"] = False
        return result

    def _read_stream_message(self, client: Any) -> tuple[str, dict[str, str]] | None:
        response = client.xreadgroup(
            self.group,
            self.consumer,
            {self.stream: ">"},
            count=1,
            block=int(os.environ.get("JIEJING_REDIS_WORKER_BLOCK_MS", "1000")),
        )
        if not response:
            return None
        _stream, messages = response[0]
        if not messages:
            return None
        message_id, raw_fields = messages[0]
        return _decode(message_id), {_decode(key): _decode(value) for key, value in dict(raw_fields).items()}

    def _dead_letter(self, client: Any, message_id: str, fields: dict[str, str], *, reason: str) -> None:
        client.xadd(
            self.dead_letter_stream,
            {
                **fields,
                "failed_message_id": _decode(message_id),
                "failure_reason": reason,
            },
        )


def redis_runtime_status(settings: SaaSSettings) -> dict[str, Any]:
    return {
        "queue_provider": settings.queue_provider,
        "redis_stream_worker_implemented": True,
        "redis_dispatch_on_enqueue_implemented": True,
        "stream": _stream_name(),
        "dead_letter_stream": os.environ.get("JIEJING_REDIS_DEAD_LETTER_STREAM", DEFAULT_DEAD_LETTER_STREAM),
        "consumer_group": os.environ.get("JIEJING_REDIS_CONSUMER_GROUP", DEFAULT_GROUP),
        "queue_url_configured": bool(os.environ.get("JIEJING_QUEUE_URL")),
        "queue_url_public": _redact_url(os.environ.get("JIEJING_QUEUE_URL") or ""),
        "secret_exposed": False,
    }


def _redis_client(queue_url: str) -> Any:
    try:
        import redis  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on deployment image
        raise RuntimeError("Redis queue provider selected but redis-py is not installed.") from exc
    return redis.Redis.from_url(queue_url, socket_connect_timeout=5, socket_timeout=10, decode_responses=False)


def _ensure_consumer_group(client: Any, stream: str, *, group: str = DEFAULT_GROUP) -> None:
    try:
        client.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def _stream_name() -> str:
    return os.environ.get("JIEJING_REDIS_STREAM", DEFAULT_STREAM)


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _redact_url(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[invalid-url]"
    netloc = parsed.netloc
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        username = userinfo.split(":", 1)[0]
        netloc = f"{username}:***@{host}" if username else f"***@{host}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))

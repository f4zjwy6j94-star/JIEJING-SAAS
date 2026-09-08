"""Read only the six nonsecret maintenance evidence values, without env reload."""
from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone
import stat
import hashlib
import uuid

CONTRACT_VERSION = "jiejing_runtime_evidence_snapshot_v1"
EVIDENCE_KEYS = (
    "JIEJING_COS_BACKUP_LAST_SUCCESS_AT",
    "JIEJING_CLS_LIVE_PROBE_LAST_AT",
    "JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED",
    "JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT",
    "JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT",
    "JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT",
)
INGESTION_KEY = "JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED"
MAX_SNAPSHOT_BYTES = 16 * 1024


class RuntimeEvidenceError(ValueError):
    """A fixed safe classification, never a path, raw value or provider error."""


def _absolute_path(value: str | Path) -> Path:
    path = Path(value)
    if os.name != "posix" or not path.is_absolute() or ".." in path.parts:
        raise RuntimeEvidenceError("runtime_evidence_path_untrusted")
    return path


def _directory_fd(path: Path, *, exact_mode: int | None = None) -> int:
    """Open each ancestor without following links; verify the opened inode."""
    path = _absolute_path(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    try:
        for component in (None, *path.parts[1:]):
            if component is not None:
                child = os.open(component, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            info = os.fstat(descriptor)
            if info.st_uid != 0 or info.st_gid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
                raise RuntimeEvidenceError("runtime_evidence_directory_untrusted")
        if exact_mode is not None and stat.S_IMODE(os.fstat(descriptor).st_mode) != exact_mode:
            raise RuntimeEvidenceError("runtime_evidence_directory_untrusted")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_trusted_file(path: Path, *, mode: int, limit: int, parent_mode: int | None = None) -> bytes:
    path = _absolute_path(path)
    parent = _directory_fd(path.parent, exact_mode=parent_mode)
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        descriptor = os.open(path.name, flags, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
                    or stat.S_IMODE(info.st_mode) != mode):
                raise RuntimeEvidenceError("runtime_evidence_file_untrusted")
            if info.st_size > limit:
                raise RuntimeEvidenceError("runtime_evidence_oversized")
            raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise RuntimeEvidenceError("runtime_evidence_oversized")
            return raw
    finally:
        os.close(parent)


def prepare_runtime_evidence_directory(output_dir: str | Path) -> None:
    """Create only a new final component; never repair an existing permission."""
    path = _absolute_path(output_dir)
    if os.geteuid() != 0 or path == Path("/"):
        raise RuntimeEvidenceError("runtime_evidence_directory_untrusted")
    parent = _directory_fd(path.parent)
    try:
        created = False
        try:
            os.mkdir(path.name, 0o755, dir_fd=parent)
            created = True
        except FileExistsError:
            pass
        descriptor = _directory_fd(path)
        try:
            if created:
                os.fchmod(descriptor, 0o755)
                os.fsync(descriptor)
                os.fsync(parent)
            if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o755:
                raise RuntimeEvidenceError("runtime_evidence_directory_untrusted")
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeEvidenceError("runtime_evidence_duplicate_key")
        result[key] = value
    return result


def _decode_snapshot(raw: bytes) -> dict[str, str]:
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise RuntimeEvidenceError("runtime_evidence_oversized")
    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    if (not isinstance(payload, dict) or set(payload) != {"version", "evidence"}
            or type(payload["version"]) is not int or payload["version"] != 1):
        raise RuntimeEvidenceError("runtime_evidence_schema_invalid")
    evidence = payload["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != set(EVIDENCE_KEYS):
        raise RuntimeEvidenceError("runtime_evidence_schema_invalid")
    result = {}
    for key in EVIDENCE_KEYS:
        value = evidence[key]
        if key == INGESTION_KEY:
            if type(value) is not bool:
                raise RuntimeEvidenceError("runtime_evidence_type_invalid")
            result[key] = "true" if value else "false"
        else:
            if not isinstance(value, str) or not 1 <= len(value) <= 80:
                raise RuntimeEvidenceError("runtime_evidence_timestamp_invalid")
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError("timezone_required")
                # Freshness consumers normalize to UTC. Offset timestamps at
                # datetime's year limits must fail here, not escape as a 500.
                parsed.astimezone(timezone.utc)
            except (ValueError, OverflowError):
                raise RuntimeEvidenceError("runtime_evidence_timestamp_invalid") from None
            result[key] = value
    return result


def read_runtime_evidence() -> dict[str, str]:
    if "JIEJING_RUNTIME_EVIDENCE_FILE" not in os.environ:
        return {key: os.environ.get(key, "").strip() for key in EVIDENCE_KEYS}
    try:
        path = _absolute_path(os.environ["JIEJING_RUNTIME_EVIDENCE_FILE"])
        return _decode_snapshot(_read_trusted_file(path, mode=0o644, limit=MAX_SNAPSHOT_BYTES, parent_mode=0o755))
    except RuntimeEvidenceError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise RuntimeEvidenceError("runtime_evidence_invalid") from None


def write_runtime_evidence_snapshot(env_file: str | Path, output_dir: str | Path) -> str:
    """Publish a bounded nonsecret snapshot; the caller owns the maintenance lock."""
    source, destination = _absolute_path(env_file), _absolute_path(output_dir)
    if (os.geteuid() != 0 or destination == Path("/") or source.parent == destination
            or source.parent in destination.parents or destination in source.parent.parents):
        raise RuntimeEvidenceError("runtime_evidence_output_untrusted")
    raw_env = _read_trusted_file(source, mode=0o600, limit=1024 * 1024)
    values = {}
    allowed = {key.encode("ascii"): key for key in EVIDENCE_KEYS}
    for line in raw_env.splitlines():
        key, separator, value = line.partition(b"=")
        key = key.strip()
        if not separator or key not in allowed:
            continue
        name = allowed[key]
        if name in values:
            raise RuntimeEvidenceError("runtime_evidence_duplicate_key")
        text = value.strip().decode("utf-8")
        if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
            text = text[1:-1]
        if name == INGESTION_KEY:
            normalized = text.lower()
            if normalized not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
                raise RuntimeEvidenceError("runtime_evidence_type_invalid")
            values[name] = normalized in {"true", "1", "yes", "on"}
        else:
            values[name] = text
    raw = (json.dumps({"version": 1, "evidence": values}, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    _decode_snapshot(raw)
    descriptor = _directory_fd(destination, exact_mode=0o755)
    temporary = ".current.json." + uuid.uuid4().hex
    try:
        try:
            _read_trusted_file(destination / "current.json", mode=0o644, limit=MAX_SNAPSHOT_BYTES, parent_mode=0o755)
        except FileNotFoundError:
            pass
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        child = os.open(temporary, flags, 0o600, dir_fd=descriptor)
        with os.fdopen(child, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.fsync(stream.fileno())
        os.replace(temporary, "current.json", src_dir_fd=descriptor, dst_dir_fd=descriptor)
        os.fsync(descriptor)
    finally:
        try:
            os.unlink(temporary, dir_fd=descriptor)
        except FileNotFoundError:
            pass
        os.close(descriptor)
    return hashlib.sha256(raw).hexdigest()

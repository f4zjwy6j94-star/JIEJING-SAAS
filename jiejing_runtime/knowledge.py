"""Sanitized knowledge support for Jiejing Runtime.

This module lets the owned Runtime learn from curated Hermes/Jiejing notes and
skills without depending on Hermes internals or importing credentials.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import now_iso


KNOWLEDGE_VERSION = "2026-05-14.2"
DEFAULT_KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "output" / "jiejing-runtime-knowledge"
DEFAULT_KNOWLEDGE_PACK = DEFAULT_KNOWLEDGE_DIR / "jiejing-runtime-knowledge-pack.json"

_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(access[_-]?token|refresh[_-]?token|api[_-]?key|app[_-]?secret|client[_-]?secret|"
    r"password|passwd|cookie|authorization|bearer|oauth[_-]?token|secret)\b\s*[:=]\s*([^\s,;]+)"
)
_SECRET_HEADER_RE = re.compile(r"(?i)^\s*(authorization|cookie|set-cookie)\s*:")
_SECRET_FIELD_NAME_RE = re.compile(r"(?i)\b(refresh_token|access_token|id_token|client_secret|app_secret)\b")
_LONG_VALUE_RE = re.compile(r"\b[A-Za-z0-9_./+=:-]{48,}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_WINDOWS_SECRET_PATH_RE = re.compile(r"(?i)(credentials|token|cookie|secret|\.env)")


@dataclass(slots=True)
class KnowledgeItem:
    item_id: str
    title: str
    role: str
    task_types: list[str]
    tags: list[str]
    source_ref: str
    content: str
    priority: int = 50
    source_type: str = "curated_note"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class KnowledgePack:
    version: str
    generated_at: str
    items: list[KnowledgeItem]
    redaction_report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "generated_at": self.generated_at,
            "item_count": len(self.items),
            "items": [item.to_dict() for item in self.items],
            "redaction_report": self.redaction_report,
        }


class KnowledgeBase:
    """Small local retrieval layer for Runtime adapters."""

    def __init__(
        self,
        items: list[KnowledgeItem] | None = None,
        pack_path: Path | None = None,
        pack_meta: dict[str, Any] | None = None,
    ) -> None:
        self.items = items or []
        self.pack_path = pack_path
        self.pack_meta = pack_meta or {}

    @classmethod
    def load(cls, pack_path: Path = DEFAULT_KNOWLEDGE_PACK, *, strict: bool = False) -> "KnowledgeBase":
        if not strict and not pack_path.exists():
            return cls([], pack_path=pack_path)
        data = json.loads(pack_path.read_text(encoding="utf-8"))
        if strict and (
            not isinstance(data, dict)
            or not isinstance(data.get("items"), list)
            or not all(isinstance(data.get(key), str) and data[key].strip() for key in ("version", "generated_at"))
            or not isinstance(data.get("redaction_report", {}), dict)
        ):
            raise ValueError("Invalid explicit knowledge pack schema")
        if strict:
            for item in data["items"]:
                if (
                    not isinstance(item, dict)
                    or not all(isinstance(item.get(key), str) and item[key].strip()
                               for key in ("item_id", "title", "role", "source_ref", "content"))
                    or not all(isinstance(item.get(key), list) and all(isinstance(value, str) for value in item[key])
                               for key in ("task_types", "tags"))
                    or type(item.get("priority", 50)) is not int
                    or not isinstance(item.get("source_type", "curated_note"), str)
                ):
                    raise ValueError("Invalid explicit knowledge item schema")
        items = [
            KnowledgeItem(
                item_id=str(item.get("item_id", "")),
                title=str(item.get("title", "")),
                role=str(item.get("role", "all")),
                task_types=[str(value) for value in item.get("task_types", [])],
                tags=[str(value) for value in item.get("tags", [])],
                source_ref=str(item.get("source_ref", "")),
                content=str(item.get("content", "")),
                priority=int(item.get("priority", 50)),
                source_type=str(item.get("source_type", "curated_note")),
            )
            for item in data.get("items", [])
            if isinstance(item, dict)
        ]
        pack_meta = {
            "version": data.get("version"),
            "generated_at": data.get("generated_at"),
            "redaction_report": data.get("redaction_report", {}),
        }
        return cls(items, pack_path=pack_path, pack_meta=pack_meta)

    def query(self, role: str | None = None, task_type: str | None = None, tags: list[str] | None = None, limit: int = 6) -> list[KnowledgeItem]:
        tag_set = set(tags or [])
        scored: list[tuple[int, KnowledgeItem]] = []
        for item in self.items:
            score = item.priority
            if role and item.role in {role, "all"}:
                score += 30
            if task_type and task_type in item.task_types:
                score += 40
            if tag_set:
                score += 12 * len(tag_set.intersection(item.tags))
            if score > item.priority or not (role or task_type or tag_set):
                scored.append((score, item))
        scored.sort(key=lambda row: (-row[0], row[1].title))
        return [item for _, item in scored[:limit]]

    def summary(self) -> dict[str, Any]:
        roles: dict[str, int] = {}
        task_types: dict[str, int] = {}
        source_types: dict[str, int] = {}
        for item in self.items:
            roles[item.role] = roles.get(item.role, 0) + 1
            source_types[item.source_type] = source_types.get(item.source_type, 0) + 1
            for task_type in item.task_types:
                task_types[task_type] = task_types.get(task_type, 0) + 1
        return {
            "pack_path": str(self.pack_path) if self.pack_path else None,
            "version": self.pack_meta.get("version"),
            "generated_at": self.pack_meta.get("generated_at"),
            "item_count": len(self.items),
            "roles": roles,
            "task_types": task_types,
            "source_types": source_types,
            "redaction_report": self.pack_meta.get("redaction_report", {}),
            "titles": [item.title for item in self.items[:12]],
        }


def sanitize_text(text: str) -> tuple[str, dict[str, int]]:
    """Redact secret-looking values while preserving product/process knowledge."""

    counters = {
        "secret_assignments_redacted": 0,
        "secret_header_lines_removed": 0,
        "long_values_redacted": 0,
        "emails_redacted": 0,
        "suspicious_path_lines_removed": 0,
    }
    sanitized_lines: list[str] = []
    for line in text.splitlines():
        if _SECRET_HEADER_RE.search(line):
            sanitized_lines.append("[REDACTED_SECRET_HEADER]")
            counters["secret_header_lines_removed"] += 1
            continue
        if _WINDOWS_SECRET_PATH_RE.search(line) and re.search(r"[:/\\]", line):
            sanitized_lines.append("[REDACTED_SENSITIVE_PATH_LINE]")
            counters["suspicious_path_lines_removed"] += 1
            continue

        line, assignment_count = _SECRET_ASSIGNMENT_RE.subn(lambda match: f"{match.group(1)}=[REDACTED]", line)
        counters["secret_assignments_redacted"] += assignment_count
        line, field_name_count = _SECRET_FIELD_NAME_RE.subn("[REDACTED_SECRET_FIELD]", line)
        counters["secret_assignments_redacted"] += field_name_count
        line, email_count = _EMAIL_RE.subn("[REDACTED_EMAIL]", line)
        counters["emails_redacted"] += email_count
        line, long_count = _LONG_VALUE_RE.subn("[REDACTED_LONG_VALUE]", line)
        counters["long_values_redacted"] += long_count
        sanitized_lines.append(line)
    return "\n".join(sanitized_lines).strip(), counters


def make_item_id(title: str, source_ref: str) -> str:
    digest = hashlib.sha1(f"{source_ref}|{title}".encode("utf-8")).hexdigest()[:10]
    safe_title = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]
    return f"kb_{safe_title}_{digest}"


def write_knowledge_pack(pack: KnowledgePack, path: Path = DEFAULT_KNOWLEDGE_PACK) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pack.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_default_knowledge_base(pack_path: str | None = None) -> KnowledgeBase:
    """Explicit backend argument wins over environment; unset keeps legacy defaults."""
    selected = pack_path if pack_path is not None else os.environ.get("JIEJING_RUNTIME_KNOWLEDGE_PACK")
    if selected is not None:
        if not selected.strip():
            raise ValueError("Explicit runtime knowledge path must be non-blank")
        selected_path = Path(selected)
        if not selected_path.is_absolute() or selected.replace("\\", "/").startswith("//"):
            raise ValueError("Explicit runtime knowledge path must be absolute local")
        return KnowledgeBase.load(selected_path, strict=True)
    return KnowledgeBase.load(DEFAULT_KNOWLEDGE_PACK)


def compact_content(text: str, limit: int = 5000) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 120].rstrip() + "\n\n[TRUNCATED_FOR_RUNTIME_KNOWLEDGE]"

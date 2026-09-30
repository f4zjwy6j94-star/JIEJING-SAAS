"""Temporary operator-consented failure diagnosis; never part of chat payloads.

No control file means no collection. An exact tenant/user/store/project consent
expires within 24 hours and is consumed atomically by the first rejected answer.
Files live beside the backend database, outside the static root and audit feed.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .repository import _redact_secret_text


def _private_answer_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<(think|thinking|analysis|reasoning)\b[^>]*>.*?(?:</\1\s*>|$)",
                  "[reasoning_removed]", text, flags=re.I | re.S)
    text = re.sub(r"-----BEGIN [^-]*(?:PRIVATE KEY|SECRET)[^-]*-----.*?(?:-----END [^-]*-----|$)",
                  "[private_material_removed]", text, flags=re.I | re.S)
    text = re.sub(r'([\"\x27]?(?:access[_-]?token|refresh[_-]?token|api[_-]?key|apikey|password|secret|cookie|authorization)[\"\x27]?\s*[:=]\s*)([\"\x27])[^\r\n]*?\2',
                  r'\1"[redacted]"', text, flags=re.I)
    text = re.sub(r"https?://[^\s/@:]+:[^\s/@]+@", "https://[redacted]@", text, flags=re.I)
    return _redact_secret_text(text)[:12000]


def create_private_answer_capture(
    *, root: Path, company_id: str, user_id: str, store_id: str,
    project_key: str, attempt_id: str,
) -> Callable[[dict[str, Any]], None] | None:
    """Return a private one-shot sink only for a current, exact scoped consent."""
    scope = dict(company_id=company_id, user_id=user_id, store_id=store_id, project_key=project_key)
    control = root / "control.json"
    try:
        if root.is_symlink() or control.is_symlink() or control.stat().st_size > 4096:
            return None
        consent = json.loads(control.read_text(encoding="utf-8"))
        if consent.get("enabled") is not True or any(
            not value or consent.get(key) != value for key, value in scope.items()
        ):
            return None
        capture_id = consent.get("capture_id", "")
        if not re.fullmatch(r"capture_[a-zA-Z0-9_-]{1,80}", capture_id):
            return None
        approved = datetime.fromisoformat(consent["approved_at"])
        expires = datetime.fromisoformat(consent["expires_at"])
        now = datetime.now(timezone.utc)
        if not approved <= now < expires or (expires - approved).total_seconds() > 86400:
            return None
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None

    def capture(event: dict[str, Any]) -> None:
        try:
            if event.get("stage") != "initial_quality_rejection" or datetime.now(timezone.utc) >= expires:
                return
            if json.loads(control.read_text(encoding="utf-8")) != consent:
                return
            # Atomic rename elects a single request across workers and closes
            # collection before any answer text is persisted.
            control.rename(root / f"{capture_id}.consumed.json")
            payload = {
                "diagnostic_tag": "DEBUG-jj-answer-capture-v1",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                **scope, "attempt_id": attempt_id,
                "stage": "initial_quality_rejection",
                "answer": _private_answer_text(event.get("answer")),
                "blocked_by": [code for code in (event.get("blocked_by") or [])
                               if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,99}", code)][:20],
                "candidate_count": event.get("candidate_count") if type(event.get("candidate_count")) is int else None,
                "required_candidate_count": event.get("required_candidate_count") if type(event.get("required_candidate_count")) is int else None,
                "bounded_empty_answer_recovery": event.get("bounded_empty_answer_recovery") is True,
            }
            fd = os.open(root / f"{capture_id}.answer.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except (OSError, ValueError, TypeError):
            # Diagnosis cannot break a merchant turn or log exception payloads.
            return

    return capture

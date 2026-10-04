"""Temporary, explicitly consented one-request research diagnostics.

No control file means no collection. Consent binds tenant/user/store/submitted
project AND exact message digest, expires within two hours, and is consumed
before the first write. No sample is returned to chat, reports, or audit feeds.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .repository import _redact_secret_text


def private_answer_text(value: Any, limit: int = 12000) -> str:
    text = str(value or "")
    text = re.sub(r"<(think|thinking|analysis|reasoning)\b[^>]*>.*?(?:</\1\s*>|$)",
                  "[reasoning_removed]", text, flags=re.I | re.S)
    text = re.sub(r"-----BEGIN [^-]*(?:PRIVATE KEY|SECRET)[^-]*-----.*?(?:-----END [^-]*-----|$)",
                  "[private_material_removed]", text, flags=re.I | re.S)
    text = re.sub(r'''(["']?(?:access[_-]?token|refresh[_-]?token|api[_-]?key|apikey|password|secret|cookie|authorization)["']?\s*[:=]\s*)(["'])[^\r\n]*?\2''',
                  r'\1"[redacted]"', text, flags=re.I)
    text = re.sub(r"https?://[^\s/@:]+:[^\s/@]+@", "https://[redacted]@", text, flags=re.I)
    text = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[email_removed]", text, flags=re.I)
    return _redact_secret_text(text)[:limit]


def _public_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    keys = ("contract_version", "planner_policy", "status", "intent", "project_action", "product_name",
            "search", "query", "source_mode", "research_delivery", "candidate_count", "listing_deferred",
            "save_artifact", "excluded_candidates")
    result = {}
    for key in keys:
        value = plan.get(key)
        if isinstance(value, str):
            result[key] = private_answer_text(value, 1200)
        elif type(value) in (bool, int):
            result[key] = value
        elif key == "excluded_candidates" and isinstance(value, list):
            result[key] = [private_answer_text(x, 160) for x in value[:10] if isinstance(x, str)]
    result["research_queries"] = [{key: private_answer_text(row.get(key), 900) for key in ("subject", "query")}
        for row in (plan.get("research_queries") or [])[:4] if isinstance(row, dict)]
    return result


def create_private_answer_capture(*, root: Path, company_id: str, user_id: str,
                                  store_id: str, project_key: str, message: str,
                                  attempt_id: str) -> Callable[[dict[str, Any]], None] | None:
    scope = dict(company_id=company_id, user_id=user_id, store_id=store_id, project_key=project_key,
                 message_sha256=hashlib.sha256(message.encode("utf-8")).hexdigest())
    control = root / "control.json"
    try:
        if root.is_symlink() or control.is_symlink() or control.stat().st_size > 4096:
            return None
        if os.name == "posix" and (root.stat().st_mode & 0o077 or control.stat().st_mode & 0o077):
            return None
        consent = json.loads(control.read_text(encoding="utf-8"))
        if consent.get("enabled") is not True or any(not value or consent.get(key) != value for key, value in scope.items()):
            return None
        capture_id = consent.get("capture_id", "")
        if not re.fullmatch(r"capture_[a-zA-Z0-9_-]{1,80}", capture_id):
            return None
        approved = datetime.fromisoformat(consent["approved_at"])
        expires = datetime.fromisoformat(consent["expires_at"])
        now = datetime.now(timezone.utc)
        if not approved <= now < expires or (expires - approved).total_seconds() > 7200:
            return None
        consumed = root / f"{capture_id}.consumed.json"
        sample = root / f"{capture_id}.answer.json"
        disabled = root / f"{capture_id}.disabled.json"
        if any(path.exists() or path.is_symlink() for path in (consumed, sample, disabled)):
            return None
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
    payload: dict[str, Any] = {}

    def capture(event: dict[str, Any]) -> None:
        try:
            stage = event.get("stage")
            if stage not in {"initial", "repair"} or datetime.now(timezone.utc) >= expires or disabled.exists():
                return
            if not payload:
                if stage != "initial" or control.is_symlink() or json.loads(control.read_text(encoding="utf-8")) != consent:
                    return
                # O_EXCL elects only one request, including across processes.
                fd = os.open(consumed, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(consent, handle)
                control.unlink()
                payload.update(diagnostic_tag="DEBUG-jj-c-research-20261004", captured_at=now.isoformat(),
                               **scope, attempt_id=attempt_id, attempts=[],
                               semantic_plan=_public_plan(event.get("semantic_plan")),
                               source_records=[{key: private_answer_text(row.get(key), 2000)
                                   for key in ("citation_id", "url", "title", "snippet", "market_evidence_role")}
                                   for row in (event.get("source_records") or [])[:12] if isinstance(row, dict)])
            elif (stage != "repair" or len(payload["attempts"]) != 1 or consumed.is_symlink()
                  or json.loads(consumed.read_text(encoding="utf-8")) != consent):
                return
            payload["attempts"].append({
                "stage": stage, "answer": private_answer_text(event.get("answer")),
                "accepted": event.get("accepted") is True,
                "blocked_by": [code for code in (event.get("blocked_by") or [])
                    if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,99}", code)][:20],
            })
            temporary = root / f"{capture_id}.{stage}.tmp"
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(temporary, sample)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return  # No exception payloads or raw answers in process logs.

    return capture

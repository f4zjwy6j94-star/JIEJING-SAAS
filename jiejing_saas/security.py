"""Small security helpers for the local SaaS backend MVP.

The production version should use a managed identity provider, short-lived
tokens, MFA options, and a managed secret store. This file gives the local
test backend a real password hash and signed session boundary without adding
third-party dependencies.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any


PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> tuple[str, str]:
    if not password or len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), PBKDF2_ITERATIONS)
    return salt, digest.hex()


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), PBKDF2_ITERATIONS)
    return hmac.compare_digest(digest.hex(), password_hash)


@dataclass(slots=True)
class SessionPayload:
    user_id: str
    company_id: str
    email: str
    jti: str
    iat: int
    exp: int
    sid: str = ""
    token_type: str = "access"

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "company_id": self.company_id,
            "email": self.email,
            "jti": self.jti,
            "iat": self.iat,
            "exp": self.exp,
            "sid": self.sid,
            "token_type": self.token_type,
        }


def _session_ttl_from_env() -> int:
    raw = str(os.environ.get("JIEJING_SAAS_SESSION_TTL_SECONDS") or "").strip()
    production_like = str(os.environ.get("JIEJING_SAAS_ENV") or "").strip().lower() in {"staging", "production"}
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return min(value, 30 * 60) if production_like else value
        except ValueError:
            pass
    return 30 * 60 if production_like else 60 * 60 * 24 * 7


class SessionManager:
    def __init__(self, secret: str | None = None, ttl_seconds: int | None = None) -> None:
        self.secret = (secret or os.environ.get("JIEJING_SAAS_SESSION_SECRET") or "local-dev-session-secret-change-me").encode(
            "utf-8"
        )
        self.ttl_seconds = ttl_seconds if ttl_seconds is not None else _session_ttl_from_env()

    def create_token(self, *, user_id: str, company_id: str, email: str, refresh_session_id: str = "") -> str:
        issued_at = int(time.time())
        payload = SessionPayload(
            user_id=user_id,
            company_id=company_id,
            email=email,
            jti=f"session_{secrets.token_urlsafe(24)}",
            iat=issued_at,
            exp=issued_at + self.ttl_seconds,
            sid=str(refresh_session_id or ""),
            token_type="access",
        )
        payload_b64 = _b64(json.dumps(payload.to_dict(), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        signature = _b64(hmac.new(self.secret, payload_b64.encode("ascii"), hashlib.sha256).digest())
        return f"{payload_b64}.{signature}"

    def verify_token(self, token: str) -> dict[str, Any]:
        try:
            payload_b64, signature = token.split(".", 1)
        except ValueError as exc:
            raise ValueError("invalid bearer token") from exc
        expected = _b64(hmac.new(self.secret, payload_b64.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid bearer token signature")
        try:
            payload = json.loads(base64.urlsafe_b64decode(_pad(payload_b64)).decode("utf-8"))
        except Exception as exc:  # pragma: no cover - defensive parsing boundary
            raise ValueError("invalid bearer token payload") from exc
        if int(payload.get("exp") or 0) < int(time.time()):
            raise ValueError("bearer token expired")
        required = {"user_id", "company_id", "email"}
        if not required.issubset(payload):
            raise ValueError("bearer token missing identity fields")
        if payload.get("token_type") not in {None, "", "access"}:
            raise ValueError("invalid bearer token type")
        if not str(payload.get("jti") or ""):
            payload["jti"] = f"legacy_{hashlib.sha256(token.encode('utf-8')).hexdigest()[:40]}"
            payload["legacy_session"] = True
        else:
            payload["legacy_session"] = False
        payload.setdefault("iat", max(0, int(payload.get("exp") or 0) - self.ttl_seconds))
        return payload


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _pad(value: str) -> bytes:
    return (value + "=" * (-len(value) % 4)).encode("ascii")

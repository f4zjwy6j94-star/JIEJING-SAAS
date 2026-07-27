"""Server-side verification for registration trial activation challenges."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any


TURNSTILE_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TURNSTILE_ACTION_DEFAULT = "jiejing_register"
MAX_CHALLENGE_TOKEN_LENGTH = 2048
MAX_SITEVERIFY_RESPONSE_BYTES = 16 * 1024


def public_registration_challenge_config(*, environment: str) -> dict[str, Any]:
    required = _env_bool(
        "JIEJING_PLATFORM_TRIAL_ACTIVATION_REQUIRED",
        str(environment or "").strip().lower() in {"staging", "production"},
    )
    edge_enabled = _env_bool("JIEJING_TURNSTILE_OR_CHALLENGE_ENABLED", False)
    site_key = str(os.environ.get("JIEJING_TURNSTILE_SITE_KEY") or "").strip()
    secret_configured = bool(str(os.environ.get("JIEJING_TURNSTILE_SECRET_KEY") or "").strip())
    production_like = str(environment or "").strip().lower() in {"staging", "production"}
    hostname_ready = bool(_allowed_hostnames()) or not production_like
    verification_ready = bool(required and edge_enabled and site_key and secret_configured and hostname_ready)
    return {
        "contract_version": "2026-07-15-registration-challenge-siteverify-v1",
        "provider": "turnstile",
        "required": required,
        "enabled": bool(edge_enabled and site_key),
        "verification_ready": verification_ready,
        "site_key": site_key if edge_enabled else "",
        "action": _expected_action(),
        "account_registration_allowed_without_verification": True,
        "platform_trial_requires_verification": required,
        "merchant_byok_unaffected": True,
        "secret_exposed": False,
    }


def verify_registration_challenge(
    payload: dict[str, Any] | None,
    *,
    environment: str,
    remote_ip: str = "",
) -> dict[str, Any]:
    config = public_registration_challenge_config(environment=environment)
    if config.get("required") is not True:
        return _decision(verified=True, reason="activation_guard_not_required")
    if not _env_bool("JIEJING_TURNSTILE_OR_CHALLENGE_ENABLED", False):
        return _decision(verified=False, reason="edge_challenge_not_enabled")

    secret = str(os.environ.get("JIEJING_TURNSTILE_SECRET_KEY") or "").strip()
    if not config.get("site_key") or not secret:
        return _decision(verified=False, reason="challenge_verifier_not_configured")
    production_like = str(environment or "").strip().lower() in {"staging", "production"}
    if production_like and not _allowed_hostnames():
        return _decision(verified=False, reason="challenge_verifier_not_configured")

    challenge = payload if isinstance(payload, dict) else {}
    provider = str(challenge.get("provider") or "").strip().lower()
    token = str(challenge.get("token") or "").strip()
    action = str(challenge.get("action") or "").strip()
    expected_action = _expected_action()
    if provider != "turnstile" or not token:
        return _decision(verified=False, reason="challenge_required")
    if len(token) > MAX_CHALLENGE_TOKEN_LENGTH or action != expected_action:
        return _decision(verified=False, reason="challenge_context_mismatch")

    try:
        result = _call_siteverify(
            token=token,
            secret=secret,
            remote_ip=remote_ip,
            environment=environment,
        )
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError, urllib.error.URLError):
        return _decision(verified=False, reason="challenge_service_unavailable")

    if result.get("success") is not True:
        return _decision(verified=False, reason="challenge_verification_failed")
    if str(result.get("action") or "").strip() != expected_action:
        return _decision(verified=False, reason="challenge_context_mismatch")
    allowed_hostnames = _allowed_hostnames()
    hostname = str(result.get("hostname") or "").strip().lower()
    if allowed_hostnames and hostname not in allowed_hostnames:
        return _decision(verified=False, reason="challenge_context_mismatch")
    return _decision(verified=True, reason="server_verified_challenge")


def _call_siteverify(*, token: str, secret: str, remote_ip: str, environment: str) -> dict[str, Any]:
    endpoint = TURNSTILE_SITEVERIFY_URL
    if str(environment or "").strip().lower() == "test":
        test_endpoint = str(os.environ.get("JIEJING_TURNSTILE_SITEVERIFY_URL") or "").strip()
        if test_endpoint:
            endpoint = test_endpoint
    form = {
        "secret": secret,
        "response": token,
        "idempotency_key": str(uuid.uuid4()),
    }
    if remote_ip and remote_ip != "unknown":
        form["remoteip"] = remote_ip
    request = urllib.request.Request(
        endpoint,
        data=urllib.parse.urlencode(form).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "JiejingRegistrationGuard/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:  # noqa: S310 - fixed origin outside tests
        raw = response.read(MAX_SITEVERIFY_RESPONSE_BYTES + 1)
    if len(raw) > MAX_SITEVERIFY_RESPONSE_BYTES:
        raise ValueError("siteverify response too large")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("siteverify response must be an object")
    return value


def _decision(*, verified: bool, reason: str) -> dict[str, Any]:
    return {
        "verified": verified,
        "challenge_attested": verified,
        "decision_reason": reason,
        "merchant_byok_unaffected": True,
        "secret_exposed": False,
    }


def _expected_action() -> str:
    value = str(os.environ.get("JIEJING_TURNSTILE_ACTION") or TURNSTILE_ACTION_DEFAULT).strip()
    return value or TURNSTILE_ACTION_DEFAULT


def _allowed_hostnames() -> set[str]:
    configured = str(os.environ.get("JIEJING_TURNSTILE_ALLOWED_HOSTNAMES") or "")
    values = {item.strip().lower() for item in configured.split(",") if item.strip()}
    target = str(os.environ.get("JIEJING_TARGET_APP_HOST") or "").strip().lower()
    if target:
        values.add(target)
    return values


def _timeout_seconds() -> float:
    try:
        value = float(str(os.environ.get("JIEJING_TURNSTILE_TIMEOUT_SECONDS") or "5").strip())
    except ValueError:
        value = 5.0
    return min(10.0, max(1.0, value))


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

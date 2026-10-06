"""Shared backend detector for credential-shaped text in merchant content."""

from __future__ import annotations

import re
from typing import Any


_SECRET_LIKE_PATTERNS = tuple(
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in (
        r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |)?PRIVATE KEY-----",
        r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b",
        r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b",
        r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b",
        r"\bA(?:KIA|SIA)[A-Z0-9]{16}\b",
        r"\bAKID[A-Za-z0-9]{16,}\b",
        r"\bAIza[0-9A-Za-z_-]{35}\b",
        r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}",
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
        r"(?:^|[\s:=])v\^1\.\d+#i\^\d+#[A-Za-z0-9^#._~+/=-]{12,}",
        r"\b(?:access[_-]?token|refresh[_-]?token|api[_-]?key|apikey|password|private[_-]?key|client[_-]?secret|secret)\s*[:=]\s*[^,\s;]+",
        r"\btoken\s*[:=]\s*[A-Za-z0-9._~+/=-]{12,}",
        r"\b(?:postgres(?:ql)?|redis|mysql)://[^:\s/@]+:[^@\s]+@",
    )
)
_SECRET_LIKE_KEY_PATTERN = re.compile(
    r"(?:^|[_-])(?:access[_-]?token|refresh[_-]?token|token|api[_-]?key|apikey|password|private[_-]?key|client[_-]?secret|secret)(?:$|[_-])",
    flags=re.IGNORECASE,
)
_SAFE_SECRET_FLAG_KEYS = frozenset(
    {
        "secret_exposed",
        "raw_secret_returned",
        "raw_secret_stored",
        "secret_value_stored",
        "runtime_gets_raw_secret",
        "frontend_gets_raw_secret",
        "frontend_gets_token",
        "runtime_gets_token",
        "access_token_present",
        "refresh_token_present",
        "token_values_returned_to_public_response",
        "access_token_returned_to_frontend",
        "refresh_token_returned_to_frontend",
        "access_token_returned_to_runtime",
        "refresh_token_returned_to_runtime",
        "access_token_stored_in_database",
        "refresh_token_stored_in_database",
        "access_token_ttl_seconds",
        "seller_refresh_credential_ttl_seconds",
        "token_exchange_http_status",
        "token_endpoint",
        "merchant_brings_own_key",
        "frontend_gets_model_api_key",
        "runtime_gets_model_api_key",
        "reports_get_model_api_key",
        "frontend_gets_raw_key_after_save",
        "raw_key_stored_in_database",
        "jiejing_stores_only_secret_ref",
        "secret_value_returned",
        "raw_provider_secret_stored",
        "payment_secret_persisted",
        "frontend_gets_payment_secret",
        "raw_provider_response_persisted",
    }
)
_SAFE_TOKEN_COUNTER_KEYS = frozenset(
    {
        "cached_tokens",
        "completion_tokens",
        "input_tokens",
        "model_max_output_tokens",
        "output_tokens",
        "prompt_tokens",
        "reasoning_tokens",
        "total_tokens",
        "token_count",
    }
)
_SAFE_SECRET_METADATA_KEYS = frozenset(
    {
        "access_token_ttl_seconds",
        "seller_refresh_credential_ttl_seconds",
        "token_exchange_http_status",
        "token_endpoint",
    }
)
_SAFE_SECRET_CONTAINER_KEYS = frozenset(
    {"model_secret_resolution", "model_secret_ref_scope", "secret_ref_scope"}
)


def contains_secret_like_text(value: Any) -> bool:
    text = str(value or "")
    return any(pattern.search(text) is not None for pattern in _SECRET_LIKE_PATTERNS)


def contains_secret_like_data(value: Any) -> bool:
    """Inspect nested merchant input without returning or persisting the matched value."""

    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").casefold()
            safe_flag = normalized_key in _SAFE_SECRET_FLAG_KEYS and isinstance(item, bool)
            safe_counter = (
                normalized_key in _SAFE_TOKEN_COUNTER_KEYS
                and isinstance(item, (int, float))
                and not isinstance(item, bool)
            )
            safe_metadata = normalized_key in _SAFE_SECRET_METADATA_KEYS and isinstance(item, (str, int, float))
            safe_container = normalized_key in _SAFE_SECRET_CONTAINER_KEYS
            if not (safe_flag or safe_counter or safe_metadata or safe_container) and _SECRET_LIKE_KEY_PATTERN.search(normalized_key) is not None:
                return True
            if contains_secret_like_data(item):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(contains_secret_like_data(item) for item in value)
    if isinstance(value, str):
        return contains_secret_like_text(value)
    return False

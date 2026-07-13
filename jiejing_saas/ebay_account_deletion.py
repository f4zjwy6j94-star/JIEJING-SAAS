"""eBay marketplace account deletion notification boundary."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Callable
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa


_VERIFICATION_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,80}$")
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
NotificationTransport = Callable[[urllib.request.Request, float], tuple[int, dict[str, str], bytes]]


class AccountDeletionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class EbayNotificationSignatureVerifier:
    def __init__(
        self,
        *,
        environment: str,
        client_id: str,
        client_secret: str,
        transport: NotificationTransport | None = None,
        cache_seconds: int = 3600,
    ) -> None:
        self.environment = "sandbox" if str(environment).strip().lower() == "sandbox" else "production"
        self.client_id = str(client_id or "")
        self.client_secret = str(client_secret or "")
        self.transport = transport or _urlopen_transport
        self.cache_seconds = max(60, min(int(cache_seconds), 86400))
        self._public_key_cache: dict[str, tuple[float, str]] = {}
        self._application_token_cache: tuple[float, str] | None = None

    def verify(self, *, raw_body: bytes, signature_header: str) -> dict[str, Any]:
        try:
            key_id = _signature_key_id(signature_header)
            public_key = self._public_key(key_id)
        except AccountDeletionError as exc:
            return {
                "verified": False,
                "status": exc.code,
                "retryable": exc.code == "verification_unavailable",
                "secret_exposed": False,
            }
        return verify_notification_signature(
            raw_body=raw_body,
            signature_header=signature_header,
            public_key_pem=public_key,
        )

    def _public_key(self, key_id: str) -> str:
        now = time.time()
        cached = self._public_key_cache.get(key_id)
        if cached and cached[0] > now:
            return cached[1]
        if not self.client_id or not self.client_secret:
            raise AccountDeletionError("verification_unavailable", "eBay notification verification is unavailable")
        base = "https://api.sandbox.ebay.com" if self.environment == "sandbox" else "https://api.ebay.com"
        access_token = self._application_token(base=base, now=now)
        key_request = urllib.request.Request(
            f"{base}/commerce/notification/v1/public_key/{urllib.parse.quote(key_id, safe='')}",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            key_status, _key_headers, key_raw = self.transport(key_request, 12)
            key_payload = json.loads(key_raw.decode("utf-8")) if key_raw else {}
            public_key = str(key_payload.get("key") or "") if isinstance(key_payload, dict) else ""
            if key_status >= 400 or not public_key:
                raise ValueError("public key unavailable")
        except Exception as exc:
            raise AccountDeletionError("verification_unavailable", "eBay notification verification is unavailable") from exc
        if len(self._public_key_cache) >= 128:
            oldest_key = min(self._public_key_cache, key=lambda item: self._public_key_cache[item][0])
            self._public_key_cache.pop(oldest_key, None)
        self._public_key_cache[key_id] = (now + self.cache_seconds, public_key)
        return public_key

    def _application_token(self, *, base: str, now: float) -> str:
        cached = self._application_token_cache
        if cached and cached[0] > now:
            return cached[1]
        token_body = urllib.parse.urlencode(
            {"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}
        ).encode("ascii")
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode("utf-8")).decode("ascii")
        token_request = urllib.request.Request(
            f"{base}/identity/v1/oauth2/token",
            data=token_body,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            token_status, _token_headers, token_raw = self.transport(token_request, 12)
            token_payload = json.loads(token_raw.decode("utf-8")) if token_raw else {}
            access_token = str(token_payload.get("access_token") or "") if isinstance(token_payload, dict) else ""
            if token_status >= 400 or not access_token:
                raise ValueError("application token unavailable")
            expires_in = int(token_payload.get("expires_in") or 300) if isinstance(token_payload, dict) else 300
        except Exception as exc:
            raise AccountDeletionError("verification_unavailable", "eBay notification verification is unavailable") from exc
        self._application_token_cache = (now + max(1, min(expires_in, 7200) - 30), access_token)
        return access_token


def fetch_ebay_identity_hashes(
    *,
    access_token: str,
    environment: str,
    transport: NotificationTransport | None = None,
) -> dict[str, Any]:
    """Resolve the OAuth seller once and retain only irreversible selectors."""

    token = str(access_token or "")
    if not token:
        return {
            "status": "identity_mapping_unavailable",
            "blocked_by": ["oauth_access_token_missing"],
            "raw_identity_returned": False,
            "secret_exposed": False,
        }
    root = "https://apiz.sandbox.ebay.com" if str(environment).strip().lower() == "sandbox" else "https://apiz.ebay.com"
    request = urllib.request.Request(
        f"{root}/commerce/identity/v1/user/",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        status, _headers, raw = (transport or _urlopen_transport)(request, 12)
        if status != 200 or not raw or len(raw) > 131072:
            raise ValueError("identity response unavailable")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("identity response invalid")
        user_id = _bounded_text(payload.get("userId"), limit=512)
        username = _bounded_text(payload.get("username"), limit=512)
        if not user_id:
            raise ValueError("immutable user identity missing")
    except Exception:
        return {
            "status": "identity_mapping_unavailable",
            "blocked_by": ["ebay_identity_read_failed"],
            "raw_identity_returned": False,
            "secret_exposed": False,
        }
    return {
        "status": "identity_mapping_ready",
        "ebay_user_id_hash": _sha256_text(user_id),
        "ebay_username_hash": _sha256_text(username.casefold()) if username else "",
        "registration_marketplace_id": _bounded_text(payload.get("registrationMarketplaceId"), limit=32),
        "account_type": _bounded_text(payload.get("accountType"), limit=32),
        "account_status": _bounded_text(payload.get("status"), limit=32),
        "raw_identity_returned": False,
        "secret_exposed": False,
    }


def normalize_notification(*, raw_body: bytes, signature_header: str) -> dict[str, Any]:
    if not raw_body or len(raw_body) > 65536:
        raise AccountDeletionError("invalid_notification", "notification body is invalid")
    if not str(signature_header or "").strip() or len(str(signature_header)) > 8192:
        raise AccountDeletionError("invalid_signature_header", "notification signature is invalid")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AccountDeletionError("invalid_notification", "notification body is invalid") from exc
    if not isinstance(payload, dict):
        raise AccountDeletionError("invalid_notification", "notification body is invalid")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    notification = payload.get("notification") if isinstance(payload.get("notification"), dict) else {}
    data = notification.get("data") if isinstance(notification.get("data"), dict) else {}
    topic = _bounded_text(metadata.get("topic"), limit=80)
    if topic != "MARKETPLACE_ACCOUNT_DELETION":
        raise AccountDeletionError("unsupported_topic", "notification topic is unsupported")
    notification_id = _bounded_text(notification.get("notificationId"), limit=256)
    user_id = _bounded_text(data.get("userId"), limit=512)
    username = _bounded_text(data.get("username"), limit=512)
    eias_token = _bounded_text(data.get("eiasToken"), limit=2048)
    if not notification_id or not any((user_id, username, eias_token)):
        raise AccountDeletionError("invalid_notification", "notification identifiers are invalid")
    attempt = notification.get("publishAttemptCount")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1 or attempt > 1000:
        raise AccountDeletionError("invalid_notification", "notification delivery metadata is invalid")
    return {
        "event_key": _sha256_text(notification_id),
        "notification_id_hash": _sha256_text(notification_id),
        "topic": topic,
        "schema_version": _bounded_text(metadata.get("schemaVersion"), limit=24),
        "deprecated": bool(metadata.get("deprecated")),
        "event_date": _bounded_text(notification.get("eventDate"), limit=64),
        "publish_date": _bounded_text(notification.get("publishDate"), limit=64),
        "publish_attempt_count": attempt,
        "user_id_hash": _sha256_text(user_id) if user_id else "",
        "username_hash": _sha256_text(username.casefold()) if username else "",
        "eias_identity_hash": _sha256_text(eias_token) if eias_token else "",
        "payload_sha256": hashlib.sha256(raw_body).hexdigest(),
        "signature_present": True,
        "raw_payload_persisted": False,
        "raw_identity_persisted": False,
        "secret_exposed": False,
    }


def verify_notification_signature(*, raw_body: bytes, signature_header: str, public_key_pem: str) -> dict[str, Any]:
    try:
        envelope = _decode_signature_header(signature_header)
        key_id = _bounded_text(envelope.get("kid"), limit=512)
        signature_text = _bounded_text(envelope.get("signature"), limit=8192)
        if not key_id or not signature_text:
            raise ValueError("signature envelope is invalid")
        signature = base64.b64decode(signature_text, validate=True)
        public_key = serialization.load_pem_public_key(_format_public_key(public_key_pem).encode("ascii"))
        message = json.dumps(json.loads(raw_body.decode("utf-8")), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA1())
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, message, ec.ECDSA(hashes.SHA1()))
        else:
            raise ValueError("unsupported public key type")
    except InvalidSignature:
        return {"verified": False, "status": "invalid_signature", "secret_exposed": False}
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error, TypeError):
        return {"verified": False, "status": "invalid_signature_envelope", "secret_exposed": False}
    return {
        "verified": True,
        "status": "verified",
        "key_id": key_id,
        "algorithm": "ssl3-sha1-compatible",
        "raw_signature_returned": False,
        "secret_exposed": False,
    }


def build_challenge_response(*, challenge_code: str, verification_token: str, endpoint_url: str) -> dict[str, str]:
    challenge = str(challenge_code or "")
    token = str(verification_token or "")
    endpoint = str(endpoint_url or "")
    if not challenge or len(challenge) > 256 or any(ord(char) < 32 for char in challenge):
        raise AccountDeletionError("invalid_challenge", "challenge code is invalid")
    if not _VERIFICATION_TOKEN_RE.fullmatch(token):
        raise AccountDeletionError("configuration_unavailable", "account deletion verification is unavailable")
    try:
        parsed = urlsplit(endpoint)
    except ValueError as exc:
        raise AccountDeletionError("configuration_unavailable", "account deletion verification is unavailable") from exc
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise AccountDeletionError("configuration_unavailable", "account deletion verification is unavailable")
    digest = hashlib.sha256(f"{challenge}{token}{endpoint}".encode("utf-8")).hexdigest()
    return {"challengeResponse": digest}


def _bounded_text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit or any(ord(char) < 32 for char in text):
        return ""
    return text


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _decode_signature_header(signature_header: str) -> dict[str, Any]:
    envelope_bytes = base64.b64decode(str(signature_header or ""), validate=True)
    if not envelope_bytes or len(envelope_bytes) > 8192:
        raise ValueError("signature envelope is invalid")
    envelope = json.loads(envelope_bytes.decode("ascii"))
    if not isinstance(envelope, dict):
        raise ValueError("signature envelope is invalid")
    return envelope


def _signature_key_id(signature_header: str) -> str:
    try:
        key_id = _bounded_text(_decode_signature_header(signature_header).get("kid"), limit=512)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise AccountDeletionError("invalid_signature_header", "notification signature is invalid") from exc
    if not key_id or not _KEY_ID_RE.fullmatch(key_id):
        raise AccountDeletionError("invalid_signature_header", "notification signature is invalid")
    return key_id


def _format_public_key(value: str) -> str:
    text = str(value or "").strip()
    if "-----BEGIN PUBLIC KEY-----" not in text or "-----END PUBLIC KEY-----" not in text:
        raise ValueError("invalid public key")
    body = text.replace("-----BEGIN PUBLIC KEY-----", "").replace("-----END PUBLIC KEY-----", "")
    body = "".join(body.split())
    if not body:
        raise ValueError("invalid public key")
    lines = [body[index : index + 64] for index in range(0, len(body), 64)]
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----\n"


def _urlopen_transport(request: urllib.request.Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed eBay API origins
        return int(response.status), dict(response.headers.items()), response.read()

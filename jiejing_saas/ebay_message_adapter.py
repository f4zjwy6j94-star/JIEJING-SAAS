"""Narrow Message API boundary. Disabled by default; credentials stay backend-only.

Uses the existing HttpTransport shape. No implicit token lookup, refresh, OAuth,
notification subscription, or environment fallback is added. The provided HTTP
transport forbids redirects; read/send flags still default to off.
The integration layer must construct the scope from its authorized connection.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
import re
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener

MESSAGE_SCOPE = "https://api.ebay.com/oauth/api_scope/commerce.message"
BASE_URL = "https://api.ebay.com/commerce/message/v1"
MAX_MESSAGE_TEXT_LENGTH = 2000
MAX_RESPONSE_BYTES = 2_000_000
HttpTransport = Callable[[Request, float], tuple[int, dict[str, str], bytes]]


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("ambiguous_provider_json")
        value[key] = item
    return value


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def message_http_transport(request: Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
    """Official host only; never forward credentials to any redirect target."""
    url = urlsplit(request.full_url)
    if (url.scheme != "https" or url.netloc != "api.ebay.com"
            or not url.path.startswith("/commerce/message/v1/") or url.fragment):
        raise ValueError("message_transport_destination_not_allowed")
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return int(response.status), dict(response.headers), response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        # Includes blocked redirects. Do not read/echo provider error bodies.
        status = int(exc.code)
        exc.close()
        return status, {}, b""


@dataclass(frozen=True)
class MessageScope:
    """Internal identity binding, not a browser/account/store display identity.

    The default raw mode is only for existing offline fixtures. A future server
    resolver must independently verify its connection's username hash before
    constructing hash mode; a metadata selector alone is not that proof.
    """
    company_id: str
    store_id: str
    owner_id: str
    owner_binding_kind: str = "raw_fixture"

    def __post_init__(self):
        if any(not isinstance(value, str) or not value.strip() or len(value) > 200
               for value in asdict(self).values()):
            raise ValueError("invalid_message_scope")
        if self.owner_binding_kind not in ("raw_fixture", "sha256_casefold_ebay_username"):
            raise ValueError("invalid_owner_binding")
        if (self.owner_binding_kind == "sha256_casefold_ebay_username"
                and not re.fullmatch(r"[0-9a-f]{64}", self.owner_id)):
            raise ValueError("invalid_owner_binding")

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    @property
    def owner_storage_key(self) -> str:
        """Mode is part of every durable scope; never reuse an untyped owner key.

        Existing untyped local candidate rows are retained, not auto-migrated or
        treated as new approvals. This adds no schema change/production DDL.
        """
        return self.owner_binding_kind + ":" + self.owner_id

    def matches_owner(self, username: str) -> bool:
        if not isinstance(username, str) or not username.strip():
            return False
        # Same casefold + UTF-8 SHA256 convention as ebay_account_deletion's
        # verified Identity API username mapping. Never compare a digest to a
        # provider username directly, nor derive identity from a display name.
        bounded = username.strip()
        if len(bounded) > 512 or any(ord(char) < 32 for char in bounded):
            return False
        canonical = bounded.casefold()
        if self.owner_binding_kind == "sha256_casefold_ebay_username":
            return hashlib.sha256(canonical.encode("utf-8")).hexdigest() == self.owner_id
        return canonical == self.owner_id.strip().casefold()

    def is_incoming_message(self, sender_username: str, recipient_username: str) -> bool:
        return self.matches_owner(recipient_username) and not self.matches_owner(sender_username)


@dataclass(frozen=True)
class _PreparedReply:
    """Backend memory only. Never serialize or persist this credentialed request."""
    scope: MessageScope
    request: Request = field(repr=False)
    expected_recipient: str = field(repr=False)
    body_sha256: str
    request_sha256: str


class EbayMessageAdapter:
    def __init__(self, scope: MessageScope, *, token_provider: Callable,
                 transport: HttpTransport | None = None, read_enabled: bool = False,
                 send_enabled: bool = False):
        self.scope = scope
        self.token_provider = token_provider
        self.transport = transport or message_http_transport
        self.read_enabled = read_enabled
        self.send_enabled = send_enabled

    def _prepare_request(self, method: str, path: str, *, query=None, body=None) -> dict[str, Any]:
        try:
            token = self.token_provider(self.scope)
        except Exception:
            return {"status": "blocked_token_resolution", "http_status": None}
        if not isinstance(token, dict) or token.get("ok") is not True:
            return {"status": "blocked_token_resolution", "http_status": None}
        if token.get("binding") != self.scope.as_dict():
            return {"status": "blocked_token_binding", "http_status": None}
        if MESSAGE_SCOPE not in (token.get("scopes") or []):
            return {"status": "blocked_scope_missing", "http_status": None}
        access_token = token.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            return {"status": "blocked_token_resolution", "http_status": None}
        url = BASE_URL + path + ("?" + urlencode(query) if query else "")
        request = Request(url, method=method,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={"Accept": "application/json", "Content-Type": "application/json"})
        request.add_unredirected_header("Authorization", "Bearer " + access_token)
        return {"status": "prepared", "request": request}

    def _perform_request(self, request: Request) -> dict[str, Any]:
        try:
            status, _headers, raw = self.transport(request, 20)
            if type(status) is not int or status != (200 if request.get_method() == "GET" else 201):
                return {"status": "http_error", "http_status": status}
            if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
                return {"status": "invalid_response", "http_status": status}
            payload = json.loads(raw.decode(), object_pairs_hook=_unique_json_object)
            if not isinstance(payload, dict):
                return {"status": "invalid_response", "http_status": status}
            return {"status": "ok", "http_status": status, "payload": payload}
        except Exception:
            # Never surface exception strings: providers may include tokens or PII.
            return {"status": "transport_error", "http_status": None}

    def _request(self, method: str, path: str, *, query=None, body=None) -> dict[str, Any]:
        prepared = self._prepare_request(method, path, query=query, body=body)
        if prepared["status"] != "prepared":
            return prepared
        return self._perform_request(prepared["request"])

    def get_conversations(self, *, limit: int = 25, max_pages: int = 1, offset: int = 0) -> dict[str, Any]:
        if (type(limit) is not int or not 1 <= limit <= 50 or type(max_pages) is not int or not 1 <= max_pages <= 3
                or type(offset) is not int or not 0 <= offset <= 10000):
            raise ValueError("invalid_pagination_bound")
        if not self.read_enabled:
            return {"status": "blocked_read_disabled", "conversations": None}
        conversations = []
        truncated = False
        for page in range(max_pages):
            response = self._request("GET", "/conversation", query={
                "conversation_type": "FROM_MEMBERS", "limit": limit, "offset": offset + page * limit})
            if response["status"] != "ok":
                return {"status": response["status"], "http_status": response["http_status"], "conversations": None}
            entries = response["payload"].get("conversations")
            if not isinstance(entries, list) or len(entries) > limit or not all(isinstance(x, dict) for x in entries):
                return {"status": "invalid_response", "conversations": None}
            if any(type(item.get("conversationId")) is not str
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", item["conversationId"])
                    or item.get("conversationType", "FROM_MEMBERS") != "FROM_MEMBERS" for item in entries):
                return {"status": "invalid_response", "conversations": None}
            conversations.extend(entries)
            truncated = bool(response["payload"].get("next"))
            if truncated and not entries:
                return {"status": "invalid_response", "conversations": None}
            if not truncated:
                break
        return {"status": "ok", "conversations": conversations, "truncated": truncated,
                "next_offset": offset + (page + 1) * limit if truncated else None,
                "scope": self.scope.as_dict()}

    def get_conversation(self, conversation_id: str, *, limit: int = 25,
                         max_pages: int = 1) -> dict[str, Any]:
        if not isinstance(conversation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", conversation_id):
            raise ValueError("invalid_conversation_id")
        if type(limit) is not int or not 1 <= limit <= 50 or type(max_pages) is not int or not 1 <= max_pages <= 3:
            raise ValueError("invalid_pagination_bound")
        failure_context = {"scope": self.scope.as_dict(), "conversation_id": conversation_id, "messages": None}
        if not self.read_enabled:
            return {**failure_context, "status": "blocked_read_disabled"}
        messages = []
        truncated = False
        for page in range(max_pages):
            response = self._request("GET", "/conversation/" + conversation_id, query={
                "conversation_type": "FROM_MEMBERS", "limit": limit, "offset": page * limit})
            if response["status"] != "ok":
                return {**failure_context, "status": response["status"], "http_status": response["http_status"]}
            payload = response["payload"]
            entries = payload.get("messages")
            if payload.get("conversationType") != "FROM_MEMBERS" or not isinstance(entries, list) or len(entries) > limit:
                return {**failure_context, "status": "invalid_response"}
            if not all(isinstance(x, dict) for x in entries):
                return {**failure_context, "status": "invalid_response"}
            messages.extend(entries)
            truncated = bool(payload.get("next"))
            if not truncated:
                break
        return {"status": "ok", "messages": messages, "conversation_id": conversation_id,
                "scope": self.scope.as_dict(), "truncated": truncated}

    def prepare_reply(self, conversation_id: str, body: str, *, expected_recipient: str | None = None) -> dict[str, Any] | _PreparedReply:
        """Resolve binding/token before the durable claim; no buyer-message HTTP."""
        if not self.send_enabled:
            return {"status": "blocked_send_disabled", "message_sent": False}
        if not isinstance(conversation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", conversation_id):
            raise ValueError("invalid_conversation_id")
        if not isinstance(body, str) or not body.strip() or len(body) > MAX_MESSAGE_TEXT_LENGTH:
            raise ValueError("invalid_message_body")
        recipient = self._recipient_identity(expected_recipient)
        if not recipient or self.scope.matches_owner(recipient):
            return {"status": "blocked_recipient_binding", "message_sent": False,
                    "buyer_message_http_attempted": False}
        prepared = self._prepare_request("POST", "/send_message", body={
            "conversationId": conversation_id, "messageText": body})
        if prepared["status"] != "prepared":
            return {"status": prepared["status"], "message_sent": False, "buyer_message_http_attempted": False}
        return _PreparedReply(self.scope, prepared["request"], recipient,
                              hashlib.sha256(body.encode("utf-8")).hexdigest(),
                              hashlib.sha256(prepared["request"].data).hexdigest())

    @staticmethod
    def _recipient_identity(value):
        if (not isinstance(value, str) or not value.strip() or len(value) > 512
                or any(ord(char) < 32 for char in value)):
            return None
        try:
            value.encode("utf-8")
        except UnicodeError:
            return None
        return value.strip().casefold()

    def _receipt_matches(self, payload, prepared):
        try:
            message_id = payload.get("messageId")
            created_at = payload.get("createdDate")
            body = payload.get("messageBody")
            if (not isinstance(message_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", message_id)
                    or not isinstance(created_at, str) or len(created_at) > 40 or "T" not in created_at
                    or not isinstance(body, str) or not body or len(body) > MAX_MESSAGE_TEXT_LENGTH):
                return False
            stamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            return (stamp.tzinfo is not None and stamp.utcoffset() is not None
                    and self.scope.matches_owner(payload.get("senderUserName"))
                    and self._recipient_identity(payload.get("recipientUserName")) == prepared.expected_recipient
                    and hashlib.sha256(body.encode("utf-8")).hexdigest() == prepared.body_sha256)
        except (ValueError, TypeError, UnicodeError):
            return False

    def send_prepared_reply(self, prepared: _PreparedReply) -> dict[str, Any]:
        """Call only after durable claim. One HTTP attempt; no token lookup/retry."""
        if not self.send_enabled or not isinstance(prepared, _PreparedReply) or prepared.scope != self.scope:
            return {"status": "result_unknown", "message_sent": False}
        if (prepared.request.get_method() != "POST" or prepared.request.full_url != BASE_URL + "/send_message"
                or not isinstance(prepared.request.data, bytes)
                or hashlib.sha256(prepared.request.data).hexdigest() != prepared.request_sha256):
            return {"status": "result_unknown", "message_sent": False, "buyer_message_http_attempted": False}
        response = self._perform_request(prepared.request)
        payload = response.get("payload") or {}
        if (response["status"] == "ok" and response.get("http_status") == 201
                and self._receipt_matches(payload, prepared)):
            return {"status": "sent", "message_sent": True, "message_id": payload["messageId"],
                    "created_at": payload["createdDate"]}
        # Even successful HTTP without a usable provider receipt is not "sent".
        # No retry policy exists here. The service persists unknown for reconciliation.
        return {"status": "result_unknown", "message_sent": False,
                "http_status": response.get("http_status")}

    def send_reply(self, conversation_id: str, body: str, *, expected_recipient: str | None = None) -> dict[str, Any]:
        """Standalone one-attempt adapter; persistent callers use prepare/claim/send."""
        prepared = self.prepare_reply(conversation_id, body, expected_recipient=expected_recipient)
        if isinstance(prepared, dict):
            return prepared
        return self.send_prepared_reply(prepared)

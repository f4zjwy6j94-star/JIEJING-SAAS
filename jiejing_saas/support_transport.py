"""Scoped credential HTTP transport. No factory, credentials or network by default.

Server code supplies a verified immutable Vault binding/URL, never request data.
No injected callable/opener or trust marker can replace this implementation.
Tests replace urllib's network boundary, not the production type check.
"""
from dataclasses import dataclass
import math
import re
import ssl
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, unquote, urlsplit
import urllib.request

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
INTROSPECTION_URL = TOKEN_URL + "/introspect"
IDENTITY_URL = "https://apiz.ebay.com/commerce/identity/v1/user/"
MAX_RESPONSE_BYTES = 131072
MAX_REQUEST_BYTES = 262144
_BINDING_KEYS = {"company_id", "store_id", "connection_id", "oauth_request_id", "secret_ref",
                 "seller_identity_hash", "owner_username_hash", "owner_binding_kind", "environment"}


def _text(value):
    return (type(value) is str and bool(value) and value == value.strip()
            and len(value) <= 65536 and all(32 <= ord(c) != 127 for c in value)
            and not any(0xD800 <= ord(c) <= 0xDFFF for c in value))


def _vault_url_valid(url):
    if not _text(url) or len(url) > 4096:
        return False
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or not parts.path.startswith("/v1/")
            or parts.netloc != parts.netloc.lower() or "\\" in url
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[1-9][0-9]{0,4})?", parts.netloc)
            or parts.hostname.endswith(".") or parts.port is not None and not 1 <= parts.port <= 65535):
        return False
    for segment in parts.path.split("/")[1:]:
        decoded = unquote(segment, encoding="utf-8", errors="strict")
        if (not _text(decoded) or decoded in {".", ".."} or "/" in decoded or "\\" in decoded
                or quote(decoded, safe="-._~") != segment):
            return False
    return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True, slots=True, repr=False)
class SupportTransport:
    role: str = "credential"
    enabled: bool = False
    vault_url: str = ""
    vault_binding: tuple = ()

    def __post_init__(self):
        try:
            if self.role not in {"credential", "identity"} or type(self.enabled) is not bool:
                raise ValueError()
            if self.vault_url or self.vault_binding:
                if self.role != "credential" or not _vault_url_valid(self.vault_url):
                    raise ValueError()
                if (type(self.vault_binding) is not tuple or len(self.vault_binding) != len(_BINDING_KEYS)
                        or any(type(pair) is not tuple or len(pair) != 2 for pair in self.vault_binding)):
                    raise ValueError()
                binding = dict(self.vault_binding)
                if (set(binding) != _BINDING_KEYS or len(binding) != len(self.vault_binding)
                        or not all(_text(value) and len(value) <= 200 for value in binding.values())
                        or binding["environment"] != "production"
                        or binding["owner_binding_kind"] != "sha256_casefold_ebay_username"
                        or any(not re.fullmatch(r"[0-9a-f]{64}", binding[key])
                               for key in ("seller_identity_hash", "owner_username_hash"))):
                    raise ValueError()
        except Exception:
            raise ValueError("support_transport_policy_invalid") from None

    def __repr__(self):
        return "<SupportTransport scoped redacted>"

    def matches_vault(self, binding, url):
        return (self.enabled is True and self.role == "credential" and bool(self.vault_url)
                and self.vault_url == url and isinstance(binding, dict) and dict(self.vault_binding) == binding)

    def __call__(self, request, timeout):
        if not self.enabled:
            raise ValueError("support_transport_disabled")
        if (type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 0 < timeout <= (12 if self.role == "identity" else 20)):
            raise ValueError("support_transport_timeout_invalid")
        if type(request) is not urllib.request.Request:
            raise ValueError("support_transport_request_invalid")
        target, method = request.full_url, request.get_method()
        if self.role == "identity" and target == IDENTITY_URL and method == "GET":
            purpose = "identity"
        elif self.role == "credential" and target in (TOKEN_URL, INTROSPECTION_URL) and method == "POST":
            purpose = "token" if target == TOKEN_URL else "introspection"
        elif self.role == "credential" and self.vault_url and target == self.vault_url and method == "GET":
            purpose = "vault"
        else:
            raise ValueError("support_transport_destination_not_allowed")
        headers = {}
        for source in (request.headers, request.unredirected_hdrs):
            for name, value in source.items():
                key = name.lower()
                if key in headers or not _text(value):
                    raise ValueError("support_transport_headers_invalid")
                headers[key] = value
        allowed = {"accept", "x-vault-token"} if purpose == "vault" else {"accept", "authorization"}
        if purpose in {"token", "introspection"}:
            allowed.add("content-type")
        credential_key = "x-vault-token" if purpose == "vault" else "authorization"
        if (set(headers) != allowed or headers.get("accept") != "application/json"
                or not headers.get(credential_key)):
            raise ValueError("support_transport_credential_boundary_invalid")
        if purpose != "vault" and not headers[credential_key].startswith("Bearer " if purpose == "identity" else "Basic "):
            raise ValueError("support_transport_credential_boundary_invalid")
        body = request.data
        if purpose in {"token", "introspection"}:
            if (type(body) is not bytes or not 0 < len(body) <= MAX_REQUEST_BYTES
                    or headers["content-type"] != "application/x-www-form-urlencoded"):
                raise ValueError("support_transport_body_invalid")
            try:
                fields = parse_qs(body.decode("utf-8"), strict_parsing=True, keep_blank_values=True,
                                  max_num_fields=2, encoding="utf-8", errors="strict")
                expected = {"grant_type", "refresh_token"} if purpose == "token" else {"token", "token_type_hint"}
                if (set(fields) != expected or any(len(values) != 1 or not _text(values[0]) for values in fields.values())
                        or purpose == "token" and fields["grant_type"] != ["refresh_token"]
                        or purpose == "introspection" and fields["token_type_hint"] != ["access_token"]):
                    raise ValueError()
            except Exception:
                raise ValueError("support_transport_body_invalid") from None
        elif body is not None:
            raise ValueError("support_transport_body_invalid")
        # Reconstruct after validation; do not inherit caller proxy/Host flags.
        safe_request = urllib.request.Request(target, data=body, method=method)
        for name, value in headers.items():
            safe_request.add_unredirected_header(name, value)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        try:
            with opener.open(safe_request, timeout=timeout) as response:
                status = response.status
                if type(status) is not int or status != 200:
                    return status if type(status) is int else 502, {}, b""
                if response.geturl() != target:
                    raise ValueError("support_transport_response_origin_invalid")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if type(raw) is not bytes or len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("support_transport_response_oversized")
                return status, {}, raw
        except HTTPError as exc:
            status = int(exc.code)
            exc.close()
            return status, {}, b""
        except Exception:
            raise ValueError("support_transport_unavailable") from None

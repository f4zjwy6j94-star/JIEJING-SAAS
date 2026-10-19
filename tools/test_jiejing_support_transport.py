"""No sockets: exercise real stdlib opener/redirect handling at HTTPS boundary."""
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from email.message import Message
from io import BytesIO
from pathlib import Path
import json
import math
import os
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import urllib.request
from urllib.response import addinfourl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jiejing_saas.support_transport import (SupportTransport, TOKEN_URL, INTROSPECTION_URL,
    IDENTITY_URL, MAX_RESPONSE_BYTES, MAX_REQUEST_BYTES)

BINDING = dict(company_id="synthetic-company", store_id="synthetic-store", connection_id="synthetic-connection",
    oauth_request_id="synthetic-oauth", secret_ref="synthetic-ref", seller_identity_hash="a"*64,
    owner_username_hash="b"*64, owner_binding_kind="sha256_casefold_ebay_username", environment="production")
VAULT_URL = "https://vault.example.invalid/v1/secret/data/synthetic-company/synthetic-store/synthetic-ref"
ORIGINAL_HTTPS = urllib.request.HTTPSHandler


def transport(role="credential"):
    return SupportTransport(role=role, enabled=True, **({"vault_url": VAULT_URL,
        "vault_binding": tuple(sorted(BINDING.items()))} if role == "credential" else {}))


def request(purpose="token", url=None):
    if purpose == "identity":
        return urllib.request.Request(url or IDENTITY_URL,
            headers={"Authorization": "Bearer synthetic-access", "Accept": "application/json"}, method="GET")
    if purpose == "vault":
        return urllib.request.Request(url or VAULT_URL,
            headers={"X-Vault-Token": "synthetic-vault-token", "Accept": "application/json"}, method="GET")
    fields = {"grant_type": "refresh_token", "refresh_token": "synthetic-refresh"} if purpose == "token" else {
        "token": "synthetic-access", "token_type_hint": "access_token"}
    return urllib.request.Request(url or (TOKEN_URL if purpose == "token" else INTROSPECTION_URL),
        data=urlencode(fields).encode(), method="POST", headers={"Authorization": "Basic c3ludGhldGlj",
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})


@contextmanager
def network_boundary(*, status=200, location=None, body=b'{"synthetic":true}', returned_url=None, error=None):
    calls, reads, contexts = [], [], []
    class Reader(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)
    class FakeHTTPS(ORIGINAL_HTTPS):
        def __init__(self, *args, **kwargs):
            contexts.append(kwargs.get("context"))
            super().__init__(*args, **kwargs)
        def https_open(self, req):
            calls.append(req)
            if error:
                raise error
            headers = Message()
            if location:
                headers["Location"] = location
            result = addinfourl(Reader(body), headers, returned_url or req.full_url, status)
            result.msg = "Synthetic"
            return result
    # Real opener, error processor, redirect policy and HTTPS handler selection;
    # fake only the final HTTPS I/O method. Socket use is separately prohibited.
    with patch("urllib.request.HTTPSHandler", FakeHTTPS):
        yield calls, reads, contexts


class SupportTransportTests(unittest.TestCase):
    def setUp(self):
        for name in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex"):
            guard = patch(name, side_effect=AssertionError("network forbidden"))
            guard.start()
            self.addCleanup(guard.stop)

    def test_disabled_default_has_zero_network(self):
        with network_boundary() as (calls, _, _):
            with self.assertRaisesRegex(ValueError, "disabled"):
                SupportTransport()(request(), 20)
        self.assertEqual(calls, [])

    def test_exact_requests_use_verified_tls_no_proxy_and_unredirected_credentials(self):
        for purpose in ("token", "introspection", "identity", "vault"):
            with self.subTest(purpose=purpose), network_boundary() as (calls, reads, contexts), \
                 patch.dict(os.environ, {"HTTPS_PROXY": "http://outside.invalid:1", "https_proxy": "http://outside.invalid:1"}):
                result = transport("identity" if purpose == "identity" else "credential")(request(purpose), 12)
                self.assertEqual(result, (200, {}, b'{"synthetic":true}'))
                self.assertEqual(len(calls), 1)
                req = calls[0]
                key = "X-vault-token" if purpose == "vault" else "Authorization"
                self.assertIn(key, req.unredirected_hdrs)
                self.assertNotIn(key, req.headers)
                self.assertEqual(req.host, "apiz.ebay.com" if purpose == "identity" else
                    "vault.example.invalid" if purpose == "vault" else "api.ebay.com")
                self.assertEqual(reads, [MAX_RESPONSE_BYTES + 1])
                self.assertTrue(contexts[0].check_hostname)
                self.assertEqual(contexts[0].verify_mode, 2)

    def test_all_same_and_cross_origin_redirects_stop_after_one_request(self):
        for code in (301, 302, 303, 307, 308):
            for purpose in ("token", "introspection", "identity", "vault"):
                for location in ("https://outside.invalid/collect", request(purpose).full_url + "/moved"):
                    with self.subTest(code=code, purpose=purpose, location=location), \
                         network_boundary(status=code, location=location, body=b"synthetic-secret-must-not-read") as (calls, reads, _):
                        result = transport("identity" if purpose == "identity" else "credential")(request(purpose), 12)
                        self.assertEqual(result, (code, {}, b""))
                        self.assertEqual(len(calls), 1)
                        self.assertEqual(reads, [])

    def test_wrong_destinations_and_methods_are_rejected_before_io(self):
        urls = [TOKEN_URL.replace("https:", "http:"), TOKEN_URL.replace("api.ebay.com", "api.ebay.com.evil.invalid"),
            TOKEN_URL.replace("api.ebay.com", "api.ebay.com:443"), TOKEN_URL.replace("api.ebay.com", "user@api.ebay.com"),
            TOKEN_URL + "?x=1", TOKEN_URL + "#x", TOKEN_URL + "/", TOKEN_URL.replace("/token", "/%74oken"),
            TOKEN_URL.replace("/token", "/../token"), "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
            VAULT_URL.replace("synthetic-ref", "other-ref"), VAULT_URL.replace("synthetic-store", "other-store")]
        with network_boundary() as (calls, _, _):
            for url in urls:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    transport()(request(url=url), 20)
            for method in ("GET", "PUT", "DELETE", "HEAD"):
                req = request()
                req.method = method
                with self.subTest(method=method), self.assertRaises(ValueError):
                    transport()(req, 20)
            with self.assertRaises(ValueError):
                transport("identity")(request(), 12)
        self.assertEqual(calls, [])

    def test_vault_binding_and_policy_are_immutable_and_exact(self):
        scoped = transport()
        self.assertTrue(scoped.matches_vault(BINDING, VAULT_URL))
        for key in BINDING:
            self.assertFalse(scoped.matches_vault({**BINDING, key: "different"}, VAULT_URL))
        self.assertFalse(scoped.matches_vault(BINDING, VAULT_URL + "/"))
        with self.assertRaises(FrozenInstanceError):
            scoped.vault_url = "https://outside.invalid/v1/other"
        self.assertNotIn("synthetic-ref", repr(scoped))
        for bad in ("http://vault.example.invalid/v1/x", "https://user@vault.example.invalid/v1/x",
            "https://vault.example.invalid/v1/../x", "https://vault.example.invalid/v1/%2Fother",
            "https://vault.example.invalid/v1/%2e%2e/x", "https://vault.example.invalid/v1//x",
            "https://vault.example.invalid/v1/x?param=1", "https://vault.example.invalid/v1/x#fragment",
            "https://vault.example.invalid:99999/v1/x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                SupportTransport(enabled=True, vault_url=bad, vault_binding=tuple(sorted(BINDING.items())))

    def test_credentials_never_cross_purpose_or_accept_extra_headers(self):
        with network_boundary() as (calls, _, _):
            for purpose, header, value in (("token", "X-Vault-Token", "synthetic"),
                ("vault", "Authorization", "Basic synthetic"), ("identity", "Authorization", "Basic synthetic"),
                ("token", "Authorization", "Bearer synthetic"), ("token", "Cookie", "synthetic"),
                ("identity", "Proxy-Authorization", "synthetic"), ("token", "Host", "outside.invalid")):
                req = request(purpose)
                req.add_header(header, value)
                with self.subTest(purpose=purpose, header=header), self.assertRaises(ValueError):
                    transport("identity" if purpose == "identity" else "credential")(req, 12)
            req = request()
            req.add_unredirected_header("Authorization", "Basic duplicate")
            with self.assertRaises(ValueError): transport()(req, 20)
        self.assertEqual(calls, [])

    def test_timeout_request_body_and_response_are_bounded(self):
        with network_boundary() as (calls, _, _):
            for timeout in (0, -1, 21, True, math.inf, math.nan, "20"):
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    transport()(request(), timeout)
            with self.assertRaises(ValueError): transport("identity")(request("identity"), 13)
            for body in (b"x" * (MAX_REQUEST_BYTES + 1), b"grant_type=refresh_token&refresh_token=",
                b"grant_type=refresh_token&refresh_token=a&refresh_token=b", b"grant_type=client_credentials&refresh_token=a",
                b"wrong=value", b"not-form", b"grant_type=refresh_token&refresh_token=%ED%A0%80"):
                req = request()
                req.data = body
                with self.subTest(length=len(body)), self.assertRaises(ValueError): transport()(req, 20)
        self.assertEqual(calls, [])
        with network_boundary(body=b"x" * (MAX_RESPONSE_BYTES + 1)) as (calls, reads, _):
            with self.assertRaises(ValueError): transport()(request(), 20)
            self.assertEqual(reads, [MAX_RESPONSE_BYTES + 1])
        with network_boundary(returned_url="https://outside.invalid/final") as (_, reads, _):
            with self.assertRaises(ValueError): transport()(request(), 20)
            self.assertEqual(reads, [])

    def test_provider_errors_and_tls_errors_do_not_read_or_echo_bodies(self):
        for status in (400, 401, 403, 429, 500):
            with self.subTest(status=status), network_boundary(status=status, body=b"synthetic-secret") as (_, reads, _):
                self.assertEqual(transport()(request(), 20), (status, {}, b""))
                self.assertEqual(reads, [])
        with network_boundary(error=RuntimeError("synthetic-sensitive-detail")):
            with self.assertRaises(ValueError) as caught:
                transport()(request(), 20)
            self.assertNotIn("synthetic", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

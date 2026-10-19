"""Offline credential resolution. All selectors, tokens and identities synthetic."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jiejing_saas.ebay_message_adapter import MessageScope, MESSAGE_SCOPE
from jiejing_saas.support_token_resolver import SupportTokenResolver


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class MetadataRepository:
    def __init__(self, boundary):
        self.boundary = boundary
        self.calls = []

    def get_support_connection_boundary(self, *, company_id, store_id):
        self.calls.append((company_id, store_id))
        return copy.deepcopy(self.boundary)


class SupportTokenResolverTests(unittest.TestCase):
    def setUp(self):
        self.now = 1791792000.0
        self.internal = {
            "company_id": "company-a", "store_id": "store-a", "connection_id": "connection-a",
            "oauth_request_id": "oauth-a", "secret_ref": "synthetic-ref-a",
            "seller_identity_hash": digest("immutable-seller-a"),
            "owner_username_hash": digest("synthetic-seller"),
            "owner_binding_kind": "sha256_casefold_ebay_username", "environment": "production",
        }
        self.boundary = {
            "contract_version": "2026-10-12-support-connection-boundary-v1",
            "status": "blocked", "ready": False, "connection_bound": True,
            "requested_message_scope_present": True, "granted_message_scope_verified": False,
            "requires_live_owner_check": True, "owner_identity_verified": False,
            "live_scope_check_required": True, "blocked_by": ["support_message_scope_unverified"],
            "internal": self.internal,
        }
        self.repo = MetadataRepository(self.boundary)
        self.calls = []
        self.refresh_result = {
            "ok": True, "status": "refreshed", "http_status": 200,
            "source": "backend_vault_secret_ref_refresh", "binding": copy.deepcopy(self.internal),
            "access_token": "synthetic-access-not-real", "token_type": "Bearer",
            "expires_in": 7200, "refreshed_at": int(self.now), "secret_exposed": False,
        }
        self.introspection = {"ok": True, "http_status": 200, "active": True,
                              "client_id": "synthetic-client", "scopes": [MESSAGE_SCOPE], "secret_exposed": False}
        self.identity = {"status": "identity_mapping_ready", "ebay_user_id_hash": digest("immutable-seller-a"),
                         "ebay_username_hash": digest("synthetic-seller"), "secret_exposed": False}

    def refresh(self, *, binding, task_scope):
        self.calls.append(("refresh", copy.deepcopy(binding), task_scope))
        return copy.deepcopy(self.refresh_result)

    def introspect(self, *, access_token, environment, expected_client_id):
        self.calls.append(("introspect", access_token, environment, expected_client_id))
        return copy.deepcopy(self.introspection)

    def get_identity(self, *, access_token, environment):
        self.calls.append(("identity", access_token, environment))
        return copy.deepcopy(self.identity)

    def resolver(self, **overrides):
        return SupportTokenResolver(self.repo, refresh=self.refresh, introspect=self.introspect,
            get_identity=self.get_identity, expected_client_id="synthetic-client", clock=lambda: self.now, **overrides)

    def test_disabled_by_default_performs_no_metadata_or_provider_call(self):
        result = self.resolver().resolve(company_id="company-a", store_id="store-a")
        self.assertEqual(result.public_result()["blocked_by"], ["support_verification_disabled"])
        self.assertFalse(result.public_result()["credentials_verified"])
        self.assertIsNone(result.scope)
        self.assertEqual(self.repo.calls, [])
        self.assertEqual(self.calls, [])

    def test_exact_connection_refresh_live_scope_and_identity_produce_memory_only_binding(self):
        result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
        public = result.public_result()
        self.assertTrue(public["credentials_verified"])
        self.assertTrue(public["owner_identity_verified"])
        self.assertTrue(public["granted_message_scope_verified"])
        self.assertFalse(public["read_enabled"])
        self.assertFalse(public["send_enabled"])
        self.assertFalse(public["live_end_to_end_verified"])
        self.assertEqual([call[0] for call in self.calls], ["refresh", "introspect", "identity"])
        self.assertEqual(self.calls[0][1], self.internal)
        self.assertEqual(self.calls[1][1], self.refresh_result["access_token"])
        self.assertEqual(self.calls[2][1], self.refresh_result["access_token"])
        self.assertEqual(self.calls[1][2:], ("production", "synthetic-client"))
        self.assertEqual(result.scope.owner_binding_kind, "sha256_casefold_ebay_username")
        self.assertTrue(result.scope.matches_owner("SYNTHETIC-SELLER"))
        token = result.token_provider(result.scope)
        self.assertTrue(token["ok"])
        self.assertEqual(token["binding"], result.scope.as_dict())
        self.assertEqual(token["access_token"], self.refresh_result["access_token"])
        for forbidden in (*self.internal.values(), self.refresh_result["access_token"]):
            self.assertNotIn(forbidden, json.dumps(public))
            self.assertNotIn(forbidden, repr(result))

    def test_only_narrow_scope_blockers_can_enter_explicit_verification(self):
        for codes in (["support_metadata_unavailable"], ["support_connection_ambiguous"], ["unknown"],
                      ["support_message_scope_unverified", "unknown"], "support_message_scope_unverified", None):
            with self.subTest(codes=codes):
                self.repo.boundary = {**self.boundary, "blocked_by": codes}
                self.calls.clear()
                result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
                self.assertFalse(result.public_result()["credentials_verified"])
                self.assertEqual(self.calls, [])
        for codes in (["support_message_scope_unverified"], ["support_message_scope_missing"], []):
            with self.subTest(allowed=codes):
                self.repo.boundary = {**self.boundary, "blocked_by": codes,
                                     "status": "blocked" if codes else "metadata_ready"}
                result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
                self.assertTrue(result.public_result()["credentials_verified"])

    def test_expiry_is_verified_before_provider_checks_and_public_status_expires(self):
        original = copy.deepcopy(self.refresh_result)
        for changed in ({"expires_in": None}, {"expires_in": True}, {"expires_in": 0}, {"expires_in": -1},
                        {"expires_in": "7200"}, {"expires_in": float("nan")},
                        {"refreshed_at": int(self.now) - 500}, {"refreshed_at": int(self.now) + 60},
                        {"refreshed_at": None}, {"refreshed_at": True}):
            with self.subTest(changed=changed):
                self.calls.clear()
                self.refresh_result = {**original, **changed}
                result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
                self.assertEqual(result.public_result()["blocked_by"], ["support_token_expiry_invalid"])
                self.assertEqual([call[0] for call in self.calls], ["refresh"])
        self.refresh_result = original
        result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
        self.now += 61
        self.assertFalse(result.public_result()["credentials_verified"])
        self.assertEqual(result.public_result()["blocked_by"], ["support_verified_token_expired"])
        self.assertFalse(result.token_provider(result.scope)["ok"])
        self.assertEqual(len(self.calls), 4)  # Last invalid refresh + one successful three-stage check.

    def test_untrusted_or_cross_scope_metadata_stops_before_refresh(self):
        variants = [None, {}, {**self.boundary, "connection_bound": False},
                    {**self.boundary, "contract_version": "unknown"}, {**self.boundary, "internal": None}]
        for change in ({"company_id": "other"}, {"store_id": "other"}, {"environment": "sandbox"},
                       {"connection_id": ""}, {"secret_ref": ""}, {"oauth_request_id": ""},
                       {"seller_identity_hash": "bad"}, {"owner_username_hash": "a" * 63},
                       {"owner_binding_kind": "raw_fixture"}):
            variants.append({**self.boundary, "internal": {**self.internal, **change}})
        for boundary in variants:
            with self.subTest(boundary=boundary):
                self.calls.clear()
                self.repo.boundary = boundary
                result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
                self.assertFalse(result.public_result()["credentials_verified"])
                self.assertIsNone(result.scope)
                self.assertEqual(self.calls, [])

    def test_refresh_cannot_select_different_connection_ref_or_fallback_source(self):
        original = copy.deepcopy(self.refresh_result)
        variants = [None, {}, {**original, "ok": 1}, {**original, "source": "environment"},
                    {**original, "token_type": "Other"}, {**original, "secret_exposed": True},
                    {**original, "access_token": ""}, {**original, "access_token": "leak\ntoken"}]
        for key in ("company_id", "store_id", "connection_id", "oauth_request_id", "secret_ref", "owner_username_hash"):
            variants.append({**original, "binding": {**self.internal, key: "other"}})
        for status in (201, 302, 400, "200", 200.0):
            variants.append({**original, "http_status": status})
        for response in variants:
            with self.subTest(response=response):
                self.refresh_result = response
                self.calls.clear()
                result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
                self.assertEqual(result.public_result()["blocked_by"], ["support_refresh_binding_invalid"])
                self.assertEqual([call[0] for call in self.calls], ["refresh"])

    def test_introspection_requires_active_same_client_and_explicit_granted_message_scope(self):
        original = copy.deepcopy(self.introspection)
        for changes in ({"active": False}, {"active": 1}, {"client_id": "other"}, {"client_id": None},
                        {"ok": False}, {"secret_exposed": True}, {"http_status": 302}, {"http_status": 200.0},
                        {"scopes": None}, {"scopes": MESSAGE_SCOPE}, {"scopes": []}, {"scopes": ["requested-only"]},
                        {"scopes": [MESSAGE_SCOPE, MESSAGE_SCOPE]}, {"scopes": [MESSAGE_SCOPE, {}]}):
            with self.subTest(changes=changes):
                self.introspection = {**original, **changes}
                self.calls.clear()
                result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
                self.assertFalse(result.public_result()["credentials_verified"])
                self.assertEqual([call[0] for call in self.calls], ["refresh", "introspect"])

    def test_independent_identity_requires_immutable_and_casefold_username_hashes(self):
        original = copy.deepcopy(self.identity)
        for changes in ({"ebay_user_id_hash": digest("other-immutable")},
                        {"ebay_username_hash": digest("other-seller")},
                        {"ebay_username_hash": ""}, {"ebay_user_id_hash": None},
                        {"status": "identity_mapping_unavailable"}, {"secret_exposed": True}):
            with self.subTest(changes=changes):
                self.identity = {**original, **changes}
                result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
                self.assertEqual(result.public_result()["blocked_by"], ["support_owner_identity_mismatch"])
                self.assertIsNone(result.scope)

    def test_connection_replacement_during_verification_is_rejected(self):
        def changed_identity(**kwargs):
            self.repo.boundary = {**self.boundary, "internal": {**self.internal, "secret_ref": "replacement-ref"}}
            return copy.deepcopy(self.identity)
        resolver = self.resolver(verification_enabled=True)
        resolver.get_identity = changed_identity
        result = resolver.resolve(company_id="company-a", store_id="store-a")
        self.assertEqual(result.public_result()["blocked_by"], ["support_connection_changed"])
        self.assertIsNone(result.scope)

    def test_token_provider_rechecks_binding_and_never_refreshes_automatically(self):
        for change in ("revoked", "replacement", "metadata-error"):
            with self.subTest(change=change):
                self.repo.boundary = copy.deepcopy(self.boundary)
                result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
                checked_calls = len(self.calls)
                if change == "revoked":
                    self.repo.boundary["connection_bound"] = False
                elif change == "replacement":
                    self.repo.boundary["internal"]["connection_id"] = "replacement-connection"
                else:
                    self.repo.boundary["blocked_by"] = ["support_metadata_unavailable"]
                token = result.token_provider(result.scope)
                self.assertFalse(token["ok"])
                self.assertNotIn("access_token", token)
                self.assertFalse(result.public_result()["credentials_verified"])
                self.assertEqual(len(self.calls), checked_calls)
                self.repo.boundary = copy.deepcopy(self.boundary)
                self.assertFalse(result.token_provider(result.scope)["ok"])  # Fresh resolve required.

    def test_token_provider_rejects_raw_cross_tenant_store_and_owner_scopes(self):
        result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
        provider_calls = len(self.calls)
        boundary_calls = len(self.repo.calls)
        for scope in (MessageScope("company-a", "store-a", self.internal["owner_username_hash"]),
                      MessageScope("other", "store-a", self.internal["owner_username_hash"],
                                   owner_binding_kind="sha256_casefold_ebay_username"),
                      MessageScope("company-a", "other", self.internal["owner_username_hash"],
                                   owner_binding_kind="sha256_casefold_ebay_username"),
                      MessageScope("company-a", "store-a", digest("other"),
                                   owner_binding_kind="sha256_casefold_ebay_username"), None):
            self.assertFalse(result.token_provider(scope)["ok"])
        self.assertEqual(len(self.calls), provider_calls)
        self.assertEqual(len(self.repo.calls), boundary_calls)

    def test_exceptions_and_provider_error_details_never_escape_public_result(self):
        marker = "synthetic-token-ref-PII-in-provider-exception"
        for stage, expected in (("refresh", "support_refresh_failed"),
                                ("introspect", "support_introspection_failed"),
                                ("get_identity", "support_owner_identity_check_failed")):
            with self.subTest(stage=stage):
                resolver = self.resolver(verification_enabled=True)
                def fail(**kwargs):
                    raise RuntimeError(marker)
                setattr(resolver, stage, fail)
                result = resolver.resolve(company_id="company-a", store_id="store-a")
                self.assertEqual(result.public_result()["blocked_by"], [expected])
                self.assertNotIn(marker, json.dumps(result.public_result()) + repr(result))
        def unavailable(**kwargs):
            raise RuntimeError(marker)
        self.repo.get_support_connection_boundary = unavailable
        result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
        self.assertEqual(result.public_result()["blocked_by"], ["support_connection_metadata_unavailable"])
        self.assertNotIn(marker, json.dumps(result.public_result()))

    def test_actual_identity_helper_casefold_contract_with_injected_offline_transport(self):
        from jiejing_saas.ebay_account_deletion import fetch_ebay_identity_hashes
        username = "Synthetic-Straße"
        self.internal["owner_username_hash"] = digest(username.casefold())
        self.refresh_result["binding"] = copy.deepcopy(self.internal)
        http_calls = []
        def identity_transport(request, timeout):
            http_calls.append(request)
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.full_url, "https://apiz.ebay.com/commerce/identity/v1/user/")
            self.assertEqual(request.get_header("Authorization"), "Bearer " + self.refresh_result["access_token"])
            return 200, {}, json.dumps({"userId": "immutable-seller-a", "username": username.upper()}).encode()
        resolver = self.resolver(verification_enabled=True)
        resolver.get_identity = lambda **kwargs: fetch_ebay_identity_hashes(**kwargs, transport=identity_transport)
        result = resolver.resolve(company_id="company-a", store_id="store-a")
        self.assertTrue(result.public_result()["credentials_verified"])
        self.assertTrue(result.scope.matches_owner(username))
        self.assertEqual(len(http_calls), 1)
        self.assertNotIn(username, json.dumps(result.public_result()))

    def test_real_repository_accessor_is_read_only_and_scope_metadata_is_not_grant_proof(self):
        # Reuse the independently tested synthetic OAuth/callback fixture; no
        # production DB or actual credential is opened.
        import test_jiejing_support_connection_boundary as boundary_tests
        fixture = boundary_tests.SupportConnectionBoundaryTests()
        fixture.setUp()
        try:
            fixture.fixture(verified=False)
            self.repo = fixture.repo
            boundary = fixture.boundary()
            self.internal = boundary["internal"]
            self.refresh_result["binding"] = copy.deepcopy(self.internal)
            self.identity.update(ebay_user_id_hash=self.internal["seller_identity_hash"],
                                 ebay_username_hash=self.internal["owner_username_hash"])
            self.assertFalse(boundary["granted_message_scope_verified"])
            with patch.object(self.repo, "initialize", side_effect=AssertionError("must not initialize")):
                result = self.resolver(verification_enabled=True).resolve(company_id=fixture.company, store_id=fixture.store)
                self.assertTrue(result.public_result()["credentials_verified"])
                self.assertTrue(result.token_provider(result.scope)["ok"])
            self.assertEqual([call[0] for call in self.calls], ["refresh", "introspect", "identity"])
            self.assertEqual(self.calls[0][1]["secret_ref"], fixture.ref)
            self.assertEqual(self.calls[0][1]["connection_id"], fixture.connection_id)
        finally:
            fixture.tearDown()

    def test_invalid_or_reversed_clock_cannot_keep_verified_token_usable(self):
        for clock_value in (float("nan"), float("inf"), None, self.now - 1000):
            with self.subTest(clock_value=clock_value):
                self.now = 1791792000.0
                result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
                self.now = clock_value
                self.assertFalse(result.token_provider(result.scope)["ok"])
                self.assertFalse(result.public_result()["credentials_verified"])

    def test_expiry_during_metadata_recheck_does_not_release_token(self):
        result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
        read = self.repo.get_support_connection_boundary
        def slow_read(**kwargs):
            snapshot = read(**kwargs)
            self.now += 61
            return snapshot
        self.repo.get_support_connection_boundary = slow_read
        token = result.token_provider(result.scope)
        self.assertFalse(token["ok"])
        self.assertNotIn("access_token", token)

    def test_resolver_binding_is_compatible_with_adapter_but_does_not_enable_it(self):
        from jiejing_saas.ebay_message_adapter import EbayMessageAdapter
        result = self.resolver(verification_enabled=True).resolve(company_id="company-a", store_id="store-a")
        http = []
        def fake_transport(request, timeout):
            http.append(request)
            self.assertEqual(request.get_header("Authorization"), "Bearer " + self.refresh_result["access_token"])
            return 200, {}, b'{"conversations":[]}'
        disabled = EbayMessageAdapter(result.scope, token_provider=result.token_provider, transport=fake_transport)
        self.assertEqual(disabled.get_conversations()["status"], "blocked_read_disabled")
        self.assertEqual(disabled.send_reply("conv-1", "Not enabled")["status"], "blocked_send_disabled")
        self.assertEqual(http, [])
        explicitly_enabled_fixture = EbayMessageAdapter(result.scope, token_provider=result.token_provider,
                                                        transport=fake_transport, read_enabled=True)
        self.assertEqual(explicitly_enabled_fixture.get_conversations()["status"], "ok")
        self.assertEqual(len(http), 1)
        self.assertEqual(http[0].get_method(), "GET")


if __name__ == "__main__":
    unittest.main()

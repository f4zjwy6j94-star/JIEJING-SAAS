"""Offline credential adapter contract: synthetic refs/tokens; socket denied."""
from __future__ import annotations

from pathlib import Path
from functools import partial
import json
import os
import sqlite3
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jiejing_saas.support_credential_adapters import SupportCredentialAdapters
from jiejing_saas.config import SaaSSettings
from jiejing_saas.ebay_token_refresh_adapter import EbayVaultTokenRefreshAdapter
from jiejing_saas.ebay_oauth_token_store import EbayLocalOAuthTokenStore
from jiejing_saas.ebay_account_deletion import fetch_ebay_identity_hashes
from jiejing_saas.support_token_resolver import SupportTokenResolver
from jiejing_saas.support_transport import SupportTransport
from jiejing_saas import ebay_token_refresh_adapter as refresh_module
from tools import test_jiejing_support_connection_boundary as boundary_fixture


class SupportCredentialAdaptersTests(unittest.TestCase):
    def setUp(self):
        for name in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex"):
            guard = patch(name, side_effect=AssertionError("network forbidden in this suite"))
            guard.start()
            self.addCleanup(guard.stop)

    def test_disabled_default_never_reads_or_calls_dependencies(self):
        dependencies = {name: Mock(side_effect=AssertionError("must not call")) for name in
                        ("repository", "refresh_adapter", "introspection_adapter", "identity_helper",
                         "credential_transport", "identity_transport")}
        adapter = SupportCredentialAdapters(**dependencies, expected_client_id="synthetic-client")
        results = [adapter.refresh(binding={}, task_scope="support.message.verify"),
                   adapter.introspect(access_token="synthetic", environment="production", expected_client_id="synthetic-client"),
                   adapter.get_identity(access_token="synthetic", environment="production")]
        for result in results:
            self.assertEqual(result["blocked_by"], ["support_credential_adapters_disabled"])
            self.assertFalse(result["ok"])
            self.assertNotIn("access_token", result)
        for value in dependencies.values():
            self.assertEqual(value.mock_calls, [])

    def test_managed_only_refresh_cannot_fall_back_to_local_secrets(self):
        self.setup_enabled()
        self.refresh_object.managed_provider_only = "vault"
        record = self.adapter._read_exact_record(self.binding)
        with patch("jiejing_saas.vault_secret_resolver.VaultSecretResolver._resolution_blockers", return_value=[]), \
             patch("jiejing_saas.vault_secret_resolver._hashicorp_vault_live_ready", side_effect=[True, False]), \
             patch("jiejing_saas.vault_secret_resolver.VaultSecretResolver._resolve_local_secret") as local, \
             patch("jiejing_saas.vault_secret_resolver.VaultSecretResolver._resolve_tencent_ssm_secret") as tencent:
            result = self.refresh_object.refresh_access_token_from_secret_ref(secret_ref=record,
                company_id=self.fixture.company, store_id=self.fixture.store, task_scope="support.message.verify")
        self.assertFalse(result["ok"])
        local.assert_not_called()
        tencent.assert_not_called()
        self.assertEqual(self.transport.call_count, 0)

    def test_reviewed_server_factory_builds_scoped_resolver_without_request_dependencies(self):
        from jiejing_saas.support_credential_adapters import build_support_resolver
        self.setup_enabled()
        self.assertIsNone(build_support_resolver(self.repo, self.settings,
            company_id=self.fixture.company, store_id=self.fixture.store))
        self.assertEqual(self.transport.call_count, 0)
        def reply(request, timeout):
            if request.full_url == self.vault_url:
                payload = {"data": {"data": {"refresh_token": "synthetic-refresh"}}}
            elif request.full_url.endswith("/introspect"):
                payload = {"active": True, "client_id": "synthetic-client", "scope": boundary_fixture.MESSAGE_SCOPE}
            else:
                payload = {"access_token": "synthetic-access", "token_type": "Bearer", "expires_in": 7200}
            return 200, {}, json.dumps(payload).encode()
        self.transport.side_effect = reply
        self.identity_transport.return_value = (200, {}, json.dumps({
            "userId": "synthetic-immutable-user", "username": "synthetic-seller"}).encode())
        resolver = build_support_resolver(self.repo, self.settings,
            company_id=self.fixture.company, store_id=self.fixture.store, enabled=True)
        self.assertIs(type(resolver), SupportTokenResolver)
        self.assertEqual(self.transport.call_count, 0, "construction never resolves secrets or calls a provider")
        resolution = resolver.resolve(company_id=self.fixture.company, store_id=self.fixture.store)
        self.assertTrue(resolution.public_result()["credentials_verified"], resolution.public_result())
        self.assertEqual(self.transport.call_count, 3)
        self.assertEqual(self.identity_transport.call_count, 1)
        self.assertNotIn("synthetic-access", json.dumps(resolution.public_result()))
        self.assertIsNone(build_support_resolver(self.repo, self.settings,
            company_id="foreign-company", store_id=self.fixture.store, enabled=True))

    def setup_enabled(self):
        self.fixture = boundary_fixture.SupportConnectionBoundaryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.fixture(verified=False)
        self.repo = self.fixture.repo
        self.binding = self.fixture.boundary()["internal"]
        env = patch.dict(os.environ, {
            "JIEJING_SAAS_ENV": "local_dev",
            "JIEJING_EBAY_CLIENT_ID": "synthetic-client",
            "JIEJING_EBAY_CLIENT_SECRET": "synthetic-client-secret",
            "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "1",
            "JIEJING_EBAY_OAUTH_ENV": "production",
            "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE": "1",
            "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED": "0",
            "JIEJING_VAULT_PROVIDER": "vault", "JIEJING_VAULT_ENABLED": "1",
            "JIEJING_VAULT_LIVE_RESOLVE_ENABLED": "1", "JIEJING_VAULT_ADDR": "https://vault.example.invalid",
            "JIEJING_VAULT_KEYSPACE": "synthetic", "JIEJING_VAULT_TOKEN": "synthetic-vault-token",
            "JIEJING_VAULT_LOCAL_SECRET_STORE_PATH": str(Path(self.fixture.temp.name) / "never-read.json")}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.settings = SaaSSettings.from_env(db_path=self.repo.db_path,
            runtime_db_path=Path(self.fixture.temp.name) / "unused-runtime.sqlite",
            output_root=Path(self.fixture.temp.name), host="127.0.0.1", port=0)
        self.transport = Mock(return_value=(200, {}, json.dumps({"access_token": "synthetic-access",
                                             "expires_in": 7200, "token_type": "Bearer"}).encode()))
        self.identity_transport = Mock()
        self.vault_url = "https://vault.example.invalid/v1/secret/data/" + "/".join(
            quote(part, safe="") for part in ("synthetic", self.fixture.company, self.fixture.store, self.fixture.ref))
        self.credential_http = SupportTransport(role="credential", enabled=True, vault_url=self.vault_url,
                                                vault_binding=tuple(sorted(self.binding.items())))
        self.identity_http = SupportTransport(role="identity", enabled=True)
        case = self
        class Response:
            def __init__(self, request, reply):
                self.request, (self.status, self.headers, self.raw) = request, reply
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def geturl(self): return self.request.full_url
            def read(self, limit): return self.raw[:limit]
        class Opener:
            def open(self, request, *, timeout):
                boundary = case.identity_transport if "/identity/v1/user/" in request.full_url else case.transport
                return Response(request, boundary(request, timeout))
        network = patch("urllib.request.build_opener", return_value=Opener())
        network.start()
        self.addCleanup(network.stop)
        self.refresh_object = EbayVaultTokenRefreshAdapter(self.settings, transport=self.credential_http)
        self.introspection_object = EbayLocalOAuthTokenStore(self.settings, transport=self.credential_http)
        self.adapter = SupportCredentialAdapters(self.repo, refresh_adapter=self.refresh_object,
            introspection_adapter=self.introspection_object, identity_helper=fetch_ebay_identity_hashes,
            credential_transport=self.credential_http, identity_transport=self.identity_http,
            expected_client_id="synthetic-client", enabled=True)

    def test_refresh_reads_exact_complete_metadata_without_initialization(self):
        self.setup_enabled()
        metadata = {"oauth_request_id": self.fixture.request_id, "credential_owner": "jiejing_saas_backend",
                    "vault_path": "synthetic-vault-route", "nested": {"version": 17}}
        self.fixture.sql("update secret_refs set metadata_json=? where secret_ref=?",
                         (json.dumps(metadata), self.fixture.ref))
        with patch.object(self.repo, "initialize", side_effect=AssertionError("no schema writes")), \
             patch("jiejing_saas.ebay_token_refresh_adapter.VaultSecretResolver.resolve_secret",
                   return_value={"ok": True, "secret_value": "synthetic-refresh", "source": "synthetic-vault"}) as resolve:
            result = self.adapter.refresh(binding=self.binding, task_scope="support.message.verify")
        self.assertTrue(result["ok"], result)
        self.assertEqual(resolve.call_args.kwargs["secret_ref"]["metadata"], metadata)
        self.assertEqual(resolve.call_args.kwargs["secret_ref"]["secret_ref"], self.fixture.ref)
        self.assertEqual(result["binding"], self.binding)
        self.assertEqual(result["access_token"], "synthetic-access")
        self.assertNotIn("metadata", result)
        self.assertNotIn("synthetic-vault-route", json.dumps(result))
        self.assertEqual(self.transport.call_count, 1)
        self.assertEqual(self.transport.call_args.args[0].full_url, "https://api.ebay.com/identity/v1/oauth2/token")

    def test_introspection_proves_configured_client_without_token_store_fallback(self):
        self.setup_enabled()
        self.transport.return_value = (200, {}, json.dumps({"active": True, "client_id": "synthetic-client",
                                    "scope": boundary_fixture.MESSAGE_SCOPE}).encode())
        with patch.object(self.introspection_object, "_read_records", side_effect=AssertionError("no token store")), \
             patch.object(self.introspection_object, "resolve_access_token", side_effect=AssertionError("no fallback")):
            result = self.adapter.introspect(access_token="synthetic-access", environment="production",
                                             expected_client_id="synthetic-client")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["client_id"], "synthetic-client")
        self.assertEqual(result["scopes"], [boundary_fixture.MESSAGE_SCOPE])
        self.assertNotIn("synthetic-access", json.dumps(result))
        self.assertEqual(self.transport.call_count, 1)

    def test_existing_helpers_and_resolver_verify_same_token_offline_but_never_enable_io(self):
        self.setup_enabled()
        self.transport.side_effect = [self.transport.return_value,
            (200, {}, json.dumps({"active": True, "client_id": "synthetic-client",
                                  "scope": boundary_fixture.MESSAGE_SCOPE}).encode())]
        self.identity_transport.return_value = (200, {}, json.dumps({"userId": "synthetic-immutable-user",
                                                   "username": "SYNTHETIC-SELLER"}).encode())
        resolver = SupportTokenResolver(self.repo, refresh=self.adapter.refresh, introspect=self.adapter.introspect,
            get_identity=self.adapter.get_identity, expected_client_id="synthetic-client", verification_enabled=True)
        with patch.object(self.repo, "initialize", side_effect=AssertionError("no DDL")), \
             patch.object(self.introspection_object, "_read_records", side_effect=AssertionError("no token store")), \
             patch("jiejing_saas.ebay_token_refresh_adapter.VaultSecretResolver.resolve_secret",
                   return_value={"ok": True, "secret_value": "synthetic-refresh", "source": "synthetic-vault"}):
            resolution = resolver.resolve(company_id=self.fixture.company, store_id=self.fixture.store)
            public = resolution.public_result()
            self.assertTrue(public["credentials_verified"], public)
            provider_result = resolution.token_provider(resolution.scope)
        self.assertTrue(provider_result["ok"])
        self.assertEqual(provider_result["access_token"], "synthetic-access")
        self.assertFalse(public["read_enabled"])
        self.assertFalse(public["send_enabled"])
        self.assertFalse(public["live_end_to_end_verified"])
        self.assertNotIn("synthetic-access", json.dumps(public) + repr(resolution) + repr(self.adapter))
        identity_request = self.identity_transport.call_args.args[0]
        self.assertEqual(identity_request.full_url, "https://apiz.ebay.com/commerce/identity/v1/user/")
        self.assertEqual(identity_request.get_header("Authorization"), "Bearer synthetic-access")
        self.assertIn(b"token=synthetic-access", self.transport.call_args.args[0].data)
        self.assertEqual(self.identity_transport.call_count, 1)

    def test_known_urlopen_defaults_cannot_be_promoted_by_passing_them_explicitly(self):
        self.setup_enabled()
        self.refresh_object.transport = refresh_module._urlopen_transport
        self.introspection_object.transport = refresh_module._urlopen_transport
        adapter = SupportCredentialAdapters(self.repo, refresh_adapter=self.refresh_object,
            introspection_adapter=self.introspection_object, identity_helper=fetch_ebay_identity_hashes,
            credential_transport=refresh_module._urlopen_transport, identity_transport=self.identity_http,
            expected_client_id="synthetic-client", enabled=True)
        with patch.object(self.introspection_object, "introspect_access_token") as call:
            result = adapter.introspect(access_token="synthetic-access", environment="production",
                                         expected_client_id="synthetic-client")
        self.assertFalse(result["ok"])
        self.assertEqual(call.call_count, 0)

    def test_wrapped_urlopen_defaults_are_rejected_before_credentials(self):
        self.setup_enabled()
        unsafe = partial(refresh_module._urlopen_transport)
        self.refresh_object.transport = unsafe
        self.introspection_object.transport = unsafe
        adapter = SupportCredentialAdapters(self.repo, refresh_adapter=self.refresh_object,
            introspection_adapter=self.introspection_object, identity_helper=fetch_ebay_identity_hashes,
            credential_transport=unsafe, identity_transport=unsafe,
            expected_client_id="synthetic-client", enabled=True)
        with patch("urllib.request.urlopen") as opened:
            result = adapter.introspect(access_token="synthetic-access", environment="production",
                                         expected_client_id="synthetic-client")
        self.assertFalse(result["ok"])
        self.assertEqual(opened.call_count, 0, "a wrapped default cannot reach credentialed I/O")

    def test_unreviewed_secret_providers_are_blocked_before_generic_helper(self):
        self.setup_enabled()
        for provider in ("secret_ref_only", "local", "tencent_ssm", "tencent_kms", "ssm", "unknown"):
            with self.subTest(provider=provider):
                self.settings.vault_provider = provider
                with patch("jiejing_saas.ebay_token_refresh_adapter.build_ebay_token_refresh_adapter_status",
                           side_effect=AssertionError("must not read provider configuration")) as status:
                    result = self.refresh()
                self.assertFalse(result["ok"])
                self.assertEqual(status.call_count, 0)
        self.assertEqual(self.transport.call_count, 0)

    def test_local_flag_or_changed_vault_target_stops_before_secret_configuration(self):
        self.setup_enabled()
        for patch_env in ({"JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED": "1"},
                          {"JIEJING_VAULT_LIVE_RESOLVE_ENABLED": "0"},
                          {"JIEJING_VAULT_ADDR": "https://other.invalid"},
                          {"JIEJING_VAULT_PATH_TEMPLATE": "{keyspace}/different-ref"}):
            with self.subTest(patch_env=patch_env), patch.dict(os.environ, patch_env), \
                 patch("jiejing_saas.ebay_token_refresh_adapter.build_ebay_token_refresh_adapter_status",
                       side_effect=AssertionError("cannot read credential configuration")) as status:
                result = self.refresh()
                self.assertFalse(result["ok"])
                self.assertEqual(status.call_count, 0)
        self.assertEqual(self.transport.call_count, 0)

    def test_wrong_vault_binding_or_wrapper_cannot_be_blessed_by_markers(self):
        self.setup_enabled()
        wrong = {**self.binding, "secret_ref": "different-ref"}
        wrapped = lambda *args: self.credential_http(*args)
        wrapped.safe = True
        for http in (SupportTransport(enabled=True, vault_url=self.vault_url,
                        vault_binding=tuple(sorted(wrong.items()))), wrapped, partial(self.credential_http)):
            self.refresh_object.transport = self.introspection_object.transport = http
            candidate = SupportCredentialAdapters(self.repo, refresh_adapter=self.refresh_object,
                introspection_adapter=self.introspection_object, identity_helper=fetch_ebay_identity_hashes,
                credential_transport=http, identity_transport=self.identity_http,
                expected_client_id="synthetic-client", enabled=True)
            with patch("jiejing_saas.ebay_token_refresh_adapter.build_ebay_token_refresh_adapter_status",
                       side_effect=AssertionError("cannot read credentials")) as status:
                self.assertFalse(candidate.refresh(binding=self.binding, task_scope="support.message.verify")["ok"])
                self.assertEqual(status.call_count, 0)
        self.assertEqual(self.transport.call_count, 0)

    def test_real_hashicorp_helper_uses_only_the_bound_read_then_oauth_no_fallback(self):
        self.setup_enabled()
        self.transport.side_effect = [
            (200, {}, b'{"data":{"data":{"refresh_token":"synthetic-refresh"}}}'),
            self.transport.return_value,
            (200, {}, json.dumps({"active": True, "client_id": "synthetic-client",
                "scope": boundary_fixture.MESSAGE_SCOPE}).encode())]
        self.identity_transport.return_value = (200, {}, json.dumps({
            "userId": "synthetic-immutable-user", "username": "SYNTHETIC-SELLER"}).encode())
        with patch("jiejing_saas.vault_secret_resolver.VaultSecretResolver._resolve_local_secret",
                   side_effect=AssertionError("no local file path")) as local, \
             patch("jiejing_saas.vault_secret_resolver.VaultSecretResolver._resolve_tencent_ssm_secret",
                   side_effect=AssertionError("no SSM path")) as ssm:
            resolver = SupportTokenResolver(self.repo, refresh=self.adapter.refresh, introspect=self.adapter.introspect,
                get_identity=self.adapter.get_identity, expected_client_id="synthetic-client", verification_enabled=True)
            result = resolver.resolve(company_id=self.fixture.company, store_id=self.fixture.store)
        self.assertTrue(result.public_result()["credentials_verified"], result.public_result())
        self.assertFalse(result.public_result()["read_enabled"])
        self.assertFalse(result.public_result()["send_enabled"])
        self.assertEqual(local.call_count, 0)
        self.assertEqual(ssm.call_count, 0)
        self.assertEqual([call.args[0].full_url for call in self.transport.call_args_list], [self.vault_url,
            "https://api.ebay.com/identity/v1/oauth2/token", "https://api.ebay.com/identity/v1/oauth2/token/introspect"])

    def refresh(self, binding=None):
        with patch("jiejing_saas.ebay_token_refresh_adapter.VaultSecretResolver.resolve_secret",
                   return_value={"ok": True, "secret_value": "synthetic-refresh", "source": "synthetic-vault"}):
            return self.adapter.refresh(binding=self.binding if binding is None else binding, task_scope="support.message.verify")

    def test_record_replaced_during_refresh_discards_access_token(self):
        self.setup_enabled()
        def response(*args):
            self.fixture.sql("update secret_refs set metadata_json=? where secret_ref=?", (json.dumps({
                "oauth_request_id": self.fixture.request_id, "credential_owner": "jiejing_saas_backend",
                "vault_path": "changed-synthetic-route"}), self.fixture.ref))
            return self.transport.return_value
        self.transport.side_effect = response
        result = self.refresh()
        self.assertFalse(result["ok"])
        self.assertNotIn("access_token", result)
        self.assertNotIn("changed-synthetic-route", json.dumps(result))

    def test_missing_sqlite_file_and_missing_schema_are_never_created(self):
        self.setup_enabled()
        boundary = self.fixture.boundary()
        for filename, existing in (("missing.sqlite", False), ("empty.sqlite", True)):
            with self.subTest(filename=filename):
                path = Path(self.fixture.temp.name) / filename
                if existing:
                    sqlite3.connect(path).close()
                original = path.read_bytes() if existing else None
                with patch.object(self.repo, "db_path", path), \
                     patch.object(self.repo, "get_support_connection_boundary", return_value=boundary), \
                     patch.object(self.repo, "_connect", side_effect=AssertionError("cannot use create-on-open")), \
                     patch.object(self.repo, "initialize", side_effect=AssertionError("no DDL")):
                    result = self.refresh()
                self.assertFalse(result["ok"])
                self.assertEqual(path.exists(), existing)
                if existing:
                    self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.transport.call_count, 0)

    def test_exact_record_rejects_wrong_tenant_store_ref_and_metadata(self):
        self.setup_enabled()
        boundary = self.fixture.boundary()
        originals = {"company_id": self.fixture.company, "store_id": self.fixture.store,
                     "secret_ref": self.fixture.ref, "purpose": "ebay_refresh_token", "provider": "ebay",
                     "status": "managed_vault_stored", "metadata_json": json.dumps({
                         "oauth_request_id": self.fixture.request_id, "credential_owner": "jiejing_saas_backend"})}
        cases = [("company_id", "other-company"), ("store_id", "other-store"), ("secret_ref", "other-ref"),
                 ("purpose", "model_api_key"), ("provider", "other"), ("status", "revoked"),
                 ("metadata_json", "not-json"), ("metadata_json", "[]"),
                 ("metadata_json", json.dumps({"oauth_request_id": "wrong", "credential_owner": "jiejing_saas_backend"})),
                 ("metadata_json", json.dumps({"oauth_request_id": self.fixture.request_id, "credential_owner": "browser"}))]
        # Pin boundary only to independently exercise exact record validation,
        # rather than letting the real boundary reject all cases first.
        with patch.object(self.repo, "get_support_connection_boundary", return_value=boundary):
            for column, value in cases:
                with self.subTest(column=column, value=value):
                    self.fixture.sql(f"update secret_refs set {column}=? where secret_ref=?", (value, self.fixture.ref))
                    self.assertFalse(self.refresh()["ok"])
                    selected_ref = value if column == "secret_ref" else self.fixture.ref
                    self.fixture.sql(f"update secret_refs set {column}=? where secret_ref=?", (originals[column], selected_ref))
        self.assertEqual(self.transport.call_count, 0)

    def test_read_context_exception_never_returns_partial_record(self):
        self.setup_enabled()
        boundary = self.fixture.boundary()
        for stage in ("enter", "execute", "exit"):
            with self.subTest(stage=stage):
                raw = sqlite3.connect(self.repo.db_path)
                raw.row_factory = sqlite3.Row
                statements = []
                class Context:
                    def __enter__(self):
                        if stage == "enter":
                            raise RuntimeError("synthetic-sensitive-error")
                        return self
                    def __exit__(self, *args):
                        if stage == "exit":
                            raise RuntimeError("synthetic-sensitive-error")
                    def execute(self, sql, params):
                        statements.append(sql)
                        if stage == "execute":
                            raise RuntimeError("synthetic-sensitive-error")
                        return raw.execute(sql, params)
                try:
                    with patch.object(self.repo, "database_engine", "postgres"), \
                         patch.object(self.repo, "get_support_connection_boundary", return_value=boundary), \
                         patch.object(self.repo, "_connect", return_value=Context()), \
                         patch.object(self.repo, "initialize", side_effect=AssertionError("no DDL")):
                        result = self.refresh()
                    self.assertFalse(result["ok"])
                    self.assertNotIn("synthetic-sensitive-error", json.dumps(result))
                    self.assertNotIn("access_token", result)
                    self.assertTrue(all(sql.lstrip().lower().startswith("select ") for sql in statements))
                finally:
                    raw.close()
        self.assertEqual(self.transport.call_count, 0)

    def test_revoked_or_changed_owner_during_refresh_discards_token(self):
        self.setup_enabled()
        for change in ("revoked", "owner"):
            with self.subTest(change=change):
                self.fixture.sql("update platform_connections set status='read_only_authorized' where connection_id=?",
                                 (self.fixture.connection_id,))
                self.fixture.patch_metadata({})
                def response(*args):
                    if change == "revoked":
                        self.fixture.sql("update platform_connections set status='revoked' where connection_id=?",
                                         (self.fixture.connection_id,))
                    else:
                        self.fixture.patch_metadata({"ebay_username_hash": boundary_fixture.digest("changed-owner")})
                    return self.transport.return_value
                self.transport.side_effect = response
                result = self.refresh()
                self.assertFalse(result["ok"])
                self.assertNotIn("access_token", result)
        self.assertEqual(self.transport.call_count, 2)

    def test_unknown_or_ambiguous_boundary_blocker_cannot_enter_refresh(self):
        self.setup_enabled()
        original = self.fixture.boundary()
        for code in ("support_metadata_unavailable", "support_connection_ambiguous", "unknown"):
            with self.subTest(code=code), patch.object(self.repo, "get_support_connection_boundary",
                return_value={**original, "status": "blocked", "blocked_by": [code]}):
                result = self.refresh()
                self.assertFalse(result["ok"])
        self.assertEqual(self.transport.call_count, 0)

    def test_introspection_malformed_json_wrong_client_and_non_200_fail_closed(self):
        self.setup_enabled()
        valid = {"active": True, "client_id": "synthetic-client", "scope": boundary_fixture.MESSAGE_SCOPE}
        cases = [(200, b"not-json"), (200, b"[]"), (200, b"null"),
                 (200, json.dumps({**valid, "client_id": "other-client"}).encode()),
                 (200, json.dumps({**valid, "active": False}).encode()),
                 (302, json.dumps(valid).encode()), (201, json.dumps(valid).encode()),
                 (200, json.dumps({**valid, "scope": []}).encode())]
        for status, raw in cases:
            with self.subTest(status=status, raw=raw):
                self.transport.return_value = (status, {}, raw)
                result = self.adapter.introspect(access_token="synthetic-access", environment="production",
                                                 expected_client_id="synthetic-client")
                self.assertFalse(result["ok"])
                self.assertNotIn("client_id", result)
                self.assertNotIn("synthetic-access", json.dumps(result))

    def test_mismatched_config_or_requested_client_is_not_echoed_as_proof(self):
        self.setup_enabled()
        for requested, configured, environment in (("other-client", "synthetic-client", "production"),
                ("synthetic-client", "other-client", "production"),
                ("synthetic-client", "synthetic-client", "sandbox")):
            with self.subTest(requested=requested, configured=configured, environment=environment):
                self.settings.ebay_client_id = configured
                result = self.adapter.introspect(access_token="synthetic-access", environment=environment,
                                                 expected_client_id=requested)
                self.assertFalse(result["ok"])
        self.assertEqual(self.transport.call_count, 0)

    def test_client_configuration_changed_during_introspection_fails_closed(self):
        self.setup_enabled()
        def response(*args):
            self.settings.ebay_client_id = "changed-client"
            return 200, {}, json.dumps({"active": True, "client_id": "changed-client",
                                       "scope": boundary_fixture.MESSAGE_SCOPE}).encode()
        self.transport.side_effect = response
        result = self.adapter.introspect(access_token="synthetic-access", environment="production",
                                         expected_client_id="synthetic-client")
        self.assertFalse(result["ok"])
        self.assertNotIn("client_id", result)

    def test_identity_returns_only_two_hashes_and_fails_on_partial_or_malformed_response(self):
        self.setup_enabled()
        for raw in (b"not-json", b"[]", json.dumps({"userId": "synthetic-immutable-user"}).encode()):
            with self.subTest(raw=raw):
                self.identity_transport.return_value = (200, {}, raw)
                result = self.adapter.get_identity(access_token="synthetic-access", environment="production")
                self.assertFalse(result["ok"])
                self.assertNotIn("ebay_user_id_hash", result)
        self.identity_transport.return_value = (200, {}, json.dumps({"userId": "synthetic-immutable-user",
            "username": "SYNTHETIC-SELLER", "accountType": "BUSINESS", "status": "CONFIRMED"}).encode())
        result = self.adapter.get_identity(access_token="synthetic-access", environment="production")
        self.assertEqual(set(result), {"status", "ebay_user_id_hash", "ebay_username_hash", "secret_exposed"})
        self.assertEqual(result["ebay_username_hash"], self.binding["owner_username_hash"])

    def test_dependency_configuration_must_be_explicit_and_consistent(self):
        self.setup_enabled()
        original_transport = self.refresh_object.transport
        cases = [("refresh_transport", None), ("identity_transport", None), ("helper", None),
                 ("environment", "sandbox"), ("introspection_client", "other-client")]
        for name, value in cases:
            with self.subTest(name=name):
                introspection_settings = SaaSSettings.from_env(db_path=self.repo.db_path,
                    runtime_db_path=Path(self.fixture.temp.name) / "unused.sqlite",
                    output_root=Path(self.fixture.temp.name), host="127.0.0.1", port=0)
                if name == "introspection_client":
                    introspection_settings.ebay_client_id = value
                self.introspection_object.settings = introspection_settings
                self.settings.ebay_oauth_environment = value if name == "environment" else "production"
                self.refresh_object.transport = value if name == "refresh_transport" else original_transport
                candidate = SupportCredentialAdapters(self.repo, refresh_adapter=self.refresh_object,
                    introspection_adapter=self.introspection_object,
                    identity_helper=value if name == "helper" else fetch_ebay_identity_hashes,
                    credential_transport=self.credential_http,
                    identity_transport=value if name == "identity_transport" else self.identity_http,
                    expected_client_id="synthetic-client", enabled=True)
                self.assertFalse(candidate.refresh(binding=self.binding, task_scope="support.message.verify")["ok"])
        self.assertEqual(self.transport.call_count, 0)
        self.assertEqual(self.identity_transport.call_count, 0)

    def test_refresh_adapter_error_and_unexpected_success_status_never_escape(self):
        self.setup_enabled()
        for status, raw in ((302, b'{"access_token":"synthetic-access"}'),
                            (400, b'{"error_description":"synthetic-secret-do-not-echo"}'),
                            (200, b"broken-json")):
            with self.subTest(status=status, raw=raw):
                self.transport.return_value = (status, {}, raw)
                result = self.refresh()
                self.assertFalse(result["ok"])
                self.assertNotIn("synthetic-secret", json.dumps(result))
                self.assertNotIn("access_token", result)
        self.transport.side_effect = RuntimeError("synthetic-secret-error")
        self.assertNotIn("synthetic-secret", json.dumps(self.refresh()))

    def test_record_query_only_uses_bound_parameters_and_select(self):
        self.setup_enabled()
        boundary = self.fixture.boundary()
        queries = []
        def connection():
            raw = sqlite3.connect(self.repo.db_path)
            raw.row_factory = sqlite3.Row
            class ExistingConnection:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    raw.close()
                def execute(self, sql, params):
                    queries.append((sql, params))
                    return raw.execute(sql, params)
            return ExistingConnection()
        with patch.object(self.repo, "database_engine", "postgres"), \
             patch.object(self.repo, "get_support_connection_boundary", return_value=boundary), \
             patch.object(self.repo, "_connect", side_effect=connection), \
             patch.object(self.repo, "initialize", side_effect=AssertionError("no DDL")):
            result = self.refresh()
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(queries), 3)
        for sql, params in queries:
            self.assertTrue(sql.lstrip().lower().startswith("select "))
            self.assertEqual(params, (self.fixture.company, self.fixture.store, self.fixture.ref))
            self.assertEqual(sql.count("?"), 3)
            self.assertNotIn(self.fixture.ref, sql)

    def test_current_boundary_owner_change_during_identity_is_rejected_by_resolver(self):
        self.setup_enabled()
        self.transport.side_effect = [self.transport.return_value,
            (200, {}, json.dumps({"active": True, "client_id": "synthetic-client",
                                  "scope": boundary_fixture.MESSAGE_SCOPE}).encode())]
        def response(*args):
            self.fixture.patch_metadata({"ebay_username_hash": boundary_fixture.digest("changed-owner")})
            return 200, {}, json.dumps({"userId": "synthetic-immutable-user", "username": "synthetic-seller"}).encode()
        self.identity_transport.side_effect = response
        resolver = SupportTokenResolver(self.repo, refresh=self.adapter.refresh, introspect=self.adapter.introspect,
            get_identity=self.adapter.get_identity, expected_client_id="synthetic-client", verification_enabled=True)
        with patch("jiejing_saas.ebay_token_refresh_adapter.VaultSecretResolver.resolve_secret",
                   return_value={"ok": True, "secret_value": "synthetic-refresh", "source": "synthetic-vault"}):
            resolution = resolver.resolve(company_id=self.fixture.company, store_id=self.fixture.store)
        self.assertFalse(resolution.public_result()["credentials_verified"])
        self.assertIn("support_connection_changed", resolution.public_result()["blocked_by"])
        self.assertNotIn("access_token", resolution.token_provider(None))


if __name__ == "__main__":
    unittest.main()

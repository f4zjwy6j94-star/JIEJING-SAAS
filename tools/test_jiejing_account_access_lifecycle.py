"""Account access behavior over loopback HTTP; synthetic disposable accounts only."""
from __future__ import annotations

import json
import gc
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from contextlib import closing, contextmanager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class AccountAccessLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="jiejing-account-access-")
        cls.path = Path(cls.directory.name)
        cls.db = cls.path / "saas.sqlite"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        cls.base = f"http://127.0.0.1:{port}"
        # Never inherit model, platform, database, Vault or payment credentials.
        allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
                   "LOCALAPPDATA", "APPDATA", "USERPROFILE", "PROGRAMFILES"}
        env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                   JIEJING_SAAS_ENV="test", JIEJING_DATABASE_ENGINE="sqlite",
                   JIEJING_ENABLE_REAL_PLATFORM_WRITES="0", JIEJING_EBAY_WRITE_LIVE="0",
                   JIEJING_PUBLIC_CHARGING_ALLOWED="false",
                   JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP="0",
                   JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED="0",
                   JIEJING_AI_CEO_PLATFORM_MODEL_ENABLED="0",
                   JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED="0",
                   JIEJING_AI_CEO_BUILTIN_WEB_FALLBACK_ENABLED="0",
                   JIEJING_ENABLE_HERMES_EBAY_BRIDGE="0")
        cls.fixture_env = env
        cls.process = subprocess.Popen([
            sys.executable, str(ROOT / "tools/jiejing_saas_backend_cli.py"), "serve",
            "--db", str(cls.db), "--runtime-db", str(cls.path / "runtime.sqlite"),
            "--output-root", str(cls.path), "--host", "127.0.0.1", "--port", str(port),
        ], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_server)
        cls._wait_for_server(phase="initial")

    @classmethod
    def _wait_for_server(cls, *, phase):
        started = time.monotonic()
        deadline = started + 60.0
        last_probe = "not_attempted"
        while True:
            code = cls.process.poll()
            now = time.monotonic()
            if code is not None:
                raise AssertionError(
                    f"{phase}: owned fixture exited {code} after "
                    f"{now - started:.3f}s; last_probe={last_probe}")
            remaining = deadline - now
            if remaining <= 0:
                raise AssertionError(
                    f"{phase}: owned fixture readiness deadline after "
                    f"{now - started:.3f}s; last_probe={last_probe}")
            status = None
            try:
                status = cls.request("/health", timeout=min(1.0, remaining))[0]
                last_probe = f"HTTP {status}"
            except OSError as error:
                last_probe = type(error).__name__
            code = cls.process.poll()
            now = time.monotonic()
            if code is not None:
                raise AssertionError(
                    f"{phase}: owned fixture exited {code} after "
                    f"{now - started:.3f}s; last_probe={last_probe}")
            if now >= deadline:
                raise AssertionError(
                    f"{phase}: owned fixture readiness deadline after "
                    f"{now - started:.3f}s; last_probe={last_probe}")
            if status == 200:
                return
            time.sleep(min(0.1, deadline - now))

    @classmethod
    def stop_server(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)
        gc.collect()
        cls.directory.cleanup()

    @classmethod
    def request(cls, path, payload=None, *, access="", refresh="", timeout=15):
        headers = {"Accept": "application/json"}
        if access:
            headers["Authorization"] = "Bearer " + access
        if refresh:
            headers["Cookie"] = "jiejing_saas_refresh=" + refresh
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        if data is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = urllib.request.urlopen(urllib.request.Request(cls.base + path, data=data, headers=headers), timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            cookies = SimpleCookie()
            for value in response.headers.get_all("Set-Cookie", []):
                cookies.load(value)
            return response.status, json.load(response), {key: item.value for key, item in cookies.items()}

    def account(self, name):
        credentials = {"email": f"{name}@example.test", "password": "synthetic-local-password"}
        status, body, cookies = self.request("/auth/register", {**credentials, "company_name": name})
        self.assertEqual(status, 201)
        return credentials, body["user"]["user_id"], body["company"]["company_id"], body["token"], cookies["jiejing_saas_refresh"]

    def setUp(self):
        # Each case has an independent abuse-control window in its owned fixture;
        # do not disable the product limiter just to run many synthetic users.
        with closing(sqlite3.connect(self.db)) as connection:
            with connection:
                connection.execute("delete from api_rate_limit_buckets")

    def fixture_status(self, user_id, status):
        # Inject out-of-band account state into our disposable fixture only.
        with closing(sqlite3.connect(self.db)) as connection:
            with connection:
                connection.execute("update users set status=? where user_id=?", (status, user_id))

    @contextmanager
    def local_application(self, handler, *, internal_admin_emails=None):
        import http.client
        import threading
        from jiejing_saas.api_server import JiejingSafeThreadingHTTPServer
        from jiejing_saas.config import SaaSSettings
        from jiejing_saas.security import SessionManager
        handler.settings = SaaSSettings.from_env(db_path=self.db,
            runtime_db_path=self.path / "race-runtime.sqlite", output_root=self.path / "race-output", host="127.0.0.1", port=0)
        if internal_admin_emails is not None:
            handler.settings.internal_admin_emails = internal_admin_emails
        handler.sessions = SessionManager(secret="local-dev-session-secret-change-me", ttl_seconds=600)
        server = JiejingSafeThreadingHTTPServer(("127.0.0.1", 0), handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        def request(path, payload, *, access="", headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=15)
            request_headers = {"Content-Type": "application/json", **(headers or {})}
            if access:
                request_headers["Authorization"] = "Bearer " + access
            try:
                connection.request("POST", path, json.dumps(payload), request_headers)
                response = connection.getresponse()
                return response.status, json.loads(response.read()), response.getheader("Set-Cookie")
            finally:
                connection.close()
        try:
            yield request
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

    def test_switch_cannot_use_a_source_session_revoked_after_authentication(self):
        from jiejing_saas.api_server import SaaSBackendHandler
        from jiejing_saas.repository import SaaSRepository
        from jiejing_saas.security import SessionManager
        credentials, user, home, _, _ = self.account("source-session-revocation")
        _, owner, company, _, _ = self.account("source-session-target")
        repo = SaaSRepository(self.db, database_engine="sqlite", database_url="")
        repo.create_team_invitation(company_id=company, invited_by=owner, email=credentials["email"], role="operator")
        manager = SessionManager(secret="local-dev-session-secret-change-me")
        for kind in ("family", "access_jti", "other_devices", "refresh_logout"):
            with self.subTest(kind=kind):
                status, body, cookies = self.request("/auth/login", credentials)
                self.assertEqual(status, 200)
                source = manager.verify_token(body["token"])
                other = repo.create_browser_refresh_session(user_id=user, company_id=home,
                    device_class="desktop", ttl_seconds=3600)
                class Handler(SaaSBackendHandler):
                    repository = repo
                    def _issue_browser_session(self, **kwargs):
                        if kind == "family":
                            repo.revoke_browser_session(user_id=user, company_id=home, session_id=source["sid"])
                        elif kind == "access_jti":
                            repo.revoke_user_session(user_id=user, jti=source["jti"])
                        elif kind == "refresh_logout":
                            repo.revoke_browser_session_by_refresh_token(refresh_token=cookies["jiejing_saas_refresh"])
                        else:
                            repo.revoke_other_browser_sessions(user_id=user, company_id=home,
                                current_session_id=other["session"]["session_ref"])
                        return super()._issue_browser_session(**kwargs)
                with self.local_application(Handler) as request:
                    status, result, set_cookie = request("/auth/switch-company", {"company_id": company}, access=body["token"])
                self.assertEqual(status, 401, "revoked source must not mint a new company family")
                self.assertNotIn("token", result)
                self.assertFalse(set_cookie)

    def test_all_password_issuance_routes_revalidate_epoch_and_keep_snapshots_private(self):
        from jiejing_saas.api_server import SaaSBackendHandler
        from jiejing_saas.repository import SaaSRepository
        from jiejing_saas.security import SessionManager
        credentials, user, _, _, _ = self.account("all-issuers")
        repo = SaaSRepository(self.db, database_engine="sqlite", database_url="")
        routes = [
            ("/auth/login", credentials, {}),
            ("/owner/auth/login", credentials, {"Host": "ops.jiejing.shop"}),
            ("/auth/demo-session", credentials, {}),
            ("/auth/register", {"email": "register-issuance-race@example.test", "password": credentials["password"]}, {}),
            ("/auth/demo-session", {"email": "demo-issuance-race@example.test", "password": credentials["password"]}, {}),
        ]
        class RacingHandler(SaaSBackendHandler):
            repository = repo
            def _issue_browser_session(self, **kwargs):
                repo.set_user_access_status(user_id=kwargs["user_id"], status="disabled")
                repo.set_user_access_status(user_id=kwargs["user_id"], status="active")
                return super()._issue_browser_session(**kwargs)
        with self.local_application(RacingHandler, internal_admin_emails=[credentials["email"]]) as request:
            for path, payload, headers in routes:
                with self.subTest(path=path, email=payload["email"]):
                    status, result, cookie = request(path, payload, headers=headers)
                    self.assertEqual(status, 401, result)
                    self.assertNotIn("token", result)
                    self.assertFalse(cookie)
        class NormalHandler(SaaSBackendHandler):
            repository = repo
        manager = SessionManager(secret="local-dev-session-secret-change-me")
        with self.local_application(NormalHandler, internal_admin_emails=[credentials["email"]]) as request:
            for path, payload, headers in routes[:3]:
                with self.subTest(normal=path):
                    status, result, cookie = request(path, payload, headers=headers)
                    self.assertEqual(status, 201 if path == "/auth/demo-session" else 200, result)
                    self.assertTrue(cookie)
                    self.assertFalse({"access_epochs", "user_epoch", "member_epoch"} & result.keys())
                    self.assertFalse({"access_epochs", "user_epoch", "member_epoch"} & result.get("user", {}).keys())
                    if result.get("token"):
                        identity = manager.verify_token(result["token"])
                        self.assertGreater(identity["user_epoch"], 0)
                        self.assertTrue(repo.ensure_user_session(identity)["active"])

    def test_disabled_account_cannot_log_in(self):
        credentials, user_id, _, access, _ = self.account("disabled-login")
        self.assertEqual(self.request("/me", access=access)[0], 200)
        self.fixture_status(user_id, "disabled")
        status, body, cookies = self.request("/auth/login", credentials)
        self.assertEqual(status, 401, "disabled account must not issue a new session")
        self.assertEqual(body["error"], "invalid email or password")
        self.assertNotIn("token", body)
        self.assertNotIn("jiejing_saas_refresh", cookies)

    def test_disabled_account_loses_old_access_without_reviving_on_enable(self):
        _, user_id, company_id, access, _ = self.account("disabled-access")
        self.fixture_status(user_id, "disabled")
        self.assertEqual(self.request("/me", access=access)[0], 401)
        self.assertEqual(self.request("/auth/switch-company", {"company_id": company_id}, access=access)[0], 401)
        self.fixture_status(user_id, "active")
        self.assertEqual(self.request("/me", access=access)[0], 401, "observed revoked access must not revive")

    def test_disabled_account_cannot_refresh_before_any_access_check(self):
        credentials, user_id, _, access, refresh = self.account("disabled-refresh")
        self.fixture_status(user_id, "disabled")
        status, body, cookies = self.request("/auth/refresh", {}, refresh=refresh)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "session_refresh_invalid")
        self.assertFalse(cookies.get("jiejing_saas_refresh"))
        self.fixture_status(user_id, "active")
        self.assertEqual(self.request("/auth/refresh", {}, refresh=refresh)[0], 401)
        self.assertEqual(self.request("/me", access=access)[0], 401)
        self.assertEqual(self.request("/auth/login", credentials)[0], 200)

    def test_rotation_rechecks_disabled_user_after_preflight(self):
        from jiejing_saas.repository import SaaSRepository
        _, user_id, _, _, refresh = self.account("disabled-between-refresh")
        repository = SaaSRepository(self.db, database_engine="sqlite", database_url="")
        self.assertEqual(repository.browser_refresh_session_identity(refresh_token=refresh)["user_id"], user_id)
        self.fixture_status(user_id, "disabled")
        with self.assertRaisesRegex(ValueError, "session_refresh_invalid"):
            repository.rotate_browser_refresh_session(refresh_token=refresh)
        self.fixture_status(user_id, "active")
        with self.assertRaisesRegex(ValueError, "session_refresh_invalid"):
            repository.rotate_browser_refresh_session(refresh_token=refresh)

    def test_status_transition_revokes_sessions_without_waiting_for_a_request(self):
        from jiejing_saas.repository import SaaSRepository
        credentials, user_id, _, access, refresh = self.account("disabled-transition")
        repository = SaaSRepository(self.db, database_engine="sqlite", database_url="")
        repository.set_user_access_status(user_id=user_id, status="disabled")
        repository.set_user_access_status(user_id=user_id, status="active")
        self.assertEqual(self.request("/me", access=access)[0], 401)
        self.assertEqual(self.request("/auth/refresh", {}, refresh=refresh)[0], 401)
        self.assertEqual(self.request("/auth/login", credentials)[0], 200)

    def test_never_seen_legacy_access_cannot_revive_after_disable_enable(self):
        from jiejing_saas.repository import SaaSRepository
        from jiejing_saas.security import SessionManager
        credentials, user_id, company_id, _, _ = self.account("unseen-legacy")
        # A legitimately signed, pre-migration token never presented to the DB.
        # The fixed secret belongs only to this disposable local test server.
        token = SessionManager(secret="local-dev-session-secret-change-me").create_token(
            user_id=user_id, company_id=company_id, email=credentials["email"])
        repository = SaaSRepository(self.db, database_engine="sqlite", database_url="")
        repository.set_user_access_status(user_id=user_id, status="disabled")
        repository.set_user_access_status(user_id=user_id, status="active")
        self.assertEqual(self.request("/me", access=token)[0], 401,
                         "unregistered signed token must not revive without a disabled-time request")
        status, fresh, _ = self.request("/auth/login", credentials)
        self.assertEqual(status, 200)
        self.assertEqual(self.request("/me", access=fresh["token"])[0], 200)

    def test_member_remove_readd_revokes_unknown_and_known_target_sessions_only(self):
        from jiejing_saas.repository import SaaSRepository
        from jiejing_saas.security import SessionManager
        credentials, user, home, home_access, home_refresh = self.account("member-lifecycle")
        _, owner, company, _, _ = self.account("member-owner")
        repository = SaaSRepository(self.db, database_engine="sqlite", database_url="")
        repository.create_team_invitation(company_id=company, invited_by=owner,
            email=credentials["email"], role="operator")
        # Signed but never registered and without a refresh family.
        unseen = SessionManager(secret="local-dev-session-secret-change-me").create_token(
            user_id=user, company_id=company, email=credentials["email"])
        status, switched, cookies = self.request("/auth/switch-company", {"company_id": company}, access=home_access)
        self.assertEqual(status, 200)
        second_access, second_refresh = switched["token"], cookies["jiejing_saas_refresh"]
        _, fresh_home, home_cookies = self.request("/auth/login", credentials)
        repository.set_team_member_access(company_id=company, user_id=user, role=None, actor_user_id=owner)
        repository.create_team_invitation(company_id=company, invited_by=owner,
            email=credentials["email"], role="operator")
        for token in (unseen, second_access):
            self.assertEqual(self.request("/me", access=token)[0], 401)
        self.assertEqual(self.request("/auth/refresh", {}, refresh=second_refresh)[0], 401)
        self.assertEqual(self.request("/me", access=fresh_home["token"])[0], 200)
        self.assertEqual(self.request("/auth/refresh", {}, refresh=home_cookies["jiejing_saas_refresh"])[0], 200)
        status, new_target, _ = self.request("/auth/switch-company", {"company_id": company}, access=fresh_home["token"])
        self.assertEqual(status, 200)
        self.assertEqual(self.request("/me", access=new_target["token"])[0], 200)

    def test_existing_invitation_entry_rechecks_active_inviter_permission(self):
        from jiejing_saas.repository import SaaSRepository
        _, owner, company, _, _ = self.account("invite-owner")
        member_credentials, member, _, _, _ = self.account("invite-operator")
        credentials, target, _, _, _ = self.account("invite-target")
        repository = SaaSRepository(self.db, database_engine="sqlite", database_url="")
        repository.create_team_invitation(company_id=company, invited_by=owner,
            email=member_credentials["email"], role="operator")
        with self.assertRaisesRegex(ValueError, "team management not allowed"):
            repository.create_team_invitation(company_id=company, invited_by=member,
                email=credentials["email"], role="admin")
        repository.set_user_access_status(user_id=owner, status="disabled")
        with self.assertRaisesRegex(ValueError, "team management not allowed"):
            repository.create_team_invitation(company_id=company, invited_by=owner,
                email=credentials["email"], role="admin")
        self.assertIsNone(repository.get_team_member(company_id=company, user_id=target))

    def test_member_role_change_revokes_old_sessions_and_protects_last_owner(self):
        from jiejing_saas.repository import SaaSRepository
        credentials, member, _, access, _ = self.account("role-member")
        _, owner, company, _, _ = self.account("role-owner")
        repo = SaaSRepository(self.db, database_engine="sqlite", database_url="")
        repo.create_team_invitation(company_id=company, invited_by=owner, email=credentials["email"], role="admin")
        status, target, cookies = self.request("/auth/switch-company", {"company_id": company}, access=access)
        self.assertEqual(status, 200)
        with self.assertRaisesRegex(ValueError, "team management not allowed"):
            repo.set_team_member_access(company_id=company, user_id=member, role="owner", actor_user_id=member)
        repo.set_team_member_access(company_id=company, user_id=member, role="viewer", actor_user_id=owner)
        self.assertEqual(self.request("/me", access=target["token"])[0], 401)
        self.assertEqual(self.request("/auth/refresh", {}, refresh=cookies["jiejing_saas_refresh"])[0], 401)
        for role in (None, "admin"):
            with self.assertRaisesRegex(ValueError, "last active owner"):
                repo.set_team_member_access(company_id=company, user_id=owner, role=role, actor_user_id=owner)
        repo.set_team_member_access(company_id=company, user_id=member, role="owner", actor_user_id=owner)
        repo.set_team_member_access(company_id=company, user_id=owner, role="viewer", actor_user_id=member)
        self.assertEqual(repo.get_team_member(company_id=company, user_id=member)["role"], "owner")
        self.assertEqual(repo.get_team_member(company_id=company, user_id=owner)["role"], "viewer")

    @staticmethod
    def signed_fixture_claims(claims):
        import base64
        import hashlib
        import hmac
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        signature = base64.urlsafe_b64encode(hmac.new(b"local-dev-session-secret-change-me",
            payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")
        return payload + "." + signature

    def test_epoch_claims_are_strict_and_legacy_upgrade_preserves_valid_sessions(self):
        from jiejing_saas.repository import SaaSRepository
        from jiejing_saas.security import SessionManager
        credentials, user, company, access, _ = self.account("epoch-claims")
        manager = SessionManager(secret="local-dev-session-secret-change-me")
        claims = {"user_id": user, "company_id": company, "email": credentials["email"], "exp": int(time.time()) + 600}
        # Older no-jti/no-iat tokens have a synthetic stable jti after verification.
        legacy = self.signed_fixture_claims(claims)
        self.assertEqual(self.request("/me", access=legacy)[0], 200)
        for invalid in ({"user_epoch": 0}, {"member_epoch": 0},
                        {"user_epoch": -1, "member_epoch": 0},
                        {"user_epoch": True, "member_epoch": 0},
                        {"user_epoch": "0", "member_epoch": 0}):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.request("/me", access=self.signed_fixture_claims({**claims, **invalid}))[0], 401)
        repo = SaaSRepository(self.db, database_engine="sqlite", database_url="")
        unseen_new = manager.create_token(user_id=user, company_id=company, email=credentials["email"],
            access_epochs=repo.access_session_epochs(user_id=user, company_id=company))
        repo.set_user_access_status(user_id=user, status="disabled")
        repo.set_user_access_status(user_id=user, status="active")
        for token in (legacy, access, unseen_new):
            self.assertEqual(self.request("/me", access=token)[0], 401)

    def test_revocation_tombstone_survives_server_restart_and_reinvite(self):
        from jiejing_saas.repository import SaaSRepository
        from jiejing_saas.security import SessionManager
        credentials, user, _, _, _ = self.account("restart-member")
        _, owner, company, _, _ = self.account("restart-owner")
        repo = SaaSRepository(self.db, database_engine="sqlite", database_url="")
        repo.create_team_invitation(company_id=company, invited_by=owner, email=credentials["email"], role="operator")
        unseen = SessionManager(secret="local-dev-session-secret-change-me").create_token(
            user_id=user, company_id=company, email=credentials["email"])
        repo.set_team_member_access(company_id=company, user_id=user, role=None, actor_user_id=owner)
        command = type(self).process.args
        type(self).process.terminate()
        type(self).process.wait(timeout=5)
        type(self).process = subprocess.Popen(command, cwd=ROOT, env=self.fixture_env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        type(self)._wait_for_server(phase="restart")
        restarted = SaaSRepository(self.db, database_engine="sqlite", database_url="")
        restarted.create_team_invitation(company_id=company, invited_by=owner, email=credentials["email"], role="operator")
        self.assertEqual(self.request("/me", access=unseen)[0], 401)
        self.assertEqual(self.request("/auth/login", credentials)[0], 200)

    def test_password_verified_before_disable_enable_cannot_issue_a_session(self):
        import http.client
        import threading
        from jiejing_saas.api_server import SaaSBackendHandler, JiejingSafeThreadingHTTPServer
        from jiejing_saas.config import SaaSSettings
        from jiejing_saas.repository import SaaSRepository
        from jiejing_saas.security import SessionManager
        credentials, user, _, _, _ = self.account("login-aba")
        repo = SaaSRepository(self.db, database_engine="sqlite", database_url="")
        class Handler(SaaSBackendHandler):
            repository = repo
            def _issue_browser_session(self, **kwargs):
                repo.set_user_access_status(user_id=user, status="disabled")
                repo.set_user_access_status(user_id=user, status="active")
                return super()._issue_browser_session(**kwargs)
        Handler.settings = SaaSSettings.from_env(db_path=self.db,
            runtime_db_path=self.path / "race-runtime.sqlite", output_root=self.path / "race-output", host="127.0.0.1", port=0)
        Handler.sessions = SessionManager(secret="synthetic-race-secret", ttl_seconds=600)
        server = JiejingSafeThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=15)
        try:
            connection.request("POST", "/auth/login", json.dumps(credentials), {"Content-Type": "application/json"})
            response = connection.getresponse()
            body = json.loads(response.read())
            self.assertEqual(response.status, 401, "credential verification before revocation cannot issue after reenabling")
            self.assertNotIn("token", body)
            self.assertFalse(response.getheader("Set-Cookie"))
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

    def test_inactive_user_is_rejected_at_permission_and_admin_checks(self):
        from types import SimpleNamespace
        from jiejing_saas.api_server import SaaSBackendHandler
        from jiejing_saas.repository import SaaSRepository
        credentials, user_id, company_id, _, _ = self.account("disabled-permission")
        identity = {"user_id": user_id, "company_id": company_id, "email": credentials["email"]}
        errors = []
        handler = SimpleNamespace(
            repository=SaaSRepository(self.db, database_engine="sqlite", database_url=""),
            settings=SimpleNamespace(internal_admin_emails=[credentials["email"]]),
            _send_error=lambda *args: errors.append(args),
        )
        self.assertTrue(SaaSBackendHandler._require_permission(handler, identity, "manage_team"))
        self.assertTrue(SaaSBackendHandler._is_platform_internal_admin(handler, identity))
        self.fixture_status(user_id, "disabled")
        self.assertFalse(SaaSBackendHandler._require_permission(handler, identity, "manage_team"))
        self.assertFalse(SaaSBackendHandler._is_platform_internal_admin(handler, identity))
        self.assertEqual(errors[0][0], 403)

    def test_removed_membership_revokes_only_that_company_and_does_not_revive(self):
        credentials, user_id, home_company, home_access, home_refresh = self.account("removed-member")
        _, _, second_company, _, _ = self.account("second-company")
        with closing(sqlite3.connect(self.db)) as connection:
            with connection:
                connection.execute("insert into team_members(company_id,user_id,role,created_at) values(?,?,?,?)",
                                   (second_company, user_id, "operator", "2026-10-14T00:00:00Z"))
        status, switched, cookies = self.request("/auth/switch-company", {"company_id": second_company}, access=home_access)
        self.assertEqual(status, 200)
        second_access, second_refresh = switched["token"], cookies["jiejing_saas_refresh"]
        # Switching revokes the original family by design; create a fresh home session.
        status, home, cookies = self.request("/auth/login", credentials)
        self.assertEqual(status, 200)
        home_access, home_refresh = home["token"], cookies["jiejing_saas_refresh"]
        with closing(sqlite3.connect(self.db)) as connection:
            with connection:
                connection.execute("delete from team_members where company_id=? and user_id=?", (second_company, user_id))
        self.assertEqual(self.request("/auth/refresh", {}, refresh=second_refresh)[0], 401)
        self.assertEqual(self.request("/me", access=second_access)[0], 401)
        self.assertEqual(self.request("/me", access=home_access)[0], 200)
        self.assertEqual(self.request("/auth/refresh", {}, refresh=home_refresh)[0], 200)
        with closing(sqlite3.connect(self.db)) as connection:
            with connection:
                connection.execute("insert into team_members(company_id,user_id,role,created_at) values(?,?,?,?)",
                                   (second_company, user_id, "operator", "2026-10-14T00:00:00Z"))
        self.assertEqual(self.request("/me", access=second_access)[0], 401)
        self.assertEqual(self.request("/auth/refresh", {}, refresh=second_refresh)[0], 401)


if __name__ == "__main__":
    unittest.main()

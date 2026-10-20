#!/usr/bin/env python3
"""Behavior contract for rotating, backend-only browser refresh sessions."""

from __future__ import annotations

import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository
from jiejing_saas.api_server import SaaSBackendHandler
from jiejing_saas.security import SessionManager

OUT = ROOT / "output" / "jiejing-rotating-browser-sessions-test"


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    db_path = OUT / "saas.sqlite"
    try:
        repository = SaaSRepository(db_path, database_engine="sqlite", database_url="")
        account = repository.create_user_with_company(
            email="rotating-session@example.test",
            password="rotating-session-password",
            company_name="Rotating Session Contract",
        )
        user = account["user"]
        company = account["company"]

        inventory = repository.database_inventory()
        index_names = {
            str(item.get("index_name") or "")
            for item in inventory.get("indexes", [])
            if isinstance(item, dict)
        }
        if "idx_user_sessions_refresh_session" not in index_names:
            return fail("refresh-family access revocation must have a production index")

        if not issuance_failure_revokes_refresh_family():
            return fail("failed access-token persistence must revoke its newly-created refresh family")

        other_account = repository.create_user_with_company(
            email="rotating-session-other@example.test",
            password="rotating-session-other-password",
            company_name="Rotating Session Other Tenant",
        )
        try:
            repository.create_browser_refresh_session(
                user_id=user["user_id"],
                company_id=other_account["company"]["company_id"],
                device_class="chrome_windows",
                ttl_seconds=3600,
            )
        except ValueError as exc:
            if str(exc) != "session_refresh_invalid":
                return fail(f"wrong-tenant refresh issuance returned an unsafe error: {exc}")
        else:
            return fail("refresh issuance must require an exact user-company membership")

        issued = repository.create_browser_refresh_session(
            user_id=user["user_id"],
            company_id=company["company_id"],
            device_class="chrome_windows",
            ttl_seconds=3600,
        )
        first_token = str(issued.get("refresh_token") or "")
        public_session = issued.get("session") if isinstance(issued.get("session"), dict) else {}
        if len(first_token) < 32:
            return fail("refresh session must issue a high-entropy request-local token")
        if first_token in json.dumps(public_session, ensure_ascii=False):
            return fail("refresh token must not enter the public session summary")
        if first_token.encode("utf-8") in db_path.read_bytes():
            return fail("refresh token must not be stored raw in the database")

        rotated = repository.rotate_browser_refresh_session(refresh_token=first_token)
        second_token = str(rotated.get("refresh_token") or "")
        if len(second_token) < 32 or second_token == first_token:
            return fail("refresh must atomically issue a distinct next generation")

        try:
            repository.rotate_browser_refresh_session(refresh_token=first_token)
        except ValueError as exc:
            if str(exc) != "session_refresh_replay_blocked":
                return fail(f"old refresh replay returned the wrong fixed error: {exc}")
        else:
            return fail("old refresh replay must fail closed")

        sessions = repository.list_browser_sessions(
            user_id=user["user_id"],
            current_session_id=str(public_session.get("session_ref") or ""),
        )
        if sessions:
            return fail(f"refresh replay must revoke the full device session: {sessions}")
        try:
            repository.rotate_browser_refresh_session(refresh_token=second_token)
        except ValueError as exc:
            if str(exc) not in {"session_refresh_invalid", "session_refresh_replay_blocked"}:
                return fail(f"revoked next generation returned an unsafe error: {exc}")
        else:
            return fail("next refresh generation must be unusable after family replay revocation")

        database_text = db_path.read_bytes()
        for raw_token in (first_token, second_token):
            if raw_token.encode("utf-8") in database_text:
                return fail("no refresh token generation may be stored raw")

        concurrent = repository.create_browser_refresh_session(
            user_id=user["user_id"],
            company_id=company["company_id"],
            device_class="chrome_windows",
            ttl_seconds=3600,
        )
        concurrent_token = str(concurrent.get("refresh_token") or "")

        def rotate_once() -> str:
            try:
                repository.rotate_browser_refresh_session(refresh_token=concurrent_token)
                return "success"
            except ValueError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=4) as executor:
            outcomes = list(executor.map(lambda _index: rotate_once(), range(4)))
        if outcomes.count("success") != 1:
            return fail(f"concurrent refresh must have exactly one rotation winner: {outcomes}")
        if any(outcome not in {"success", "session_refresh_replay_blocked"} for outcome in outcomes):
            return fail(f"concurrent refresh losers must fail closed with fixed errors: {outcomes}")
        if repository.list_browser_sessions(
            user_id=user["user_id"],
            company_id=company["company_id"],
        ):
            return fail("concurrent reuse of one refresh generation must revoke that device family")

        atomic = repository.create_browser_refresh_session(
            user_id=user["user_id"],
            company_id=company["company_id"],
            device_class="chrome_windows",
            ttl_seconds=3600,
        )
        atomic_token = str(atomic.get("refresh_token") or "")
        refresh_identity = repository.browser_refresh_session_identity(refresh_token=atomic_token)
        session_ref = str((atomic.get("session") or {}).get("session_ref") or "")
        manager = SessionManager(secret="rotating-session-contract", ttl_seconds=60)
        access_token = manager.create_token(
            user_id=str(refresh_identity.get("user_id") or ""),
            company_id=str(refresh_identity.get("company_id") or ""),
            email=str(refresh_identity.get("email") or ""),
            refresh_session_id=session_ref,
        )
        access_identity = manager.verify_token(access_token)
        wrong_identity = {**access_identity, "company_id": "company_wrong"}
        try:
            repository.rotate_browser_refresh_session(
                refresh_token=atomic_token,
                access_identity=wrong_identity,
            )
        except ValueError as exc:
            if str(exc) != "session_refresh_invalid":
                return fail(f"wrong access binding returned unsafe error: {exc}")
        else:
            return fail("wrong access identity must not consume the refresh token")
        repository.rotate_browser_refresh_session(
            refresh_token=atomic_token,
            access_identity=access_identity,
        )
        persisted = repository.ensure_user_session(access_identity)
        if persisted.get("active") is not True:
            return fail("refresh rotation and its next access session must commit atomically")

        stale = repository.create_browser_refresh_session(
            user_id=user["user_id"],
            company_id=company["company_id"],
            device_class="chrome_windows",
            ttl_seconds=3600,
        )
        stale_ref = str((stale.get("session") or {}).get("session_ref") or "")
        with repository._connect() as conn:
            conn.execute("update user_refresh_sessions set expires_epoch = ? where session_id = ?", (int(time.time()) - 1, stale_ref))
            conn.execute("update user_refresh_token_history set expires_epoch = ? where session_id = ?", (int(time.time()) - 1, stale_ref))
        repository.create_browser_refresh_session(
            user_id=user["user_id"],
            company_id=company["company_id"],
            device_class="chrome_windows",
            ttl_seconds=3600,
        )
        with repository._connect() as conn:
            stale_session_count = int(conn.execute("select count(*) from user_refresh_sessions where session_id = ?", (stale_ref,)).fetchone()[0])
            stale_history_count = int(conn.execute("select count(*) from user_refresh_token_history where session_id = ?", (stale_ref,)).fetchone()[0])
        if stale_session_count or stale_history_count:
            return fail("expired refresh families must be bounded by lifecycle cleanup")
    except AttributeError:
        raise

    print("PASS jiejing_rotating_browser_sessions")
    return 0


def issuance_failure_revokes_refresh_family() -> bool:
    class FakeRepository:
        def __init__(self) -> None:
            self.revocations: list[dict[str, str]] = []

        def create_browser_refresh_session(self, **_kwargs):
            return {"session": {"session_ref": "session-orphan-guard"}, "refresh_token": "r" * 48,
                    "access_epochs": {"user_epoch": 0, "member_epoch": 0}}

        def revoke_browser_session(self, **kwargs):
            self.revocations.append({key: str(value) for key, value in kwargs.items()})
            return True

    class FakeHandler:
        def __init__(self) -> None:
            self.repository = FakeRepository()

        @staticmethod
        def _browser_device_class_from_request() -> str:
            return "chrome_windows"

        @staticmethod
        def _refresh_ttl_seconds() -> int:
            return 3600

        @staticmethod
        def _issue_session_token(**_kwargs) -> str:
            raise RuntimeError("sentinel access persistence failure")

    fake = FakeHandler()
    try:
        SaaSBackendHandler._issue_browser_session(
            fake,
            user_id="user-orphan-guard",
            company_id="company-orphan-guard",
            email="orphan@example.test",
        )
    except RuntimeError as exc:
        if str(exc) != "sentinel access persistence failure":
            raise
    else:
        return False
    return fake.repository.revocations == [{
        "user_id": "user-orphan-guard",
        "company_id": "company-orphan-guard",
        "session_id": "session-orphan-guard",
    }]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

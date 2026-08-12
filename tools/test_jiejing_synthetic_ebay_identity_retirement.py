#!/usr/bin/env python3
"""Contract for safely retiring synthetic eBay identity conflicts."""

from __future__ import annotations

import sys
import tempfile
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import SaaSRepository  # noqa: E402


IDENTITY_HASH = "a" * 64


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def add_ebay_connection(
    repo: SaaSRepository,
    *,
    email: str,
    company_name: str,
    store_name: str,
    stage: str,
) -> tuple[dict, dict, dict, dict]:
    account = repo.create_user_with_company(
        email=email,
        password="local-test-password",
        company_name=company_name,
    )
    user = account["user"]
    company = account["company"]
    store = repo.create_store(
        company_id=company["company_id"],
        user_id=user["user_id"],
        payload={
            "platform": "ebay",
            "store_name": store_name,
            "marketplace": "EBAY_US",
            "stage": stage,
        },
    )
    secret_ref = repo.create_secret_reference(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        provider="ebay",
        purpose="ebay_refresh_token",
        status="managed_vault_stored",
        metadata={
            "credential_owner": "jiejing_saas_backend",
            "secret_value_stored": False,
        },
    )
    connection = repo.create_platform_connection(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        payload={
            "platform": "ebay",
            "connection_type": "oauth",
            "status": "read_only_authorized",
            "secret_ref": secret_ref["secret_ref"],
            "scopes": ["https://api.ebay.com/oauth/api_scope/sell.account.readonly"],
            "metadata": {
                "identity_mapping_status": "identity_mapping_ready",
                "ebay_user_id_hash": IDENTITY_HASH,
            },
        },
    )
    return user, company, store, connection


def main() -> int:
    with tempfile.TemporaryDirectory(
        prefix="jiejing-synthetic-ebay-retirement-", ignore_cleanup_errors=True
    ) as temp_dir:
        db_path = Path(temp_dir) / "saas.sqlite"
        repo = SaaSRepository(db_path, database_engine="sqlite", database_url="")
        _, merchant_company, merchant_store, merchant_connection = add_ebay_connection(
            repo,
            email="real-merchant@gmail.com",
            company_name="Real Merchant",
            store_name="real-ebay-store",
            stage="newbie",
        )
        _, synthetic_company, synthetic_store, synthetic_connection = add_ebay_connection(
            repo,
            email="oauth-staging@jiejing.local",
            company_name="Synthetic OAuth Fixture",
            store_name="oauth-staging-store",
            stage="oauth_staging_validation",
        )

        before = repo.product_readiness_evidence()
        if before.get("duplicate_ebay_identity_store_count") != 1:
            return fail("fixture must begin with one duplicate eBay identity owner")

        ambiguous = repo.accept_ebay_account_deletion_event(
            event={
                "event_key": "b" * 64,
                "payload_sha256": "c" * 64,
                "notification_id_hash": "d" * 64,
                "topic": "MARKETPLACE_ACCOUNT_DELETION",
                "schema_version": "1.0",
                "user_id_hash": IDENTITY_HASH,
                "username_hash": "",
                "eias_identity_hash": "",
                "signature_present": True,
                "raw_payload_persisted": False,
                "raw_identity_persisted": False,
                "secret_exposed": False,
            }
        )
        if ambiguous.get("status") != "ambiguous_identity_review_required":
            return fail(f"cross-tenant identity deletion must be quarantined, got {ambiguous}")
        if ambiguous.get("candidate_owner_count") != 2 or ambiguous.get("job_id"):
            return fail("ambiguous deletion must expose only a value-free owner count and create no job")
        if any(ambiguous.get(key) for key in ("company_id", "store_id", "connection_id", "task_id")):
            return fail("ambiguous deletion must not select or expose one tenant owner")

        plan = repo.plan_synthetic_ebay_identity_conflict_retirement()
        expected = {
            "status": "eligible_synthetic_conflicts_found",
            "eligible_connection_count": 1,
            "eligible_secret_ref_count": 1,
            "merchant_owner_count": 1,
            "merchant_conflict_count": 0,
            "synthetic_owner_count": 1,
            "would_mutate": False,
            "secret_exposed": False,
        }
        for key, value in expected.items():
            if plan.get(key) != value:
                return fail(f"retirement plan {key} expected {value!r}, got {plan.get(key)!r}")
        cli_dry_run = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "jiejing_retire_synthetic_ebay_identity_conflicts.py"),
                "--db-path",
                str(db_path),
                "--database-engine",
                "sqlite",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if cli_dry_run.returncode != 0:
            return fail(f"operator CLI dry-run must pass: {cli_dry_run.stderr.strip()}")
        cli_plan = json.loads(cli_dry_run.stdout)
        if cli_plan.get("eligible_connection_count") != 1 or cli_plan.get("would_mutate") is not False:
            return fail("operator CLI must default to the same zero-write retirement plan")
        serialized = str(plan)
        for forbidden in (
            merchant_company["company_id"],
            merchant_store["store_id"],
            merchant_connection["connection_id"],
            synthetic_company["company_id"],
            synthetic_store["store_id"],
            synthetic_connection["connection_id"],
            IDENTITY_HASH,
        ):
            if forbidden in serialized:
                return fail("retirement plan must not expose tenant, store, connection, or identity values")

        try:
            repo.retire_synthetic_ebay_identity_conflicts(confirmation_phrase="WRONG")
        except ValueError as exc:
            if str(exc) != "synthetic_ebay_identity_retirement_confirmation_required":
                return fail(f"wrong phrase must return a fixed fail-closed error, got {exc}")
        else:
            return fail("wrong confirmation phrase must not be accepted")
        after_wrong_phrase = repo.product_readiness_evidence()
        if after_wrong_phrase.get("duplicate_ebay_identity_store_count") != 1:
            return fail("wrong confirmation phrase must perform zero writes")

        original_insert_audit = repo._insert_audit

        def fail_retirement_audit(*args, **kwargs):
            if kwargs.get("action_type") == "ebay.synthetic_identity_conflict.retired":
                raise RuntimeError("synthetic retirement audit fixture failure")
            return original_insert_audit(*args, **kwargs)

        repo._insert_audit = fail_retirement_audit  # type: ignore[method-assign]
        try:
            try:
                repo.retire_synthetic_ebay_identity_conflicts(
                    confirmation_phrase="RETIRE_SYNTHETIC_EBAY_IDENTITY_CONFLICTS"
                )
            except RuntimeError:
                pass
            else:
                return fail("audit persistence failure must abort synthetic retirement")
        finally:
            repo._insert_audit = original_insert_audit  # type: ignore[method-assign]
        after_rollback = repo.product_readiness_evidence()
        if after_rollback.get("duplicate_ebay_identity_store_count") != 1:
            return fail("retirement connection update must roll back with its audit")
        if after_rollback.get("ebay_secret_refs") != 2:
            return fail("retirement secret reference update must roll back with its audit")

        applied = repo.retire_synthetic_ebay_identity_conflicts(
            confirmation_phrase="RETIRE_SYNTHETIC_EBAY_IDENTITY_CONFLICTS"
        )
        for key, value in {
            "status": "synthetic_ebay_identity_conflicts_retired",
            "retired_connection_count": 1,
            "revoked_secret_ref_count": 1,
            "merchant_owner_count": 1,
            "merchant_conflict_count": 0,
            "synthetic_owner_count": 1,
            "data_mutated": True,
            "secret_exposed": False,
        }.items():
            if applied.get(key) != value:
                return fail(f"retirement result {key} expected {value!r}, got {applied.get(key)!r}")
        if any(forbidden in str(applied) for forbidden in (
            merchant_company["company_id"], synthetic_company["company_id"], IDENTITY_HASH
        )):
            return fail("retirement result must remain value-free")

        merchant_after = repo.list_connections(
            company_id=merchant_company["company_id"], store_id=merchant_store["store_id"]
        )[0]
        synthetic_after = repo.list_connections(
            company_id=synthetic_company["company_id"], store_id=synthetic_store["store_id"]
        )[0]
        synthetic_refs = repo.list_secret_refs(
            company_id=synthetic_company["company_id"], store_id=synthetic_store["store_id"]
        )
        if merchant_after.get("status") != "read_only_authorized" or not merchant_after.get("scopes"):
            return fail("merchant connection and read-only scopes must remain active")
        if synthetic_after.get("status") != "retired_synthetic_test" or synthetic_after.get("scopes"):
            return fail("synthetic connection must be retired with scopes cleared")
        if (synthetic_after.get("metadata") or {}).get("identity_mapping_status"):
            return fail("retired synthetic public metadata must not claim an active identity mapping")
        if not synthetic_refs or synthetic_refs[0].get("status") != "revoked_synthetic_test":
            return fail("synthetic refresh credential reference must be revoked")

        after = repo.product_readiness_evidence()
        if after.get("active_ebay_identity_connections") != 1:
            return fail("only the merchant eBay identity connection should remain active")
        if after.get("mapped_ebay_identity_connections") != 1:
            return fail("merchant immutable identity mapping must remain intact")
        if after.get("duplicate_ebay_identity_store_count") != 0:
            return fail("synthetic retirement must close the duplicate identity warning")
        if after.get("ebay_secret_refs") != 1:
            return fail("only the merchant eBay refresh secret reference should remain active")

        merchant_only_deletion = repo.accept_ebay_account_deletion_event(
            event={
                "event_key": "e" * 64,
                "payload_sha256": "f" * 64,
                "notification_id_hash": "1" * 64,
                "topic": "MARKETPLACE_ACCOUNT_DELETION",
                "schema_version": "1.0",
                "user_id_hash": IDENTITY_HASH,
                "username_hash": "",
                "eias_identity_hash": "",
                "signature_present": True,
                "raw_payload_persisted": False,
                "raw_identity_persisted": False,
                "secret_exposed": False,
            }
        )
        if merchant_only_deletion.get("status") != "queued":
            return fail("retired synthetic selectors must not keep future deletion intake ambiguous")
        if merchant_only_deletion.get("company_id") != merchant_company["company_id"]:
            return fail("post-retirement deletion intake must select the remaining merchant owner")

        repeated = repo.retire_synthetic_ebay_identity_conflicts(
            confirmation_phrase="RETIRE_SYNTHETIC_EBAY_IDENTITY_CONFLICTS"
        )
        if repeated.get("status") != "no_eligible_synthetic_conflicts" or repeated.get("data_mutated") is not False:
            return fail("retirement operation must be idempotent")

        conflict_repo = SaaSRepository(
            Path(temp_dir) / "merchant-conflict.sqlite", database_engine="sqlite", database_url=""
        )
        add_ebay_connection(
            conflict_repo,
            email="merchant-one@gmail.com",
            company_name="Merchant One",
            store_name="merchant-one",
            stage="newbie",
        )
        add_ebay_connection(
            conflict_repo,
            email="merchant-two@outlook.com",
            company_name="Merchant Two",
            store_name="merchant-two",
            stage="newbie",
        )
        add_ebay_connection(
            conflict_repo,
            email="oauth-conflict@local.invalid",
            company_name="Synthetic Conflict Fixture",
            store_name="synthetic-conflict",
            stage="oauth_staging_validation",
        )
        conflict_plan = conflict_repo.plan_synthetic_ebay_identity_conflict_retirement()
        if conflict_plan.get("eligible_connection_count") != 0:
            return fail("two merchant owners for one identity must block automatic synthetic retirement")
        if conflict_plan.get("merchant_conflict_count") != 1:
            return fail("merchant owner ambiguity must remain visible as a value-free conflict count")

        unsafe_repo = SaaSRepository(
            Path(temp_dir) / "unsafe-synthetic.sqlite", database_engine="sqlite", database_url=""
        )
        add_ebay_connection(
            unsafe_repo,
            email="safe-merchant@gmail.com",
            company_name="Safe Merchant",
            store_name="safe-merchant",
            stage="newbie",
        )
        add_ebay_connection(
            unsafe_repo,
            email="wrong-stage@jiejing.local",
            company_name="Wrong Stage Fixture",
            store_name="wrong-stage",
            stage="newbie",
        )
        if unsafe_repo.plan_synthetic_ebay_identity_conflict_retirement().get("eligible_connection_count") != 0:
            return fail("synthetic account outside the exact OAuth staging stage must not be eligible")
        inactive_repo = SaaSRepository(
            Path(temp_dir) / "inactive-secret.sqlite", database_engine="sqlite", database_url=""
        )
        add_ebay_connection(
            inactive_repo,
            email="active-merchant@gmail.com",
            company_name="Active Merchant",
            store_name="active-merchant",
            stage="newbie",
        )
        inactive_user, inactive_company, inactive_store, _ = add_ebay_connection(
            inactive_repo,
            email="inactive-secret@jiejing.local",
            company_name="Inactive Secret Fixture",
            store_name="inactive-secret",
            stage="oauth_staging_validation",
        )
        inactive_repo.update_secret_reference_status(
            company_id=inactive_company["company_id"],
            store_id=inactive_store["store_id"],
            secret_ref=inactive_repo.list_secret_refs(
                company_id=inactive_company["company_id"],
                store_id=inactive_store["store_id"],
            )[0]["secret_ref"],
            status="revoked_manual_review",
            metadata_patch={"secret_exposed": False},
            user_id=inactive_user["user_id"],
        )
        if inactive_repo.plan_synthetic_ebay_identity_conflict_retirement().get("eligible_connection_count") != 0:
            return fail("synthetic connection without an active refresh secret reference must not be eligible")

    print("PASS jiejing_synthetic_ebay_identity_retirement")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

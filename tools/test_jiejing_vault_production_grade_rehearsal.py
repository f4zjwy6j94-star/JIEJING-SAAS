#!/usr/bin/env python3
"""Public-contract test for the production-grade E/F Vault rehearsal."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.jiejing_vault_production_grade_rehearsal import (  # noqa: E402
    RehearsalBlocked,
    execute_production_grade_rehearsal,
    parse_signed_checksum_manifest,
    gpg_validsig_matches_hashicorp_release,
    pgp_packet_report_is_rsa_encryption_capable,
)


SECRET_CANARY = "vault-rehearsal-secret-canary-never-print"


class SuccessfulRehearsalBackend:
    def execute(self) -> dict[str, object]:
        return {
            "source_drive": "E",
            "restore_drive": "F",
            "source_filesystem": "NTFS",
            "restore_filesystem": "NTFS",
            "source_disk_number": 0,
            "restore_disk_number": 0,
            "source_acl_verified": True,
            "restore_acl_verified": True,
            "vault_version": "1.21.4",
            "vault_archive_sha256": "a" * 64,
            "vault_checksum_signature_verified": True,
            "vault_archive_checksum_verified": True,
            "vault_source_host": "releases.hashicorp.com",
            "listener_loopback_only": True,
            "key_shares": 3,
            "key_threshold": 2,
            "simulated_custody_unit_count": 3,
            "max_shares_per_simulated_unit": 1,
            "pgp_encrypted_shares": True,
            "pgp_encrypted_root_token": True,
            "single_share_remains_sealed": True,
            "two_share_unseal_verified": True,
            "production_policy_sha256": "b" * 64,
            "periodic_token_renewable": True,
            "periodic_token_positive_period": True,
            "periodic_token_renew_self_verified": True,
            "initial_root_token_revoked": True,
            "vault_stopped_before_backup": True,
            "encrypted_backup_verified": True,
            "encrypted_backup_sha256": "c" * 64,
            "fresh_restore_verified": True,
            "restored_single_share_remains_sealed": True,
            "restored_two_share_unseal_verified": True,
            "restored_periodic_token_renewed": True,
            "sentinel_reference_sha256": "d" * 64,
            "sentinel_payload_sha256": "e" * 64,
            "sentinel_resolved_after_restore": True,
            "sentinel_digest_match": True,
            "secret_scan_passed": True,
            "cleanup_verified": True,
            "public_health_unchanged": True,
            # A backend bug must not make an unrecognized secret-bearing field
            # durable in the public evidence object.
            "sentinel": SECRET_CANARY,
        }


class StaticFailureBackend:
    def execute(self) -> dict[str, object]:
        raise RehearsalBlocked("vault_checksum_signature_invalid")


class SecretBearingFailureBackend:
    def execute(self) -> dict[str, object]:
        raise RehearsalBlocked(SECRET_CANARY)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    selected_checksum = parse_signed_checksum_manifest(
        "0" * 64 + "  vault_1.21.4_linux_amd64.zip\n"
        + "1" * 64
        + "  vault_1.21.4_windows_amd64.zip\n",
        expected_filename="vault_1.21.4_windows_amd64.zip",
    )
    if selected_checksum != "1" * 64:
        return fail(f"official checksum selection is not exact: {selected_checksum!r}")
    duplicate_manifest = (
        "1" * 64
        + "  vault_1.21.4_windows_amd64.zip\n"
        + "2" * 64
        + "  vault_1.21.4_windows_amd64.zip\n"
    )
    try:
        parse_signed_checksum_manifest(
            duplicate_manifest,
            expected_filename="vault_1.21.4_windows_amd64.zip",
        )
    except ValueError:
        pass
    else:
        return fail("duplicate signed checksum entries did not fail closed")
    if pgp_packet_report_is_rsa_encryption_capable(
        ":public key packet:\n\tversion 4, algo 22\n:public sub key packet:\n\tversion 4, algo 18\n"
    ):
        return fail("Curve25519 rehearsal key was accepted by the Vault RSA compatibility gate")
    if not pgp_packet_report_is_rsa_encryption_capable(
        ":public key packet:\n\tversion 4, algo 1\n:public sub key packet:\n\tversion 4, algo 1\n"
    ):
        return fail("RSA primary plus encryption subkey was rejected")
    valid_status = (
        "[GNUPG:] VALIDSIG 374EC75B485913604A831CC7C820C6D5CD27AB87 "
        "2026-03-05 1772677935 0 4 0 1 8 00 C874011F0AB405110D02105534365D9472D7468F\n"
    )
    if not gpg_validsig_matches_hashicorp_release(valid_status):
        return fail("exact HashiCorp release-signing fingerprint was rejected")
    if gpg_validsig_matches_hashicorp_release(valid_status.replace("C820C6D5", "00000000")):
        return fail("wrong release-signing fingerprint was accepted")

    result = execute_production_grade_rehearsal(backend=SuccessfulRehearsalBackend())
    serialized = json.dumps(result, sort_keys=True)

    if result.get("status") != "verified":
        return fail(f"valid production-grade rehearsal was not verified: {result}")
    if result.get("mode") != "non_production_production_grade_rehearsal":
        return fail(f"rehearsal mode is not explicit: {result}")
    if result.get("discovered_physical_disk_count") != 1:
        return fail(f"E/F same-disk fact was not preserved: {result}")
    for field in (
        "production_readiness_credited",
        "production_custody_credited",
        "real_platform_writes_enabled",
        "public_charging_allowed",
        "secret_exposed",
    ):
        if result.get(field) is not False:
            return fail(f"unsafe rehearsal evidence field {field}: {result.get(field)!r}")
    if SECRET_CANARY in serialized or "sentinel\"" in serialized:
        return fail("value-free evidence exposed an unrecognized secret-bearing field")

    failed = execute_production_grade_rehearsal(backend=StaticFailureBackend())
    if failed.get("blockers") != ["vault_checksum_signature_invalid"]:
        return fail(f"allowlisted host failure code was hidden: {failed}")

    secret_failure = execute_production_grade_rehearsal(backend=SecretBearingFailureBackend())
    secret_failure_json = json.dumps(secret_failure, sort_keys=True)
    if secret_failure.get("blockers") != ["rehearsal_execution_failed"]:
        return fail(f"unrecognized backend failure was not normalized: {secret_failure}")
    if SECRET_CANARY in secret_failure_json:
        return fail("secret-bearing backend failure escaped into public evidence")

    print("PASS jiejing_vault_production_grade_rehearsal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

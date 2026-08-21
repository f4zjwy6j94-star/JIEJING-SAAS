#!/usr/bin/env python3
"""Fail-closed, value-free contract for the E/F Vault recovery rehearsal."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

try:
    from tools.jiejing_vault_recovery_drill import EncryptedOffHostArchive, WindowsDpapiKeyProtector
except ModuleNotFoundError:  # Direct `python tools/...py` execution.
    from jiejing_vault_recovery_drill import EncryptedOffHostArchive, WindowsDpapiKeyProtector


CONTRACT_VERSION = "jiejing_vault_production_grade_rehearsal_v1"
MODE = "non_production_production_grade_rehearsal"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
CHECKSUM_LINE_PATTERN = re.compile(r"([0-9a-f]{64})[ \t]+[*]?([^\r\n]+)\Z")
VAULT_VERSION = "1.21.4"
VAULT_ARCHIVE_NAME = f"vault_{VAULT_VERSION}_windows_amd64.zip"
VAULT_RELEASE_BASE = f"https://releases.hashicorp.com/vault/{VAULT_VERSION}"
PGP_CREATION_SKEW_SECONDS = 300
HASHICORP_PUBLIC_KEY_URL = "https://www.hashicorp.com/.well-known/pgp-key.txt"
HASHICORP_PRIMARY_FINGERPRINT = "C874011F0AB405110D02105534365D9472D7468F"
HASHICORP_RELEASE_SIGNING_FINGERPRINT = "374EC75B485913604A831CC7C820C6D5CD27AB87"
ALLOWED_DOWNLOAD_HOSTS = frozenset({"releases.hashicorp.com", "www.hashicorp.com"})
PUBLIC_BASE_URL = "https://app.jiejing.shop"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36"
REHEARSAL_POLICY_NAME = "jiejing-production-rehearsal"
FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "unseal_key",
        "unseal_keys",
        "root_token",
        "backend_token",
        "vault_token",
        "backup_key",
        "sentinel",
        "secret_value",
    }
)
HOST_BLOCKER_CODES = frozenset(
    {
        "approved_ef_roots_required",
        "approved_same_disk_mapping_changed",
        "backend_token_allowed_capabilities_invalid",
        "backend_token_scope_too_broad",
        "backup_archive_empty",
        "backup_archive_invalid",
        "backup_archive_member_invalid",
        "cleanup_or_secret_scan_failed",
        "cleanup_path_outside_rehearsal_roots",
        "cleanup_root_delete_forbidden",
        "current_windows_sid_unavailable",
        "download_redirect_not_allowlisted",
        "download_source_not_allowlisted",
        "encrypted_backup_contract_invalid",
        "fresh_restore_paths_not_empty",
        "fresh_restore_storage_missing",
        "fresh_vault_state_invalid",
        "hashicorp_signing_key_import_failed",
        "live_vault_process_missing",
        "official_download_empty",
        "official_download_failed",
        "periodic_backend_token_contract_invalid",
        "periodic_backend_token_missing",
        "pgp_ciphertext_invalid",
        "pgp_decryption_failed",
        "pgp_identity_invalid",
        "pgp_plaintext_invalid",
        "pgp_public_key_mapping_invalid",
        "pgp_unit_mapping_invalid",
        "physical_disk_not_healthy",
        "powershell_preflight_failed",
        "powershell_preflight_output_invalid",
        "public_evidence_not_value_free",
        "public_health_changed",
        "public_health_contract_invalid",
        "public_health_http_invalid",
        "public_health_probe_failed",
        "rehearsal_acl_apply_failed",
        "rehearsal_acl_verification_failed",
        "rehearsal_did_not_complete",
        "rehearsal_pgp_key_generation_failed",
        "rehearsal_pgp_key_generation_failed_a",
        "rehearsal_pgp_key_generation_failed_b",
        "rehearsal_pgp_key_generation_failed_c",
        "rehearsal_pgp_key_generation_failed_root",
        "rehearsal_pgp_agent_reset_failed",
        "rehearsal_pgp_algorithm_invalid",
        "rehearsal_pgp_public_export_failed",
        "rehearsal_pgp_public_key_invalid",
        "rehearsal_roots_must_not_preexist",
        "restore_secret_handles_missing",
        "restored_sentinel_digest_mismatch",
        "restored_unseal_threshold_not_proven",
        "restored_vault_initial_state_invalid",
        "sentinel_initial_read_mismatch",
        "sentinel_resolve_invalid",
        "vault_address_not_loopback",
        "vault_archive_checksum_invalid",
        "vault_archive_members_invalid",
        "vault_checksum_signature_invalid",
        "vault_checksum_signature_fingerprint_invalid",
        "vault_executable_missing",
        "vault_loopback_json_invalid",
        "vault_loopback_request_failed",
        "vault_loopback_response_unexpected",
        "vault_unseal_response_unexpected",
        "vault_mount_enable_failed",
        "vault_policy_install_failed",
        "periodic_backend_token_create_failed",
        "periodic_backend_token_lookup_failed",
        "periodic_backend_token_renew_failed",
        "backend_token_capability_probe_failed",
        "sentinel_write_failed",
        "sentinel_read_failed",
        "initial_root_token_revoke_failed",
        "initial_root_token_revoke_verification_failed",
        "vault_not_stopped_before_backup",
        "vault_operator_init_failed",
        "vault_operator_init_geometry_invalid",
        "vault_operator_init_output_invalid",
        "vault_plaintext_snapshot_invalid",
        "vault_start_timeout",
        "vault_unseal_threshold_not_proven",
        "vault_version_mismatch",
        "vault_version_probe_failed",
        "volume_discovery_invalid",
        "volume_filesystem_or_health_invalid",
        "windows_host_required",
        "wsl_gpg_unavailable",
        "wsl_path_outside_approved_volumes",
        "environment_preflight_unexpected",
        "software_verification_unexpected",
        "pgp_identity_unexpected",
        "initial_vault_start_unexpected",
        "initial_vault_init_unexpected",
        "initial_vault_unseal_unexpected",
        "vault_policy_setup_unexpected",
        "periodic_token_setup_unexpected",
        "sentinel_lifecycle_unexpected",
        "root_revocation_unexpected",
        "backup_encryption_unexpected",
        "backup_stop_unexpected",
        "backup_snapshot_unexpected",
        "backup_archive_encrypt_unexpected",
        "fresh_restore_unexpected",
        "public_health_after_unexpected",
    }
)


class ProductionGradeRehearsalBackend(Protocol):
    def execute(self) -> dict[str, object]: ...


def parse_signed_checksum_manifest(manifest: str, *, expected_filename: str) -> str:
    """Select one exact archive digest from an already signature-verified manifest."""

    matches: list[str] = []
    for raw_line in manifest.splitlines():
        match = CHECKSUM_LINE_PATTERN.fullmatch(raw_line.strip())
        if match and match.group(2) == expected_filename:
            matches.append(match.group(1))
    if len(matches) != 1:
        raise ValueError("signed checksum manifest must contain one exact archive entry")
    return matches[0]


def pgp_packet_report_is_rsa_encryption_capable(packet_report: str) -> bool:
    """Require an RSA primary key and RSA encryption subkey for Vault PGP init."""

    algorithms = re.findall(r"\balgo\s+([0-9]+)\b", packet_report)
    return len(algorithms) >= 2 and algorithms[0] == "1" and algorithms[1] == "1"


def gpg_validsig_matches_hashicorp_release(status_output: str) -> bool:
    """Pin the signature and primary fingerprints published by HashiCorp."""

    for line in status_output.splitlines():
        parts = line.strip().split()
        if len(parts) >= 12 and parts[0:2] == ["[GNUPG:]", "VALIDSIG"]:
            return (
                parts[2] == HASHICORP_RELEASE_SIGNING_FINGERPRINT
                and parts[-1] == HASHICORP_PRIMARY_FINGERPRINT
            )
    return False


_PUBLIC_FIELDS = (
    "source_drive",
    "restore_drive",
    "source_filesystem",
    "restore_filesystem",
    "source_disk_number",
    "restore_disk_number",
    "source_acl_verified",
    "restore_acl_verified",
    "vault_version",
    "vault_archive_sha256",
    "vault_checksum_signature_verified",
    "vault_archive_checksum_verified",
    "vault_source_host",
    "listener_loopback_only",
    "key_shares",
    "key_threshold",
    "simulated_custody_unit_count",
    "max_shares_per_simulated_unit",
    "pgp_encrypted_shares",
    "pgp_encrypted_root_token",
    "single_share_remains_sealed",
    "two_share_unseal_verified",
    "production_policy_sha256",
    "periodic_token_renewable",
    "periodic_token_positive_period",
    "periodic_token_renew_self_verified",
    "initial_root_token_revoked",
    "vault_stopped_before_backup",
    "encrypted_backup_verified",
    "encrypted_backup_sha256",
    "fresh_restore_verified",
    "restored_single_share_remains_sealed",
    "restored_two_share_unseal_verified",
    "restored_periodic_token_renewed",
    "sentinel_reference_sha256",
    "sentinel_payload_sha256",
    "sentinel_resolved_after_restore",
    "sentinel_digest_match",
    "secret_scan_passed",
    "cleanup_verified",
    "public_health_unchanged",
)

_REQUIRED_TRUE_FIELDS = (
    "source_acl_verified",
    "restore_acl_verified",
    "vault_checksum_signature_verified",
    "vault_archive_checksum_verified",
    "listener_loopback_only",
    "pgp_encrypted_shares",
    "pgp_encrypted_root_token",
    "single_share_remains_sealed",
    "two_share_unseal_verified",
    "periodic_token_renewable",
    "periodic_token_positive_period",
    "periodic_token_renew_self_verified",
    "initial_root_token_revoked",
    "vault_stopped_before_backup",
    "encrypted_backup_verified",
    "fresh_restore_verified",
    "restored_single_share_remains_sealed",
    "restored_two_share_unseal_verified",
    "restored_periodic_token_renewed",
    "sentinel_resolved_after_restore",
    "sentinel_digest_match",
    "secret_scan_passed",
    "cleanup_verified",
    "public_health_unchanged",
)

_SHA256_FIELDS = (
    "vault_archive_sha256",
    "production_policy_sha256",
    "encrypted_backup_sha256",
    "sentinel_reference_sha256",
    "sentinel_payload_sha256",
)


def execute_production_grade_rehearsal(*, backend: ProductionGradeRehearsalBackend) -> dict[str, object]:
    """Execute a backend and return only allowlisted, non-production evidence."""

    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        raw = backend.execute()
        if not isinstance(raw, dict):
            return _blocked("invalid_backend_result")
        evidence = {field: raw.get(field) for field in _PUBLIC_FIELDS}
        blocker = _validate_evidence(evidence)
        if blocker:
            return _blocked(blocker)
    except RehearsalBlocked as exc:
        blocker = str(exc)
        return _blocked(blocker if blocker in HOST_BLOCKER_CODES else "rehearsal_execution_failed")
    except Exception:
        return _blocked("rehearsal_execution_failed")

    disk_numbers = {evidence["source_disk_number"], evidence["restore_disk_number"]}
    return {
        "status": "verified",
        "contract_version": CONTRACT_VERSION,
        "mode": MODE,
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **evidence,
        "discovered_physical_disk_count": len(disk_numbers),
        "same_physical_disk": len(disk_numbers) == 1,
        "production_readiness_credited": False,
        "production_custody_credited": False,
        "real_platform_writes_enabled": False,
        "public_charging_allowed": False,
        "blockers": ["production_offline_custody_units_not_available"],
        "secret_exposed": False,
    }


def _validate_evidence(evidence: dict[str, object]) -> str | None:
    if evidence.get("source_drive") != "E" or evidence.get("restore_drive") != "F":
        return "approved_volume_mapping_not_met"
    if evidence.get("source_filesystem") != "NTFS" or evidence.get("restore_filesystem") != "NTFS":
        return "approved_filesystem_not_met"
    if type(evidence.get("source_disk_number")) is not int or type(evidence.get("restore_disk_number")) is not int:
        return "physical_disk_mapping_invalid"
    if evidence.get("source_disk_number") != evidence.get("restore_disk_number"):
        return "approved_same_disk_rehearsal_mapping_changed"
    if evidence.get("vault_version") != "1.21.4":
        return "vault_version_mismatch"
    if evidence.get("vault_source_host") != "releases.hashicorp.com":
        return "vault_source_host_invalid"
    if evidence.get("key_shares") != 3 or evidence.get("key_threshold") != 2:
        return "shamir_geometry_invalid"
    if evidence.get("simulated_custody_unit_count") != 3 or evidence.get("max_shares_per_simulated_unit") != 1:
        return "simulated_custody_geometry_invalid"
    for field in _REQUIRED_TRUE_FIELDS:
        if evidence.get(field) is not True:
            return f"{field}_not_verified"
    for field in _SHA256_FIELDS:
        value = evidence.get(field)
        if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
            return f"{field}_invalid"
    return None


def _blocked(reason: str) -> dict[str, object]:
    return {
        "status": "blocked",
        "contract_version": CONTRACT_VERSION,
        "mode": MODE,
        "blockers": [reason],
        "production_readiness_credited": False,
        "production_custody_credited": False,
        "real_platform_writes_enabled": False,
        "public_charging_allowed": False,
        "secret_exposed": False,
    }


class RehearsalBlocked(RuntimeError):
    """A static, value-free failure code for the host rehearsal."""


@dataclass
class _VaultProcess:
    process: subprocess.Popen[bytes]
    log_handle: object
    address: str
    port: int


class WindowsEfVaultRehearsalBackend:
    """Run the approved disposable Vault ceremony on E and F only."""

    def __init__(self, *, source_root: Path, restore_root: Path, policy_file: Path) -> None:
        self.source_root = source_root.resolve()
        self.restore_root = restore_root.resolve()
        self.policy_file = policy_file.resolve()
        self.software_dir = self.source_root / "software"
        self.config_dir = self.source_root / "config"
        self.live_data_dir = self.source_root / "live-data"
        self.original_retired_dir = self.source_root / "original-retired"
        self.backup_staging_dir = self.source_root / "backup-staging"
        self.unit_a_dir = self.source_root / "simulated-unit-A"
        self.unit_c_dir = self.source_root / "simulated-unit-C"
        self.root_unit_dir = self.source_root / "simulated-root-operator"
        self.encrypted_backup_dir = self.restore_root / "encrypted-backup"
        self.isolated_restore_dir = self.restore_root / "isolated-restore"
        self.unit_b_dir = self.restore_root / "simulated-unit-B"
        self.backup_key_dir = self.restore_root / "simulated-backup-key-unit"
        self.evidence_dir = self.restore_root / "evidence"
        self._vault_processes: list[_VaultProcess] = []
        self._secret_canaries: list[str] = []
        self._sensitive_paths: set[Path] = set()
        self._public_key_paths: list[Path] = []
        self._roots_created = False
        self._phase_failure_code = "environment_preflight_unexpected"

    def execute(self) -> dict[str, object]:
        public_before = self._public_health_projection()
        raw: dict[str, object] | None = None
        try:
            self._phase_failure_code = "environment_preflight_unexpected"
            volume = self._prepare_secure_environment()
            self._phase_failure_code = "software_verification_unexpected"
            software = self._download_and_verify_vault()
            self._phase_failure_code = "pgp_identity_unexpected"
            pgp = self._create_disposable_pgp_identities()
            self._phase_failure_code = "initial_vault_start_unexpected"
            lifecycle = self._run_initial_vault_lifecycle(pgp)
            self._phase_failure_code = "backup_encryption_unexpected"
            recovery = self._backup_and_restore(lifecycle, pgp)
            self._phase_failure_code = "public_health_after_unexpected"
            public_after = self._public_health_projection()
            if public_after != public_before:
                raise RehearsalBlocked("public_health_changed")
            raw = {
                **volume,
                **software,
                **lifecycle["public_evidence"],
                **recovery,
                "public_health_unchanged": True,
            }
        except RehearsalBlocked:
            raise
        except Exception as exc:
            raise RehearsalBlocked(self._phase_failure_code) from exc
        finally:
            self._stop_all_vault_processes()
            self._cleanup_sensitive_material()

        if raw is None:
            raise RehearsalBlocked("rehearsal_did_not_complete")
        raw["cleanup_verified"] = self._cleanup_verified()
        raw["secret_scan_passed"] = self._scan_retained_files_for_secrets()
        if raw["cleanup_verified"] is not True or raw["secret_scan_passed"] is not True:
            raise RehearsalBlocked("cleanup_or_secret_scan_failed")
        return raw

    def _prepare_secure_environment(self) -> dict[str, object]:
        if os.name != "nt":
            raise RehearsalBlocked("windows_host_required")
        if self.source_root.drive.upper() != "E:" or self.restore_root.drive.upper() != "F:":
            raise RehearsalBlocked("approved_ef_roots_required")
        if self.source_root.exists() or self.restore_root.exists():
            raise RehearsalBlocked("rehearsal_roots_must_not_preexist")

        discovery_script = """
$ErrorActionPreference = 'Stop'
$volumes = @{}
foreach ($letter in @('E','F')) {
  $volume = Get-Volume -DriveLetter $letter
  $partition = Get-Partition -DriveLetter $letter
  $disk = Get-Disk -Number $partition.DiskNumber
  $volumes[$letter] = [ordered]@{
    filesystem = [string]$volume.FileSystem
    health = [string]$volume.HealthStatus
    disk_number = [int]$partition.DiskNumber
    partition_number = [int]$partition.PartitionNumber
    disk_health = [string]$disk.HealthStatus
    disk_operational = [string]$disk.OperationalStatus
  }
}
$volumes | ConvertTo-Json -Compress
"""
        discovered = self._powershell_json(discovery_script)
        for drive in ("E", "F"):
            item = discovered.get(drive) if isinstance(discovered, dict) else None
            if not isinstance(item, dict):
                raise RehearsalBlocked("volume_discovery_invalid")
            if item.get("filesystem") != "NTFS" or item.get("health") != "Healthy":
                raise RehearsalBlocked("volume_filesystem_or_health_invalid")
            if item.get("disk_health") != "Healthy" or "Online" not in str(item.get("disk_operational") or ""):
                raise RehearsalBlocked("physical_disk_not_healthy")
        if discovered["E"].get("disk_number") != discovered["F"].get("disk_number"):
            raise RehearsalBlocked("approved_same_disk_mapping_changed")

        self.source_root.mkdir(parents=False, exist_ok=False)
        self.restore_root.mkdir(parents=False, exist_ok=False)
        self._roots_created = True
        current_sid = self._current_windows_sid()
        for root in (self.source_root, self.restore_root):
            self._apply_owner_only_acl(root, current_sid=current_sid)

        for directory in (
            self.software_dir,
            self.config_dir,
            self.live_data_dir,
            self.backup_staging_dir,
            self.unit_a_dir,
            self.unit_c_dir,
            self.root_unit_dir,
            self.encrypted_backup_dir,
            self.unit_b_dir,
            self.backup_key_dir,
            self.evidence_dir,
        ):
            directory.mkdir(parents=True, exist_ok=False)
        for unit in (self.unit_a_dir, self.unit_b_dir, self.unit_c_dir, self.root_unit_dir, self.backup_key_dir):
            (unit / "NON_PRODUCTION_REHEARSAL_ONLY").write_text(
                "Disposable rehearsal material only. Never promote this unit to production.\n",
                encoding="utf-8",
            )

        source_acl = self._verify_acl_tree(self.source_root, current_sid=current_sid)
        restore_acl = self._verify_acl_tree(self.restore_root, current_sid=current_sid)
        if not source_acl or not restore_acl:
            raise RehearsalBlocked("rehearsal_acl_verification_failed")
        return {
            "source_drive": "E",
            "restore_drive": "F",
            "source_filesystem": "NTFS",
            "restore_filesystem": "NTFS",
            "source_disk_number": int(discovered["E"]["disk_number"]),
            "restore_disk_number": int(discovered["F"]["disk_number"]),
            "source_acl_verified": True,
            "restore_acl_verified": True,
        }

    @staticmethod
    def _current_windows_sid() -> str:
        script = "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value"
        completed = subprocess.run(
            [WindowsEfVaultRehearsalBackend._powershell_executable(), "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        value = completed.stdout.strip()
        if completed.returncode != 0 or not value.startswith("S-1-"):
            raise RehearsalBlocked("current_windows_sid_unavailable")
        return value

    @staticmethod
    def _apply_owner_only_acl(path: Path, *, current_sid: str) -> None:
        completed = subprocess.run(
            [
                "icacls.exe",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"*{current_sid}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
                "*S-1-5-32-544:(OI)(CI)F",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RehearsalBlocked("rehearsal_acl_apply_failed")

    def _verify_acl_tree(self, root: Path, *, current_sid: str) -> bool:
        quoted = str(root).replace("'", "''")
        script = f"""
$ErrorActionPreference = 'Stop'
$allowed = @('{current_sid}','S-1-5-18','S-1-5-32-544')
$paths = @((Get-Item -LiteralPath '{quoted}')) + @(Get-ChildItem -Force -Recurse -LiteralPath '{quoted}')
$ok = $true
foreach ($item in $paths) {{
  $acl = Get-Acl -LiteralPath $item.FullName
  foreach ($ace in $acl.Access) {{
    $sid = $ace.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    if ($allowed -notcontains $sid -or [string]$ace.AccessControlType -ne 'Allow') {{ $ok = $false }}
  }}
}}
[ordered]@{{ verified = $ok }} | ConvertTo-Json -Compress
"""
        result = self._powershell_json(script)
        return isinstance(result, dict) and result.get("verified") is True

    @staticmethod
    def _powershell_json(script: str) -> object:
        completed = subprocess.run(
            [WindowsEfVaultRehearsalBackend._powershell_executable(), "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RehearsalBlocked("powershell_preflight_failed")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RehearsalBlocked("powershell_preflight_output_invalid") from exc

    @staticmethod
    def _powershell_executable() -> str:
        return shutil.which("pwsh.exe") or shutil.which("powershell.exe") or "powershell.exe"

    def _download_and_verify_vault(self) -> dict[str, object]:
        archive_path = self.software_dir / VAULT_ARCHIVE_NAME
        sums_path = self.software_dir / f"vault_{VAULT_VERSION}_SHA256SUMS"
        signature_path = self.software_dir / f"vault_{VAULT_VERSION}_SHA256SUMS.sig"
        public_key_path = self.software_dir / "hashicorp-release-signing-key.pgp"
        self._download_official(f"{VAULT_RELEASE_BASE}/{VAULT_ARCHIVE_NAME}", archive_path)
        self._download_official(f"{VAULT_RELEASE_BASE}/vault_{VAULT_VERSION}_SHA256SUMS", sums_path)
        self._download_official(f"{VAULT_RELEASE_BASE}/vault_{VAULT_VERSION}_SHA256SUMS.sig", signature_path)
        self._download_official(HASHICORP_PUBLIC_KEY_URL, public_key_path)

        verify_home = self.software_dir / "hashicorp-signature-verification"
        verify_home.mkdir(parents=False, exist_ok=False)
        self._run_wsl_gpg(
            ["--batch", "--homedir", self._wsl_path(verify_home), "--import", self._wsl_path(public_key_path)],
            failure_code="hashicorp_signing_key_import_failed",
        )
        signature_check = self._run_wsl_gpg(
            [
                "--batch",
                "--homedir",
                self._wsl_path(verify_home),
                "--status-fd",
                "1",
                "--verify",
                self._wsl_path(signature_path),
                self._wsl_path(sums_path),
            ],
            failure_code="vault_checksum_signature_invalid",
        )
        signature_status = signature_check.stdout.decode("utf-8", "replace")
        if not gpg_validsig_matches_hashicorp_release(signature_status):
            raise RehearsalBlocked("vault_checksum_signature_fingerprint_invalid")

        manifest = sums_path.read_text(encoding="utf-8")
        expected_sha256 = parse_signed_checksum_manifest(manifest, expected_filename=VAULT_ARCHIVE_NAME)
        archive_sha256 = self._sha256_file(archive_path)
        if not secrets.compare_digest(expected_sha256, archive_sha256):
            archive_path.unlink(missing_ok=True)
            raise RehearsalBlocked("vault_archive_checksum_invalid")

        extracted_dir = self.software_dir / f"vault-{VAULT_VERSION}-windows-amd64"
        extracted_dir.mkdir(parents=False, exist_ok=False)
        with zipfile.ZipFile(archive_path, "r") as archive:
            members = archive.namelist()
            if "vault.exe" not in members or any(
                name.startswith(("/", "\\")) or ".." in Path(name).parts for name in members
            ):
                raise RehearsalBlocked("vault_archive_members_invalid")
            archive.extractall(extracted_dir)
        self.vault_executable = extracted_dir / "vault.exe"
        if not self.vault_executable.is_file():
            raise RehearsalBlocked("vault_executable_missing")
        completed = self._run_process(
            [str(self.vault_executable), "version"],
            failure_code="vault_version_probe_failed",
        )
        version_output = completed.stdout.decode("utf-8", "replace")
        if f"Vault v{VAULT_VERSION}" not in version_output:
            raise RehearsalBlocked("vault_version_mismatch")
        return {
            "vault_version": VAULT_VERSION,
            "vault_archive_sha256": archive_sha256,
            "vault_checksum_signature_verified": True,
            "vault_archive_checksum_verified": True,
            "vault_source_host": "releases.hashicorp.com",
        }

    @staticmethod
    def _download_official(url: str, destination: Path) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
            raise RehearsalBlocked("download_source_not_allowlisted")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                final = urllib.parse.urlparse(response.geturl())
                if final.scheme != "https" or final.hostname not in ALLOWED_DOWNLOAD_HOSTS:
                    raise RehearsalBlocked("download_redirect_not_allowlisted")
                payload = response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RehearsalBlocked("official_download_failed") from exc
        if not payload:
            raise RehearsalBlocked("official_download_empty")
        with destination.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _run_process(
        args: list[str],
        *,
        failure_code: str,
        input_data: bytes | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        completed = subprocess.run(
            args,
            input=input_data,
            capture_output=True,
            env=env,
            check=False,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
        if completed.returncode != 0:
            raise RehearsalBlocked(failure_code)
        return completed

    @staticmethod
    def _wsl_path(path: Path) -> str:
        resolved = path.resolve()
        drive = resolved.drive.rstrip(":").lower()
        if drive not in {"e", "f"}:
            raise RehearsalBlocked("wsl_path_outside_approved_volumes")
        remainder = resolved.as_posix().split(":", 1)[1].lstrip("/")
        return f"/mnt/{drive}/{remainder}"

    def _run_wsl_gpg(
        self,
        args: list[str],
        *,
        failure_code: str,
        input_data: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        if shutil.which("wsl.exe") is None:
            raise RehearsalBlocked("wsl_gpg_unavailable")
        return self._run_process(
            ["wsl.exe", "-e", "gpg", *args],
            failure_code=failure_code,
            input_data=input_data,
        )

    def _run_wsl_gpgconf(self, args: list[str], *, failure_code: str) -> subprocess.CompletedProcess[bytes]:
        if shutil.which("wsl.exe") is None:
            raise RehearsalBlocked("wsl_gpg_unavailable")
        return self._run_process(["wsl.exe", "-e", "gpgconf", *args], failure_code=failure_code)

    def _create_disposable_pgp_identities(self) -> dict[str, dict[str, Path | str]]:
        specs = {
            "A": (self.unit_a_dir, "Jiejing Rehearsal Unit A", "unit-a@rehearsal.invalid"),
            "B": (self.unit_b_dir, "Jiejing Rehearsal Unit B", "unit-b@rehearsal.invalid"),
            "C": (self.unit_c_dir, "Jiejing Rehearsal Unit C", "unit-c@rehearsal.invalid"),
            "ROOT": (self.root_unit_dir, "Jiejing Rehearsal Root Operator", "root@rehearsal.invalid"),
        }
        identities: dict[str, dict[str, Path | str]] = {}
        for key, (unit_dir, name, email) in specs.items():
            uid = f"{name} <{email}>"
            # GnuPG's agent socket path is bounded on Linux. The one-character
            # private home stays inside the approved unit while keeping the WSL
            # socket path below that limit.
            gpg_home = unit_dir / "g"
            public_key = unit_dir / "recipient-public.pgp"
            gpg_home.mkdir(parents=False, exist_ok=False)
            self._sensitive_paths.add(gpg_home)
            self._run_wsl_gpgconf(
                ["--homedir", self._wsl_path(gpg_home), "--kill", "gpg-agent"],
                failure_code="rehearsal_pgp_agent_reset_failed",
            )
            key_parameters = (
                "Key-Type: RSA\n"
                "Key-Length: 3072\n"
                "Key-Usage: cert,sign\n"
                "Subkey-Type: RSA\n"
                "Subkey-Length: 3072\n"
                "Subkey-Usage: encrypt\n"
                f"Name-Real: {name}\n"
                f"Name-Email: {email}\n"
                "Expire-Date: 1d\n"
                "%no-protection\n"
                "%commit\n"
            ).encode("utf-8")
            self._run_wsl_gpg(
                [
                    "--batch",
                    "--no-tty",
                    "--homedir",
                    self._wsl_path(gpg_home),
                    "--faked-system-time",
                    str(int(time.time()) - PGP_CREATION_SKEW_SECONDS),
                    "--generate-key",
                ],
                failure_code=f"rehearsal_pgp_key_generation_failed_{key.lower()}",
                input_data=key_parameters,
            )
            self._run_wsl_gpg(
                [
                    "--batch",
                    "--no-tty",
                    "--homedir",
                    self._wsl_path(gpg_home),
                    "--output",
                    self._wsl_path(public_key),
                    "--export",
                    uid,
                ],
                failure_code="rehearsal_pgp_public_export_failed",
            )
            if not public_key.is_file() or public_key.stat().st_size < 256:
                raise RehearsalBlocked("rehearsal_pgp_public_key_invalid")
            packets = self._run_wsl_gpg(
                ["--batch", "--list-packets", self._wsl_path(public_key)],
                failure_code="rehearsal_pgp_algorithm_invalid",
            ).stdout.decode("utf-8", "replace")
            if not pgp_packet_report_is_rsa_encryption_capable(packets):
                raise RehearsalBlocked("rehearsal_pgp_algorithm_invalid")
            self._public_key_paths.append(public_key)
            identities[key] = {"unit_dir": unit_dir, "gpg_home": gpg_home, "public_key": public_key, "uid": uid}
        return identities

    def _decrypt_pgp_b64(self, encrypted_b64: str, *, identity: dict[str, Path | str]) -> str:
        try:
            encrypted = base64.b64decode(encrypted_b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise RehearsalBlocked("pgp_ciphertext_invalid") from exc
        gpg_home = identity["gpg_home"]
        if not isinstance(gpg_home, Path):
            raise RehearsalBlocked("pgp_identity_invalid")
        completed = self._run_wsl_gpg(
            ["--batch", "--no-tty", "--quiet", "--homedir", self._wsl_path(gpg_home), "--decrypt"],
            failure_code="pgp_decryption_failed",
            input_data=encrypted,
        )
        try:
            value = completed.stdout.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise RehearsalBlocked("pgp_plaintext_invalid") from exc
        if not value or len(value) > 4096:
            raise RehearsalBlocked("pgp_plaintext_invalid")
        self._secret_canaries.append(value)
        return value

    def _run_initial_vault_lifecycle(
        self, identities: dict[str, dict[str, Path | str]]
    ) -> dict[str, object]:
        policy_body = self.policy_file.read_text(encoding="utf-8")
        policy_sha256 = hashlib.sha256(policy_body.encode("utf-8")).hexdigest()
        self._phase_failure_code = "initial_vault_start_unexpected"
        port = self._free_loopback_port()
        config_path = self._write_vault_config(
            storage_path=self.live_data_dir,
            port=port,
            filename="live-vault.hcl",
        )
        vault = self._start_vault(config_path=config_path, port=port, log_name="live-vault.log")
        health = self._wait_for_vault(vault.address)
        if health.get("initialized") is not False or health.get("sealed") is not True:
            raise RehearsalBlocked("fresh_vault_state_invalid")

        self._phase_failure_code = "initial_vault_init_unexpected"
        public_keys = [identities[key]["public_key"] for key in ("A", "B", "C")]
        root_public_key = identities["ROOT"]["public_key"]
        if not all(isinstance(path, Path) for path in [*public_keys, root_public_key]):
            raise RehearsalBlocked("pgp_public_key_mapping_invalid")
        env = os.environ.copy()
        env["VAULT_ADDR"] = vault.address
        init = self._run_process(
            [
                str(self.vault_executable),
                "operator",
                "init",
                "-format=json",
                "-key-shares=3",
                "-key-threshold=2",
                "-pgp-keys=" + ",".join(str(path) for path in public_keys),
                "-root-token-pgp-key=" + str(root_public_key),
            ],
            failure_code="vault_operator_init_failed",
            env=env,
        )
        try:
            initialized = json.loads(init.stdout)
        except json.JSONDecodeError as exc:
            raise RehearsalBlocked("vault_operator_init_output_invalid") from exc
        encrypted_shares = initialized.get("unseal_keys_b64") if isinstance(initialized, dict) else None
        encrypted_root = initialized.get("root_token") if isinstance(initialized, dict) else None
        if (
            not isinstance(encrypted_shares, list)
            or len(encrypted_shares) != 3
            or not all(isinstance(item, str) and item for item in encrypted_shares)
            or not isinstance(encrypted_root, str)
            or not encrypted_root
        ):
            raise RehearsalBlocked("vault_operator_init_geometry_invalid")

        for key, encrypted_share in zip(("A", "B", "C"), encrypted_shares, strict=True):
            unit_dir = identities[key]["unit_dir"]
            if not isinstance(unit_dir, Path):
                raise RehearsalBlocked("pgp_unit_mapping_invalid")
            encrypted_path = unit_dir / "encrypted-unseal-share.pgp.b64"
            self._exclusive_write_text(encrypted_path, encrypted_share + "\n")
            self._sensitive_paths.add(encrypted_path)
        encrypted_root_path = self.root_unit_dir / "encrypted-initial-root-token.pgp.b64"
        self._exclusive_write_text(encrypted_root_path, encrypted_root + "\n")
        self._sensitive_paths.add(encrypted_root_path)

        self._phase_failure_code = "initial_vault_unseal_unexpected"
        share_a = self._decrypt_pgp_b64(encrypted_shares[0], identity=identities["A"])
        share_b = self._decrypt_pgp_b64(encrypted_shares[1], identity=identities["B"])
        root_token = self._decrypt_pgp_b64(encrypted_root, identity=identities["ROOT"])
        single_sealed, two_unsealed = self._prove_unseal_threshold(vault.address, share_a=share_a, share_b=share_b)
        if not single_sealed or not two_unsealed:
            raise RehearsalBlocked("vault_unseal_threshold_not_proven")

        self._phase_failure_code = "vault_policy_setup_unexpected"
        self._vault_request(
            vault.address,
            "POST",
            "/v1/sys/mounts/secret",
            token=root_token,
            body={"type": "kv", "options": {"version": "2"}},
            expected_statuses={200, 204},
            failure_code="vault_mount_enable_failed",
        )
        self._vault_request(
            vault.address,
            "PUT",
            f"/v1/sys/policies/acl/{REHEARSAL_POLICY_NAME}",
            token=root_token,
            body={"policy": policy_body},
            expected_statuses={200, 204},
            failure_code="vault_policy_install_failed",
        )
        self._phase_failure_code = "periodic_token_setup_unexpected"
        _, token_response = self._vault_request(
            vault.address,
            "POST",
            "/v1/auth/token/create",
            token=root_token,
            body={
                "policies": [REHEARSAL_POLICY_NAME],
                "period": "30m",
                "renewable": True,
                "no_parent": True,
                "no_default_policy": True,
                "display_name": "jiejing-production-rehearsal-backend",
            },
            expected_statuses={200},
            failure_code="periodic_backend_token_create_failed",
        )
        auth = token_response.get("auth") if isinstance(token_response, dict) else None
        backend_token = auth.get("client_token") if isinstance(auth, dict) else None
        if not isinstance(backend_token, str) or not backend_token:
            raise RehearsalBlocked("periodic_backend_token_missing")
        self._secret_canaries.append(backend_token)
        _, lookup = self._vault_request(
            vault.address,
            "GET",
            "/v1/auth/token/lookup-self",
            token=backend_token,
            expected_statuses={200},
            failure_code="periodic_backend_token_lookup_failed",
        )
        lookup_data = lookup.get("data") if isinstance(lookup, dict) else None
        renewable = isinstance(lookup_data, dict) and lookup_data.get("renewable") is True
        period = lookup_data.get("period") if isinstance(lookup_data, dict) else None
        positive_period = type(period) is int and period > 0
        if not renewable or not positive_period:
            raise RehearsalBlocked("periodic_backend_token_contract_invalid")
        self._vault_request(
            vault.address,
            "POST",
            "/v1/auth/token/renew-self",
            token=backend_token,
            body={},
            expected_statuses={200},
            failure_code="periodic_backend_token_renew_failed",
        )
        self._verify_backend_token_capabilities(vault.address, backend_token=backend_token)

        self._phase_failure_code = "sentinel_lifecycle_unexpected"
        sentinel_reference = "jiejing-production/rehearsal/" + secrets.token_urlsafe(18)
        sentinel_value = secrets.token_urlsafe(48)
        self._secret_canaries.extend([sentinel_reference, sentinel_value])
        sentinel_path = "/v1/secret/data/" + sentinel_reference
        self._phase_failure_code = "root_revocation_unexpected"
        self._vault_request(
            vault.address,
            "POST",
            sentinel_path,
            token=backend_token,
            body={"data": {"value": sentinel_value}},
            expected_statuses={200},
            failure_code="sentinel_write_failed",
        )
        resolved = self._read_sentinel(vault.address, backend_token=backend_token, sentinel_path=sentinel_path)
        if not secrets.compare_digest(resolved, sentinel_value):
            raise RehearsalBlocked("sentinel_initial_read_mismatch")

        self._vault_request(
            vault.address,
            "POST",
            "/v1/auth/token/revoke-self",
            token=root_token,
            body={},
            expected_statuses={200, 204},
            failure_code="initial_root_token_revoke_failed",
        )
        self._vault_request(
            vault.address,
            "GET",
            "/v1/auth/token/lookup-self",
            token=root_token,
            expected_statuses={403},
            failure_code="initial_root_token_revoke_verification_failed",
        )
        self._vault_request(
            vault.address,
            "GET",
            "/v1/auth/token/lookup-self",
            token=backend_token,
            expected_statuses={200},
            failure_code="periodic_backend_token_lookup_failed",
        )

        return {
            "vault": vault,
            "share_a": share_a,
            "share_b": share_b,
            "backend_token": backend_token,
            "sentinel_path": sentinel_path,
            "sentinel_value": sentinel_value,
            "public_evidence": {
                "listener_loopback_only": True,
                "key_shares": 3,
                "key_threshold": 2,
                "simulated_custody_unit_count": 3,
                "max_shares_per_simulated_unit": 1,
                "pgp_encrypted_shares": True,
                "pgp_encrypted_root_token": True,
                "single_share_remains_sealed": True,
                "two_share_unseal_verified": True,
                "production_policy_sha256": policy_sha256,
                "periodic_token_renewable": True,
                "periodic_token_positive_period": True,
                "periodic_token_renew_self_verified": True,
                "initial_root_token_revoked": True,
                "sentinel_reference_sha256": hashlib.sha256(sentinel_reference.encode("utf-8")).hexdigest(),
                "sentinel_payload_sha256": hashlib.sha256(sentinel_value.encode("utf-8")).hexdigest(),
            },
        }

    @staticmethod
    def _free_loopback_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def _write_vault_config(self, *, storage_path: Path, port: int, filename: str) -> Path:
        config_path = self.config_dir / filename
        storage = storage_path.as_posix()
        body = (
            "ui = false\n"
            "disable_mlock = true\n\n"
            "storage \"file\" {\n"
            f"  path = \"{storage}\"\n"
            "}\n\n"
            "listener \"tcp\" {\n"
            f"  address = \"127.0.0.1:{port}\"\n"
            "  tls_disable = true\n"
            "}\n\n"
            f"api_addr = \"http://127.0.0.1:{port}\"\n"
        )
        self._exclusive_write_text(config_path, body)
        return config_path

    def _start_vault(self, *, config_path: Path, port: int, log_name: str) -> _VaultProcess:
        address = f"http://127.0.0.1:{port}"
        log_path = self.software_dir / log_name
        log_handle = log_path.open("xb")
        self._sensitive_paths.add(log_path)
        try:
            process = subprocess.Popen(
                [str(self.vault_executable), "server", f"-config={config_path}"],
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
        except Exception:
            log_handle.close()
            raise
        vault = _VaultProcess(process=process, log_handle=log_handle, address=address, port=port)
        self._vault_processes.append(vault)
        return vault

    def _wait_for_vault(self, address: str, *, timeout_seconds: float = 20.0) -> dict[str, object]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                _, body = self._vault_request(
                    address,
                    "GET",
                    "/v1/sys/health",
                    expected_statuses={200, 429, 472, 473, 501, 503},
                )
                if isinstance(body, dict):
                    return body
            except RehearsalBlocked:
                pass
            time.sleep(0.2)
        raise RehearsalBlocked("vault_start_timeout")

    @staticmethod
    def _vault_request(
        address: str,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, object] | None = None,
        expected_statuses: set[int],
        failure_code: str = "vault_loopback_response_unexpected",
    ) -> tuple[int, dict[str, object]]:
        parsed = urllib.parse.urlparse(address)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None:
            raise RehearsalBlocked("vault_address_not_loopback")
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Vault-Token"] = token
        request = urllib.request.Request(address + path, data=data, headers=headers, method=method)
        status = 0
        payload = b""
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status = int(response.status)
                payload = response.read()
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            payload = exc.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RehearsalBlocked("vault_loopback_request_failed") from exc
        if status not in expected_statuses:
            raise RehearsalBlocked(failure_code)
        if not payload:
            return status, {}
        try:
            parsed_payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RehearsalBlocked("vault_loopback_json_invalid") from exc
        if not isinstance(parsed_payload, dict):
            raise RehearsalBlocked("vault_loopback_json_invalid")
        return status, parsed_payload

    def _prove_unseal_threshold(self, address: str, *, share_a: str, share_b: str) -> tuple[bool, bool]:
        _, after_one = self._vault_request(
            address,
            "POST",
            "/v1/sys/unseal",
            body={"key": share_a},
            expected_statuses={200},
            failure_code="vault_unseal_response_unexpected",
        )
        single_share_remains_sealed = after_one.get("sealed") is True and after_one.get("progress") == 1
        _, after_two = self._vault_request(
            address,
            "POST",
            "/v1/sys/unseal",
            body={"key": share_b},
            expected_statuses={200},
            failure_code="vault_unseal_response_unexpected",
        )
        two_share_unseal_verified = after_two.get("sealed") is False
        return single_share_remains_sealed, two_share_unseal_verified

    def _verify_backend_token_capabilities(self, address: str, *, backend_token: str) -> None:
        self._vault_request(
            address,
            "GET",
            "/v1/sys/mounts",
            token=backend_token,
            expected_statuses={403},
            failure_code="backend_token_capability_probe_failed",
        )
        self._vault_request(
            address,
            "GET",
            "/v1/secret/data/outside-boundary/value",
            token=backend_token,
            expected_statuses={403},
            failure_code="backend_token_capability_probe_failed",
        )

    @staticmethod
    def _read_sentinel(address: str, *, backend_token: str, sentinel_path: str) -> str:
        _, payload = WindowsEfVaultRehearsalBackend._vault_request(
            address,
            "GET",
            sentinel_path,
            token=backend_token,
            expected_statuses={200},
            failure_code="sentinel_read_failed",
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        nested = data.get("data") if isinstance(data, dict) else None
        value = nested.get("value") if isinstance(nested, dict) else None
        if not isinstance(value, str) or not value:
            raise RehearsalBlocked("sentinel_resolve_invalid")
        return value

    @staticmethod
    def _exclusive_write_text(path: Path, value: str) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise

    def _backup_and_restore(
        self,
        lifecycle: dict[str, object],
        identities: dict[str, dict[str, Path | str]],
    ) -> dict[str, object]:
        self._phase_failure_code = "backup_stop_unexpected"
        live_vault = lifecycle.get("vault")
        if not isinstance(live_vault, _VaultProcess):
            raise RehearsalBlocked("live_vault_process_missing")
        self._stop_vault_process(live_vault)
        if live_vault.process.poll() is None or not self._loopback_port_closed(live_vault.port):
            raise RehearsalBlocked("vault_not_stopped_before_backup")

        self._phase_failure_code = "backup_snapshot_unexpected"
        plaintext_archive = self.backup_staging_dir / "vault-file-backend.tar"
        self._sensitive_paths.add(plaintext_archive)
        with tarfile.open(plaintext_archive, "w") as archive:
            source_for_tar: str | Path = self.live_data_dir
            if os.name == "nt":
                source_for_tar = "\\\\?\\" + str(self.live_data_dir)
            archive.add(source_for_tar, arcname="vault-data", recursive=True)
        if not plaintext_archive.is_file() or plaintext_archive.stat().st_size <= 0:
            raise RehearsalBlocked("vault_plaintext_snapshot_invalid")

        self._phase_failure_code = "backup_archive_encrypt_unexpected"
        artifact_name = "vault-rehearsal-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".enc"
        encrypted_archive = EncryptedOffHostArchive(
            archive_dir=self.encrypted_backup_dir,
            key_dir=self.backup_key_dir,
            key_protector=WindowsDpapiKeyProtector(),
        )
        artifact = encrypted_archive.store(plaintext_archive.read_bytes(), artifact_name=artifact_name)
        protected_key_path = self.backup_key_dir / f"{artifact_name}.key.protected"
        self._sensitive_paths.add(protected_key_path)
        plaintext_archive.unlink()
        if not artifact.get("encrypted") or artifact.get("cipher") != "AES-256-GCM":
            raise RehearsalBlocked("encrypted_backup_contract_invalid")

        self._phase_failure_code = "fresh_restore_unexpected"
        if self.original_retired_dir.exists() or self.isolated_restore_dir.exists():
            raise RehearsalBlocked("fresh_restore_paths_not_empty")
        self.live_data_dir.rename(self.original_retired_dir)
        self.isolated_restore_dir.mkdir(parents=False, exist_ok=False)
        snapshot = encrypted_archive.restore(artifact_name)
        self._extract_snapshot(snapshot, destination=self.isolated_restore_dir)
        restored_data_dir = self.isolated_restore_dir / "vault-data"
        if not restored_data_dir.is_dir():
            raise RehearsalBlocked("fresh_restore_storage_missing")

        restore_port = self._free_loopback_port()
        restore_config = self._write_vault_config(
            storage_path=restored_data_dir,
            port=restore_port,
            filename="restored-vault.hcl",
        )
        restored_vault = self._start_vault(
            config_path=restore_config,
            port=restore_port,
            log_name="restored-vault.log",
        )
        restored_health = self._wait_for_vault(restored_vault.address)
        if restored_health.get("initialized") is not True or restored_health.get("sealed") is not True:
            raise RehearsalBlocked("restored_vault_initial_state_invalid")

        share_a = lifecycle.get("share_a")
        share_b = lifecycle.get("share_b")
        backend_token = lifecycle.get("backend_token")
        sentinel_path = lifecycle.get("sentinel_path")
        sentinel_value = lifecycle.get("sentinel_value")
        if not all(isinstance(item, str) and item for item in (share_a, share_b, backend_token, sentinel_path, sentinel_value)):
            raise RehearsalBlocked("restore_secret_handles_missing")
        restored_single_sealed, restored_two_unsealed = self._prove_unseal_threshold(
            restored_vault.address,
            share_a=share_a,
            share_b=share_b,
        )
        if not restored_single_sealed or not restored_two_unsealed:
            raise RehearsalBlocked("restored_unseal_threshold_not_proven")
        self._vault_request(
            restored_vault.address,
            "POST",
            "/v1/auth/token/renew-self",
            token=backend_token,
            body={},
            expected_statuses={200},
            failure_code="periodic_backend_token_renew_failed",
        )
        restored_sentinel = self._read_sentinel(
            restored_vault.address,
            backend_token=backend_token,
            sentinel_path=sentinel_path,
        )
        sentinel_digest_match = secrets.compare_digest(
            hashlib.sha256(restored_sentinel.encode("utf-8")).digest(),
            hashlib.sha256(sentinel_value.encode("utf-8")).digest(),
        )
        if not sentinel_digest_match:
            raise RehearsalBlocked("restored_sentinel_digest_mismatch")
        return {
            "vault_stopped_before_backup": True,
            "encrypted_backup_verified": True,
            "encrypted_backup_sha256": str(artifact.get("artifact_sha256") or ""),
            "fresh_restore_verified": True,
            "restored_single_share_remains_sealed": True,
            "restored_two_share_unseal_verified": True,
            "restored_periodic_token_renewed": True,
            "sentinel_resolved_after_restore": True,
            "sentinel_digest_match": True,
        }

    @staticmethod
    def _extract_snapshot(snapshot: bytes, *, destination: Path) -> None:
        try:
            with tarfile.open(fileobj=io.BytesIO(snapshot), mode="r:") as archive:
                members = archive.getmembers()
                if not members:
                    raise RehearsalBlocked("backup_archive_empty")
                for member in members:
                    member_path = Path(member.name)
                    if member_path.is_absolute() or ".." in member_path.parts or member_path.parts[0] != "vault-data":
                        raise RehearsalBlocked("backup_archive_member_invalid")
                extract_destination: str | Path = destination
                if os.name == "nt":
                    extract_destination = "\\\\?\\" + str(destination.resolve())
                archive.extractall(extract_destination, members=members, filter="data")
        except (tarfile.TarError, EOFError) as exc:
            raise RehearsalBlocked("backup_archive_invalid") from exc

    @staticmethod
    def _loopback_port_closed(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(0.5)
            return client.connect_ex(("127.0.0.1", port)) != 0

    def _stop_vault_process(self, vault: _VaultProcess) -> None:
        process = vault.process
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        try:
            vault.log_handle.close()
        except Exception:
            pass

    def _stop_all_vault_processes(self) -> None:
        for vault in reversed(self._vault_processes):
            try:
                self._stop_vault_process(vault)
            except Exception:
                pass

    def _cleanup_sensitive_material(self) -> None:
        if not self._roots_created:
            return
        for unit in (self.unit_a_dir, self.unit_b_dir, self.unit_c_dir, self.root_unit_dir):
            gpg_home = unit / "g"
            if gpg_home.exists():
                try:
                    self._run_wsl_gpgconf(
                        ["--homedir", self._wsl_path(gpg_home), "--kill", "gpg-agent"],
                        failure_code="rehearsal_pgp_agent_reset_failed",
                    )
                except Exception:
                    pass
        for path in sorted(self._sensitive_paths, key=lambda item: len(item.parts), reverse=True):
            try:
                self._remove_rehearsal_path(path)
            except Exception:
                pass
        for path in (self.live_data_dir, self.original_retired_dir, self.isolated_restore_dir):
            try:
                self._remove_rehearsal_path(path)
            except Exception:
                pass

    def _remove_rehearsal_path(self, path: Path) -> None:
        resolved = path.resolve()
        if not (resolved.is_relative_to(self.source_root) or resolved.is_relative_to(self.restore_root)):
            raise RehearsalBlocked("cleanup_path_outside_rehearsal_roots")
        if resolved in {self.source_root, self.restore_root}:
            raise RehearsalBlocked("cleanup_root_delete_forbidden")
        if resolved.is_dir() and not resolved.is_symlink():
            delete_target: str | Path = resolved
            if os.name == "nt":
                delete_target = "\\\\?\\" + str(resolved)
            shutil.rmtree(delete_target)
        else:
            resolved.unlink(missing_ok=True)

    def _cleanup_verified(self) -> bool:
        if any(path.exists() for path in self._sensitive_paths):
            return False
        if any(path.exists() for path in (self.live_data_dir, self.original_retired_dir, self.isolated_restore_dir)):
            return False
        for unit in (self.unit_a_dir, self.unit_b_dir, self.unit_c_dir, self.root_unit_dir):
            if (unit / "g").exists() or (unit / "encrypted-unseal-share.pgp.b64").exists():
                return False
        if any(self.backup_key_dir.glob("*.key.protected")):
            return False
        return True

    def _scan_retained_files_for_secrets(self) -> bool:
        canaries = [item.encode("utf-8") for item in self._secret_canaries if item]
        if not canaries:
            return False
        files: list[Path] = []
        for root in (self.source_root, self.restore_root):
            files.extend(path for path in root.rglob("*") if path.is_file())
        project_root = Path(__file__).resolve().parents[1]
        for relative in (
            "tools/jiejing_vault_production_grade_rehearsal.py",
            "tools/test_jiejing_vault_production_grade_rehearsal.py",
            "docs/superpowers/specs/2026-08-21-vault-production-grade-recovery-rehearsal-design.md",
            "docs/superpowers/plans/2026-08-21-vault-production-grade-recovery-rehearsal-implementation-plan.md",
            "deploy/vault-policy.production.hcl",
        ):
            candidate = project_root / relative
            if candidate.is_file():
                files.append(candidate)
        for path in files:
            try:
                payload = path.read_bytes()
            except OSError:
                return False
            if any(canary in payload for canary in canaries):
                return False
        return True

    @staticmethod
    def _public_health_projection() -> dict[str, object]:
        projection: dict[str, object] = {}
        for path in ("/health", "/health/deep", "/readiness/product-saas"):
            request = urllib.request.Request(PUBLIC_BASE_URL + path, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    if int(response.status) != 200:
                        raise RehearsalBlocked("public_health_http_invalid")
                    payload = json.loads(response.read())
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                raise RehearsalBlocked("public_health_probe_failed") from exc
            if path == "/health":
                source = payload
                keys = (
                    "status",
                    "database_startup_status",
                    "real_platform_writes_enabled",
                    "requested_real_platform_writes",
                    "secret_exposed",
                )
            elif path == "/health/deep":
                source = payload.get("operational_health") if isinstance(payload, dict) else None
                keys = ("status", "database", "queue", "worker", "secret_exposed")
            else:
                source = payload.get("readiness") if isinstance(payload, dict) else None
                keys = (
                    "beta_ready",
                    "production_ready",
                    "can_accept_real_customers",
                    "real_platform_writes_enabled",
                    "requested_real_platform_writes",
                    "secret_exposed",
                    "blocker_count",
                    "warning_count",
                )
            if not isinstance(source, dict):
                raise RehearsalBlocked("public_health_contract_invalid")
            projection[path] = {key: source.get(key) for key in keys}
        return projection


def _contains_forbidden_evidence_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in FORBIDDEN_EVIDENCE_KEYS or _contains_forbidden_evidence_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_evidence_key(item) for item in value)
    return False


def _write_value_free_evidence(path: Path, result: dict[str, object]) -> None:
    if _contains_forbidden_evidence_key(result) or result.get("secret_exposed") is not False:
        raise RehearsalBlocked("public_evidence_not_value_free")
    payload = (json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run the approved E/F production-grade Vault recovery rehearsal.")
    parser.add_argument("--source-root", type=Path, default=Path(r"E:\Jiejing-Vault-Recovery-Rehearsal-Source"))
    parser.add_argument("--restore-root", type=Path, default=Path(r"F:\Jiejing-Vault-Recovery-Rehearsal-Restore"))
    parser.add_argument("--policy-file", type=Path, default=project_root / "deploy" / "vault-policy.production.hcl")
    parser.add_argument("--execute", action="store_true", help="Generate disposable rehearsal credentials and execute the ceremony.")
    args = parser.parse_args(argv)
    if not args.execute:
        print("BLOCKED explicit --execute is required; no files or credentials were created")
        return 2

    backend = WindowsEfVaultRehearsalBackend(
        source_root=args.source_root,
        restore_root=args.restore_root,
        policy_file=args.policy_file,
    )
    result = execute_production_grade_rehearsal(backend=backend)
    evidence_path = args.restore_root.resolve() / "evidence" / "rehearsal-result.json"
    if evidence_path.parent.is_dir():
        _write_value_free_evidence(evidence_path, result)
    if result.get("status") == "verified":
        print("PASS jiejing_vault_production_grade_rehearsal")
        return 0
    print("BLOCKED jiejing_vault_production_grade_rehearsal")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

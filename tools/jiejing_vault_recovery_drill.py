#!/usr/bin/env python3
"""Value-free orchestration for an encrypted Vault backup/restore drill.

The orchestration deliberately depends on a narrow backend interface.  The
backend owns all secret-bearing and host-specific operations; this module only
orders them and returns evidence that is safe for logs and readiness gates.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


CONTRACT_VERSION = "jiejing_vault_recovery_drill_v1"
ARCHIVE_MAGIC = b"JIEJING-VAULT-AESGCM-V1\x00"
ARCHIVE_AAD = b"jiejing-vault-recovery-drill-v1"
ARTIFACT_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\.enc\Z")


class KeyProtector(Protocol):
    def protect(self, key: bytes) -> bytes: ...

    def unprotect(self, protected_key: bytes) -> bytes: ...


class WindowsDpapiKeyProtector:
    """Protect recovery keys for the current Windows user with DPAPI."""

    def protect(self, key: bytes) -> bytes:
        return self._crypt(key, protect=True)

    def unprotect(self, protected_key: bytes) -> bytes:
        return self._crypt(protected_key, protect=False)

    @staticmethod
    def _crypt(data: bytes, *, protect: bool) -> bytes:
        if sys.platform != "win32":
            raise RuntimeError("Windows DPAPI is required for Vault recovery keys")
        import ctypes
        from ctypes import wintypes

        class DataBlob(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        source = ctypes.create_string_buffer(data)
        source_blob = DataBlob(
            len(data),
            ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)),
        )
        target_blob = DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if protect:
            ok = crypt32.CryptProtectData(
                ctypes.byref(source_blob),
                "Jiejing Vault recovery key",
                None,
                None,
                None,
                0,
                ctypes.byref(target_blob),
            )
        else:
            description = ctypes.c_wchar_p()
            ok = crypt32.CryptUnprotectData(
                ctypes.byref(source_blob),
                ctypes.byref(description),
                None,
                None,
                None,
                0,
                ctypes.byref(target_blob),
            )
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(target_blob.pbData, target_blob.cbData)
        finally:
            if target_blob.pbData:
                kernel32.LocalFree(target_blob.pbData)


class EncryptedOffHostArchive:
    """Store AES-256-GCM artifacts with a separately protected recovery key."""

    def __init__(self, *, archive_dir: Path, key_dir: Path, key_protector: KeyProtector) -> None:
        self.archive_dir = archive_dir.resolve()
        self.key_dir = key_dir.resolve()
        self.key_protector = key_protector

    def store(self, snapshot: bytes, *, artifact_name: str) -> dict[str, object]:
        artifact_path, key_path = self._paths(artifact_name)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.key_dir.mkdir(parents=True, exist_ok=True)
        if artifact_path.exists() or key_path.exists():
            raise FileExistsError("Vault recovery artifact already exists")
        key = secrets.token_bytes(32)
        nonce = secrets.token_bytes(12)
        encrypted = ARCHIVE_MAGIC + nonce + AESGCM(key).encrypt(nonce, snapshot, ARCHIVE_AAD)
        protected_key = self.key_protector.protect(key)
        self._exclusive_write(artifact_path, encrypted)
        try:
            self._exclusive_write(key_path, protected_key)
        except Exception:
            # Keep the encrypted artifact; it contains no plaintext and documents
            # the failed operation without risking an overwrite on retry.
            raise
        return {
            "artifact_id": artifact_name,
            "encrypted": True,
            "off_host": True,
            "cipher": "AES-256-GCM",
            "encrypted_bytes": len(encrypted),
            "artifact_sha256": hashlib.sha256(encrypted).hexdigest(),
            "secret_exposed": False,
        }

    def restore(self, artifact_id: str) -> bytes:
        artifact_path, key_path = self._paths(artifact_id)
        payload = artifact_path.read_bytes()
        if not payload.startswith(ARCHIVE_MAGIC) or len(payload) <= len(ARCHIVE_MAGIC) + 12:
            raise ValueError("Invalid encrypted Vault recovery artifact")
        nonce_offset = len(ARCHIVE_MAGIC)
        nonce = payload[nonce_offset : nonce_offset + 12]
        ciphertext = payload[nonce_offset + 12 :]
        key = self.key_protector.unprotect(key_path.read_bytes())
        if len(key) != 32:
            raise ValueError("Invalid protected Vault recovery key")
        return AESGCM(key).decrypt(nonce, ciphertext, ARCHIVE_AAD)

    def _paths(self, artifact_name: str) -> tuple[Path, Path]:
        if not ARTIFACT_NAME_PATTERN.fullmatch(artifact_name):
            raise ValueError("Invalid Vault recovery artifact name")
        return (
            self.archive_dir / artifact_name,
            self.key_dir / f"{artifact_name}.key.protected",
        )

    @staticmethod
    def _exclusive_write(path: Path, data: bytes) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise


class VaultRecoveryDrillBackend(Protocol):
    def install_synthetic_sentinel(self) -> str: ...

    def quiesce_live_vault(self) -> None: ...

    def capture_consistent_snapshot(self) -> bytes: ...

    def resume_and_unseal_live_vault(self) -> bool: ...

    def store_encrypted_off_host(self, snapshot: bytes) -> dict[str, object]: ...

    def verify_isolated_restore(self, *, artifact_id: str, sentinel: str) -> dict[str, object]: ...


def execute_vault_recovery_drill(*, backend: VaultRecoveryDrillBackend) -> dict[str, object]:
    """Run one drill while always restoring the live Vault before validation."""

    sentinel = ""
    snapshot = b""
    live_quiesced = False
    live_resumed = False
    error_type: str | None = None

    try:
        sentinel = backend.install_synthetic_sentinel()
        backend.quiesce_live_vault()
        live_quiesced = True
        snapshot = backend.capture_consistent_snapshot()
    except Exception as exc:  # The public report records only an allowlisted type shape.
        error_type = type(exc).__name__
    finally:
        if live_quiesced:
            try:
                live_resumed = backend.resume_and_unseal_live_vault() is True
            except Exception as exc:  # Never replace the original failure with a message.
                error_type = error_type or type(exc).__name__

    if error_type is not None or not live_resumed:
        return _blocked(error_type=error_type or "LiveVaultResumeFailed", live_resumed=live_resumed)

    try:
        artifact = backend.store_encrypted_off_host(snapshot)
        artifact_id = str(artifact.get("artifact_id") or "")
        if not artifact_id or artifact.get("encrypted") is not True or artifact.get("off_host") is not True:
            return _blocked(error_type="EncryptedArtifactInvalid", live_resumed=True)
        restore = backend.verify_isolated_restore(artifact_id=artifact_id, sentinel=sentinel)
        restored = restore.get("restored") is True
        manually_unsealed = restore.get("manually_unsealed") is True
        sentinel_resolved = restore.get("sentinel_resolved") is True
        if not (restored and manually_unsealed and sentinel_resolved):
            return _blocked(error_type="IsolatedRestoreNotVerified", live_resumed=True)
        key_shares = restore.get("key_shares")
        key_threshold = restore.get("key_threshold")
        if (
            type(key_shares) is not int
            or type(key_threshold) is not int
            or key_shares < 3
            or key_threshold < 2
            or key_threshold > key_shares
        ):
            return _blocked(error_type="ProductionUnsealBoundaryNotMet", live_resumed=True)
    except Exception as exc:
        return _blocked(error_type=type(exc).__name__, live_resumed=True)

    return {
        "status": "verified",
        "contract_version": CONTRACT_VERSION,
        "artifact_id": artifact_id,
        "encrypted_off_host_backup": True,
        "live_vault_resumed_and_unsealed": True,
        "isolated_restore_verified": True,
        "manual_unseal_verified": True,
        "sentinel_resolve_verified": True,
        "blockers": [],
        "error_type": None,
        "secret_exposed": False,
    }


def _blocked(*, error_type: str, live_resumed: bool) -> dict[str, object]:
    return {
        "status": "blocked",
        "contract_version": CONTRACT_VERSION,
        "artifact_id": None,
        "encrypted_off_host_backup": False,
        "live_vault_resumed_and_unsealed": live_resumed,
        "isolated_restore_verified": False,
        "manual_unseal_verified": False,
        "sentinel_resolve_verified": False,
        "blockers": ["vault_recovery_drill_failed"],
        "error_type": error_type,
        "secret_exposed": False,
    }

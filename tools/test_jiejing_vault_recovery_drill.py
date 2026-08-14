#!/usr/bin/env python3
"""Public-contract tests for the value-free Vault recovery drill."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.jiejing_vault_recovery_drill import (  # noqa: E402
    EncryptedOffHostArchive,
    WindowsDpapiKeyProtector,
    execute_vault_recovery_drill,
)


SECRET_SENTINEL = "vault-recovery-secret-must-never-leak"


class FakeVaultDrillBackend:
    def __init__(self, *, fail_snapshot: bool = False, key_shares: int = 3, key_threshold: int = 2) -> None:
        self.fail_snapshot = fail_snapshot
        self.key_shares = key_shares
        self.key_threshold = key_threshold
        self.calls: list[str] = []

    def install_synthetic_sentinel(self) -> str:
        self.calls.append("install_synthetic_sentinel")
        return SECRET_SENTINEL

    def quiesce_live_vault(self) -> None:
        self.calls.append("quiesce_live_vault")

    def capture_consistent_snapshot(self) -> bytes:
        self.calls.append("capture_consistent_snapshot")
        if self.fail_snapshot:
            raise RuntimeError(f"snapshot failed with {SECRET_SENTINEL}")
        return b"synthetic-vault-snapshot-without-real-secrets"

    def resume_and_unseal_live_vault(self) -> bool:
        self.calls.append("resume_and_unseal_live_vault")
        return True

    def store_encrypted_off_host(self, snapshot: bytes) -> dict[str, object]:
        self.calls.append("store_encrypted_off_host")
        assert snapshot.startswith(b"synthetic-vault-snapshot")
        return {
            "artifact_id": "vault-backups/20260814/drill.enc",
            "encrypted": True,
            "off_host": True,
        }

    def verify_isolated_restore(self, *, artifact_id: str, sentinel: str) -> dict[str, object]:
        self.calls.append("verify_isolated_restore")
        assert artifact_id.endswith("drill.enc")
        assert sentinel == SECRET_SENTINEL
        return {
            "restored": True,
            "manually_unsealed": True,
            "sentinel_resolved": True,
            "key_shares": self.key_shares,
            "key_threshold": self.key_threshold,
        }


class FakeKeyProtector:
    def protect(self, key: bytes) -> bytes:
        return b"protected-key:" + key[::-1]

    def unprotect(self, protected_key: bytes) -> bytes:
        prefix = b"protected-key:"
        if not protected_key.startswith(prefix):
            raise ValueError("invalid protected key")
        return protected_key[len(prefix) :][::-1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    backend = FakeVaultDrillBackend()
    result = execute_vault_recovery_drill(backend=backend)
    expected_calls = [
        "install_synthetic_sentinel",
        "quiesce_live_vault",
        "capture_consistent_snapshot",
        "resume_and_unseal_live_vault",
        "store_encrypted_off_host",
        "verify_isolated_restore",
    ]
    if backend.calls != expected_calls:
        return fail(f"recovery order is unsafe: {backend.calls}")
    if result != {
        "status": "verified",
        "contract_version": "jiejing_vault_recovery_drill_v1",
        "artifact_id": "vault-backups/20260814/drill.enc",
        "encrypted_off_host_backup": True,
        "live_vault_resumed_and_unsealed": True,
        "isolated_restore_verified": True,
        "manual_unseal_verified": True,
        "sentinel_resolve_verified": True,
        "blockers": [],
        "error_type": None,
        "secret_exposed": False,
    }:
        return fail(f"unexpected verified report: {result}")
    if SECRET_SENTINEL in json.dumps(result, sort_keys=True):
        return fail("verified report exposed the synthetic sentinel")

    failing_backend = FakeVaultDrillBackend(fail_snapshot=True)
    failed = execute_vault_recovery_drill(backend=failing_backend)
    if failing_backend.calls != [
        "install_synthetic_sentinel",
        "quiesce_live_vault",
        "capture_consistent_snapshot",
        "resume_and_unseal_live_vault",
    ]:
        return fail(f"failure path did not restore the live Vault first: {failing_backend.calls}")
    serialized = json.dumps(failed, sort_keys=True)
    if failed.get("status") != "blocked" or failed.get("live_vault_resumed_and_unsealed") is not True:
        return fail(f"snapshot failure did not remain fail closed: {failed}")
    if failed.get("error_type") != "RuntimeError" or SECRET_SENTINEL in serialized:
        return fail("failure report leaked an exception message or secret")

    weak_backend = FakeVaultDrillBackend(key_shares=1, key_threshold=1)
    weak = execute_vault_recovery_drill(backend=weak_backend)
    if weak.get("status") != "blocked" or weak.get("error_type") != "ProductionUnsealBoundaryNotMet":
        return fail(f"a 1-of-1 Vault was incorrectly accepted for formal launch: {weak}")

    with tempfile.TemporaryDirectory(prefix="jiejing-vault-drill-") as temp_dir:
        base = Path(temp_dir)
        archive_dir = base / "encrypted-artifacts"
        key_dir = base / "recovery-keys"
        archive = EncryptedOffHostArchive(
            archive_dir=archive_dir,
            key_dir=key_dir,
            key_protector=FakeKeyProtector(),
        )
        plaintext = b"vault-snapshot-" + SECRET_SENTINEL.encode("utf-8")
        evidence = archive.store(plaintext, artifact_name="vault-20260814.enc")
        artifact_path = archive_dir / "vault-20260814.enc"
        protected_key_path = key_dir / "vault-20260814.enc.key.protected"
        if not artifact_path.is_file() or not protected_key_path.is_file():
            return fail("encrypted artifact and protected key were not stored separately")
        if plaintext in artifact_path.read_bytes() or plaintext in protected_key_path.read_bytes():
            return fail("off-host files contain the plaintext snapshot")
        if evidence.get("encrypted") is not True or evidence.get("off_host") is not True:
            return fail(f"archive evidence is not value-free: {evidence}")
        if SECRET_SENTINEL in json.dumps(evidence, sort_keys=True):
            return fail("archive evidence exposed plaintext")
        if archive.restore(str(evidence["artifact_id"])) != plaintext:
            return fail("encrypted artifact did not restore byte-for-byte")
        tampered = bytearray(artifact_path.read_bytes())
        tampered[-1] ^= 1
        artifact_path.write_bytes(bytes(tampered))
        try:
            archive.restore(str(evidence["artifact_id"]))
        except Exception as exc:
            if type(exc).__name__ not in {"InvalidTag", "ValueError"}:
                return fail(f"tampered archive failed with unexpected type: {type(exc).__name__}")
        else:
            return fail("tampered encrypted artifact restored successfully")

    if sys.platform == "win32":
        dpapi = WindowsDpapiKeyProtector()
        raw_key = bytes(range(32))
        protected_key = dpapi.protect(raw_key)
        if not protected_key or protected_key == raw_key or raw_key in protected_key:
            return fail("Windows DPAPI did not protect the recovery key")
        if dpapi.unprotect(protected_key) != raw_key:
            return fail("Windows DPAPI recovery key roundtrip failed")

    print("PASS jiejing_vault_recovery_drill")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

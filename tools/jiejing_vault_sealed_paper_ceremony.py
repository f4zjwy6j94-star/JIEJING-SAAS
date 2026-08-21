#!/usr/bin/env python3
"""Human-only, value-free production Vault sealed-paper ceremony."""

from __future__ import annotations

import ctypes
import faulthandler
import gc
import getpass
import hashlib
import hmac
import json
import os
import secrets
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Protocol, TextIO


CONTRACT_VERSION = "jiejing_vault_sealed_paper_ceremony_v1"
POLICY_NAME = "jiejing-production"
BACKEND_TOKEN_PERIOD = "720h"
KEY_SHARES = 3
KEY_THRESHOLD = 2
IRREVERSIBLE_CONFIRMATION_PHRASE = (
    "INITIALIZE JIEJING PRODUCTION VAULT WITH 3 SHARES AND THRESHOLD 2"
)
ANSI_CLEAR_DISPLAY_AND_SCROLLBACK = "\x1b[3J\x1b[2J\x1b[H"
PRODUCTION_POLICY_PATH = Path("/run/jiejing-vault-policy/vault-policy.production.hcl")
PRODUCTION_TOKEN_OUTPUT_DIRECTORY = Path("/run/jiejing-vault-token-output")
PRODUCTION_POLICY_SHA256 = "99a5246fa6a93e0dcc12a84ae43c801b0159d5b78cfb25cb647ea4eb476f633c"
PUBLIC_BLOCKER_CODES = frozenset(
    {
        "backend_token_directory_invalid",
        "backend_token_directory_not_writable",
        "backend_token_directory_permissions_invalid",
        "backend_token_file_already_exists",
        "backend_token_file_invalid",
        "backend_token_file_permissions_invalid",
        "backend_token_preflight_cleanup_failed",
        "backend_token_preflight_required",
        "backend_token_write_failed",
        "core_dump_disable_failed",
        "direct_trusted_tty_required",
        "initial_root_token_revoke_verification_failed",
        "linux_operator_container_required",
        "operator_confirmation_required",
        "operator_console_closed_after_initialization",
        "orphan_token_did_not_survive_root_revocation",
        "paper_share_display_contract_invalid",
        "paper_share_transcription_not_verified",
        "periodic_backend_token_contract_invalid",
        "periodic_backend_token_invalid",
        "periodic_backend_token_policy_invalid",
        "periodic_backend_token_renew_failed",
        "periodic_backend_token_request_invalid",
        "periodic_backend_token_response_invalid",
        "process_dumpability_disable_failed",
        "production_policy_contract_invalid",
        "recording_environment_detected",
        "root_operator_container_required",
        "secret_process_memory_lock_failed",
        "single_share_unseal_boundary_invalid",
        "two_share_unseal_boundary_invalid",
        "vault_already_initialized",
        "vault_http_request_failed",
        "vault_initialization_response_invalid",
        "vault_initialization_status_invalid",
        "vault_internal_address_invalid",
        "vault_mount_status_invalid",
        "vault_policy_contract_invalid",
        "vault_request_path_invalid",
        "vault_request_token_invalid",
        "vault_response_content_type_invalid",
        "vault_response_json_invalid",
        "vault_response_too_large",
        "vault_secret_mount_invalid",
        "vault_token_lookup_failed",
        "vault_token_lookup_invalid",
        "vault_token_renew_response_invalid",
        "vault_unseal_share_invalid",
    }
)


class VaultCeremonyBackend(Protocol):
    def initialization_status(self) -> bool: ...

    def initialize(self, *, shares: int, threshold: int) -> dict[str, object]: ...

    def submit_unseal_share(self, share: str) -> dict[str, object]: ...

    def ensure_kv_v2(self, *, root_token: str) -> None: ...

    def install_policy(self, *, root_token: str, policy_name: str, policy_hcl: str) -> None: ...

    def create_orphan_periodic_token(
        self,
        *,
        root_token: str,
        policy_name: str,
        period: str,
    ) -> str: ...

    def lookup_token(self, *, token: str) -> dict[str, object]: ...

    def renew_token(self, *, token: str) -> dict[str, object]: ...

    def revoke_self(self, *, token: str) -> None: ...


class CeremonyConsole(Protocol):
    def confirm_irreversible_initialization(self) -> bool: ...

    def copy_and_verify_share(self, *, label: str, share: str) -> bool: ...

    def clear_secret_display(self) -> None: ...


class BackendTokenWriter(Protocol):
    def preflight(self) -> None: ...

    def write_once(self, value: str) -> None: ...


class ProcessSecurityRuntime(Protocol):
    def is_linux(self) -> bool: ...

    def effective_user_id(self) -> int: ...

    def recording_environment_detected(self) -> bool: ...

    def disable_core_dumps(self) -> bool: ...

    def disable_process_dumpability(self) -> bool: ...

    def lock_process_memory(self) -> bool: ...


class CeremonyBlocked(RuntimeError):
    """Fail-closed ceremony outcome with a value-free reason."""


class LinuxProcessSecurityRuntime:
    """Linux controls that keep the secret-bearing ceremony process non-dumpable."""

    _RECORDING_ENVIRONMENT_MARKERS = (
        "CI",
        "GITHUB_ACTIONS",
        "TMUX",
        "STY",
        "ASCIINEMA_REC",
        "SCRIPT_OUTPUT",
        "CODEX_SANDBOX",
        "CODEX_CI",
    )

    def is_linux(self) -> bool:
        return sys.platform.startswith("linux")

    def effective_user_id(self) -> int:
        return os.geteuid() if hasattr(os, "geteuid") else -1

    def recording_environment_detected(self) -> bool:
        return any(str(os.environ.get(name) or "").strip() for name in self._RECORDING_ENVIRONMENT_MARKERS)

    def disable_core_dumps(self) -> bool:
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            return resource.getrlimit(resource.RLIMIT_CORE) == (0, 0)
        except (ImportError, OSError, ValueError):
            return False

    def disable_process_dumpability(self) -> bool:
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            pr_set_dumpable = 4
            return libc.prctl(pr_set_dumpable, 0, 0, 0, 0) == 0
        except (AttributeError, OSError):
            return False

    def lock_process_memory(self) -> bool:
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            mcl_current = 1
            mcl_future = 2
            return libc.mlockall(mcl_current | mcl_future) == 0
        except (AttributeError, OSError):
            return False


def enforce_secure_process_boundary(
    *,
    runtime: ProcessSecurityRuntime | None = None,
) -> None:
    """Fail before initialization unless the ceremony process is memory-safe."""

    selected = runtime or LinuxProcessSecurityRuntime()
    if not selected.is_linux():
        raise CeremonyBlocked("linux_operator_container_required")
    if selected.effective_user_id() != 0:
        raise CeremonyBlocked("root_operator_container_required")
    if selected.recording_environment_detected():
        raise CeremonyBlocked("recording_environment_detected")
    if not selected.disable_core_dumps():
        raise CeremonyBlocked("core_dump_disable_failed")
    if not selected.disable_process_dumpability():
        raise CeremonyBlocked("process_dumpability_disable_failed")
    if not selected.lock_process_memory():
        raise CeremonyBlocked("secret_process_memory_lock_failed")
    faulthandler.disable()
    gc.disable()
    os.umask(0o077)


class InteractivePaperConsole:
    """Reveal one share at a time and verify two hidden paper transcriptions."""

    def __init__(
        self,
        *,
        stdin: TextIO = sys.stdin,
        stdout: TextIO = sys.stdout,
        stderr: TextIO = sys.stderr,
        secret_reader: Callable[[str], str] | None = None,
    ) -> None:
        if not stdin.isatty() or not stdout.isatty() or not stderr.isatty():
            raise CeremonyBlocked("direct_trusted_tty_required")
        self._stdin = stdin
        self._stdout = stdout
        self._stderr = stderr
        self._secret_reader = secret_reader or (
            lambda prompt: getpass.getpass(prompt=prompt, stream=self._stderr)
        )

    def confirm_irreversible_initialization(self) -> bool:
        self._stdout.write(
            "\nThis action initializes a fresh production Vault exactly once.\n"
            "Confirm that screen/shell recording, browser automation, screen sharing,\n"
            "clipboard history, cameras, cloud terminals and synced printers are disabled.\n\n"
            f"Type exactly: {IRREVERSIBLE_CONFIRMATION_PHRASE}\n> "
        )
        self._stdout.flush()
        entered = self._stdin.readline()
        if not entered:
            return False
        return hmac.compare_digest(entered.rstrip("\r\n"), IRREVERSIBLE_CONFIRMATION_PHRASE)

    def copy_and_verify_share(self, *, label: str, share: str) -> bool:
        if label not in {"A", "B", "C"} or not isinstance(share, str) or not share:
            raise CeremonyBlocked("paper_share_display_contract_invalid")
        self.clear_secret_display()
        self._stdout.write(
            f"ENVELOPE {label} — copy this one share by hand, then seal it:\n\n"
            f"{share}\n\n"
            "Press Enter only after the paper copy is complete and the envelope is sealed."
        )
        self._stdout.flush()
        if not self._stdin.readline():
            self.clear_secret_display()
            raise CeremonyBlocked("operator_console_closed_after_initialization")
        self.clear_secret_display()

        try:
            first = self._secret_reader(f"Read envelope {label} back privately (check 1/2): ")
            self.clear_secret_display()
            second = self._secret_reader(f"Read envelope {label} back privately (check 2/2): ")
            self.clear_secret_display()
        except (EOFError, KeyboardInterrupt):
            self.clear_secret_display()
            raise CeremonyBlocked("operator_console_closed_after_initialization") from None
        return bool(
            isinstance(first, str)
            and isinstance(second, str)
            and hmac.compare_digest(first, share)
            and hmac.compare_digest(second, share)
        )

    def clear_secret_display(self) -> None:
        self._stdout.write(ANSI_CLEAR_DISPLAY_AND_SCROLLBACK)
        self._stdout.flush()


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _req, _fp, _code, _msg, _headers, _newurl):  # type: ignore[no-untyped-def]
        return None


class VaultHttpBackend:
    """Exact Vault v1 client for the operator-only internal Docker network."""

    def __init__(
        self,
        base_url: str,
        *,
        allow_test_loopback: bool = False,
        timeout_seconds: float = 10.0,
    ) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        exact_production = (
            parsed.scheme == "http"
            and parsed.hostname == "jiejing-vault"
            and parsed.port == 8200
            and parsed.path in {"", "/"}
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
        exact_test = (
            allow_test_loopback
            and parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "::1"}
            and parsed.port is not None
            and parsed.path in {"", "/"}
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
        )
        if not exact_production and not exact_test:
            raise CeremonyBlocked("vault_internal_address_invalid")
        self._base_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        self._timeout_seconds = timeout_seconds
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )

    def initialization_status(self) -> bool:
        payload = self._request("GET", "/v1/sys/init")
        initialized = payload.get("initialized")
        if not isinstance(initialized, bool):
            raise CeremonyBlocked("vault_initialization_status_invalid")
        return initialized

    def initialize(self, *, shares: int, threshold: int) -> dict[str, object]:
        return self._request(
            "POST",
            "/v1/sys/init",
            body={"secret_shares": shares, "secret_threshold": threshold},
        )

    def submit_unseal_share(self, share: str) -> dict[str, object]:
        if not isinstance(share, str) or not share:
            raise CeremonyBlocked("vault_unseal_share_invalid")
        return self._request("POST", "/v1/sys/unseal", body={"key": share})

    def ensure_kv_v2(self, *, root_token: str) -> None:
        mounts = self._request("GET", "/v1/sys/mounts", token=root_token).get("data")
        if not isinstance(mounts, dict):
            raise CeremonyBlocked("vault_mount_status_invalid")
        current = mounts.get("secret/")
        if current is None:
            self._request(
                "POST",
                "/v1/sys/mounts/secret",
                token=root_token,
                body={"type": "kv", "options": {"version": "2"}},
            )
            return
        if not isinstance(current, dict):
            raise CeremonyBlocked("vault_secret_mount_invalid")
        options = current.get("options")
        if current.get("type") != "kv" or not isinstance(options, dict) or str(options.get("version")) != "2":
            raise CeremonyBlocked("vault_secret_mount_invalid")

    def install_policy(self, *, root_token: str, policy_name: str, policy_hcl: str) -> None:
        if policy_name != POLICY_NAME or not isinstance(policy_hcl, str) or not policy_hcl.strip():
            raise CeremonyBlocked("vault_policy_contract_invalid")
        self._request(
            "PUT",
            f"/v1/sys/policies/acl/{POLICY_NAME}",
            token=root_token,
            body={"policy": policy_hcl},
        )

    def create_orphan_periodic_token(
        self,
        *,
        root_token: str,
        policy_name: str,
        period: str,
    ) -> str:
        if policy_name != POLICY_NAME or period != BACKEND_TOKEN_PERIOD:
            raise CeremonyBlocked("periodic_backend_token_request_invalid")
        payload = self._request(
            "POST",
            "/v1/auth/token/create-orphan",
            token=root_token,
            body={
                "policies": [POLICY_NAME],
                "period": BACKEND_TOKEN_PERIOD,
                "renewable": True,
                "no_default_policy": True,
            },
        )
        auth = payload.get("auth")
        token = auth.get("client_token") if isinstance(auth, dict) else None
        if not isinstance(token, str) or not token:
            raise CeremonyBlocked("periodic_backend_token_response_invalid")
        return token

    def lookup_token(self, *, token: str) -> dict[str, object]:
        try:
            payload = self._request("GET", "/v1/auth/token/lookup-self", token=token)
        except _VaultHttpStatus as exc:
            if exc.status == 403:
                return {"valid": False}
            raise CeremonyBlocked("vault_token_lookup_failed") from None
        data = payload.get("data")
        if not isinstance(data, dict):
            raise CeremonyBlocked("vault_token_lookup_invalid")
        policies = data.get("policies")
        return {
            "valid": True,
            "renewable": data.get("renewable"),
            "period": data.get("period"),
            "policies": policies,
        }

    def renew_token(self, *, token: str) -> dict[str, object]:
        payload = self._request("POST", "/v1/auth/token/renew-self", token=token, body={})
        auth = payload.get("auth")
        if not isinstance(auth, dict):
            raise CeremonyBlocked("vault_token_renew_response_invalid")
        return {
            "renewable": auth.get("renewable"),
            "lease_duration": auth.get("lease_duration"),
        }

    def revoke_self(self, *, token: str) -> None:
        self._request("POST", "/v1/auth/token/revoke-self", token=token, body={})

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if not path.startswith("/v1/") or "?" in path or "#" in path:
            raise CeremonyBlocked("vault_request_path_invalid")
        encoded = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json"}
        if encoded is not None:
            headers["Content-Type"] = "application/json"
        if token is not None:
            if not isinstance(token, str) or not token:
                raise CeremonyBlocked("vault_request_token_invalid")
            headers["X-Vault-Token"] = token
        request = urllib.request.Request(
            self._base_url + path,
            data=encoded,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    raise CeremonyBlocked("vault_response_too_large")
                if response.status == 204 or not raw:
                    return {}
                content_type = str(response.headers.get("Content-Type") or "").lower()
                if "application/json" not in content_type:
                    raise CeremonyBlocked("vault_response_content_type_invalid")
                decoded = json.loads(raw.decode("utf-8"))
                if not isinstance(decoded, dict):
                    raise CeremonyBlocked("vault_response_json_invalid")
                return decoded
        except urllib.error.HTTPError as exc:
            raise _VaultHttpStatus(exc.code) from None
        except CeremonyBlocked:
            raise
        except (urllib.error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError, OSError):
            raise CeremonyBlocked("vault_http_request_failed") from None


class _VaultHttpStatus(RuntimeError):
    def __init__(self, status: int) -> None:
        super().__init__("vault_http_status")
        self.status = status


class AtomicBackendTokenWriter:
    """Write the one permitted backend token atomically into a private directory."""

    def __init__(self, output_directory: str | os.PathLike[str]) -> None:
        self._directory = Path(output_directory)
        self._target = self._directory / "jiejing-vault-token"
        self._preflight_complete = False

    def preflight(self) -> None:
        try:
            directory_stat = self._directory.lstat()
        except OSError:
            raise CeremonyBlocked("backend_token_directory_invalid") from None
        if not stat.S_ISDIR(directory_stat.st_mode) or self._directory.is_symlink():
            raise CeremonyBlocked("backend_token_directory_invalid")
        if os.name != "nt":
            if directory_stat.st_uid != os.geteuid() or directory_stat.st_mode & 0o077:
                raise CeremonyBlocked("backend_token_directory_permissions_invalid")
        if self._target.exists() or self._target.is_symlink():
            raise CeremonyBlocked("backend_token_file_already_exists")

        probe = self._directory / f".jiejing-vault-token-preflight-{secrets.token_hex(8)}"
        descriptor: int | None = None
        try:
            descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.fsync(descriptor)
        except OSError:
            raise CeremonyBlocked("backend_token_directory_not_writable") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                raise CeremonyBlocked("backend_token_preflight_cleanup_failed") from None
        self._preflight_complete = True

    def write_once(self, value: str) -> None:
        if not self._preflight_complete:
            raise CeremonyBlocked("backend_token_preflight_required")
        if not isinstance(value, str) or not value:
            raise CeremonyBlocked("periodic_backend_token_invalid")
        if self._target.exists() or self._target.is_symlink():
            raise CeremonyBlocked("backend_token_file_already_exists")

        temporary = self._directory / f".jiejing-vault-token-{secrets.token_hex(16)}.tmp"
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            encoded = value.encode("utf-8")
            total = 0
            while total < len(encoded):
                total += os.write(descriptor, encoded[total:])
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.chmod(temporary, 0o600)
            if self._target.exists() or self._target.is_symlink():
                raise CeremonyBlocked("backend_token_file_already_exists")
            try:
                os.link(temporary, self._target)
            except FileExistsError:
                raise CeremonyBlocked("backend_token_file_already_exists") from None
            if os.name != "nt":
                directory_fd = os.open(self._directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            target_stat = self._target.lstat()
            if not stat.S_ISREG(target_stat.st_mode) or self._target.is_symlink():
                raise CeremonyBlocked("backend_token_file_invalid")
            if os.name != "nt" and (
                target_stat.st_uid != os.geteuid() or target_stat.st_mode & 0o777 != 0o600
            ):
                raise CeremonyBlocked("backend_token_file_permissions_invalid")
        except CeremonyBlocked:
            raise
        except OSError:
            raise CeremonyBlocked("backend_token_write_failed") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def run_sealed_paper_ceremony(
    *,
    backend: VaultCeremonyBackend,
    console: CeremonyConsole,
    token_writer: BackendTokenWriter,
    policy_hcl: str,
) -> dict[str, object]:
    """Run one fresh 3-share/2-threshold ceremony and return no secret values."""

    token_writer.preflight()
    if backend.initialization_status():
        raise CeremonyBlocked("vault_already_initialized")
    if not console.confirm_irreversible_initialization():
        raise CeremonyBlocked("operator_confirmation_required")

    initialized = backend.initialize(shares=KEY_SHARES, threshold=KEY_THRESHOLD)
    shares = initialized.get("keys_base64")
    root_token = initialized.get("root_token")
    if (
        not isinstance(shares, list)
        or len(shares) != KEY_SHARES
        or len(set(shares)) != KEY_SHARES
        or any(not isinstance(item, str) or not item for item in shares)
        or not isinstance(root_token, str)
        or not root_token
    ):
        raise CeremonyBlocked("vault_initialization_response_invalid")

    for label, share in zip(("A", "B", "C"), shares, strict=True):
        verified = False
        while not verified:
            try:
                verified = console.copy_and_verify_share(label=label, share=share)
            finally:
                console.clear_secret_display()

    first = backend.submit_unseal_share(shares[0])
    single_share_remains_sealed = bool(
        first.get("sealed") is True
        and first.get("progress") == 1
        and first.get("t") == KEY_THRESHOLD
        and first.get("n") == KEY_SHARES
    )
    if not single_share_remains_sealed:
        raise CeremonyBlocked("single_share_unseal_boundary_invalid")

    second = backend.submit_unseal_share(shares[1])
    two_share_unseal_verified = bool(
        second.get("sealed") is False
        and second.get("progress") == 0
        and second.get("t") == KEY_THRESHOLD
        and second.get("n") == KEY_SHARES
    )
    if not two_share_unseal_verified:
        raise CeremonyBlocked("two_share_unseal_boundary_invalid")

    backend.ensure_kv_v2(root_token=root_token)
    backend.install_policy(root_token=root_token, policy_name=POLICY_NAME, policy_hcl=policy_hcl)
    backend_token = backend.create_orphan_periodic_token(
        root_token=root_token,
        policy_name=POLICY_NAME,
        period=BACKEND_TOKEN_PERIOD,
    )
    if not isinstance(backend_token, str) or not backend_token:
        raise CeremonyBlocked("periodic_backend_token_invalid")

    lookup = backend.lookup_token(token=backend_token)
    periodic_token_renewable = lookup.get("valid") is True and lookup.get("renewable") is True
    periodic_token_positive_period = isinstance(lookup.get("period"), int) and lookup["period"] > 0
    if lookup.get("policies") != [POLICY_NAME]:
        raise CeremonyBlocked("periodic_backend_token_policy_invalid")
    if not periodic_token_renewable or not periodic_token_positive_period:
        raise CeremonyBlocked("periodic_backend_token_contract_invalid")

    renewed = backend.renew_token(token=backend_token)
    periodic_token_renew_verified = bool(
        renewed.get("renewable") is True
        and isinstance(renewed.get("lease_duration"), int)
        and renewed["lease_duration"] > 0
    )
    if not periodic_token_renew_verified:
        raise CeremonyBlocked("periodic_backend_token_renew_failed")

    token_writer.write_once(backend_token)
    backend.revoke_self(token=root_token)
    initial_root_token_revoked = backend.lookup_token(token=root_token).get("valid") is False
    if not initial_root_token_revoked:
        raise CeremonyBlocked("initial_root_token_revoke_verification_failed")
    surviving = backend.lookup_token(token=backend_token)
    orphan_token_survives_root_revocation = bool(
        surviving.get("valid") is True
        and surviving.get("renewable") is True
        and isinstance(surviving.get("period"), int)
        and surviving["period"] > 0
        and surviving.get("policies") == [POLICY_NAME]
    )
    if not orphan_token_survives_root_revocation:
        raise CeremonyBlocked("orphan_token_did_not_survive_root_revocation")

    return {
        "status": "verified",
        "contract_version": CONTRACT_VERSION,
        "key_shares": KEY_SHARES,
        "key_threshold": KEY_THRESHOLD,
        "custody_unit_count": KEY_SHARES,
        "max_shares_per_custody_unit": 1,
        "single_share_remains_sealed": single_share_remains_sealed,
        "two_share_unseal_verified": two_share_unseal_verified,
        "periodic_token_renewable": periodic_token_renewable,
        "periodic_token_positive_period": periodic_token_positive_period,
        "periodic_token_renew_verified": periodic_token_renew_verified,
        "initial_root_token_revoked": initial_root_token_revoked,
        "orphan_token_survives_root_revocation": orphan_token_survives_root_revocation,
        "secret_exposed": False,
        "real_platform_writes_enabled": False,
        "public_charging_allowed": False,
    }


def _load_exact_production_policy(path: Path = PRODUCTION_POLICY_PATH) -> str:
    try:
        source_stat = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(source_stat.st_mode) or source_stat.st_mode & 0o022:
            raise CeremonyBlocked("production_policy_contract_invalid")
        raw = path.read_bytes()
    except CeremonyBlocked:
        raise
    except OSError:
        raise CeremonyBlocked("production_policy_contract_invalid") from None
    if len(raw) > 32_768 or hashlib.sha256(raw).hexdigest() != PRODUCTION_POLICY_SHA256:
        raise CeremonyBlocked("production_policy_contract_invalid")
    try:
        return raw.decode("utf-8")
    except UnicodeError:
        raise CeremonyBlocked("production_policy_contract_invalid") from None


def _blocked_result(reason: str) -> dict[str, object]:
    return {
        "status": "blocked",
        "contract_version": CONTRACT_VERSION,
        "reason": reason if reason in PUBLIC_BLOCKER_CODES else "ceremony_execution_failed",
        "secret_exposed": False,
        "real_platform_writes_enabled": False,
        "public_charging_allowed": False,
    }


def main() -> int:
    """Production entry point. It accepts no secret-bearing command-line arguments."""

    console: InteractivePaperConsole | None = None
    try:
        enforce_secure_process_boundary()
        console = InteractivePaperConsole()
        policy_hcl = _load_exact_production_policy()
        backend = VaultHttpBackend(str(os.environ.get("VAULT_ADDR") or ""))
        writer = AtomicBackendTokenWriter(PRODUCTION_TOKEN_OUTPUT_DIRECTORY)
        result = run_sealed_paper_ceremony(
            backend=backend,
            console=console,
            token_writer=writer,
            policy_hcl=policy_hcl,
        )
        console.clear_secret_display()
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        return 0
    except CeremonyBlocked as exc:
        if console is not None:
            console.clear_secret_display()
        sys.stderr.write(json.dumps(_blocked_result(str(exc)), sort_keys=True, separators=(",", ":")) + "\n")
        sys.stderr.flush()
        return 1
    except Exception:
        if console is not None:
            console.clear_secret_display()
        sys.stderr.write(
            json.dumps(_blocked_result("ceremony_execution_failed"), sort_keys=True, separators=(",", ":")) + "\n"
        )
        sys.stderr.flush()
        return 1
    finally:
        gc.collect()


if __name__ == "__main__":
    raise SystemExit(main())

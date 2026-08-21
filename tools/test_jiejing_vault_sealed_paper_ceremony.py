#!/usr/bin/env python3
"""Public-contract test for the human-only sealed-paper Vault ceremony."""

from __future__ import annotations

import json
import io
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.jiejing_vault_sealed_paper_ceremony import (  # noqa: E402
    AtomicBackendTokenWriter,
    CeremonyBlocked,
    InteractivePaperConsole,
    VaultHttpBackend,
    enforce_secure_process_boundary,
    run_sealed_paper_ceremony,
)


SHARES = (
    "paper-share-a-secret-never-persist",
    "paper-share-b-secret-never-persist",
    "paper-share-c-secret-never-persist",
)
ROOT_TOKEN = "initial-root-token-never-display"
BACKEND_TOKEN = "periodic-backend-token-write-once"


class FakeVaultBackend:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self._progress: list[str] = []
        self._root_revoked = False

    def initialization_status(self) -> bool:
        self.calls.append("initialization_status")
        return False

    def initialize(self, *, shares: int, threshold: int) -> dict[str, object]:
        self.calls.append(("initialize", shares, threshold))
        return {"keys_base64": list(SHARES), "root_token": ROOT_TOKEN}

    def submit_unseal_share(self, share: str) -> dict[str, object]:
        self.calls.append(("submit_unseal_share", share))
        self._progress.append(share)
        return {
            "sealed": len(set(self._progress)) < 2,
            "progress": len(set(self._progress)) if len(set(self._progress)) < 2 else 0,
            "t": 2,
            "n": 3,
        }

    def ensure_kv_v2(self, *, root_token: str) -> None:
        self.calls.append(("ensure_kv_v2", root_token))

    def install_policy(self, *, root_token: str, policy_name: str, policy_hcl: str) -> None:
        self.calls.append(("install_policy", root_token, policy_name, policy_hcl))

    def create_orphan_periodic_token(
        self,
        *,
        root_token: str,
        policy_name: str,
        period: str,
    ) -> str:
        self.calls.append(("create_orphan_periodic_token", root_token, policy_name, period))
        return BACKEND_TOKEN

    def lookup_token(self, *, token: str) -> dict[str, object]:
        self.calls.append(("lookup_token", token))
        if token == ROOT_TOKEN and self._root_revoked:
            return {"valid": False}
        return {
            "valid": True,
            "renewable": token == BACKEND_TOKEN,
            "period": 2_592_000 if token == BACKEND_TOKEN else 0,
            "policies": ["jiejing-production"] if token == BACKEND_TOKEN else ["root"],
        }

    def renew_token(self, *, token: str) -> dict[str, object]:
        self.calls.append(("renew_token", token))
        return {"renewable": True, "lease_duration": 2_592_000}

    def revoke_self(self, *, token: str) -> None:
        self.calls.append(("revoke_self", token))
        if token == ROOT_TOKEN:
            self._root_revoked = True


class FakeOperatorConsole:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def confirm_irreversible_initialization(self) -> bool:
        self.events.append(("confirm", "value-free"))
        return True

    def copy_and_verify_share(self, *, label: str, share: str) -> bool:
        self.events.append((f"share-{label}", share))
        return True

    def clear_secret_display(self) -> None:
        self.events.append(("clear", "value-free"))


class OneMismatchThenVerifiedConsole(FakeOperatorConsole):
    def __init__(self) -> None:
        super().__init__()
        self.attempts: dict[str, int] = {}

    def copy_and_verify_share(self, *, label: str, share: str) -> bool:
        self.events.append((f"share-{label}", share))
        self.attempts[label] = self.attempts.get(label, 0) + 1
        return label != "A" or self.attempts[label] > 1


class FakeTokenWriter:
    def __init__(self) -> None:
        self.values: list[str] = []

    def preflight(self) -> None:
        return None

    def write_once(self, value: str) -> None:
        self.values.append(value)


class FakeVaultApiHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []
    unseal_progress = 0
    root_revoked = False

    def log_message(self, _format: str, *_args: object) -> None:
        return None

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8")) if body else {}

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _record(self, body: dict[str, object]) -> None:
        self.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "token": self.headers.get("X-Vault-Token"),
                "body": body,
            }
        )

    def do_GET(self) -> None:  # noqa: N802
        self._record({})
        if self.path == "/v1/sys/init":
            self._send_json(200, {"initialized": False})
        elif self.path == "/v1/sys/mounts":
            self._send_json(200, {"data": {"cubbyhole/": {"type": "cubbyhole"}}})
        elif self.path == "/v1/auth/token/lookup-self":
            token = self.headers.get("X-Vault-Token")
            if token == ROOT_TOKEN and self.root_revoked:
                self._send_json(403, {"errors": ["permission denied"]})
            elif token == BACKEND_TOKEN:
                self._send_json(
                    200,
                    {
                        "data": {
                            "renewable": True,
                            "period": 2_592_000,
                            "policies": ["jiejing-production"],
                        }
                    },
                )
            else:
                self._send_json(200, {"data": {"renewable": False, "period": 0, "policies": ["root"]}})
        else:
            self._send_json(404, {"errors": ["not found"]})

    def do_POST(self) -> None:  # noqa: N802
        body = self._read_json()
        self._record(body)
        if self.path == "/v1/sys/init":
            self._send_json(200, {"keys_base64": list(SHARES), "root_token": ROOT_TOKEN})
        elif self.path == "/v1/sys/unseal":
            self.__class__.unseal_progress += 1
            progress = self.unseal_progress
            self._send_json(
                200,
                {"sealed": progress < 2, "progress": progress if progress < 2 else 0, "t": 2, "n": 3},
            )
        elif self.path == "/v1/sys/mounts/secret":
            self._send_json(204, {})
        elif self.path == "/v1/sys/policies/acl/jiejing-production":
            self._send_json(204, {})
        elif self.path == "/v1/auth/token/create-orphan":
            self._send_json(200, {"auth": {"client_token": BACKEND_TOKEN}})
        elif self.path == "/v1/auth/token/renew-self":
            self._send_json(200, {"auth": {"renewable": True, "lease_duration": 2_592_000}})
        elif self.path == "/v1/auth/token/revoke-self":
            self.__class__.root_revoked = True
            self._send_json(204, {})
        else:
            self._send_json(404, {"errors": ["not found"]})

    do_PUT = do_POST


def exercise_http_backend() -> str | None:
    FakeVaultApiHandler.requests = []
    FakeVaultApiHandler.unseal_progress = 0
    FakeVaultApiHandler.root_revoked = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeVaultApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        backend = VaultHttpBackend(
            f"http://127.0.0.1:{server.server_port}",
            allow_test_loopback=True,
        )
        if backend.initialization_status() is not False:
            return "HTTP backend initialization status was not exact"
        if backend.initialize(shares=3, threshold=2).get("root_token") != ROOT_TOKEN:
            return "HTTP backend initialization response was not parsed"
        if backend.submit_unseal_share(SHARES[0]).get("progress") != 1:
            return "HTTP backend first unseal response was not parsed"
        backend.ensure_kv_v2(root_token=ROOT_TOKEN)
        backend.install_policy(
            root_token=ROOT_TOKEN,
            policy_name="jiejing-production",
            policy_hcl='path "secret/data/jiejing-production/*" { capabilities = ["read"] }',
        )
        token = backend.create_orphan_periodic_token(
            root_token=ROOT_TOKEN,
            policy_name="jiejing-production",
            period="720h",
        )
        if token != BACKEND_TOKEN:
            return "HTTP backend did not extract the periodic token"
        if backend.lookup_token(token=BACKEND_TOKEN).get("period") != 2_592_000:
            return "HTTP backend did not parse periodic token lookup"
        if backend.renew_token(token=BACKEND_TOKEN).get("lease_duration") != 2_592_000:
            return "HTTP backend did not parse token renewal"
        backend.revoke_self(token=ROOT_TOKEN)
        if backend.lookup_token(token=ROOT_TOKEN) != {"valid": False}:
            return "HTTP backend did not treat revoked-root 403 as invalid"

        requests = FakeVaultApiHandler.requests
        init_request = next(item for item in requests if item["path"] == "/v1/sys/init" and item["method"] == "POST")
        if init_request["body"] != {"secret_shares": 3, "secret_threshold": 2}:
            return f"HTTP init geometry was not exact: {init_request}"
        unseal_request = next(item for item in requests if item["path"] == "/v1/sys/unseal")
        if unseal_request["body"] != {"key": SHARES[0]} or unseal_request["token"] is not None:
            return "unseal share was not confined to the JSON body"
        orphan = next(item for item in requests if item["path"] == "/v1/auth/token/create-orphan")
        if orphan["body"] != {
            "policies": ["jiejing-production"],
            "period": "720h",
            "renewable": True,
            "no_default_policy": True,
        }:
            return f"backend token was not exact orphan/periodic: {orphan}"
        if any(SHARES[0] in str(item["path"]) or ROOT_TOKEN in str(item["path"]) for item in requests):
            return "share or root token leaked into a request URL"
        return None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def exercise_atomic_token_writer() -> str | None:
    with tempfile.TemporaryDirectory(prefix="jiejing-paper-token-") as temp_root:
        output_dir = Path(temp_root) / "token-output"
        output_dir.mkdir(mode=0o700)
        if os.name != "nt":
            output_dir.chmod(0o700)
        writer = AtomicBackendTokenWriter(output_dir)
        writer.preflight()
        writer.write_once(BACKEND_TOKEN)
        token_path = output_dir / "jiejing-vault-token"
        if token_path.read_text(encoding="utf-8") != BACKEND_TOKEN:
            return "atomic writer did not persist the exact backend token"
        if os.name != "nt" and (token_path.stat().st_mode & 0o777) != 0o600:
            return f"backend token mode is not 0600: {oct(token_path.stat().st_mode & 0o777)}"
        try:
            writer.write_once("replacement-must-not-overwrite")
        except CeremonyBlocked as exc:
            if str(exc) != "backend_token_file_already_exists":
                return f"second write failed with the wrong value-free code: {exc}"
        else:
            return "atomic writer overwrote an existing production backend token"
        if token_path.read_text(encoding="utf-8") != BACKEND_TOKEN:
            return "second write mutated the original backend token"

        token_path.unlink()
        unsafe_dir = Path(temp_root) / "unsafe-output"
        unsafe_dir.mkdir(mode=0o777)
        if os.name != "nt":
            unsafe_dir.chmod(0o777)
            try:
                AtomicBackendTokenWriter(unsafe_dir).preflight()
            except CeremonyBlocked as exc:
                if str(exc) != "backend_token_directory_permissions_invalid":
                    return f"unsafe directory failed with the wrong code: {exc}"
            else:
                return "group/world-accessible token directory passed preflight"
    return None


class FakeTty(io.StringIO):
    def isatty(self) -> bool:
        return True


def exercise_interactive_console() -> str | None:
    confirmation_phrase = "INITIALIZE JIEJING PRODUCTION VAULT WITH 3 SHARES AND THRESHOLD 2"
    stdin = FakeTty(confirmation_phrase + "\n\n")
    stdout = FakeTty()
    stderr = FakeTty()
    secret_answers = iter((SHARES[0], SHARES[0]))
    console = InteractivePaperConsole(
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        secret_reader=lambda _prompt: next(secret_answers),
    )
    if not console.confirm_irreversible_initialization():
        return "exact irreversible ceremony phrase was rejected"
    if not console.copy_and_verify_share(label="A", share=SHARES[0]):
        return "double transcription of share A was rejected"
    console.clear_secret_display()
    rendered = stdout.getvalue()
    if rendered.count(SHARES[0]) != 1:
        return "share A was displayed more than once or not displayed"
    if "\x1b[3J\x1b[2J\x1b[H" not in rendered:
        return "terminal display and scrollback were not cleared"
    if ROOT_TOKEN in rendered or BACKEND_TOKEN in rendered:
        return "console displayed a token that must remain process-only"

    wrong_answers = iter((SHARES[1], "one-character-mismatch"))
    wrong = InteractivePaperConsole(
        stdin=FakeTty("\n"),
        stdout=FakeTty(),
        stderr=FakeTty(),
        secret_reader=lambda _prompt: next(wrong_answers),
    )
    if wrong.copy_and_verify_share(label="B", share=SHARES[1]):
        return "mismatched paper transcription was accepted"
    closed_stdout = FakeTty()
    closed = InteractivePaperConsole(
        stdin=FakeTty(""),
        stdout=closed_stdout,
        stderr=FakeTty(),
        secret_reader=lambda _prompt: "must-not-be-read",
    )
    try:
        closed.copy_and_verify_share(label="C", share=SHARES[2])
    except CeremonyBlocked as exc:
        if str(exc) != "operator_console_closed_after_initialization":
            return f"closed operator console failed with the wrong value-free code: {exc}"
    else:
        return "closed operator console did not fail closed after initialization"
    if not closed_stdout.getvalue().endswith("\x1b[3J\x1b[2J\x1b[H"):
        return "closed operator console did not clear the displayed recovery share"
    try:
        InteractivePaperConsole(
            stdin=io.StringIO(),
            stdout=FakeTty(),
            stderr=FakeTty(),
            secret_reader=lambda _prompt: "",
        )
    except CeremonyBlocked as exc:
        if str(exc) != "direct_trusted_tty_required":
            return f"non-TTY console failed with the wrong code: {exc}"
    else:
        return "non-TTY ceremony console was accepted"
    return None


class FakeSecurityRuntime:
    def __init__(
        self,
        *,
        linux: bool = True,
        euid: int = 0,
        recording_marker: bool = False,
        memory_lock: bool = True,
    ) -> None:
        self.linux = linux
        self.euid = euid
        self.recording_marker = recording_marker
        self.memory_lock = memory_lock
        self.calls: list[str] = []

    def is_linux(self) -> bool:
        return self.linux

    def effective_user_id(self) -> int:
        return self.euid

    def recording_environment_detected(self) -> bool:
        return self.recording_marker

    def disable_core_dumps(self) -> bool:
        self.calls.append("disable_core_dumps")
        return True

    def disable_process_dumpability(self) -> bool:
        self.calls.append("disable_process_dumpability")
        return True

    def lock_process_memory(self) -> bool:
        self.calls.append("lock_process_memory")
        return self.memory_lock


def exercise_secure_process_boundary() -> str | None:
    runtime = FakeSecurityRuntime()
    enforce_secure_process_boundary(runtime=runtime)
    if runtime.calls != ["disable_core_dumps", "disable_process_dumpability", "lock_process_memory"]:
        return f"secure process controls were not applied in order: {runtime.calls}"

    for label, candidate, expected in (
        ("non-linux", FakeSecurityRuntime(linux=False), "linux_operator_container_required"),
        ("non-root", FakeSecurityRuntime(euid=1000), "root_operator_container_required"),
        (
            "recording",
            FakeSecurityRuntime(recording_marker=True),
            "recording_environment_detected",
        ),
        ("unlocked-memory", FakeSecurityRuntime(memory_lock=False), "secret_process_memory_lock_failed"),
    ):
        try:
            enforce_secure_process_boundary(runtime=candidate)
        except CeremonyBlocked as exc:
            if str(exc) != expected:
                return f"{label} boundary failed with wrong code: {exc}"
        else:
            return f"{label} boundary was accepted"
    return None


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    security_error = exercise_secure_process_boundary()
    if security_error:
        return fail(security_error)

    console_error = exercise_interactive_console()
    if console_error:
        return fail(console_error)

    writer_error = exercise_atomic_token_writer()
    if writer_error:
        return fail(writer_error)

    http_error = exercise_http_backend()
    if http_error:
        return fail(http_error)

    backend = FakeVaultBackend()
    console = FakeOperatorConsole()
    writer = FakeTokenWriter()
    result = run_sealed_paper_ceremony(
        backend=backend,
        console=console,
        token_writer=writer,
        policy_hcl='path "secret/data/jiejing-production/*" { capabilities = ["read"] }',
    )

    if result.get("status") != "verified":
        return fail(f"valid sealed-paper ceremony did not verify: {result}")
    expected_public = {
        "status": "verified",
        "contract_version": "jiejing_vault_sealed_paper_ceremony_v1",
        "key_shares": 3,
        "key_threshold": 2,
        "custody_unit_count": 3,
        "max_shares_per_custody_unit": 1,
        "single_share_remains_sealed": True,
        "two_share_unseal_verified": True,
        "periodic_token_renewable": True,
        "periodic_token_positive_period": True,
        "periodic_token_renew_verified": True,
        "initial_root_token_revoked": True,
        "orphan_token_survives_root_revocation": True,
        "secret_exposed": False,
        "real_platform_writes_enabled": False,
        "public_charging_allowed": False,
    }
    if result != expected_public:
        return fail(f"ceremony evidence is not exact/value-free: {result}")
    serialized = json.dumps(result, sort_keys=True)
    if any(secret in serialized for secret in (*SHARES, ROOT_TOKEN, BACKEND_TOKEN)):
        return fail("ceremony evidence exposed a share or token")
    if writer.values != [BACKEND_TOKEN]:
        return fail("scoped backend token was not written exactly once")

    share_events = [event for event in console.events if event[0].startswith("share-")]
    if share_events != [("share-A", SHARES[0]), ("share-B", SHARES[1]), ("share-C", SHARES[2])]:
        return fail(f"shares were not revealed one at a time in A/B/C order: {share_events}")
    for index, event in enumerate(console.events):
        if event[0].startswith("share-"):
            if index + 1 >= len(console.events) or console.events[index + 1][0] != "clear":
                return fail(f"share display was not immediately cleared: {console.events}")

    if ("create_orphan_periodic_token", ROOT_TOKEN, "jiejing-production", "720h") not in backend.calls:
        return fail("backend token was not created as an orphan periodic token")
    if backend.calls[-2:] != [("lookup_token", ROOT_TOKEN), ("lookup_token", BACKEND_TOKEN)]:
        return fail(f"root revocation and orphan survival were not finally verified: {backend.calls}")

    retry_backend = FakeVaultBackend()
    retry_console = OneMismatchThenVerifiedConsole()
    retry_writer = FakeTokenWriter()
    retry_result = run_sealed_paper_ceremony(
        backend=retry_backend,
        console=retry_console,
        token_writer=retry_writer,
        policy_hcl='path "secret/data/jiejing-production/*" { capabilities = ["read"] }',
    )
    if retry_result.get("status") != "verified" or retry_console.attempts != {"A": 2, "B": 1, "C": 1}:
        return fail(f"a transcription mismatch must retry the same share without exiting: {retry_console.attempts}")

    print("PASS jiejing_vault_sealed_paper_ceremony")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

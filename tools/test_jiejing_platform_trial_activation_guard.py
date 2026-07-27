#!/usr/bin/env python3
"""Regression for platform-funded trial activation without blocking BYOK accounts."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-platform-trial-activation-guard-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    withheld = _run_scenario("verifier-missing", verifier_configured=False)
    if withheld.get("platform_trial_allowed") is not False:
        return fail(f"registration without a challenge must withhold Jiejing-funded trial: {withheld}")
    if withheld.get("status") != "verification_required":
        return fail(f"missing challenge should have an explicit merchant-safe status: {withheld}")
    if withheld.get("merchant_byok_unaffected") is not True:
        return fail(f"withheld Jiejing trial must not block merchant BYOK: {withheld}")
    if withheld.get("welcome_media_points_granted") != 0:
        return fail(f"withheld trial must not grant provider-funded media points: {withheld}")

    activated = _run_scenario("server-verified", verifier_configured=True)
    challenge_config = activated.get("challenge_config") if isinstance(activated.get("challenge_config"), dict) else {}
    if challenge_config.get("required") is not True or challenge_config.get("verification_ready") is not True:
        return fail(f"public challenge config should expose a usable non-secret contract: {challenge_config}")
    if challenge_config.get("site_key") != "test-site-key" or challenge_config.get("action") != "jiejing_register":
        return fail(f"public challenge config should expose only the client contract: {challenge_config}")
    missing = activated.get("missing") if isinstance(activated.get("missing"), dict) else {}
    invalid = activated.get("invalid") if isinstance(activated.get("invalid"), dict) else {}
    wrong_action = activated.get("wrong_action") if isinstance(activated.get("wrong_action"), dict) else {}
    wrong_hostname = activated.get("wrong_hostname") if isinstance(activated.get("wrong_hostname"), dict) else {}
    replay = activated.get("replay") if isinstance(activated.get("replay"), dict) else {}
    first = activated.get("first") if isinstance(activated.get("first"), dict) else {}
    second = activated.get("second") if isinstance(activated.get("second"), dict) else {}
    third = activated.get("third") if isinstance(activated.get("third"), dict) else {}
    if first.get("status") != "active" or first.get("welcome_media_points_granted") != 300:
        return fail(f"first server-verified registration should receive the welcome trial: {first}")
    if first.get("decision_reason") != "server_verified_challenge_and_daily_budget_passed":
        return fail(f"successful activation must prove server verification, not an environment flag: {first}")
    if missing.get("status") != "verification_required" or missing.get("platform_trial_allowed") is not False:
        return fail(f"a request without a token must not activate platform-funded usage: {missing}")
    if invalid.get("status") != "verification_required" or invalid.get("platform_trial_allowed") is not False:
        return fail(f"an invalid provider token must not activate platform-funded usage: {invalid}")
    if wrong_action.get("status") != "verification_required" or wrong_action.get("platform_trial_allowed") is not False:
        return fail(f"a token for another action must not activate platform-funded usage: {wrong_action}")
    if wrong_hostname.get("status") != "verification_required" or wrong_hostname.get("platform_trial_allowed") is not False:
        return fail(f"a token for another hostname must not activate platform-funded usage: {wrong_hostname}")
    if replay.get("status") != "verification_required" or replay.get("platform_trial_allowed") is not False:
        return fail(f"a replayed single-use token must not activate platform-funded usage: {replay}")
    if second.get("status") != "activation_budget_exhausted" or second.get("platform_trial_allowed") is not False:
        return fail(f"same-IP registration beyond the daily budget must be withheld: {second}")
    if second.get("merchant_byok_unaffected") is not True or second.get("welcome_media_points_granted") != 0:
        return fail(f"budget exhaustion must affect only Jiejing-funded usage: {second}")
    if third.get("status") != "active" or third.get("platform_trial_allowed") is not True:
        return fail(f"a different client IP should retain its own daily trial budget: {third}")

    serialized = json.dumps({"withheld": withheld, "activated": activated}, ensure_ascii=False).lower()
    for forbidden in (
        "203.0.113.50",
        "203.0.113.51",
        "valid-first",
        "test-secret",
        "api_key",
        "client_secret",
        "challenge_token",
        "secret_key",
    ):
        if forbidden in serialized:
            return fail(f"trial activation response leaked forbidden data: {forbidden}")

    print("PASS jiejing_platform_trial_activation_guard")
    return 0


def _run_scenario(name: str, *, verifier_configured: bool) -> dict[str, Any]:
    scenario_root = OUT / name
    scenario_root.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    verifier, verifier_thread = _start_fake_verifier()
    env = dict(os.environ)
    env.update(
        {
            "JIEJING_SAAS_ENV": "test",
            "JIEJING_PLATFORM_TRIAL_ACTIVATION_REQUIRED": "true",
            "JIEJING_TURNSTILE_OR_CHALLENGE_ENABLED": "true",
            "JIEJING_TURNSTILE_SITE_KEY": "test-site-key",
            "JIEJING_TURNSTILE_SECRET_KEY": "test-secret" if verifier_configured else "",
            "JIEJING_TURNSTILE_ALLOWED_HOSTNAMES": "app.jiejing.shop",
            "JIEJING_TURNSTILE_SITEVERIFY_URL": f"http://127.0.0.1:{verifier.server_port}/siteverify",
            "JIEJING_PLATFORM_TRIAL_ACTIVATION_MAX_PER_IP_PER_DAY": "1",
            # The rejected second request must not consume the remaining global
            # activation slot needed by the third request from another IP.
            "JIEJING_PLATFORM_TRIAL_ACTIVATION_MAX_GLOBAL_PER_DAY": "2",
            "JIEJING_TRUSTED_PROXY_CIDRS": "127.0.0.0/8,::1/128",
            "JIEJING_AUTH_REGISTER_RATE_LIMIT_MAX_PER_IP": "10",
            "JIEJING_AUTH_REGISTER_RATE_LIMIT_MAX_GLOBAL": "100",
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(scenario_root / "saas.sqlite"),
            "--runtime-db",
            str(scenario_root / "runtime.sqlite"),
            "--output-root",
            str(scenario_root),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        if _wait_for_health(base_url):
            stderr = process.stderr.read() if process.stderr else ""
            raise RuntimeError(f"backend did not become healthy: {stderr[-800:]}")

        challenge_config = _fetch_json(f"{base_url}/auth/challenge-config", ip="203.0.113.40").get(
            "registration_challenge", {}
        )
        if not verifier_configured:
            registered = _register(base_url, "missing@example.test", ip="203.0.113.40", challenge_token="valid-missing")
            activation = _activation(registered)
            media = registered.get("media_welcome") if isinstance(registered.get("media_welcome"), dict) else {}
            if media.get("status") != "platform_trial_activation_required":
                raise RuntimeError(f"withheld registration should return a safe media status: {media}")
            store = _post_json(
                f"{base_url}/stores",
                {"platform": "ebay", "store_name": "Trial Guard Store", "marketplace": "EBAY_US", "stage": "store_opened"},
                token=str(registered.get("token") or ""),
                ip="203.0.113.40",
            ).get("store", {})
            settings = _fetch_json(
                f"{base_url}/stores/{store.get('store_id')}/model/settings",
                token=str(registered.get("token") or ""),
                ip="203.0.113.40",
            ).get("model_settings", {})
            quota = settings.get("platform_trial_quota") if isinstance(settings.get("platform_trial_quota"), dict) else {}
            if quota.get("allowed") is not False or quota.get("activation_status") != "verification_required":
                raise RuntimeError(f"platform-managed model quota must honor trial activation: {quota}")
            return {**activation, "challenge_config": challenge_config}

        missing_record = _register(base_url, "missing@example.test", ip="203.0.113.40")
        invalid_record = _register(base_url, "invalid@example.test", ip="203.0.113.41", challenge_token="invalid-token")
        wrong_action_record = _register(
            base_url,
            "wrong-action@example.test",
            ip="203.0.113.42",
            challenge_token="valid-wrong-action",
        )
        wrong_hostname_record = _register(
            base_url,
            "wrong-hostname@example.test",
            ip="203.0.113.43",
            challenge_token="valid-wrong-hostname",
        )
        first_record = _register(base_url, "first@example.test", ip="203.0.113.50", challenge_token="valid-first")
        replay_record = _register(base_url, "replay@example.test", ip="203.0.113.52", challenge_token="valid-first")
        second_record = _register(base_url, "second@example.test", ip="203.0.113.50", challenge_token="valid-second")
        third_record = _register(base_url, "third@example.test", ip="203.0.113.51", challenge_token="valid-third")
        return {
            "challenge_config": challenge_config,
            "missing": _activation(missing_record),
            "invalid": _activation(invalid_record),
            "wrong_action": _activation(wrong_action_record),
            "wrong_hostname": _activation(wrong_hostname_record),
            "first": _activation(first_record),
            "replay": _activation(replay_record),
            "second": _activation(second_record),
            "third": _activation(third_record),
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        verifier.shutdown()
        verifier.server_close()
        verifier_thread.join(timeout=5)


def _activation(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("platform_trial_activation")
    return value if isinstance(value, dict) else {}


def _register(base_url: str, email: str, *, ip: str, challenge_token: str = "") -> dict[str, Any]:
    body: dict[str, Any] = {
        "email": email,
        "password": "Trial-activation-2026",
        "company_name": "Trial Activation Guard",
    }
    if challenge_token:
        body["trial_activation_challenge"] = {
            "provider": "turnstile",
            "token": challenge_token,
            "action": "jiejing_register",
        }
    return _post_json(
        f"{base_url}/auth/register",
        body,
        ip=ip,
    )


class _FakeVerifierHandler(BaseHTTPRequestHandler):
    used_tokens: set[str] = set()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        params = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        secret = str((params.get("secret") or [""])[0])
        token = str((params.get("response") or [""])[0])
        valid = secret == "test-secret" and token.startswith("valid-") and token not in self.used_tokens
        if valid:
            self.used_tokens.add(token)
        payload = {
            "success": valid,
            "hostname": (
                "another.example.test"
                if token == "valid-wrong-hostname"
                else "app.jiejing.shop" if valid else ""
            ),
            "action": "another_action" if token == "valid-wrong-action" else "jiejing_register" if valid else "",
            "error-codes": [] if valid else ["invalid-input-response"],
        }
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        return


def _start_fake_verifier() -> tuple[ThreadingHTTPServer, threading.Thread]:
    _FakeVerifierHandler.used_tokens = set()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeVerifierHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _post_json(url: str, body: dict[str, Any], *, token: str = "", ip: str = "") -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "User-Agent": "JiejingTrialActivationGuard/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if ip:
        headers["X-Forwarded-For"] = ip
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_json(url: str, *, token: str = "", ip: str = "") -> dict[str, Any]:
    headers = {"User-Agent": "JiejingTrialActivationGuard/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if ip:
        headers["X-Forwarded-For"] = ip
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for_health(base_url: str) -> int:
    for _ in range(80):
        try:
            if _fetch_json(f"{base_url}/health").get("status") == "ok":
                return 0
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(0.1)
    return 1


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    raise SystemExit(main())

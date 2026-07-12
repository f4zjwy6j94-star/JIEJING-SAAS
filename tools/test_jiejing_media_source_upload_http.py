#!/usr/bin/env python3
"""HTTP regression for authenticated upload and short-lived provider fetch."""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def request_json(url: str, *, method: str = "GET", token: str = "", body=None, headers=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request_headers = {"accept": "application/json", **(headers or {})}
    if data is not None:
        request_headers.setdefault("content-type", "application/json")
    if token:
        request_headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def request_error(request: urllib.request.Request) -> tuple[int, str]:
    try:
        urllib.request.urlopen(request, timeout=20)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    raise AssertionError("request unexpectedly succeeded")


def main() -> None:
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="jiejing-media-upload-http-") as temp:
        root = Path(temp)
        env = {
            **os.environ,
            "JIEJING_SAAS_ENV": "test",
            "JIEJING_SAAS_SESSION_SECRET": "media-source-upload-http-test-secret",
            "JIEJING_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}",
        }
        process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
                "serve",
                "--db",
                str(root / "saas.sqlite"),
                "--runtime-db",
                str(root / "runtime.sqlite"),
                "--output-root",
                str(root / "output"),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(80):
                try:
                    request_json(f"{base}/health")
                    break
                except Exception:
                    time.sleep(0.1)
            else:
                raise AssertionError("backend did not become healthy")

            _, registered = request_json(
                f"{base}/auth/register",
                method="POST",
                body={"email": "media-upload@example.test", "password": "local-test-password", "company_name": "Media Upload Test"},
            )
            token = registered["token"]
            _, created = request_json(
                f"{base}/stores",
                method="POST",
                token=token,
                body={"platform": "ebay", "store_name": "Media Upload Store", "marketplace": "EBAY_US"},
            )
            store_id = created["store"]["store_id"]
            png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
            upload = urllib.request.Request(
                f"{base}/stores/{store_id}/media-source-assets",
                data=png,
                method="POST",
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "image/png",
                    "x-jiejing-file-name": urllib.parse.quote("merchant-source.png"),
                    "accept": "application/json",
                },
            )
            with urllib.request.urlopen(upload, timeout=20) as response:
                assert response.status == 201
                payload = json.loads(response.read().decode("utf-8"))
            asset = payload["media_source_asset"]
            assert asset["tenant_scoped"] is True
            assert asset["signed_url_required"] is True
            assert asset["secret_exposed"] is False
            with urllib.request.urlopen(asset["source_url"], timeout=20) as response:
                assert response.headers.get_content_type() == "image/png"
                assert response.read() == png

            parsed = urllib.parse.urlparse(asset["source_url"])
            bad_query = urllib.parse.parse_qs(parsed.query)
            bad_query["signature"] = ["wrong"]
            bad_url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(bad_query, doseq=True)))
            status, _ = request_error(urllib.request.Request(bad_url))
            assert status == 403

            no_auth = urllib.request.Request(
                f"{base}/stores/{store_id}/media-source-assets",
                data=png,
                method="POST",
                headers={"content-type": "image/png"},
            )
            status, _ = request_error(no_auth)
            assert status == 401

            unsafe = urllib.request.Request(
                f"{base}/stores/{store_id}/media-source-assets",
                data=b"<svg><script>alert(1)</script></svg>",
                method="POST",
                headers={"authorization": f"Bearer {token}", "content-type": "image/svg+xml"},
            )
            status, _ = request_error(unsafe)
            assert status == 400
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    print("PASS jiejing_media_source_upload_http")


if __name__ == "__main__":
    main()

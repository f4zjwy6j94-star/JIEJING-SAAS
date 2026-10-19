#!/usr/bin/env python3
"""HTTP regression for authenticated upload and short-lived provider fetch."""

from __future__ import annotations

import base64
from contextlib import closing
import json
import os
import socket
import sqlite3
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
            upload_id = "http-recovery-upload-0001"
            upload = urllib.request.Request(
                f"{base}/stores/{store_id}/media-source-assets",
                data=png,
                method="POST",
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "image/png",
                    "x-jiejing-file-name": urllib.parse.quote("merchant-source.png"),
                    "x-jiejing-upload-id": upload_id,
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
            assert payload["upload_id"] == upload_id
            recovery_url = f"{base}/stores/{store_id}/media-source-uploads/{upload_id}"
            source_root = root / "output" / "private-media-source-assets"
            before_recovery = {p: p.read_bytes() for p in source_root.glob("*/*") if p.is_file()}
            # The POST response can be lost; querying this exact attempt must not write another asset.
            status, recovered = request_json(recovery_url, token=token)
            assert status == 200 and recovered["upload_status"] == "completed"
            assert recovered["upload_id"] == upload_id
            assert recovered["media_source_asset"]["asset_id"] == asset["asset_id"]
            assert recovered["provider_reference_ready"] is True
            assert {p: p.read_bytes() for p in source_root.glob("*/*") if p.is_file()} == before_recovery
            # Existing generated jobs can restore their original after tab-local
            # upload selectors are lost. Fixture rows contain no live provider job.
            with closing(sqlite3.connect(root / "saas.sqlite")) as db, db:
                actor = db.execute('select u.user_id,t.company_id from users u join team_members t on u.user_id=t.user_id where u.email=?', ('media-upload@example.test',)).fetchone()
                # Company membership is authoritative; user rows do not own companies.
                if actor is None: raise AssertionError('fixture actor missing')
                job_payload = {"job_spec": {"inputs": {"product_facts": {"source_asset_id": asset['asset_id'], "product":"fixture box"}}}}
                db.execute('''insert into media_asset_jobs
                    (media_job_id,company_id,store_id,task_id,provider_job_key,status,idempotency_key,retry_count,created_by,created_at,updated_at,media_job_json)
                    values (?,?,?,?,?,?,?,?,?,?,?,?)''', ('media_job_http_recovery',actor[1],store_id,'fixture-task','media.asset_generation','waiting_review','fixture-job-source',0,actor[0],'2026-10-13','2026-10-13',json.dumps(job_payload)))
            job_recovery_url=f'{base}/stores/{store_id}/media-asset-jobs/media_job_http_recovery/source'
            _, by_job=request_json(job_recovery_url,token=token)
            assert by_job['upload_id']==upload_id and by_job['media_job_id']=='media_job_http_recovery'
            assert by_job['media_source_asset']['asset_id']==asset['asset_id']
            assert {p:p.read_bytes() for p in source_root.glob('*/*') if p.is_file()}==before_recovery
            with urllib.request.urlopen(upload, timeout=20) as response:
                duplicate = json.loads(response.read().decode("utf-8"))
            assert duplicate["media_source_asset"]["asset_id"] == asset["asset_id"]
            conflict = urllib.request.Request(upload.full_url, data=png + b"changed", method="POST", headers=dict(upload.headers))
            status, conflict_body = request_error(conflict)
            assert status == 409 and json.loads(conflict_body)["code"] == "upload_id_conflict"
            assert {p: p.read_bytes() for p in source_root.glob("*/*") if p.is_file()} == before_recovery
            status, _ = request_error(urllib.request.Request(recovery_url))
            assert status == 401
            status, missing_body = request_error(urllib.request.Request(
                f"{base}/stores/{store_id}/media-source-uploads/unknown-http-upload-0001",
                headers={"authorization": f"Bearer {token}"}))
            assert status == 404 and json.loads(missing_body)["code"] == "upload_not_found"
            _, other = request_json(f"{base}/auth/register", method="POST", body={
                "email": "other-media-upload@example.test", "password": "local-test-password", "company_name": "Other Upload Test"})
            status, other_body = request_error(urllib.request.Request(recovery_url,
                headers={"authorization": f"Bearer {other['token']}"}))
            assert status == 404 and asset["asset_id"] not in other_body and "signature=" not in other_body
            status, other_job_body=request_error(urllib.request.Request(job_recovery_url,headers={'authorization':f"Bearer {other['token']}"}))
            assert status==404 and 'signature=' not in other_job_body
            # A job in the same company/store but created by another user is
            # still not owned by this actor. Never expose its original.
            with closing(sqlite3.connect(root / "saas.sqlite")) as db, db:
                other_actor = db.execute('select user_id from users where email=?', ('other-media-upload@example.test',)).fetchone()[0]
                db.execute('update media_asset_jobs set created_by=? where media_job_id=?',
                           (other_actor, 'media_job_http_recovery'))
            status, owner_mismatch = request_error(urllib.request.Request(job_recovery_url,
                headers={"authorization": f"Bearer {token}"}))
            assert status == 404 and asset['asset_id'] not in owner_mismatch and 'signature=' not in owner_mismatch
            with closing(sqlite3.connect(root / "saas.sqlite")) as db, db:
                db.execute('update media_asset_jobs set created_by=? where media_job_id=?',
                           (actor[0], 'media_job_http_recovery'))
            _, second_store = request_json(f"{base}/stores", method="POST", token=token,
                body={"platform": "ebay", "store_name": "Second Upload Store", "marketplace": "EBAY_US"})
            status, wrong_store = request_error(urllib.request.Request(
                f"{base}/stores/{second_store['store']['store_id']}/media-source-uploads/{upload_id}",
                headers={"authorization": f"Bearer {token}"}))
            assert status == 404 and "signature=" not in wrong_store
            status, wrong_job_store = request_error(urllib.request.Request(
                f"{base}/stores/{second_store['store']['store_id']}/media-asset-jobs/media_job_http_recovery/source",
                headers={"authorization": f"Bearer {token}"}))
            assert status == 404 and asset['asset_id'] not in wrong_job_store and 'signature=' not in wrong_job_store
            # Old or damaged stored payloads fail closed without disconnecting
            # HTTP or leaking a source URL; they must not become a new upload.
            for malformed in ({'job_spec': []}, {'job_spec': {'inputs': []}},
                              {'job_spec': {'inputs': {'product_facts': []}}},
                              {'job_spec': {'inputs': {'product_facts': {'source_asset_id': [asset['asset_id']]}}}}):
                with closing(sqlite3.connect(root / "saas.sqlite")) as db, db:
                    db.execute('update media_asset_jobs set media_job_json=? where media_job_id=?',
                               (json.dumps(malformed), 'media_job_http_recovery'))
                status, invalid_job_source = request_error(urllib.request.Request(job_recovery_url,
                    headers={"authorization": f"Bearer {token}"}))
                assert status == 404 and 'signature=' not in invalid_job_source and asset['asset_id'] not in invalid_job_source
            with closing(sqlite3.connect(root / "saas.sqlite")) as db, db:
                db.execute('update media_asset_jobs set media_job_json=? where media_job_id=?',
                           (json.dumps(job_payload), 'media_job_http_recovery'))
            assert {p: p.read_bytes() for p in source_root.glob('*/*') if p.is_file()} == before_recovery
            status, invalid_id = request_error(urllib.request.Request(
                f"{base}/stores/{store_id}/media-source-uploads/too-short",
                headers={"authorization": f"Bearer {token}"}))
            assert status == 400 and json.loads(invalid_id)["code"] == "invalid_upload_id"
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

            # Backwards compatibility: existing clients may omit the new attempt id.
            legacy_upload = urllib.request.Request(upload.full_url, data=png, method="POST",
                headers={"authorization": f"Bearer {token}", "content-type": "image/png"})
            with urllib.request.urlopen(legacy_upload, timeout=20) as response:
                legacy = json.loads(response.read().decode("utf-8"))
            assert legacy["media_source_asset"]["asset_id"] != asset["asset_id"]

            # Deliberately discard every response field: recovery must need only our scoped attempt id.
            lost_id = "http-discarded-response-0001"
            lost_upload = urllib.request.Request(upload.full_url, data=png, method="POST", headers={
                "authorization": f"Bearer {token}", "content-type": "image/png", "x-jiejing-upload-id": lost_id})
            with urllib.request.urlopen(lost_upload, timeout=20) as response:
                response.read()
            before_lookup = {p: p.read_bytes() for p in source_root.glob("*/*") if p.is_file()}
            _, after_loss = request_json(f"{base}/stores/{store_id}/media-source-uploads/{lost_id}", token=token)
            assert after_loss["upload_id"] == lost_id and after_loss["upload_status"] == "completed"
            assert after_loss["media_source_asset"]["asset_id"] not in (asset["asset_id"], legacy["media_source_asset"]["asset_id"])
            assert {p: p.read_bytes() for p in source_root.glob("*/*") if p.is_file()} == before_lookup
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

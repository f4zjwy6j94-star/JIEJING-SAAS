#!/usr/bin/env python3
"""Focused security and product contract for grounded media source uploads."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.media_source_assets import (  # noqa: E402
    MAX_MEDIA_SOURCE_BYTES,
    MediaSourceAssetError,
    MediaSourceAssetStore,
)


def expect_error(code: str, callback) -> None:
    try:
        callback()
    except MediaSourceAssetError as exc:
        assert exc.code == code, (exc.code, code)
        return
    raise AssertionError(f"expected MediaSourceAssetError: {code}")


def upload_process(root, request, quota_entered, release_quota, outcomes) -> None:
    store = MediaSourceAssetStore(root=Path(root), signing_secret=b"process-test-only",
        public_base_url="https://app.jiejing.example", max_assets_per_company=1)
    original_usage = store._company_usage_locked
    def held_usage(**kwargs):
        result = original_usage(**kwargs)
        quota_entered.set()
        if release_quota == "crash":
            time.sleep(30)  # Parent terminates here, outside shared Event/Queue critical sections.
        elif release_quota is not None and not release_quota.wait(10):
            raise RuntimeError("fixture quota gate timed out")
        return result
    store._company_usage_locked = held_usage
    try:
        asset, _ = store.create(**request)
        outcomes.put(("ok", asset.asset_id))
    except MediaSourceAssetError as exc:
        outcomes.put(("error", exc.code))


def process_lock_contract(png: bytes) -> None:
    context = multiprocessing.get_context("spawn")
    request = dict(company_id="process-company", store_id="process-store", user_id="process-user",
        upload_id="process-crash-upload-0001", content_type="image/png", filename="source.png", content=png)
    with tempfile.TemporaryDirectory(prefix="jiejing-upload-process-lock-") as temp:
        root = Path(temp) / "crash"
        entered, outcomes = context.Event(), context.Queue()
        held = context.Process(target=upload_process, args=(str(root), request, entered, "crash", outcomes))
        held.start()
        try:
            assert entered.wait(10), "child must own write scope before termination"
            store = MediaSourceAssetStore(root=root, signing_secret=b"process-test-only",
                public_base_url="https://app.jiejing.example", max_assets_per_company=1)
            lock_files = list((root / ".source-upload-locks").glob("*.lock"))
            assert len(lock_files) == 1
            expect_error("upload_in_progress", lambda: store.create(**request))
            assert held.is_alive(), "a waiting writer must neither steal nor terminate an active owner"
            assert lock_files[0].exists() and not list(root.glob("*/*.json"))
            held.terminate(); held.join(5)
            assert not held.is_alive()
            # A terminated process may leave a file, but must not leave an owned lock.
            asset, _ = store.create(**request)
            assert lock_files[0].exists(), "persistent lock inode is reused rather than unlinked"
            recovered, _ = store.get_by_upload_id(**{k: request[k] for k in ("company_id", "store_id", "user_id", "upload_id")})
            assert recovered.asset_id == asset.asset_id
        finally:
            if held.is_alive(): held.terminate()
            held.join(5); outcomes.close()

        root = Path(temp) / "quota-race"
        first_entered, second_entered = context.Event(), context.Event()
        release, outcomes = context.Event(), context.Queue()
        first = context.Process(target=upload_process, args=(str(root), request, first_entered, release, outcomes))
        second_request = {**request, "upload_id": "process-other-upload-0002"}
        second = context.Process(target=upload_process, args=(str(root), second_request, second_entered, None, outcomes))
        first.start()
        try:
            assert first_entered.wait(10)
            second.start()
            assert not second_entered.wait(1), "same-company quota calculation must remain serialized"
            release.set()
            first.join(10); second.join(10)
            assert not first.is_alive() and not second.is_alive()
            results = [outcomes.get(timeout=3), outcomes.get(timeout=3)]
            assert sum(row[0] == "ok" for row in results) == 1, results
            assert ("error", "tenant_upload_quota_exceeded") in results, results
            assert len(list(root.glob("*/*.json"))) == 1
        finally:
            release.set()
            for process in (first, second):
                if process.pid and process.is_alive(): process.terminate()
                if process.pid: process.join(5)
            outcomes.close()


def recovery_contract(png: bytes) -> None:
    """Lost responses recover by scoped read; writes retain one stable receipt."""
    with tempfile.TemporaryDirectory(prefix="jiejing-upload-recovery-") as temp:
        root = Path(temp)
        now = [1_800_000_000.0]
        options = dict(root=root / "assets", signing_secret=b"recovery-test-only",
                       public_base_url="https://app.jiejing.example", now=lambda: now[0],
                       max_assets_per_company=1)
        store = MediaSourceAssetStore(**options)
        scope = dict(company_id="recovery-company", store_id="recovery-store", user_id="recovery-user")
        upload_id = "test-upload-recovery-0001"
        request = dict(**scope, upload_id=upload_id, content_type="image/png", filename="source.png", content=png)
        asset, _ = store.create(**request)
        initial_files = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
        now[0] += 10
        repeated, _ = store.create(**request)
        assert repeated.asset_id == asset.asset_id
        assert repeated.created_at == asset.created_at
        assert repeated.retention_expires_at == asset.retention_expires_at
        assert sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) == initial_files
        # Simulate page/restart loss: only the safe client attempt id survives.
        reopened = MediaSourceAssetStore(**options)
        recovered, url = reopened.get_by_upload_id(**scope, upload_id=upload_id)
        assert recovered.asset_id == asset.asset_id and recovered.sha256 == asset.sha256
        assert recovered.public_dict(source_url=url)["secret_exposed"] is False
        assert sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) == initial_files
        for field in ("company_id", "store_id", "user_id"):
            expect_error("upload_not_found", lambda field=field: reopened.get_by_upload_id(
                **{**scope, field: "other-scope"}, upload_id=upload_id))
        expect_error("upload_not_found", lambda: reopened.get_by_upload_id(**scope, upload_id="unknown-upload-id-0001"))
        expect_error("invalid_upload_id", lambda: reopened.get_by_upload_id(**scope, upload_id="../unsafe"))
        expect_error("upload_id_conflict", lambda: reopened.create(**{**request, "content": png + b"changed"}))
        assert recovered.file_path.read_bytes() == png
        now[0] = asset.retention_expires_at + 1
        expect_error("asset_expired", lambda: reopened.get_by_upload_id(**scope, upload_id=upload_id))
        expect_error("asset_expired", lambda: reopened.create(**request))

        unavailable = MediaSourceAssetStore(root=root / "unsigned", signing_secret=None,
                                             public_base_url="https://app.jiejing.example")
        expect_error("signing_unavailable", lambda: unavailable.create(**request))
        assert not any(p.is_file() for p in unavailable.root.rglob("*")), "no blob or metadata before signing readiness"

        # Separate store objects model distinct request handlers sharing a disk root.
        concurrent_options = {**options, "root": root / "concurrent"}
        stores = [MediaSourceAssetStore(**concurrent_options), MediaSourceAssetStore(**concurrent_options)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            pairs = list(pool.map(lambda instance: instance.create(**request), stores))
        assert pairs[0][0].asset_id == pairs[1][0].asset_id
        assert len(list((root / "concurrent").glob("*/*.json"))) == 1

        # A disk failure after the image write must not let another body replace it.
        import jiejing_saas.media_source_assets as source_module
        original_write = source_module._atomic_write
        interrupted = MediaSourceAssetStore(**{**options, "root": root / "interrupted"})
        def fail_metadata(path, content):
            if path.suffix == ".json":
                raise OSError("synthetic metadata failure")
            return original_write(path, content)
        with patch.object(source_module, "_atomic_write", side_effect=fail_metadata):
            try:
                interrupted.create(**request)
            except OSError:
                pass
            else:
                raise AssertionError("synthetic metadata failure must propagate")
        expect_error("upload_receipt_incomplete", lambda: interrupted.get_by_upload_id(**scope, upload_id=upload_id))
        expect_error("upload_receipt_incomplete", lambda: interrupted.create(**{**request, "content": png + b"other"}))
        assert next((root / "interrupted").glob("*/*.png")).read_bytes() == png


def main() -> None:
    now = [1_800_000_000.0]
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    process_lock_contract(png)
    recovery_contract(png)
    with tempfile.TemporaryDirectory(prefix="jiejing-media-source-") as temp:
        store = MediaSourceAssetStore(
            root=Path(temp),
            signing_secret=b"test-only-signing-secret",
            public_base_url="https://app.jiejing.example",
            now=lambda: now[0],
        )
        asset, source_url = store.create(
            company_id="company_test",
            store_id="store_test",
            user_id="user_test",
            content_type="image/png",
            filename="merchant source.png",
            content=png,
        )
        parsed = urlparse(source_url)
        query = parse_qs(parsed.query)
        assert parsed.path == f"/media-source-assets/{asset.asset_id}/content"
        assert asset.public_dict(source_url=source_url)["tenant_scoped"] is True
        assert asset.width == 1 and asset.height == 1
        resolved = store.resolve(
            asset_id=asset.asset_id,
            expires=query["expires"][0],
            signature=query["signature"][0],
        )
        assert resolved.file_path.read_bytes() == png
        provider_asset, provider_content = store.read_for_provider(
            asset_id=asset.asset_id,
            company_id="company_test",
            store_id="store_test",
        )
        assert provider_asset.asset_id == asset.asset_id and provider_content == png
        expect_error(
            "asset_scope_mismatch",
            lambda: store.read_for_provider(
                asset_id=asset.asset_id,
                company_id="company_attacker",
                store_id="store_test",
            ),
        )
        expect_error(
            "asset_scope_mismatch",
            lambda: store.read_for_provider(
                asset_id=asset.asset_id,
                company_id="company_test",
                store_id="store_attacker",
            ),
        )
        expect_error(
            "invalid_signature",
            lambda: store.resolve(asset_id=asset.asset_id, expires=query["expires"][0], signature="wrong"),
        )
        now[0] += 3601
        expect_error(
            "signed_url_expired",
            lambda: store.resolve(
                asset_id=asset.asset_id,
                expires=query["expires"][0],
                signature=query["signature"][0],
            ),
        )
        expect_error(
            "unsupported_image",
            lambda: store.create(
                company_id="company_test",
                store_id="store_test",
                user_id="user_test",
                content_type="image/svg+xml",
                filename="unsafe.svg",
                content=b"<svg><script>alert(1)</script></svg>",
            ),
        )
        expect_error(
            "invalid_image_structure",
            lambda: store.create(
                company_id="company_test",
                store_id="store_test",
                user_id="user_test",
                content_type="image/png",
                filename="broken.png",
                content=b"\x89PNG\r\n\x1a\nnot-a-real-image",
            ),
        )
        expect_error(
            "file_too_large",
            lambda: store.create(
                company_id="company_test",
                store_id="store_test",
                user_id="user_test",
                content_type="image/png",
                filename="large.png",
                content=png + b"x" * MAX_MEDIA_SOURCE_BYTES,
            ),
        )
        quota_store = MediaSourceAssetStore(
            root=Path(temp) / "quota",
            signing_secret=b"test-only-signing-secret",
            public_base_url="https://app.jiejing.example",
            now=lambda: now[0],
            max_assets_per_company=1,
        )
        quota_store.create(
            company_id="company_quota",
            store_id="store_test",
            user_id="user_test",
            content_type="image/png",
            filename="first.png",
            content=png,
        )
        expect_error(
            "tenant_upload_quota_exceeded",
            lambda: quota_store.create(
                company_id="company_quota",
                store_id="store_test",
                user_id="user_test",
                content_type="image/png",
                filename="second.png",
                content=png,
            ),
        )

    server = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy" / "nginx.public-staging.conf").read_text(encoding="utf-8")
    for marker in [
        "MediaSourceAssetStore",
        'parts[0] == "media-source-assets"',
        'parts[2] == "media-source-assets"',
        "_read_media_source_body",
        "_send_media_source_asset",
    ]:
        assert marker in server, marker
    for marker in [
        "uploadSaasMediaSourceFile",
        "saasMediaSourceUpload",
        "referenceImageUrl",
        "source_asset_id",
        "provider_reference_ready",
        "delete safeAsset.source_url",
    ]:
        assert marker in app, marker
    assert "media-source-assets" in nginx
    assert "client_max_body_size 6m;" in nginx
    print("PASS jiejing_media_source_assets")


if __name__ == "__main__":
    main()

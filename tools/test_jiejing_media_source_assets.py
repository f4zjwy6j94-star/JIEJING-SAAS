#!/usr/bin/env python3
"""Focused security and product contract for grounded media source uploads."""

from __future__ import annotations

import base64
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse


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


def main() -> None:
    now = [1_800_000_000.0]
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
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
        "source_url",
    ]:
        assert marker in app, marker
    assert "media-source-assets" in nginx
    assert "client_max_body_size 6m;" in nginx
    print("PASS jiejing_media_source_assets")


if __name__ == "__main__":
    main()

"""Static contract for merchant-facing media version, cost and retry controls."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")
    api = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    repository = (ROOT / "jiejing_saas" / "repository.py").read_text(encoding="utf-8")
    pipeline = (ROOT / "jiejing_saas" / "media_asset_pipeline.py").read_text(encoding="utf-8")
    required = {
        "version label": "saasMediaAssetJobVersionLabel",
        "cost transparency": "actual_cost_status",
        "merchant retry action": "data-media-rework-job",
        "retry endpoint": 'parts[2] == "retry"',
        "immutable lineage": "parent_media_job_id",
        "review evidence": "confirmed_by_merchant",
        "draft-only approval": "approved_for_listing_draft",
        "no merchant charge claim": '"merchant_charge_created": False',
        "source output comparison": "asset-source-comparison",
        "source image extraction": "saasMediaSourceImageForReview",
        "modal rework action": 'id="assetReworkCurrent"',
        "shape review": "商品外形、结构、比例和配件数量与来源图一致",
        "material review": "颜色、材质、Logo 和包装没有被擅自改变",
        "claim review": "尺寸、容量、认证和效果承诺都有真实资料支持",
    }
    corpus = "\n".join((app_html, app, styles, api, repository, pipeline))
    missing = [label for label, marker in required.items() if marker not in corpus]
    if missing:
        print(f"FAIL media version/rework UI contract missing: {missing}")
        return 1
    retry_start = app.index("async function retrySaasMediaAssetJob")
    retry_end = app.index("\nfunction saasMediaSourceAssetForListingDraft", retry_start)
    retry_source = app[retry_start:retry_end]
    if "window.confirm" in retry_source:
        print("FAIL media rework must use an in-page confirmation instead of a blocking browser dialog")
        return 1
    if "await requestMediaReworkAcceptance(sourceJob)" not in retry_source:
        print("FAIL media rework must wait for the merchant-facing in-page acceptance before queueing")
        return 1
    if "不会写入 eBay" not in app or "确认创建新版本" not in app:
        print("FAIL media rework must disclose usage and eBay write boundary before queueing")
        return 1
    if 'app.js?v=20260825-listing-media-restore-v1' not in app_html:
        print("FAIL media retry fix must advance the browser cache key so deployed clients receive it")
        return 1
    print("PASS jiejing_media_version_rework_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

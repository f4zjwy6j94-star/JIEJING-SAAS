#!/usr/bin/env python3
"""Focused UI contract for media review and real bulk candidate handoff."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle}")


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")

    for needle, label in [
        ('status.live_image_generation_enabled === true', "live image readiness signal"),
        ("素材清单实际返回 ${deliveredCount} 个结果", "actual manifest result count"),
        ('job.status !== "approved_for_listing"', "review gate before Listing writeback"),
        ("approveLatestSaasMediaAssetJobForListingDraft", "persisted merchant media review"),
        ('state.saasActiveMediaPreviewKey === "script"', "script-only preview handling"),
        ("视频文件尚未生成", "honest video state"),
        ("parseSaasBulkManualCandidates", "manual bulk candidate parser"),
        ("saasBulkCandidatesFromCurrentWork", "AI CEO bulk candidate source"),
        ("saasBulkCandidateToListingDraft", "real candidate Listing handoff"),
        ("没有可送出的真实候选", "empty batch guard"),
        ("不会把计划数量或旧演示商品算作真实候选", "actual batch count copy"),
        ("isLegacySampleProductLabel", "public media legacy product label guard"),
        ("真实视频预览 · 待人工审核", "dynamic real video preview copy"),
    ]:
        require(app_js, needle, label)

    require(app_html, 'id="assetSendConfirm">完成素材审核', "media review button copy")
    require(app_html, '<option selected>不生成视频</option>', "video generation requires explicit merchant choice")
    if 'id="assetSendConfirm">送确认中心' in app_html:
        raise AssertionError("media review must not navigate to an empty high-risk confirmation center")
    require(app_js, "const videoRequested = /视频/.test", "video request derives from merchant media settings")
    require(app_js, "!/不生成视频/.test(videoPreset)", "no-video selection prevents provider spend")
    require(app_js, "video_generation_requested: videoRequested", "video request reaches backend provider job")

    public_accept_start = app_js.index('if (action === "accept-candidates")')
    public_accept_end = app_js.index("state.bulkApprovedCount = state.batchPreviewCount", public_accept_start)
    public_accept = app_js[public_accept_start:public_accept_end]
    require(public_accept, "saasBulkCandidateToListingDraft(firstCandidate)", "public bulk uses selected real candidate")
    if "attachBulkHandoffDrafts()" in public_accept:
        raise AssertionError("public bulk handoff must not attach static demo catalog drafts")

    print("PASS jiejing_workflow_closure_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

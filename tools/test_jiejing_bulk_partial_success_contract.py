"""Contract for bulk draft partial success, pause and item-level retry."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")
    checks = {
        "independent item attempt": "function saasBulkHandoffAttempt",
        "batch execution ledger": "function executeSaasBulkHandoffBatch",
        "partial success": 'status: failed && succeeded ? "partial_success"',
        "pause": 'action === "pause-batch"',
        "resume": 'action === "resume-batch"',
        "item retry": 'action === "retry-bulk-item"',
        "successful item open": 'action === "open-bulk-item"',
        "merchant run panel": "bulk_partial_success_pause_retry_v1",
        "successful drafts retained": "state.saasBulkListingDrafts",
        "no real writes": "real_platform_writes_enabled: false",
        "responsive run items": ".saas-bulk-run-items",
        "manual import preview": "saasBulkManualImportPreview",
        "manual import dedupe": "saasBulkManualCandidateDedupeKey",
        "row-level validation": "bulk-import-preview-row",
        "two-step import": "确认导入",
    }
    corpus = app + "\n" + styles
    missing = [label for label, marker in checks.items() if marker not in corpus]
    if missing:
        print(f"FAIL bulk partial-success contract missing: {missing}")
        return 1
    accept = app[app.index('if (action === "accept-candidates")') : app.index('state.bulkApprovedCount = state.batchPreviewCount', app.index('if (action === "accept-candidates")'))]
    if "executeSaasBulkHandoffBatch(eligible)" not in accept:
        print("FAIL public bulk acceptance must execute the per-item batch ledger")
        return 1
    if "successfulIds" not in accept:
        print("FAIL public bulk acceptance must keep successful items when siblings fail")
        return 1
    empty_preview = app[app.index("if (!previewCount)") : app.index("const laneMeta", app.index("if (!previewCount)"))]
    if empty_preview.count("先小批量筛，不一键乱铺") > 0:
        print("FAIL bulk result panel must not repeat the page hero and controls")
        return 1
    print("PASS jiejing_bulk_partial_success_contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

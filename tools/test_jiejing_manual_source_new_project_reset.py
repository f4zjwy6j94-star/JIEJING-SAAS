#!/usr/bin/env python3
"""Regression for starting a fresh manual-source Listing project."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "app.js").read_text(encoding="utf-8")


def function_body(source: str, name: str) -> str:
    markers = (f"async function {name}", f"function {name}")
    starts = [source.find(marker) for marker in markers]
    starts = [value for value in starts if value >= 0]
    if not starts:
        raise AssertionError(f"missing JavaScript function: {name}")
    start = min(starts)
    next_function = source.find("\nfunction ", start + 1)
    next_async = source.find("\nasync function ", start + 1)
    ends = [value for value in (next_function, next_async) if value > start]
    return source[start : min(ends) if ends else len(source)]


def run_node_json(script: str) -> dict[str, object]:
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"node fixture failed:\n{completed.stderr or completed.stdout}")
    output = completed.stdout.strip().splitlines()
    if not output:
        raise AssertionError("node fixture returned no JSON")
    return json.loads(output[-1])


def main() -> None:
    reset_evidence = function_body(APP_JS, "resetSaasListingPublishEvidenceForNewProject")
    persist_facts = function_body(APP_JS, "persistSaasManualSourceFacts")
    result = run_node_json(
        "\n".join(
            [
                "const oldConfirmation = { confirmation_id: 'confirm-old', action_type: 'save_ebay_listing_draft' };",
                "const oldExecution = { execution_id: 'execution-old', confirmation_id: 'confirm-old' };",
                "const state = {",
                "  saasConnected: false,",
                "  saasListingComposerDraft: { listing_project_key: 'project-old', media_writeback: { media_job_id: 'media-old' } },",
                "  activeMediaDraft: 'project-old',",
                "  saasMediaSourceUploadEpoch: 7,",
                "  saasMediaSourceUpload: { upload_id: 'upload-old' },",
                "  saasActiveMediaPreviewKey: 'manifest:media-old:asset-old:0',",
                "  saasLastPublishReadiness: { status: 'ready', listing_project_key: 'project-old' },",
                "  saasLastPublishConfirmationEvidence: { confirmation_id: 'confirm-old', listing_project_key: 'project-old' },",
                "  saasPreflightResults: [{ status: 'ready', listing_project_key: 'project-old' }],",
                "  saasPreTestCheck: { status: 'ready', listing_project_key: 'project-old' },",
                "  saasConfirmations: [oldConfirmation],",
                "  saasExecutionResults: [oldExecution],",
                "};",
                "const document = { querySelector: () => null };",
                "const setSaasAiCeoTaskContextState = () => {};",
                "const saasListingDraftFromManualSourceFacts = () => ({",
                "  product: 'New Manual Product',",
                "  listing_project_key: 'project-new',",
                "  listing_project_identity: { key: 'project-new', source_report_id: '', candidate_id: '' },",
                "  media_writeback: null,",
                "});",
                "const activeSaasStore = () => ({ store_id: 'store-unit' });",
                "const saveSaasProtectedStateSnapshot = () => {};",
                "const showActionToast = () => {};",
                reset_evidence,
                persist_facts,
                "(async () => {",
                "  const saved = await persistSaasManualSourceFacts({ product_name: 'New Manual Product' });",
                "  console.log(JSON.stringify({",
                "    saved,",
                "    projectKey: state.saasListingComposerDraft?.listing_project_identity?.key || '',",
                "    mediaWriteback: state.saasListingComposerDraft?.media_writeback || null,",
                "    activeMediaDraft: state.activeMediaDraft,",
                "    uploadEpoch: state.saasMediaSourceUploadEpoch,",
                "    mediaSourceUpload: state.saasMediaSourceUpload || null,",
                "    activeMediaPreviewKey: state.saasActiveMediaPreviewKey,",
                "    publishReadiness: state.saasLastPublishReadiness,",
                "    confirmationEvidence: state.saasLastPublishConfirmationEvidence,",
                "    preflightResults: state.saasPreflightResults,",
                "    preTestCheck: state.saasPreTestCheck,",
                "    confirmationHistoryPreserved: state.saasConfirmations[0] === oldConfirmation,",
                "    executionHistoryPreserved: state.saasExecutionResults[0] === oldExecution,",
                "  }));",
                "})().catch((error) => { console.error(error); process.exit(1); });",
            ]
        )
    )

    assert result["saved"] is False, result
    assert result["projectKey"] == "project-new", result
    assert result["mediaWriteback"] is None, result
    assert result["activeMediaDraft"] == "project-new", result
    assert result["uploadEpoch"] == 8, result
    assert result["mediaSourceUpload"] is None, result
    assert result["activeMediaPreviewKey"] == "", result
    assert result["publishReadiness"] is None, result
    assert result["confirmationEvidence"] is None, result
    assert result["preflightResults"] == [], result
    assert result["preTestCheck"] is None, result
    assert result["confirmationHistoryPreserved"] is True, result
    assert result["executionHistoryPreserved"] is True, result
    print("PASS jiejing_manual_source_new_project_reset")


if __name__ == "__main__":
    main()

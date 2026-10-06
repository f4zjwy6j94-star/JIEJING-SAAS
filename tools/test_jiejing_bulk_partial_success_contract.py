"""Contract for bulk draft partial success, pause and item-level retry.

The browser smoke requires a dedicated local test backend with its fixture APIs.
An environment 404 is test-environment setup failure, not an A-scheme product RED.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def guard_allows(script: Path, target: str, *, opt_in: bool, allowlist: str) -> bool:
    probe = """
const { assertSafeMutationBase } = require(process.argv[1]);
try { assertSafeMutationBase(process.argv[2]); process.stdout.write("ALLOW"); }
catch (error) { process.stdout.write(`BLOCK:${error.message}`); process.exitCode = 2; }
"""
    env = os.environ.copy()
    if opt_in:
        env["JIEJING_ALLOW_REMOTE_TEST_MUTATION"] = "true"
    else:
        env.pop("JIEJING_ALLOW_REMOTE_TEST_MUTATION", None)
    env["JIEJING_REMOTE_TEST_HOSTS"] = allowlist
    result = subprocess.run(
        ["node", "-e", probe, str(script), target],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout == "ALLOW"


def main() -> int:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")
    browser_smoke = (ROOT / "tools" / "codex_jiejing_bulk_media_handoff_smoke.js").read_text(encoding="utf-8")
    guard_script = ROOT / "tools" / "jiejing_browser_smoke_mutation_guard.js"
    guard_cases = [
        ("https://jiejing.shop", True, "jiejing.shop", False),
        ("https://app.jiejing.shop", True, "app.jiejing.shop", False),
        ("https://jiejing.shop.", True, "jiejing.shop", False),
        ("https://APP.JIEJING.SHOP.", True, "app.jiejing.shop", False),
        ("http://43.129.169.223", True, "43.129.169.223", False),
        ("http://43.129.205.244", True, "43.129.205.244", False),
        ("http://[::ffff:43.129.169.223]", True, "43.129.169.223", False),
        ("http://[::ffff:2b81:a9df]", True, "43.129.169.223", False),
        ("http://[0:0:0:0:0:ffff:2b81:cdf4]", True, "43.129.205.244", False),
        ("http://[::ffff:192.0.2.1]", True, "192.0.2.1", True),
        ("https://test.invalid", False, "test.invalid", False),
        ("https://test.invalid", True, "", False),
        ("https://test.invalid", True, "other.invalid", False),
        ("https://test.invalid.", True, "test.invalid", True),
        ("http://127.0.0.1:8788", False, "", True),
        ("http://localhost:8788", False, "", True),
        ("http://[::1]:8788", False, "", True),
    ]
    for target, opt_in, allowlist, expected in guard_cases:
        if guard_allows(guard_script, target, opt_in=opt_in, allowlist=allowlist) != expected:
            print(f"FAIL bulk mutation guard drifted for {target} opt_in={opt_in} allowlist={allowlist}")
            return 1
    if "assertSafeMutationBase(base);" not in browser_smoke:
        print("FAIL bulk browser smoke must invoke its mutation guard before account setup")
        return 1
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
        "stable internal mode control": "data-listing-mode",
        "active internal mode semantics": "aria-current",
        "legacy batch deep link": 'batch: "bulk"',
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

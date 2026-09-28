#!/usr/bin/env python3
"""Static checks for Jiejing frontend staging API configuration."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def validate_prepare_bundle_contract() -> str:
    with TemporaryDirectory(prefix="jiejing-clean-bundle-fixture-") as temp_dir:
        fixture = Path(temp_dir)
        (fixture / "tools").mkdir()
        (fixture / "deploy").mkdir()
        prepare_source = (ROOT / "tools" / "jiejing_prepare_public_staging_bundle.py").read_text(
            encoding="utf-8"
        )
        (fixture / "tools" / "jiejing_prepare_public_staging_bundle.py").write_text(
            prepare_source,
            encoding="utf-8",
        )
        (fixture / "tools" / "jiejing_release_gate_evidence.py").write_text(
            (ROOT / "tools" / "jiejing_release_gate_evidence.py").read_text(encoding="utf-8"), encoding="utf-8",
        )
        gate_source = (ROOT / "tools" / "jiejing_precloud_deployment_gate.py").read_text(encoding="utf-8")
        catalog_node = next(node for node in ast.parse(gate_source).body
                            if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "CHECKS")
        gate_lines = gate_source.splitlines(keepends=True)
        gate_lines[catalog_node.lineno - 1:catalog_node.end_lineno] = [
            'CHECKS = [("fixture_pass", [sys.executable, "-c", "raise SystemExit(0)"])]\n'
        ]
        (fixture / "tools" / "jiejing_precloud_deployment_gate.py").write_text("".join(gate_lines), encoding="utf-8")
        app_js = "console.log('clean fixture');\n"
        styles_css = "body { color: #123; }\n"
        app_digest = hashlib.sha256(app_js.encode("utf-8")).hexdigest()[:12]
        style_digest = hashlib.sha256(styles_css.encode("utf-8")).hexdigest()[:12]
        family = "fixture-atomic-release"
        fixture_files = {
            "app.js": app_js,
            "styles.css": styles_css,
            "index.html": (
                f'<link rel="preload" href="./app.js?v={family}-{app_digest}" as="script">\n'
                f'<link rel="preload" href="./styles.css?v={family}-{style_digest}" as="style">\n'
            ),
            "app.html": (
                f'<link rel="stylesheet" href="./styles.css?v={family}-{style_digest}">\n'
                f'<script src="./app.js?v={family}-{app_digest}"></script>\n'
            ),
        }
        ops_fixture_files = {
            "ops.js": "console.log('public operations fixture');\n",
            "ops.css": "body { color: #234; }\n",
            "assets/jiejing-ops-panels.js": "window.publicOpsFixture = true;\n",
            "assets/jiejing-logo-mark.svg": '<svg xmlns="http://www.w3.org/2000/svg"/>\n',
            "assets/jiejing-app-icon.svg": '<svg xmlns="http://www.w3.org/2000/svg"/>\n',
        }
        ops_hashes = {
            name: hashlib.sha256(ops_fixture_files[name].encode("utf-8")).hexdigest()
            for name in ("assets/jiejing-ops-panels.js", "ops.css", "ops.js")
        }
        ops_version = "ops-v1-" + hashlib.sha256(
            json.dumps(ops_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:12]
        ops_fixture_files["ops.html"] = (
            f'<link rel="stylesheet" href="ops.css?v={ops_version}">\n'
            f'<script src="assets/jiejing-ops-panels.js?v={ops_version}"></script>\n'
            f'<script src="ops.js?v={ops_version}"></script>\n'
        )
        fixture_files.update(ops_fixture_files)
        for name, contents in fixture_files.items():
            (fixture / name).parent.mkdir(parents=True, exist_ok=True)
            (fixture / name).write_text(contents, encoding="utf-8")
        whitelist = [
            "deploy/apply-staging-patch.sh",
            "index.html",
            "app.html",
            "app.js",
            "styles.css",
            *ops_fixture_files,
        ]
        apply_text = "FILES=(\n" + "".join(f'  "{name}"\n' for name in whitelist) + ")\n"
        (fixture / "deploy" / "apply-staging-patch.sh").write_text(apply_text, encoding="utf-8")
        (fixture / ".gitignore").write_text("output/\n__pycache__/\n", encoding="utf-8")
        for command in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "fixture@jiejing.invalid"],
            ["git", "config", "user.name", "Jiejing Fixture"],
            ["git", "add", "."],
            ["git", "commit", "-q", "-m", "fixture"],
        ):
            completed = subprocess.run(
                command,
                cwd=fixture,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                timeout=30,
            )
            if completed.returncode != 0:
                return "clean fixture git setup failed"
        source_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=fixture,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout.strip()
        prepare = fixture / "tools" / "jiejing_prepare_public_staging_bundle.py"
        unverified = subprocess.run([sys.executable, str(prepare), "--dry-run"], cwd=fixture,
                                    capture_output=True, text=True, encoding="utf-8", timeout=120)
        if unverified.returncode == 0 or "gate_evidence" not in unverified.stdout + unverified.stderr:
            return "new bundle without source-bound gate evidence was accepted"
        fixture_gate = subprocess.run([sys.executable, str(fixture / "tools" / "jiejing_precloud_deployment_gate.py")],
                                      cwd=fixture, capture_output=True, text=True, encoding="utf-8", timeout=30)
        if fixture_gate.returncode != 0:
            return "isolated one-check fixture gate failed"
        bundle_dry_run = subprocess.run(
            [sys.executable, str(prepare), "--dry-run"],
            cwd=fixture,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=120,
        )
        if bundle_dry_run.returncode != 0:
            return "clean public staging bundle dry-run was rejected"
        try:
            bundle_manifest = json.loads(bundle_dry_run.stdout)
        except json.JSONDecodeError:
            return "public staging bundle dry-run did not emit readable JSON"
        if bundle_manifest.get("source_commit") != source_commit:
            return "bundle manifest is not bound to the clean source commit"
        proof = bundle_manifest.get("release_gate_proof", {})
        gate_path = fixture / "output" / "jiejing-precloud-deployment-gate" / "latest.json"
        if proof.get("report_sha256") != hashlib.sha256(gate_path.read_bytes()).hexdigest():
            return "bundle did not bind its exact gate report bytes"
        if proof.get("evidence", {}).get("source_commit") != source_commit or "stdout_tail" in json.dumps(proof):
            return "bundle gate proof is unbound or contains raw check output"
        original_gate_bytes = gate_path.read_bytes()
        stale_gate = json.loads(original_gate_bytes)
        stale_gate["release_gate_evidence"]["check_catalog_sha256"] = "0" * 64
        gate_path.write_text(json.dumps(stale_gate), encoding="utf-8")
        stale_prepare = subprocess.run([sys.executable, str(prepare), "--dry-run"], cwd=fixture,
                                       capture_output=True, text=True, encoding="utf-8", timeout=120)
        gate_path.write_bytes(original_gate_bytes)
        if stale_prepare.returncode == 0 or "gate_evidence_check_catalog_mismatch" not in stale_prepare.stdout + stale_prepare.stderr:
            return "bundle accepted a stale gate catalog"
        files_sha256 = bundle_manifest.get("files_sha256")
        if not isinstance(files_sha256, dict) or set(files_sha256) != set(whitelist):
            return "bundle manifest does not hash the complete whitelist"
        for name in whitelist:
            committed = subprocess.run(
                ["git", "show", f"{source_commit}:{name}"],
                cwd=fixture,
                capture_output=True,
                check=True,
                timeout=30,
            ).stdout
            expected = hashlib.sha256(committed).hexdigest()
            if files_sha256.get(name) != expected:
                return f"bundle whitelist hash does not match fixed commit blob: {name}"
        frontend_hashes = bundle_manifest.get("frontend_files_sha256")
        atomic_frontend_files = {"index.html", "app.html", "app.js", "styles.css"}
        if not isinstance(frontend_hashes, dict) or set(frontend_hashes) != atomic_frontend_files:
            return "bundle manifest does not expose the four frontend hashes"
        ops_manifest_hashes = bundle_manifest.get("ops_files_sha256")
        if not isinstance(ops_manifest_hashes, dict) or set(ops_manifest_hashes) != set(ops_fixture_files):
            return "bundle manifest does not expose exactly the six operations hashes"
        if ops_manifest_hashes != {name: files_sha256[name] for name in ops_fixture_files}:
            return "operations hashes do not match the source-bound whitelist"
        bundle_build = subprocess.run(
            [sys.executable, str(prepare)],
            cwd=fixture,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=120,
        )
        if bundle_build.returncode != 0:
            return "clean public staging bundle build was rejected"
        bundle_match = re.search(r"^BUNDLE_PATH=(.+)$", bundle_build.stdout, flags=re.MULTILINE)
        manifest_match = re.search(r"^MANIFEST_PATH=(.+)$", bundle_build.stdout, flags=re.MULTILINE)
        if not bundle_match or not manifest_match:
            return "bundle build did not return exact artifact paths"
        bundle_path = Path(bundle_match.group(1).strip())
        manifest_path = Path(manifest_match.group(1).strip())
        built_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if built_manifest.get("release_gate_proof") != proof:
            return "built bundle lost or changed the reviewed gate proof"
        if built_manifest.get("ops_files_sha256") != ops_manifest_hashes:
            return "built bundle lost or changed the operations asset hashes"
        with zipfile.ZipFile(bundle_path, "r") as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != set(whitelist):
                return "built bundle entries do not exactly match the whitelist"
            for name in whitelist:
                observed = hashlib.sha256(archive.read(name)).hexdigest()
                if observed != built_manifest.get("files_sha256", {}).get(name):
                    return f"built bundle hash mismatch: {name}"
        spec = importlib.util.spec_from_file_location("jiejing_prepare_fixture", prepare)
        if spec is None or spec.loader is None:
            return "unable to load bundle prepare race fixture"
        prepare_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prepare_module)
        original_committed_files = prepare_module._committed_bundle_files

        def swap_and_restore(source: str, files: list[Path]) -> dict[str, bytes]:
            committed = original_committed_files(source, files)
            target = fixture / "app.js"
            original = target.read_bytes()
            target.write_bytes(original + b"// transient race\n")
            target.write_bytes(original)
            return committed

        prepare_module._committed_bundle_files = swap_and_restore
        whitelist_path = fixture / "deploy" / "apply-staging-patch.sh"
        original_whitelist_bytes = whitelist_path.read_bytes()
        expanded_whitelist = original_whitelist_bytes.decode("utf-8").replace(
            ")\n",
            '  "worktree-only-forged.txt"\n)\n',
            1,
        )
        whitelist_path.write_text(expanded_whitelist, encoding="utf-8")
        try:
            pinned_whitelist = prepare_module._apply_patch_file_list(source_commit)
        finally:
            whitelist_path.write_bytes(original_whitelist_bytes)
        if pinned_whitelist != whitelist or "worktree-only-forged.txt" in pinned_whitelist:
            return "bundle whitelist followed a transient worktree expansion"
        original_argv = sys.argv
        sys.argv = [str(prepare), "--dry-run"]
        try:
            with redirect_stdout(io.StringIO()):
                prepare_module.main()
        except RuntimeError as exc:
            if "whitelist file changed during bundle preparation" not in str(exc):
                return f"bundle race produced imprecise rejection: {exc}"
        else:
            return "transient whitelist swap-and-restore race was accepted"
        finally:
            sys.argv = original_argv
        (fixture / "app.js").write_text(app_js + "// dirty\n", encoding="utf-8")
        dirty_prepare = subprocess.run(
            [sys.executable, str(prepare), "--dry-run"],
            cwd=fixture,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=120,
        )
        if dirty_prepare.returncode == 0 or "dirty git worktree" not in (
            dirty_prepare.stdout + dirty_prepare.stderr
        ):
            return "bundle prepare must fail closed on a dirty worktree"
    return ""


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    index_html = (ROOT / "index.html").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    styles_css = (ROOT / "styles.css").read_text(encoding="utf-8")
    privacy_html = (ROOT / "privacy.html").read_text(encoding="utf-8")
    terms_html = (ROOT / "terms.html").read_text(encoding="utf-8")
    refund_html = (ROOT / "refund-policy.html").read_text(encoding="utf-8")
    support_html = (ROOT / "support.html").read_text(encoding="utf-8")
    risk_html = (ROOT / "risk-disclosure.html").read_text(encoding="utf-8")

    if "document.write(" in app_js:
        return fail("frontend must not use document.write for report export or public rendering")
    if "onclick=" in index_html:
        return fail("public homepage must bind actions in script instead of inline event handlers")
    app_html_app_versions = re.findall(r"\./app\.js\?v=([A-Za-z0-9._-]+)", app_html)
    app_html_style_versions = re.findall(r"\./styles\.css\?v=([A-Za-z0-9._-]+)", app_html)
    if len(app_html_app_versions) != 1:
        return fail("workbench entry must contain exactly one current app.js cache version")
    if len(app_html_style_versions) != 1:
        return fail("workbench entry must contain exactly one current styles.css cache version")
    app_js_asset_version = app_html_app_versions[0]
    frontend_asset_version = app_html_style_versions[0]
    app_js_digest = hashlib.sha256(app_js.encode("utf-8")).hexdigest()[:12]
    styles_digest = hashlib.sha256(styles_css.encode("utf-8")).hexdigest()[:12]
    if not app_js_asset_version.endswith(app_js_digest):
        return fail(
            "workbench app.js cache version must end with the current app.js sha256 prefix "
            f"{app_js_digest}; update both entry files whenever app.js changes"
        )
    if not frontend_asset_version.endswith(styles_digest):
        return fail(
            "workbench styles.css cache version must end with the current styles.css sha256 prefix "
            f"{styles_digest}; update both entry files whenever styles.css changes"
        )
    app_release_family = app_js_asset_version[: -len(app_js_digest)].rstrip("-._")
    style_release_family = frontend_asset_version[: -len(styles_digest)].rstrip("-._")
    if app_release_family != style_release_family:
        return fail(
            "app.js and styles.css must share one atomic frontend release family: "
            f"{app_release_family!r} != {style_release_family!r}"
        )
    prepare_contract_failure = validate_prepare_bundle_contract()
    if prepare_contract_failure:
        return fail(prepare_contract_failure)
    for expected_asset in [
        f"./app.js?v={app_js_asset_version}",
        f"./styles.css?v={frontend_asset_version}",
    ]:
        if expected_asset not in index_html + app_html:
            return fail(f"frontend entry files must bust owner publish cache with {expected_asset}")
    if f"./app.js?v={app_js_asset_version}" not in app_html or f"./app.js?v={app_js_asset_version}" not in index_html:
        return fail("both public and workbench entry files must reference the current app.js cache version")
    if "./app.js?v=20260825-owner-media-testing-v3" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-vision-report-recovery app.js cache version")
    if "./app.js?v=20260826-controlled-existing-draft-publish-v5" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-cross-view publish-recovery cache version")
    if "./app.js?v=20260826-controlled-publish-recovery-v6" in index_html + app_html:
        return fail("frontend entry files must not retain the execution-cache-dependent recovery version")
    if "./app.js?v=20260826-readonly-publish-recovery-v7" in index_html + app_html:
        return fail("frontend entry files must not retain the pending-only decision-center recovery version")
    index_html_app_versions = re.findall(r"\./app\.js\?v=([A-Za-z0-9._-]+)", index_html)
    if index_html_app_versions != [app_js_asset_version, app_js_asset_version]:
        return fail("public entry prefetch and lazy preload must both use the current app.js cache version")
    if "./app.js?v=20260810-safe-revise-confirmation-v1" in index_html + app_html:
        return fail("frontend entry files must not retain the stale pre-clock-skew app.js cache version")
    if "./app.js?v=20260812-ebay-oauth-clock-skew-v2" in index_html + app_html:
        return fail("frontend entry files must not retain the stale pre-terminal-recovery app.js cache version")
    if "./app.js?v=20260812-ebay-oauth-terminal-recovery-v3" in index_html + app_html:
        return fail("frontend entry files must not retain the stale single-terminal OAuth recovery cache version")
    if "./app.js?v=20260812-ebay-oauth-terminal-history-v4" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-sync-confirmation app.js cache version")
    if "./app.js?v=20260812-ebay-readonly-sync-confirmation-v5" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-listing-product-gate app.js cache version")
    if "./app.js?v=20260812-listing-concrete-product-gate-v6" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-confirmation-core-load app.js cache version")
    if "./app.js?v=20260813-confirmation-core-load-v7" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-draft-entry app.js cache version")
    if "./app.js?v=20260813-unpublished-draft-entry-v8" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-server-clock draft OAuth cache version")
    if "./app.js?v=20260814-server-clock-draft-oauth-v9" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-resumable-draft-oauth cache version")
    if "./app.js?v=20260814-draft-oauth-resume-v10" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-inventory-location cache version")
    if "./app.js?v=20260814-ebay-inventory-location-v11" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-inventory-reconciliation cache version")
    if "./app.js?v=20260815-ebay-inventory-reconcile-v12" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-WeChat-zero-charge-rehearsal cache version")
    if "./app.js?v=20260816-wechat-zero-charge-rehearsal-v13" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-rotating-session cache version")
    if "./app.js?v=20260820-rotating-browser-sessions-v14" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-current-store-refresh-proof cache version")
    if "./app.js?v=20260820-ebay-refresh-proof-v15" in index_html + app_html:
        return fail("frontend entry files must not retain the slow commercial-launch-gate refresh proof cache version")
    if "./app.js?v=20260821-ebay-refresh-proof-fast-v16" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-mainland-payment-cutover cache version")
    if "./app.js?v=20260821-mainland-payment-cutover-v17" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-merchant-trial-pricing cache version")
    if "./app.js?v=20260803-product-feedback-v1" in index_html + app_html:
        return fail("frontend entry files must not retain the stale app.js cache version")
    for stale_asset_version in [
        "20260802-merchant-onboarding-v2",
        "20260802-merchant-onboarding-v1",
        "20260715-billing-recovery-renewal-v101",
        "20260715-listing-us-title-v98",
        "20260715-listing-copy-boundary-v97",
        "20260715-listing-copy-boundary-v96",
        "20260714-ebay-draft-save-v95",
        "20260712-publish-receipt-v75",
        "20260711-account-chat-sync-v48",
        "20260711-account-chat-sync-v47",
        "20260525-workflow-feedback-v1",
        "20260526-owner-publish-v1",
        "20260526-owner-publish-v2",
        "20260526-workflow-safety-v2",
        "20260526-readable-pages-v1",
        "20260526-media-fal-v1",
        "20260526-ai-ceo-media-v1",
        "20260526-ai-ceo-ui-v2",
        "20260527-realtime-search-v1",
        "20260527-global-ui-v1",
        "20260619-core-workbench-v1",
        "20260619-first-order-loop-v1",
        "20260619-confirmation-preflight-v1",
        "20260620-onboarding-control-v3",
        "20260620-billing-guardrail-v1",
        "20260620-billing-rehearsal-v2",
        "20260620-owner-cutover-checklist-v1",
        "20260621-final-rehearsal-record-v1",
        "20260621-prelaunch-report-v1",
        "20260621-brand-overlap-v1",
        "20260621-interactive-command-v1",
        "20260621-orbit-command-v1",
        "20260621-minimal-ai-ceo-v1",
        "20260621-minimal-listing-v1",
        "20260621-listing-composer-v1",
        "20260621-core-modules-clean-flow-v9",
        "20260621-core-modules-clean-flow-v11",
        "20260621-listing-input-clarity-v12",
        "20260621-listing-full-form-open-v13",
        "20260621-listing-ordered-flow-v14",
        "20260622-listing-form-prefill-groups-v15",
        "20260623-settings-simplified-v2",
        "20260623-settings-merchant-v3",
        "20260623-settings-child-clean-v4",
        "20260623-settings-five-clean-v5",
        "20260623-ai-ceo-routing-v1",
        "20260624-ai-ceo-minimal-v2",
        "20260624-clean-core-workflows-v1",
        "20260624-first-run-empty-v1",
        "20260624-bulk-media-v1",
        "20260624-confirm-v2",
        "20260624-settings-v1",
        "20260624-ceo-route-v2",
        "20260625-home-settings-v1",
        "20260625-billing-clarity-v2",
        "20260625-first-day-v3",
        "20260625-ai-ceo-pending-v4",
        "20260629-home-intents-v1",
        "20260629-onboarding-guard-v1",
        "20260629-onboarding-lite-v1",
        "20260701-payment-review-brief-v1",
        "20260701-media-asset-review-ui-v1",
        "20260702-merchant-entry-copy-v1",
        "20260702-merchant-subscription-request-v1",
        "20260702-internal-access-boundary-v1",
        "20260702-ai-ceo-route-card-v2",
        "20260710-ai-ceo-reliability-v34",
        "20260710-model-connection-v38",
        "20260711-ai-response-v39",
        "20260711-ai-response-v40",
        "20260711-product-context-v41",
        "20260711-actionable-report-v42",
        "20260711-legacy-report-recovery-v43",
        "20260711-concrete-import-v44",
        "20260711-media-project-v45",
        "20260711-account-chat-sync-v46",
        "20260510-ebay-policy-v1",
    ]:
        if stale_asset_version in index_html + app_html:
            return fail(f"frontend entry files still reference stale asset version: {stale_asset_version}")
    if 'document.documentElement.classList.remove("app-direct-start", "saas-public-direct-start")' not in app_js:
        return fail("returning from the workbench logo to the homepage must clear direct-start shell classes")
    for app_boot_guard in [
        'document.documentElement.classList.add("app-start-requested")',
        "html.app-start-requested:not(.app-ready) #entryShell",
        "html.app-start-requested:not(.app-ready) #appBootLoading[hidden]",
        "正在打开捷境工作台",
        'document.documentElement.classList.add("app-ready")',
    ]:
        if app_boot_guard not in app_html + app_js:
            return fail(f"app start must hide legacy entry shell before JS boot completes: {app_boot_guard}")
    if f'const JIEJING_SITE_VERSION = "{frontend_asset_version}"' not in index_html:
        return fail("public homepage must expose the current JIEJING site version marker")
    # Accepted v12 is a new public visual surface; keep business/session checks below.
    from test_jiejing_homepage_maturity import main as homepage_visual_contract
    homepage_visual_contract()
    for first_day_marker in [
        "login_onboarding_ai_ceo_v3", "saas-first-day-path-strip",
        'data-first-day-path="login_onboarding_ai_ceo_v3"', "刷新不会跳过向导",
        "一句话交给 JV AI",
    ]:
        if first_day_marker not in app_js + app_html + styles_css:
            return fail(f"first-day path marker missing: {first_day_marker}")
    for pending_marker in [
        "merchant_clear_pending_v4", "function scheduleSaasAiCeoPendingWatchdog",
        "function updateCeoAssistantPendingMessage", "model_response_delayed",
        "真实发布、付款、退款、广告、授权和敏感客服承诺不会自动执行",
        ".saas-ai-ceo-pending-status",
    ]:
        if pending_marker not in app_js + styles_css:
            return fail(f"merchant-safe pending marker missing: {pending_marker}")
    deploy_script = (ROOT / "tools/jiejing_deploy_frontend_staging_with_key.ps1").read_text(encoding="utf-8")
    if "Unable to derive frontend asset version from app.html" not in deploy_script or "DEPLOY_FRONTEND_VERSION=$frontendVersion" not in deploy_script:
        return fail("frontend deploy must derive the app version")
    for brand in ["favicon.ico", "assets/jiejing-app-icon.svg", "assets/jiejing-logo-lockup.svg", "assets/jiejing-logo-mark.svg"]:
        if brand not in deploy_script:
            return fail(f"frontend deploy missing brand: {brand}")
    for forbidden_brand in ["捷境 Jiejing", "Jiejing / 捷境", "Jiejing AI CEO", "Jiejing Merchant"]:
        if forbidden_brand in index_html + app_html + privacy_html:
            return fail(f"public brand casing: {forbidden_brand}")
    for expected in [r'[/\bJingjing\b/g, "JIEJING"]', r'[/\bJiejing\b/g, "JIEJING"]', "JIEJING Listing"]:
        if expected not in app_js:
            return fail(f"runtime brand guard missing: {expected}")
    if 'localStorage.getItem("jiejing_saas_backend_token")' in app_html:
        return fail("public app entry must not accept legacy localStorage bearer tokens")
    for forbidden_frontend_secret in [
        "jiejing-demo-password",
        "demo@jiejing.local",
    ]:
        if forbidden_frontend_secret in app_js + app_html + index_html:
            return fail(f"public frontend must not carry default demo credential: {forbidden_frontend_secret}")
    for relative_path in [
        "deploy/Caddyfile.public-staging",
        "deploy/nginx.public-staging.conf",
        "deploy/jiejing-route-a-edge.env.example",
        "deploy/jiejing-saas.infra.env.example",
        "deploy/jiejing-saas.tencent-managed.env.example",
        "tools/jiejing_deploy_channel_doctor.py",
        "tools/jiejing_staging_deploy.py",
        "tools/jiejing_deploy_frontend_staging_with_key.ps1",
        "tools/jiejing_prepare_stable_deploy_key.ps1",
    ]:
        active_text = (ROOT / relative_path).read_text(encoding="utf-8")
        if "42.194.158.47" in active_text or "mentioned-shake-inter-critical.trycloudflare.com" in active_text:
            return fail(f"active deploy config still points at retired Guangzhou staging route: {relative_path}")

    compose_public = (ROOT / "deploy/docker-compose.public-staging.yml").read_text(encoding="utf-8")
    compose_https = (ROOT / "deploy/docker-compose.public-https-staging.yml").read_text(encoding="utf-8")
    managed_env_template = (ROOT / "deploy/jiejing-saas.tencent-managed.env.example").read_text(encoding="utf-8")
    deploy_script = (ROOT / "tools/jiejing_deploy_frontend_staging_with_key.ps1").read_text(encoding="utf-8")
    prelaunch_runbook = (ROOT / "docs/JIEJING_PRELAUNCH_INTERNAL_HARDENING_RUNBOOK_20260620.md").read_text(encoding="utf-8")
    public_staging_contracts = [
        (
            "docker-compose.public-staging.yml",
            compose_public,
            'JIEJING_EBAY_DRAFT_SAVE_LIVE: "false"',
            'JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: "disabled_public_staging"',
        ),
        (
            "docker-compose.public-https-staging.yml",
            compose_https,
            'JIEJING_EBAY_DRAFT_SAVE_LIVE: "true"',
            'JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: "controlled_unpublished_draft_only"',
        ),
    ]
    for compose_name, compose_text, draft_marker, policy_marker in public_staging_contracts:
        for marker in [
            'JIEJING_ENABLE_REAL_PLATFORM_WRITES: "false"',
            'JIEJING_EBAY_WRITE_LIVE: "false"',
            draft_marker,
            policy_marker,
        ]:
            if compose_text.count(marker) != 2:
                return fail(
                    "public staging API and worker must own the same narrow write contract: "
                    f"{compose_name} expected two declarations of {marker}"
                )
    with TemporaryDirectory() as temp_dir:
        candidate_deploy = Path(temp_dir) / "workspace" / "deploy"
        private_root = Path(temp_dir) / "private"
        candidate_deploy.mkdir(parents=True)
        private_root.mkdir()
        compose_path = candidate_deploy / "docker-compose.public-https-staging.yml"
        managed_path = private_root / "tencent-managed.env"
        secret_path = private_root / "jiejing-saas.staging-oauth.env"
        postgres_path = private_root / "postgres-localqueue.env"
        compose_path.write_text(compose_https, encoding="utf-8")
        managed_path.write_text(
            (ROOT / "deploy/jiejing-saas.tencent-managed.env.example").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        secret_path.write_text(
            (ROOT / "deploy/jiejing-saas.staging-oauth.env.example").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        postgres_path.write_text(
            (ROOT / "deploy/jiejing-saas.postgres-localqueue.env.example").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/jiejing_runtime_env_overlap_guard.py"),
                "check",
                "--compose",
                str(compose_path),
                "--managed-env",
                str(managed_path),
                "--secret-env",
                str(secret_path),
                "--postgres-env",
                str(postgres_path),
                "--json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            return fail(f"public HTTPS narrow draft-save ownership guard failed: {completed.stderr or completed.stdout}")
        guard_report = json.loads(completed.stdout)
        if not guard_report["ok"] or guard_report["blockers"] or guard_report["secret_exposed"]:
            return fail("public HTTPS narrow draft-save ownership guard did not pass safely")
    if "../privacy.html:/usr/share/nginx/html/privacy.html:ro" not in compose_https:
        return fail("public HTTPS staging frontend must serve privacy.html for eBay OAuth developer configuration")
    for mounted_page in [
        "../terms.html:/usr/share/nginx/html/terms.html:ro",
        "../refund-policy.html:/usr/share/nginx/html/refund-policy.html:ro",
        "../support.html:/usr/share/nginx/html/support.html:ro",
        "../risk-disclosure.html:/usr/share/nginx/html/risk-disclosure.html:ro",
    ]:
        if mounted_page not in compose_https:
            return fail(f"public HTTPS staging frontend must serve legal page: {mounted_page}")
    for deploy_page in ["privacy.html", "terms.html", "refund-policy.html", "support.html", "risk-disclosure.html"]:
        if deploy_page not in deploy_script:
            return fail(f"frontend deploy archive must sync legal page: {deploy_page}")
    for deploy_archive_marker in [
        '"tar"',
        "$patchArchive",
        "$remoteArchive",
        "tar -xzf",
        "install -m 0644",
    ]:
        if deploy_archive_marker not in deploy_script:
            return fail(f"frontend deploy script must use the atomic archive deploy path: {deploy_archive_marker}")
    for marker in [
        'JIEJING_INCIDENT_RUNBOOK_PUBLISHED: "true"',
        'JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED: "true"',
        'JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED: "true"',
        'JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED: "true"',
        'JIEJING_TEST_DATA_GOVERNANCE_REVIEWED: "true"',
    ]:
        if marker not in compose_https:
            return fail(f"public HTTPS staging compose missing prelaunch evidence flag: {marker}")
    for marker in [
        "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED=true",
        "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED=true",
    ]:
        if marker not in managed_env_template:
            return fail(f"managed runtime env template missing operations evidence flag: {marker}")
        compose_marker = marker.replace("=true", ': "true"')
        if compose_marker in compose_public or compose_marker in compose_https:
            return fail(f"operations evidence flag must not be owned by Compose: {compose_marker}")
    for marker in [
        "Do not create live Stripe Checkout sessions.",
        "Do not start or repeat eBay OAuth.",
        "Do not delete smoke data automatically.",
        "Access logs must not record request bodies.",
        "High-cost API groups are rate-limited.",
        "Cleanup is not automatic.",
    ]:
        if marker not in prelaunch_runbook:
            return fail(f"prelaunch hardening runbook missing marker: {marker}")
    for marker in [
        "隐私与数据边界说明",
        "在线付款已开放为一次性 30 天订阅，不会自动续费",
        "eBay 授权凭证、模型连接凭证和支付连接密钥",
        "服务条款",
        "风险披露与确认中心边界",
    ]:
        if marker not in privacy_html:
            return fail(f"privacy page missing staging data-boundary marker: {marker}")
    for marker in [
        "捷境服务条款",
        "在线付款已开放为一次性 30 天订阅，不会自动续费或自动扣款",
        "禁止自动执行的动作",
        "试用数据默认只标记和报告，不自动删除",
        "基础订阅是软件功能费",
        "eBay 费用、广告费、物流和退款不是捷境代扣",
        "更新日期：2026-08-22",
    ]:
        if marker not in terms_html:
            return fail(f"terms page missing launch-boundary marker: {marker}")
    for marker in [
        "捷境退款政策",
        "在线付款已经开放，不会自动续费或自动扣款",
        "退款必须由人工审核并在后端执行",
        "eBay 成交费、广告费、店铺订阅费、物流费、采购款、买家退款",
        "当前尚未提供匿名客服入口",
        "更新日期：2026-08-22",
    ]:
        if marker not in refund_html:
            return fail(f"refund policy page missing payment-review marker: {marker}")
    for marker in [
        "捷境客服与反馈入口",
        "在线付款已经开放",
        "意见箱只记录流程意见和上下文编号，不保存密钥、平台凭证或身份资料",
        "不会替商家直接发布商品、改价、改库存、退款、投广告",
        "提交前请准备",
        "更新日期：2026-08-22",
    ]:
        if marker not in support_html:
            return fail(f"support page missing payment-review marker: {marker}")
    for marker in [
        "风险披露与确认中心边界",
        "所有高风险动作都必须由商家或授权管理员确认",
        "红色阻断",
        "绿色只表示当前证据满足系统预检",
    ]:
        if marker not in risk_html:
            return fail(f"risk disclosure page missing confirmation-boundary marker: {marker}")
    for marker in (
        '<meta name="description"',
        '<link rel="canonical" href="https://app.jiejing.shop/"',
        'property="og:title"',
        'name="twitter:card"',
        'href="./terms.html"',
        'href="./privacy.html"',
        'href="./refund-policy.html"',
        'href="./support.html"',
    ):
        if marker not in index_html:
            return fail(f"public landing discovery/trust marker is missing: {marker}")
    sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    if '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' not in sitemap or "<loc>https://app.jiejing.shop/</loc>" not in sitemap:
        return fail("public sitemap must be real XML with the canonical production domain")

    if 'runtimeApiBase: "http://127.0.0.1:8765"' in app_js:
        return fail("runtime API base is still hardcoded in initial state")
    if 'saasApiBase: "http://127.0.0.1:8788"' in app_js:
        return fail("SaaS API base is still hardcoded in initial state")
    for marker in [
        "resolveJiejingApiBase",
        "function isPlausibleJiejingApiBase",
        'url.protocol !== "https:"',
        "url.origin !== window.location.origin",
        "Public SaaS requests must stay on the current HTTPS origin",
        "function safeEbayOAuthAuthorizationUrl",
        '"auth.ebay.com"',
        '"auth.sandbox.ebay.com"',
        'url.pathname !== "/oauth2/authorize"',
        "url.port",
        "url.username",
        "url.password",
        "validatedSaasReadOnlyOAuthAuthorizationUrl(rawUrl, planScopes, planState)",
        "validatedSaasUnpublishedDraftOAuthAuthorizationUrl(value = \"\", expectedState = \"\")",
        "validatedSaasUnpublishedDraftOAuthPlanResponse(payload, store, existingConfirmation)",
        "window.JIEJING_CONFIG",
        "__JIEJING_CONFIG__",
        "jiejing_saas_api_base",
        "jiejing_runtime_api_base",
        "jiejing-saas-api-base",
        "jiejing-runtime-api-base",
        "jiejing-saas-operator-bootstrap",
        "inferJiejingSameOriginApiBase",
        "defaultJiejingDemoBootstrapEnabled",
        "saasDemoBootstrapEnabled",
        "当前公网页面需要已有捷境账号会话",
        "/secret-refs?store_id=",
        "eBay 官方授权",
        "敏感凭证不进入浏览器",
        'optionalSaasFetchFast(`/data-packets?platform=ebay&limit=5`',
        "function getLatestSaasDataPacketRecord",
        "function saasKnownStoreCandidates",
        'saasFetch("/reports?limit=24")',
        'saasFetch("/confirmations?limit=40")',
        "renderSaasEbaySyncStatusPanel",
        "renderSaasAiCeoOutputPanel",
        "renderSaasConfirmPanel",
        "function renderSaasModuleAiGoalStrip",
        "function renderSaasModuleAiGoalStripIntoView",
        'data-ai-ceo-module-goal-strip="ai_ceo_module_goal_v1"',
        "小批量实验目标已带入",
        "高风险动作已拦住",
        "saasRealBackendBindingStatus",
        "数据连接",
        "saasWorkbenchReportDetailMarkup",
        "saasWorkbenchConfirmationDetailMarkup",
        "saas-ai-report-detail",
        "saas-confirm-detail",
        "shouldShowLegacyDemoControls",
        "blockLegacyDemoPublishAction",
        "isPublicJiejingOrigin",
        "renderSaasWorkbenchTruthPanel",
        "renderSaasMerchantEvidencePanel",
        "saasModelValueGate",
        "Market Report",
        "Listing Package",
        "真实写入",
        "renderSaasLoginCard",
        "data-saas-login-card",
        "function renderSaasMerchantExecutiveCockpit",
        "saas-executive-cockpit",
        "saas-cockpit-risk-queue",
        "saas-executive-evidence-rail",
        "<b>凭证安全</b>不在浏览器显示",
        "function saasBackendPublishImpact",
        "function saasBackendPublishDecisionGate",
        "function renderSaasPublishCommandSummaryPanel",
        "saas-backend-preflight-route",
        "saas-publish-command-summary",
        "confirmation_required_no_direct_write",
        "register-session",
        "hasSaasProtectedSessionCandidate",
        "shouldAttachSaasBearerToken",
        "purgeLegacySaasStoredBearerToken",
        "operatorBootstrapEmail",
        "operatorBootstrapPassword",
        "resetSaasProtectedWorkbenchState",
        "saasLastPublicRefreshSkippedProtectedFetch",
        "shouldFetchDirectRuntimeApi",
        "refreshSaasEbayDiagnostics",
        "isSaasEbayReadOnlyAuthorized",
        "saasEbayReadOnlyResourcePayload",
        "eBay 只读授权已经完成；不会再次生成授权链接",
        "saasAiCeoStageCoverage",
        "saas-ai-stage-strip",
        "freshness.status",
        "route_health",
        "currentSaasEbayCallbackUrl",
        "copy-ebay-return-url",
        "官方连接返回地址",
        'productFeedbackOutbox: "jiejing_saas_product_feedback_outbox_v1"',
        'productFeedbackReceipts: "jiejing_saas_product_feedback_receipts_v1"',
        'productFeedbackMigration: "jiejing_saas_product_feedback_migration_v1"',
        "function saasProductFeedbackIdentityParts",
        "function prepareSaasProductFeedbackScopeAfterIdentity",
        'saasFetchWithTimeout(\n      "/product-feedback"',
        "window.addEventListener(\"online\"",
    ]:
        if marker not in app_js + app_html:
            return fail(f"missing frontend staging config marker: {marker}")
    for endpoint in ["/model/value-gate"]:
        if (
            f'saasFetch("{endpoint}")' not in app_js + app_html
            and f'optionalSaasFetch("{endpoint}"' not in app_js + app_html
            and f'optionalSaasFetchFast("{endpoint}"' not in app_js + app_html
            and f'optionalSaasFetchFast(`{endpoint}?' not in app_js + app_html
        ):
            return fail(f"missing frontend staging config marker: {endpoint} fetch")
    for marker in [
        "cursorGlow",
        "merchant-guide",
        "entryModeGrid",
        "openLoggedInExperience",
        "./app.html",
    ]:
        if marker not in index_html:
            return fail(f"missing interactive homepage/onboarding marker: {marker}")
    homepage_motion_js = (ROOT / "assets/homepage-finish.js").read_text(encoding="utf-8")
    if "pointermove" not in homepage_motion_js:
        return fail("homepage motion module must retain pointer interaction")
    homepage_css = (ROOT / "assets/homepage-finish.css").read_text(encoding="utf-8")
    price_rule = re.search(r"\.price\s*\{([^}]+)\}", homepage_css)
    if not price_rule or not re.search(r"white-space\s*:\s*nowrap", price_rule.group(1)):
        return fail("public pricing cards must keep prices on one stable line")
    if "体验流程会用倒流香炉跑一遍" in index_html:
        return fail("homepage onboarding copy must not route real testing through a fixed sample product")
    for stale_public_copy in [
        "主页、向导和工作台只讲同一条",
        "不是通用 ERP，也不是通用 Agent 市场",
    ]:
        if stale_public_copy in index_html + app_html:
            return fail(f"public product copy should avoid abstract internal positioning: {stale_public_copy}")
    for merchant_outcome_copy in [
        "把重复工作交给 AI，把时间留给经营。",
        "资料不足不编造",
        "侵权风险初筛，仍需商家核对",
    ]:
        if merchant_outcome_copy not in re.sub(r"<[^>]+>", "", index_html + app_html):
            return fail(f"public product copy should explain the merchant outcome: {merchant_outcome_copy}")
    if "免费体验不绑卡、不自动续费" not in index_html:
        return fail("homepage onboarding copy should explain the bounded free trial")
    for onboarding_control_marker in [
        "onboardingDeferredSettingsFields",
        "onboarding-lite-path",
        "onboarding-lite-safety",
        "设置里可继续补接",
        "不需要一次配置完所有平台接口",
        "发布、改价、退款、广告预算、采购付款和买家承诺都会进入确认中心",
        "onboardingLaunchMapMarkup",
        "onboardingControlStripMarkup",
        "onboardingChoiceContextMarkup",
        "onboardingSummaryMetricsMarkup",
        "onboardingLaunchReadinessMarkup",
        "onboarding-launch-map",
        "onboarding-control-strip",
        "onboarding-choice-context",
        "onboarding-summary-metrics",
        "onboarding-summary-launch",
        "官方只读优先",
        "可跳过授权继续",
        "确认中心兜底",
        "首日安全边界",
    ]:
        if onboarding_control_marker not in app_js + app_html + styles_css:
            return fail(f"missing onboarding control-room marker: {onboarding_control_marker}")
    if '"sourceApiMode",\n    "fulfillmentMode",' in app_js or '"returnPolicy",\n    "feeInsightMode",' in app_js:
        return fail("public first-day onboarding must keep advanced connection details in Settings instead of the main route")
    for billing_guardrail_marker in [
        "function renderSaasMerchantPricingModelPanel",
        "saas-merchant-pricing-model",
        "免费体验不含生图点数；有店铺含 1,000 素材点，多店铺含 3,000 素材点",
        "subscription_ai_media_platform_v1",
        "saas-merchant-pricing-split",
        "¥99 / 30 天",
        "¥0 / ¥99 / ¥199",
        "商家自带模型",
        "图片 / 视频",
        "eBay 费用、广告费、物流和退款不是捷境代扣",
        "function renderSaasMerchantBillingCurrentStatusPanel",
        "function renderSaasMerchantBillingPlainSummaryPanel",
        "merchant_billing_plain_summary_v1",
        "订阅和用量总览",
        "套餐权益、商家模型、素材点和平台成本清楚可查",
        "套餐已包含素材点；用完后才需要加购",
        "有店铺含 1,000 素材点，多店铺含 3,000 素材点",
        "不消耗素材点",
        "生成前显示预计点数",
        "高成本任务暂停",
        "仍可看历史和确认中心",
        "微信扫码付款",
        "敏感凭证不进入浏览器",
    ]:
        if billing_guardrail_marker not in app_js + app_html + styles_css:
            return fail(f"missing merchant billing guardrail marker: {billing_guardrail_marker}")
    for internal_billing_marker in (
        "no_charge_launch_rehearsal",
        "saas-merchant-billing-rehearsal-actions",
        "renderSaasBillingDomainCutoverReviewPanel",
        "saasBillingDomainCutoverReviewState",
        "saasPaidLaunchBlockerCopy",
    ):
        if internal_billing_marker in app_js + app_html:
            return fail(f"merchant runtime still contains an internal billing control: {internal_billing_marker}")
    snapshot_start = app_js.index("function buildSaasProtectedStateSnapshot")
    snapshot_end = app_js.index("function saveSaasProtectedStateSnapshot", snapshot_start)
    snapshot_body = app_js[snapshot_start:snapshot_end]
    for forbidden_snapshot_marker in (
        "saasBillingCheckout",
        "saasBillingProviderRehearsal",
        "saasBillingDomainCutoverRehearsal",
        "saasEdgeCutoverPreflight",
        "saasPaidLaunchApprovalPacket",
        "saasCommercialLaunchGate",
    ):
        if forbidden_snapshot_marker in snapshot_body:
            return fail(f"browser fast-restore snapshot must not persist backend control state: {forbidden_snapshot_marker}")
    for homepage_return_marker in [
        "function currentPublicHomepageUrl",
        "function openCurrentPublicHomepage",
        'new URL("./index.html", window.location.href)',
        'target.searchParams.set("source", source)',
        'target.searchParams.set("start", "site")',
        'currentPublicHomepageUrl("intro", "workbench_logo")',
        '"app_embedded_site_return"',
        'target.hash = scrollTarget || "intro"',
    ]:
        if homepage_return_marker not in app_js:
            return fail(f"workbench logo should return to current public homepage: {homepage_return_marker}")
    reveal_start = app_js.index("function revealSite")
    reveal_end = app_js.index("function openCurrentPublicHomepage", reveal_start)
    reveal_body = app_js[reveal_start:reveal_end]
    if 'siteShell.classList.remove("is-hidden")' in reveal_body:
        return fail("embedded app.html homepage shell must not be exposed; return to index.html instead")
    if "currentPublicHomepageUrl(scrollTarget, \"app_embedded_site_return\")" not in reveal_body:
        return fail("embedded app homepage returns must delegate to the current public index.html")
    for app_entry_marker in [
        'publicHomeUrl.searchParams.set("source", "legacy_app_entry")',
        'publicHomeUrl.searchParams.set("start", "site")',
        "window.location.replace(publicHomeUrl.toString())",
    ]:
        if app_entry_marker not in app_html:
            return fail(f"legacy app.html marketing entry must redirect to current public homepage: {app_entry_marker}")
    refresh_start = app_js.index("async function refreshSaasState")
    refresh_end = app_js.index("function clearSaasProductFeedbackLiveIdentity", refresh_start)
    refresh_body = app_js[refresh_start:refresh_end]
    if "const canFetchProtectedState = hasSaasProtectedSessionCandidate();" not in refresh_body:
        return fail("refreshSaasState must check for a real session or explicit operator bootstrap before protected reads")
    guard_index = refresh_body.find("if (!canFetchProtectedState)")
    store_fetch_index = refresh_body.find("const store = await ensureSaasDemoStoreAndConnection();")
    if guard_index < 0 or store_fetch_index < 0 or guard_index > store_fetch_index:
        return fail("refreshSaasState must skip protected store/report reads before ensuring a store")
    cached_restore_index = refresh_body.index("hydrateSaasProtectedStateFromCache({ me: coreMe,")
    live_stores_index = refresh_body.index("state.saasStores = coreStores.stores || [];")
    if cached_restore_index < live_stores_index:
        return fail("business cache must only hydrate after live identity and store membership are applied")
    if "hydrateSaasProtectedStateFromCache()" in refresh_body:
        return fail("refresh must not hydrate a protected snapshot without live scope evidence")
    for endpoint in [
        "live-read-plan",
        "http-client-dry-run",
        "credential-preflight",
    ]:
        if endpoint in refresh_body and 'method: "POST"' in refresh_body:
            return fail(f"default refreshSaasState must not POST {endpoint}; diagnostics must be explicit")
    for forbidden in [
        "saas_frontend_demo_input",
        "Front-end demo approval. ExecutionService remains demo/no-platform-write.",
        "public_demo: true",
    ]:
        if forbidden in app_js:
            return fail(f"SaaS production path still carries demo-only marker: {forbidden}")
    if "https://api.ebay.com/oauth/api_scope/sell.finances" not in app_js:
        return fail("frontend eBay OAuth scopes must include sell.finances for the first read-only packet")
    if "saasLatestOAuthUrl" not in app_js or "打开 eBay 官方授权页" not in app_js or 'target="_blank"' not in app_js:
        return fail("frontend should retain a clickable eBay authorization URL")
    if '["blocked", "pending", "published"].includes(state.publishFlow.status) &&\n    shouldShowLegacyDemoControls()' not in app_js:
        return fail("legacy publish confirmation card must be hidden from real SaaS merchant mode")
    if "if (blockLegacyDemoPublishAction()) return;" not in app_js:
        return fail("legacy demo publish actions must be blocked in real SaaS merchant mode")
    if 'start === "landing"' not in app_js or 'params.get("entry") === "1"' not in app_js:
        return fail("public workbench default must keep an explicit marketing-page override")
    if "(isPublicJiejingOrigin() && !start && !explicitMarketingEntry)" in app_js:
        return fail("public root must not auto-open the workbench; homepage must be the default")
    if 'start === "app" ||\n    params.get("onboarded") === "1"' not in app_js:
        return fail("workbench must remain available through an explicit app/onboarded route")
    if 'saasFetch("/auth/register"' not in app_js:
        return fail("workbench must support real SaaS account registration instead of a demo-only auth path")
    if "state.saasReadiness = null" in app_js:
        return fail("public readiness evidence should survive session-required failures")
    workbench_start = app_js.index("function renderSaasMerchantWorkbenchPanel")
    workbench_end = app_js.index("function renderSaasMerchantPublicMvpPanel", workbench_start)
    workbench_body = app_js[workbench_start:workbench_end]
    public_mvp_start = app_js.index("function renderSaasMerchantPublicMvpPanel")
    public_mvp_end = app_js.index("function renderSaasWorkbenchTruthPanel", public_mvp_start)
    public_mvp_body = app_js[public_mvp_start:public_mvp_end]
    for advanced_panel in [
        "renderSaasMerchantProviderHubPanel(ctx)",
        "renderSaasMerchantPermissionPanel()",
        "renderSaasMerchantIpRiskPanel()",
        "renderSaasMerchantMemoryPanel()",
        "renderSaasMerchantModelProviderPanel(ctx)",
    ]:
        if advanced_panel in workbench_body or advanced_panel in public_mvp_body:
            return fail(f"merchant workbench should keep advanced/settings panel out of the daily MVP path: {advanced_panel}")
    settings_start = app_js.index("function saasSettingsTabDefinitions")
    settings_end = app_js.index("function renderSaasSettingsCleanLayout", settings_start)
    settings_body = app_js[settings_start:settings_end]
    for settings_panel in [
        "renderSaasMerchantModelProviderPanel(ctx)",
        "renderSaasMerchantPermissionPanel()",
        "renderSaasSettingsDataPanel(ctx)",
        "renderSaasMerchantBillingPlainSummaryPanel(ctx)",
        "renderSaasMerchantMediaCreditsPanel()",
        "renderSaasMerchantDomesticPaymentPanel(ctx)",
    ]:
        if settings_panel not in settings_body:
            return fail(f"settings center must retain the merchant configuration panel: {settings_panel}")
    runtime_start = app_js.index("async function refreshRuntimeState")
    runtime_end = app_js.index("async function createRuntimeRunFromSaas", runtime_start)
    runtime_body = app_js[runtime_start:runtime_end]
    if "if (!shouldFetchDirectRuntimeApi())" not in runtime_body:
        return fail("public workbench must not auto-fetch direct Runtime API before an operator/local route")
    for visible_residue in [
        "演示版",
        "演示估算",
        "演示草稿",
        "演示批次",
        "Demo 生成",
        "内测试用",
        "演示样例",
        "演示口径",
        "演示状态",
        "演示字段",
        "演示目标",
    ]:
        if visible_residue in app_html:
            return fail(f"workbench HTML still carries visible demo residue: {visible_residue}")
    for forbidden_marker in [
        "workflow-demo-grid",
        "mockPreview",
        "bulk-demo-note",
        "mediaGenerateImagesDemo",
    ]:
        if forbidden_marker in app_js + app_html:
            return fail(f"public UI still carries old demo/mock DOM marker: {forbidden_marker}")
    print("PASS jiejing_frontend_staging_config")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

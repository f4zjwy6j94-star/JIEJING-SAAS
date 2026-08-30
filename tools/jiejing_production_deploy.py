#!/usr/bin/env python3
"""Deploy a verified Jiejing release candidate to the production host."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST = "43.129.169.223"
DEFAULT_PORT = 22
DEFAULT_USER = "ubuntu"
DEFAULT_KEY = Path.home() / ".ssh" / "jiejing_production_hk_ed25519"
DEFAULT_KNOWN_HOSTS = Path.home() / ".ssh" / "known_hosts"
EXPECTED_CONFIRM = "deploy app.jiejing.shop production"
ALLOWED_SCOPE = "public_staging_patch_whitelist_v1"
ATOMIC_FRONTEND_FILES = ("index.html", "app.html", "app.js", "styles.css")
PRODUCTION_REMOTE_APPLY_TIMEOUT_SECONDS = 3600
PHASE3_REQUIRED_BUNDLE_FILES = {
    "deploy/jiejing-production-evidence-auto-refresh.sh",
    "deploy/systemd/jiejing-production-evidence-refresh.service",
    "deploy/systemd/jiejing-production-evidence-refresh.timer",
    "tools/test_jiejing_production_evidence_auto_refresh_guardrails.py",
    "docs/superpowers/specs/2026-08-26-production-evidence-auto-refresh-design.md",
    "docs/superpowers/plans/2026-08-26-production-evidence-auto-refresh-implementation-plan.md",
}
REMOTE_BOOLEAN_CONTRACT = {
    "CANDIDATE_RELEASE_PERSISTED": "candidate_release_persisted",
    "ACTIVE_SWITCHED": "active_switched",
    "PRIVATE_ENV_NORMALIZATION_REQUIRED": "private_env_normalization_required",
    "PRIVATE_ENV_NORMALIZATION_PLANNED": "private_env_normalization_planned",
    "PRIVATE_ENV_NORMALIZATION_APPLIED": "private_env_normalization_applied",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Confirmation-gated atomic deploy to the Jiejing production host."
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--mode", choices=("dry_run", "apply"), default="dry_run")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--ssh-key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--known-hosts", type=Path, default=DEFAULT_KNOWN_HOSTS)
    parser.add_argument("--timeout", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle = args.bundle.resolve()
    manifest_path = args.manifest.resolve()
    if not bundle.is_file():
        return fail(f"bundle_not_found: {bundle}")
    if not manifest_path.is_file():
        return fail(f"manifest_not_found: {manifest_path}")
    if args.mode == "apply" and args.confirm != EXPECTED_CONFIRM:
        return fail("production_confirmation_mismatch")

    source_sha = git_value("rev-parse", "HEAD")
    try:
        assert_source_state(source_sha)
        allowed_files = set(apply_patch_file_list(source_sha))
        source_files_sha256 = source_commit_file_hashes(source_sha, allowed_files)
        _manifest, bundle_sha256, manifest_sha256 = validate_local_release_candidate(
            bundle,
            manifest_path,
            allowed_files,
            source_sha,
            source_files_sha256=source_files_sha256,
        )
    except ValueError as exc:
        return fail(f"bundle_archive_invalid: {exc}")
    if not args.ssh_key.is_file():
        return fail(f"ssh_key_not_found: {args.ssh_key}")
    if not args.known_hosts.is_file():
        return fail(f"known_hosts_not_found: {args.known_hosts}")

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    remote_base = f"/tmp/jiejing-production-{stamp}-{source_sha[:12]}"
    remote_zip = remote_base + ".zip"
    remote_zip_upload = remote_zip + ".uploading"
    remote_manifest = remote_base + ".manifest.json"
    remote_manifest_upload = remote_manifest + ".uploading"
    remote_dir = remote_base + ".d"
    sealed_dir = Path(tempfile.mkdtemp(prefix="jiejing-sealed-release-"))
    sealed_bundle = sealed_dir / "bundle.zip"
    sealed_manifest = sealed_dir / "manifest.json"
    try:
        shutil.copyfile(bundle, sealed_bundle)
        shutil.copyfile(manifest_path, sealed_manifest)
        validate_local_release_candidate(
            sealed_bundle,
            sealed_manifest,
            allowed_files,
            source_sha,
            expected_bundle_sha256=bundle_sha256,
            expected_manifest_sha256=manifest_sha256,
            source_files_sha256=source_files_sha256,
        )
        assert_source_state(source_sha)
        upload(args, sealed_bundle, remote_zip_upload)
        upload(args, sealed_manifest, remote_manifest_upload)
        assert_source_state(source_sha)
    except ValueError as exc:
        return fail(f"sealed_candidate_invalid: {exc}")
    finally:
        shutil.rmtree(sealed_dir, ignore_errors=True)

    dry_run = "1" if args.mode == "dry_run" else "0"
    confirm = EXPECTED_CONFIRM if args.mode == "dry_run" else args.confirm
    remote_script = "\n".join(
        [
            build_remote_integrity_prelude(
                remote_zip_upload=remote_zip_upload,
                remote_zip=remote_zip,
                expected_bundle_sha256=bundle_sha256,
                remote_manifest_upload=remote_manifest_upload,
                remote_manifest=remote_manifest,
                expected_manifest_sha256=manifest_sha256,
                remote_dir=remote_dir,
            ),
            (
                "sudo -n env "
                f"JIEJING_PRODUCTION_DEPLOY_CONFIRM={shlex.quote(confirm)} "
                f"JIEJING_PRODUCTION_DEPLOY_DRY_RUN={dry_run} "
                f"bash {shlex.quote(remote_dir + '/deploy/jiejing-production-release-apply.sh')} "
                f"{shlex.quote(remote_dir)} {shlex.quote(bundle_sha256)} "
                f"{shlex.quote(manifest_sha256)} {shlex.quote(source_sha)}"
            ),
        ]
    )
    remote_timeout = (
        PRODUCTION_REMOTE_APPLY_TIMEOUT_SECONDS
        if args.mode == "apply"
        else max(args.timeout * 20, 1200)
    )
    completed = run(
        ssh_base(args) + [f"bash -lc {shlex.quote(remote_script)}"],
        timeout=remote_timeout,
    )
    try:
        remote_contract = parse_remote_stdout_contract(completed.stdout, args.mode, source_sha)
    except ValueError as exc:
        reason = "dry_run_receipt_invalid" if args.mode == "dry_run" else "apply_receipt_invalid"
        return fail(f"{reason}: {exc}")
    print(
        json.dumps(
            {
                "status": "dry_run_passed" if args.mode == "dry_run" else "deployed",
                "mode": args.mode,
                "host": DEFAULT_HOST,
                "source_sha": source_sha,
                "bundle_sha256": bundle_sha256,
                "manifest_sha256": manifest_sha256,
                **remote_contract,
                "stdout_tail": completed.stdout[-5000:],
                "stderr_tail": completed.stderr[-2000:],
                "secret_exposed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_remote_stdout_contract(output: str, mode: str, expected_source_sha: str) -> dict[str, bool]:
    lines = [line.strip() for line in output.splitlines()]

    def receipt_values(key: str) -> list[str]:
        prefix = key + "="
        return [line[len(prefix) :] for line in lines if line.startswith(prefix)]

    def exact_receipt_value(key: str) -> str:
        values = receipt_values(key)
        if len(values) != 1:
            raise ValueError(f"receipt_count:{key}:{len(values)}")
        return values[0]

    mode_marker = "JIEJING_PRODUCTION_DEPLOY_DRY_RUN" if mode == "dry_run" else "JIEJING_PRODUCTION_DEPLOY_APPLIED"
    opposite_marker = "JIEJING_PRODUCTION_DEPLOY_APPLIED" if mode == "dry_run" else "JIEJING_PRODUCTION_DEPLOY_DRY_RUN"
    if exact_receipt_value(mode_marker) != "1":
        raise ValueError(f"receipt_value:{mode_marker}")
    opposite_values = receipt_values(opposite_marker)
    if opposite_values:
        raise ValueError(f"receipt_count:{opposite_marker}:{len(opposite_values)}")
    if exact_receipt_value("SOURCE_COMMIT") != expected_source_sha:
        raise ValueError("source_commit_mismatch")
    observed: dict[str, bool] = {}
    for raw_line in lines:
        key, separator, raw_value = raw_line.partition("=")
        if not separator or key not in REMOTE_BOOLEAN_CONTRACT:
            continue
        field = REMOTE_BOOLEAN_CONTRACT[key]
        if field in observed:
            raise ValueError(f"duplicate:{key}")
        if raw_value not in {"0", "1"}:
            raise ValueError(f"invalid_boolean:{key}")
        observed[field] = raw_value == "1"
    missing = sorted(set(REMOTE_BOOLEAN_CONTRACT.values()).difference(observed))
    if missing:
        raise ValueError("missing:" + ",".join(missing))
    expected_persistence = mode == "apply"
    if observed["candidate_release_persisted"] is not expected_persistence:
        raise ValueError("candidate_persistence_mismatch")
    if observed["active_switched"] is not expected_persistence:
        raise ValueError("active_switch_mismatch")
    if observed["private_env_normalization_planned"] is not observed["private_env_normalization_required"]:
        raise ValueError("normalization_plan_mismatch")
    expected_applied = mode == "apply" and observed["private_env_normalization_required"]
    if observed["private_env_normalization_applied"] is not expected_applied:
        raise ValueError("normalization_apply_mismatch")
    return observed


def assert_source_state(expected_source_commit: str) -> None:
    current = git_value("rev-parse", "HEAD")
    if current != expected_source_commit or not re.fullmatch(r"[0-9a-f]{40}", current):
        raise ValueError("source_commit_changed")
    if git_value("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("deploy_requires_clean_git_worktree")


def validate_local_release_candidate(
    bundle: Path,
    manifest_path: Path,
    allowed_files: set[str],
    expected_source_commit: str,
    *,
    expected_bundle_sha256: str = "",
    expected_manifest_sha256: str = "",
    source_files_sha256: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str, str]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"manifest_invalid:{type(exc).__name__}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("manifest_invalid_type")
    bundle_sha256 = sha256(bundle)
    manifest_sha256 = sha256(manifest_path)
    if expected_bundle_sha256 and bundle_sha256 != expected_bundle_sha256:
        raise ValueError("candidate_bundle_changed")
    if expected_manifest_sha256 and manifest_sha256 != expected_manifest_sha256:
        raise ValueError("candidate_manifest_changed")
    if str(manifest.get("zip_sha256") or "").lower() != bundle_sha256:
        raise ValueError("bundle_sha256_mismatch")
    if manifest.get("scope") != ALLOWED_SCOPE:
        raise ValueError("manifest_scope_invalid")
    if manifest.get("real_platform_writes_enabled") is not False:
        raise ValueError("manifest_real_write_state_unsafe")
    validate_zip(bundle, allowed_files=allowed_files)
    validate_bundle_manifest(bundle, manifest, allowed_files, expected_source_commit)
    validate_bundle_matches_source_commit(
        bundle,
        allowed_files,
        expected_source_commit,
        source_files_sha256=source_files_sha256,
    )
    validate_atomic_frontend_release(bundle, manifest)
    validate_bundle_javascript(bundle)
    return manifest, bundle_sha256, manifest_sha256


def source_commit_file_hashes(
    source_commit: str,
    allowed_files: set[str],
) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source_commit_invalid")
    return {
        name: hashlib.sha256(git_blob_bytes(source_commit, name)).hexdigest()
        for name in sorted(allowed_files)
    }


def git_blob_bytes(source_commit: str, relative_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{source_commit}:{relative_path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise ValueError(f"source_commit_blob_unavailable:{relative_path}")
    return completed.stdout


def validate_bundle_matches_source_commit(
    bundle: Path,
    allowed_files: set[str],
    source_commit: str,
    *,
    source_files_sha256: dict[str, str] | None = None,
) -> None:
    expected = (
        source_commit_file_hashes(source_commit, allowed_files)
        if source_files_sha256 is None
        else source_files_sha256
    )
    if set(expected) != allowed_files:
        raise ValueError("source_commit_hash_scope_invalid")
    with zipfile.ZipFile(bundle, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != allowed_files:
            raise ValueError("source_commit_bundle_scope_invalid")
        for name in sorted(allowed_files):
            observed = hashlib.sha256(archive.read(name)).hexdigest()
            if observed != expected[name]:
                raise ValueError(f"bundle_source_commit_mismatch:{name}")


def build_remote_integrity_prelude(
    *,
    remote_zip_upload: str,
    remote_zip: str,
    expected_bundle_sha256: str,
    remote_manifest_upload: str,
    remote_manifest: str,
    expected_manifest_sha256: str,
    remote_dir: str,
) -> str:
    return "\n".join(
        [
            "set -euo pipefail",
            f"REMOTE_ZIP_UPLOAD={shlex.quote(remote_zip_upload)}",
            f"REMOTE_ZIP={shlex.quote(remote_zip)}",
            f"REMOTE_MANIFEST_UPLOAD={shlex.quote(remote_manifest_upload)}",
            f"REMOTE_MANIFEST={shlex.quote(remote_manifest)}",
            f"REMOTE_DIR={shlex.quote(remote_dir)}",
            "cleanup_remote_artifacts() {",
            "  local original_rc=$? cleanup_rc=0",
            "  trap - EXIT",
            "  rm -f -- \"$REMOTE_ZIP_UPLOAD\" \"$REMOTE_ZIP\" || cleanup_rc=1",
            "  rm -f -- \"$REMOTE_MANIFEST_UPLOAD\" \"$REMOTE_MANIFEST\" || cleanup_rc=1",
            "  rm -rf -- \"$REMOTE_DIR\" || cleanup_rc=1",
            "  if [[ \"$original_rc\" != \"0\" ]]; then exit \"$original_rc\"; fi",
            "  exit \"$cleanup_rc\"",
            "}",
            "case \"$REMOTE_ZIP_UPLOAD\" in /tmp/jiejing-production-*.zip.uploading) ;; *) exit 72 ;; esac",
            "case \"$REMOTE_ZIP\" in /tmp/jiejing-production-*.zip) ;; *) exit 72 ;; esac",
            "case \"$REMOTE_MANIFEST_UPLOAD\" in /tmp/jiejing-production-*.manifest.json.uploading) ;; *) exit 72 ;; esac",
            "case \"$REMOTE_MANIFEST\" in /tmp/jiejing-production-*.manifest.json) ;; *) exit 72 ;; esac",
            "case \"$REMOTE_DIR\" in /tmp/jiejing-production-*.d) ;; *) exit 72 ;; esac",
            "trap cleanup_remote_artifacts EXIT",
            "verify_received_sha256() {",
            "  local expected=\"$1\" path=\"$2\" observed",
            "  observed=\"$(sha256sum -- \"$path\" | awk '{print $1}')\"",
            "  if [[ \"$observed\" != \"$expected\" ]]; then",
            "    printf 'REMOTE_ARTIFACT_SHA256_MISMATCH=%s\\n' \"$path\" >&2",
            "    return 1",
            "  fi",
            "}",
            f"verify_received_sha256 {shlex.quote(expected_bundle_sha256)} \"$REMOTE_ZIP_UPLOAD\"",
            f"verify_received_sha256 {shlex.quote(expected_manifest_sha256)} \"$REMOTE_MANIFEST_UPLOAD\"",
            "mv -f -- \"$REMOTE_ZIP_UPLOAD\" \"$REMOTE_ZIP\"",
            "mv -f -- \"$REMOTE_MANIFEST_UPLOAD\" \"$REMOTE_MANIFEST\"",
            f"verify_received_sha256 {shlex.quote(expected_bundle_sha256)} \"$REMOTE_ZIP\"",
            f"verify_received_sha256 {shlex.quote(expected_manifest_sha256)} \"$REMOTE_MANIFEST\"",
            "rm -rf -- \"$REMOTE_DIR\"",
            "mkdir -m 0700 -p \"$REMOTE_DIR\"",
            "unzip -tq \"$REMOTE_ZIP\" >/dev/null",
            "unzip -q \"$REMOTE_ZIP\" -d \"$REMOTE_DIR\"",
        ]
    )


def validate_zip(path: Path, *, allowed_files: set[str] | None = None) -> None:
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        if not names:
            raise ValueError("empty")
        if len(names) != len(set(names)):
            raise ValueError("duplicate_entries")
        if allowed_files is not None and set(names) != allowed_files:
            raise ValueError("bundle_whitelist_mismatch")
        required = {
            "index.html",
            "app.html",
            "app.js",
            "styles.css",
            "Dockerfile.saas",
            "deploy/docker-compose.production-pilot.yml",
            "deploy/jiejing-production-release-apply.sh",
            "jiejing_saas/migrations/002_media_credit_buckets_postgres.sql",
            "jiejing_saas/migrations/003_runtime_schema_reconciliation_postgres.sql",
            "tools/jiejing_secret_scan.py",
        } | PHASE3_REQUIRED_BUNDLE_FILES
        missing = sorted(required.difference(names))
        if missing:
            raise ValueError("missing_required:" + ",".join(missing))
        for info in archive.infolist():
            posix = PurePosixPath(info.filename)
            if posix.is_absolute() or ".." in posix.parts or not posix.parts:
                raise ValueError(f"unsafe_path:{info.filename}")
            name = posix.name.lower()
            if name == ".env" or (name.endswith(".env") and not name.endswith(".env.example")):
                raise ValueError(f"secret_file:{info.filename}")
            if name.endswith((".pem", ".key")) or name.startswith("id_"):
                raise ValueError(f"key_file:{info.filename}")
            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise ValueError(f"symlink:{info.filename}")


def validate_bundle_manifest(
    path: Path,
    manifest: dict[str, Any],
    allowed_files: set[str],
    expected_source_commit: str,
) -> None:
    source_commit = manifest.get("source_commit")
    if source_commit != expected_source_commit:
        raise ValueError("manifest_source_commit_mismatch")
    files = manifest.get("files")
    if (
        not isinstance(files, list)
        or not all(isinstance(name, str) and name for name in files)
        or len(files) != len(set(files))
        or set(files) != allowed_files
    ):
        raise ValueError("manifest_files_scope_invalid")
    hashes = manifest.get("files_sha256")
    if not isinstance(hashes, dict) or set(hashes) != allowed_files:
        raise ValueError("manifest_file_hash_scope_invalid")
    for name in files:
        digest = hashes.get(name)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"manifest_file_sha256_invalid:{name}")
    if manifest.get("file_count") != len(files):
        raise ValueError("manifest_file_count_mismatch")
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != allowed_files:
            raise ValueError("bundle_manifest_entry_scope_mismatch")
        for name in files:
            observed = hashlib.sha256(archive.read(name)).hexdigest()
            if observed != hashes[name]:
                raise ValueError(f"bundle_manifest_sha256_mismatch:{name}")


def apply_patch_file_list(source_commit: str) -> list[str]:
    try:
        text = git_blob_bytes(source_commit, "deploy/apply-staging-patch.sh").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("bundle_whitelist_not_utf8") from exc
    return parse_apply_patch_file_list(text)


def parse_apply_patch_file_list(text: str) -> list[str]:
    match = re.search(r"^FILES=\(\n(?P<body>.*?)^\)", text, flags=re.MULTILINE | re.DOTALL)
    if not match:
        raise ValueError("bundle_whitelist_unreadable")
    files = re.findall(r'^\s+"([^"\n]+)"\s*$', match.group("body"), flags=re.MULTILINE)
    if not files or len(files) != len(set(files)):
        raise ValueError("bundle_whitelist_invalid")
    for name in files:
        posix = PurePosixPath(name)
        if posix.is_absolute() or ".." in posix.parts or not posix.parts:
            raise ValueError(f"bundle_whitelist_unsafe:{name}")
    return files


def validate_atomic_frontend_release(path: Path, manifest: dict[str, Any]) -> None:
    """Bind both HTML entries and both assets to one exact immutable release."""

    expected = manifest.get("frontend_files_sha256")
    if not isinstance(expected, dict) or set(expected) != set(ATOMIC_FRONTEND_FILES):
        raise ValueError("frontend_manifest_scope_invalid")
    for name in ATOMIC_FRONTEND_FILES:
        digest = expected.get(name)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"frontend_manifest_sha256_invalid:{name}")

    contents: dict[str, bytes] = {}
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        for name in ATOMIC_FRONTEND_FILES:
            if names.count(name) != 1:
                raise ValueError(f"frontend_bundle_entry_count:{name}:{names.count(name)}")
            contents[name] = archive.read(name)
            observed = hashlib.sha256(contents[name]).hexdigest()
            if observed != expected[name]:
                raise ValueError(f"frontend_bundle_sha256_mismatch:{name}")

    try:
        index_html = contents["index.html"].decode("utf-8")
        app_html = contents["app.html"].decode("utf-8")
        app_js = contents["app.js"].decode("utf-8")
        styles_css = contents["styles.css"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("frontend_utf8_invalid") from exc

    index_refs = _frontend_asset_references(index_html)
    app_entry_refs = _frontend_asset_references(app_html)
    _validate_entry_asset_shapes("index.html", index_refs, index_entry=True)
    _validate_entry_asset_shapes("app.html", app_entry_refs, index_entry=False)
    app_urls = [ref[3] for ref in index_refs + app_entry_refs if ref[4] == "app.js"]
    style_urls = [ref[3] for ref in index_refs + app_entry_refs if ref[4] == "styles.css"]
    app_versions = {_strict_asset_version(url, "app.js") for url in app_urls}
    style_versions = {_strict_asset_version(url, "styles.css") for url in style_urls}
    if len(app_versions) != 1:
        raise ValueError("frontend_app_version_split")
    if len(style_versions) != 1:
        raise ValueError("frontend_style_version_split")
    app_version = next(iter(app_versions))
    style_version = next(iter(style_versions))
    app_digest = _normalized_utf8_sha256(app_js)[:12]
    style_digest = _normalized_utf8_sha256(styles_css)[:12]
    if not app_version.endswith(app_digest):
        raise ValueError("frontend_app_version_digest_mismatch")
    if not style_version.endswith(style_digest):
        raise ValueError("frontend_style_version_digest_mismatch")
    app_family = app_version[: -len(app_digest)].rstrip("-._")
    style_family = style_version[: -len(style_digest)].rstrip("-._")
    if not app_family or app_family != style_family:
        raise ValueError("frontend_release_family_mismatch")


def _normalized_utf8_sha256(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class _FrontendAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[tuple[str, frozenset[str], str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): value or "" for name, value in attrs}
        tag = tag.lower()
        if tag == "script":
            url = attributes.get("src", "")
        elif tag == "link":
            url = attributes.get("href", "")
        else:
            url = ""
        asset = _referenced_frontend_asset(url)
        if not asset:
            return
        rel = frozenset(part.lower() for part in attributes.get("rel", "").split() if part)
        self.references.append((tag, rel, attributes.get("as", "").lower(), url, asset))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def _frontend_asset_references(html: str) -> list[tuple[str, frozenset[str], str, str, str]]:
    parser = _FrontendAssetParser()
    parser.feed(html)
    parser.close()
    return parser.references


def _referenced_frontend_asset(url: str) -> str:
    if not url:
        return ""
    try:
        basename = PurePosixPath(urlsplit(url).path).name
    except ValueError:
        return ""
    return basename if basename in {"app.js", "styles.css"} else ""


def _validate_entry_asset_shapes(
    entry_name: str,
    references: list[tuple[str, frozenset[str], str, str, str]],
    *,
    index_entry: bool,
) -> None:
    app_refs = [ref for ref in references if ref[4] == "app.js"]
    style_refs = [ref for ref in references if ref[4] == "styles.css"]
    if len(app_refs) != 1 or len(style_refs) != 1:
        raise ValueError(f"frontend_asset_reference_count:{entry_name}")
    app_tag, app_rel, app_as, _, _ = app_refs[0]
    style_tag, style_rel, style_as, _, _ = style_refs[0]
    if index_entry:
        if (
            app_tag != "link"
            or not app_rel.intersection({"preload", "prefetch"})
            or app_as != "script"
        ):
            raise ValueError("frontend_index_app_reference_shape")
        if (
            style_tag != "link"
            or not style_rel.intersection({"preload", "prefetch"})
            or style_as != "style"
        ):
            raise ValueError("frontend_index_style_reference_shape")
    else:
        if app_tag != "script":
            raise ValueError("frontend_app_entry_script_shape")
        if style_tag != "link" or "stylesheet" not in style_rel:
            raise ValueError("frontend_app_entry_style_shape")


def _strict_asset_version(url: str, asset_name: str) -> str:
    match = re.fullmatch(rf"\./{re.escape(asset_name)}\?v=([A-Za-z0-9._-]+)", url)
    if not match:
        raise ValueError(f"frontend_asset_url_invalid:{asset_name}")
    return match.group(1)


def validate_bundle_javascript(path: Path) -> None:
    """Syntax-check the exact bundled frontend before any production upload."""
    node = shutil.which("node")
    if not node:
        raise ValueError("local_node_unavailable")
    with tempfile.TemporaryDirectory(prefix="jiejing-production-js-") as temp_dir:
        app_js = Path(temp_dir) / "app.js"
        with zipfile.ZipFile(path, "r") as archive:
            app_js.write_bytes(archive.read("app.js"))
        completed = subprocess.run(
            [node, "--check", str(app_js)],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=60,
        )
        if completed.returncode != 0:
            raise ValueError("bundle_javascript_invalid")


def upload(args: argparse.Namespace, source: Path, remote_path: str) -> None:
    target = f"{DEFAULT_USER}@{DEFAULT_HOST}:{remote_path}"
    command = [
        "scp",
        "-O",
        "-P",
        str(DEFAULT_PORT),
        "-i",
        str(args.ssh_key),
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=12",
        "-o",
        "TCPKeepAlive=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={args.known_hosts}",
        "-o",
        f"ConnectTimeout={args.timeout}",
        str(source),
        target,
    ]
    run(command, timeout=max(args.timeout * 8, 240))


def ssh_base(args: argparse.Namespace) -> list[str]:
    return [
        "ssh",
        "-T",
        "-p",
        str(DEFAULT_PORT),
        "-i",
        str(args.ssh_key),
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=12",
        "-o",
        "TCPKeepAlive=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={args.known_hosts}",
        "-o",
        f"ConnectTimeout={args.timeout}",
        f"{DEFAULT_USER}@{DEFAULT_HOST}",
    ]


def run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "command_timeout",
                    "stdout_tail": text_tail(exc.stdout, 1500),
                    "stderr_tail": text_tail(exc.stderr, 1500),
                    "secret_exposed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    if completed.returncode != 0:
        raise SystemExit(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "remote_command_failed",
                    "returncode": completed.returncode,
                    "stdout_tail": completed.stdout[-3000:],
                    "stderr_tail": completed.stderr[-3000:],
                    "secret_exposed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return completed


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"git_command_failed:{' '.join(args)}")
    return completed.stdout.strip()


def text_tail(value: str | bytes | None, length: int) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[-length:]
    return value[-length:]


def fail(message: str) -> int:
    print(
        json.dumps(
            {"status": "failed", "reason": message, "secret_exposed": False},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Create a secret-safe zip bundle for Jiejing public staging handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-public-staging-bundle"
APPLY_SCRIPT = ROOT / "deploy" / "apply-staging-patch.sh"
BUNDLE_SCOPE_MARKER = "public_staging_patch_whitelist_v1"
ATOMIC_FRONTEND_FILES = ("index.html", "app.html", "app.js", "styles.css")

EXCLUDED_PARTS = {
    ".git",
    "__pycache__",
    "output",
    "artifacts",
    "screenshots",
    "test-results",
    "node_modules",
}

EXCLUDED_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".sqlite",
    ".db",
    ".log",
)

EXCLUDED_FILENAMES = {
    ".env",
    "jiejing-saas.env",
    "jiejing-saas.staging-oauth.env",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="List files without creating a zip")
    args = parser.parse_args()

    source_commit = _clean_source_commit()
    whitelist = _apply_patch_file_list(source_commit)
    files = list(_iter_bundle_files(whitelist))
    worktree_fingerprints = _worktree_fingerprints(files)
    leaks = _secret_leak_candidates(files)
    if leaks:
        raise SystemExit("refusing to bundle possible secret files: " + ", ".join(leaks))
    committed_files = _committed_bundle_files(source_commit, files)
    files_sha256 = _bundle_file_hashes(committed_files)
    frontend_files_sha256 = {name: files_sha256[name] for name in ATOMIC_FRONTEND_FILES}
    _assert_source_unchanged(source_commit)
    _assert_worktree_fingerprints_unchanged(files, worktree_fingerprints)

    manifest = {
        "product": "Jiejing SaaS",
        "bundle": "public_staging",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_commit": source_commit,
        "file_count": len(files),
        "files": [str(path.relative_to(ROOT)).replace("\\", "/") for path in files],
        "files_sha256": files_sha256,
        "scope": BUNDLE_SCOPE_MARKER,
        "scope_source": str(APPLY_SCRIPT.relative_to(ROOT)).replace("\\", "/"),
        "full_assets_included": False,
        "secret_files_excluded": sorted(EXCLUDED_FILENAMES),
        "real_platform_writes_enabled": False,
        "frontend_files_sha256": frontend_files_sha256,
    }

    if args.dry_run:
        print(json.dumps({**manifest, "status": "dry_run"}, ensure_ascii=False, indent=2))
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    zip_path = OUT / f"jiejing-public-staging-{stamp}.zip"
    manifest_path = OUT / f"jiejing-public-staging-{stamp}.manifest.json"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, contents in committed_files.items():
            zf.writestr(arcname, contents)
    _verify_bundle_files_in_zip(zip_path, files_sha256)
    _assert_source_unchanged(source_commit)
    _assert_worktree_fingerprints_unchanged(files, worktree_fingerprints)
    digest = _sha256(zip_path)
    manifest["zip_sha256"] = digest
    manifest["zip_path"] = zip_path.relative_to(ROOT).as_posix()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"BUNDLE_STATUS=created")
    print(f"BUNDLE_PATH={zip_path}")
    print(f"MANIFEST_PATH={manifest_path}")
    print(f"FILE_COUNT={len(files)}")
    print(f"SHA256={digest}")
    return 0


def _iter_bundle_files(whitelist: list[str]) -> Iterable[Path]:
    seen: set[Path] = set()
    for rel in whitelist:
        path = ROOT / rel
        if path in seen:
            continue
        if path.exists() and path.is_file() and not _is_excluded(path):
            seen.add(path)
            yield path
            continue
        raise FileNotFoundError(f"apply patch whitelist file missing or excluded from repo: {rel}")


def _apply_patch_file_list(source_commit: str) -> list[str]:
    """Use the remote apply whitelist as the bundle source of truth."""

    try:
        text = _git_blob_bytes(
            source_commit,
            APPLY_SCRIPT.relative_to(ROOT).as_posix(),
        ).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("apply patch whitelist blob is not UTF-8") from exc
    return _parse_apply_patch_file_list(text)


def _parse_apply_patch_file_list(text: str) -> list[str]:
    match = re.search(r"^FILES=\(\n(?P<body>.*?)^\)", text, flags=re.MULTILINE | re.DOTALL)
    if not match:
        raise RuntimeError("unable to parse FILES whitelist from deploy/apply-staging-patch.sh")
    files = re.findall(r'^\s+"([^"\n]+)"\s*$', match.group("body"), flags=re.MULTILINE)
    if not files:
        raise RuntimeError("empty FILES whitelist in deploy/apply-staging-patch.sh")
    if len(files) != len(set(files)):
        raise RuntimeError("duplicate FILES whitelist entry in deploy/apply-staging-patch.sh")
    unsafe = [item for item in files if item.startswith("/") or ".." in Path(item).parts]
    if unsafe:
        raise RuntimeError("unsafe apply patch whitelist entries: " + ", ".join(unsafe))
    if "deploy/apply-staging-patch.sh" not in files:
        raise RuntimeError("apply patch script must include itself in the staging patch whitelist")
    return files


def _is_excluded(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = set(rel.parts)
    if parts & EXCLUDED_PARTS:
        return True
    if "assets" in parts and path.name.startswith("demo-"):
        return True
    if path.name in EXCLUDED_FILENAMES:
        return True
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    if path.name.endswith(".env") and not path.name.endswith(".env.example"):
        return True
    return False


def _secret_leak_candidates(files: list[Path]) -> list[str]:
    candidates = []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        name = path.name.lower()
        if name.endswith(".env") and not name.endswith(".env.example"):
            candidates.append(rel)
        if name in EXCLUDED_FILENAMES:
            candidates.append(rel)
    return candidates


def _clean_source_commit() -> str:
    source_commit = _git_value("rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise RuntimeError("source commit must be a full lowercase Git SHA-1")
    dirty = _git_value("status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise RuntimeError("refusing to prepare bundle from dirty git worktree")
    return source_commit


def _git_value(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError("git source identity unavailable")
    return completed.stdout.strip()


def _assert_source_unchanged(expected_commit: str) -> None:
    if _git_value("rev-parse", "HEAD") != expected_commit:
        raise RuntimeError("source commit changed during bundle preparation")
    if _git_value("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("git worktree changed during bundle preparation")


def _worktree_fingerprints(files: list[Path]) -> dict[str, tuple[int, int, int, int, int]]:
    fingerprints: dict[str, tuple[int, int, int, int, int]] = {}
    for path in files:
        stat_result = path.stat()
        fingerprints[path.relative_to(ROOT).as_posix()] = (
            stat_result.st_dev,
            stat_result.st_ino,
            stat_result.st_size,
            stat_result.st_mtime_ns,
            stat_result.st_ctime_ns,
        )
    return fingerprints


def _assert_worktree_fingerprints_unchanged(
    files: list[Path],
    expected: dict[str, tuple[int, int, int, int, int]],
) -> None:
    if _worktree_fingerprints(files) != expected:
        raise RuntimeError("whitelist file changed during bundle preparation")


def _committed_bundle_files(source_commit: str, files: list[Path]) -> dict[str, bytes]:
    committed: dict[str, bytes] = {}
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        committed[relative] = _git_blob_bytes(source_commit, relative)
    return committed


def _git_blob_bytes(source_commit: str, relative_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{source_commit}:{relative_path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"whitelist file missing from source commit: {relative_path}")
    return completed.stdout


def _bundle_file_hashes(files: dict[str, bytes]) -> dict[str, str]:
    missing = [name for name in ATOMIC_FRONTEND_FILES if name not in files]
    if missing:
        raise RuntimeError("atomic frontend files missing from bundle whitelist: " + ", ".join(missing))
    return {name: hashlib.sha256(contents).hexdigest() for name, contents in files.items()}


def _verify_bundle_files_in_zip(zip_path: Path, expected: dict[str, str]) -> None:
    with zipfile.ZipFile(zip_path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("bundle contains duplicate zip entries")
        if set(names) != set(expected):
            raise RuntimeError("bundle entries do not match the reviewed whitelist")
        for name, expected_digest in expected.items():
            observed = hashlib.sha256(archive.read(name)).hexdigest()
            if observed != expected_digest:
                raise RuntimeError(f"bundle content mismatch: {name}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())

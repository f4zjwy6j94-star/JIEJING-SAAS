#!/usr/bin/env python3
"""Create a secret-safe zip bundle for Jiejing public staging handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import zipfile
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-public-staging-bundle"

INCLUDE_ROOT_FILES = [
    ".dockerignore",
    ".gitignore",
    "AGENTS.md",
    "Dockerfile.saas",
    "README.md",
    "requirements.saas.txt",
    "app.js",
    "app.html",
    "favicon.ico",
    "index.html",
    "privacy.html",
    "terms.html",
    "refund-policy.html",
    "support.html",
    "risk-disclosure.html",
    "robots.txt",
    "styles.css",
]

INCLUDE_DIRS = [
    "assets",
    "deploy",
    "docs",
    "jiejing_runtime",
    "jiejing_saas",
    "schemas",
    "tools",
]

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

    files = list(_iter_bundle_files())
    leaks = _secret_leak_candidates(files)
    if leaks:
        raise SystemExit("refusing to bundle possible secret files: " + ", ".join(leaks))

    manifest = {
        "product": "Jiejing SaaS",
        "bundle": "public_staging",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "file_count": len(files),
        "files": [str(path.relative_to(ROOT)).replace("\\", "/") for path in files],
        "secret_files_excluded": sorted(EXCLUDED_FILENAMES),
        "real_platform_writes_enabled": False,
    }

    if args.dry_run:
        print(json.dumps({**manifest, "status": "dry_run"}, ensure_ascii=False, indent=2))
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    zip_path = OUT / f"jiejing-public-staging-{stamp}.zip"
    manifest_path = OUT / f"jiejing-public-staging-{stamp}.manifest.json"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arcname = path.relative_to(ROOT).as_posix()
            zf.write(path, arcname)
    digest = _sha256(zip_path)
    manifest["zip_sha256"] = digest
    manifest["zip_path"] = str(zip_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"BUNDLE_STATUS=created")
    print(f"BUNDLE_PATH={zip_path}")
    print(f"MANIFEST_PATH={manifest_path}")
    print(f"FILE_COUNT={len(files)}")
    print(f"SHA256={digest}")
    return 0


def _iter_bundle_files() -> Iterable[Path]:
    seen: set[Path] = set()
    for rel in INCLUDE_ROOT_FILES:
        path = ROOT / rel
        if path.exists() and path.is_file() and not _is_excluded(path):
            seen.add(path)
            yield path
    for rel_dir in INCLUDE_DIRS:
        base = ROOT / rel_dir
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and path not in seen and not _is_excluded(path):
                seen.add(path)
                yield path


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())

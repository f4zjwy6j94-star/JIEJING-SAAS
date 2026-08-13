#!/usr/bin/env python3
"""No-secret-output scanner for Jiejing repository hygiene.

The scanner intentionally reports only path, line number, and rule label. It
never prints the matched value, so CI logs do not become a new secret leak.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT_BYTES = 2_500_000

SKIP_DIRS = {
    ".git",
    ".playwright-cli",
    "__pycache__",
    "artifacts",
    "external_references",
    "node_modules",
    "output",
    "screenshots",
    "test-results",
    "CC-desktop-zh-cn-WIN-portable-main",
}

SKIP_SUFFIXES = {
    ".7z",
    ".db",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyc",
    ".sqlite",
    ".webm",
    ".webp",
    ".wav",
    ".zip",
}

RULES = [
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |)?PRIVATE KEY-----")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{24,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("aws_access_key_id", re.compile(r"\bA(?:KIA|SIA)[A-Z0-9]{16}\b")),
    ("tencent_secret_id", re.compile(r"\bAKID[A-Za-z0-9]{16,}\b")),
    (
        "secret_assignment",
        re.compile(
            r"\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PRIVATE_KEY|REFRESH_TOKEN|CLIENT_SECRET|API_KEY)[A-Z0-9_]*\s*[:=]\s*['\"]?([^'\"\s#]{12,})",
            re.IGNORECASE,
        ),
    ),
    (
        "credentialed_service_url",
        re.compile(r"\b(?:postgres(?:ql)?|redis|mysql)://[^:\s/@]+:(?!\*\*\*|redacted|xxxxx)[^@\s]+@",
                   re.IGNORECASE),
    ),
]

ASSIGNMENT_RULES = {"secret_assignment", "credentialed_service_url"}
CONFIG_SUFFIXES = {".bat", ".cmd", ".cfg", ".env", ".ini", ".properties", ".ps1", ".sh", ".toml", ".yaml", ".yml"}
CONFIG_FILENAMES = {"Dockerfile", "Dockerfile.saas"}

ALLOWLIST_FRAGMENTS = {
    "change-me",
    "dummy",
    "example",
    "fake",
    "inject",
    "not-real",
    "placeholder",
    "replace",
    "redacted",
    "test-password",
    "unit-test",
}


def main() -> int:
    findings: list[tuple[str, int, str]] = []
    for path in _iter_files(ROOT):
        if path.relative_to(ROOT).as_posix() == "tools/jiejing_secret_scan.py":
            continue
        text = _read_text(path)
        if text is None:
            continue
        scan_assignment_rules = _should_scan_assignment_rules(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            if any(fragment in lowered for fragment in ALLOWLIST_FRAGMENTS):
                continue
            for label, pattern in RULES:
                if label in ASSIGNMENT_RULES and not scan_assignment_rules:
                    continue
                if label == "secret_assignment" and _assignment_is_path_metadata(line):
                    continue
                if pattern.search(line):
                    findings.append((str(path.relative_to(ROOT)), line_no, label))
                    break
    if findings:
        print("FAIL jiejing_secret_scan found potential secrets:")
        for rel_path, line_no, label in findings[:80]:
            print(f"- {rel_path}:{line_no} {label}")
        if len(findings) > 80:
            print(f"- ... {len(findings) - 80} more findings omitted")
        return 1
    print("PASS jiejing_secret_scan")
    return 0


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = set(path.relative_to(root).parts[:-1])
        if rel_parts & SKIP_DIRS:
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        yield path


def _read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > MAX_TEXT_BYTES or b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("utf-8", errors="ignore")
        except Exception:
            return None


def _should_scan_assignment_rules(path: Path) -> bool:
    if path.name in CONFIG_FILENAMES:
        return True
    if path.suffix.lower() in CONFIG_SUFFIXES:
        return True
    return any(part.lower() in {"deploy", ".github"} for part in path.parts)


def _assignment_is_path_metadata(line: str) -> bool:
    stripped = line.strip().strip('"\'')
    if stripped.startswith("-") and ":/" in stripped and any(
        marker in stripped.lower() for marker in ("/run/secrets/", "/private/", "\\private\\")
    ):
        return True
    match = re.match(r"\s*([A-Za-z0-9_]+)\s*[:=]", line)
    if not match:
        return False
    name = match.group(1).upper()
    return name.endswith(("_FILE", "_PATH", "_DIR", "_DIRECTORY", "_TEMPLATE", "_MOUNT", "_KEYSPACE", "_VERSION", "_SERVICE"))


if __name__ == "__main__":
    raise SystemExit(main())

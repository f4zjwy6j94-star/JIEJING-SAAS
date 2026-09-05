#!/usr/bin/env python3
"""Source-bound local gate receipts, not signatures or live-launch evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
import uuid

CONTRACT = "2026-09-05-source-bound-release-gate-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest_json(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def tracked_index_flags_safe(root: Path) -> bool:
    """Git status omits changes hidden by assume-unchanged or skip-worktree."""
    result = subprocess.run(["git", "ls-files", "-v", "-z"], cwd=root, capture_output=True, check=False, timeout=30)
    if result.returncode:
        raise ValueError("gate_source_tracking_flags_unavailable")
    entries = filter(None, result.stdout.split(b"\0"))
    return all(len(entry) > 2 and entry[1:2] == b" " and entry[:1].isupper() and entry[:1] != b"S" for entry in entries)


def capture_source_state(root: Path) -> dict:
    def git(*args):
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False, timeout=30)
        if result.returncode:
            raise ValueError("gate_source_identity_unavailable")
        return result.stdout.decode("utf-8", errors="strict")

    commit = git("rev-parse", "HEAD").strip()
    tree = git("rev-parse", "HEAD^{tree}").strip()
    flags_safe = tracked_index_flags_safe(root)
    clean = not git("status", "--porcelain", "--untracked-files=all").strip() and flags_safe
    fingerprints = []
    for name in sorted(filter(None, git("ls-files", "-z").split("\0"))):
        try:
            stat = (root / name).stat()
            fingerprints.append([name, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns])
        except FileNotFoundError:
            fingerprints.append([name, "missing"])
    return {"source_commit": commit, "source_tree": tree, "worktree_clean": clean,
            "tracked_flags_safe": flags_safe,
            "tracked_fingerprint_sha256": digest_json(fingerprints)}


def canonical_checks(checks, root: Path) -> list[dict]:
    """Normalize runtime location, never the order or arguments of checks."""
    root_text = str(root).replace("\\", "/").rstrip("/") + "/"
    catalog = []
    for key, command in checks:
        args = []
        for index, raw in enumerate(command):
            value = str(raw)
            path_text = value.replace("\\", "/")
            executable = path_text.rsplit("/", 1)[-1].lower()
            if index == 0 and (str(raw) == sys.executable or re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", executable)):
                value = "python"
            elif index == 0 and executable in {"node", "node.exe"}:
                value = "node"
            elif path_text.startswith(root_text):
                value = path_text[len(root_text):]
            args.append(value)
        catalog.append({"key": key, "command": args})
    return catalog


def build_gate_evidence(checks, results, source_before: dict, source_after: dict,
                        started_at: str, finished_at: str, root: Path) -> dict:
    catalog = canonical_checks(checks, root)
    keys = [entry["key"] for entry in catalog]
    outcomes = [{"key": item.get("key"), "pass": item.get("pass"), "returncode": item.get("returncode")} for item in results]
    checks_passed = bool(keys) and len(keys) == len(set(keys)) and [item["key"] for item in outcomes] == keys and all(
        item["pass"] is True and type(item["returncode"]) is int and item["returncode"] == 0 for item in outcomes)
    source_stable = source_before == source_after and source_before.get("worktree_clean") is True
    return {"contract": CONTRACT, "run_id": uuid.uuid4().hex, "started_at": started_at, "finished_at": finished_at,
            "source_commit": source_before["source_commit"], "source_tree": source_before["source_tree"],
            "source_before": source_before, "source_after": source_after,
            "check_catalog_sha256": digest_json(catalog), "expected_check_keys": keys, "results": outcomes,
            "checks_passed": checks_passed, "source_stable": source_stable,
            "release_eligible": bool(checks_passed and source_stable)}


def load_release_checks(root: Path):
    """Read the candidate's catalog without calling its gate main function."""
    return runpy.run_path(str(root / "tools" / "jiejing_precloud_deployment_gate.py"), run_name="release_gate_catalog")["CHECKS"]


def validate_gate_evidence(evidence, source_commit: str, source_tree: str, checks, root: Path) -> dict:
    fields = {"contract", "run_id", "started_at", "finished_at", "source_commit", "source_tree", "source_before", "source_after",
              "check_catalog_sha256", "expected_check_keys", "results", "checks_passed", "source_stable", "release_eligible"}
    if not isinstance(evidence, dict) or set(evidence) != fields or evidence.get("contract") != CONTRACT:
        raise ValueError("gate_evidence_missing_or_contract_invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit) or not re.fullmatch(r"[0-9a-f]{40}", source_tree):
        raise ValueError("gate_evidence_expected_source_invalid")
    if evidence["source_commit"] != source_commit or evidence["source_tree"] != source_tree:
        raise ValueError("gate_evidence_source_mismatch")
    if not isinstance(evidence["run_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", evidence["run_id"]):
        raise ValueError("gate_evidence_run_id_invalid")
    try:
        started = datetime.fromisoformat(evidence["started_at"])
        finished = datetime.fromisoformat(evidence["finished_at"])
        if started.tzinfo is None or finished.tzinfo is None or finished < started:
            raise ValueError()
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("gate_evidence_time_invalid") from exc
    state_fields = {"source_commit", "source_tree", "worktree_clean", "tracked_flags_safe", "tracked_fingerprint_sha256"}
    for state in (evidence["source_before"], evidence["source_after"]):
        if not isinstance(state, dict) or set(state) != state_fields or state.get("worktree_clean") is not True or state.get("tracked_flags_safe") is not True:
            raise ValueError("gate_evidence_source_not_clean")
        if state["source_commit"] != source_commit or state["source_tree"] != source_tree or not isinstance(state["tracked_fingerprint_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", state["tracked_fingerprint_sha256"]):
            raise ValueError("gate_evidence_source_state_invalid")
    if evidence["source_before"] != evidence["source_after"]:
        raise ValueError("gate_evidence_source_changed")
    catalog = canonical_checks(checks, root)
    keys = [entry["key"] for entry in catalog]
    if not keys or any(not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key) for key in keys) or len(keys) != len(set(keys)):
        raise ValueError("gate_evidence_check_catalog_invalid")
    if any(not entry["command"] or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in entry["command"]) for entry in catalog):
        raise ValueError("gate_evidence_check_command_invalid")
    if evidence["expected_check_keys"] != keys or evidence["check_catalog_sha256"] != digest_json(catalog):
        raise ValueError("gate_evidence_check_catalog_mismatch")
    outcomes = evidence["results"]
    if not isinstance(outcomes, list) or len(outcomes) != len(keys):
        raise ValueError("gate_evidence_results_incomplete")
    for key, outcome in zip(keys, outcomes):
        if not isinstance(outcome, dict) or set(outcome) != {"key", "pass", "returncode"} or outcome.get("key") != key or outcome.get("pass") is not True or type(outcome.get("returncode")) is not int or outcome["returncode"] != 0:
            raise ValueError("gate_evidence_result_failed_or_out_of_order")
    if any(evidence[field] is not True for field in ("checks_passed", "source_stable", "release_eligible")):
        raise ValueError("gate_evidence_not_release_eligible")
    # Only the validated schema can enter a manifest; stdout and environment are excluded.
    return json.loads(json.dumps(evidence))


def load_gate_report(path: Path, source_commit: str, source_tree: str, checks, root: Path) -> dict:
    try:
        raw = path.read_bytes()
        report = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("gate_evidence_report_unavailable") from exc
    if not isinstance(report, dict):
        raise ValueError("gate_evidence_report_invalid")
    evidence = validate_gate_evidence(report.get("release_gate_evidence"), source_commit, source_tree, checks, root)
    if report.get("gate") != "precloud_deployment_gate" or report.get("status") != "pass_local_checks" or report.get("ready_for_public_staging_code_handoff") is not True or report.get("secret_exposed") is not False:
        raise ValueError("gate_evidence_report_not_passing")
    results = report.get("checks")
    if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
        raise ValueError("gate_evidence_report_results_invalid")
    observed = [{"key": item.get("key"), "pass": item.get("pass"), "returncode": item.get("returncode")} for item in results]
    if observed != evidence["results"] or any(item["pass"] is not True or type(item["returncode"]) is not int or item["returncode"] != 0 for item in observed):
        raise ValueError("gate_evidence_report_results_mismatch")
    return {"evidence": evidence, "report_sha256": hashlib.sha256(raw).hexdigest()}


def validate_manifest_gate_proof(proof, source_commit: str, source_tree: str, checks, root: Path) -> dict:
    if not isinstance(proof, dict) or set(proof) != {"evidence", "report_sha256"} or not isinstance(proof.get("report_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", proof["report_sha256"]):
        raise ValueError("gate_evidence_manifest_proof_missing_or_invalid")
    return validate_gate_evidence(proof["evidence"], source_commit, source_tree, checks, root)

#!/usr/bin/env python3
"""Verify the private handoff and editable video checkpoint without altering it."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_file(root: Path, relative: str, expected: str | None = None) -> Path:
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Unsafe checkpoint path: {relative}")
    if not path.is_file():
        raise FileNotFoundError(f"Missing checkpoint file: {path}")
    if expected is not None and digest(path) != expected:
        raise ValueError(f"Checkpoint hash changed; preserve work and review: {path}")
    return path


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(f"Git command failed with exit {result.returncode}: {args[0]}")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", action="store_true", help="Verify the saved branch tip equals HEAD")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("CHECKPOINT.safe.json"))
    args = parser.parse_args()
    state = json.loads(args.manifest.read_text())
    if Path(git("rev-parse", "--show-toplevel")).resolve() != ROOT:
        raise ValueError("Unexpected checkout root")
    head = git("rev-parse", "HEAD")
    git("merge-base", "--is-ancestor", state["migration_base"], head)
    roots = {"repo": ROOT, "private": Path(state["private_root"]), "video": Path(state["video_output_root"]),
             "evidence": Path("/workspace/onboarding-evidence"),
             "complete_video": Path(state["complete_video_output_root"]),
             "voiceover_video": Path(state["voiceover_video_output_root"]),
             "narrative_video": Path(state["narrative_video_output_root"])}
    for group, files in state["pinned_files"].items():
        for relative, expected in files.items():
            checked_file(roots[group], relative, expected)
    for relative in state["required_private_controls"]:
        checked_file(roots["private"], relative)
    artifact_receipt = json.loads(checked_file(roots["video"], "SAVE_RECEIPT.safe.json").read_text())
    for item in artifact_receipt["files"]:
        path = checked_file(roots["video"], item["path"], item["sha256"])
        if path.stat().st_size != item["bytes"]:
            raise ValueError(f"Artifact size changed: {item['path']}")
    complete_receipt = json.loads(checked_file(roots["complete_video"], "ASSET_RECEIPT.safe.json").read_text())
    for item in complete_receipt["files"]:
        path = checked_file(roots["complete_video"], item["path"], item["sha256"])
        if path.stat().st_size != item["bytes"]:
            raise ValueError(f"Complete video asset size changed: {item['path']}")
    voiceover_receipt = json.loads(checked_file(roots["voiceover_video"], "ASSET_RECEIPT.safe.json").read_text())
    for item in voiceover_receipt["files"]:
        path = checked_file(roots["voiceover_video"], item["path"], item["sha256"])
        if path.stat().st_size != item["bytes"]:
            raise ValueError(f"Voiceover video asset size changed: {item['path']}")
    narrative_receipt = json.loads(checked_file(roots["narrative_video"], "ASSET_RECEIPT.safe.json").read_text())
    for item in narrative_receipt["files"]:
        path = checked_file(roots["narrative_video"], item["path"], item["sha256"])
        if path.stat().st_size != item["bytes"]:
            raise ValueError(f"Narrative study asset size changed: {item['path']}")
    verifier = checked_file(roots["private"], "continuity_tools.py", state["pinned_files"]["private"]["continuity_tools.py"])
    result = subprocess.run([sys.executable, str(verifier), "--verify"], capture_output=True, text=True, timeout=120)
    if result.returncode:
        try:
            details = json.loads(result.stdout).get("errors", [])
        except ValueError:
            details = ["Run continuity_tools.py --verify for exact package diagnostics"]
        raise RuntimeError(f"Imported-data verifier exited {result.returncode}: {details}")
    imported = json.loads(result.stdout)
    if not imported.get("complete_supplied_package_import_verified") or imported.get("errors"):
        raise ValueError("Imported-data verifier did not certify supplied packages")
    dirty = bool(git("status", "--porcelain"))
    remote_saved = None
    if args.remote:
        if dirty:
            raise ValueError("Uncommitted work exists; preserve it and save a checkpoint before claiming the working files are remotely saved")
        ref = "refs/heads/" + state["working_branch"]
        output = git("ls-remote", "--exit-code", "origin", ref).splitlines()
        remote_saved = len(output) == 1 and output[0].split() == [head, ref]
        if not remote_saved:
            raise ValueError("Remote branch differs from this HEAD; preserve work and reconcile the recorded version")
    print(json.dumps({"exit_code": 0, "head": head, "branch": git("branch", "--show-current"),
        "dirty": dirty, "video_source_and_artifacts_verified": True,
        "artifact_files_verified": len(artifact_receipt["files"]), "imported_data_exit_code": result.returncode,
        "complete_video_files_verified": len(complete_receipt["files"]),
        "voiceover_video_files_verified": len(voiceover_receipt["files"]),
        "narrative_study_files_verified": len(narrative_receipt["files"]),
        "remote_head_equals_local": remote_saved, "independent_new_task_cold_start_certified": False,
        "production_deployment_certified": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"exit_code": 1, "error": str(exc), "action": "Preserve existing work; do not reset, clean or substitute missing history."}, ensure_ascii=False))
        raise SystemExit(1)

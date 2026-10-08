#!/usr/bin/env python3
"""Read-only Git/material check; Python 3.8+ and Git with --no-lazy-fetch.

This checks a snapshot, performs no sync, and does not certify either cold start.
Remote access occurs only with --check-remote. Git error text is never emitted.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import subprocess
import sys


GIT_TIMEOUT_SECONDS = 15
REMOTE_TIMEOUT_SECONDS = 30
SHA_RE = re.compile(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?\Z")


def failure(report, code, check, **metadata):
    report["errors"].append(dict(code=code, check=check, **metadata))


def within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def git(report, repo, check, arguments, allowed=(0,), remote=False):
    env = os.environ.copy()
    for name in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(name, None)
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1",
               GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
    try:
        result = subprocess.run(
            ["git", "--no-lazy-fetch", "-c", "core.fsmonitor=false", "-C", str(repo)] + arguments,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
            timeout=REMOTE_TIMEOUT_SECONDS if remote else GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        failure(report, "GIT_TIMEOUT", check)
        return None
    except OSError:
        failure(report, "GIT_UNAVAILABLE", check)
        return None
    if result.returncode not in allowed:
        failure(report, "GIT_COMMAND_FAILED", check, git_exit_code=result.returncode)
        return None
    return result


def decoded(result):
    return result.stdout.decode("utf-8", errors="replace").strip()


def valid_branch(value):
    if not isinstance(value, str) or not re.fullmatch(r"video/[A-Za-z0-9_][A-Za-z0-9_./-]*", value):
        return False
    return (".." not in value and "//" not in value and not value.endswith(("/", "."))
            and all(not part.startswith(".") and not part.endswith(".lock") for part in value.split("/")))


def valid_relative(value):
    # Forward-slash relative paths only; also exclude Windows drive/ADS syntax.
    return (isinstance(value, str) and bool(value) and "\\" not in value
            and not any(ord(char) < 32 or char in '<>:"|?*' for char in value)
            and not Path(value).is_absolute() and not PureWindowsPath(value).drive
            and all(part not in ("", ".", "..") and not part.endswith((".", " "))
                    and not re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", part.split(".")[0])
                    for part in value.split("/")))


def read_manifest(report, path):
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError, UnicodeError):
        failure(report, "MANIFEST_UNREADABLE", "manifest")
        return None
    if not isinstance(data, dict):
        failure(report, "MANIFEST_SCHEMA_INVALID", "manifest")
        return None
    if (type(data.get("schema_version")) is not int or data["schema_version"] != 1
            or not valid_branch(data.get("work_branch"))
            or not isinstance(data.get("required_ancestor"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{4,64}", data["required_ancestor"])
            or not isinstance(data.get("artifacts"), list)):
        failure(report, "MANIFEST_SCHEMA_INVALID", "manifest")
        return None
    seen = set()
    errors_before = len(report["errors"])
    for index, item in enumerate(data["artifacts"]):
        if not isinstance(item, dict):
            failure(report, "ARTIFACT_SCHEMA_INVALID", "manifest", artifact_index=index)
            continue
        path = item.get("relative_path")
        metadata = {"artifact_index": index}
        if isinstance(path, str):
            metadata["relative_path"] = path
        if not valid_relative(path):
            failure(report, "ARTIFACT_PATH_INVALID", "manifest", **metadata)
            continue
        key = path.casefold()
        if key in seen:
            failure(report, "ARTIFACT_PATH_DUPLICATE", "manifest", **metadata)
        seen.add(key)
        if type(item.get("bytes")) is not int or item["bytes"] < 0:
            failure(report, "ARTIFACT_SIZE_INVALID", "manifest", **metadata)
        if not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", item["sha256"]):
            failure(report, "ARTIFACT_SHA256_INVALID", "manifest", **metadata)
    return data if len(report["errors"]) == errors_before else None


def check_artifacts(report, manifest, materials_root):
    items = manifest["artifacts"]
    report["checks"]["materials"] = {"required": len(items), "verified": 0}
    if not items:
        return
    if materials_root is None:
        for item in items:
            failure(report, "MATERIALS_ROOT_REQUIRED", "materials", relative_path=item["relative_path"])
        return
    try:
        root = Path(materials_root).resolve(strict=True)
        if not root.is_dir():
            raise OSError()
    except (OSError, RuntimeError, ValueError):
        failure(report, "MATERIALS_ROOT_INVALID", "materials")
        return
    for item in items:
        relative = item["relative_path"]
        entry = {"relative_path": relative, "expected_bytes": item["bytes"],
                 "expected_sha256": item["sha256"].lower(), "ok": False}
        report["artifacts"].append(entry)
        error_count = len(report["errors"])
        path = root
        try:
            for part in relative.split("/"):
                path = path / part
                if path.is_symlink():
                    failure(report, "ARTIFACT_SYMLINK_REJECTED", "materials", relative_path=relative)
                    break
            else:
                resolved = path.resolve(strict=True)
                if not within(resolved, root):
                    failure(report, "ARTIFACT_PATH_ESCAPE", "materials", relative_path=relative)
                    continue
                if not stat.S_ISREG(resolved.stat().st_mode):
                    failure(report, "ARTIFACT_NOT_REGULAR", "materials", relative_path=relative)
                    continue
                digest = hashlib.sha256()
                size = 0
                with resolved.open("rb") as stream:
                    before = os.fstat(stream.fileno())
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        size += len(chunk)
                        digest.update(chunk)
                    after = os.fstat(stream.fileno())
                entry.update(actual_bytes=size, actual_sha256=digest.hexdigest())
                if size != item["bytes"]:
                    failure(report, "ARTIFACT_SIZE_MISMATCH", "materials", relative_path=relative,
                            expected_bytes=item["bytes"], actual_bytes=size)
                if entry["actual_sha256"] != entry["expected_sha256"]:
                    failure(report, "ARTIFACT_SHA256_MISMATCH", "materials", relative_path=relative,
                            expected_sha256=entry["expected_sha256"], actual_sha256=entry["actual_sha256"])
                if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                        or size != before.st_size):
                    failure(report, "ARTIFACT_CHANGED_DURING_READ", "materials", relative_path=relative)
                entry["ok"] = len(report["errors"]) == error_count
                if entry["ok"]:
                    report["checks"]["materials"]["verified"] += 1
        except FileNotFoundError:
            failure(report, "ARTIFACT_MISSING", "materials", relative_path=relative)
        except (OSError, RuntimeError, ValueError):
            failure(report, "ARTIFACT_UNREADABLE", "materials", relative_path=relative)


def check_local(report, repo, manifest):
    head = git(report, repo, "head", ["rev-parse", "--verify", "HEAD"])
    if head is not None:
        value = decoded(head)
        if SHA_RE.fullmatch(value):
            report["checks"]["git"]["head"] = value.lower()
        else:
            failure(report, "GIT_RESPONSE_INVALID", "head")
    branch = git(report, repo, "branch", ["rev-parse", "--abbrev-ref", "HEAD"])
    if branch is not None:
        value = decoded(branch)
        report["checks"]["git"]["branch"] = value
        if value != manifest["work_branch"]:
            failure(report, "BRANCH_MISMATCH", "branch")
    status = git(report, repo, "worktree", ["status", "--porcelain=v1", "--untracked-files=all"])
    if status is not None:
        dirty = bool(status.stdout)
        report["checks"]["git"]["dirty"] = dirty
        if dirty:
            failure(report, "WORKTREE_DIRTY", "worktree")
    ancestor = git(report, repo, "required_ancestor", [
        "rev-parse", "--verify", manifest["required_ancestor"] + "^{commit}"])
    if ancestor is not None:
        value = decoded(ancestor)
        if not SHA_RE.fullmatch(value):
            failure(report, "GIT_RESPONSE_INVALID", "required_ancestor")
            return
        report["checks"]["git"]["required_ancestor"] = value.lower()
        result = git(report, repo, "ancestry", ["merge-base", "--is-ancestor", value, "HEAD"], allowed=(0, 1))
        if result is not None:
            report["checks"]["git"]["contains_required_ancestor"] = result.returncode == 0
            if result.returncode == 1:
                failure(report, "REQUIRED_ANCESTOR_MISSING", "ancestry")


def check_remote(report, repo, manifest):
    ref = "refs/heads/" + manifest["work_branch"]
    result = git(report, repo, "remote", ["ls-remote", "--exit-code", "origin", ref], remote=True)
    if result is None:
        report["checks"]["remote"]["status"] = "failed"
        return
    rows = [line.split() for line in decoded(result).splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != ref or not SHA_RE.fullmatch(rows[0][0]):
        failure(report, "GIT_RESPONSE_INVALID", "remote")
        report["checks"]["remote"]["status"] = "failed"
        return
    remote_sha = rows[0][0].lower()
    report["checks"]["remote"].update(head=remote_sha, status="checked")
    if remote_sha != report["checks"]["git"].get("head"):
        failure(report, "REMOTE_HEAD_MISMATCH", "remote", remote_head=remote_sha,
                local_head=report["checks"]["git"].get("head"))


def output_path(report, value, repo, git_dir):
    if value is None:
        return None
    try:
        original = Path(value)
        if original.exists() or original.is_symlink():
            failure(report, "OUTPUT_EXISTS", "output")
            return None
        path = original.resolve(strict=False)
        if not path.parent.is_dir():
            failure(report, "OUTPUT_PARENT_MISSING", "output")
            return None
        if within(path, repo) or (git_dir is not None and within(path, git_dir)):
            failure(report, "OUTPUT_INSIDE_REPOSITORY", "output")
            return None
        for parent in path.parents:
            if (parent.name.casefold() == ".git" or (parent / ".git").exists()
                    or ((parent / "HEAD").is_file() and (parent / "objects").is_dir()
                        and (parent / "refs").is_dir())):
                failure(report, "OUTPUT_INSIDE_REPOSITORY", "output")
                return None
        return path
    except (OSError, RuntimeError, ValueError):
        failure(report, "OUTPUT_PATH_INVALID", "output")
        return None


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid CLI arguments")


def main(argv=None):
    report = {"schema_version": 1, "ok": False, "sync_performed": False,
              "coldstart": {"local": "not_certified", "cloud": "not_certified"},
              "checks": {"git": {}, "remote": {"status": "not_checked"}},
              "artifacts": [], "errors": []}
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--materials-root")
    parser.add_argument("--check-remote", action="store_true")
    parser.add_argument("--output", help="New JSON receipt outside all Git repositories; never overwritten")
    destination = None
    try:
        args = parser.parse_args(argv)
    except ValueError:
        failure(report, "CLI_ARGUMENT_INVALID", "arguments")
        args = None
    if args is not None:
        report["checks"]["remote"]["requested"] = args.check_remote
        try:
            repo = Path(args.repo).resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            failure(report, "REPOSITORY_PATH_INVALID", "repository")
            repo = None
        if repo is not None:
            root = git(report, repo, "repository", ["rev-parse", "--show-toplevel"])
            git_directory = git(report, repo, "git_directory", ["rev-parse", "--absolute-git-dir"])
            if root is not None and git_directory is not None:
                try:
                    repo = Path(decoded(root)).resolve(strict=True)
                    git_dir = Path(decoded(git_directory)).resolve(strict=True)
                except (OSError, RuntimeError, ValueError):
                    failure(report, "GIT_RESPONSE_INVALID", "repository")
                else:
                    destination = output_path(report, args.output, repo, git_dir)
                    manifest = read_manifest(report, args.manifest)
                    if manifest is not None:
                        report["checks"]["git"]["expected_branch"] = manifest["work_branch"]
                        check_local(report, repo, manifest)
                        check_artifacts(report, manifest, args.materials_root)
                        if args.check_remote:
                            check_remote(report, repo, manifest)
    report["ok"] = not report["errors"]
    payload = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    if destination is not None:
        try:
            # Exclusive creation also rejects a target introduced after validation.
            with destination.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
        except FileExistsError:
            failure(report, "OUTPUT_EXISTS", "output")
        except OSError:
            failure(report, "OUTPUT_WRITE_FAILED", "output")
        report["ok"] = not report["errors"]
        payload = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    sys.stdout.write(payload)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

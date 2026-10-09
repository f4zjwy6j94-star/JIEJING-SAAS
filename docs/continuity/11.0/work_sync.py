#!/usr/bin/env python3
"""Explicit source/progress handoff; Python 3.8+, Git with --no-lazy-fetch.

One active writer per task. This is not a daemon, lease, material uploader, or
chat-memory sync. Existing Git authentication, hooks, and signing remain active.
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


BRANCH = "video/jiejing-11-continuity-20261006"
REPOSITORY = "f4zjwy6j94-star/JIEJING-SAAS"
INDEX = "docs/JIEJING_CURRENT_EXECUTION_STATE.md"
SCANNER = "tools/jiejing_secret_scan.py"
REF = "refs/heads/" + BRANCH
TRACKING = "refs/remotes/origin/" + BRANCH
MAX_TEXT_BYTES = 2_500_000  # Existing scanner skips larger/binary files.
SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".md",
                   ".rst", ".txt", ".json", ".yaml", ".yml", ".toml", ".sh",
                   ".ps1", ".bat", ".cmd", ".c", ".h", ".cpp", ".rs", ".go"}
BLOCKED_DIRS = {"assets", "media", "materials", "artifacts", "output", "outputs",
                "dist", "build", "node_modules", "__pycache__", "screenshots",
                "test-results", "external_references", "backups", "backup", "data",
                "databases", "database", "logs", "uploads", "downloads", "private",
                "secrets", "credentials", "videos", "audio", "images",
                "cc-desktop-zh-cn-win-portable-main"}
# Owner-approved 2026-10-09: these existing text sources only, not asset folders.
REVIEWED_TRACKED_ASSET_SOURCES = frozenset({
    "assets/jiejing-first-party-analytics.js",
    "assets/jiejing-ops-panels.js",
})
SENSITIVE_WORDS = {"env", "secret", "secrets", "credential", "credentials", "token",
                   "tokens", "password", "passwords", "cookie", "cookies", "session",
                   "sessions", "key", "keys"}


class Stop(Exception):
    def __init__(self, code, step, **details):
        self.error = dict(code=code, step=step, **details)


def inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def git_env():
    env = os.environ.copy()
    for name in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(name, None)
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1",
               GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
    return env


def production_origin(url):
    value = url.lower()
    if value.endswith(".git"):
        value = value[:-4]
    slug = REPOSITORY.lower()
    return value in {"https://github.com/" + slug, "git@github.com:" + slug,
                     "ssh://git@github.com/" + slug}


class Git:
    def __init__(self, repo, report, test_origin=None):
        try:
            self.repo = Path(repo).resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            raise Stop("REPOSITORY_INVALID", "repository")
        self.report = report
        self.origin_ok = production_origin if test_origin is None else lambda value: value == test_origin
        self.identity()
        self.git_dir = Path(self.text(self.raw(["rev-parse", "--absolute-git-dir"], "repository"))).resolve()

    @staticmethod
    def text(result):
        return result.stdout.decode("utf-8", errors="surrogateescape").strip()

    def raw(self, arguments, step, allowed=(0,), remote=False):
        try:
            result = subprocess.run(
                ["git", "--no-lazy-fetch", "--literal-pathspecs", "-c", "core.fsmonitor=false",
                 "-C", str(self.repo)] + arguments,
                env=git_env(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=45 if remote else 20,
            )
        except subprocess.TimeoutExpired:
            raise Stop("COMMAND_TIMEOUT", step)
        except OSError:
            raise Stop("COMMAND_UNAVAILABLE", step)
        if result.returncode not in allowed:
            raise Stop("GIT_FAILED", step, exit_code=result.returncode)
        return result

    def identity(self):
        root = self.text(self.raw(["rev-parse", "--show-toplevel"], "identity"))
        if Path(root).resolve() != self.repo:
            raise Stop("REPOSITORY_ROOT_REQUIRED", "identity")
        branch = self.raw(["symbolic-ref", "--quiet", "--short", "HEAD"], "identity", allowed=(0, 1))
        if branch.returncode or self.text(branch) != BRANCH:
            raise Stop("WRONG_BRANCH", "identity")
        urls = self.text(self.raw(["config", "--get-all", "remote.origin.url"], "identity")).splitlines()
        push = self.raw(["config", "--get-all", "remote.origin.pushurl"], "identity", allowed=(0, 1))
        push_urls = self.text(push).splitlines() if push.returncode == 0 else urls
        if (len(urls) != 1 or len(push_urls) != 1 or not self.origin_ok(urls[0])
                or not self.origin_ok(push_urls[0])):
            raise Stop("WRONG_ORIGIN", "identity")
        mirror = self.raw(["config", "--bool", "--get", "remote.origin.mirror"], "identity", allowed=(0, 1))
        if mirror.returncode == 0 and self.text(mirror) != "false":
            raise Stop("MIRROR_ORIGIN_FORBIDDEN", "identity")

    def run(self, arguments, step, allowed=(0,), remote=False):
        # Raw configured URLs identify the repository; Git retains auth/proxy URL rewrites.
        self.identity()
        result = self.raw(arguments, step, allowed=allowed, remote=remote)
        return result

    def head(self, ref="HEAD"):
        value = self.text(self.run(["rev-parse", "--verify", ref], "head"))
        if not SHA.fullmatch(value):
            raise Stop("GIT_RESPONSE_INVALID", "head")
        return value

    def remote_head(self):
        rows = self.text(self.run(["ls-remote", "--exit-code", "origin", REF], "remote", remote=True)).splitlines()
        parts = rows[0].split() if len(rows) == 1 else []
        if len(parts) != 2 or parts[1] != REF or not SHA.fullmatch(parts[0]):
            raise Stop("GIT_RESPONSE_INVALID", "remote")
        return parts[0]

    def status(self):
        data = self.run(["status", "--porcelain=v1", "-z", "--untracked-files=all"], "status").stdout
        fields = data.decode("utf-8", errors="surrogateescape").split("\x00")
        dirty, staged = set(), set()
        index = 0
        while index < len(fields) and fields[index]:
            row = fields[index]
            if len(row) < 4 or row[2] != " ":
                raise Stop("GIT_RESPONSE_INVALID", "status")
            code, path = row[:2], row[3:]
            dirty.add(path)
            if code[0] not in (" ", "?"):
                staged.add(path)
            if "R" in code or "C" in code:
                index += 1
                if index >= len(fields) or not fields[index]:
                    raise Stop("GIT_RESPONSE_INVALID", "status")
                dirty.add(fields[index])
                if code[0] not in (" ", "?"):
                    staged.add(fields[index])
            index += 1
        return dirty, staged

    def assert_idle(self):
        for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-apply", "rebase-merge", "sequencer"):
            if (self.git_dir / name).exists():
                raise Stop("GIT_OPERATION_IN_PROGRESS", "worktree")

    def relation(self, local, remote):
        if local == remote:
            return "equal"
        exists = self.run(["cat-file", "-e", remote + "^{commit}"], "relation", allowed=(0, 1, 128))
        if exists.returncode:
            return "remote_object_unavailable"
        if self.run(["merge-base", "--is-ancestor", local, remote], "relation", allowed=(0, 1)).returncode == 0:
            return "behind"
        if self.run(["merge-base", "--is-ancestor", remote, local], "relation", allowed=(0, 1)).returncode == 0:
            return "ahead"
        return "diverged"


def new_output(value, git):
    if value is None:
        return None
    try:
        original = Path(value)
        if original.exists() or original.is_symlink():
            raise Stop("OUTPUT_EXISTS", "output")
        path = original.resolve(strict=False)
        if not path.parent.is_dir():
            raise Stop("OUTPUT_PARENT_MISSING", "output")
        if inside(path, git.repo) or inside(path, git.git_dir):
            raise Stop("OUTPUT_INSIDE_REPOSITORY", "output")
        for parent in path.parents:
            if (parent.name.casefold() == ".git" or (parent / ".git").exists()
                    or ((parent / "HEAD").is_file() and (parent / "objects").is_dir()
                        and (parent / "refs").is_dir())):
                raise Stop("OUTPUT_INSIDE_REPOSITORY", "output")
        return path
    except (OSError, RuntimeError, ValueError):
        raise Stop("OUTPUT_INVALID", "output")


def safe_path(git, relative):
    parts = relative.split("/")
    invalid = (not relative or Path(relative).is_absolute() or PureWindowsPath(relative).drive
               or "\\" in relative or any(ord(c) < 32 or c in '<>:"|?*' for c in relative)
               or any(not p or p.startswith(".") or p.endswith((".", " ")) for p in parts)
               or any(re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", p.split(".")[0]) for p in parts))
    if invalid:
        raise Stop("UNSAFE_PATH", "paths", relative_path=relative)
    lower = [part.lower() for part in parts]
    words = {word for part in lower for word in re.split(r"[._-]", part)}
    reviewed_asset = (relative in REVIEWED_TRACKED_ASSET_SOURCES
                      and git.run(["ls-files", "--error-unmatch", "--", relative],
                                  "paths", allowed=(0, 1)).returncode == 0)
    if (relative == SCANNER or (set(lower) & BLOCKED_DIRS and not reviewed_asset)
            or words & SENSITIVE_WORDS
            or (Path(relative).suffix.lower() not in SOURCE_SUFFIXES
                and parts[-1] not in {"README", "LICENSE", "Makefile", "Dockerfile"})):
        raise Stop("SENSITIVE_OR_NON_SOURCE_PATH", "paths", relative_path=relative)
    path = git.repo
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise Stop("SYMLINK_PATH_FORBIDDEN", "paths", relative_path=relative)
    if not inside(path.resolve(strict=False), git.repo):
        raise Stop("PATH_ESCAPE", "paths", relative_path=relative)
    if not path.exists():
        if relative == INDEX:
            raise Stop("INDEX_MISSING", "progress_index")
        if reviewed_asset:
            raise Stop("PATH_MISSING", "paths", relative_path=relative)
        if git.run(["ls-files", "--error-unmatch", "--", relative], "paths", allowed=(0, 1)).returncode:
            raise Stop("PATH_MISSING", "paths", relative_path=relative)
        return None  # Explicit deletion of a previously tracked source file.
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > MAX_TEXT_BYTES:
        raise Stop("NON_TEXT_OR_OVERSIZE", "paths", relative_path=relative)
    content = path.read_bytes()
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        raise Stop("NON_TEXT_OR_OVERSIZE", "paths", relative_path=relative)
    if b"\x00" in content:
        raise Stop("NON_TEXT_OR_OVERSIZE", "paths", relative_path=relative)
    return hashlib.sha256(content).hexdigest()


def save_scope(git, selected):
    git.assert_idle()
    dirty, staged = git.status()
    if staged:
        raise Stop("EXISTING_STAGED_CHANGES", "scope")
    if INDEX not in selected:
        raise Stop("INDEX_PATH_REQUIRED", "progress_index")
    if INDEX not in dirty:
        raise Stop("INDEX_UNCHANGED", "progress_index")
    index_diff = git.text(git.run(["diff", "--numstat", "--no-ext-diff", "--no-textconv",
                                  "HEAD", "--", INDEX], "progress_index")).split("\t", 2)
    if (len(index_diff) != 3 or not index_diff[0].isdigit() or not index_diff[1].isdigit()
            or int(index_diff[0]) + int(index_diff[1]) == 0):
        raise Stop("INDEX_CONTENT_UNCHANGED", "progress_index")
    unexpected = sorted(dirty - selected)
    if unexpected:
        raise Stop("UNLISTED_DIRTY_PATHS", "scope", relative_paths=unexpected)
    if not dirty:
        raise Stop("NO_CHANGES", "scope")
    return dirty, {path: safe_path(git, path) for path in sorted(selected)}


def scan(git):
    git.identity()
    scanner = git.repo / SCANNER
    if not scanner.is_file() or scanner.is_symlink():
        raise Stop("SECRET_SCANNER_MISSING", "secret_scan")
    if git.run(["ls-files", "--error-unmatch", "--", SCANNER], "secret_scan", allowed=(0, 1)).returncode:
        raise Stop("SECRET_SCANNER_UNTRACKED", "secret_scan")
    if git.run(["diff", "--quiet", "HEAD", "--", SCANNER], "secret_scan", allowed=(0, 1)).returncode:
        raise Stop("SECRET_SCANNER_CHANGED", "secret_scan")
    try:
        result = subprocess.run([sys.executable, str(scanner)], cwd=str(git.repo), env=git_env(),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    except subprocess.TimeoutExpired:
        raise Stop("COMMAND_TIMEOUT", "secret_scan")
    except OSError:
        raise Stop("COMMAND_UNAVAILABLE", "secret_scan")
    git.report["steps"].append({"step": "secret_scan", "exit_code": result.returncode})
    if result.returncode:
        raise Stop("SECRET_SCAN_FAILED", "secret_scan", exit_code=result.returncode)


def receive(git, report):
    git.assert_idle()
    if git.status()[0]:
        raise Stop("WORKTREE_DIRTY", "receive")
    before = git.head()
    report["head_before"] = before
    remote = git.remote_head()
    report["remote_before"] = remote
    initial_relation = git.relation(before, remote)
    if initial_relation == "diverged":
        raise Stop("DIVERGED", "receive")
    if initial_relation == "ahead":
        raise Stop("LOCAL_AHEAD_NOT_PUBLISHED", "receive")
    git.run(["fetch", "--no-tags", "--recurse-submodules=no", "origin", REF + ":" + TRACKING], "fetch", remote=True)
    report["steps"].append({"step": "fetch", "exit_code": 0})
    fetched = git.head(TRACKING)
    if fetched != remote:
        raise Stop("REMOTE_CHANGED", "receive")
    relation = git.relation(before, fetched)
    if relation == "diverged" or relation == "remote_object_unavailable":
        raise Stop("DIVERGED", "receive")
    if relation == "ahead":
        raise Stop("LOCAL_AHEAD_NOT_PUBLISHED", "receive")
    git.assert_idle()
    if git.status()[0] or git.head() != before:
        raise Stop("LOCAL_CHANGED_DURING_RECEIVE", "receive")
    git.run(["merge", "--ff-only", "--no-edit", "--no-overwrite-ignore", "--no-autostash", fetched], "fast_forward")
    report["steps"].append({"step": "fast_forward", "exit_code": 0})
    report["head_after"] = git.head()
    report["sync_performed"] = report["head_after"] != before
    report["remote_after"] = git.remote_head()
    if report["remote_after"] != fetched or report["head_after"] != fetched:
        raise Stop("REMOTE_CHANGED", "receive_readback")
    report["relation"] = git.relation(report["head_after"], fetched)
    if git.status()[0]:
        raise Stop("WORKTREE_CHANGED_DURING_RECEIVE", "receive_readback")


def save(git, args, report):
    selected = set(args.path)
    if len(selected) != len(args.path) or len({path.casefold() for path in selected}) != len(selected):
        raise Stop("DUPLICATE_PATH", "paths")
    if not args.message.strip():
        raise Stop("MESSAGE_REQUIRED", "arguments")
    dirty, fingerprints = save_scope(git, selected)
    before = git.head()
    report["head_before"] = before
    remote = git.remote_head()
    report["remote_before"] = remote
    if before != remote:
        raise Stop("REMOTE_HEAD_MISMATCH", "save_preflight", local_head=before, remote_head=remote)
    scan(git)
    # Recheck the complete dirty set immediately before staging, including new files.
    current_dirty, current_fingerprints = save_scope(git, selected)
    if current_dirty != dirty or current_fingerprints != fingerprints or git.head() != before:
        raise Stop("LOCAL_CHANGED_DURING_SAVE", "save_preflight")
    if git.remote_head() != before:
        raise Stop("REMOTE_CHANGED", "save_preflight")
    current_dirty, current_fingerprints = save_scope(git, selected)
    if current_dirty != dirty or current_fingerprints != fingerprints:
        raise Stop("LOCAL_CHANGED_DURING_SAVE", "save_preflight")
    git.run(["add", "--"] + sorted(selected), "stage")
    report["steps"].append({"step": "stage", "exit_code": 0})
    after_dirty, staged = git.status()
    if staged != dirty or after_dirty != dirty:
        raise Stop("STAGED_SCOPE_CHANGED", "stage_review")
    if git.run(["diff", "--quiet"], "stage_review", allowed=(0, 1)).returncode:
        raise Stop("WORKTREE_CHANGED_DURING_SAVE", "stage_review")
    if {path: safe_path(git, path) for path in sorted(selected)} != fingerprints:
        raise Stop("WORKTREE_CHANGED_DURING_SAVE", "stage_review")
    staged_tree = git.text(git.run(["write-tree"], "stage_review"))
    if not SHA.fullmatch(staged_tree):
        raise Stop("GIT_RESPONSE_INVALID", "stage_review")
    report["commit_attempted"] = True
    git.run(["commit", "--message", args.message], "commit")
    report["steps"].append({"step": "commit", "exit_code": 0})
    report["committed"] = True
    head = git.head()
    report["head_after"] = head
    parents = git.text(git.run(["rev-list", "--parents", "-n", "1", "HEAD"], "commit_review")).split()
    committed_paths = set(git.run(["diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "HEAD"],
                                  "commit_review").stdout.decode("utf-8", errors="surrogateescape").rstrip("\x00").split("\x00"))
    if (parents != [head, before] or committed_paths != dirty or git.status()[0]
            or git.head("HEAD^{tree}") != staged_tree
            or {path: safe_path(git, path) for path in sorted(selected)} != fingerprints):
        raise Stop("COMMIT_SCOPE_CHANGED", "commit_review")
    if git.remote_head() != before:
        raise Stop("REMOTE_CHANGED", "push_preflight")
    if git.head() != head:
        raise Stop("LOCAL_CHANGED_DURING_SAVE", "push_preflight")
    report["push_attempted"] = True
    git.run(["push", "--no-follow-tags", "--recurse-submodules=no", "origin", head + ":" + REF], "push", remote=True)
    report["steps"].append({"step": "push", "exit_code": 0})
    report["pushed"] = True
    report["sync_performed"] = True
    report["remote_after"] = git.remote_head()
    if report["remote_after"] != head:
        raise Stop("REMOTE_READBACK_MISMATCH", "push_readback")
    if git.head() != head or git.status()[0]:
        raise Stop("LOCAL_CHANGED_DURING_SAVE", "push_readback")
    report["saved_paths"] = sorted(committed_paths)
    report["relation"] = "equal"


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Stop("CLI_ARGUMENT_INVALID", "arguments")


def main(argv=None, *, _test_origin=None):
    # The test injection is deliberately absent from CLI flags and environment variables.
    report = {"schema_version": 1, "ok": False, "repository": REPOSITORY, "branch": BRANCH,
              "sync_performed": False, "committed": False, "pushed": False,
              "commit_attempted": False, "push_attempted": False,
              "effect_flags_are_confirmations": True,
              "coldstart": {"local": "not_certified", "cloud": "not_certified"},
              "steps": [], "errors": []}
    destination = None
    git = None
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "receive", "save"):
        child = commands.add_parser(name)
        child.add_argument("--repo", required=True)
        child.add_argument("--output")
        if name == "save":
            child.add_argument("--path", action="append", required=True)
            child.add_argument("--message", required=True)
    try:
        args = parser.parse_args(argv)
        report["command"] = args.command
        git = Git(args.repo, report, _test_origin)
        destination = new_output(args.output, git)
        if args.command == "status":
            dirty, staged = git.status()
            report.update(head=git.head(), dirty_paths=sorted(dirty), staged_paths=sorted(staged))
            report["remote_head"] = git.remote_head()
            report["relation"] = git.relation(report["head"], report["remote_head"])
        elif args.command == "receive":
            receive(git, report)
        else:
            save(git, args, report)
        report["ok"] = True
    except Stop as error:
        report["errors"].append(error.error)
    except (OSError, RuntimeError, ValueError):
        report["errors"].append({"code": "LOCAL_IO_FAILED", "step": "local_io"})
    if git is not None and not report["ok"] and (report["commit_attempted"] or report["push_attempted"]):
        # Failed/expired Git calls can already have taken effect. Diagnose; never retry writes.
        for key, readback in (("observed_head_after_failure", git.head),
                              ("observed_remote_after_failure", git.remote_head)):
            try:
                report[key] = readback()
            except Stop as error:
                report.setdefault("readback_errors", []).append(error.error)
            except (OSError, RuntimeError, ValueError):
                report.setdefault("readback_errors", []).append({"code": "LOCAL_IO_FAILED", "step": "readback"})
    payload = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    if destination is not None:
        try:
            with destination.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
        except (OSError, ValueError):
            report["ok"] = False
            report["errors"].append({"code": "OUTPUT_WRITE_FAILED", "step": "output"})
            payload = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    sys.stdout.write(payload)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

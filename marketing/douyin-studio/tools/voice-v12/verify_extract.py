"""Verify the official model archive, reject traversal/links, extract data only."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

EXPECTED = "a3f4c73d043860e3fd2e5b06f36795eb81de0fc8e8de6df703245edddd87dbad"
parser = argparse.ArgumentParser()
parser.add_argument("archive", type=Path)
parser.add_argument("destination", type=Path)
args = parser.parse_args()
if not args.archive.is_absolute() or not args.destination.is_absolute():
    raise SystemExit("Absolute archive and destination paths required")
if args.destination.exists():
    raise SystemExit("Refusing existing destination")
with args.archive.open("rb") as source:
    digest = hashlib.file_digest(source, "sha256").hexdigest()
if digest != EXPECTED:
    raise SystemExit("Model archive hash mismatch; do not extract")
with tarfile.open(args.archive, "r:bz2") as archive:
    members = archive.getmembers()
    size = 0
    for member in members:
        path = PurePosixPath(member.name)
        if (path.is_absolute() or ".." in path.parts or "\\" in member.name
                or ":" in member.name or not path.parts
                or path.parts[0] != "kokoro-multi-lang-v1_1"
                or not (member.isfile() or member.isdir())):
            raise SystemExit("Unsafe archive member rejected")
        size += member.size
    if size > 2_000_000_000:
        raise SystemExit("Unexpected expanded archive size")
    args.destination.mkdir(parents=True)
    archive.extractall(args.destination, members=members, filter="data")
print(json.dumps({"archive_sha256": digest, "members": len(members),
                  "expanded_bytes": size, "executed_archive_scripts": False}))

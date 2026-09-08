#!/usr/bin/env python3
"""Export only verified nonsecret evidence; never run a provider or reload env."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONTRACT_VERSION = "jiejing_runtime_evidence_snapshot_v1"


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("arguments_invalid")


def main() -> int:
    # Host bootstrap needs only this same-source stdlib module, not package
    # __init__ (which imports the API server and its third-party dependencies).
    module_path = ROOT / "jiejing_saas" / "runtime_evidence.py"
    if module_path.resolve() != module_path:
        raise ValueError("reader_source_unavailable")
    spec = importlib.util.spec_from_file_location("jiejing_runtime_evidence_cli", module_path)
    if spec is None or spec.loader is None:
        raise ValueError("reader_source_unavailable")
    runtime_evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime_evidence)

    parser = SafeParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-capability", action="store_true")
    mode.add_argument("--prepare-directory", action="store_true")
    parser.add_argument("--output-dir")
    parser.add_argument("--env-file")
    args = parser.parse_args()
    if (runtime_evidence.CONTRACT_VERSION != CONTRACT_VERSION
            or not callable(runtime_evidence.read_runtime_evidence)
            or not callable(runtime_evidence.write_runtime_evidence_snapshot)
            or not callable(runtime_evidence.prepare_runtime_evidence_directory)):
        raise ValueError("reader_protocol_unavailable")
    if args.check_capability and args.output_dir is None and args.env_file is None:
        status = "capable"
    elif args.prepare_directory and args.output_dir and args.env_file is None:
        runtime_evidence.prepare_runtime_evidence_directory(args.output_dir)
        status = "prepared"
    elif not args.check_capability and not args.prepare_directory and args.output_dir and args.env_file:
        digest = runtime_evidence.write_runtime_evidence_snapshot(args.env_file, args.output_dir)
        print(json.dumps({"status": "verified", "contract_version": CONTRACT_VERSION,
                          "secret_exposed": False, "evidence_sha256": digest}))
        return 0
    else:
        raise ValueError("arguments_invalid")
    print(json.dumps({"status": status, "contract_version": CONTRACT_VERSION,
                      "secret_exposed": False, "writes_snapshot": False}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print(json.dumps({"status": "blocked", "contract_version": CONTRACT_VERSION,
                          "reason": "runtime_evidence_operation_failed", "secret_exposed": False}))
        raise SystemExit(2)

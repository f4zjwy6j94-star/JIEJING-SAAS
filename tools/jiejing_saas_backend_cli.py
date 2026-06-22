#!/usr/bin/env python3
"""CLI for the local Jiejing SaaS backend MVP."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import SaaSBackendServer, SaaSRepository, SaaSSettings, build_product_readiness
from jiejing_saas.json_safe import json_default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Jiejing formal SaaS backend MVP.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Serve the local backend API.")
    serve.add_argument("--db", default=str(ROOT / "output" / "jiejing-saas-backend" / "saas.sqlite"))
    serve.add_argument("--runtime-db", default=str(ROOT / "output" / "jiejing-saas-backend" / "runtime.sqlite"))
    serve.add_argument("--output-root", default=str(ROOT / "output" / "jiejing-saas-backend"))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8788)

    readiness = subparsers.add_parser("readiness", help="Print product SaaS readiness for this backend config.")
    readiness.add_argument("--db", default=str(ROOT / "output" / "jiejing-saas-backend" / "saas.sqlite"))
    readiness.add_argument("--runtime-db", default=str(ROOT / "output" / "jiejing-saas-backend" / "runtime.sqlite"))
    readiness.add_argument("--output-root", default=str(ROOT / "output" / "jiejing-saas-backend"))
    readiness.add_argument("--host", default="127.0.0.1")
    readiness.add_argument("--port", type=int, default=8788)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "serve":
        SaaSBackendServer(
            db_path=Path(args.db).resolve(),
            runtime_db_path=Path(args.runtime_db).resolve(),
            output_root=Path(args.output_root).resolve(),
            host=args.host,
            port=args.port,
        ).serve_forever()
        return 0
    if args.command == "readiness":
        settings = SaaSSettings.from_env(
            db_path=Path(args.db).resolve(),
            runtime_db_path=Path(args.runtime_db).resolve(),
            output_root=Path(args.output_root).resolve(),
            host=args.host,
            port=args.port,
        )
        repo = SaaSRepository(settings.db_path)
        repo.initialize()
        print(json.dumps({"readiness": build_product_readiness(settings, repo)}, ensure_ascii=False, indent=2, default=json_default))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

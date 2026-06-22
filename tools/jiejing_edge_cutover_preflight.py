#!/usr/bin/env python3
"""Print the no-write edge/WAF/origin/callback cutover preflight packet."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.edge_cutover_preflight import build_edge_cutover_preflight  # noqa: E402


ENV_KEYS = [
    "JIEJING_SELECTED_DOMAIN",
    "JIEJING_DOMAIN_REGISTRATION_STATUS",
    "JIEJING_EDGE_PROVIDER",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Jiejing edge/WAF/origin/callback cutover preflight.")
    parser.add_argument("--domain", default=os.environ.get("JIEJING_SELECTED_DOMAIN", "jiejing.shop"))
    parser.add_argument("--registration-status", default=os.environ.get("JIEJING_DOMAIN_REGISTRATION_STATUS", "registered"))
    parser.add_argument("--provider", default=os.environ.get("JIEJING_EDGE_PROVIDER", "cloudflare"))
    args = parser.parse_args()

    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    try:
        os.environ["JIEJING_SELECTED_DOMAIN"] = args.domain.strip().lower()
        os.environ["JIEJING_DOMAIN_REGISTRATION_STATUS"] = args.registration_status.strip().lower()
        os.environ["JIEJING_EDGE_PROVIDER"] = args.provider.strip().lower()
        settings = SaaSSettings.from_env(
            db_path=ROOT / "output" / "jiejing-edge-cutover-preflight" / "saas.sqlite",
            runtime_db_path=ROOT / "output" / "jiejing-edge-cutover-preflight" / "runtime.sqlite",
            output_root=ROOT / "output" / "jiejing-edge-cutover-preflight",
            host="127.0.0.1",
            port=8788,
        )
        packet = build_edge_cutover_preflight(settings)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print(json.dumps({"edge_cutover_preflight": packet}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

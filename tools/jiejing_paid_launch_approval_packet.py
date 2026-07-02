#!/usr/bin/env python3
"""Build or fetch the paid public launch approval packet.

This tool is read-only. It does not create Stripe Checkout sessions, does not
call Stripe APIs, does not start eBay OAuth, and does not perform platform
writes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.paid_launch_approval_packet import build_paid_launch_approval_packet  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the Jiejing paid-launch approval packet.")
    parser.add_argument("--base-url", default=os.environ.get("JIEJING_SAAS_BASE_URL", "").strip())
    parser.add_argument("--token-env", default="JIEJING_SAAS_TOKEN")
    parser.add_argument("--local-db", default=str(ROOT / "output" / "jiejing-saas-backend" / "saas.sqlite"))
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    if args.base_url:
        token = os.environ.get(args.token_env, "").strip()
        if not token:
            return _emit(
                {
                    "ok": False,
                    "blocked_by": ["missing_auth_token_env"],
                    "token_env": args.token_env,
                    "message": "Set a backend session token env var to fetch the protected live packet, or omit --base-url for local env evaluation.",
                    "secret_exposed": False,
                },
                args.output,
                code=2,
            )
        packet = _fetch_packet(args.base_url.rstrip("/"), token=token)
        return _emit(packet, args.output, code=0 if not packet.get("request_failed") else 1)

    db_path = Path(args.local_db)
    settings = SaaSSettings.from_env(db_path=db_path, runtime_db_path=db_path.with_name("runtime.sqlite"), output_root=ROOT / "output", host="127.0.0.1", port=8788)
    repo = SaaSRepository(db_path)
    repo.initialize()
    return _emit({"paid_launch_approval_packet": build_paid_launch_approval_packet(settings, repo)}, args.output, code=0)


def _fetch_packet(base_url: str, *, token: str) -> dict[str, object]:
    request = Request(
        f"{base_url}/owner/paid-launch-approval-packet",
        headers={"accept": "application/json", "authorization": f"Bearer {token}", "cache-control": "no-store"},
    )
    try:
        with urlopen(request, timeout=20) as response:  # nosec B310 - operator-supplied SaaS base URL.
            raw = response.read(1_000_000)
    except HTTPError as exc:
        return {"request_failed": True, "http_status": exc.code, "secret_exposed": False}
    except (TimeoutError, URLError) as exc:
        return {"request_failed": True, "error_type": type(exc).__name__, "secret_exposed": False}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        return {"request_failed": True, "error_type": "invalid_json", "secret_exposed": False}
    return parsed if isinstance(parsed, dict) else {"request_failed": True, "error_type": "non_object_json", "secret_exposed": False}


def _emit(payload: dict[str, object], output: str, *, code: int) -> int:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

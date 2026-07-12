#!/usr/bin/env python3
"""Run the controlled product-grade merchant journey against public staging."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-product-grade-journey"


def _run(command: list[str], *, env: dict[str, str], timeout: int) -> dict[str, Any]:
    started = time.time()
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    payload = _structured_payload(completed.stdout)
    if not payload:
        payload = _structured_payload(completed.stderr)
    if not payload:
        payload = {"ok": False, "error": "invalid_json_output"}
    return {
        "command": command,
        "pass": completed.returncode == 0 and payload.get("ok") is True,
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.time() - started, 2),
        "payload": payload,
        "stderr_tail": completed.stderr[-1200:],
        "secret_exposed": False,
    }


def _structured_payload(output: str) -> dict[str, Any]:
    text = output.strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("JIEJING_TEST_BASE", "https://app.jiejing.shop")

    ai_bridge = _run(
        ["node", "tools/codex_jiejing_ai_ceo_market_listing_bridge_smoke.js"],
        env=env,
        timeout=240,
    )
    product = str(ai_bridge.get("payload", {}).get("report", {}).get("product") or "").strip()
    if not ai_bridge["pass"] or not product:
        return _finish([ai_bridge], product=product, status="failed_ai_ceo_to_listing")

    shared_env = {**env, "JIEJING_ACCEPTANCE_PRODUCT": product}
    bulk_media = _run(
        ["node", "tools/codex_jiejing_bulk_media_handoff_smoke.js"],
        env=shared_env,
        timeout=600 if str(env.get("JIEJING_ACCEPTANCE_INCLUDE_VIDEO") or "").lower() in {"1", "true", "yes", "on"} else 360,
    )
    publish_confirmation = _run(
        ["node", "tools/codex_jiejing_publish_confirmation_loop_smoke.js"],
        env=shared_env,
        timeout=300,
    )
    steps = [ai_bridge, bulk_media, publish_confirmation]
    product_identity_ok = (
        bulk_media.get("payload", {}).get("acceptance_product") == product
        and publish_confirmation.get("payload", {}).get("seed", {}).get("product") == product
        and publish_confirmation.get("payload", {}).get("seed", {}).get("title") == product[:80]
    )
    status = "passed" if all(item["pass"] for item in steps) and product_identity_ok else "failed_downstream_journey"
    return _finish(steps, product=product, status=status, product_identity_ok=product_identity_ok)


def _finish(
    steps: list[dict[str, Any]],
    *,
    product: str,
    status: str,
    product_identity_ok: bool = False,
) -> int:
    summary = {
        "contract_version": "2026-07-11-product-grade-merchant-journey-v1",
        "status": status,
        "pass": status == "passed",
        "acceptance_product": product,
        "product_identity_ok": product_identity_ok,
        "steps": steps,
        "real_platform_writes_enabled": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "secret_exposed": False,
    }
    path = OUT / "latest.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"OUTPUT={path}")
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

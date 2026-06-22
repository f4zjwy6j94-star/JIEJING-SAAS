#!/usr/bin/env python3
"""Run a local eBay credential preflight without exposing secrets."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.ebay_credential_preflight import build_ebay_credential_preflight  # noqa: E402


RESOURCES = [
    "store_profile",
    "account_business_policies",
    "inventory_and_offers",
    "orders_and_fulfillment",
    "finances",
    "taxonomy_listing_metadata",
]


def main() -> int:
    out_dir = ROOT / "output" / "jiejing-saas-backend" / "ebay-credential-preflight"
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = SaaSSettings.from_env(
        db_path=out_dir / "preflight.sqlite",
        runtime_db_path=out_dir / "preflight-runtime.sqlite",
        output_root=out_dir,
        host="127.0.0.1",
        port=8788,
    )
    store = {
        "store_id": os.environ.get("JIEJING_EBAY_PREFLIGHT_STORE_ID") or "local_preflight_store",
        "store_name": os.environ.get("JIEJING_EBAY_PREFLIGHT_STORE_NAME") or "local eBay preflight",
        "platform": "ebay",
        "marketplace": os.environ.get("JIEJING_EBAY_MARKETPLACE") or "EBAY_US",
    }
    secret_refs = []
    if settings.ebay_env_refresh_token_allowed:
        secret_refs.append(
            {
                "secret_ref": "env:ebay_refresh_token",
                "provider": "ebay",
                "purpose": "ebay_refresh_token",
                "status": "configured_in_backend_env",
                "secret_exposed": False,
            }
        )
    connections = []
    if settings.ebay_env_access_token_allowed or settings.ebay_env_refresh_token_allowed:
        connections.append(
            {
                "connection_id": "local_preflight_ebay_oauth",
                "platform": "ebay",
                "connection_type": "oauth",
                "status": "read_only_authorized",
                "scopes": ["sell.account.readonly", "sell.inventory.readonly", "sell.fulfillment.readonly", "sell.finances"],
                "secret_ref": secret_refs[0]["secret_ref"] if secret_refs else None,
                "secret_exposed": False,
            }
        )

    preflight = build_ebay_credential_preflight(
        settings=settings,
        store=store,
        secret_refs=secret_refs,
        connections=connections,
        requested_resources=RESOURCES,
    )
    json_path = out_dir / "credential_preflight_latest.json"
    md_path = out_dir / "credential_preflight_latest.md"
    json_path.write_text(json.dumps(preflight, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(preflight), encoding="utf-8")

    print(f"EBAY_PREFLIGHT_STATUS={preflight.get('status')}")
    print(f"CAN_QUEUE_SYNC={preflight.get('can_queue_sync')}")
    print(f"TOKEN_MODE={preflight.get('token_mode')}")
    print(f"BLOCKERS={','.join(preflight.get('blocked_by') or []) or '-'}")
    print(f"JSON={json_path}")
    print(f"MD={md_path}")
    return 0


def _markdown(preflight: dict[str, object]) -> str:
    checks = preflight.get("checks") if isinstance(preflight.get("checks"), list) else []
    lines = [
        "# eBay 只读凭证预检",
        "",
        f"- 状态：{preflight.get('status')}",
        f"- Token 模式：{preflight.get('token_mode')}",
        f"- 能否进入同步队列：{preflight.get('can_queue_sync')}",
        f"- 下一步：{preflight.get('merchant_next_step')}",
        f"- 是否暴露密钥：{preflight.get('secret_exposed')}",
        "",
        "## 检查项",
        "",
    ]
    for item in checks:
        if not isinstance(item, dict):
            continue
        lines.append(f"- {item.get('label')}：{item.get('status')}。{item.get('detail')}")
    lines.append("")
    lines.append("说明：这个预检只判断后端能否读取 eBay 官方只读数据，不做发布、改价、退款、广告或政策修改。")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())

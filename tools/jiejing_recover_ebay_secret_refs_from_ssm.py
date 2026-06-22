#!/usr/bin/env python3
"""Recover eBay secret_ref metadata from Tencent SSM without exposing tokens.

This is an operational repair tool for the case where Postgres was restored
without the `secret_refs` / `platform_connections` rows, while backend-managed
Tencent SSM still contains the encrypted eBay refresh-token payload.

Default mode is dry-run. Use `--apply` only inside the backend secret boundary.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository, now_iso  # noqa: E402
from jiejing_saas.vault_secret_resolver import (  # noqa: E402
    _build_tencent_ssm_client,
    _extract_secret_value,
    _new_tencent_ssm_request,
    _tencent_ssm_config,
)


EBAY_REFRESH_PURPOSE = "ebay_refresh_token"
ACTIVE_STATUS = "managed_vault_stored"
DEFAULT_SCOPES = [
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write recovered metadata rows")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--db-path", default=os.environ.get("JIEJING_SAAS_DB") or "/data/saas.sqlite")
    args = parser.parse_args()

    settings = SaaSSettings.from_env(
        db_path=Path(args.db_path),
        runtime_db_path=Path(os.environ.get("JIEJING_RUNTIME_DB") or "/data/runtime.sqlite"),
        output_root=Path(os.environ.get("JIEJING_OUTPUT_ROOT") or "/data/output"),
        host="127.0.0.1",
        port=8788,
    )
    repo = SaaSRepository(
        Path(args.db_path),
        database_engine=settings.database_engine,
        database_url=os.environ.get("JIEJING_DATABASE_URL", ""),
    )
    repo.initialize()

    packet = _latest_official_ebay_packet(repo)
    if not packet:
        _print(
            {
                "ok": False,
                "mode": "apply" if args.apply else "dry_run",
                "blocked_by": ["latest_official_ebay_packet_missing"],
                "secret_exposed": False,
            }
        )
        return 2

    candidates = _ssm_ebay_refresh_candidates(settings, limit=args.limit)
    if not candidates:
        _print(
            {
                "ok": False,
                "mode": "apply" if args.apply else "dry_run",
                "packet_id": packet["packet_id"],
                "candidate_count": 0,
                "blocked_by": ["ssm_ebay_refresh_candidate_missing"],
                "secret_exposed": False,
            }
        )
        return 3

    selected = candidates[0]
    if not args.apply:
        _print(
            {
                "ok": True,
                "mode": "dry_run",
                "packet_id": packet["packet_id"],
                "candidate_count": len(candidates),
                "selected_secret_ref": selected["secret_ref"],
                "would_create_or_update_secret_ref": True,
                "would_create_platform_connection": True,
                "secret_value_returned": False,
                "secret_exposed": False,
            }
        )
        return 0

    action = _apply_recovery(repo=repo, packet=packet, selected=selected)
    evidence = repo.product_readiness_evidence()
    _print(
        {
            "ok": True,
            "mode": "apply",
            "action": action,
            "packet_id": packet["packet_id"],
            "candidate_count": len(candidates),
            "selected_secret_ref": selected["secret_ref"],
            "read_only_authorized_connections": evidence.get("read_only_authorized_connections"),
            "ebay_secret_refs": evidence.get("ebay_secret_refs"),
            "secret_value_returned": False,
            "secret_exposed": False,
        }
    )
    return 0


def _latest_official_ebay_packet(repo: SaaSRepository) -> dict[str, Any] | None:
    with repo._connect() as conn:  # operational tool; only metadata is returned
        row = conn.execute(
            """
            select packet_id, company_id, store_id, created_by, source_mode, status
            from platform_data_packets
            where platform = 'ebay'
            order by created_at desc
            limit 1
            """
        ).fetchone()
    if not row:
        return None
    packet = dict(row) if hasattr(row, "keys") else {}
    if "official_api" not in str(packet.get("source_mode") or "").lower():
        return None
    return packet


def _ssm_ebay_refresh_candidates(settings: SaaSSettings, *, limit: int) -> list[dict[str, Any]]:
    config = _tencent_ssm_config(settings)
    if config.get("blocked_by"):
        return []
    client = _build_tencent_ssm_client(config)
    req = _new_tencent_ssm_request("ListSecretsRequest")
    setattr(req, "Offset", 0)
    setattr(req, "Limit", limit)
    data = json.loads(client.ListSecrets(req).to_json_string())
    items = data.get("SecretMetadatas") or data.get("SecretMetadata") or data.get("Secrets") or []
    candidates: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("SecretName") or item.get("Name") or "")
        if not name:
            continue
        payload = _read_ssm_payload(client, name)
        if not payload:
            continue
        candidate = _candidate_from_payload(secret_name=name, payload=payload)
        if candidate:
            candidates.append(candidate)
    candidates.sort(key=lambda item: item.get("score", 0), reverse=True)
    return candidates


def _read_ssm_payload(client: Any, secret_name: str) -> dict[str, Any]:
    try:
        req = _new_tencent_ssm_request("GetSecretValueRequest")
        setattr(req, "SecretName", secret_name)
        data = json.loads(client.GetSecretValue(req).to_json_string())
        raw = str(data.get("SecretString") or "")
        parsed = json.loads(raw) if raw.strip().startswith("{") else {"secret_value": raw}
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _candidate_from_payload(*, secret_name: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    purpose = str(payload.get("purpose") or metadata.get("purpose") or "")
    provider = str(payload.get("provider") or metadata.get("provider") or "")
    haystack = json.dumps(
        {
            "secret_name": secret_name,
            "purpose": purpose,
            "provider": provider,
            "metadata": metadata,
        },
        ensure_ascii=False,
    ).lower()
    secret_value = _extract_secret_value(payload=payload, purpose=purpose or EBAY_REFRESH_PURPOSE, configured_field="")
    if not secret_value:
        return None
    if "ebay" not in haystack and purpose != EBAY_REFRESH_PURPOSE:
        return None
    if "refresh" not in haystack and purpose != EBAY_REFRESH_PURPOSE and "refresh_token" not in payload:
        return None
    secret_ref = str(payload.get("secret_ref") or metadata.get("secret_ref") or "")
    if not secret_ref:
        match = re.search(r"(secret_[A-Za-z0-9]+)", secret_name)
        secret_ref = match.group(1) if match else ""
    if not secret_ref:
        return None
    score = 0
    score += 10 if purpose == EBAY_REFRESH_PURPOSE else 0
    score += 6 if provider == "ebay" else 0
    score += 3 if "read_only" in haystack or "readonly" in haystack else 0
    scopes = metadata.get("scopes") if isinstance(metadata.get("scopes"), list) else payload.get("scopes")
    scopes = scopes if isinstance(scopes, list) else DEFAULT_SCOPES
    return {
        "secret_ref": secret_ref,
        "provider": "ebay",
        "purpose": EBAY_REFRESH_PURPOSE,
        "status": ACTIVE_STATUS,
        "metadata": {
            "contract_version": "2026-06-13-recovered-ssm-ebay-secret-ref",
            "credential_owner": "jiejing_saas_backend",
            "storage_adapter": "managed_tencent_ssm",
            "recovered_from_ssm_metadata": True,
            "refresh_token_stored_in_database": False,
            "token_values_returned_to_public_response": False,
            "secret_value_returned": False,
            "secret_exposed": False,
            "scopes": scopes,
        },
        "scopes": scopes,
        "score": score,
    }


def _apply_recovery(*, repo: SaaSRepository, packet: dict[str, Any], selected: dict[str, Any]) -> str:
    company_id = str(packet["company_id"])
    store_id = str(packet["store_id"])
    user_id = str(packet.get("created_by") or "")
    secret_ref = str(selected["secret_ref"])
    created_at = now_iso()
    action = "noop"
    with repo._connect() as conn:
        existing = conn.execute(
            """
            select secret_ref from secret_refs
            where company_id = ? and store_id = ? and secret_ref = ?
            """,
            (company_id, store_id, secret_ref),
        ).fetchone()
        if existing:
            conn.execute(
                """
                update secret_refs
                set provider = ?, purpose = ?, status = ?, metadata_json = ?
                where company_id = ? and store_id = ? and secret_ref = ?
                """,
                (
                    "ebay",
                    EBAY_REFRESH_PURPOSE,
                    ACTIVE_STATUS,
                    json.dumps(selected["metadata"], ensure_ascii=False),
                    company_id,
                    store_id,
                    secret_ref,
                ),
            )
            action = "updated_secret_ref"
        else:
            conn.execute(
                """
                insert into secret_refs (
                  secret_ref, company_id, store_id, provider, purpose, status, created_by, created_at, metadata_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    secret_ref,
                    company_id,
                    store_id,
                    "ebay",
                    EBAY_REFRESH_PURPOSE,
                    ACTIVE_STATUS,
                    user_id,
                    created_at,
                    json.dumps(selected["metadata"], ensure_ascii=False),
                ),
            )
            action = "inserted_secret_ref"
        connection = conn.execute(
            """
            select connection_id from platform_connections
            where company_id = ? and store_id = ? and platform = 'ebay' and secret_ref = ?
            """,
            (company_id, store_id, secret_ref),
        ).fetchone()
        if not connection:
            conn.execute(
                """
                insert into platform_connections (
                  connection_id, company_id, store_id, platform, connection_type, status, scopes_json,
                  secret_ref, metadata_json, created_by, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _id_for_connection(secret_ref),
                    company_id,
                    store_id,
                    "ebay",
                    "oauth",
                    "read_only_authorized",
                    json.dumps(selected["scopes"], ensure_ascii=False),
                    secret_ref,
                    json.dumps(
                        {
                            "credential_source": "managed_tencent_ssm_secret_ref",
                            "recovered_from_ssm_metadata": True,
                            "secret_exposed": False,
                        },
                        ensure_ascii=False,
                    ),
                    user_id,
                    created_at,
                ),
            )
            action += "_and_inserted_connection"
        repo._insert_audit(
            conn,
            company_id=company_id,
            store_id=store_id,
            user_id=user_id,
            actor_type="system",
            action_type="secret_ref.recovered_from_ssm",
            target_type="secret_ref",
            target_id=secret_ref,
            summary="Recovered eBay refresh-token secret_ref metadata from Tencent SSM without exposing raw token.",
            details={
                "provider": "ebay",
                "purpose": EBAY_REFRESH_PURPOSE,
                "status": ACTIVE_STATUS,
                "secret_value_returned": False,
                "secret_exposed": False,
            },
        )
    return action


def _id_for_connection(secret_ref: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9]", "", secret_ref)[-16:] or "recovered"
    return f"conn_recovered_{suffix}"


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    raise SystemExit(main())

"""Bounded, read-only merchant view of existing point reservations.

No raw accounting payload, source identifier or provider data crosses this boundary.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

MERCHANT_SOURCES = frozenset({'plan_included', 'purchased', 'legacy'})
SCAN_LIMIT = 100


def _allocations(raw: Any) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        details = payload.get('details', {}) if isinstance(payload, dict) else {}
        values = details.get('allocations', []) if isinstance(details, dict) else []
        return values if isinstance(values, list) and len(values) <= 100 else []
    except (ValueError, TypeError):
        return []


def read_merchant_media_credit_usage(conn: Any, *, company_id: str, limit: int = 30) -> dict[str, Any]:
    limit = min(max(int(limit), 1), SCAN_LIMIT)
    held = conn.execute('''
        select coalesce(sum(reserved_points), 0) as held from media_credit_buckets
        where company_id = ? and source_type in ('plan_included', 'purchased', 'legacy')
          and status in ('active', 'expiring', 'revoking')
    ''', (company_id,)).fetchone()
    rows = conn.execute('''
        select r.ledger_id, r.points, r.status, r.created_at, r.updated_at, r.ledger_json, j.media_job_id
        from media_credit_ledger r left join media_asset_jobs j
          on j.company_id = r.company_id and j.idempotency_key = r.reference_id
        where r.company_id = ? and r.operation_type = 'reserve' and r.reference_type = 'media_job'
        order by r.updated_at desc, r.ledger_id desc limit ?
    ''', (company_id, SCAN_LIMIT + 1)).fetchall()
    scanned = rows[:SCAN_LIMIT]
    terminals: dict[str, list[Any]] = {}
    if scanned:
        reservation_ids = [str(row['ledger_id']) for row in scanned]
        placeholders = ','.join('?' for _ in reservation_ids)
        for terminal in conn.execute(f'''select reservation_id, operation_type, points, status
            from media_credit_ledger where company_id = ? and reservation_id in ({placeholders})
              and operation_type in ('settle', 'release', 'revoke')''', (company_id, *reservation_ids)).fetchall():
            terminals.setdefault(str(terminal['reservation_id']), []).append(terminal)
    allocations = {str(row['ledger_id']): _allocations(row['ledger_json']) for row in scanned}
    bucket_ids = sorted({str(item.get('bucket_id', '')) for values in allocations.values()
                         for item in values if isinstance(item, dict) and item.get('bucket_id')})
    sources = {}
    for offset in range(0, len(bucket_ids), 400):
        batch = bucket_ids[offset:offset + 400]
        placeholders = ','.join('?' for _ in batch)
        for bucket in conn.execute(f'''select bucket_id, source_type from media_credit_buckets
            where company_id = ? and bucket_id in ({placeholders})''', (company_id, *batch)).fetchall():
            sources[str(bucket['bucket_id'])] = str(bucket['source_type'])
    items = []
    incomplete = False
    for row in scanned:
        raw = allocations[str(row['ledger_id'])]
        valid = bool(raw) and all(isinstance(item, dict) and type(item.get('points')) is int
                                 and item['points'] > 0 and isinstance(item.get('bucket_id'), str)
                                 and item['bucket_id'] in sources for item in raw)
        if (not valid or sum(item['points'] for item in raw) != int(row['points'])
                or len({item['bucket_id'] for item in raw}) != len(raw)):
            incomplete = True
            continue
        if any(sources[item['bucket_id']] not in MERCHANT_SOURCES for item in raw):
            # Internal-only attempts must neither leak identifiers nor inflate merchant usage.
            if any(sources[item['bucket_id']] in MERCHANT_SOURCES for item in raw):
                incomplete = True
            continue
        outcomes = terminals.get(str(row['ledger_id']), [])
        state = 'reserved' if row['status'] == 'reserved' and not outcomes else 'needs_review'
        spent = None
        released = 0
        if len(outcomes) == 1 and outcomes[0]['status'] == 'completed':
            outcome = outcomes[0]
            if outcome['operation_type'] == 'settle' and row['status'] == 'settled' and 0 < int(outcome['points']) <= int(row['points']):
                state, spent = 'settled', int(outcome['points'])
                released = int(row['points']) - spent
            elif outcome['operation_type'] == 'release' and row['status'] == 'released':
                state, spent, released = 'released', 0, int(row['points'])
        items.append({
            'activity_id': hashlib.sha256(str(row['ledger_id']).encode()).hexdigest()[:16],
            'media_job_id': str(row['media_job_id']) if re.fullmatch(r'media_job_[a-zA-Z0-9_-]{1,64}', str(row['media_job_id'] or '')) else '',
            'state': state,
            'estimated_points': int(row['points']), 'spent_points': spent, 'released_points': released,
            'created_at': str(row['created_at']), 'updated_at': str(row['updated_at']),
        })
    return {
        'contract_version': '2026-09-25-merchant-media-usage-v1',
        'status': 'ready', 'held_points': max(0, int(held['held'])),
        'items': items[:limit], 'has_more': len(rows) > SCAN_LIMIT or len(items) > limit,
        'incomplete': incomplete, 'scope': 'recent_image_reservations',
    }

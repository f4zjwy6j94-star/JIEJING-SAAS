"""Safe JSON serialization helpers for API and CLI responses."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any


def json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")

"""Deterministic evidence checks for merchant-visible market quote answers.

This module is intentionally provider-neutral.  Search capture and publication
timestamps describe retrieval/publication, not the trading session represented
by a quoted number; only dates present in attributable source content may ground
session-specific claims.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_CITATION_RE = re.compile(r"\[(S\d{1,3})\]", flags=re.IGNORECASE)
_MARKET_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_-])[-+]?\d[\d,]*(?:\.\s*\d+)?\s*(?:%|％|点|點|美元|美金|元|USD\b|CNY\b|HKD\b)",
    flags=re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"(?<!\d)(20\d{2})-(0[1-9]|1[0-2])-([0-2]\d|3[01])(?!\d)")
_CHINESE_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>20\d{2})年(?P<month>0?[1-9]|1[0-2])月(?P<day>0?[1-9]|[12]\d|3[01])日"
)
_MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_ENGLISH_MONTH_TOKEN = "|".join(sorted(_MONTH_NAMES, key=len, reverse=True))
_ENGLISH_MONTH_DATE_RE = re.compile(
    rf"\b(?P<month>{_ENGLISH_MONTH_TOKEN})\.?\s+(?P<day>[0-3]?\d)(?:st|nd|rd|th)?[,]?\s+(?P<year>20\d{{2}})\b",
    re.IGNORECASE,
)
_ENGLISH_DAY_MONTH_DATE_RE = re.compile(
    rf"\b(?P<day>[0-3]?\d)(?:st|nd|rd|th)?\s+(?P<month>{_ENGLISH_MONTH_TOKEN})\.?[,]?\s+(?P<year>20\d{{2}})\b",
    re.IGNORECASE,
)
_PLAIN_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_-])[-+]?\d[\d,]*(?:\.\s*\d+)?")
_FORMATTED_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9_-])[-+]?(?:\d{1,3}(?:,\d{3})+(?:\.\s*\d+)?|\d+\.\s*\d+)"
)
_COLON_VALUE_RE = re.compile(
    r"(?<!\d)[:：]\s*(?P<number>[-+]?\d[\d,]*(?:\.\s*\d+)?)(?![\d:])"
)
_CURRENCY_NUMBER_RE = re.compile(
    r"(?:US\$|\$|￥|¥)\s*(?P<number>[-+]?\d[\d,]*(?:\.\s*\d+)?)",
    flags=re.IGNORECASE,
)
_QUOTE_VERB_NUMBER_RE = re.compile(
    r"(?:closed\s+at|closed\s+(?:at|of)|trading\s+at|last\s+price|price\s*(?:is|[:：])|"
    r"收于|报收于?|收盘\s*(?:为|于|[:：])?|现价\s*(?:为|[:：])?|报价\s*(?:为|[:：])?|成交价\s*(?:为|[:：])?)"
    r"\s*(?P<number>[-+]?\d[\d,]*(?:\.\s*\d+)?)",
    flags=re.IGNORECASE,
)
_CLOSE_VALUE_RE = re.compile(
    r"(?P<label>current\s*/?\s*close|closed\s+at|closing\s+(?:price|value)|close(?:\s+price)?|"
    r"收于|收於|报收于?|報收於?|收盘价?|收盤價?|收市[价價]?)\s*(?:为|為|于|於|at|of|[:：])?\s*"
    r"(?P<number>[-+]?\d[\d,]*(?:\.\s*\d+)?)",
    flags=re.IGNORECASE,
)
_NON_CURRENT_CLOSE_PREFIX_RE = re.compile(
    r"(?:previous(?:\s+day)?|prev(?:ious)?|prior|adjusted|adj|前|昨)\s*$",
    flags=re.IGNORECASE,
)
_NON_TICKER_WORDS = {
    "AI", "AT", "CEO", "CLOSE", "CURRENT", "CNY", "EDT", "EST", "ET",
    "HKD", "IS", "NASDAQ", "NOW", "NYSE", "PRICE", "STOCK", "THE", "TODAY",
    "USD", "WHAT",
}
_COMPANY_TICKERS = {
    "nvidia": "NVDA",
    "英伟达": "NVDA",
    "tesla": "TSLA",
    "特斯拉": "TSLA",
    "apple": "AAPL",
    "苹果": "AAPL",
}
_TIME_RE = re.compile(r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*(?:ET|EST|EDT))?\b", re.IGNORECASE)


def _source_content(record: dict[str, Any]) -> str:
    return " ".join(
        str(record.get(key) or "").strip()
        for key in ("title", "snippet", "summary")
        if str(record.get(key) or "").strip()
    )


def _dates_from_text(text: str) -> set[str]:
    raw = str(text or "")
    dates: set[str] = set()
    for match in _ISO_DATE_RE.finditer(raw):
        try:
            dates.add(datetime(*(int(part) for part in match.groups())).date().isoformat())
        except ValueError:
            continue
    for match in _CHINESE_DATE_RE.finditer(raw):
        try:
            dates.add(
                datetime(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                ).date().isoformat()
            )
        except ValueError:
            continue
    for pattern in (_ENGLISH_MONTH_DATE_RE, _ENGLISH_DAY_MONTH_DATE_RE):
        for match in pattern.finditer(raw):
            try:
                dates.add(
                    datetime(
                        int(match.group("year")),
                        _MONTH_NAMES[match.group("month").lower()],
                        int(match.group("day")),
                    ).date().isoformat()
                )
            except (KeyError, ValueError):
                continue
    return dates


def _strip_complete_dates(text: str) -> str:
    result = str(text or "")
    for pattern in (
        _ISO_DATE_RE,
        _CHINESE_DATE_RE,
        _ENGLISH_MONTH_DATE_RE,
        _ENGLISH_DAY_MONTH_DATE_RE,
    ):
        result = pattern.sub(" ", result)
    return result


def _content_trading_dates(record: dict[str, Any]) -> set[str]:
    # Do not read published_at/captured_at here.  Neither proves the market
    # session represented by a number on a dynamic quote page.
    return _dates_from_text(_source_content(record))


def _canonical_number(value: str) -> str:
    compact = re.sub(r"\s+", "", str(value or "")).replace(",", "").lstrip("+")
    if compact.startswith("-"):
        compact = compact[1:]
    try:
        number = Decimal(compact)
    except InvalidOperation:
        return ""
    rendered = format(number, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _market_claim_numbers(text: str) -> set[str]:
    without_dates = _strip_complete_dates(text)
    numbers = {
        number
        for match in _MARKET_NUMBER_RE.finditer(without_dates)
        if (number := _canonical_number(_PLAIN_NUMBER_RE.search(match.group(0)).group(0)))
    }
    for pattern in (_CURRENCY_NUMBER_RE, _QUOTE_VERB_NUMBER_RE, _COLON_VALUE_RE):
        numbers.update(
            number
            for match in pattern.finditer(without_dates)
            if (number := _canonical_number(match.group("number")))
        )
    numbers.update(
        number
        for match in _FORMATTED_VALUE_RE.finditer(without_dates)
        if (number := _canonical_number(match.group(0)))
    )
    return numbers


def _labeled_close_numbers(text: str) -> set[str]:
    normalized = re.sub(r"(?<=\d)\.\s+(?=\d)", ".", _strip_complete_dates(text))
    numbers: set[str] = set()
    for match in _CLOSE_VALUE_RE.finditer(normalized):
        prefix = normalized[max(0, match.start() - 24):match.start()]
        if _NON_CURRENT_CLOSE_PREFIX_RE.search(prefix):
            continue
        number = _canonical_number(match.group("number"))
        if number:
            numbers.add(number)
    return numbers


def _source_numbers(record: dict[str, Any]) -> set[str]:
    # Search-result sanitization historically inserted a space after decimal
    # punctuation ("26,939. 37").  Collapse it only between digits so prose
    # sentence boundaries remain untouched.
    content = re.sub(r"(?<=\d)\.\s+(?=\d)", ".", _source_content(record))
    without_dates = _strip_complete_dates(content)
    return {
        number
        for match in _PLAIN_NUMBER_RE.finditer(without_dates)
        if (number := _canonical_number(match.group(0)))
    }


def _instrument_key(text: str) -> str:
    original = _CITATION_RE.sub(" ", str(text or ""))
    lowered = original.lower()
    compact = re.sub(r"[\s_-]+", "", lowered)
    if any(marker in lowered for marker in ("nasdaq-100", "nasdaq 100")) or any(
        marker in compact for marker in ("nasdaq100", "纳斯达克100", "納斯達克100", "纳指100", "納指100")
    ) or re.search(r"(?:\^|\b)ndx\b", lowered):
        return "index:nasdaq_100"
    if any(marker in lowered for marker in ("nasdaq composite", "^ixic")) or any(
        marker in compact
        for marker in (
            "纳斯达克综合指数", "納斯達克綜合指數", "纳斯达克指数", "納斯達克指數",
            "纳指综合", "納指綜合", "纳指", "納指",
        )
    ):
        return "index:nasdaq_composite"
    if any(marker in lowered for marker in ("s&p 500", "s&p500", "standard & poor's 500", "^gspc")) or any(
        marker in compact for marker in ("标普500", "标普指数")
    ):
        return "index:sp_500"
    if any(marker in lowered for marker in ("dow jones", "dow 30", "^dji")) or any(
        marker in compact for marker in ("道琼斯指数", "道指")
    ):
        return "index:dow_jones"
    for alias, ticker in _COMPANY_TICKERS.items():
        if alias in lowered:
            return f"ticker:{ticker}"
    # Preserve original casing so ordinary English words (for example
    # "What") cannot be promoted to fake ticker symbols by uppercasing the
    # entire question.  Real ticker tokens are conventionally uppercase.
    for candidate in re.findall(r"\b[A-Z]{1,5}\b", original):
        if candidate not in _NON_TICKER_WORDS:
            return f"ticker:{candidate}"
    return ""


def _record_supports_instrument(record: dict[str, Any], expected: str) -> bool:
    if not expected:
        return True
    content = _source_content(record)
    observed = _instrument_key(content)
    if expected.startswith("ticker:"):
        ticker = expected.split(":", 1)[1]
        return bool(re.search(rf"\b{re.escape(ticker)}\b", content, flags=re.IGNORECASE))
    return observed == expected


def _market_direction(text: str) -> str:
    lowered = _strip_complete_dates(text).lower()
    up_markers = ("上涨", "上漲", "上升", "走高", "涨幅", "漲幅", "up ", "rose", "risen", "gained", "higher")
    down_markers = ("下跌", "下降", "走低", "跌幅", "down ", "fell", "fallen", "lost", "lower")
    has_up = any(marker in lowered for marker in up_markers) or bool(re.search(r"\+\s*\d", lowered))
    has_down = any(marker in lowered for marker in down_markers) or bool(re.search(r"-\s*\d", lowered))
    if has_up == has_down:
        return ""
    return "up" if has_up else "down"


def _parse_now(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def new_york_market_time(value: datetime) -> datetime:
    """Convert an aware datetime to New York market wall time."""

    try:
        return value.astimezone(ZoneInfo("America/New_York"))
    except ZoneInfoNotFoundError:
        # Minimal stdlib fallback for hosts that omit the Windows tzdata wheel.
        # US daylight time since 2007: second Sunday in March to first Sunday
        # in November.  ZoneInfo remains the default and authoritative path.
        utc_value = value.astimezone(timezone.utc)
        year = utc_value.year
        march_first = datetime(year, 3, 1, tzinfo=timezone.utc)
        second_sunday_day = 1 + ((6 - march_first.weekday()) % 7) + 7
        dst_start_utc = datetime(year, 3, second_sunday_day, 7, tzinfo=timezone.utc)
        november_first = datetime(year, 11, 1, tzinfo=timezone.utc)
        first_sunday_day = 1 + ((6 - november_first.weekday()) % 7)
        dst_end_utc = datetime(year, 11, first_sunday_day, 6, tzinfo=timezone.utc)
        offset_hours = -4 if dst_start_utc <= utc_value < dst_end_utc else -5
        return utc_value.astimezone(timezone(timedelta(hours=offset_hours), name="America/New_York"))


def _is_closing_query(message: str) -> bool:
    lowered = str(message or "").lower()
    return bool(re.search(r"\bclose\b", lowered)) or any(
        marker in lowered
        for marker in (
            "收盘", "收盤", "收市", "报收", "報收", "收于", "收於", "前收盘", "昨收",
            "closing", "closed", "close price", "previous close",
        )
    )


def _requested_session_date(message: str, now: str | datetime | None) -> tuple[str, str]:
    explicit_dates = _dates_from_text(message)
    if len(explicit_dates) == 1:
        return next(iter(explicit_dates)), "explicit_message_date"
    if len(explicit_dates) > 1:
        return "", "ambiguous_message_dates"
    lowered = str(message or "").lower()
    current_markers = ("今天", "当前", "當前", "最新", "现在", "現在", "今日", "today", "latest", "current", "now")
    if not any(marker in lowered for marker in current_markers):
        return "", "not_session_specific"
    parsed = _parse_now(now)
    if parsed is None:
        return "", "reference_time_unavailable"
    market_now = new_york_market_time(parsed)
    # This is deliberately not an exchange calendar.  Do not guess Friday on
    # weekends or skip exchange holidays.  A dated source must prove that a
    # session actually existed on the New York calendar date.
    if market_now.weekday() >= 5:
        return "", "exchange_calendar_required"
    if _is_closing_query(message):
        if (market_now.hour, market_now.minute) < (16, 0):
            return "", "regular_session_not_complete"
        return market_now.date().isoformat(), "new_york_calendar_after_close"
    return market_now.date().isoformat(), "new_york_calendar_intraday"


def market_quote_answer_quality(
    answer: str,
    source_records: list[dict[str, Any]],
    *,
    message: str,
    now: str | datetime | None = None,
) -> dict[str, Any]:
    """Return whether a market quote answer is grounded in cited source data."""

    reasons: list[str] = []
    answer_text = str(answer or "").strip()
    if not answer_text:
        reasons.append("empty_answer")
    has_market_numbers = bool(_market_claim_numbers(answer_text))
    insufficiency_markers = (
        "无法核实", "无法确认", "不能确认", "证据不足", "来源不足", "未能核实",
        "cannot verify", "unable to verify", "insufficient evidence", "not enough evidence",
    )
    honest_insufficient = not has_market_numbers and any(
        marker in answer_text.lower() for marker in insufficiency_markers
    )
    if honest_insufficient:
        return {
            "accepted": True,
            "reasons": [],
            "contract_version": "market_quote_answer_quality_v1",
            "secret_exposed": False,
        }
    if not source_records:
        reasons.append("market_quote_source_required")
    citation_ids = {item.upper() for item in _CITATION_RE.findall(answer_text)}
    records_by_citation = {
        str(record.get("citation_id") or f"S{index}").strip().upper(): record
        for index, record in enumerate(source_records, start=1)
        if isinstance(record, dict)
    }
    cited_records = [records_by_citation[item] for item in citation_ids if item in records_by_citation]
    expected_instrument = _instrument_key(message)
    answer_instrument = _instrument_key(answer_text)
    if expected_instrument and answer_instrument and answer_instrument != expected_instrument:
        reasons.append("market_answer_instrument_mismatch")
    requested_session_date, session_basis = _requested_session_date(message, now)
    answer_dates = _dates_from_text(answer_text)
    if has_market_numbers and not citation_ids:
        reasons.append("market_numeric_claim_citation_required")
    if has_market_numbers and citation_ids and not cited_records:
        reasons.append("market_numeric_claim_valid_citation_required")
    if has_market_numbers and cited_records and not any(_content_trading_dates(record) for record in cited_records):
        reasons.append("cited_source_trading_date_required")
    for clause in re.split(r"(?<=[。！？；;])|\n+", answer_text):
        claim_numbers = _market_claim_numbers(clause)
        if not claim_numbers:
            continue
        clause_citations = {item.upper() for item in _CITATION_RE.findall(clause)}
        clause_records = [records_by_citation[item] for item in clause_citations if item in records_by_citation]
        if not clause_citations:
            if "market_numeric_claim_citation_required" not in reasons:
                reasons.append("market_numeric_claim_citation_required")
            continue
        if not clause_records:
            if "market_numeric_claim_valid_citation_required" not in reasons:
                reasons.append("market_numeric_claim_valid_citation_required")
            continue
        matching_instrument_records = [
            record for record in clause_records if _record_supports_instrument(record, expected_instrument)
        ]
        if expected_instrument and not matching_instrument_records:
            reasons.append("cited_source_instrument_mismatch")
            continue
        evidence_records = matching_instrument_records or clause_records
        if not any(
            claim_numbers.issubset(_source_numbers(record))
            for record in evidence_records
        ):
            reasons.append("market_numeric_claim_not_supported_by_citation")
            continue
        if _is_closing_query(message):
            answer_close_numbers = _labeled_close_numbers(clause)
            close_supported = any(
                (
                    answer_close_numbers.issubset(_labeled_close_numbers(_source_content(record)))
                    if answer_close_numbers
                    else bool(claim_numbers & _labeled_close_numbers(_source_content(record)))
                )
                for record in evidence_records
            )
            if not close_supported:
                reasons.append("market_close_claim_not_supported_by_close_field")
                continue
        if session_basis not in {"not_session_specific", "explicit_message_date"} and not requested_session_date:
            reasons.append("requested_market_session_unresolved")
            continue
        if requested_session_date and not answer_dates:
            reasons.append("market_answer_trading_date_required")
            continue
        if requested_session_date and requested_session_date not in answer_dates:
            reasons.append("market_answer_not_requested_session")
        if requested_session_date and not any(
            claim_numbers.issubset(_source_numbers(record))
            and _content_trading_dates(record) == {requested_session_date}
            for record in evidence_records
        ):
            reasons.append("cited_source_not_requested_session")
            continue
        if session_basis == "new_york_calendar_intraday" and not _TIME_RE.search(clause):
            reasons.append("market_answer_timestamp_required")
            continue
        if session_basis == "new_york_calendar_intraday" and not any(
            claim_numbers.issubset(_source_numbers(record))
            and _content_trading_dates(record) == {requested_session_date}
            and _TIME_RE.search(_source_content(record))
            for record in evidence_records
        ):
            reasons.append("cited_source_timestamp_required")
            continue
        answer_direction = _market_direction(clause)
        if answer_direction and not any(
            claim_numbers.issubset(_source_numbers(record))
            and _market_direction(_source_content(record)) == answer_direction
            for record in evidence_records
        ):
            reasons.append("market_direction_not_supported_by_citation")
    return {
        "accepted": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "contract_version": "market_quote_answer_quality_v1",
        "secret_exposed": False,
    }

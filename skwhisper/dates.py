"""Ground relative dates in a session digest against the session's event time.

A digest is written long after the conversation (backlog runs can be weeks
late), so "yesterday" in the summary must mean the day before the
conversation, never the day before the digest ran. The model is told the event
date, and this deterministic pass then appends the resolved ISO date in
parentheses after each relative phrase, keeping the original words. It never
reads the wall clock.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]
_WD = "(?:" + "|".join(w.capitalize() for w in _WEEKDAYS) + ")"

# Phrases that put a bare "on Friday" in the future rather than the past.
_FUTURE_RE = re.compile(
    r"\b(will|won't|going to|plans? to|planned|scheduled|due|upcoming|next steps?|"
    r"to be|should|need to|needs to|expects?|expected|by)\b|'ll\b",
    re.IGNORECASE,
)

_PHRASE_RE = re.compile(
    r"\b(?P<phrase>"
    r"day before yesterday|day after tomorrow|yesterday|tomorrow|today|tonight|last night|"
    r"last week|next week|last month|next month|"
    r"(?:last|next|this|on)\s+" + _WD + r")\b(?!\s*\(\s*(?:week of )?\d{4}-\d{2})",
    re.IGNORECASE,
)


def parse_event_at(value) -> datetime | None:
    """Parse an ISO timestamp or epoch seconds into an aware UTC datetime."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    except (ValueError, OverflowError, OSError):
        return None
    return (
        dt.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None
        else dt.astimezone(timezone.utc)
    )


def session_event_at(session: dict) -> datetime | None:
    """When the conversation happened: its newest message timestamp, else file mtime.

    Returns None when neither is known, in which case nothing is resolved
    (guessing from the wall clock is exactly the bug this module prevents).
    """
    stamps = [parse_event_at(m.get("timestamp")) for m in session.get("messages") or []]
    stamps = [s for s in stamps if s is not None]
    if stamps:
        return max(stamps)
    return parse_event_at(session.get("last_seen"))


def _weekday_date(base, wd: int, mode: str, sentence: str):
    cur = base.weekday()
    if mode == "last":
        delta = -((cur - wd) % 7 or 7)
    elif mode == "next":
        delta = (wd - cur) % 7 or 7
    elif mode == "this":
        delta = wd - cur  # same Monday-Sunday week
    else:  # bare "on <weekday>": tense decides
        if _FUTURE_RE.search(sentence):
            delta = (wd - cur) % 7 or 7
        else:
            delta = -((cur - wd) % 7 or 7)
    return base + timedelta(days=delta)


def _resolve(phrase: str, base, sentence: str) -> str | None:
    p = phrase.lower()
    day = {
        "yesterday": -1,
        "last night": -1,
        "today": 0,
        "tonight": 0,
        "tomorrow": 1,
        "day before yesterday": -2,
        "day after tomorrow": 2,
    }
    if p in day:
        return (base + timedelta(days=day[p])).isoformat()
    monday = base - timedelta(days=base.weekday())
    if p == "last week":
        return f"week of {(monday - timedelta(days=7)).isoformat()}"
    if p == "next week":
        return f"week of {(monday + timedelta(days=7)).isoformat()}"
    if p in ("last month", "next month"):
        step = -1 if p == "last month" else 1
        idx = base.year * 12 + base.month - 1 + step
        return f"{idx // 12:04d}-{idx % 12 + 1:02d}"
    mode, _, name = p.partition(" ")
    return _weekday_date(base, _WEEKDAYS.index(name), mode, sentence).isoformat()


def resolve_relative_dates(text: str, event_at: datetime | None) -> str:
    """Append "(ISO date)" after each relative date phrase, anchored at event_at."""
    if not text or event_at is None:
        return text
    base = event_at.date()
    out, last = [], 0
    for m in _PHRASE_RE.finditer(text):
        start = text.rfind(".", 0, m.start()) + 1
        end = text.find(".", m.end())
        sentence = text[start : end if end != -1 else len(text)]
        resolved = _resolve(m.group("phrase"), base, sentence)
        if resolved is None:
            continue
        out.append(text[last : m.end()])
        out.append(f" ({resolved})")
        last = m.end()
    out.append(text[last:])
    return "".join(out)

"""Relative dates resolve against the session's event time, never the wall clock."""

import asyncio
from datetime import datetime, timezone

from skwhisper import daemon
from skwhisper.dates import resolve_relative_dates, session_event_at

# Friday 2026-03-13, far from any plausible "now".
EVENT = datetime(2026, 3, 13, 15, 0, tzinfo=timezone.utc)


def test_day_words():
    out = resolve_relative_dates("Shipped it yesterday and will test tomorrow.", EVENT)
    assert (
        out == "Shipped it yesterday (2026-03-12) and will test tomorrow (2026-03-14)."
    )


def test_week_and_month():
    out = resolve_relative_dates("Last week we met; next month we ship.", EVENT)
    assert "Last week (week of 2026-03-02)" in out
    assert "next month (2026-04)" in out


def test_weekdays():
    assert "last Monday (2026-03-09)" in resolve_relative_dates(
        "Met last Monday.", EVENT
    )
    assert "next Monday (2026-03-16)" in resolve_relative_dates(
        "See you next Monday.", EVENT
    )
    assert "on Tuesday (2026-03-10)" in resolve_relative_dates(
        "They called on Tuesday.", EVENT
    )
    assert "on Tuesday (2026-03-17)" in resolve_relative_dates(
        "The demo will be on Tuesday.", EVENT
    )


def test_idempotent_and_case_preserved():
    once = resolve_relative_dates("Yesterday it broke.", EVENT)
    assert once == "Yesterday (2026-03-12) it broke."
    assert resolve_relative_dates(once, EVENT) == once


def test_no_event_leaves_text_alone():
    assert resolve_relative_dates("yesterday", None) == "yesterday"


def test_session_event_at_prefers_message_timestamps():
    s = {
        "messages": [
            {"timestamp": "2026-03-13T15:00:00Z"},
            {"timestamp": "2026-03-12T01:00:00Z"},
            {"timestamp": ""},
        ],
        "last_seen": 1.0,
    }
    assert session_event_at(s) == EVENT
    assert session_event_at({"messages": [], "last_seen": 0}).year == 1970
    assert session_event_at({"messages": []}) is None


def test_digest_session_resolves_against_event_at(tmp_path, monkeypatch):
    seen = {}

    class Ollama:
        async def summarize(self, text):
            seen["text"] = text
            return "We fixed the bug yesterday and deploy tomorrow, per the notes."

        async def extract_topics(self, summary):
            return {"topics": ["bug"], "people": [], "projects": []}

    class Mem:
        def write_snapshot(self, **kw):
            seen["content"] = kw["content"]
            return "id1"

    class Cfg:
        skip_cron = False
        min_transcript_chars = 1
        user_label, agent_label = "User", "Agent"
        state_dir = tmp_path
        sessions_dir = tmp_path

    async def noop(*a, **k):
        return True

    monkeypatch.setattr(daemon, "_vector_write", noop)
    monkeypatch.setattr(daemon, "mark_digested", lambda *a, **k: None)
    monkeypatch.setattr(daemon, "update_patterns", lambda *a, **k: None)
    session = {
        "session_id": "s" * 12,
        "path": None,
        "new_offset": 0,
        "messages": [
            {
                "role": "user",
                "text": "we fixed the bug yesterday",
                "timestamp": "2026-03-13T15:00:00Z",
            }
        ],
    }
    assert asyncio.run(daemon.digest_session(Cfg(), session, Ollama(), None, Mem()))
    assert "[Conversation date: 2026-03-13]" in seen["text"]
    assert "yesterday (2026-03-12)" in seen["content"]
    assert "tomorrow (2026-03-14)" in seen["content"]

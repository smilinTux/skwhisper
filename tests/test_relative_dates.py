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
    assert session_event_at({"messages": [], "last_seen": 0}) is None
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


def test_event_date_keeps_own_offset():
    from datetime import date

    from skwhisper.dates import event_date, parse_event_at

    west = parse_event_at("2026-03-13T23:30:00-08:00")  # 07:30 UTC next day
    assert event_date(west) == date(2026, 3, 13)
    assert "yesterday (2026-03-12)" in resolve_relative_dates("yesterday", west)
    east = parse_event_at("2026-03-14T00:10:00+09:00")  # 15:10 UTC previous day
    assert event_date(east) == date(2026, 3, 14)
    assert "yesterday (2026-03-13)" in resolve_relative_dates("yesterday", east)


def test_naive_timestamp_uses_its_own_date():
    from skwhisper.dates import event_date, parse_event_at

    assert event_date(parse_event_at("2026-03-13T23:30:00")).isoformat() == "2026-03-13"


def test_header_uses_own_offset_date(tmp_path, monkeypatch):
    from skwhisper.dates import event_date, session_event_at

    s = {"messages": [{"timestamp": "2026-03-13T23:30:00-08:00"}]}
    assert event_date(session_event_at(s)).isoformat() == "2026-03-13"


def test_guards_leave_code_urls_quotes_alone():
    for t in [
        "run `echo yesterday` now",
        "```\nsleep until tomorrow\n```",
        "see https://x.io/yesterday/last-week",
        'he said "see you tomorrow" then left',
        "he said \u201csee you tomorrow\u201d then left",
    ]:
        assert resolve_relative_dates(t, EVENT) == t, t
    assert "tomorrow (2026-03-14)" in resolve_relative_dates('"q" and tomorrow', EVENT)


def test_possessive_left_alone():
    t = "Reviewed last week's PR and yesterday\u2019s fix."
    assert resolve_relative_dates(t, EVENT) == t


def test_existing_parenthetical_date_not_doubled():
    for t in ["fixed yesterday (March 12) ok", "fixed yesterday (2026-03-12) ok"]:
        assert resolve_relative_dates(t, EVENT) == t


def test_should_is_not_future():
    assert "on Tuesday (2026-03-10)" in resolve_relative_dates(
        "It should have run on Tuesday.", EVENT
    )


def test_digest_source_ref_names_session_and_byte_range(tmp_path, monkeypatch):
    seen = {}

    class Ollama:
        async def summarize(self, text):
            return "We decided to ship the gateway change after review today."

        async def extract_topics(self, summary):
            return {"topics": ["gateway"], "people": [], "projects": []}

    class Mem:
        def write_snapshot(self, **kw):
            seen.update(kw)
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
        "session_id": "20260101_abc",
        "path": None,
        "new_offset": 900,
        "start_offset": 400,
        "messages": [{"role": "user", "text": "we shipped the gateway change", "timestamp": "2026-01-01T00:00:00Z"}],
    }
    asyncio.run(daemon.digest_session(Cfg(), session, Ollama(), None, Mem()))
    assert seen["source_ref"] == "session:20260101_abc@400-900"

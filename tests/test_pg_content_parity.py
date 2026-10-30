"""digest_session: the pg row carries the same content as the flat file."""
import asyncio

import skwhisper.daemon as daemon


class _Ollama:
    def __init__(self, summary):
        self._summary = summary

    async def summarize(self, text):
        return self._summary

    async def extract_topics(self, summary):
        return {"topics": ["alpha"], "people": [], "projects": [], "decisions": []}


class _Vec:
    def __init__(self):
        self.payloads = []

    async def embed(self, text):
        assert len(text) <= 800
        return [0.0] * 4

    async def upsert(self, vector, payload, point_id=None):
        self.payloads.append((point_id, payload))
        return True


class _Mem:
    def __init__(self):
        self.written = []

    def write_snapshot(self, title, content, **kw):
        self.written.append((title, content))
        return "mem-1"


def test_long_digest_reaches_pg_untruncated(monkeypatch):
    monkeypatch.setattr(daemon, "classify_session", lambda m, p=None: "human")
    monkeypatch.setattr(daemon, "update_patterns", lambda *a, **k: None)
    monkeypatch.setattr(daemon, "mark_digested", lambda *a, **k: None)

    class Cfg:
        skip_cron = False
        min_transcript_chars = 0  # this test is about pg content, not the empty guard
        user_label = "User"
        agent_label = "Agent"
        state_dir = "x"

    summary = "word " * 1000  # 5000 chars, well past the old 2000 cut
    vec, mem = _Vec(), _Mem()
    session = {"session_id": "s1", "messages": [{"role": "user", "text": "hi"}], "new_offset": 1}
    assert asyncio.run(daemon.digest_session(Cfg(), session, _Ollama(summary), vec, mem)) is True

    (flat_title, flat_content), = mem.written
    (pid, payload), = vec.payloads
    assert pid == "mem-1"
    assert len(flat_content) > 2000
    assert payload["content"] == flat_content
    assert payload["title"] == flat_title

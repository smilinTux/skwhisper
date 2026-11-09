"""The pg row's memory_json is the flat-file record, id included.

It used to be the digest payload (tier/session_type, no id). skmemory parses
memory_json back into a Memory, so a missing id became a fresh random id on
every read: one memory surfaced as an extra, untraceable copy in search.
"""
import asyncio
import json

import skwhisper.clients.pgmem as pgmem
import skwhisper.daemon as daemon
from skwhisper.clients.skmemory import SKMemoryWriter


class _Ollama:
    async def summarize(self, text):
        return "A real digest about the work that happened in this session."

    async def extract_topics(self, summary):
        return {"topics": ["alpha"], "people": [], "projects": [], "decisions": []}


class _Vec:
    def __init__(self):
        self.calls = []

    async def embed(self, text):
        return [0.0] * 4

    async def upsert(self, vector, payload, point_id=None):
        self.calls.append((point_id, payload))
        return True


class _Cfg:
    skip_cron = False
    min_transcript_chars = 0
    user_label = "User"
    agent_label = "Agent"
    state_dir = "x"


def _patch_daemon(monkeypatch):
    monkeypatch.setattr(daemon, "classify_session", lambda m, p=None: "human")
    monkeypatch.setattr(daemon, "update_patterns", lambda *a, **k: None)
    monkeypatch.setattr(daemon, "mark_digested", lambda *a, **k: None)


def test_digest_sends_the_flat_record_as_memory_json(tmp_path, monkeypatch):
    _patch_daemon(monkeypatch)
    writer, vec = SKMemoryWriter(tmp_path), _Vec()
    session = {"session_id": "s1", "messages": [{"role": "user", "text": "hi"}], "new_offset": 7}
    assert asyncio.run(daemon.digest_session(_Cfg(), session, _Ollama(), vec, writer)) is True

    (pid, payload), = vec.calls
    flat = json.loads((tmp_path / "short-term" / f"{pid}.json").read_text())
    assert payload["memory_json"] == flat
    assert payload["memory_json"]["id"] == pid
    assert payload["memory_json"]["source_ref"] == "session:s1@0-7"


class _Cursor:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.sink.append(params)


class _Conn(_Cursor):
    def cursor(self):
        return _Cursor(self.sink)

    def commit(self):
        pass


def _stored_record(monkeypatch, payload, point_id):
    sink = []
    monkeypatch.setattr(pgmem.psycopg, "connect", lambda *a, **k: _Conn(sink))
    client = pgmem.PGMemClient(dsn="postgresql://unused", agent="a")
    assert client._upsert_sync([0.0] * 4, payload, point_id) is True
    (params,) = sink
    return params, json.loads(params[10])


def test_upsert_stores_the_canonical_record(monkeypatch):
    record = {"id": "mem-1", "title": "T", "content": "C", "layer": "short-term"}
    payload = {"title": "T", "content": "C", "tier": "short-term", "memory_json": record}
    params, stored = _stored_record(monkeypatch, payload, "mem-1")
    assert stored == record
    assert params[0] == "mem-1"
    assert "memory_json" in payload  # the caller's dict is not mutated


def test_upsert_without_a_record_still_carries_the_row_id(monkeypatch):
    payload = {"title": "T", "content": "C", "tier": "short-term"}
    params, stored = _stored_record(monkeypatch, payload, None)
    assert stored["id"] == params[0]
    assert stored["title"] == "T"

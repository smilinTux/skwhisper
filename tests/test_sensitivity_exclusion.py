"""whisper.md never selects sensitive memories (sacred, grief, medical, family-private ...)."""
import asyncio
import sqlite3

import pytest

from skwhisper import sensitivity as sv
from skwhisper.clients import pgmem
from skwhisper.clients.sqlite_recency import SQLiteRecencyClient

VARIANTS = [
    "sacred", "SACRED", "Grief", "medical", "family-private", "family_private", "Family Private",
    "familyprivate", "personal_history", "PersonalHistory", "sаcred", "ｓａｃｒｅｄ",
    "griεf", "private", "therapy",
]


@pytest.mark.parametrize("tag", VARIANTS)
def test_variants_are_sensitive(tag):
    assert sv.is_sensitive([tag])


def test_ordinary_tags_are_not_sensitive():
    assert not sv.is_sensitive(["ops", "pr", "retrieval"])
    assert sv.csv_is_sensitive("ops,sacred") and not sv.csv_is_sensitive("ops,pr") and not sv.csv_is_sensitive("")


def _db(path, rows):
    c = sqlite3.connect(path)
    c.executescript(
        """CREATE TABLE memories (id TEXT PRIMARY KEY, title TEXT, summary TEXT, content_preview TEXT,
        tags TEXT, layer TEXT, created_at TEXT NOT NULL);
        CREATE VIEW active_memories AS SELECT id,title,summary,content_preview,tags,layer,created_at,
        'today' AS context_tier FROM memories;"""
    )
    for i, (title, tags) in enumerate(rows):
        c.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?)",
                  (f"m{i}", title, "", "", tags, "mid-term", f"2026-11-01T12:{59 - i:02d}:00"))
    c.commit()
    c.close()


def test_recency_skips_sensitive_and_takes_the_next_newest(tmp_path):
    db = tmp_path / "index.db"
    rows = [("sacred one", "sacred"), ("grief two", "Grief,x"), ("variant", "family_private")]
    rows += [(f"ordinary {i}", "ops") for i in range(5)]
    _db(db, rows)
    got = SQLiteRecencyClient(db).recent(limit=3)
    assert [r["title"] for r in got] == ["ordinary 0", "ordinary 1", "ordinary 2"]


def test_recency_pages_past_a_long_sensitive_run(tmp_path):
    db = tmp_path / "index.db"
    rows = [(f"s{i}", "sacred") for i in range(200)] + [("the one", "ops")]
    _db(db, rows)
    assert [r["title"] for r in SQLiteRecencyClient(db).recent(limit=2)] == ["the one"]


class _Cur:
    def __init__(self, rows, tags):
        self.rows, self.tags, self.last = rows, tags, None

    def execute(self, sql, params=None):
        self.last = sql

    def fetchall(self):
        return self.rows if "hybrid_search" in self.last else self.tags

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn(_Cur):
    def cursor(self):
        return self


def test_pg_search_drops_sensitive_and_unreadable_rows(monkeypatch):
    rows = [("a", "long-term", "Vigil", "c", 0.9), ("b", "long-term", "Ops note", "c", 0.8),
            ("c", "long-term", "Variant", "c", 0.7), ("d", "long-term", "No tags row", "c", 0.6)]
    tags = [("a", ["sacred"]), ("b", ["ops"]), ("c", ["sаcred"])]  # d missing: fail closed
    monkeypatch.setattr(pgmem.psycopg, "connect", lambda *a, **k: _Conn(rows, tags))
    client = pgmem.PGMemClient(dsn="postgresql://x", agent="t")
    out = asyncio.run(client.search("q", [0.0], top_k=5))
    assert [r["id"] for r in out] == ["b"]
    assert out[0]["payload"]["tags"] == ["ops"]


def test_stems_and_normalization_match_skmemory():
    skm = pytest.importorskip("skmemory.hooks.sensitivity", reason="packaged skmemory predates the helper")
    assert sv.SENSITIVE_STEMS == skm.SENSITIVE_STEMS
    assert sv.OWNER_ONLY_STEMS == skm.OWNER_ONLY_STEMS
    for t in VARIANTS + ["ops", "Sacred Ground", "legal-docs"]:
        assert sv.normalize(t) == skm.normalize(t)
        assert sv.is_sensitive([t]) == skm.is_sensitive([t])

"""Tests for the SQLite recency client (relational/recency memory layer)."""
import sqlite3
from pathlib import Path

from skwhisper.clients.sqlite_recency import SQLiteRecencyClient

# Minimal replica of the skmemory `active_memories` view contract.
_SCHEMA = """
CREATE TABLE memories (
  id TEXT PRIMARY KEY, title TEXT, summary TEXT, content_preview TEXT,
  tags TEXT, layer TEXT, importance REAL DEFAULT 0.5, access_count INTEGER DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE VIEW active_memories AS
SELECT id, title, summary, content_preview, tags, layer, created_at, importance, access_count,
  CASE
    WHEN DATE(created_at) = CURRENT_DATE THEN 'today'
    WHEN DATE(created_at) = DATE('now','-1 day') THEN 'yesterday'
    WHEN DATE(created_at) >= DATE('now','-7 days') THEN 'week'
    ELSE 'historical'
  END AS context_tier
FROM memories WHERE created_at >= DATE('now','-30 days');
"""


def _make_db(path: Path):
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO memories (id,title,content_preview,created_at) VALUES (?,?,?,?)",
        [
            ("m-today", "Today note", "happened today", "datetime('now')"),
        ],
    )
    # created_at needs real datetimes; insert via SQL expressions
    conn.execute("DELETE FROM memories")
    conn.execute("INSERT INTO memories (id,title,content_preview,created_at) VALUES ('m-today','Today','now-ish', datetime('now'))")
    conn.execute("INSERT INTO memories (id,title,content_preview,created_at) VALUES ('m-yest','Yesterday','y', datetime('now','-1 day'))")
    conn.execute("INSERT INTO memories (id,title,content_preview,created_at) VALUES ('m-old','Old','o', datetime('now','-20 day'))")
    conn.commit()
    conn.close()


def test_recent_returns_newest_within_tiers(tmp_path):
    db = tmp_path / "index.db"
    _make_db(db)
    client = SQLiteRecencyClient(db)
    rows = client.recent(limit=8)
    ids = [r["id"] for r in rows]
    # today + yesterday are in default tiers; the 20-day-old one ('historical') is excluded
    assert "m-today" in ids
    assert "m-yest" in ids
    assert "m-old" not in ids
    # newest first
    assert ids[0] == "m-today"
    # tier is populated
    assert rows[0]["context_tier"] == "today"


def test_missing_db_returns_empty(tmp_path):
    client = SQLiteRecencyClient(tmp_path / "nope.db")
    assert client.recent() == []


def test_limit_respected(tmp_path):
    db = tmp_path / "index.db"
    _make_db(db)
    assert len(SQLiteRecencyClient(db).recent(limit=1)) == 1

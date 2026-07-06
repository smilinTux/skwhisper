"""SQLite recency client for skwhisper — the relational/recency layer.

Reads the local skmemory SQLite index (`index.db`) for the *latest* memories via
the `active_memories` view. This is the structured/recency half of memory:

  - **SQLite (this client)** answers *"what happened recently / this session"* —
    a fast, local, dependency-light `created_at` query. Works even if Docker/pg is down.
  - **pgmem (skmem-pg)** answers *"what's semantically relevant across all history"* —
    vectors + BM25 + graph.

Both index the same flat-file source of truth. Decoupled by design — no skmemory
import, read-only raw SQL — mirroring `pgmem.py`.
"""
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("skwhisper.sqlite_recency")

# Recency tiers (from the active_memories view). "historical" (>7d, <=30d) is excluded
# by default — skwhisper wants the *latest* context, not the whole 30-day window.
DEFAULT_TIERS = ("today", "yesterday", "week")


class SQLiteRecencyClient:
    """Read-only accessor for the newest memories in the skmemory SQLite index."""

    def __init__(self, index_db: str | Path):
        self.index_db = Path(index_db)

    def recent(self, limit: int = 8, tiers: tuple[str, ...] = DEFAULT_TIERS) -> list[dict]:
        """Return up to ``limit`` newest memories (created_at DESC) within ``tiers``.

        Each dict: id, title, summary, content_preview, tags, layer, created_at, context_tier.
        Returns ``[]`` (never raises) if the index is missing or unreadable — recency is a
        best-effort enrichment, not a hard dependency.
        """
        if not self.index_db.exists():
            log.info("SQLite index not found at %s — skipping recency feed", self.index_db)
            return []
        placeholders = ",".join("?" for _ in tiers)
        try:
            # Open read-only so we never interfere with the writer/daemon holding index.db.
            conn = sqlite3.connect(f"file:{self.index_db}?mode=ro", uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    f"SELECT id, title, summary, content_preview, tags, layer, "
                    f"       created_at, context_tier "
                    f"FROM active_memories "
                    f"WHERE context_tier IN ({placeholders}) "
                    f"ORDER BY created_at DESC LIMIT ?",
                    (*tiers, limit),
                ).fetchall()
            finally:
                conn.close()
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            log.warning("SQLite recency read failed (%s) — continuing without recency feed", e)
            return []

"""Local Postgres + pgvector memory client for skwhisper.

Sovereign vector client (the only backend): reads/writes the shared
`memories` table in skmem-pg (.158:5432), embeds via the mxbai-embed-large server
(.100:11434), and searches via the hybrid (vector + BM25 RRF) SQL function
`hybrid_search_memories()`. Decoupled — no skmemory import; raw SQL + httpx.

Interface:
  - await embed(text) -> list[float]            (mxbai-embed-large, 1024-dim)
  - await search(q_text, q_vec, top_k) -> [{"payload": {...}, "score": float}]
  - await upsert(vector, payload, point_id)
  - await close()
"""
import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import httpx
import psycopg

from ..pgdsn import resolve_dsn
from ..sensitivity import is_sensitive

log = logging.getLogger("skwhisper.pgmem")

EMBED_URL = os.environ.get(
    "SKMEMORY_EMBED_URL", "http://192.168.0.100:11434/api/embed"  # mxbai (Ollama); was :11435 bge
)
EMBED_MODEL = os.environ.get("SKMEMORY_EMBED_MODEL", "mxbai-embed-large")  # was bge-legal-v2


class PGMemClient:
    """Hybrid (vector+BM25) memory over local Postgres; bge-legal-v2 embeddings."""

    def __init__(self, dsn: str | None = None, embed_url: str = EMBED_URL,
                 embed_model: str = EMBED_MODEL, agent: str | None = None):
        self._dsn = dsn
        self.embed_url = embed_url
        self.embed_model = embed_model
        self.agent = agent
        self._http: httpx.AsyncClient | None = None

    @property
    def dsn(self) -> str:
        # Resolved lazily from the canonical env on every use, never frozen at import.
        return self._dsn or resolve_dsn()

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def embed(self, text: str) -> list[float]:
        """Embed text via the bge-legal-v2 server (Ollama /api/embed shape)."""
        c = await self._client()
        resp = await c.post(self.embed_url,
                            json={"model": self.embed_model, "input": text})
        resp.raise_for_status()
        data = resp.json()
        embs = data.get("embeddings")
        if embs:
            return embs[0]
        if data.get("embedding"):
            return data["embedding"]
        if data.get("data"):  # OpenAI shape fallback
            return data["data"][0]["embedding"]
        raise ValueError(f"no embedding in response: {list(data.keys())}")

    @staticmethod
    def _vec_literal(vec: list[float]) -> str:
        return "[" + ",".join(repr(float(x)) for x in vec) + "]"

    @staticmethod
    def _bm25_query(text: str, max_words: int = 50) -> str:
        """Sanitize free text into a safe ParadeDB BM25 query.

        ParadeDB's `@@@ <text>` parses query syntax, so URLs, colons, parens,
        and bare and/or/not break it. Reduce to plain alphanumeric word tokens.
        """
        text = re.sub(r"https?://\S+", " ", text)
        text = re.sub(r"[^A-Za-z0-9\s]", " ", text)
        stop = {"and", "or", "not"}
        words = [w for w in text.split() if w.lower() not in stop and len(w) > 1]
        return " ".join(words[:max_words]) or "memory"

    # --- search (curator) -------------------------------------------------
    def _search_sync(self, q_text: str, q_vec: list[float], k: int) -> list[dict]:
        sql = ("SELECT id, layer, title, content, score "
               "FROM hybrid_search_memories(%s, %s::vector, %s, %s)")
        out: list[dict] = []
        bm_q = self._bm25_query(q_text)
        with psycopg.connect(self.dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                # Over-fetch: sensitive rows (sacred, grief, medical, ...) are dropped
                # below and must not shrink the result set.
                cur.execute(sql, (bm_q, self._vec_literal(q_vec), k * 3, self.agent))
                rows = cur.fetchall()
                ids = [r[0] for r in rows]
                tags_by_id: dict = {}
                if ids:
                    cur.execute("SELECT id, tags FROM memories WHERE id = ANY(%s)", (ids,))
                    tags_by_id = {i: list(t or []) for i, t in cur.fetchall()}
        for _id, layer, title, content, score in rows:
            tags = tags_by_id.get(_id)
            # Fail closed: a row whose tags cannot be read is not shown.
            if tags is None or is_sensitive(tags):
                continue
            out.append({
                "id": _id,
                "payload": {
                    "title": title or "untitled",
                    "content": content or "",
                    "tags": tags,
                    "tier": layer,
                },
                "score": float(score) if score is not None else 0.0,
            })
        return out[:k]

    async def search(self, q_text: str, q_vec: list[float],
                     top_k: int = 10, score_threshold: float = 0.0) -> list[dict]:
        return await asyncio.to_thread(self._search_sync, q_text, q_vec, top_k)

    # --- upsert (daemon digest) ------------------------------------------
    def _upsert_sync(self, vector: list[float], payload: dict, point_id: str | None) -> bool:
        pid = point_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        # memory_json is what skmemory parses back into a Memory. It used to be
        # this digest payload (tier/session_type, no id), and on conflict it
        # overwrote skmemory's canonical record for the same id. Every read then
        # minted a fresh random id for the row, so one memory surfaced as an
        # untraceable duplicate that recall could not find (nor, 2026-11-09:
        # 347 lumina + 213 opus rows). Store the canonical record when given,
        # and never a record without the row's id.
        payload = dict(payload)
        record = payload.pop("memory_json", None) or dict(payload)
        record["id"] = pid
        tags = payload.get("tags") or []
        sql = (
            "INSERT INTO memories "
            "(id, layer, role, title, content, summary, tags, source, "
            " created_at, updated_at, memory_json, embedding, agent) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s) "
            "ON CONFLICT (id) DO UPDATE SET "
            " content=EXCLUDED.content, summary=EXCLUDED.summary, tags=EXCLUDED.tags, "
            " updated_at=EXCLUDED.updated_at, memory_json=EXCLUDED.memory_json, "
            " embedding=EXCLUDED.embedding"
        )
        with psycopg.connect(self.dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    pid,
                    payload.get("tier", "short-term"),
                    payload.get("role", "general"),
                    payload.get("title", "untitled"),
                    payload.get("content", ""),
                    payload.get("summary", payload.get("content", ""))[:2000],
                    tags,
                    payload.get("source", "skwhisper"),
                    now, now,
                    json.dumps(record),
                    self._vec_literal(vector),
                    self.agent,
                ))
            conn.commit()
        return True

    async def upsert(self, vector: list[float], payload: dict,
                     point_id: str | None = None) -> bool:
        try:
            return await asyncio.to_thread(self._upsert_sync, vector, payload, point_id)
        except Exception as e:
            from ..pgdsn import redact
            log.error("pgmem upsert failed: %s", redact(e))
            return False

    async def close(self):
        if self._http is not None:
            await self._http.aclose()
            self._http = None

"""Local Postgres + pgvector memory client for skwhisper.

Sovereign replacement for the Qdrant (skvector) client: reads/writes the shared
`memories` table in skmem-pg (.158:5432), embeds via the bge-legal-v2 server
(.100:11435), and searches via the hybrid (vector + BM25 RRF) SQL function
`hybrid_search_memories()`. Decoupled — no skmemory import; raw SQL + httpx.

Drop-in shape-compatible with the old QdrantClient:
  - await embed(text) -> list[float]            (bge-legal-v2, 1024-dim)
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

log = logging.getLogger("skwhisper.pgmem")

PG_DSN = os.environ.get(
    "SKMEMORY_PG_DSN", "postgresql://postgres:skmemory@localhost:5432/skmemory"
)
EMBED_URL = os.environ.get(
    "SKMEMORY_EMBED_URL", "http://192.168.0.100:11435/api/embed"
)
EMBED_MODEL = os.environ.get("SKMEMORY_EMBED_MODEL", "bge-legal-v2")


class PGMemClient:
    """Hybrid (vector+BM25) memory over local Postgres; bge-legal-v2 embeddings."""

    def __init__(self, dsn: str = PG_DSN, embed_url: str = EMBED_URL,
                 embed_model: str = EMBED_MODEL, agent: str | None = None):
        self.dsn = dsn
        self.embed_url = embed_url
        self.embed_model = embed_model
        self.agent = agent
        self._http: httpx.AsyncClient | None = None

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
                cur.execute(sql, (bm_q, self._vec_literal(q_vec), k, self.agent))
                for _id, layer, title, content, score in cur.fetchall():
                    out.append({
                        "id": _id,
                        "payload": {
                            "title": title or "untitled",
                            "content": content or "",
                            "tags": [],
                            "tier": layer,
                        },
                        "score": float(score) if score is not None else 0.0,
                    })
        return out

    async def search(self, q_text: str, q_vec: list[float],
                     top_k: int = 10, score_threshold: float = 0.0) -> list[dict]:
        return await asyncio.to_thread(self._search_sync, q_text, q_vec, top_k)

    # --- upsert (daemon digest) ------------------------------------------
    def _upsert_sync(self, vector: list[float], payload: dict, point_id: str | None) -> bool:
        pid = point_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc)
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
                    json.dumps(payload),
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
            log.error("pgmem upsert failed: %s", e)
            return False

    async def close(self):
        if self._http is not None:
            await self._http.aclose()
            self._http = None

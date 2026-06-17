"""ChromaDB vector client for skwhisper.

Local, embedded vector store (skmemory's Level-1 backend). Conforms to the shared
vector-client interface (embed/search/upsert/close) so it's interchangeable with
PGMemClient and QdrantClient via clients/factory.py.

chromadb is imported lazily (only when this backend is selected) so it isn't a
hard dependency for the default pgvector path.
"""
import asyncio
import logging
import os
import uuid
from pathlib import Path

import httpx

log = logging.getLogger("skwhisper.chroma")

_EMBED_URL = os.environ.get("SKMEMORY_EMBED_URL", "http://192.168.0.100:11434/api/embed")
_EMBED_MODEL = os.environ.get("SKMEMORY_EMBED_MODEL", "mxbai-embed-large")


class ChromaClient:
    def __init__(self, memory_dir, agent: str | None = None, collection: str | None = None):
        self.path = str(Path(memory_dir) / "chroma")
        self.collection_name = collection or f"{agent or 'lumina'}-memory"
        self._coll = None  # lazy

    def _collection(self):
        if self._coll is None:
            import chromadb  # lazy
            client = chromadb.PersistentClient(path=self.path)
            self._coll = client.get_or_create_collection(
                name=self.collection_name, metadata={"hnsw:space": "cosine"}
            )
        return self._coll

    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=30.0) as c:
            resp = await c.post(_EMBED_URL, json={"model": _EMBED_MODEL, "input": text})
            resp.raise_for_status()
            data = resp.json()
            embs = data.get("embeddings")
            if embs:
                return embs[0]
            if data.get("embedding"):
                return data["embedding"]
            if data.get("data"):
                return data["data"][0]["embedding"]
            raise ValueError(f"no embedding in response: {list(data.keys())}")

    @staticmethod
    def _meta(payload: dict) -> dict:
        """Chroma metadata must be scalar — flatten lists, drop None."""
        out = {}
        for k, v in payload.items():
            if v is None:
                continue
            if isinstance(v, (list, tuple)):
                out[k] = ", ".join(str(x) for x in v)
            elif isinstance(v, (str, int, float, bool)):
                out[k] = v
            else:
                out[k] = str(v)
        return out

    def _upsert_sync(self, vector, payload, point_id):
        coll = self._collection()
        coll.upsert(
            ids=[point_id or str(uuid.uuid4())],
            embeddings=[vector],
            documents=[payload.get("content", "")],
            metadatas=[self._meta(payload)],
        )
        return True

    async def upsert(self, vector, payload, point_id=None) -> bool:
        try:
            return await asyncio.to_thread(self._upsert_sync, vector, payload, point_id)
        except Exception as e:
            log.error("chroma upsert failed: %s", e)
            return False

    def _search_sync(self, q_vec, top_k):
        coll = self._collection()
        res = coll.query(query_embeddings=[q_vec], n_results=top_k,
                         include=["metadatas", "documents", "distances"])
        out = []
        ids = (res.get("ids") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for i, _id in enumerate(ids):
            meta = metas[i] or {}
            tags = meta.get("tags", "")
            out.append({
                "id": _id,
                "payload": {
                    "title": meta.get("title", "untitled"),
                    "content": docs[i] if i < len(docs) else meta.get("content", ""),
                    "tags": tags.split(", ") if isinstance(tags, str) and tags else [],
                    "tier": meta.get("tier", ""),
                },
                "score": 1.0 - float(dists[i]) if i < len(dists) else 0.0,  # cosine dist -> sim
            })
        return out

    async def search(self, q_text: str, q_vec: list[float], top_k: int = 10,
                     score_threshold: float = 0.0) -> list[dict]:
        return await asyncio.to_thread(self._search_sync, q_vec, top_k)

    async def close(self):
        pass

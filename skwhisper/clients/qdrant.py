"""Qdrant vector DB client using httpx (no qdrant_client dependency)."""

import httpx
import uuid
import logging
from datetime import datetime, timezone

log = logging.getLogger("skwhisper.qdrant")


class QdrantClient:
    """Thin async Qdrant HTTP client."""

    def __init__(self, url: str, api_key: str, collection: str):
        self.url = url.rstrip("/")
        self.collection = collection
        self.headers = {
            "api-key": api_key,
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                verify=False,  # Self-signed cert on internal infra
                headers=self.headers,
            )
        return self._client

    async def upsert(
        self,
        vector: list[float],
        payload: dict,
        point_id: str | None = None,
    ) -> bool:
        """Upsert a single point."""
        if not self.url:
            log.debug("Qdrant not configured, skipping upsert")
            return True
        client = await self._get_client()
        pid = point_id or str(uuid.uuid5(uuid.NAMESPACE_URL, payload.get("content", str(uuid.uuid4()))))

        body = {
            "points": [
                {
                    "id": pid,
                    "vector": vector,
                    "payload": payload,
                }
            ]
        }

        resp = await client.put(
            f"{self.url}/collections/{self.collection}/points",
            json=body,
        )
        if resp.status_code in (200, 202):
            log.info("Upserted point %s", pid)
            return True
        log.error("Qdrant upsert failed (%d): %s", resp.status_code, resp.text[:300])
        return False

    async def search(
        self,
        vector: list[float],
        top_k: int = 10,
        score_threshold: float = 0.5,
    ) -> list[dict]:
        """Search for similar vectors."""
        if not self.url:
            log.debug("Qdrant not configured, skipping search")
            return []
        client = await self._get_client()
        body = {
            "vector": vector,
            "limit": top_k,
            "score_threshold": score_threshold,
            "with_payload": True,
        }

        resp = await client.post(
            f"{self.url}/collections/{self.collection}/points/search",
            json=body,
        )
        resp.raise_for_status()
        results = resp.json().get("result", [])
        return [
            {
                "id": r["id"],
                "score": r["score"],
                "payload": r.get("payload", {}),
            }
            for r in results
        ]

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

"""Ollama API client for embeddings and summarization."""

import httpx
import json
import logging

log = logging.getLogger("skwhisper.ollama")


class OllamaClient:
    """Thin async client for Ollama API."""

    def __init__(self, base_url: str, embed_model: str, summarize_model: str):
        self.base_url = base_url.rstrip("/")
        self.embed_model = embed_model
        self.summarize_model = summarize_model
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=300.0)
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Generate embedding vector for text."""
        client = await self._get_client()
        resp = await client.post(
            f"{self.base_url}/api/embed",
            json={"model": self.embed_model, "input": text},
        )
        resp.raise_for_status()
        data = resp.json()
        # Ollama returns {"embeddings": [[...]]} for /api/embed
        embeddings = data.get("embeddings", [])
        if embeddings and len(embeddings) > 0:
            return embeddings[0]
        raise ValueError(f"No embedding returned: {data}")

    async def summarize(self, messages: str, system_prompt: str | None = None) -> str:
        """Summarize conversation text using the summarize model."""
        client = await self._get_client()
        prompt = system_prompt or (
            "You are a memory digest agent. Summarize this conversation concisely in 2-3 paragraphs. Extract:\n"
            "- Key topics discussed\n"
            "- Decisions made\n"
            "- Action items or next steps\n"
            "- Emotional moments or notable interactions\n"
            "- People and projects mentioned\n\n"
            "Be factual and specific. Include names, dates, and concrete details. "
            "Do NOT add commentary — just the digest."
        )

        resp = await client.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.summarize_model,
                "system": prompt,
                "prompt": messages,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 800},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("response", "").strip()
        # Fallback: thinking models put output in "thinking" field, response may be empty
        if not text:
            text = data.get("thinking", "").strip()
        return text

    async def extract_topics(self, summary: str) -> dict:
        """Extract structured topics, entities, and questions from a summary."""
        client = await self._get_client()
        prompt = (
            "Given this conversation summary, extract structured data as JSON:\n\n"
            f"{summary}\n\n"
            "Return ONLY valid JSON with this schema:\n"
            '{"topics": ["topic1", "topic2"], "people": ["name1"], '
            '"projects": ["project1"], "questions": ["question1"], '
            '"decisions": ["decision1"], "mood": "neutral|positive|negative|mixed"}\n'
            "Be concise. Use lowercase for topics. Return ONLY the JSON."
        )

        resp = await client.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.summarize_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 500},
            },
        )
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()

        # Parse JSON from response (handle markdown code blocks)
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning("Failed to parse topics JSON: %s", text[:200])
            return {"topics": [], "people": [], "projects": [], "questions": [], "decisions": [], "mood": "unknown"}

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

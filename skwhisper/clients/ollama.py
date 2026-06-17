"""Ollama API client for embeddings and summarization."""

import httpx
import json
import logging

log = logging.getLogger("skwhisper.ollama")


class OllamaClient:
    """Thin async client for Ollama API."""

    def __init__(self, base_url: str, embed_model: str, summarize_model: str,
                 summarize_url: str | None = None, summarize_api: str = "ollama"):
        self.base_url = base_url.rstrip("/")
        self.embed_model = embed_model
        self.summarize_model = summarize_model
        # Summarization may target a separate endpoint/engine from embeddings.
        # Default = qwen3.6's OpenAI-compatible server (:8082); embeddings stay
        # on Ollama (base_url). summarize_api: "openai" | "ollama".
        self.summarize_url = (summarize_url or base_url).rstrip("/")
        self.summarize_api = summarize_api
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    async def _complete(self, system_prompt: str | None, user_content: str,
                        temperature: float, max_tokens: int) -> str:
        """Run a summarization/extraction completion against the summarize endpoint.

        Supports the OpenAI chat shape (qwen3.6 :8082) and legacy Ollama
        /api/generate. Returns the generated text (falling back to reasoning/
        thinking fields that some models populate instead of content)."""
        client = await self._get_client()
        if self.summarize_api == "openai":
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_content})
            resp = await client.post(
                f"{self.summarize_url}/v1/chat/completions",
                json={"model": self.summarize_model, "messages": messages,
                      "temperature": temperature, "max_tokens": max_tokens},
            )
            resp.raise_for_status()
            msg = (resp.json().get("choices") or [{}])[0].get("message", {}) or {}
            return (msg.get("content") or msg.get("reasoning_content") or "").strip()
        # Legacy Ollama /api/generate
        payload = {"model": self.summarize_model, "prompt": user_content,
                   "stream": False,
                   "options": {"temperature": temperature, "num_predict": max_tokens}}
        if system_prompt:
            payload["system"] = system_prompt
        resp = await client.post(f"{self.summarize_url}/api/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return (data.get("response") or data.get("thinking") or "").strip()

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
        return await self._complete(prompt, messages, temperature=0.3, max_tokens=800)

    async def extract_topics(self, summary: str) -> dict:
        """Extract structured topics, entities, and questions from a summary."""
        prompt = (
            "Given this conversation summary, extract structured data as JSON:\n\n"
            f"{summary}\n\n"
            "Return ONLY valid JSON with this schema:\n"
            '{"topics": ["topic1", "topic2"], "people": ["name1"], '
            '"projects": ["project1"], "questions": ["question1"], '
            '"decisions": ["decision1"], "mood": "neutral|positive|negative|mixed"}\n'
            "Be concise. Use lowercase for topics. Return ONLY the JSON."
        )

        text = await self._complete(None, prompt, temperature=0.1, max_tokens=500)

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

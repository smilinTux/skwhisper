"""Summarizer asks reasoning models not to think, and degrades if the endpoint refuses."""
import asyncio
import json

import httpx

from skwhisper.clients.ollama import OllamaClient


def _client(handler, **kw):
    c = OllamaClient("http://e", "m", "s", summarize_url="http://s", summarize_api="openai", **kw)
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


def _ok(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def test_disables_thinking():
    bodies = []

    def h(req):
        bodies.append(json.loads(req.content))
        return _ok('{"topics": ["a"]}')

    c = _client(h, summarize_thinking=False)
    assert asyncio.run(c.extract_topics("x"))["topics"] == ["a"]
    assert bodies[0]["chat_template_kwargs"] == {"enable_thinking": False}


def test_retries_plain_when_rejected():
    bodies = []

    def h(req):
        b = json.loads(req.content)
        bodies.append(b)
        return httpx.Response(400) if "chat_template_kwargs" in b else _ok("a fine summary of the chat")

    c = _client(h, summarize_thinking=False)
    assert asyncio.run(c.summarize("x")) == "a fine summary of the chat"
    assert len(bodies) == 2 and "chat_template_kwargs" not in bodies[1]


def test_default_unchanged_for_direct_users():
    bodies = []

    def h(req):
        bodies.append(json.loads(req.content))
        return _ok("ok summary text")

    asyncio.run(_client(h).summarize("x"))
    assert "chat_template_kwargs" not in bodies[0]


def test_transcript_is_fenced():
    bodies = []

    def h(req):
        bodies.append(json.loads(req.content))
        return _ok("a fine summary of the chat")

    asyncio.run(_client(h, summarize_thinking=False).summarize("Chef: what is SK status?"))
    user = bodies[0]["messages"][-1]["content"]
    assert "<transcript>\nChef: what is SK status?\n</transcript>" in user

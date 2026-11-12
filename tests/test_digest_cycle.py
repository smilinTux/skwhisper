"""run_digest_cycle: newest first, capped per cycle."""
import asyncio
import os
import time

import skwhisper.daemon as daemon


class _Closer:
    async def close(self):
        pass


def test_cycle_newest_first_and_capped(tmp_path, monkeypatch):
    sessions = []
    for i in range(5):
        p = tmp_path / f"s{i}.jsonl"
        p.write_text("{}\n")
        t = time.time() - 10000 + i * 100  # s4 newest
        os.utime(p, (t, t))
        sessions.append({"path": p, "session_id": f"s{i}", "messages": [], "new_offset": 3, "is_idle": True})

    seen = []

    async def fake_digest(config, session, *a, **k):
        seen.append(session["session_id"])
        return True

    async def no_sleep(_):
        pass

    monkeypatch.setattr(daemon, "scan_sessions", lambda c: list(sessions))
    monkeypatch.setattr(daemon, "digest_session", fake_digest)
    monkeypatch.setattr(daemon, "OllamaClient", lambda *a, **k: _Closer())
    monkeypatch.setattr(daemon, "make_vector_client", lambda c: _Closer())
    monkeypatch.setattr(daemon, "make_graph_writer", lambda c: None)
    monkeypatch.setattr(daemon, "SKMemoryWriter", lambda d: None)
    monkeypatch.setattr(daemon.asyncio, "sleep", no_sleep)

    class Cfg:
        ollama_url = embed_model = summarize_model = summarize_url = summarize_api = memory_dir = "x"
        max_digest_per_cycle = 3
        summarize_thinking = False

    assert asyncio.run(daemon.run_digest_cycle(Cfg())) == 3
    assert seen == ["s4", "s3", "s2"]


def test_digest_session_records_usage_on_state_entry(tmp_path):
    """A fake completion with a usage block lands as counts on the session entry in state.json."""
    import json
    import httpx
    from types import SimpleNamespace
    from skwhisper.clients.ollama import OllamaClient
    from skwhisper.watcher import mark_digested

    def h(req):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
        })

    ollama = OllamaClient("http://e", "m", "s", summarize_url="http://s", summarize_api="openai")
    ollama._client = httpx.AsyncClient(transport=httpx.MockTransport(h))
    asyncio.run(ollama.extract_topics("x"))
    (tmp_path / "st").mkdir()
    cfg = SimpleNamespace(state_dir=tmp_path / "st")
    mark_digested(cfg, "sess1", 5, usage=ollama.take_usage())
    entry = json.loads((tmp_path / "st" / "state.json").read_text())["sessions"]["sess1"]
    assert entry["usage"] == {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16}


class _UsageOllama:
    """Fake client with per-client usage, like OllamaClient: calls add, take_usage drains."""

    def __init__(self, summaries):
        self.summaries = list(summaries)
        self._tokens = 0

    async def summarize(self, text):
        self._tokens += 100
        return self.summaries.pop(0)

    async def extract_topics(self, s):
        self._tokens += 2
        return {}

    def take_usage(self):
        t, self._tokens = self._tokens, 0
        return {"total_tokens": t}


class _UsageCfg:
    user_label = "User"
    agent_label = "Agent"
    skip_cron = False
    min_transcript_chars = 1
    state_dir = None


def _usage_session(sid):
    return {"session_id": sid, "messages": [{"role": "user", "text": "hello there"}], "new_offset": 5}


def _run_two(monkeypatch, summaries, memory_a_fails=False):
    marked = {}

    async def no_vec(*a, **k):
        return True

    class Mem:
        calls = 0

        def write_snapshot(self, **k):
            Mem.calls += 1
            if memory_a_fails and Mem.calls == 1:
                raise RuntimeError("boom")
            return "id"

    monkeypatch.setattr(daemon, "classify_session", lambda m, p: "human")
    monkeypatch.setattr(daemon, "_vector_write", no_vec)
    monkeypatch.setattr(daemon, "update_patterns", lambda *a, **k: None)
    monkeypatch.setattr(
        daemon, "mark_digested",
        lambda c, sid, off, session_type="human", usage=None: marked.__setitem__(sid, usage),
    )
    ollama = _UsageOllama(summaries)
    good = "A real summary that is comfortably longer than twenty chars."

    async def go():
        a = await daemon.digest_session(_UsageCfg(), _usage_session("A"), ollama, None, Mem())
        b = await daemon.digest_session(_UsageCfg(), _usage_session("B"), ollama, None, Mem())
        return a, b

    return asyncio.run(go()), marked


def test_usage_does_not_leak_after_short_summary(monkeypatch):
    good = "A real summary that is comfortably longer than twenty chars."
    (a, b), marked = _run_two(monkeypatch, ["x", good])
    assert a is False and b is True
    assert marked["B"] == {"total_tokens": 102}


def test_usage_does_not_leak_after_write_failure(monkeypatch):
    good = "A real summary that is comfortably longer than twenty chars."
    (a, b), marked = _run_two(monkeypatch, [good, good], memory_a_fails=True)
    assert a is False and b is True
    assert marked["B"] == {"total_tokens": 102}

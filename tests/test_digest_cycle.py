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

    assert asyncio.run(daemon.run_digest_cycle(Cfg())) == 3
    assert seen == ["s4", "s3", "s2"]

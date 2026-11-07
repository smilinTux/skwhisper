"""whisper.md keeps the Relevant Memories header and names the cause when the source is down."""

import asyncio
import sqlite3
from types import SimpleNamespace

import httpx
import psycopg
import pytest

import skwhisper.curator as curator

SECRET_DSN = "postgresql://wuser:hunter2pw@127.0.0.1:1/db"  # invented, never reachable


class _Down:
    def __init__(self, exc, embed_fails=False):
        self.exc, self.embed_fails = exc, embed_fails

    async def embed(self, text):
        if self.embed_fails:
            raise self.exc
        return [0.0]

    async def search(self, *a, **k):
        raise self.exc

    async def close(self):
        pass


class _Ok(_Down):
    async def search(self, *a, **k):
        return [
            {
                "payload": {"title": "Invented note", "content": "c", "tags": ["ops"]},
                "score": 0.9,
            }
        ]


def _index(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE memories (id TEXT, tags TEXT, source_ref TEXT)")
    c.commit()
    c.close()


def _cfg(tmp_path):
    for d in ("state", "mem"):
        (tmp_path / d).mkdir()
    _index(tmp_path / "mem" / "index.db")
    return SimpleNamespace(
        state_dir=tmp_path / "state", memory_dir=tmp_path / "mem", recent_k=3, top_k=3
    )


def _curate(cfg, client, monkeypatch):
    monkeypatch.setattr(curator, "make_vector_client", lambda c: client)
    monkeypatch.setattr(curator, "_get_recent_context", lambda c: "some recent talk")
    return asyncio.run(curator.curate_context(cfg))


def _http_status_error():
    req = httpx.Request("POST", "http://127.0.0.1:1/api/embed")
    return httpx.HTTPStatusError(
        "500", request=req, response=httpx.Response(500, request=req)
    )


LIBPQ_BAD_PASSWORD = (
    'connection failed: connection to server at "127.0.0.1", port 5432 failed: '
    'FATAL:  password authentication failed for user "wuser"'
)
LIBPQ_NO_ROLE = (
    'connection failed: connection to server at "127.0.0.1", port 5432 failed: '
    'FATAL:  role "wuser" does not exist'
)

# (exception, fails in the embed phase, expected cause). Types, not message keywords.
CASES = [
    # real psycopg 3.3 login rejections are plain OperationalError with sqlstate None
    (psycopg.OperationalError(LIBPQ_BAD_PASSWORD), False, "postgres auth failed"),
    (psycopg.OperationalError(LIBPQ_NO_ROLE), False, "postgres auth failed"),
    (
        psycopg.errors.InvalidPassword(f"FATAL: auth failed ({SECRET_DSN})"),
        False,
        "postgres auth failed",
    ),
    (
        psycopg.OperationalError(f"connection refused {SECRET_DSN}"),
        False,
        "postgres unreachable",
    ),
    (
        psycopg.OperationalError(
            "could not translate host name to address: Name or service not known"
        ),
        False,
        "postgres unreachable",
    ),  # DNS failure
    (
        psycopg.errors.UndefinedFunction(
            "function hybrid_search_memories does not exist"
        ),
        False,
        "postgres query failed",
    ),
    (
        RuntimeError("bad config password=abc, auth token rejected"),
        False,
        "search failed",
    ),
    (
        httpx.ConnectError("all connection attempts failed"),
        True,
        "embedding service unreachable",
    ),
    (httpx.ReadTimeout("timed out"), True, "embedding service timed out"),
    (_http_status_error(), True, "embedding service returned an error"),
    (ValueError("no embedding in response"), True, "embedding service failed"),
]


@pytest.mark.parametrize(
    "exc,embed_phase,cause", CASES, ids=[c[2] + str(i) for i, c in enumerate(CASES)]
)
def test_failed_source_keeps_header_with_cause_and_no_dsn(
    tmp_path, monkeypatch, caplog, exc, embed_phase, cause
):
    cfg = _cfg(tmp_path)
    with caplog.at_level("WARNING"):
        out = _curate(cfg, _Down(exc, embed_fails=embed_phase), monkeypatch)
    assert "## Relevant Memories" in out
    assert f"source unavailable: {cause}" in out
    for leak in ("hunter2pw", "wuser", "127.0.0.1", SECRET_DSN):
        assert leak not in out
        assert leak not in "\n".join(r.getMessage() for r in caplog.records)
    assert any("source unavailable" in r.message for r in caplog.records)
    assert (cfg.state_dir / "whisper.md").read_text() == out


def test_healthy_source_has_no_unavailable_line(tmp_path, monkeypatch):
    out = _curate(_cfg(tmp_path), _Ok(None), monkeypatch)
    assert "Invented note" in out and "source unavailable" not in out


def test_no_context_is_not_reported_as_down(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(curator, "make_vector_client", lambda c: _Ok(None))
    monkeypatch.setattr(curator, "_get_recent_context", lambda c: "")
    assert "source unavailable" not in asyncio.run(curator.curate_context(cfg))

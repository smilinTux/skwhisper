"""Canonical DSN resolution, dead-backend removal, and the degraded banner."""

import asyncio

import pytest

from skwhisper import health, pgdsn
from skwhisper.clients import factory
from skwhisper.config import Config

CANON = "postgresql://u:canonpw@127.0.0.1:5432/skmemory"
STALE = "postgresql://u:stalepw@127.0.0.1:5432/skmemory"


def _conf(tmp_path, dsn=CANON):
    p = tmp_path / "skmemory.conf"
    p.write_text(f"# c\nSKMEMORY_VECTOR_BACKEND=pgvector\nSKMEMORY_PG_DSN={dsn}\n")
    return p


def test_env_wins_over_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SKMEMORY_PG_DSN", CANON)
    assert pgdsn.resolve_dsn(conf_path=_conf(tmp_path, STALE)) == CANON


def test_file_used_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("SKMEMORY_PG_DSN", raising=False)
    assert pgdsn.resolve_dsn(conf_path=_conf(tmp_path)) == CANON


def test_no_source_raises_no_hardcoded_password(tmp_path, monkeypatch):
    monkeypatch.delenv("SKMEMORY_PG_DSN", raising=False)
    with pytest.raises(pgdsn.DSNUnavailable):
        pgdsn.resolve_dsn(conf_path=tmp_path / "absent.conf")


def test_per_agent_toml_pg_dsn_cannot_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SKMEMORY_PG_DSN", CANON)
    monkeypatch.setenv("HOME", str(tmp_path))
    toml = tmp_path / "skwhisper.toml"
    toml.write_text(f'[db]\npg_dsn = "{STALE}"\n')
    assert Config(toml).pg_dsn == CANON


def test_dead_backends_removed(tmp_path):
    import importlib.util

    assert importlib.util.find_spec("skwhisper.clients.chroma") is None
    assert importlib.util.find_spec("skwhisper.clients.qdrant") is None

    class C:
        memory_dir = tmp_path
        agent_name = "x"

    for backend in ("chromadb", "chroma", "qdrant"):
        C.vector_backend = backend
        with pytest.raises(ValueError, match="retired"):
            factory.make_vector_client(C)


def test_banner_roundtrip(tmp_path):
    assert health.banner(tmp_path) == ""
    health.record(tmp_path, "graph", False, "connection failed")
    b = health.banner(tmp_path)
    assert "GRAPH DEGRADED" in b and "connection failed" in b
    health.record(tmp_path, "vector_write", False, "no pg")
    assert "VECTOR DEGRADED" in health.banner(tmp_path)
    health.record(tmp_path, "graph", True)
    health.record(tmp_path, "vector_write", True)
    assert health.banner(tmp_path) == ""


def test_banner_never_contains_dsn_password(tmp_path):
    health.record(tmp_path, "graph", False, f"failed for {CANON}")
    assert "canonpw" not in health.banner(tmp_path)


def test_unavailable_graph_records_degraded(tmp_path, monkeypatch):
    monkeypatch.setenv("SKMEMORY_PG_DSN", CANON)
    import skwhisper.clients.agegraph as age

    def boom(*a, **k):
        raise RuntimeError("connection failed")

    monkeypatch.setattr(age.psycopg, "connect", boom)

    class C:
        state_dir = tmp_path
        pg_dsn = CANON
        falkordb_graph = "t_knowledge"
        graph_backend = "age"

    assert factory.make_graph_writer(C) is None
    assert "GRAPH DEGRADED" in health.banner(tmp_path)


def test_failed_graph_write_records_degraded(tmp_path):
    import skwhisper.daemon as daemon

    class BadGraph:
        def write_memory(self, **k):
            raise RuntimeError("age write failed")

    class Cfg:
        state_dir = tmp_path

    daemon._graph_write(
        Cfg,
        BadGraph(),
        session_id="s",
        title="t",
        summary="x",
        topics=[],
        people=[],
        projects=[],
        created_at="now",
    )
    assert "GRAPH DEGRADED" in health.banner(tmp_path)


def test_failed_vector_upsert_records_degraded(tmp_path):
    import skwhisper.daemon as daemon

    class Vec:
        async def embed(self, t):
            return [0.0]

        async def upsert(self, **k):
            return False

    class Cfg:
        state_dir = tmp_path

    asyncio.run(daemon._vector_write(Cfg, Vec(), "summary", {"title": "t"}, "id"))
    assert "VECTOR DEGRADED" in health.banner(tmp_path)


def test_whisper_carries_banner_when_semantic_feed_fails(tmp_path, monkeypatch):
    import skwhisper.curator as cur

    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = Config(tmp_path / "none.toml")
    cfg._data.update(
        state_dir=tmp_path / "st",
        memory_dir=tmp_path / "mem",
        sessions_dir=tmp_path / "sess",
    )
    for d in ("st", "mem", "sess"):
        (tmp_path / d).mkdir()
    (tmp_path / "sess" / "a.jsonl").write_text(
        '{"message": {"role": "user", "content": "hello there"}}\n'
    )

    class Dead:
        async def embed(self, t):
            raise RuntimeError("pg missing")

        async def close(self):
            pass

    monkeypatch.setattr(cur, "make_vector_client", lambda c: Dead())
    monkeypatch.setattr(cur, "_get_recent_context", lambda c: "User: hi")
    out = asyncio.run(cur.curate_context(cfg))
    assert out.index("VECTOR DEGRADED") < out.index("> Auto-generated")
    assert "VECTOR DEGRADED" in (tmp_path / "st" / "whisper.md").read_text()


def test_banner_has_no_error_text_or_secrets(tmp_path):
    health.record(tmp_path, "graph", False, "password=hunter2 host=x\nINJECT")
    assert "hunter2" not in health.banner(tmp_path)
    assert "hunter2" not in (tmp_path / "health.json").read_text()
    assert "\n" not in health.banner(tmp_path).strip().replace("\n>", "")


def test_redact_keyvalue():
    assert "hunter2" not in pgdsn.redact("host=a password='hunter2' user=b")


def test_read_success_does_not_clear_write_failure(tmp_path):
    health.record(tmp_path, "vector_write", False, "x")
    health.record(tmp_path, "vector_read", True)
    assert "VECTOR DEGRADED" in health.banner(tmp_path)


def test_ignored_toml_dsn_warns_once(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("SKMEMORY_PG_DSN", CANON)
    monkeypatch.setenv("HOME", str(tmp_path))
    Config._warned_dsn = False
    toml = tmp_path / "skwhisper.toml"
    toml.write_text(f'[db]\npg_dsn = "{STALE}"\n')
    Config(toml)
    Config(toml)
    assert sum("pg_dsn in the skwhisper TOML" in r.message for r in caplog.records) == 1

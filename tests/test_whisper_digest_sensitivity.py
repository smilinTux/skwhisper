"""Digest-derived whisper.md sections (hot topics, questions, people) honor sensitivity."""

import asyncio
import sqlite3

import pytest
from types import SimpleNamespace

import skwhisper.curator as curator
from skwhisper.patterns import update_patterns

SACRED = "Quillan Marrowby"  # invented


class _Vec:
    async def close(self):
        pass


def _index(path, rows):
    c = sqlite3.connect(path)
    c.executescript(
        """CREATE TABLE memories (id TEXT PRIMARY KEY, title TEXT, summary TEXT, content_preview TEXT,
        tags TEXT, layer TEXT, created_at TEXT, source_ref TEXT);
        CREATE VIEW active_memories AS SELECT id,title,summary,content_preview,tags,layer,created_at,
        'today' AS context_tier FROM memories;"""
    )
    for i, (tags, ref) in enumerate(rows):
        c.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?)",
            (f"m{i}", f"t{i}", "", "", tags, "mid-term", "2026-11-01T12:00:00", ref),
        )
    c.commit()
    c.close()


def _run(tmp_path, monkeypatch):
    state, mem = tmp_path / "state", tmp_path / "mem"
    state.mkdir(exist_ok=True)
    mem.mkdir(exist_ok=True)
    cfg = SimpleNamespace(
        state_dir=state,
        memory_dir=mem,
        recent_k=3,
        top_k=3,
        user_label="U",
        agent_label="A",
        sessions_dir=tmp_path / "none",
    )
    return cfg


def _curate(cfg, monkeypatch):
    monkeypatch.setattr(curator, "make_vector_client", lambda c: _Vec())
    monkeypatch.setattr(curator, "_get_recent_context", lambda c: "")
    return asyncio.run(curator.curate_context(cfg))


def test_sensitive_digest_tags_keep_sacred_name_out_of_whisper(tmp_path, monkeypatch):
    cfg = _run(tmp_path, monkeypatch)
    _index(cfg.memory_dir / "index.db", [("sacred,quillan-marrowby", "")])
    sacred_tags = ["skwhisper", "auto-digest", "human", "sacred", "quillan-marrowby"]
    for sid in ("s1", "s2"):  # the sacred name mentioned in two sessions
        update_patterns(
            cfg.state_dir,
            sid,
            {
                "topics": ["vigil planning"],
                "questions": [f"Where is {SACRED}?"],
                "people": [SACRED],
            },
            digest_tags=sacred_tags,
        )
    # an ordinary digest mentions the same name later
    update_patterns(
        cfg.state_dir,
        "s3",
        {
            "topics": ["deploys", "deploys"],
            "questions": [f"How is {SACRED}?"] * 2,
            "people": [SACRED, "Dana Ortel"],
        },
        digest_tags=["skwhisper", "auto-digest", "human", "deploys"],
    )
    update_patterns(
        cfg.state_dir,
        "s4",
        {"topics": ["deploys"], "questions": [], "people": ["Dana Ortel"]},
        digest_tags=["skwhisper", "auto-digest", "human"],
    )
    out = _curate(cfg, monkeypatch)
    assert SACRED not in out and "marrowby" not in out.lower()
    assert "vigil planning" not in out
    assert "deploys" in out and "Dana Ortel" in out  # ordinary content survives


def test_digest_tagged_sensitive_after_the_fact_drops_its_topics(tmp_path, monkeypatch):
    cfg = _run(tmp_path, monkeypatch)
    for sid in ("sA", "sB"):
        update_patterns(
            cfg.state_dir,
            sid,
            {"topics": ["memorial garden", "deploys"], "people": ["Pell Hazan"]},
            digest_tags=["skwhisper", "auto-digest", "human"],
        )
    # skmemory later tags the sA digest grief; its source_ref names the session
    _index(
        cfg.memory_dir / "index.db",
        [("auto-digest,grief,pell-hazan", "session:sA@0-90")],
    )
    out = _curate(cfg, monkeypatch)
    assert (
        "memorial garden" not in out and "deploys" not in out
    )  # both topics came from sA
    assert "Pell Hazan" not in out


def test_person_on_a_sensitive_memory_is_dropped_but_others_stay(tmp_path, monkeypatch):
    cfg = _run(tmp_path, monkeypatch)
    update_patterns(
        cfg.state_dir,
        "s1",
        {"topics": ["ops"], "people": ["Ines Vask", "Lowe Raine"]},
        digest_tags=["skwhisper", "auto-digest"],
    )
    _index(cfg.memory_dir / "index.db", [("sacred,ines-vask", ""), ("ops", "")])
    out = _curate(cfg, monkeypatch)
    assert "Ines Vask" not in out and "Lowe Raine" in out and "ops" in out


def test_topic_or_question_with_a_sensitive_stem_is_dropped(tmp_path, monkeypatch):
    cfg = _run(tmp_path, monkeypatch)
    _index(cfg.memory_dir / "index.db", [("ops", "")])
    for sid in ("s1", "s2"):
        update_patterns(
            cfg.state_dir,
            sid,
            {
                "topics": ["grief support", "builds"],
                "questions": ["my medical results?"],
            },
            digest_tags=["skwhisper"],
        )
    out = _curate(cfg, monkeypatch)
    assert (
        "grief" not in out.lower() and "medical" not in out.lower() and "builds" in out
    )


def test_possessive_first_name_and_unlisted_variants_are_dropped(tmp_path, monkeypatch):
    cfg = _run(tmp_path, monkeypatch)
    _index(cfg.memory_dir / "index.db", [("sacred,quillan-marrowby", ""), ("ops", "")])
    for sid in ("s1", "s2"):  # ordinary digests, no people entry for the sacred name
        update_patterns(
            cfg.state_dir,
            sid,
            {
                "topics": [
                    "quillan's birthday",
                    "visiting quillan",
                    "quillan marrowby anniversary",
                    "annual planning",
                ],
                "questions": ["When is Quillans party?", "Is the annual review done?"],
                "people": ["Dana Ortel"],
            },
            digest_tags=["skwhisper", "auto-digest"],
        )
    out = _curate(cfg, monkeypatch).lower()
    assert "quillan" not in out and "marrowby" not in out
    assert "annual planning" in out and "annual review" in out and "dana ortel" in out


def test_short_name_does_not_drop_longer_words(tmp_path, monkeypatch):
    cfg = _run(tmp_path, monkeypatch)
    _index(cfg.memory_dir / "index.db", [("sacred,ann-vell", "")])
    update_patterns(
        cfg.state_dir,
        "s1",
        {"topics": ["annual planning", "ann visit"]},
        digest_tags=["x"],
    )
    update_patterns(
        cfg.state_dir,
        "s2",
        {"topics": ["annual planning", "ann visit"]},
        digest_tags=["x"],
    )
    out = _curate(cfg, monkeypatch)
    assert "annual planning" in out and "ann visit" not in out


def test_stored_patterns_are_purged(tmp_path, monkeypatch):
    from skwhisper.patterns import load_patterns

    cfg = _run(tmp_path, monkeypatch)
    _index(cfg.memory_dir / "index.db", [("sacred,quillan-marrowby", "")])
    update_patterns(
        cfg.state_dir,
        "s1",
        {
            "topics": ["quillan"],
            "questions": ["Where is Quillan?"],
            "people": ["Quillan Marrowby"],
            "projects": ["Quillan memorial"],
        },
        digest_tags=["x"],
    )
    _curate(cfg, monkeypatch)
    raw = str(load_patterns(cfg.state_dir)).lower()
    assert "quillan" not in raw


@pytest.mark.parametrize("breakage", ["missing", "corrupt", "no_table"])
def test_unreadable_index_fails_closed(tmp_path, monkeypatch, caplog, breakage):
    cfg = _run(tmp_path, monkeypatch)
    db = cfg.memory_dir / "index.db"
    if breakage == "corrupt":
        db.write_bytes(b"not a sqlite file" * 100)
    elif breakage == "no_table":
        sqlite3.connect(db).close()
    for sid in ("s1", "s2"):
        update_patterns(
            cfg.state_dir,
            sid,
            {
                "topics": ["quillan memorial"],
                "questions": ["Where is Quillan?"],
                "people": ["Quillan Marrowby"],
            },
            digest_tags=["x"],
        )
    with caplog.at_level("WARNING"):
        out = _curate(cfg, monkeypatch)
    assert "quillan" not in out.lower()
    for h in (
        "Hot Topics (recurring)",
        "Repeated Questions",
        "Frequently Mentioned People",
    ):
        assert f"## {h}" in out
    assert out.count("source unavailable") == 3
    assert any(
        "unreadable" in r.message or "unknown" in r.message for r in caplog.records
    )

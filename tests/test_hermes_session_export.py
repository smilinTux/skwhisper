import importlib.util
import sqlite3
from pathlib import Path

from skwhisper.watcher import extract_messages

_SPEC = importlib.util.spec_from_file_location(
    "hse", Path(__file__).resolve().parents[1] / "scripts" / "hermes-session-export.py")
hse = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hse)


def _db(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE sessions (id TEXT, source TEXT, title TEXT, started_at REAL)")
    c.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL)")
    return c


def test_export_roundtrips_through_watcher_and_appends(tmp_path):
    import time
    db = tmp_path / "state.db"
    c = _db(db)
    now = time.time()
    c.execute("INSERT INTO sessions VALUES ('s1','nctalk','Chat',?)", (now,))
    c.execute("INSERT INTO sessions VALUES ('c1','cron','Job',?)", (now,))
    msgs = [("s1", "user", "hello jarvis, how is the cluster"), ("s1", "assistant", None),
            ("s1", "tool", "{\"ok\": true}"), ("s1", "assistant", "The cluster is healthy today."),
            ("c1", "user", "cron prompt that should be skipped")]
    c.executemany("INSERT INTO messages (session_id, role, content, timestamp) VALUES (?,?,?,0)", msgs)
    c.commit()

    out = tmp_path / "sessions"
    stats = hse.export(db, out, 1, {"cron"}, 2)
    assert stats["written"] == 1 and not (out / "c1.jsonl").exists()
    got, off1 = extract_messages(out / "s1.jsonl")
    assert [m["role"] for m in got] == ["user", "assistant"]

    c.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s1','user','and the gpu nodes?',0)")
    c.commit()
    assert hse.export(db, out, 1, {"cron"}, 2)["appended"] == 1
    new, _ = extract_messages(out / "s1.jsonl", off1)
    assert [m["role"] for m in new] == ["user"]
    assert hse.export(db, out, 1, {"cron"}, 2)["unchanged"] == 1


def _db2(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE sessions (id TEXT, source TEXT, title TEXT, started_at REAL)")
    c.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,"
              " timestamp REAL, display_kind TEXT)")
    return c


def test_export_filters_ui_rows_sets_mtime_and_is_private(tmp_path):
    import os
    import time
    db = tmp_path / "state.db"
    c = _db2(db)
    t0 = time.time() - 7200
    c.execute("INSERT INTO sessions VALUES ('s1','telegram','x',?)", (t0,))
    c.executemany("INSERT INTO messages (session_id, role, content, timestamp, display_kind) VALUES (?,?,?,?,?)", [
        ("s1", "user", "is the backup done yet?", t0, None),
        ("s1", "user", "[IMPORTANT: Background process finished]", t0 + 1, "internal_notification"),
        ("s1", "assistant", "This turn did not complete.", t0 + 2, "failed_turn"),
        ("s1", "assistant", "Yes, finished at 04:00.", t0 + 3, None),
    ])
    c.commit()
    out = tmp_path / "out"
    assert hse.export(db, out, 1, set(hse.DEFAULT_EXCLUDE_SOURCES), 2)["written"] == 1
    f = out / "s1.jsonl"
    got, _ = extract_messages(f)
    assert [m["text"] for m in got] == ["is the backup done yet?", "Yes, finished at 04:00."]
    assert abs(f.stat().st_mtime - (t0 + 3)) < 1  # mtime = last message, not export time
    assert (f.stat().st_mode & 0o777) == 0o600
    assert not list(out.glob("*.tmp"))
    # Retitling in Hermes must not rewrite the file (offsets stay valid).
    c.execute("UPDATE sessions SET title='Backup status'")
    c.commit()
    assert hse.export(db, out, 1, set(hse.DEFAULT_EXCLUDE_SOURCES), 2)["unchanged"] == 1
    assert os.path.getsize(f) > 0


def test_export_never_overwrites_foreign_transcript_and_skips_automation(tmp_path):
    import time
    db = tmp_path / "state.db"
    c = _db2(db)
    now = time.time()
    for sid, src in (("legacy", "telegram"), ("o1", "oneshot"), ("sub", "subagent")):
        c.execute("INSERT INTO sessions VALUES (?,?,NULL,?)", (sid, src, now))
        c.executemany("INSERT INTO messages (session_id, role, content, timestamp) VALUES (?,?,?,?)",
                      [(sid, "user", "a real looking question", now), (sid, "assistant", "a real looking answer", now)])
    c.commit()
    out = tmp_path / "out"
    out.mkdir()
    legacy = out / "legacy.jsonl"
    legacy.write_text('{"role": "session_meta", "platform": "telegram"}\n')  # Hermes-written original
    stats = hse.export(db, out, 1, set(hse.DEFAULT_EXCLUDE_SOURCES), 2)
    assert stats["foreign"] == 1 and stats["written"] == 0
    assert legacy.read_text() == '{"role": "session_meta", "platform": "telegram"}\n'
    assert not (out / "o1.jsonl").exists() and not (out / "sub.jsonl").exists()


def test_export_window_uses_last_message_not_start(tmp_path):
    import time
    db = tmp_path / "state.db"
    c = _db2(db)
    now = time.time()
    c.execute("INSERT INTO sessions VALUES ('old','telegram',NULL,?)", (now - 90 * 86400,))
    c.executemany("INSERT INTO messages (session_id, role, content, timestamp) VALUES (?,?,?,?)", [
        ("old", "user", "started long ago", now - 90 * 86400), ("old", "assistant", "still chatting today", now)])
    c.commit()
    assert hse.export(db, tmp_path / "out", 30, set(), 2)["written"] == 1

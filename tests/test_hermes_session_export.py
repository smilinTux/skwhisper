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

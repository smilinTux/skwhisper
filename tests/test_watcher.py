"""Basic tests for SKWhisper components."""

import json
import tempfile
import os
from pathlib import Path

def test_extract_messages():
    """Test message extraction from JSONL session files."""
    from skwhisper.watcher import extract_messages

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        # Write sample session data
        lines = [
            {"type": "session", "id": "test-session"},
            {"type": "message", "message": {"role": "user", "content": "Hello, how are you?"}, "timestamp": "2026-03-24T00:00:00Z"},
            {"type": "message", "message": {"role": "assistant", "content": "I'm doing great! How can I help?"}, "timestamp": "2026-03-24T00:00:01Z"},
            {"type": "message", "message": {"role": "toolResult", "content": "tool output"}, "timestamp": "2026-03-24T00:00:02Z"},
            {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "Content array message"}]}, "timestamp": "2026-03-24T00:00:03Z"},
        ]
        for line in lines:
            f.write(json.dumps(line) + "\n")
        fname = f.name

    try:
        messages, offset = extract_messages(Path(fname), 0)
        assert len(messages) == 3, f"Expected 3 messages, got {len(messages)}"
        assert messages[0]["role"] == "user"
        assert messages[0]["text"] == "Hello, how are you?"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["text"] == "Content array message"
        print("✓ extract_messages: OK")
        print(f"  Offset: {offset}")
    finally:
        os.unlink(fname)


def test_extract_messages_hermes_schema():
    """Hermes writes role+content+timestamp at the top level (no `type`, no `message` wrapper)."""
    from skwhisper.watcher import extract_messages

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        lines = [
            {"role": "session_meta", "tools": [], "model": "kimi", "platform": "hermes", "timestamp": "2026-04-25T00:00:00Z"},
            {"role": "user", "content": "Welcome back to Hermes!", "timestamp": "2026-04-25T00:00:01Z"},
            {"role": "assistant", "content": "Thanks Chef — Hermes feels lighter than OpenClaw.", "reasoning": "...", "timestamp": "2026-04-25T00:00:02Z"},
            {"role": "tool", "content": "irrelevant tool output", "timestamp": "2026-04-25T00:00:03Z"},
        ]
        for line in lines:
            f.write(json.dumps(line) + "\n")
        fname = f.name

    try:
        messages, _ = extract_messages(Path(fname), 0)
        assert len(messages) == 2, f"Expected 2 (user + assistant), got {len(messages)}"
        assert messages[0]["role"] == "user"
        assert messages[0]["text"] == "Welcome back to Hermes!"
        assert messages[1]["role"] == "assistant"
        assert "Hermes feels lighter" in messages[1]["text"]
    finally:
        os.unlink(fname)


def test_skmemory_writer():
    """Test writing skmemory snapshots."""
    from skwhisper.clients.skmemory import SKMemoryWriter

    with tempfile.TemporaryDirectory() as tmpdir:
        writer = SKMemoryWriter(tmpdir)
        mem_id = writer.write_snapshot(
            title="Test Memory",
            content="This is a test memory snapshot.",
            tags=["test", "skwhisper"],
            emotions=["curious"],
            intensity=5.0,
        )
        assert mem_id

        # Verify file exists and is valid JSON
        mem_file = Path(tmpdir) / "short-term" / f"{mem_id}.json"
        assert mem_file.exists(), f"Memory file not found: {mem_file}"

        data = json.loads(mem_file.read_text())
        assert data["title"] == "Test Memory"
        assert data["layer"] == "short-term"
        assert "test" in data["tags"]
        print("✓ skmemory_writer: OK")
        print(f"  Memory ID: {mem_id}")


def test_patterns():
    """Test pattern tracking."""
    from skwhisper.patterns import update_patterns, get_hot_topics, load_patterns

    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)

        # Update patterns with some data
        update_patterns(state_dir, "session-1", {
            "topics": ["skmemory", "python", "daemon"],
            "people": ["Chef", "Lumina"],
            "projects": ["SKWhisper", "SKStacks"],
            "questions": ["How does FEB work?"],
            "mood": "positive",
        })
        update_patterns(state_dir, "session-2", {
            "topics": ["skmemory", "qdrant", "embeddings"],
            "people": ["Chef"],
            "projects": ["SKWhisper"],
            "questions": ["How does FEB work?"],
            "mood": "neutral",
        })

        hot = get_hot_topics(state_dir, top_n=5)
        assert len(hot) > 0
        assert hot[0]["topic"] == "skmemory"  # Most mentioned
        assert hot[0]["count"] == 2

        patterns = load_patterns(state_dir)
        assert patterns["entities"]["people"]["Chef"] == 2
        assert patterns["questions"]["how does feb work?"]["count"] == 2

        print("✓ patterns: OK")
        print(f"  Hot topics: {[t['topic'] for t in hot[:3]]}")


def test_config(monkeypatch):
    """Test config loading is agent-aware via SKAGENT env."""
    import importlib
    monkeypatch.setenv("SKAGENT", "lumina")
    monkeypatch.delenv("SKCAPSTONE_AGENT", raising=False)
    import skwhisper.config as cfg_mod
    importlib.reload(cfg_mod)

    config = cfg_mod.Config()  # No TOML, use defaults
    assert config.ollama_url == "http://192.168.0.100:11434"
    assert config.qdrant_collection == "lumina-memory"
    assert config.min_messages == 2
    assert config.max_digest_per_cycle == 20
    # Sovereign default: sessions live under skcapstone agent home
    assert str(config.sessions_dir).endswith("/.skcapstone/agents/lumina/sessions")
    print("✓ config: OK")
    print(f"  State dir: {config.state_dir}")


def test_classify_session_human():
    """Human conversations are classified correctly."""
    from skwhisper.watcher import classify_session

    msgs = [
        {"role": "user", "text": "Hey Lumina, can you help me debug this async race condition?"},
        {"role": "assistant", "text": "Sure! Let me look at the code and trace the execution path."},
        {"role": "user", "text": "The issue appears in the pattern matching logic around line 42."},
        {"role": "assistant", "text": "I see it. The problem is that you're not awaiting the coroutine."},
        {"role": "user", "text": "Ah right! Thanks, fixing that now."},
    ]
    result = classify_session(msgs)
    assert result == "human", f"Expected 'human', got '{result}'"
    print("✓ classify_session (human): OK")


def test_classify_session_cron_keyword():
    """Sessions with cron markers are classified as cron."""
    from skwhisper.watcher import classify_session

    # [cron:] marker
    msgs_cron_tag = [
        {"role": "user", "text": "[cron:moltbook] Running scheduled task"},
        {"role": "assistant", "text": "Running automated reply sprint..."},
    ]
    assert classify_session(msgs_cron_tag) == "cron", "Should detect [cron:] marker"

    # moltbook keyword
    msgs_moltbook = [
        {"role": "user", "text": "moltbook reply sprint starting now"},
        {"role": "assistant", "text": "Processing replies..."},
    ]
    assert classify_session(msgs_moltbook) == "cron", "Should detect moltbook keyword"

    # heartbeat keyword
    msgs_heartbeat = [
        {"role": "user", "text": "HEARTBEAT check — systems nominal"},
        {"role": "assistant", "text": "All systems operational."},
    ]
    assert classify_session(msgs_heartbeat) == "cron", "Should detect heartbeat keyword"

    # comms-check keyword
    msgs_comms = [
        {"role": "user", "text": "comms-check initiated"},
        {"role": "assistant", "text": "Checking all communication channels..."},
    ]
    assert classify_session(msgs_comms) == "cron", "Should detect comms-check keyword"

    print("✓ classify_session (cron keywords): OK")


def _write_jsonl(path, lines):
    path.write_text("".join(json.dumps(l) + "\n" for l in lines))
    return path


def test_short_real_chat_is_human(tmp_path):
    """A one-question chat is a conversation, not cron (was: tiny file => cron)."""
    from skwhisper.watcher import classify_session, extract_messages

    p = _write_jsonl(tmp_path / "s.jsonl", [
        {"type": "session_meta", "session_id": "s", "source": "telegram"},
        {"role": "user", "content": "what time is dinner tonight?"},
        {"role": "assistant", "content": "Dinner is at 7, Chef."},
    ])
    msgs, _ = extract_messages(p)
    assert classify_session(msgs, p) == "human"

    # Same for a short transcript without any metadata (Claude Code, legacy).
    q = _write_jsonl(tmp_path / "q.jsonl", [
        {"type": "message", "message": {"role": "user", "content": "run the tests please"}},
        {"type": "message", "message": {"role": "assistant", "content": "All 16 tests pass."}},
    ])
    msgs, _ = extract_messages(q)
    assert classify_session(msgs, q) == "human"


def test_classify_by_source_metadata(tmp_path):
    """Hermes source metadata is authoritative, in both exporter and legacy shapes."""
    from skwhisper.watcher import classify_session

    human_msgs = [{"role": "user", "text": "hey, quick question about the heartbeat monitor"}]
    for i, (key, src, want) in enumerate([
        ("source", "cron", "cron"), ("source", "subagent", "cron"), ("source", "oneshot", "cron"),
        ("source", "nctalk", "human"), ("source", "api_server", "human"),
        ("platform", "telegram", "human"), ("platform", "cron", "cron"),
    ]):
        meta = {"type" if key == "source" else "role": "session_meta", key: src}
        p = _write_jsonl(tmp_path / f"m{i}.jsonl", [meta])
        # 'heartbeat' would trip the keyword fallback; metadata wins for real chats.
        assert classify_session(human_msgs, p) == want, (key, src)


def test_partial_line_not_consumed(tmp_path):
    """A line still being written is left for the next read (offset not advanced past it)."""
    from skwhisper.watcher import extract_messages

    p = tmp_path / "s.jsonl"
    full = json.dumps({"role": "user", "content": "first complete message"}) + "\n"
    p.write_text(full + '{"role": "assistant", "content": "half wri')
    msgs, off = extract_messages(p)
    assert len(msgs) == 1 and off == len(full)
    with open(p, "a") as f:
        f.write('tten reply"}\n')
    msgs, _ = extract_messages(p, off)
    assert [m["text"] for m in msgs] == ["half written reply"]


def test_digested_session_continuation(tmp_path):
    """A digested session that keeps growing gets its new part digested, once idle."""
    import time as _t
    from skwhisper.config import Config
    from skwhisper.watcher import scan_sessions, mark_digested, extract_messages

    sessions = tmp_path / "sessions"
    sessions.mkdir()
    cfg_file = tmp_path / "c.toml"
    cfg_file.write_text(f'[a]\nsessions_dir = "{sessions}"\nstate_dir = "{tmp_path / "st"}"\n')
    config = Config(cfg_file)
    p = _write_jsonl(sessions / "s1.jsonl", [
        {"type": "session_meta", "session_id": "s1", "source": "telegram"},
        {"role": "user", "content": "morning, what is on today?"},
        {"role": "assistant", "content": "Two calls and the dentist."},
    ])
    _, off = extract_messages(p)
    mark_digested(config, "s1", off)
    old = _t.time() - 3600
    os.utime(p, (old, old))
    assert scan_sessions(config) == []

    with open(p, "a") as f:
        f.write(json.dumps({"role": "user", "content": "move the dentist to friday"}) + "\n")
        f.write(json.dumps({"role": "assistant", "content": "Done, Friday at 10."}) + "\n")
    os.utime(p, (old, old))
    got = scan_sessions(config)
    assert len(got) == 1 and got[0]["continuation"]
    assert [m["text"] for m in got[0]["messages"]] == ["move the dentist to friday", "Done, Friday at 10."]


def test_classify_session_no_false_positive():
    """Multi-turn human session with keywords in later messages isn't misclassified."""
    from skwhisper.watcher import classify_session

    # The word 'moltbook' only appears after the first 10 messages
    msgs = [{"role": "user", "text": f"message {i}"} for i in range(15)]
    msgs.append({"role": "user", "text": "checking moltbook status"})

    result = classify_session(msgs)
    assert result == "human", f"Late keyword in large session should be 'human', got '{result}'"
    print("✓ classify_session (no false positive for late keywords): OK")


def test_patterns_session_type_tracking():
    """Topics are tracked per session type (human_count / cron_count)."""
    from skwhisper.patterns import update_patterns, get_hot_topics, load_patterns

    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)

        update_patterns(state_dir, "session-h1", {
            "topics": ["skmemory", "python"],
            "people": ["Chef"],
            "projects": ["SKWhisper"],
            "questions": [],
            "mood": "positive",
        }, session_type="human")

        update_patterns(state_dir, "session-h2", {
            "topics": ["skmemory", "qdrant"],
            "people": [],
            "projects": [],
            "questions": [],
            "mood": "neutral",
        }, session_type="human")

        update_patterns(state_dir, "session-c1", {
            "topics": ["moltbook", "comms-check", "skmemory"],
            "people": [],
            "projects": [],
            "questions": [],
            "mood": "neutral",
        }, session_type="cron")

        patterns = load_patterns(state_dir)
        skmemory = patterns["topics"]["skmemory"]
        assert skmemory["count"] == 3, f"Total count should be 3, got {skmemory['count']}"
        assert skmemory.get("human_count", 0) == 2, f"human_count should be 2, got {skmemory.get('human_count')}"
        assert skmemory.get("cron_count", 0) == 1, f"cron_count should be 1, got {skmemory.get('cron_count')}"

        # get_hot_topics with type filter
        human_topics = get_hot_topics(state_dir, top_n=5, session_type="human")
        human_topic_names = [t["topic"] for t in human_topics]
        assert "skmemory" in human_topic_names
        assert "moltbook" not in human_topic_names, "moltbook is cron-only, shouldn't appear in human topics"

        cron_topics = get_hot_topics(state_dir, top_n=5, session_type="cron")
        cron_topic_names = [t["topic"] for t in cron_topics]
        assert "moltbook" in cron_topic_names
        assert "python" not in cron_topic_names, "python is human-only, shouldn't appear in cron topics"

        print("✓ patterns session_type tracking: OK")
        print(f"  Human topics: {human_topic_names}")
        print(f"  Cron topics: {cron_topic_names}")


if __name__ == "__main__":
    print("Running SKWhisper tests...\n")
    test_extract_messages()
    test_skmemory_writer()
    test_patterns()
    test_config()
    test_classify_session_human()
    test_classify_session_cron_keyword()
    test_classify_session_cron_file_size()
    test_classify_session_no_false_positive()
    test_patterns_session_type_tracking()
    print("\n✅ All tests passed!")

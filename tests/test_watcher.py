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


def test_config():
    """Test config loading."""
    from skwhisper.config import Config

    config = Config()  # No TOML, use defaults
    assert config.ollama_url == "http://localhost:11434"
    assert config.qdrant_collection == f"{config.agent_label.lower()}-memory"
    assert config.min_messages == 5
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


def test_classify_session_cron_file_size():
    """Small file with few user messages classified as cron."""
    import tempfile
    from skwhisper.watcher import classify_session

    msgs = [
        {"role": "user", "text": "run task"},
        {"role": "assistant", "text": "done"},
    ]

    # Write a tiny file (< 6000 bytes, <= 3 user messages)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        f.write('{"type": "message", "message": {"role": "user", "content": "run task"}}\n')
        f.write('{"type": "message", "message": {"role": "assistant", "content": "done"}}\n')
        fname = f.name

    try:
        from pathlib import Path
        result = classify_session(msgs, Path(fname))
        assert result == "cron", f"Tiny file with 1 user msg should be 'cron', got '{result}'"
        print("✓ classify_session (small file): OK")
    finally:
        import os
        os.unlink(fname)


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

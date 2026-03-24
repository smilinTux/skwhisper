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
    assert config.ollama_url == "http://192.168.0.100:11434"
    assert config.qdrant_collection == "lumina-memory"
    assert config.min_messages == 5
    print("✓ config: OK")
    print(f"  State dir: {config.state_dir}")


if __name__ == "__main__":
    print("Running SKWhisper tests...\n")
    test_extract_messages()
    test_skmemory_writer()
    test_patterns()
    test_config()
    print("\n✅ All tests passed!")

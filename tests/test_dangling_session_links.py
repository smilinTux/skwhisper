"""A dangling session symlink must not abort curation.

Sessions dirs are symlink farms into runtime transcript dirs. When a runtime
deletes a transcript (Claude Code prunes subagent logs), the link dangles. On
chiap02/03/08 one such link made every daemon cycle raise FileNotFoundError in
_get_recent_context, so whisper.md went stale for days.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from skwhisper import curator


def _session(path: Path, text: str) -> None:
    path.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": text}})
        + "\n"
    )


def test_recent_context_skips_dangling_symlink(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    _session(sessions / "live.jsonl", "hello from a live session")
    (sessions / "agent-gone.jsonl").symlink_to(
        tmp_path / "missing" / "agent-gone.jsonl"
    )

    config = SimpleNamespace(sessions_dir=sessions, user_label="User", agent_label="Agent")
    # Must not raise; the live session is still considered.
    curator._get_recent_context(config)


def test_recent_context_with_only_dangling_links(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "a.jsonl").symlink_to(tmp_path / "nope-a.jsonl")
    (sessions / "b.jsonl").symlink_to(tmp_path / "nope-b.jsonl")

    config = SimpleNamespace(sessions_dir=sessions, user_label="User", agent_label="Agent")
    assert isinstance(curator._get_recent_context(config), str)

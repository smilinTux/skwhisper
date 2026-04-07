"""Transcript Watcher — monitors and digests OpenClaw session transcripts."""

import json
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

from .config import Config

log = logging.getLogger("skwhisper.watcher")

# Keywords that indicate an automated/cron session rather than a human conversation
_CRON_KEYWORDS = (
    "[cron:",
    "moltbook",
    "heartbeat",
    "reply sprint",
    "self-reflection: review",
    "morning-motivation",
    "comms-check",
    "gmail-check",
)


def classify_session(messages: list[dict], path: Path | None = None) -> str:
    """
    Classify a session as 'human' or 'cron'.

    Primary signal: content patterns in early messages (cron markers, automation keywords).
    Secondary signal: very small file + few user turns suggests an automated session.

    Returns 'cron' or 'human'.
    """
    # Check first 10 messages for cron markers
    for msg in messages[:10]:
        text = msg.get("text", "").lower()
        if any(kw in text for kw in _CRON_KEYWORDS):
            return "cron"

    # Secondary: tiny file + very few user messages → likely automated
    if path is not None and messages:
        user_count = sum(1 for m in messages if m["role"] == "user")
        try:
            size = path.stat().st_size
            if size < 6000 and user_count <= 3:
                return "cron"
        except OSError:
            pass

    return "human"


def load_state(state_dir: Path) -> dict:
    """Load watcher state (offsets per session file)."""
    state_file = state_dir / "state.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("Corrupted state.json, starting fresh")
    return {"sessions": {}, "last_run": None}


def save_state(state_dir: Path, state: dict):
    """Persist watcher state."""
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    state_file = state_dir / "state.json"
    state_file.write_text(json.dumps(state, indent=2))


def extract_messages(jsonl_path: Path, offset: int = 0) -> tuple[list[dict], int]:
    """
    Extract conversational messages from a session JSONL file.
    Returns (messages, new_offset).
    """
    messages = []
    new_offset = offset

    try:
        with open(jsonl_path, "r") as f:
            f.seek(offset)
            while True:
                line = f.readline()
                if not line:
                    break
                new_offset = f.tell()
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type", "")

                # Support both OpenClaw format (type="message") and
                # Claude Code format (type="user" / type="assistant")
                if entry_type == "message":
                    msg = entry.get("message", {})
                    role = msg.get("role", "")
                elif entry_type in ("user", "assistant"):
                    msg = entry.get("message", {})
                    role = entry_type
                else:
                    continue

                # Only keep user and assistant messages (skip toolResult)
                if role not in ("user", "assistant"):
                    continue

                # Extract text content
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Content array — extract text parts only
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif isinstance(part, str):
                            text_parts.append(part)
                    content = "\n".join(text_parts)

                if not content or len(content) < 10:
                    continue

                # Skip rehydration preambles (system context, not conversation)
                if content.startswith("[SKMemory —") or content.startswith("=== Memory Rehydration"):
                    continue

                messages.append({
                    "role": role,
                    "text": content[:5000],  # Cap per-message length
                    "timestamp": entry.get("timestamp", ""),
                })
    except (OSError, IOError) as e:
        log.error("Error reading %s: %s", jsonl_path, e)

    return messages, new_offset


def scan_sessions(config: Config) -> list[dict]:
    """
    Scan for sessions that need digesting.
    Returns list of {path, session_id, messages, new_offset, is_idle}.
    """
    sessions_dir = config.sessions_dir
    state = load_state(config.state_dir)
    now = time.time()
    results = []

    # Scan active .jsonl files
    for path in sorted(sessions_dir.glob("*.jsonl")):
        session_id = path.stem
        session_state = state.get("sessions", {}).get(session_id, {})

        if session_state.get("digested"):
            continue

        offset = session_state.get("offset", 0)
        last_seen = session_state.get("last_seen", 0)

        # Check file modification time
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue

        # Only process if file changed since last check
        if mtime <= last_seen and offset > 0:
            # Check if idle long enough to digest
            idle_seconds = now - mtime
            if idle_seconds >= config.idle_threshold:
                # Collect ALL messages for digestion
                all_messages, _ = extract_messages(path, 0)
                if len(all_messages) >= config.min_messages:
                    results.append({
                        "path": path,
                        "session_id": session_id,
                        "messages": all_messages,
                        "new_offset": _,
                        "is_idle": True,
                    })
            continue

        # File has new content — extract new messages
        messages, new_offset = extract_messages(path, offset)

        if messages:
            # Update state
            if "sessions" not in state:
                state["sessions"] = {}
            state["sessions"][session_id] = {
                "offset": new_offset,
                "last_seen": mtime,
                "message_count": session_state.get("message_count", 0) + len(messages),
            }

            # Check if idle enough for digestion
            idle_seconds = now - mtime
            if idle_seconds >= config.idle_threshold:
                # Get all messages for full digestion
                all_messages, final_offset = extract_messages(path, 0)
                if len(all_messages) >= config.min_messages:
                    results.append({
                        "path": path,
                        "session_id": session_id,
                        "messages": all_messages,
                        "new_offset": final_offset,
                        "is_idle": True,
                    })
        else:
            # No new messages but update last_seen
            if "sessions" not in state:
                state["sessions"] = {}
            state["sessions"][session_id] = {
                "offset": offset,
                "last_seen": mtime,
                "message_count": session_state.get("message_count", 0),
            }

    # Also scan deleted/archived sessions that weren't digested
    for suffix in ("*.deleted.*", "*.archived.*"):
        for path in sessions_dir.glob(suffix):
            # Extract session ID from filename like "uuid.jsonl.deleted.timestamp"
            parts = path.name.split(".")
            if len(parts) >= 2:
                session_id = parts[0]
            else:
                continue

            session_state = state.get("sessions", {}).get(session_id, {})
            if session_state.get("digested"):
                continue

            all_messages, final_offset = extract_messages(path, 0)
            if len(all_messages) >= config.min_messages:
                results.append({
                    "path": path,
                    "session_id": session_id,
                    "messages": all_messages,
                    "new_offset": final_offset,
                    "is_idle": True,
                })

    save_state(config.state_dir, state)
    return results


def format_messages_for_summary(messages: list[dict], max_chars: int = 15000) -> str:
    """Format extracted messages into a text block for summarization."""
    lines = []
    total = 0
    for msg in messages:
        role = "Chef" if msg["role"] == "user" else "Lumina"
        line = f"{role}: {msg['text']}"
        if total + len(line) > max_chars:
            lines.append(f"[...{len(messages) - len(lines)} more messages truncated...]")
            break
        lines.append(line)
        total += len(line)
    return "\n\n".join(lines)


def mark_digested(config: Config, session_id: str, offset: int, session_type: str = "human"):
    """Mark a session as fully digested in state."""
    state = load_state(config.state_dir)
    if "sessions" not in state:
        state["sessions"] = {}
    state["sessions"][session_id] = {
        "offset": offset,
        "digested": True,
        "session_type": session_type,
        "digested_at": datetime.now(timezone.utc).isoformat(),
    }
    save_state(config.state_dir, state)

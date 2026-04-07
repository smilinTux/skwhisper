"""Context Curator — surfaces relevant memories before sessions."""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from .clients.ollama import OllamaClient
from .clients.qdrant import QdrantClient
from .patterns import load_patterns, get_hot_topics, get_repeated_questions
from .watcher import extract_messages
from .config import Config

log = logging.getLogger("skwhisper.curator")


async def curate_context(config: Config) -> str:
    """
    Generate a curated whisper context file based on recent sessions
    and semantic memory search.
    Returns the whisper content as a string.
    """
    ollama = OllamaClient(config.ollama_url, config.embed_model, config.summarize_model)
    qdrant = QdrantClient(config.qdrant_url, config.qdrant_api_key, config.qdrant_collection)

    try:
        # 1. Gather recent conversation context
        recent_text = _get_recent_context(config)
        if not recent_text:
            log.info("No recent conversation context found")
            return _build_whisper(config, [], [], [], [])

        # 2. Generate embedding of recent context
        # mxbai-embed-large has ~512 token limit (~1000 chars); truncate safely
        embed_text = recent_text[:800]
        log.info("Embedding recent context (%d chars)...", len(embed_text))
        vector = await ollama.embed(embed_text)

        # 3. Search Qdrant for semantically similar memories (optional)
        results = []
        if config.qdrant_url:
            log.info("Searching skvector for relevant memories...")
            results = await qdrant.search(vector, top_k=config.top_k, score_threshold=0.5)
            log.info("Found %d relevant memories", len(results))
        else:
            log.info("Qdrant not configured, skipping semantic search")

        # 4. Get pattern data
        hot_topics = get_hot_topics(config.state_dir, top_n=10)
        repeated_qs = get_repeated_questions(config.state_dir, min_count=2)

        # 5. Build whisper file
        whisper = _build_whisper(config, results, hot_topics, repeated_qs, [])

        # 6. Write to file
        whisper_path = config.state_dir / "whisper.md"
        whisper_path.write_text(whisper)
        log.info("Wrote whisper context: %s (%d chars)", whisper_path, len(whisper))

        return whisper

    finally:
        await ollama.close()
        await qdrant.close()


def _is_cron_session(path: Path) -> bool:
    """Detect if a session was triggered by cron (automated, not human-driven)."""
    import json
    try:
        with open(path) as f:
            for i, line in enumerate(f):
                if i > 15:  # Only check first few lines
                    break
                try:
                    entry = json.loads(line.strip())
                    # Cron sessions have [cron:...] markers in early messages
                    text = entry.get("message", {}).get("content", "")
                    if isinstance(text, str) and "[cron:" in text:
                        return True
                    # Also check for common cron task patterns
                    if isinstance(text, str) and any(kw in text.lower() for kw in [
                        "moltbook reply sprint",
                        "self-reflection: review",
                        "morning-motivation",
                        "comms-check",
                        "gmail-check",
                    ]):
                        return True
                except (json.JSONDecodeError, KeyError):
                    continue
    except OSError:
        pass
    return False


def _get_recent_context(config: Config) -> str:
    """Extract text from the most recent active sessions, prioritizing human-driven ones."""
    sessions_dir = config.sessions_dir
    # Get most recent active .jsonl files by mtime
    active = sorted(
        sessions_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    # Separate human-driven sessions from cron/automated sessions
    human_sessions = []
    cron_sessions = []
    for path in active[:20]:  # Check last 20 sessions
        if _is_cron_session(path):
            cron_sessions.append(path)
        else:
            human_sessions.append(path)

    # Prioritize: 2 human sessions + 1 cron (for variety), or all human if enough
    selected = human_sessions[:2]
    if len(selected) < 3 and cron_sessions:
        selected.append(cron_sessions[0])
    elif len(human_sessions) >= 3:
        selected = human_sessions[:3]

    log.info("Context selection: %d human, %d cron (from %d checked)",
             len([s for s in selected if s in human_sessions]),
             len([s for s in selected if s in cron_sessions]),
             min(len(active), 20))

    all_text = []
    for path in selected:
        messages, _ = extract_messages(path, 0)
        for msg in messages[-20:]:  # Last 20 messages per session
            role = config.user_label if msg["role"] == "user" else config.agent_label
            all_text.append(f"{role}: {msg['text'][:500]}")

    return "\n".join(all_text)[:8000]


def _build_whisper(
    config: Config,
    memory_results: list[dict],
    hot_topics: list[dict],
    repeated_questions: list[dict],
    suggestions: list[str],
) -> str:
    """Build the whisper.md content."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    lines = [
        f"# SKWhisper Context — {now}",
        "",
        "> Auto-generated subconscious context. Read-only.",
        "",
    ]

    # Relevant memories
    if memory_results:
        lines.append("## Relevant Memories")
        lines.append("")
        for r in memory_results[:10]:
            payload = r.get("payload", {})
            title = payload.get("title", "untitled")
            content = payload.get("content", "")[:200]
            score = r.get("score", 0)
            tags = ", ".join(payload.get("tags", [])[:5])
            lines.append(f"- **{title}** (relevance: {score:.2f})")
            if content:
                lines.append(f"  {content}")
            if tags:
                lines.append(f"  _Tags: {tags}_")
            lines.append("")

    # Recurring patterns
    if hot_topics:
        lines.append("## Hot Topics (recurring)")
        lines.append("")
        for t in hot_topics[:10]:
            lines.append(f"- **{t['topic']}** — mentioned {t['count']}x (last: {t.get('last', '?')})")
        lines.append("")

    # Repeated questions
    if repeated_questions:
        lines.append("## Repeated Questions")
        lines.append("")
        for q in repeated_questions[:5]:
            lines.append(f"- \"{q['question']}\" — asked {q['count']}x (last: {q.get('last_asked', '?')})")
        lines.append("")

    # Patterns summary
    patterns = load_patterns(config.state_dir)
    people = patterns.get("entities", {}).get("people", {})
    if people:
        top_people = sorted(people.items(), key=lambda x: x[1], reverse=True)[:10]
        lines.append("## Frequently Mentioned People")
        lines.append("")
        for name, count in top_people:
            lines.append(f"- {name}: {count} mentions")
        lines.append("")

    if not memory_results and not hot_topics:
        lines.append("_No patterns detected yet. SKWhisper is still learning._")
        lines.append("")

    lines.append(f"---")
    lines.append(f"_Generated by SKWhisper v0.1.0 at {now}_")
    return "\n".join(lines)

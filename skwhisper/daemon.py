"""SKWhisper Daemon — main loop that watches, digests, and curates."""

import asyncio
import logging
import time
from datetime import datetime, timezone

from .config import get_config, Config
from .watcher import scan_sessions, format_messages_for_summary, mark_digested, classify_session, extract_messages, load_state
from .curator import curate_context
from .patterns import update_patterns
from .clients.ollama import OllamaClient
from .clients.qdrant import QdrantClient
from .clients.skmemory import SKMemoryWriter

log = logging.getLogger("skwhisper")


async def digest_session(
    config: Config,
    session: dict,
    ollama: OllamaClient,
    qdrant: QdrantClient,
    memory: SKMemoryWriter,
) -> bool:
    """Digest a single session: summarize, extract, store, embed."""
    session_id = session["session_id"]
    messages = session["messages"]
    log.info("Digesting session %s (%d messages)...", session_id[:12], len(messages))

    try:
        # 1. Classify session before processing
        session_type = classify_session(messages, session.get("path"))
        log.debug("Session %s classified as: %s", session_id[:12], session_type)

        # 2. Format messages for summarization
        text = format_messages_for_summary(messages)

        # 3. Summarize via ollama
        summary = await ollama.summarize(text)
        if not summary or len(summary) < 20:
            log.warning("Summary too short for session %s, skipping", session_id[:12])
            return False

        # 4. Extract structured topics
        extracted = await ollama.extract_topics(summary)

        # 5. Build title from topics
        topics = extracted.get("topics", [])[:3]
        title_parts = [t.title() for t in topics] if topics else ["Session Digest"]
        title = f"Session Digest — {', '.join(title_parts)}"

        # 6. Determine tags (include session type for filtering)
        tags = ["skwhisper", "auto-digest", session_type]
        tags.extend(extracted.get("topics", [])[:5])
        for person in extracted.get("people", [])[:3]:
            tags.append(person.lower().replace(" ", "-"))

        # 7. Determine emotional labels
        mood = extracted.get("mood", "neutral")
        emotions = []
        if mood == "positive":
            emotions = ["engaged", "productive"]
        elif mood == "negative":
            emotions = ["frustrated", "concerned"]
        elif mood == "mixed":
            emotions = ["reflective"]

        # 8. Write to skmemory
        content = f"{summary}\n\nPeople: {', '.join(extracted.get('people', []))}\n"
        content += f"Projects: {', '.join(extracted.get('projects', []))}\n"
        if extracted.get("decisions"):
            content += f"Decisions: {'; '.join(extracted['decisions'])}\n"

        mem_id = memory.write_snapshot(
            title=title,
            content=content,
            tags=tags,
            emotions=emotions,
            intensity=6.0,
        )

        # 9. Embed and upsert to Qdrant (optional — skip if not configured)
        if qdrant.url:
            vector = await ollama.embed(summary[:800])
            await qdrant.upsert(
                vector=vector,
                payload={
                    "title": title,
                    "content": content[:2000],
                    "tier": "short-term",
                    "tags": tags,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "intensity": 6.0,
                    "emotions": ", ".join(emotions),
                    "source": "skwhisper",
                    "session_id": session_id,
                    "session_type": session_type,
                },
                point_id=mem_id,
            )

        # 10. Update patterns (pass session type so topics can be split by origin)
        update_patterns(config.state_dir, session_id, extracted, session_type=session_type)

        # 11. Mark as digested (store classification for status reporting)
        mark_digested(config, session_id, session["new_offset"], session_type=session_type)

        log.info("✓ Digested session %s: '%s'", session_id[:12], title)
        return True

    except Exception as e:
        log.error("Failed to digest session %s: %s", session_id[:12], e, exc_info=True)
        return False


async def run_digest_cycle(config: Config) -> int:
    """Run one digest cycle. Returns number of sessions digested."""
    ollama = OllamaClient(config.ollama_url, config.embed_model, config.summarize_model)
    qdrant = QdrantClient(config.qdrant_url, config.qdrant_api_key, config.qdrant_collection)
    memory = SKMemoryWriter(config.memory_dir)

    try:
        sessions = scan_sessions(config)
        idle_sessions = [s for s in sessions if s["is_idle"]]

        if not idle_sessions:
            log.debug("No idle sessions to digest")
            return 0

        log.info("Found %d sessions to digest", len(idle_sessions))
        digested = 0

        for session in idle_sessions:
            ok = await digest_session(config, session, ollama, qdrant, memory)
            if ok:
                digested += 1
            # Small delay between sessions to avoid hammering ollama
            await asyncio.sleep(2)

        return digested

    finally:
        await ollama.close()
        await qdrant.close()


async def run_backlog_digest(config: Config, batch_size: int = 10) -> int:
    """
    Process ALL undigested sessions that have enough messages, in batches.

    Unlike run_digest_cycle (which respects idle_threshold and only catches
    recently-changed files), this scans the entire sessions directory and
    processes anything pending — regardless of timing.

    Returns total number of sessions successfully digested.
    """
    sessions_dir = config.sessions_dir
    state = load_state(config.state_dir)

    # Collect candidates: active .jsonl files + deleted/archived
    candidates = []

    for path in sorted(sessions_dir.glob("*.jsonl")):
        session_id = path.stem
        if state.get("sessions", {}).get(session_id, {}).get("digested"):
            continue
        messages, final_offset = extract_messages(path, 0)
        if len(messages) >= config.min_messages:
            candidates.append({
                "path": path,
                "session_id": session_id,
                "messages": messages,
                "new_offset": final_offset,
                "is_idle": True,
            })

    for suffix in ("*.deleted.*", "*.archived.*"):
        for path in sorted(sessions_dir.glob(suffix)):
            parts = path.name.split(".")
            if len(parts) < 2:
                continue
            session_id = parts[0]
            if state.get("sessions", {}).get(session_id, {}).get("digested"):
                continue
            messages, final_offset = extract_messages(path, 0)
            if len(messages) >= config.min_messages:
                candidates.append({
                    "path": path,
                    "session_id": session_id,
                    "messages": messages,
                    "new_offset": final_offset,
                    "is_idle": True,
                })

    total = len(candidates)
    if total == 0:
        print("No pending sessions to digest.")
        return 0

    print(f"Found {total} sessions pending digest.")
    total_batches = (total + batch_size - 1) // batch_size

    ollama = OllamaClient(config.ollama_url, config.embed_model, config.summarize_model)
    qdrant = QdrantClient(config.qdrant_url, config.qdrant_api_key, config.qdrant_collection)
    memory = SKMemoryWriter(config.memory_dir)

    digested = 0
    try:
        for batch_start in range(0, total, batch_size):
            batch = candidates[batch_start:batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            print(f"\nBatch {batch_num}/{total_batches} ({len(batch)} sessions)...")

            for j, session in enumerate(batch, 1):
                idx = batch_start + j
                print(f"  [{idx}/{total}] {session['session_id'][:16]}...", end=" ", flush=True)
                ok = await digest_session(config, session, ollama, qdrant, memory)
                if ok:
                    digested += 1
                    print("✓")
                else:
                    print("✗")
                await asyncio.sleep(1)
    finally:
        await ollama.close()
        await qdrant.close()

    print(f"\nBacklog complete: {digested}/{total} sessions digested.")
    return digested


async def run_daemon(config: Config):
    """Main daemon loop: digest + curate on intervals."""
    log.info("SKWhisper daemon starting...")
    log.info("  Sessions dir: %s", config.sessions_dir)
    log.info("  Memory dir: %s", config.memory_dir)
    log.info("  State dir: %s", config.state_dir)
    log.info("  Poll interval: %ds", config.poll_interval)
    log.info("  Curate interval: %ds", config.curate_interval)

    last_curate = 0

    while True:
        try:
            # Digest cycle
            digested = await run_digest_cycle(config)
            if digested:
                log.info("Digest cycle: %d sessions processed", digested)

            # Curate cycle (less frequent)
            now = time.time()
            if now - last_curate >= config.curate_interval:
                log.info("Running context curation...")
                await curate_context(config)
                last_curate = now

        except Exception as e:
            log.error("Daemon cycle error: %s", e, exc_info=True)

        await asyncio.sleep(config.poll_interval)

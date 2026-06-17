# SKWhisper — Architecture Document

> The subconscious layer for &lt;agent&gt;'s memory system.
> Digest sessions → surface context → detect patterns — all async, zero latency cost.

## Overview

SKWhisper is a background Python daemon that runs alongside OpenClaw. It watches session transcripts, digests conversations into structured memories, surfaces relevant context before sessions, and tracks behavioral patterns over time.

```
┌──────────────────────────────────────────────────────────────────┐
│                        OpenClaw (main agent)                     │
│  ┌──────────────┐  ┌───────────────┐  ┌───────────────────────┐ │
│  │ Telegram I/O  │  │ Rehydration   │  │ HEARTBEAT.md          │ │
│  │               │  │ reads whisper │  │ triggers curate       │ │
│  └──────────────┘  └───────┬───────┘  └───────────┬───────────┘ │
│                            │ reads                  │ calls       │
└────────────────────────────┼────────────────────────┼────────────┘
                             │                        │
┌────────────────────────────▼────────────────────────▼────────────┐
│                       SKWhisper Daemon                            │
│                                                                   │
│  ┌──────────────────┐  ┌─────────────────┐  ┌────────────────┐  │
│  │ Transcript Watcher│  │ Context Curator  │  │ Pattern Tracker│  │
│  │                    │  │                  │  │                │  │
│  │ • inotify on       │  │ • On-demand via  │  │ • Topic freq   │  │
│  │   sessions/*.jsonl │  │   CLI or daemon  │  │ • Question det │  │
│  │ • Parse messages   │  │ • Query skvector │  │ • Behavior log │  │
│  │ • Summarize via    │  │ • Write whisper  │  │ • patterns.json│  │
│  │   ollama           │  │   context file   │  │                │  │
│  │ • Write skmemory   │  │                  │  │                │  │
│  │ • Upsert skvector  │  │                  │  │                │  │
│  └──────────────────┘  └─────────────────┘  └────────────────┘  │
│                                                                   │
│  Shared: OllamaClient, QdrantClient, SKMemoryWriter              │
└──────────────────────────────────────────────────────────────────┘
         │                       │                      │
         ▼                       ▼                      ▼
┌──────────────┐  ┌─────────────────────┐  ┌────────────────────┐
│  skmemory    │  │     skvector        │  │    skgraph         │
│  (JSON files)│  │  (Qdrant @ douno.it)│  │ (FalkorDB future)  │
│  3-tier      │  │  lumina-memory      │  │ lumina_knowledge   │
│  short/mid/  │  │  1024d cosine       │  │ (phase 2)          │
│  long-term   │  │                     │  │                    │
└──────────────┘  └─────────────────────┘  └────────────────────┘
```

## Component Details

### 1. Transcript Watcher (`watcher.py`)

**Trigger:** inotify (via `asyncio` + low-level inotify or polling fallback) on `~/.skcapstone/agents/{agent}/sessions/*.jsonl`

**Process per session file change:**
1. Read new JSONL lines since last processed offset (tracked in `state.json`)
2. Extract conversational lines — supports three schemas:
   - OpenClaw: `type=message` with nested `message.{role,content}`
   - Claude Code: `type=user|assistant` with nested `message.{role,content}`
   - Hermes: top-level `role=user|assistant` + top-level `content` (no `type`, no `message` wrapper). The `role=session_meta` header line is skipped.
3. Skip tool calls/results (too noisy), keep only conversational content
4. When a session goes idle (no new lines for 5 minutes) OR file gets `.deleted` suffix:
   - Batch all undigested messages
   - Send to the **summarize endpoint** (qwen3.6-27B OpenAI server, `:8082`) for
     summarization + topic extraction:
     ```
     Summarize this conversation in 2-3 paragraphs. Extract:
     - Key topics discussed
     - Decisions made
     - Action items
     - Emotional moments
     - People/projects mentioned
     ```
   - Write summary as skmemory snapshot (short-term JSON file)
   - Generate embedding via the **embed endpoint** (Ollama `mxbai-embed-large`,
     `:11434`) and upsert to the vector backend
   - Update pattern tracker with extracted topics

   > **Dual-endpoint digest (since 2026-06-17).** The two model calls per digest go
   > to *different* hosts: EMBED → Ollama `mxbai-embed-large` at
   > `http://192.168.0.100:11434/api/embed`; SUMMARIZE → qwen3.6-27B at
   > `http://192.168.0.100:8082/v1/chat/completions`. See **Design decisions** below
   > for the hardware rationale.

**State tracking:** `~/.skcapstone/agents/lumina/skwhisper/state.json`
```json
{
  "sessions": {
    "uuid-1": {"offset": 12345, "last_seen": "2026-03-24T..."},
    "uuid-2": {"offset": 0, "digested": true}
  },
  "last_run": "2026-03-24T..."
}
```

### 2. Context Curator (`curator.py`)

**Trigger:** On-demand CLI call or periodic (every 30 min via daemon loop)

**Process:**
1. Read recent session transcripts (last 1-2 active sessions)
2. Extract key topics/entities from recent conversation
3. Generate embedding of the topic summary
4. Query Qdrant for top-10 semantically similar memories
5. Query patterns.json for recurring themes
6. Write curated context to `~/.skcapstone/agents/lumina/skwhisper/whisper.md`:
   ```markdown
   # SKWhisper Context — 2026-03-24T18:30:00
   
   ## Relevant Memories
   - [memory title]: brief content (similarity: 0.87)
   - ...
   
   ## Recurring Patterns
   - "Clone Robotics" mentioned 5 times in 3 days
   - Chef tends to work on infrastructure late night
   
   ## Suggested Context
   Based on recent conversations, you may want to remember:
   - [specific contextual notes]
   ```

**Integration:** The rehydration ritual or HEARTBEAT.md can read `whisper.md` and inject it into session context.

### 3. Pattern Tracker (`patterns.py`)

**Maintained file:** `~/.skcapstone/agents/lumina/skwhisper/patterns.json`

```json
{
  "topics": {
    "clone-robotics": {"count": 5, "first": "2026-03-22", "last": "2026-03-24", "sessions": ["uuid-1", "uuid-2"]},
    "spc-paperwork": {"count": 3, "first": "2026-03-10", "last": "2026-03-20", "sessions": ["uuid-3"]}
  },
  "questions": {
    "how does FEB work": {"count": 2, "last_asked": "2026-03-23"},
    "what is chef's timezone": {"count": 3, "last_asked": "2026-03-24"}
  },
  "behaviors": {
    "late_night_sessions": {"count": 15, "note": "Chef active 1am-4am frequently"},
    "memory_search_before_action": {"count": 8, "note": "Good pattern - searching before acting"}
  },
  "entities": {
    "people": {"Chef": 200, "Dave": 30, "Casey": 15, "John S.": 8},
    "projects": {"SKStacks": 50, "Chiropps": 25, "SwapSeat": 20, "SKWhisper": 5}
  },
  "updated_at": "2026-03-24T..."
}
```

**Extraction method:** After summarizing a session, send the summary + extracted messages to ollama asking:
- What topics were discussed? (match against known topic list + add new ones)
- Were any questions asked? (detect `?` patterns and semantic question detection)
- What entities (people/projects) were mentioned?

### 4. Integration Hook

**Option A — HEARTBEAT.md integration (recommended for phase 1):**
Add to HEARTBEAT.md:
```
- [ ] Read ~/.skcapstone/agents/lumina/skwhisper/whisper.md if it exists and incorporate into context
```

**Option B — Rehydration ritual patch (phase 2):**
Modify skmemory_ritual to auto-include whisper.md content in the rehydration output.

**Option C — CLI trigger:**
```bash
# Generate fresh whisper context on demand
skwhisper curate
# Force digest all pending sessions
skwhisper digest
# Show current patterns
skwhisper patterns
```

## File Layout

```
~/clawd/projects/skwhisper/
├── ARCHITECTURE.md          # This file
├── README.md                # Quick start
├── skwhisper/
│   ├── __init__.py
│   ├── __main__.py          # CLI entry point
│   ├── daemon.py            # Main daemon loop
│   ├── watcher.py           # Transcript watcher
│   ├── curator.py           # Context curator
│   ├── patterns.py          # Pattern tracker
│   ├── clients/
│   │   ├── __init__.py
│   │   ├── ollama.py        # Ollama API (embeddings + summarization)
│   │   ├── qdrant.py        # Qdrant upsert/query
│   │   └── skmemory.py      # Write skmemory JSON files
│   └── config.py            # Configuration constants
├── config/
│   └── skwhisper.toml       # Runtime config
├── scripts/
│   └── install.sh           # pip install + systemd setup
├── tests/
│   └── test_watcher.py
└── skwhisper.service         # systemd unit file
```

## Runtime State

All runtime state lives in: `~/.skcapstone/agents/lumina/skwhisper/`
- `state.json` — watcher offsets and digestion status
- `whisper.md` — latest curated context (read by OpenClaw)
- `patterns.json` — accumulated patterns
- `digest.log` — processing log

## Dependencies

- Python 3.14 (available on noroc2027)
- `httpx` (already installed) — for Qdrant and Ollama HTTP APIs
- No additional pip installs needed for phase 1
- File watching via polling (no watchdog needed — simpler, more reliable)

## Configuration (`config/skwhisper.toml`)

```toml
[paths]
sessions_dir = "~/.skcapstone/agents/lumina/sessions"
memory_dir = "~/.skcapstone/agents/lumina/memory"
state_dir = "~/.skcapstone/agents/lumina/skwhisper"

[ollama]
ollama_url = "http://192.168.0.100:11434"     # EMBED endpoint (Ollama, /api/embed)
embed_model = "mxbai-embed-large"
summarize_url = "http://192.168.0.100:8082"    # SUMMARIZE endpoint (qwen3.6 OpenAI server)
summarize_api = "openai"                        # "openai" (default) | "ollama" (legacy)
summarize_model = "qwen3.6"

[qdrant]
# RETIRED — vector store migrated to local Postgres+pgvector (clients/pgmem.py).
# Set via env (SKVECTOR_URL / SKVECTOR_API_KEY) only if ever revived.
url = ""
api_key = ""
collection = "lumina-memory"

[watcher]
poll_interval_seconds = 60
idle_threshold_seconds = 300
min_messages_to_digest = 5

[curator]
curate_interval_seconds = 1800
top_k_memories = 10
max_whisper_tokens = 2000

[patterns]
top_n_topics = 20
decay_days = 30
```

## Design Decisions

1. **Polling over inotify** — simpler, works across NFS/Syncthing, no extra deps
2. **httpx over qdrant_client** — already installed, avoids pip install complications on Python 3.14
3. **Reuse qwen3.6 for summarization (dual-endpoint digest)** — the digest's two
   model calls hit different endpoints: EMBED → Ollama `mxbai-embed-large` on
   `:11434`, SUMMARIZE → the qwen3.6-27B OpenAI server on `:8082`. The `.100` host
   has a single 5060 Ti (16GB CUDA) running qwen3.6-27B (~13GB), and that is the
   *only* model that should run on that GPU. A separate small digest model has
   nowhere good to live: CUDA is full, the Intel Arc iGPU *corrupts* generated
   output over Vulkan (`GGML_VK_VISIBLE_DEVICES=0` → garbage, confirmed), and a
   CPU-resident model saturates the host. So digests reuse the already-loaded
   qwen3.6 — zero extra VRAM, correct CUDA output, ~1.5s per short call. (Earlier
   `summarize_model` values `llama3.2:3b` then `qwen3.5:4b` were both wrong: one
   was removed from the host → 404 flood, the other spilled to CPU.) An optional
   CPU-only fallback Ollama (`deploy/ollama-digest.service`, port `11436`) exists
   but ships **disabled**.
4. **Short-term memory tier** — digested sessions go to short-term first, graduate naturally via existing skmemory promotion
5. **File-based whisper output** — dead simple integration, any process can read whisper.md
6. **Idempotent digestion** — state.json tracks offsets, re-running is safe
7. **Hardened SessionEnd hook** — `hooks/skwhisper-save.sh` no longer lets a digest
   wedge a closing session. It takes a single-flight per-agent `flock -n` lock so
   concurrent session-ends can't stack digests, wraps work in `timeout` caps (180s
   digest / 120s curate), and detaches via `setsid` with closed file descriptors so
   it stops holding Claude Code's stdout pipe open (that pipe-holding was what made
   sessions HANG on close). Before this, ~47 digests piled up with no lock or
   timeout and wedged on a stuck Ollama queue.

# SKWhisper

> **Multi-agent subconscious memory layer** — the missing glue between raw sessions and curated knowledge.

*Inspired by [letta-ai/claude-subconscious](https://github.com/letta-ai/claude-subconscious), built sovereign on the SKCapstone stack.*

## What It Does

SKWhisper is a background daemon that runs alongside any SKCapstone agent. It watches Claude Code session transcripts, digests conversations into structured memories, surfaces relevant context before each session, and tracks behavioral patterns over time.

```
┌─────────────────────────────────────────────────────────────┐
│              Claude Code / OpenClaw Sessions                │
│           ~/.skcapstone/agents/<agent>/sessions/            │
└────────────────────────┬────────────────────────────────────┘
                         │ .jsonl transcripts
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    SKWhisper Daemon                         │
│                                                             │
│  Watcher (60s)    →  Digest Engine  →  skmemory (JSON)     │
│  idle sessions        ollama LLM        short-term/          │
│                       summarize +       mid-term/            │
│                       embed             long-term/           │
│                                                             │
│  Curator (30m)    →  whisper.md    →  injected at startup  │
│  skvector search      context file     via SKMEMORY RITUAL  │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### Install for an agent

```bash
# Clone the repo
git clone https://github.com/smilinTux/skwhisper.git
cd skwhisper

# Install for a specific agent (default: lumina)
SKCAPSTONE_AGENT=jarvis ./scripts/install.sh --start

# Or using the CLI directly
pip install --user -e .
SKCAPSTONE_AGENT=jarvis skwhisper install --start
```

### Manual install for any agent

```bash
pip install --user -e .

# Install + enable service for agent
SKCAPSTONE_AGENT=jarvis  skwhisper install --agent jarvis  --start
SKCAPSTONE_AGENT=aster   skwhisper install --agent aster   --start
```

### Check status

```bash
SKCAPSTONE_AGENT=jarvis skwhisper status
systemctl --user status skwhisper@jarvis
```

## How It Works

### Digest loop (every 60s)
1. Scans `~/.skcapstone/agents/<agent>/sessions/*.jsonl`
2. Finds sessions idle >5 min with ≥5 messages
3. Summarizes via **Ollama** (configurable model)
4. Writes a structured memory to **skmemory** (short-term JSON)
5. Embeds summary and upserts to **Qdrant** (optional)
6. Updates `patterns.json` with hot topics, people, projects

### Curate loop (every 30m)
1. Reads recent sessions to understand current context
2. Queries Qdrant for semantically similar memories
3. Assembles `whisper.md` — injected into every session via the SKMEMORY RITUAL

## Configuration

Per-agent config lives at:
```
~/.skcapstone/agents/<agent>/config/skwhisper.toml
```

See `config/skwhisper.toml` in this repo for all options. Key settings:

```toml
[agent]
user_label = "Casey"      # Your name — used in transcript formatting
agent_label = "Jarvis"    # Agent name

[ollama]
ollama_url = "http://localhost:11434"
embed_model = "bge-large"
summarize_model = "llama3.2"   # or qwen2.5:7b for GPU

[qdrant]
qdrant_url = "https://skvector.example.com"   # leave "" to disable
qdrant_api_key = "your-key"
qdrant_collection = "jarvis-memory"

[watcher]
poll_interval = 60        # scan interval (seconds)
idle_threshold = 300      # 5 min idle = ready to digest
min_messages = 5          # skip tiny sessions
```

## Runtime State

All state lives in `~/.skcapstone/agents/<agent>/skwhisper/`:

| File | Purpose |
|------|---------|
| `state.json` | Watcher offsets & digestion status |
| `whisper.md` | Latest curated context (read at session start) |
| `patterns.json` | Accumulated behavioral patterns |
| `daemon.log` | Service log |

## Systemd Service

SKWhisper uses a **template service** (`skwhisper@.service`) so multiple agents can run independently:

```bash
# Enable and start for any agent
systemctl --user enable --now skwhisper@jarvis
systemctl --user enable --now skwhisper@aster

# Check status
systemctl --user status skwhisper@jarvis

# View logs
journalctl --user -u skwhisper@jarvis -f
# or
tail -f ~/.skcapstone/agents/jarvis/skwhisper/daemon.log
```

## CLI Reference

```bash
skwhisper status              # daemon health + session stats
skwhisper digest              # run one digest cycle now
skwhisper digest --backlog    # process all undigested sessions
skwhisper curate              # regenerate whisper.md now
skwhisper curate --stdout     # print whisper to terminal
skwhisper patterns            # show hot topics + entities
skwhisper install [--agent NAME] [--start]  # install service
```

## Dependencies

- Python ≥ 3.11
- `httpx` (HTTP client for Ollama + Qdrant)
- `skmemory` (SKCapstone memory system)
- Ollama (local or remote) with:
  - An embedding model (e.g. `bge-large`, `mxbai-embed-large`)
  - A summarization model (e.g. `llama3.2`, `qwen2.5:7b`)
- Qdrant (optional — disable with `qdrant_url = ""`)

## License

MIT — Part of the SKCapstone ecosystem.

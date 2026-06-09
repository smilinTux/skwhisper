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

---

## Installation

### Prerequisites

- Python ≥ 3.11
- `skmemory` installed (`pip install skmemory` or editable from source)
- Ollama running locally or on a reachable host
- SKCapstone agent directory structure at `~/.skcapstone/agents/<agent>/`

### Option A — Script (recommended for first install)

```bash
git clone https://github.com/smilinTux/skwhisper.git ~/skwhisper-dev
cd ~/skwhisper-dev

# Install and start for a specific agent
SKCAPSTONE_AGENT=jarvis ./scripts/install.sh --start

# The script will:
#   1. pip install the package
#   2. Create ~/.skcapstone/agents/jarvis/config/skwhisper.toml (if missing)
#   3. Create sessions/ and skwhisper/ state dirs
#   4. Install skwhisper@.service template
#   5. systemctl --user enable --now skwhisper@jarvis
```

### Option B — CLI install

```bash
pip install --user -e ~/skwhisper-dev

# Install service for one or more agents
SKCAPSTONE_AGENT=jarvis skwhisper install --agent jarvis --start
SKCAPSTONE_AGENT=aster  skwhisper install --agent aster  --start
```

### Option C — Externally-managed Python (Ubuntu 23.04+)

On systems that block `pip --user` (PEP 668):

```bash
# If ~/.skenv exists (SKCapstone standard venv)
~/.skenv/bin/pip install -e ~/skwhisper-dev

# Otherwise, force user install
pip install --user --break-system-packages -e ~/skwhisper-dev
```

---

## Estate-Wide Deployment

To deploy skwhisper across multiple nodes, SSH to each and run the install script.
The `SKCAPSTONE_AGENT` env var controls which agent is configured.

### Single node

```bash
ssh chiap01 "cd ~/skwhisper-dev && git pull && SKCAPSTONE_AGENT=jarvis ./scripts/install.sh --start"
```

### All nodes in parallel (bash)

```bash
NODES="chiap01 chiap02 chiap03 chiap08 chiap09 chiap10"

DEPLOY='
set -e
DEST=~/skwhisper-dev
[ -d "$DEST" ] && (cd "$DEST" && git pull --quiet) || git clone --quiet https://github.com/smilinTux/skwhisper.git "$DEST"

if [ -f ~/.skenv/bin/pip ]; then
  ~/.skenv/bin/pip install -q -e "$DEST"
  ln -sf ~/.skenv/bin/skwhisper ~/.local/bin/skwhisper 2>/dev/null || true
else
  pip3 install --user --break-system-packages -q -e "$DEST"
fi

SKCAPSTONE_AGENT=jarvis ~/.local/bin/skwhisper install --agent jarvis --start
SKCAPSTONE_AGENT=aster  ~/.local/bin/skwhisper install --agent aster  --start
'

for host in $NODES; do
  ssh -o BatchMode=yes $host "bash -s" <<< "$DEPLOY" 2>&1 | sed "s/^/[$host] /" &
done
wait
```

### Verify estate health

```bash
for host in chiap01 chiap02 chiap03 chiap08 chiap09 chiap10; do
  echo -n "$host  jarvis="
  ssh $host "systemctl --user is-active skwhisper@jarvis" 2>/dev/null
  echo -n "        aster="
  ssh $host "systemctl --user is-active skwhisper@aster"  2>/dev/null
done
```

---

## SKCapstone Integration

SKWhisper is designed to work within the SKCapstone agent framework. Here's how the pieces connect.

### Directory layout (per agent)

```
~/.skcapstone/agents/<agent>/
├── config/
│   └── skwhisper.toml        # SKWhisper config for this agent
├── sessions/                 # Claude Code .jsonl transcripts (watched)
├── memory/
│   ├── short-term/           # Digested session memories land here
│   ├── mid-term/
│   └── long-term/
├── skwhisper/
│   ├── state.json            # Watcher offsets + digestion status
│   ├── whisper.md            # Curated context — injected at session start
│   ├── patterns.json         # Hot topics, people, repeated questions
│   └── daemon.log            # Service log
└── journal.md
```

### How whisper.md gets injected

The SKMEMORY RITUAL (run by the session startup hook) reads `whisper.md` and prepends it into the Claude Code context window before each session. No manual steps required — once the service is running, every new session automatically gets the subconscious context.

To verify injection is wired up, check your startup hook reads:
```
~/.skcapstone/agents/<agent>/skwhisper/whisper.md
```

### Triggering SKCapstone-aware digestion

If you use `skcapstone coord` for task scheduling, you can trigger a digest or curate from a cron task:

```bash
# One-shot digest (e.g. from a cron task)
SKCAPSTONE_AGENT=jarvis skwhisper digest

# Force-regenerate whisper context
SKCAPSTONE_AGENT=jarvis skwhisper curate

# Process entire session backlog
SKCAPSTONE_AGENT=jarvis skwhisper digest --backlog
```

### Adding a new agent

```bash
# 1. Create the agent directory structure (if not already done by skcapstone)
mkdir -p ~/.skcapstone/agents/myagent/{sessions,memory/{short-term,mid-term,long-term},skwhisper,config}

# 2. Install and start skwhisper for it
SKCAPSTONE_AGENT=myagent skwhisper install --agent myagent --start

# 3. Edit the generated config
$EDITOR ~/.skcapstone/agents/myagent/config/skwhisper.toml

# 4. Verify
SKCAPSTONE_AGENT=myagent skwhisper status
```

---

## Configuration

Per-agent config at `~/.skcapstone/agents/<agent>/config/skwhisper.toml`.
See `config/skwhisper.toml` in this repo for the full annotated template.

```toml
[agent]
user_label = "Casey"       # Your name — used in transcript formatting
agent_label = "Jarvis"     # Agent name

[ollama]
ollama_url = "http://localhost:11434"
embed_model = "bge-large"
summarize_model = "llama3.2"    # CPU; use qwen2.5:7b for GPU

[qdrant]
qdrant_url = "https://skvector.example.com"   # set "" to disable
qdrant_api_key = "your-key"
qdrant_collection = "jarvis-memory"

[watcher]
poll_interval = 60        # scan interval (seconds)
idle_threshold = 300      # 5 min idle = ready to digest
min_messages = 5          # skip tiny sessions

[curator]
curate_interval = 1800    # regenerate whisper.md every 30 min
top_k = 10                # memories to surface via vector search
```

---

## Systemd Service

SKWhisper uses a **template unit** (`skwhisper@.service`) — one service file, one instance per agent.

```bash
# Install the template and enable for an agent (idempotent)
SKCAPSTONE_AGENT=jarvis skwhisper install --agent jarvis --start

# Or manually manage instances
systemctl --user enable --now skwhisper@jarvis
systemctl --user enable --now skwhisper@aster

# Status
systemctl --user status skwhisper@jarvis
systemctl --user status skwhisper@aster

# Restart after config change
systemctl --user restart skwhisper@jarvis

# Stop
systemctl --user stop skwhisper@jarvis

# Disable (won't start on login)
systemctl --user disable skwhisper@jarvis

# Logs
journalctl --user -u skwhisper@jarvis -f
tail -f ~/.skcapstone/agents/jarvis/skwhisper/daemon.log
```

The template file lives at `~/.config/systemd/user/skwhisper@.service` after install.
A copy of the source template is at `skwhisper@.service` in this repo.

---

## CLI Reference

```bash
# Daemon
skwhisper daemon                        # run in foreground (verbose with -v)

# Digest
skwhisper digest                        # one digest cycle
skwhisper digest --backlog              # process all undigested sessions
skwhisper digest --backlog --batch-size 5

# Curate
skwhisper curate                        # regenerate whisper.md
skwhisper curate --stdout               # print to terminal instead

# Inspect
skwhisper status                        # daemon health + session stats
skwhisper patterns                      # hot topics, people, projects
skwhisper patterns --json               # machine-readable output

# Service install
skwhisper install                       # install for $SKCAPSTONE_AGENT
skwhisper install --agent jarvis        # explicit agent name
skwhisper install --agent jarvis --start  # install and start immediately

# Global flags
skwhisper -v <command>                  # verbose logging
skwhisper -c /path/to/skwhisper.toml <command>  # explicit config
```

---

## Runtime State

| File | Purpose |
|------|---------|
| `~/.skcapstone/agents/<agent>/skwhisper/state.json` | Watcher offsets + digestion status per session |
| `~/.skcapstone/agents/<agent>/skwhisper/whisper.md` | Latest curated context injected at session start |
| `~/.skcapstone/agents/<agent>/skwhisper/patterns.json` | Accumulated hot topics, people, questions |
| `~/.skcapstone/agents/<agent>/skwhisper/daemon.log` | Service log |

---

## How It Works

### Digest loop (every 60s)
1. Scans `~/.skcapstone/agents/<agent>/sessions/*.jsonl`
2. Finds sessions idle >5 min with ≥5 messages
3. Summarizes via Ollama (`summarize_model`)
4. Extracts topics, people, projects, decisions as structured JSON
5. Writes a short-term memory snapshot to `skmemory`
6. Embeds the summary and upserts to Qdrant (if configured)
7. Updates `patterns.json`

### Curate loop (every 30m)
1. Reads the last 2–3 active sessions to build a query context
2. Embeds that context and searches Qdrant for the top-K most similar memories
3. Combines semantic results + pattern data into `whisper.md`
4. `whisper.md` is read by the SKMEMORY RITUAL at the start of every new session

### Session classification
Sessions are classified as `human` or `cron` based on early message content. Cron sessions (automated tasks, scheduled agents) are tracked separately and deprioritized in curator output, so human-driven context always surfaces first.

---

## Dependencies

- Python ≥ 3.11
- `httpx` — async HTTP for Ollama + Qdrant
- `skmemory` — SKCapstone memory system
- Ollama (local or remote):
  - Embedding model: `bge-large` or `mxbai-embed-large`
  - Summarization model: `llama3.2` (CPU) / `qwen2.5:7b` (GPU)
- Qdrant — optional; disable with `qdrant_url = ""`

---

## License

MIT — Part of the SKCapstone ecosystem.

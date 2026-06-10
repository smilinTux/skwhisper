# SKWhisper — Architecture

> The subconscious layer for an agent's memory: digest sessions → surface context →
> detect patterns — all asynchronous, off the conscious critical path, zero latency
> cost to the live conversation.

SKWhisper is a single background Python daemon (`skwhisper daemon`) that runs one
instance **per agent** (keyed to `$SKAGENT`). It has three cooperating concerns —
a **watcher/digester**, a **pattern tracker**, and a **curator** — all sharing a
small set of clients (Ollama, a pluggable vector backend, an optional graph writer,
and the skmemory snapshot writer).

It is the *write side* of sovereign memory. The agent's conscious memory recall (the
skmemory ritual) happens during a session; SKWhisper does the slow, reflective work
**between** sessions: reading what was said, distilling it, and leaving a briefing.

---

## The two loops

The daemon's `run_daemon` loop runs two cadences (see `daemon.py`):

- a **digest cycle** every `poll_interval` (default 60s), and
- a **curate cycle** every `curate_interval` (default 1800s / 30 min).

### Digest loop (per session)

```mermaid
sequenceDiagram
    participant W as Watcher (scan_sessions)
    participant D as Digester (digest_session)
    participant O as Ollama
    participant M as skmemory (JSON)
    participant V as Vector backend (pgvector)
    participant G as Graph (AGE)
    participant P as patterns.json

    W->>W: glob sessions/*.jsonl, read new bytes since offset
    W->>D: idle session (>=5 min, >=min_messages)
    D->>D: classify_session() -> human | cron
    alt cron and skip_cron
        D->>W: mark_digested (cron-skipped), stop
    else human (or cron kept)
        D->>O: summarize(formatted transcript)
        O-->>D: 2-3 paragraph summary
        D->>O: extract_topics(summary) -> JSON
        O-->>D: topics, people, projects, decisions, mood
        D->>M: write_snapshot(title, content, tags, emotions)
        M-->>D: mem_id
        D->>O: embed(summary) -> 1024-dim vector
        D->>V: upsert(vector, payload, point_id=mem_id)
        D->>P: update_patterns(topics, people, questions)
        opt graph enabled
            D->>G: write_memory(session, topics, people, projects)
        end
        D->>W: mark_digested(session_id, new_offset, session_type)
    end
```

Key properties, all grounded in `daemon.py` / `watcher.py`:

- **Idempotent.** `state.json` records a byte offset and a `digested` flag per
  session id; re-running never re-processes a finished session. Non-digest outcomes
  are recorded too (`skipped-too-few-messages`, `cleaned-missing-file`,
  `cron-skipped`) so `status` can report them.
- **Idle-gated.** `run_digest_cycle` only digests sessions that have gone idle
  (no new bytes for `idle_threshold`). `run_backlog_digest` ignores timing and
  sweeps everything pending in batches — used for first-run catch-up.
- **Safe summaries.** A summary shorter than 20 chars is discarded (the session is
  left pending rather than filed as junk).

### Curate loop (briefing generation)

```mermaid
sequenceDiagram
    participant C as Curator (curate_context)
    participant S as Recent sessions
    participant O as Ollama
    participant V as Vector backend (pgvector + BM25)
    participant P as patterns.json
    participant F as whisper.md

    C->>S: pick recent sessions (2 human + 1 cron, by mtime)
    S-->>C: last ~20 turns per session (truncated)
    C->>O: embed(recent context) -> 1024-dim vector
    C->>V: search(query_text, query_vec, top_k) [hybrid vec + BM25 RRF]
    V-->>C: top-K memories with relevance scores
    C->>P: get_hot_topics(human) + get_repeated_questions
    P-->>C: pattern data
    C->>F: write whisper.md (memories + topics + questions + people)
```

The curator deliberately **prioritizes human-driven sessions** over cron/automation
when choosing what's "recent" (`_get_recent_context` / `_is_cron_session`), so the
briefing reflects what *you* are working on, not what the scheduler ran.

---

## Component map

| Source | Responsibility |
|---|---|
| `skwhisper/__main__.py` | CLI: `daemon`, `digest`, `curate`, `patterns`, `status`, `install`; logging setup |
| `skwhisper/daemon.py` | The loop; `digest_session`, `run_digest_cycle`, `run_backlog_digest`, `run_daemon` |
| `skwhisper/watcher.py` | Session scan, multi-schema JSONL parsing, `classify_session`, `state.json` load/save, `mark_digested` |
| `skwhisper/curator.py` | Recent-context gathering, hybrid search, `whisper.md` rendering (`_build_whisper`) |
| `skwhisper/patterns.py` | `patterns.json` accumulation; `get_hot_topics`, `get_repeated_questions` (session-type aware) |
| `skwhisper/config.py` | `$SKAGENT`/`$SKCAPSTONE_AGENT` resolution, TOML merge, config search path, defaults |
| `skwhisper/clients/factory.py` | `make_vector_client` / `make_graph_writer` — backend selection |
| `skwhisper/clients/ollama.py` | Async `embed` (`/api/embed`) + `summarize` + `extract_topics` |
| `skwhisper/clients/pgmem.py` | **Default** vector backend: local Postgres + pgvector + pg_search BM25 hybrid |
| `skwhisper/clients/qdrant.py` | Alternate vector backend: remote Qdrant / skvector |
| `skwhisper/clients/chroma.py` | Alternate vector backend: local ChromaDB |
| `skwhisper/clients/agegraph.py` | **Default** graph writer: Apache AGE inside the local Postgres |
| `skwhisper/clients/skgraph.py` | Alternate graph writer: FalkorDB / skgraph |
| `skwhisper/clients/skmemory.py` | `SKMemoryWriter` — writes 3-tier JSON snapshots |
| `config/skwhisper.toml` | Annotated per-agent config template |
| `scripts/install.sh` | pip install + systemd template setup |
| `skwhisper@.service` | Systemd template unit (`%i` = agent name) |

---

## Transcript schemas

`extract_messages` (in `watcher.py`) parses three transcript shapes from a single
sessions directory, because different runtimes write the agent home differently:

| Runtime | Line shape |
|---|---|
| **Claude Code** | `type = user \| assistant`, with nested `message.{role, content}` |
| **OpenClaw** | `type = message`, with nested `message.{role, content}` |
| **Hermes** | top-level `role = user \| assistant` + top-level `content` (no `type`, no `message` wrapper); a `role = session_meta` header line is skipped |

Tool calls and tool results are dropped — only conversational turns are kept, which
keeps the LLM summary signal clean.

---

## Pluggable backends

Backend choice is resolved at runtime from config/env by `clients/factory.py`. All
vector clients implement the same async duck-typed interface:

```
embed(text) -> list[float]
search(q_text, q_vec, top_k) -> [{payload, score}]
upsert(vector, payload, point_id)
close()
```

```mermaid
flowchart TD
    CFG["config: vector_backend / graph_backend<br/>(TOML or env)"] --> FAC["clients/factory.py"]
    FAC -->|"pgvector (default)"| PG["PGMemClient<br/>(Postgres + pgvector + pg_search BM25)"]
    FAC -->|qdrant| QD["QdrantClient<br/>(remote skvector)"]
    FAC -->|chromadb| CH["ChromaClient<br/>(local ChromaDB)"]
    FAC -->|"age (default)"| AGE["AGEGraphWriter<br/>(Apache AGE in Postgres)"]
    FAC -->|falkordb| FK["SKGraphWriter<br/>(FalkorDB)"]
    FAC -->|none| OFF["graph writes disabled"]
```

The default path (**pgvector + AGE**) lands every digest into the one local
`skmem-pg` Postgres: vectors via pgvector, keyword matching via pg_search BM25
(fused with vectors through Reciprocal Rank Fusion at curate time), and a knowledge
graph via Apache AGE — no external cluster required. Qdrant/FalkorDB remain selectable
for installs that still front a remote vector/graph cluster.

> **Embedding model contract:** digests are embedded with `mxbai-embed-large`
> (1024-dim). The curator MUST embed its query with the **same** model for the
> vector half of the hybrid search to be meaningful.

---

## Where it lives in the SKWorld ecosystem

SKWhisper is a **Core** capability deployed through skos like every other `sk*`
service. It reads from the agent's filesystem home, calls **Compute** (the local
LLM), and writes into **Data** (skmem-pg). Its sibling is `skmemory`: SKWhisper is
the subconscious *writer*, the ritual is the conscious *reader*.

```mermaid
flowchart TD
    OP["operator / agent"] -->|"skwhisper install --start"| SKW
    subgraph CORE["Core"]
      SKW["**skwhisper**<br/>subconscious memory layer"]
      SKMEMORY["skmemory<br/>(3-tier JSON + ritual)"]
      CAPAUTH["capauth"]
      CLOUD9["cloud9"]
    end
    subgraph COMPUTE["Compute"]
      SKMODEL["skmodel → ollama<br/>(summarize + mxbai embed)"]
    end
    subgraph DATA["Data"]
      SKMEMPG["skmem-pg<br/>(pgvector + pg_search BM25 + Apache AGE)"]
    end
    subgraph PLATFORM["Platform primitives"]
      SCHED["skscheduler / coord<br/>(can trigger digest/curate)"]
      SKCAP["skcapstone<br/>(agent home + \$SKAGENT)"]
    end
    SKCAP -->|"sessions/*.jsonl"| SKW
    SKW -->|"summarize + embed"| SKMODEL
    SKW -->|"snapshots"| SKMEMORY
    SKW -->|"vectors + graph"| SKMEMPG
    SKW -->|"hybrid search"| SKMEMPG
    SCHED -.->|"optional cron trigger"| SKW
    SKW -->|"whisper.md"| SKMEMORY
```

---

## Design decisions

1. **Polling over inotify** — simpler, survives NFS/Syncthing-backed session dirs,
   no extra dependency. Offsets in `state.json` make it cheap and idempotent.
2. **Local LLM for summarization** — Ollama on the compute node; no transcript ever
   leaves sovereign infrastructure.
3. **Short-term tier on write** — digests land in short-term memory and graduate
   naturally via skmemory's existing promotion, rather than guessing tier on ingest.
4. **File-based briefing** — `whisper.md` is a plain Markdown file any process (the
   ritual, a hook, a human) can read. Dead-simple integration boundary.
5. **Pluggable backends behind one interface** — pgvector/qdrant/chromadb and
   AGE/falkordb/none are swappable without touching the daemon, so the same code runs
   personal (one Postgres) or fleet (remote cluster).
6. **Human-first curation** — cron/automation sessions are classified and
   deprioritized so the subconscious reflects human intent, not scheduler noise.

---

Part of the **[SKWorld](https://skworld.io)** sovereign ecosystem · the subconscious behind every agent · 🐧 smilinTux

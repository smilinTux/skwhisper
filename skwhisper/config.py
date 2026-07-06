"""SKWhisper configuration."""

from pathlib import Path
import tomllib
import os

# Resolve active agent from env. SKAGENT is the primary source of truth
# (matches skmemory). SKCAPSTONE_AGENT kept for backward compatibility.
_AGENT = os.environ.get("SKAGENT") or os.environ.get("SKCAPSTONE_AGENT") or "lumina"

# Defaults — all agent-specific paths use _AGENT.
# Sessions live under the sovereign agent home; sources (Claude Code, Hermes,
# OpenClaw, etc.) symlink or write into ~/.skcapstone/agents/{agent}/sessions/.
# Vector store is local Postgres+pgvector (see clients/pgmem.py); qdrant/falkordb
# are retired (douno cluster) and read from env only if ever revived.
DEFAULTS = {
    "agent_name": _AGENT,
    "sessions_dir": Path.home() / ".skcapstone" / "agents" / _AGENT / "sessions",
    "memory_dir": Path.home() / ".skcapstone" / "agents" / _AGENT / "memory",
    "state_dir": Path.home() / ".skcapstone" / "agents" / _AGENT / "skwhisper",
    "ollama_url": "http://192.168.0.100:11434",  # embeddings (mxbai) — Ollama on the GPU host
    "embed_model": "mxbai-embed-large",
    # Summarization reuses the already-resident qwen3.6 on the 5060 Ti via its
    # OpenAI-compatible server (:8082) — the ONLY model on that GPU. The Arc iGPU
    # corrupts generated output (GGML_VK_VISIBLE_DEVICES=0) and a separate small
    # model has nowhere to run, so digests share qwen3.6 (zero extra VRAM, ~1.5s).
    # summarize_api: "openai" (default, qwen3.6 :8082) | "ollama" (legacy /api/generate).
    "summarize_url": "http://192.168.0.100:8082",
    "summarize_api": "openai",
    "summarize_model": "qwen3.6",
    # Vector backend selection: "pgvector" (default) | "qdrant" | "chromadb"
    "vector_backend": os.environ.get("SKMEMORY_VECTOR_BACKEND", "pgvector"),
    "qdrant_url": os.environ.get("SKVECTOR_URL", ""),
    "qdrant_api_key": os.environ.get("SKVECTOR_API_KEY", ""),
    "qdrant_collection": f"{_AGENT}-memory",
    # Graph backend selection: "age" (Postgres/Apache AGE, default) | "falkordb" | "none"
    "graph_backend": os.environ.get("SKMEMORY_GRAPH_BACKEND", "age"),
    "pg_dsn": os.environ.get("SKMEMORY_PG_DSN", "postgresql://postgres:skmemory@localhost:5432/skmemory"),
    "falkordb_host": "192.168.0.59",
    "falkordb_port": 16379,
    "falkordb_graph": f"{_AGENT}_knowledge",
    "user_label": "Casey",
    "agent_label": _AGENT.capitalize(),
    "poll_interval": 60,
    "idle_threshold": 300,
    "min_messages": 5,
    "curate_interval": 1800,
    "top_k": 10,
    # Recency feed: newest memories pulled from the local SQLite index (relational/
    # recency layer) — the "latest session info" half of whisper. Complements the
    # semantic pg feed (top_k). See clients/sqlite_recency.py.
    "recent_k": 8,
    "max_whisper_tokens": 2000,
    "top_n_topics": 20,
    "decay_days": 30,
    "skip_cron": True,
}


class Config:
    """Runtime configuration loaded from TOML or defaults."""

    def __init__(self, config_path: str | Path | None = None):
        self._data = dict(DEFAULTS)
        if config_path and Path(config_path).exists():
            with open(config_path, "rb") as f:
                toml = tomllib.load(f)
            self._merge(toml)
        # Ensure state dir exists
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _merge(self, toml: dict):
        flat = {}
        for section in toml.values():
            if isinstance(section, dict):
                flat.update(section)
        for k, v in flat.items():
            if k in self._data:
                if isinstance(self._data[k], Path):
                    self._data[k] = Path(os.path.expanduser(v))
                elif isinstance(self._data[k], int):
                    self._data[k] = int(v)
                else:
                    self._data[k] = v

    def __getattr__(self, name):
        if name.startswith("_"):
            return super().__getattribute__(name)
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(f"No config key: {name}")


# Singleton
_config: Config | None = None


def get_config(path: str | Path | None = None) -> Config:
    global _config
    if _config is None:
        # Search order: explicit path > XDG config > skcapstone config > legacy
        candidates = [
            Path.home() / ".skcapstone" / "agents" / _AGENT / "config" / "skwhisper.toml",
            Path.home() / ".config" / "skwhisper" / "skwhisper.toml",
            Path.home() / ".skcapstone" / "config" / "skwhisper.toml",
        ]
        if path:
            default_path = Path(path)
        else:
            default_path = next((p for p in candidates if p.exists()), candidates[0])
        _config = Config(default_path)
    return _config


def reset_config() -> None:
    """Force re-resolution of SKCAPSTONE_AGENT (useful when env changes between calls)."""
    global _config
    _config = None

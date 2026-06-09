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
DEFAULTS = {
    "agent_name": _AGENT,
    "sessions_dir": Path.home() / ".skcapstone" / "agents" / _AGENT / "sessions",
    "memory_dir": Path.home() / ".skcapstone" / "agents" / _AGENT / "memory",
    "state_dir": Path.home() / ".skcapstone" / "agents" / _AGENT / "skwhisper",
    "ollama_url": "http://192.168.0.100:11434",
    "embed_model": "mxbai-embed-large",
    "summarize_model": "llama3.2:3b",
    "qdrant_url": os.environ.get("SKVECTOR_URL", ""),
    "qdrant_api_key": os.environ.get("SKVECTOR_API_KEY", ""),
    "qdrant_collection": f"{_AGENT}-memory",
    "falkordb_host": "192.168.0.59",
    "falkordb_port": 16379,
    "falkordb_graph": f"{_AGENT}_knowledge",
    "poll_interval": 60,
    "idle_threshold": 300,
    "min_messages": 5,
    "curate_interval": 1800,
    "top_k": 10,
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
        default_path = Path.home() / "clawd" / "projects" / "skwhisper" / "config" / "skwhisper.toml"
        _config = Config(path or default_path)
    return _config


def reset_config() -> None:
    """Force re-resolution of SKCAPSTONE_AGENT (useful when env changes between calls)."""
    global _config
    _config = None

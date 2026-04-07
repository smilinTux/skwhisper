"""SKWhisper configuration."""

from pathlib import Path
import tomllib
import os

# Defaults
_AGENT = os.environ.get("SKCAPSTONE_AGENT", "lumina")

DEFAULTS = {
    "sessions_dir": Path.home() / ".skcapstone" / "agents" / _AGENT / "sessions",
    "memory_dir": Path.home() / ".skcapstone" / "agents" / _AGENT / "memory",
    "state_dir": Path.home() / ".skcapstone" / "agents" / _AGENT / "skwhisper",
    "ollama_url": "http://localhost:11434",
    "embed_model": "bge-large",
    "summarize_model": "llama3.2:3b",
    "qdrant_url": "https://skvector.skstack01.douno.it",
    "qdrant_api_key": "e4hPZkg0Q899N7x0FmgNPT+s8QvY7a/LOnl0go1QCIQ",
    "qdrant_collection": f"{_AGENT}-memory",
    "user_label": "User",
    "agent_label": _AGENT.capitalize(),
    "poll_interval": 60,
    "idle_threshold": 300,
    "min_messages": 5,
    "curate_interval": 1800,
    "top_k": 10,
    "max_whisper_tokens": 2000,
    "top_n_topics": 20,
    "decay_days": 30,
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

"""skwhisper@<agent> must run as <agent>, whatever the node's default agent is.

The unit used to set only SKCAPSTONE_AGENT=%i. config.py reads SKAGENT first,
and environment.d sets SKAGENT node-wide, so on chi skwhisper@aster ran as a
second jarvis daemon on jarvis's state dir and aster's whisper.md went stale.
"""
from pathlib import Path
from types import SimpleNamespace

import skwhisper.__main__ as cli

SELECTORS = ("SKAGENT", "SKCAPSTONE_AGENT", "SKMEMORY_AGENT")
REPO = Path(__file__).resolve().parents[1]


def _env_lines(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines() if line.strip().startswith("Environment=")}


def test_shipped_unit_pins_every_selector():
    lines = _env_lines((REPO / "skwhisper@.service").read_text())
    for name in SELECTORS:
        assert f"Environment={name}=%i" in lines


def test_install_writes_a_unit_that_pins_every_selector(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda args, **kw: calls.append(args))
    cli.cmd_install(SimpleNamespace(agent="aster", start=False))
    lines = _env_lines((tmp_path / ".config/systemd/user/skwhisper@.service").read_text())
    for name in SELECTORS:
        assert f"Environment={name}=%i" in lines
    assert ["systemctl", "--user", "enable", "skwhisper@aster"] in calls


def test_config_follows_skagent_first(monkeypatch):
    """The reason all three matter: SKAGENT outranks SKCAPSTONE_AGENT."""
    import importlib

    import skwhisper.config as config

    monkeypatch.setenv("SKAGENT", "jarvis")
    monkeypatch.setenv("SKCAPSTONE_AGENT", "aster")
    try:
        assert importlib.reload(config)._AGENT == "jarvis"
    finally:
        monkeypatch.undo()
        importlib.reload(config)

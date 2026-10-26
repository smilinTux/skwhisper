"""Config default tests."""

from skwhisper.config import Config


def test_user_label_default_is_neutral(tmp_path, monkeypatch):
    """No agent may silently inherit another estate's human as its user label."""
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = Config(tmp_path / "missing.toml")
    assert cfg.user_label == "User"


def test_user_label_explicit_override(tmp_path):
    path = tmp_path / "skwhisper.toml"
    path.write_text(
        f'[paths]\nstate_dir = "{tmp_path}/state"\n[agent]\nuser_label = "Casey"\n'
    )
    assert Config(path).user_label == "Casey"

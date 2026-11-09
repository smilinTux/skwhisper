"""A graph that comes back clears GRAPH DEGRADED without waiting for a digest."""
from types import SimpleNamespace

import skwhisper.clients.agegraph as agegraph
from skwhisper import health
from skwhisper.clients.factory import make_graph_writer


def test_reachable_graph_clears_a_boot_time_failure(tmp_path, monkeypatch):
    cfg = SimpleNamespace(graph_backend="age", state_dir=tmp_path)
    monkeypatch.setattr(agegraph.AGEGraphWriter, "from_config", classmethod(lambda cls, c: None))
    assert make_graph_writer(cfg) is None
    assert health._load(tmp_path)["graph"]["error"]

    monkeypatch.setattr(agegraph.AGEGraphWriter, "from_config", classmethod(lambda cls, c: object()))
    assert make_graph_writer(cfg) is not None
    assert "graph" not in health._load(tmp_path)


def test_banner_is_gone_after_recovery(tmp_path, monkeypatch):
    cfg = SimpleNamespace(graph_backend="age", state_dir=tmp_path)
    monkeypatch.setattr(agegraph.AGEGraphWriter, "from_config", classmethod(lambda cls, c: None))
    make_graph_writer(cfg)
    assert "GRAPH DEGRADED" in health.banner(tmp_path)
    monkeypatch.setattr(agegraph.AGEGraphWriter, "from_config", classmethod(lambda cls, c: object()))
    make_graph_writer(cfg)
    assert health.banner(tmp_path) == ""

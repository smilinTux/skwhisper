"""Backend factories — select vector + graph clients from config.

Vector backends (config.vector_backend, only "pgvector"; Chroma and Qdrant are retired):
  - pgvector : local Postgres + pgvector + BM25 hybrid (clients/pgmem.py)   [DEFAULT]

Graph backends (config.graph_backend, default "age"):
  - age      : Apache AGE graph inside the local Postgres (clients/agegraph.py) [DEFAULT]
  - falkordb : FalkorDB / skgraph (clients/skgraph.py)
  - none     : disabled

All vector clients share one async duck-typed interface:
  embed(text) -> list[float] · search(q_text, q_vec, top_k) -> [{payload,score}]
  · upsert(vector, payload, point_id) · close()
"""
import logging

log = logging.getLogger("skwhisper.factory")


def make_vector_client(config):
    backend = (getattr(config, "vector_backend", None) or "pgvector").lower()
    agent = getattr(config, "agent_name", None)

    if backend in ("pgvector", "pg", "postgres", "postgresql"):
        from .pgmem import PGMemClient
        log.info("vector backend: pgvector (local Postgres)")
        return PGMemClient(agent=agent)

    if backend in ("qdrant", "chroma", "chromadb"):
        raise ValueError(f"vector_backend {backend!r} is retired; only pgvector is supported")

    raise ValueError(f"unknown vector_backend: {backend!r} (use pgvector)")


def _mark(config, comp, ok, err=""):
    sd = getattr(config, "state_dir", None)
    if sd is not None:
        from .. import health
        health.record(sd, comp, ok, err)


def make_graph_writer(config):
    """Return a graph writer (with .write_memory) or None if disabled/unavailable."""
    backend = (getattr(config, "graph_backend", None) or "age").lower()

    if backend in ("none", "off", ""):
        return None

    if backend == "age":
        from .agegraph import AGEGraphWriter
        writer = AGEGraphWriter.from_config(config)
        if writer is None:
            _mark(config, "graph", False, "AGE graph unavailable, graph writes are skipped")
        return writer

    if backend == "falkordb":
        from .skgraph import SKGraphWriter
        return SKGraphWriter.from_config(config)

    log.warning("unknown graph_backend %r — graph writes disabled", backend)
    return None

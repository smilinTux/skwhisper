"""SKWhisper → Apache AGE graph writer (Postgres-native skgraph).

Sovereign replacement for the FalkorDB skgraph: writes the same knowledge graph
(Memory / Tag / Person / Project nodes; TAGGED_WITH / MENTIONS / PART_OF /
RELATED_TO edges) into the Apache AGE graph living inside the local Postgres
(graph name = {agent}_knowledge). Cypher is executed via
  SELECT * FROM cypher('<graph>', $$ <cypher> $$) AS (v agtype);

Same node/edge model as clients/skgraph.py so downstream graph queries are
unchanged — only the storage engine differs (AGE-in-pg vs FalkorDB).
"""
import logging
import os
from typing import TYPE_CHECKING

import psycopg

if TYPE_CHECKING:
    from ..config import Config

log = logging.getLogger("skwhisper.agegraph")

_AGENT = os.environ.get("SKAGENT") or os.environ.get("SKCAPSTONE_AGENT") or "lumina"
DEFAULT_DSN = os.environ.get("SKMEMORY_PG_DSN", "postgresql://postgres:skmemory@localhost:5432/skmemory")
DEFAULT_GRAPH = f"{_AGENT}_knowledge"

KNOWN_PROJECTS = [
    "SKStacks", "Chiropps", "SwapSeat", "SKGentis", "SKWhisper",
    "Brother John", "FORGEPRINT", "NAMStacks", "Sovereign AI",
]


def _escape(s) -> str:
    """Escape a string for a single-quoted Cypher literal."""
    if not s:
        return ""
    return str(s).replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"') \
                 .replace("\n", " ").replace("\r", "")[:400]


class AGEGraphWriter:
    """Synchronous Apache-AGE graph writer (same model as SKGraphWriter)."""

    def __init__(self, dsn: str = DEFAULT_DSN, graph: str = DEFAULT_GRAPH):
        self._graph = graph
        self._conn = psycopg.connect(dsn, connect_timeout=10, autocommit=True)
        with self._conn.cursor() as cur:
            try:
                cur.execute("LOAD 'age';")
            except Exception:
                pass  # already preloaded via shared_preload_libraries
            cur.execute('SET search_path = ag_catalog, "$user", public;')
            # Verify graph exists (created out-of-band in skmem-build)
            cur.execute("SELECT count(*) FROM ag_catalog.ag_graph WHERE name = %s;", (graph,))
            if cur.fetchone()[0] == 0:
                cur.execute("SELECT ag_catalog.create_graph(%s);", (graph,))
        log.info("agegraph: connected to AGE graph=%s", graph)

    @classmethod
    def from_config(cls, config: "Config") -> "AGEGraphWriter | None":
        dsn = getattr(config, "pg_dsn", DEFAULT_DSN)
        graph = getattr(config, "falkordb_graph", DEFAULT_GRAPH)
        try:
            return cls(dsn=dsn, graph=graph)
        except Exception as e:
            log.warning("AGE graph unavailable (%s): %s — skipping graph writes", graph, e)
            return None

    def _q(self, cypher: str):
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM cypher('{self._graph}', $$ {cypher} $$) AS (v agtype);"
                )
                return cur.fetchall()
        except Exception as e:
            log.debug("agegraph query error: %s | cypher: %.120s", e, cypher)
            return None

    def _merge_node(self, label: str, name: str):
        safe = _escape(name)
        if not safe.strip():
            return
        self._q(f"MERGE (n:{label} {{name: '{safe}'}})")

    def _merge_rel(self, from_label, from_name, rel, to_label, to_name, weight: float = 1.0):
        sf, st = _escape(from_name), _escape(to_name)
        if not sf.strip() or not st.strip():
            return
        self._q(
            f"MATCH (a:{from_label} {{name: '{sf}'}}), (b:{to_label} {{name: '{st}'}}) "
            f"MERGE (a)-[r:{rel}]->(b) SET r.weight = coalesce(r.weight, 0) + {weight}"
        )

    def write_memory(self, session_id, title, summary, topics, people, projects, created_at):
        safe_title = _escape(title[:120])
        if not safe_title.strip():
            return
        self._q(
            f"MERGE (m:Memory {{name: '{safe_title}'}}) "
            f"SET m.summary = '{_escape(summary[:300])}', "
            f"m.date = '{_escape(created_at)}', m.session_id = '{_escape(session_id[:36])}'"
        )

        clean_topics = [t for t in (topics or []) if t and t not in ("skwhisper", "auto-digest")][:8]
        for topic in clean_topics:
            self._merge_node("Tag", topic)
            self._merge_rel("Memory", title, "TAGGED_WITH", "Tag", topic)

        for person in (people or [])[:6]:
            self._merge_node("Person", person)
            self._merge_rel("Memory", title, "MENTIONS", "Person", person)

        all_projects = set(projects or [])
        combined = (title + " " + summary).lower()
        for proj in KNOWN_PROJECTS:
            if proj.lower() in combined:
                all_projects.add(proj)
        for proj in list(all_projects)[:5]:
            self._merge_node("Project", proj)
            self._merge_rel("Memory", title, "PART_OF", "Project", proj)

        for i, t1 in enumerate(clean_topics):
            for t2 in clean_topics[i + 1:]:
                a, b = sorted((_escape(t1), _escape(t2)))
                self._merge_rel("Tag", a, "RELATED_TO", "Tag", b)

        log.debug("agegraph: Memory '%s' (topics=%d people=%d projects=%d)",
                  title[:40], len(clean_topics), len(people or []), len(all_projects))

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

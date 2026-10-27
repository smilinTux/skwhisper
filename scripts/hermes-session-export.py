#!/usr/bin/env python3
"""Export Hermes conversations from state.db to per-session JSONL for skwhisper.

Hermes stopped writing ``~/.hermes/sessions/<id>.jsonl`` transcripts (upstream
"stop writing JSONL in append_to_transcript"); conversations now live only in
the SQLite ``state.db``. skwhisper's watcher only reads ``*.jsonl`` in the
agent's ``sessions_dir``, so without this bridge it digests nothing from Hermes.

This script reads state.db READ-ONLY and writes one ``<session_id>.jsonl`` per
session into ``--out`` (the agent's sovereign sessions dir), in the Hermes line
shape skwhisper already parses (top-level ``role`` + ``content``). Files are
only ever appended to while the transcript grows, so skwhisper's byte offsets
stay valid; a file is rewritten only if its history no longer matches.

Stdlib only. Safe to run repeatedly (e.g. from a systemd timer).

    hermes-session-export.py --out ~/.skcapstone/agents/jarvis/sessions
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

# Automated or delegated sources: not a conversation with the agent's human.
DEFAULT_EXCLUDE_SOURCES = ("cron", "subagent")
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")


def _lines_for_session(conn: sqlite3.Connection, row: sqlite3.Row) -> list[str]:
    meta = {
        "type": "session_meta",
        "session_id": row["id"],
        "source": row["source"],
        "title": row["title"],
        "started_at": row["started_at"],
        "exporter": "skwhisper/hermes-session-export",
    }
    lines = [json.dumps(meta, ensure_ascii=False)]
    cur = conn.execute(
        "SELECT role, content, timestamp FROM messages "
        "WHERE session_id = ? AND role IN ('user', 'assistant') ORDER BY id",
        (row["id"],),
    )
    for role, content, ts in cur:
        if not isinstance(content, str) or not content.strip():
            continue  # tool-call-only assistant turns carry no text
        lines.append(json.dumps({"role": role, "content": content, "timestamp": ts}, ensure_ascii=False))
    return lines


def _write_if_changed(path: Path, text: str) -> str:
    """Append-only when possible so skwhisper offsets remain valid."""
    data = text.encode("utf-8")
    if path.exists():
        old = path.read_bytes()
        if old == data:
            return "unchanged"
        if data.startswith(old):
            with open(path, "ab") as f:
                f.write(data[len(old):])
            return "appended"
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return "written"


def export(state_db: Path, out: Path, since_days: float, exclude: set[str], min_messages: int,
           dry_run: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    cutoff = time.time() - since_days * 86400
    stats = {"sessions": 0, "unchanged": 0, "appended": 0, "written": 0, "skipped_short": 0}
    try:
        rows = conn.execute(
            "SELECT id, source, title, started_at FROM sessions "
            "WHERE started_at >= ? ORDER BY started_at",
            (cutoff,),
        ).fetchall()
        for row in rows:
            if (row["source"] or "") in exclude:
                continue
            lines = _lines_for_session(conn, row)
            if len(lines) - 1 < min_messages:
                stats["skipped_short"] += 1
                continue
            stats["sessions"] += 1
            path = out / f"{_SAFE_ID.sub('_', row['id'])}.jsonl"
            if dry_run:
                continue
            stats[_write_if_changed(path, "\n".join(lines) + "\n")] += 1
    finally:
        conn.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--state-db", type=Path, default=Path.home() / ".hermes" / "state.db")
    p.add_argument("--out", type=Path, required=True, help="agent sessions dir skwhisper watches")
    p.add_argument("--since-days", type=float, default=30.0)
    p.add_argument("--exclude-source", action="append", default=None,
                   help=f"Hermes session source to skip (repeatable; default: {', '.join(DEFAULT_EXCLUDE_SOURCES)})")
    p.add_argument("--min-messages", type=int, default=2, help="minimum user/assistant text turns")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    if not a.state_db.exists():
        print(f"state.db not found: {a.state_db}", file=sys.stderr)
        return 1
    exclude = set(a.exclude_source if a.exclude_source is not None else DEFAULT_EXCLUDE_SOURCES)
    stats = export(a.state_db.expanduser(), a.out.expanduser(), a.since_days, exclude, a.min_messages, a.dry_run)
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
# "oneshot" is a single non-interactive `hermes -z` run (scripts and agents).
DEFAULT_EXCLUDE_SOURCES = ("cron", "subagent", "oneshot")
# Hermes UI-only rows that are not conversation: hidden turns, background-process
# notices injected as user turns, and "this turn did not complete" placeholders.
_SKIP_DISPLAY_KINDS = ("hidden", "internal_notification", "failed_turn")
_EXPORTER = "skwhisper/hermes-session-export"
_EXPORTER_TAG = _EXPORTER.encode()
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _lines_for_session(conn: sqlite3.Connection, row: sqlite3.Row, has_display_kind: bool) -> list[str]:
    # Only stable fields: a change to line 1 (e.g. Hermes retitling the session
    # later) would force a full rewrite and invalidate the watcher's offsets.
    meta = {
        "type": "session_meta",
        "session_id": row["id"],
        "source": row["source"],
        "started_at": row["started_at"],
        "exporter": _EXPORTER,
    }
    lines = [json.dumps(meta, ensure_ascii=False)]
    sql = ("SELECT role, content, timestamp FROM messages "
           "WHERE session_id = ? AND role IN ('user', 'assistant')")
    params: list = [row["id"]]
    if has_display_kind:
        sql += f" AND COALESCE(display_kind, '') NOT IN ({','.join('?' * len(_SKIP_DISPLAY_KINDS))})"
        params += _SKIP_DISPLAY_KINDS
    cur = conn.execute(sql + " ORDER BY id", params)
    for role, content, ts in cur:
        if not isinstance(content, str) or not content.strip():
            continue  # tool-call-only assistant turns carry no text
        lines.append(json.dumps({"role": role, "content": content, "timestamp": ts}, ensure_ascii=False))
    return lines


def _write_if_changed(path: Path, text: str, mtime: float | None = None) -> str:
    """Append-only when possible so skwhisper offsets remain valid.

    Transcripts are private (mode 0600). The file mtime is set to the session's
    last activity so skwhisper's idle check and newest-first ordering reflect
    the conversation, not when this exporter happened to run."""
    data = text.encode("utf-8")
    result = "written"
    if path.exists():
        old = path.read_bytes()
        if _EXPORTER_TAG not in old.split(b"\n", 1)[0]:
            # A transcript Hermes itself wrote (pre state.db) or anything else we
            # did not create: never overwrite it.
            return "foreign"
        if old == data:
            return "unchanged"
        if data.startswith(old):
            # One write of whole lines; the watcher only consumes newline-terminated lines.
            with open(path, "ab") as f:
                f.write(data[len(old):])
            result = "appended"
    if result == "written":
        tmp = path.with_name(path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    if mtime:
        os.utime(path, (mtime, mtime))
    return result


def _as_epoch(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def export(state_db: Path, out: Path, since_days: float, exclude: set[str], min_messages: int,
           dry_run: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    cutoff = time.time() - since_days * 86400
    stats = {"sessions": 0, "unchanged": 0, "appended": 0, "written": 0, "foreign": 0,
             "skipped_short": 0}
    try:
        has_display_kind = "display_kind" in _columns(conn, "messages")
        # Window on the newest message, so a long-lived chat keeps exporting after
        # its start falls outside the window.
        last = "MAX(s.started_at, COALESCE((SELECT MAX(m.timestamp) FROM messages m WHERE m.session_id = s.id), 0))"
        rows = conn.execute(
            f"SELECT s.id, s.source, s.started_at, {last} AS last_at FROM sessions s "
            f"WHERE {last} >= ? ORDER BY s.started_at",
            (cutoff,),
        ).fetchall()
        for row in rows:
            if (row["source"] or "") in exclude:
                continue
            lines = _lines_for_session(conn, row, has_display_kind)
            if len(lines) - 1 < min_messages:
                stats["skipped_short"] += 1
                continue
            stats["sessions"] += 1
            path = out / f"{_SAFE_ID.sub('_', row['id'])}.jsonl"
            if dry_run:
                continue
            stats[_write_if_changed(path, "\n".join(lines) + "\n", _as_epoch(row["last_at"]))] += 1
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

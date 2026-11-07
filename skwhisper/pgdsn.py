"""Resolve the skmem-pg DSN from the canonical sources only.

Order: the process environment (systemd imports ~/.config/environment.d), then
~/.config/environment.d/skmemory.conf read directly (cron, bash, bare CLI).
There is deliberately NO hardcoded fallback password and NO per-agent override:
a stale copy of the DSN in a TOML or a default string is how a password rotation
left the AGE graph write failing with auth errors while whisper.md kept
regenerating (opus and lumina, 2026-08-15).
"""

import os
import re
from pathlib import Path

CANONICAL_CONF = Path.home() / ".config" / "environment.d" / "skmemory.conf"
_KEY = "SKMEMORY_PG_DSN"


class DSNUnavailable(RuntimeError):
    """No canonical SKMEMORY_PG_DSN could be found."""


def resolve_dsn(conf_path: Path | None = None) -> str:
    val = os.environ.get(_KEY, "").strip()
    if val:
        return val
    path = (
        Path(conf_path)
        if conf_path
        else Path(os.path.expanduser("~/.config/environment.d/skmemory.conf"))
    )
    try:
        for line in path.read_text().splitlines():
            m = re.match(rf"\s*(?:export\s+)?{_KEY}\s*=\s*(.*)$", line)
            if m:
                v = m.group(1).strip().strip("'\"")
                if v:
                    return v
    except OSError:
        pass
    raise DSNUnavailable(f"{_KEY} is not set and not found in {path}")


def redact(text: str) -> str:
    """Strip any user:password@ credentials from a message."""
    return re.sub(r"(\w+://[^:/\s@]+):[^@\s]*@", r"\1:***@", str(text))

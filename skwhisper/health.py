"""Backend health markers so a failed graph or vector write is visible.

The daemon records failures in state_dir/health.json; the curator reads them
and puts a banner at the top of whisper.md. A later success clears the marker.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .pgdsn import redact

log = logging.getLogger("skwhisper.health")
_FILE = "health.json"
_LABEL = {"graph": "GRAPH DEGRADED", "vector": "VECTOR DEGRADED"}


def _load(state_dir) -> dict:
    try:
        return json.loads((Path(state_dir) / _FILE).read_text())
    except (OSError, ValueError):
        return {}


def record(state_dir, component: str, ok: bool, error: str = "") -> None:
    try:
        data = _load(state_dir)
        if ok:
            if data.pop(component, None) is None:
                return
        else:
            data[component] = {
                "error": redact(error)[:200],
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        Path(state_dir).mkdir(parents=True, exist_ok=True)
        (Path(state_dir) / _FILE).write_text(json.dumps(data))
    except OSError as e:  # never let health bookkeeping break a digest
        log.warning("could not write health marker: %s", e)


def banner(state_dir) -> str:
    out = []
    for comp, info in _load(state_dir).items():
        label = _LABEL.get(comp, f"{comp.upper()} DEGRADED")
        out.append(
            f"> **WARNING {label}** since {info.get('at', '?')}: "
            f"{info.get('error', '')}. Context below may be incomplete."
        )
    return "\n".join(out)

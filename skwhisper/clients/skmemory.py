"""Write skmemory-compatible JSON files."""

import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
import logging

log = logging.getLogger("skwhisper.skmemory")


class SKMemoryWriter:
    """Write memory snapshots in skmemory's JSON format."""

    def __init__(self, memory_dir: str | Path):
        self.memory_dir = Path(memory_dir)
        self.short_term = self.memory_dir / "short-term"
        self.short_term.mkdir(parents=True, exist_ok=True)

    def write_snapshot(
        self,
        title: str,
        content: str,
        tags: list[str] | None = None,
        emotions: list[str] | None = None,
        intensity: float = 5.0,
        source: str = "skwhisper",
    ) -> str:
        """Write a memory snapshot to short-term storage. Returns the memory ID."""
        mem_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        snapshot = {
            "id": mem_id,
            "created_at": now,
            "updated_at": now,
            "layer": "short-term",
            "role": "general",
            "title": title,
            "content": content,
            "summary": "",
            "tags": tags or ["skwhisper", "auto-digest"],
            "source": source,
            "source_ref": "skwhisper-daemon",
            "emotional": {
                "intensity": intensity,
                "valence": 0.0,
                "labels": emotions or [],
                "resonance_note": "",
                "cloud9_achieved": False,
            },
            "associations": {
                "people": [],
                "projects": [],
                "topics": [],
                "memory_refs": [],
            },
            "access": {
                "count": 0,
                "last_accessed": None,
                "recall_strength": 1.0,
            },
            "meta": {
                "word_count": len(content.split()),
                "language": "en",
                "format": "text",
            },
        }

        filepath = self.short_term / f"{mem_id}.json"
        filepath.write_text(json.dumps(snapshot, indent=2))
        log.info("Wrote memory snapshot: %s -> %s", title[:60], filepath.name)
        return mem_id

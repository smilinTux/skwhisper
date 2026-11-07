"""Pattern Tracker — detects recurring topics, questions, and behaviors."""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from .sensitivity import is_sensitive

log = logging.getLogger("skwhisper.patterns")


def load_patterns(state_dir: Path) -> dict:
    """Load patterns.json."""
    pf = state_dir / "patterns.json"
    if pf.exists():
        try:
            return json.loads(pf.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("Corrupted patterns.json, starting fresh")
    return {
        "topics": {},
        "questions": {},
        "behaviors": {},
        "entities": {"people": {}, "projects": {}},
        "updated_at": None,
    }


def save_patterns(state_dir: Path, patterns: dict):
    """Persist patterns.json."""
    patterns["updated_at"] = datetime.now(timezone.utc).isoformat()
    pf = state_dir / "patterns.json"
    pf.write_text(json.dumps(patterns, indent=2))


def update_patterns(
    state_dir: Path,
    session_id: str,
    extracted: dict,
    session_type: str = "human",
    digest_tags: list[str] | None = None,
) -> dict:
    """
    Update patterns with extracted data from a digested session.
    `extracted` comes from OllamaClient.extract_topics().
    `session_type` is 'human' or 'cron', used to track topic origin.
    """
    patterns = load_patterns(state_dir)
    if digest_tags is not None and is_sensitive(digest_tags):
        # A sensitive digest (its tags carry a sacred/grief/medical/... stem) feeds
        # no topic, question or people count: whisper.md is read at every session
        # start. Its people are remembered so the same name from an ordinary
        # digest is dropped at curation time too.
        sp = patterns.setdefault("sensitive_people", [])
        for person in extracted.get("people", []):
            person = person.strip()
            if person and person not in sp:
                sp.append(person)
        save_patterns(state_dir, patterns)
        log.info("Sensitive digest %s: kept out of patterns", session_id[:12])
        return patterns
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    type_count_key = f"{session_type}_count"

    # Topics
    for topic in extracted.get("topics", []):
        topic = topic.lower().strip()
        if not topic or len(topic) < 2:
            continue
        if topic in patterns["topics"]:
            entry = patterns["topics"][topic]
            entry["count"] += 1
            entry["last"] = today
            entry[type_count_key] = entry.get(type_count_key, 0) + 1
            if session_id not in entry.get("sessions", []):
                entry.setdefault("sessions", []).append(session_id)
                # Keep only last 20 session refs
                entry["sessions"] = entry["sessions"][-20:]
        else:
            patterns["topics"][topic] = {
                "count": 1,
                "first": today,
                "last": today,
                "sessions": [session_id],
                type_count_key: 1,
            }

    # Questions
    for question in extracted.get("questions", []):
        question = question.strip()
        if not question:
            continue
        # Normalize
        qkey = question.lower()[:100]
        if qkey in patterns["questions"]:
            patterns["questions"][qkey]["count"] += 1
            patterns["questions"][qkey]["last_asked"] = today
        else:
            patterns["questions"][qkey] = {
                "count": 1,
                "text": question,
                "last_asked": today,
            }

    # People
    for person in extracted.get("people", []):
        person = person.strip()
        if person:
            patterns["entities"]["people"][person] = (
                patterns["entities"]["people"].get(person, 0) + 1
            )

    # Projects
    for project in extracted.get("projects", []):
        project = project.strip()
        if project:
            patterns["entities"]["projects"][project] = (
                patterns["entities"]["projects"].get(project, 0) + 1
            )

    # Detect behavioral patterns from session metadata
    # (e.g., late night sessions)
    for topic in extracted.get("topics", []):
        topic_lower = topic.lower()
        if any(kw in topic_lower for kw in ["late night", "3am", "2am", "1am", "insomnia"]):
            patterns["behaviors"].setdefault("late_night_activity", {
                "count": 0, "note": "Sessions or topics involving late-night activity"
            })["count"] += 1

    save_patterns(state_dir, patterns)
    log.info(
        "Patterns updated: %d topics, %d questions, %d people, %d projects",
        len(patterns["topics"]),
        len(patterns["questions"]),
        len(patterns["entities"]["people"]),
        len(patterns["entities"]["projects"]),
    )
    return patterns


def get_hot_topics(state_dir: Path, top_n: int = 10, session_type: str | None = None) -> list[dict]:
    """
    Get the most frequently discussed topics, sorted by count.
    If session_type is 'human' or 'cron', filter and rank by that type's count only.
    """
    patterns = load_patterns(state_dir)
    topics = []
    for k, v in patterns.get("topics", {}).items():
        if session_type is not None:
            count = v.get(f"{session_type}_count", 0)
            if count == 0:
                continue
        else:
            count = v.get("count", 0)
        topics.append({
            "topic": k,
            "count": count,
            "first": v.get("first"),
            "last": v.get("last"),
            "sessions": list(v.get("sessions", [])),
        })
    topics.sort(key=lambda t: t["count"], reverse=True)
    return topics[:top_n]


def get_repeated_questions(state_dir: Path, min_count: int = 2) -> list[dict]:
    """Get questions asked multiple times."""
    patterns = load_patterns(state_dir)
    return [
        {"question": v.get("text", k), "count": v["count"], "last_asked": v.get("last_asked")}
        for k, v in patterns.get("questions", {}).items()
        if v["count"] >= min_count
    ]


def get_people(state_dir: Path) -> dict[str, int]:
    """People mention counts (name -> count)."""
    return dict(load_patterns(state_dir).get("entities", {}).get("people", {}))


def get_sensitive_people(state_dir: Path) -> list[str]:
    """Names seen in sensitive digests (recorded by update_patterns)."""
    return list(load_patterns(state_dir).get("sensitive_people", []))

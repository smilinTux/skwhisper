"""Pattern Tracker — detects recurring topics, questions, and behaviors."""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone

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
) -> dict:
    """
    Update patterns with extracted data from a digested session.
    `extracted` comes from OllamaClient.extract_topics().
    """
    patterns = load_patterns(state_dir)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Topics
    for topic in extracted.get("topics", []):
        topic = topic.lower().strip()
        if not topic or len(topic) < 2:
            continue
        if topic in patterns["topics"]:
            entry = patterns["topics"][topic]
            entry["count"] += 1
            entry["last"] = today
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


def get_hot_topics(state_dir: Path, top_n: int = 10) -> list[dict]:
    """Get the most frequently discussed topics, sorted by count."""
    patterns = load_patterns(state_dir)
    topics = [
        {"topic": k, **v}
        for k, v in patterns.get("topics", {}).items()
    ]
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

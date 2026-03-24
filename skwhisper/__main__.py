"""SKWhisper CLI entry point."""

import argparse
import asyncio
import logging
import sys
import json
from pathlib import Path

from .config import get_config
from .daemon import run_daemon, run_digest_cycle
from .curator import curate_context
from .patterns import load_patterns, get_hot_topics, get_repeated_questions
from .watcher import load_state


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def cmd_daemon(args):
    """Run the background daemon."""
    config = get_config(args.config)
    asyncio.run(run_daemon(config))


def cmd_digest(args):
    """Run one digest cycle."""
    config = get_config(args.config)
    count = asyncio.run(run_digest_cycle(config))
    print(f"Digested {count} sessions.")


def cmd_curate(args):
    """Generate fresh whisper context."""
    config = get_config(args.config)
    whisper = asyncio.run(curate_context(config))
    if args.stdout:
        print(whisper)
    else:
        print(f"Whisper context written to: {config.state_dir / 'whisper.md'}")


def cmd_patterns(args):
    """Show current patterns."""
    config = get_config(args.config)

    if args.json:
        patterns = load_patterns(config.state_dir)
        print(json.dumps(patterns, indent=2))
        return

    hot = get_hot_topics(config.state_dir, top_n=15)
    questions = get_repeated_questions(config.state_dir)
    patterns = load_patterns(config.state_dir)

    print("═══ SKWhisper Patterns ═══\n")

    if hot:
        print("🔥 Hot Topics:")
        for t in hot:
            print(f"  {t['topic']:30s}  {t['count']:3d}x  (last: {t.get('last', '?')})")
        print()

    if questions:
        print("❓ Repeated Questions:")
        for q in questions:
            print(f"  \"{q['question'][:60]}\"  ({q['count']}x)")
        print()

    people = patterns.get("entities", {}).get("people", {})
    if people:
        print("👥 People (by mention count):")
        for name, count in sorted(people.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {name:25s}  {count:3d}")
        print()

    projects = patterns.get("entities", {}).get("projects", {})
    if projects:
        print("📁 Projects:")
        for name, count in sorted(projects.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {name:25s}  {count:3d}")

    print(f"\nUpdated: {patterns.get('updated_at', 'never')}")


def cmd_status(args):
    """Show daemon status."""
    config = get_config(args.config)
    state = load_state(config.state_dir)
    patterns = load_patterns(config.state_dir)
    whisper_path = config.state_dir / "whisper.md"

    total = len(state.get("sessions", {}))
    digested = sum(1 for s in state.get("sessions", {}).values() if s.get("digested"))
    pending = total - digested

    print("═══ SKWhisper Status ═══\n")
    print(f"Sessions tracked:    {total}")
    print(f"Sessions digested:   {digested}")
    print(f"Sessions pending:    {pending}")
    print(f"Last run:            {state.get('last_run', 'never')}")
    print(f"Topics tracked:      {len(patterns.get('topics', {}))}")
    print(f"Questions tracked:   {len(patterns.get('questions', {}))}")
    print(f"Whisper file:        {'exists' if whisper_path.exists() else 'not yet generated'}")
    if whisper_path.exists():
        import os
        mtime = os.path.getmtime(whisper_path)
        from datetime import datetime
        print(f"Whisper updated:     {datetime.fromtimestamp(mtime).isoformat()}")


def main():
    parser = argparse.ArgumentParser(
        prog="skwhisper",
        description="SKWhisper — Lumina's subconscious memory layer",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("-c", "--config", default=None, help="Path to skwhisper.toml")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("daemon", help="Run the background daemon")
    sub.add_parser("digest", help="Run one digest cycle")

    curate_p = sub.add_parser("curate", help="Generate fresh whisper context")
    curate_p.add_argument("--stdout", action="store_true", help="Print to stdout instead of file")

    patterns_p = sub.add_parser("patterns", help="Show current patterns")
    patterns_p.add_argument("--json", action="store_true", help="Output as JSON")

    sub.add_parser("status", help="Show daemon status")

    args = parser.parse_args()
    setup_logging(args.verbose)

    commands = {
        "daemon": cmd_daemon,
        "digest": cmd_digest,
        "curate": cmd_curate,
        "patterns": cmd_patterns,
        "status": cmd_status,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

"""SKWhisper CLI entry point."""

import argparse
import asyncio
import logging
import os
import subprocess
import sys
import json
from pathlib import Path

from .config import get_config
from .daemon import run_daemon, run_digest_cycle, run_backlog_digest
from .curator import curate_context
from .patterns import load_patterns, get_hot_topics, get_repeated_questions
from .watcher import load_state, extract_messages


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
    """Run one digest cycle, or process the full backlog."""
    config = get_config(args.config)
    if args.backlog:
        asyncio.run(run_backlog_digest(config, batch_size=args.batch_size))
    else:
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


def _check_daemon_health() -> str:
    """Check if the skwhisper@<agent> systemd user service is active."""
    import subprocess
    agent = os.environ.get("SKCAPSTONE_AGENT", "lumina")
    service = f"skwhisper@{agent}"
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", service],
            capture_output=True, text=True, timeout=5,
        )
        status = result.stdout.strip()
        return status if status else "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "unknown"


def cmd_status(args):
    """Show daemon status with session breakdown and topic distribution."""
    import os
    from datetime import datetime

    config = get_config(args.config)
    state = load_state(config.state_dir)
    sessions = state.get("sessions", {})
    sessions_dir = config.sessions_dir
    whisper_path = config.state_dir / "whisper.md"

    # --- Session breakdown ---
    # Note: legacy state uses digested_at as a status sentinel for non-digested outcomes
    # ("skipped-too-few-messages", "cleaned-missing-file") with digested=True.
    # Real digests have ISO timestamp strings starting with '2'.
    n_digested = 0
    n_pending = 0
    n_skipped = 0
    n_missing = 0
    last_digest_ts = None
    human_digested = 0
    cron_digested = 0
    unknown_digested = 0

    for session_id, s in sessions.items():
        digested_at = s.get("digested_at", "")
        if digested_at == "skipped-too-few-messages":
            n_skipped += 1
        elif digested_at == "cleaned-missing-file":
            n_missing += 1
        elif s.get("digested"):
            # Real digest — has ISO timestamp or no digested_at (older format)
            n_digested += 1
            stype = s.get("session_type", "unknown")
            if stype == "human":
                human_digested += 1
            elif stype == "cron":
                cron_digested += 1
            else:
                unknown_digested += 1
            # Track most recent digest timestamp (ISO strings start with '2')
            if digested_at and digested_at.startswith("2"):
                if last_digest_ts is None or digested_at > last_digest_ts:
                    last_digest_ts = digested_at
        else:
            # Not digested — check if file still exists and has enough messages
            active = sessions_dir / f"{session_id}.jsonl"
            deleted = list(sessions_dir.glob(f"{session_id}.jsonl.deleted.*"))
            archived = list(sessions_dir.glob(f"{session_id}.jsonl.archived.*"))
            file_path = active if active.exists() else (deleted or archived or [None])[0]

            if file_path is None:
                n_missing += 1
            else:
                msg_count = s.get("message_count", 0)
                if msg_count < config.min_messages:
                    n_skipped += 1
                else:
                    n_pending += 1

    # Also count files on disk not yet tracked in state
    for path in sessions_dir.glob("*.jsonl"):
        sid = path.stem
        if sid not in sessions:
            n_pending += 1

    # --- Daemon health ---
    daemon_status = _check_daemon_health()

    # --- Display ---
    print("═══ SKWhisper Status ═══\n")

    # Session breakdown
    total = len(sessions)
    print(f"Sessions tracked:    {total}")
    print(f"  Digested:          {n_digested}")
    if n_digested:
        type_parts = []
        if human_digested:
            type_parts.append(f"{human_digested} human")
        if cron_digested:
            type_parts.append(f"{cron_digested} cron")
        if unknown_digested:
            type_parts.append(f"{unknown_digested} unclassified")
        if type_parts:
            print(f"    ({', '.join(type_parts)})")
    print(f"  Pending:           {n_pending}")
    print(f"  Skipped (<{config.min_messages} msgs): {n_skipped}")
    print(f"  Missing file:      {n_missing}")
    print()

    # Timing
    print(f"Last state update:   {state.get('last_run', 'never')}")
    print(f"Last digest:         {last_digest_ts or 'never'}")
    print()

    # Whisper file
    if whisper_path.exists():
        mtime = os.path.getmtime(whisper_path)
        whisper_age = datetime.fromtimestamp(mtime).isoformat()
        print(f"Whisper updated:     {whisper_age}")
    else:
        print("Whisper file:        not yet generated")
    print()

    # Daemon health
    daemon_icon = "✓" if daemon_status == "active" else "✗"
    print(f"Daemon (systemd):    {daemon_icon} {daemon_status}")
    print()

    # Topic distribution: top 5 human vs top 5 cron
    human_topics = get_hot_topics(config.state_dir, top_n=5, session_type="human")
    cron_topics = get_hot_topics(config.state_dir, top_n=5, session_type="cron")

    if human_topics or cron_topics:
        print("Top Topics by Session Type:")
        print()
        if human_topics:
            print("  Human:")
            for t in human_topics:
                print(f"    {t['topic']:30s}  {t['count']:3d}x")
        if cron_topics:
            print("  Cron:")
            for t in cron_topics:
                print(f"    {t['topic']:30s}  {t['count']:3d}x")
        print()

    # Overall pattern stats
    patterns = load_patterns(config.state_dir)
    print(f"Topics tracked:      {len(patterns.get('topics', {}))}")
    print(f"Questions tracked:   {len(patterns.get('questions', {}))}")
    print(f"Patterns updated:    {patterns.get('updated_at', 'never')}")


def cmd_install(args):
    """Install the systemd user service template and enable it for an agent."""
    agent = getattr(args, "agent", None) or os.environ.get("SKCAPSTONE_AGENT", "lumina")
    home = Path.home()
    service_dir = home / ".config" / "systemd" / "user"
    service_dir.mkdir(parents=True, exist_ok=True)

    # Find the skwhisper binary
    skwhisper_bin = Path(sys.argv[0]).resolve()

    # Write the template service file
    template_path = service_dir / "skwhisper@.service"
    template_content = f"""\
[Unit]
Description=SKWhisper — %i agent subconscious memory layer
After=network.target

[Service]
Type=simple
ExecStart={skwhisper_bin} daemon
Environment=SKCAPSTONE_AGENT=%i
Environment=HOME={home}
Restart=on-failure
RestartSec=30
StandardOutput=append:{home}/.skcapstone/agents/%i/skwhisper/daemon.log
StandardError=append:{home}/.skcapstone/agents/%i/skwhisper/daemon.log

[Install]
WantedBy=default.target
"""
    template_path.write_text(template_content)
    print(f"→ Wrote service template: {template_path}")

    # Ensure agent state dir exists
    state_dir = home / ".skcapstone" / "agents" / agent / "skwhisper"
    state_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir = home / ".skcapstone" / "agents" / agent / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    print(f"→ Ensured state/sessions dirs for agent '{agent}'")

    # Reload systemd and enable the instance
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", f"skwhisper@{agent}"], check=True)
    print(f"→ Enabled skwhisper@{agent}")

    if getattr(args, "start", False):
        subprocess.run(["systemctl", "--user", "start", f"skwhisper@{agent}"], check=True)
        print(f"→ Started skwhisper@{agent}")
    else:
        print(f"\nRun to start:")
        print(f"  systemctl --user start skwhisper@{agent}")

    print(f"\nLogs:")
    print(f"  tail -f {state_dir}/daemon.log")
    print(f"\nStatus:")
    print(f"  SKCAPSTONE_AGENT={agent} skwhisper status")


def main():
    parser = argparse.ArgumentParser(
        prog="skwhisper",
        description="SKWhisper — multi-agent subconscious memory layer",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("-c", "--config", default=None, help="Path to skwhisper.toml")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("daemon", help="Run the background daemon")

    digest_p = sub.add_parser("digest", help="Run one digest cycle (or full backlog)")
    digest_p.add_argument(
        "--backlog", action="store_true",
        help="Process all undigested sessions (ignores idle_threshold)",
    )
    digest_p.add_argument(
        "--batch-size", type=int, default=10, metavar="N",
        help="Sessions per batch when using --backlog (default: 10)",
    )

    curate_p = sub.add_parser("curate", help="Generate fresh whisper context")
    curate_p.add_argument("--stdout", action="store_true", help="Print to stdout instead of file")

    patterns_p = sub.add_parser("patterns", help="Show current patterns")
    patterns_p.add_argument("--json", action="store_true", help="Output as JSON")

    sub.add_parser("status", help="Show daemon status")

    install_p = sub.add_parser("install", help="Install and enable the systemd user service for an agent")
    install_p.add_argument("--agent", default=None, help="Agent name (default: $SKCAPSTONE_AGENT or 'lumina')")
    install_p.add_argument("--start", action="store_true", help="Start the service after installing")

    args = parser.parse_args()
    setup_logging(args.verbose)

    commands = {
        "daemon": cmd_daemon,
        "digest": cmd_digest,
        "curate": cmd_curate,
        "patterns": cmd_patterns,
        "status": cmd_status,
        "install": cmd_install,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

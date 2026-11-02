#!/usr/bin/env bash
# Install SKWhisper hooks into Claude Code settings.json (Linux / macOS).
#
# Default: if skmemory is installed, delegate to `skmemory hooks install`,
# which already injects a distilled whisper.md in its budgeted ritual and runs
# the skwhisper digest at session end. Installing skwhisper's own inject hook
# on top of that would inject the subconscious context twice.
#
# Without skmemory (standalone skwhisper):
#   install-hooks.sh                 # SessionEnd digest hook only
#   install-hooks.sh --with-inject   # also inject whisper.md at SessionStart
#   install-hooks.sh --standalone    # ignore skmemory even if present
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_SETTINGS="${HOME}/.claude/settings.json"
WITH_INJECT=0
STANDALONE=0
for a in "$@"; do
  case "$a" in
    --with-inject) WITH_INJECT=1 ;;
    --standalone) STANDALONE=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
  esac
done

if [[ $STANDALONE -eq 0 ]] && command -v skmemory >/dev/null 2>&1 \
   && skmemory hooks --help >/dev/null 2>&1; then
  echo "skmemory detected: installing via 'skmemory hooks install --harness claude'"
  exec skmemory hooks install --harness claude
fi

chmod +x "${SCRIPT_DIR}/skwhisper-inject.sh" "${SCRIPT_DIR}/skwhisper-save.sh"
if [[ ! -f "$CLAUDE_SETTINGS" ]]; then
  echo "Claude Code settings not found at ${CLAUDE_SETTINGS}; run 'claude' once first." >&2
  exit 1
fi
cp "$CLAUDE_SETTINGS" "${CLAUDE_SETTINGS}.bak.$(date +%Y%m%d%H%M%S)"

SETTINGS="$CLAUDE_SETTINGS" INJECT="${SCRIPT_DIR}/skwhisper-inject.sh" \
SAVE="${SCRIPT_DIR}/skwhisper-save.sh" WITH_INJECT="$WITH_INJECT" python3 - <<'PYEOF'
import json, os

path = os.environ["SETTINGS"]
with open(path) as f:
    settings = json.load(f)
hooks = settings.setdefault("hooks", {})

def present(event, suffix):
    return any(
        h.get("command", "").endswith(suffix)
        for g in hooks.get(event, []) for h in g.get("hooks", [])
    )

def add(event, cmd, timeout, suffix):
    if present(event, suffix):
        print(f"skwhisper hook already in {event} (skipped)")
        return
    hooks.setdefault(event, []).append(
        {"matcher": "", "hooks": [{"type": "command", "command": cmd, "timeout": timeout}]}
    )
    print(f"added skwhisper hook to {event}")

add("SessionEnd", os.environ["SAVE"], 30, "skwhisper-save.sh")
if os.environ["WITH_INJECT"] == "1":
    add("SessionStart", os.environ["INJECT"], 15, "skwhisper-inject.sh")

with open(path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
PYEOF
echo "done. Hooks resolve skwhisper via PATH (pip install) or python3 -m skwhisper."

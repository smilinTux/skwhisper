#!/usr/bin/env bash
# SKWhisper Session Save Hook for Claude Code (Linux / macOS)
# Triggers SKWhisper digest after session ends to capture new conversation.
#
# Hook type: SessionEnd
# Input (stdin): JSON with session_id, reason
# Exit 0 always — never block session end
set -euo pipefail

AGENT="${SKCAPSTONE_AGENT:-lumina}"
SKWHISPER_DIR=""

for D in "${HOME}/clawd/projects/skwhisper" "${HOME}/projects/skwhisper" "${HOME}/skwhisper"; do
  [ -f "${D}/skwhisper/__main__.py" ] && SKWHISPER_DIR="$D" && break
done

[ -z "$SKWHISPER_DIR" ] && exit 0

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")
REASON=$(echo "$INPUT" | jq -r '.reason // "unknown"' 2>/dev/null || echo "unknown")
SHORT_SID="${SESSION_ID:0:8}"

# Fire-and-forget a SINGLE digest cycle, fully detached. Three guards prevent
# the pile-up that wedged sessions on close (2026-06-17):
#   - flock -n  : single-flight. If a digest is already running for this agent,
#                 skip this cycle instead of stacking another concurrent one.
#   - timeout   : a wedged Ollama call can't hang forever (digest 180s, curate 120s).
#   - setsid + </dev/null >/dev/null 2>&1 : fully detach so we DON'T inherit
#                 Claude Code's stdout pipe — holding it open was what made the
#                 session "hang" on close until the digest finished.
LOCK="/tmp/skwhisper-digest-${AGENT}.lock"
DETACH=""; command -v setsid >/dev/null 2>&1 && DETACH="setsid"
$DETACH bash -c '
  exec 9>"$0" || exit 0
  flock -n 9 || exit 0          # another digest already running for this agent — skip
  cd "$1" || exit 0
  export PYTHONPATH="$1"
  TO=""; command -v timeout >/dev/null 2>&1 && TO="timeout"
  ${TO:+$TO 180} python3 -m skwhisper digest
  ${TO:+$TO 120} python3 -m skwhisper curate
' "$LOCK" "$SKWHISPER_DIR" </dev/null >/dev/null 2>&1 &

exit 0

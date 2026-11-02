#!/usr/bin/env bash
# SKWhisper context injection hook (standalone use only).
#
# When skmemory is installed, do NOT install this: `skmemory hooks install`
# wires a budgeted ritual that already includes a distilled whisper.md, and
# running both injects the subconscious context twice.
#
# Hook type: SessionStart. Output (stdout) is injected into the context.
# Exit 0 always, never blocks session start.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_resolve.sh"

[[ -z "$AGENT" ]] && { echo "--- SKWHISPER: no agent resolved (set SKAGENT) ---"; exit 0; }
WHISPER_FILE="$SK_HOME/agents/${AGENT}/skwhisper/whisper.md"

# Stale (>2h): refresh in the background, fully detached.
if [[ -f "$WHISPER_FILE" && ${#SKWHISPER_CMD[@]} -gt 0 ]]; then
  FILE_AGE=$(( $(date +%s) - $(stat -c %Y "$WHISPER_FILE" 2>/dev/null || stat -f %m "$WHISPER_FILE" 2>/dev/null || echo 0) ))
  if [[ "$FILE_AGE" -gt 7200 ]]; then
    DETACH=""; command -v setsid >/dev/null 2>&1 && DETACH="setsid"
    $DETACH "${SKWHISPER_CMD[@]}" curate </dev/null >/dev/null 2>&1 &
  fi
fi

if [[ -s "$WHISPER_FILE" ]]; then
  echo "--- SKWHISPER SUBCONSCIOUS CONTEXT ---"
  echo "Agent: ${AGENT}"
  echo "Source: ${WHISPER_FILE}"
  echo
  head -c 8000 "$WHISPER_FILE"
  echo
  echo "--- END SKWHISPER ---"
else
  echo "--- SKWHISPER: No whisper.md available for agent ${AGENT} ---"
fi
exit 0

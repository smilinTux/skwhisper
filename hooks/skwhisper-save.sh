#!/usr/bin/env bash
# SKWhisper session save hook: digest + curate after a session ends.
#
# skmemory >= the `skmemory hook` release already triggers this digest from
# its session-end hook, so `skmemory hooks install` removes this entry.
#
# Hook type: SessionEnd. Exit 0 always, never blocks session end.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_resolve.sh"

cat >/dev/null  # drain stdin JSON
[[ ${#SKWHISPER_CMD[@]} -eq 0 || -z "$AGENT" ]] && exit 0

# Fire-and-forget a SINGLE digest cycle, fully detached (2026-06-17 lessons):
#   flock -n : single-flight per agent, skip instead of stacking digests
#   timeout  : a wedged embed/LLM call cannot hang forever
#   setsid + redirects : do not inherit the harness stdout pipe
LOCK="${TMPDIR:-/tmp}/skwhisper-digest-${AGENT}.lock"
DETACH=""; command -v setsid >/dev/null 2>&1 && DETACH="setsid"
$DETACH bash -c '
  exec 9>"$1" || exit 0
  flock -n 9 || exit 0
  shift
  TO=""; command -v timeout >/dev/null 2>&1 && TO="timeout"
  ${TO:+$TO 180} "$@" digest
  ${TO:+$TO 120} "$@" curate
' _ "$LOCK" "${SKWHISPER_CMD[@]}" </dev/null >/dev/null 2>&1 &
exit 0

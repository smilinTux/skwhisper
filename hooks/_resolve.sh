# Sourced by the skwhisper hook scripts. Resolves the agent and a way to run
# skwhisper WITHOUT assuming any repo checkout path or cwd:
#   1. a `skwhisper` console script on PATH (pip install / ~/.skenv shim)
#   2. `python3 -m skwhisper` if the package is importable
#   3. legacy: $SKWHISPER_REPO checkout (opt-in, for dev setups)
# Sets SKWHISPER_CMD (a bash array). Empty array means skwhisper is unavailable.

SK_HOME="${SKCAPSTONE_HOME:-$HOME/.skcapstone}"
AGENT="${SKAGENT:-${SKCAPSTONE_AGENT:-${SKMEMORY_AGENT:-${SK_DEFAULT_AGENT:-}}}}"
if [[ -z "$AGENT" && -d "$SK_HOME/agents" ]]; then
  mapfile -t _SK_AGENTS < <(find "$SK_HOME/agents" -mindepth 1 -maxdepth 1 -type d ! -name '*-template' ! -name '.*' -printf '%f\n' 2>/dev/null | sort)
  [[ ${#_SK_AGENTS[@]} -eq 1 ]] && AGENT="${_SK_AGENTS[0]}"
fi
export SKAGENT="${AGENT}" SKCAPSTONE_AGENT="${AGENT}"

SKWHISPER_CMD=()
for _c in skwhisper "$HOME/.skenv/bin/skwhisper" "$HOME/.local/bin/skwhisper"; do
  if command -v "$_c" >/dev/null 2>&1; then SKWHISPER_CMD=("$(command -v "$_c")"); break; fi
done
if [[ ${#SKWHISPER_CMD[@]} -eq 0 ]]; then
  for _py in python3 "$HOME/.skenv/bin/python"; do
    if command -v "$_py" >/dev/null 2>&1 && "$_py" -c 'import skwhisper' >/dev/null 2>&1; then
      SKWHISPER_CMD=("$(command -v "$_py")" -m skwhisper); break
    fi
  done
fi
if [[ ${#SKWHISPER_CMD[@]} -eq 0 && -n "${SKWHISPER_REPO:-}" && -f "$SKWHISPER_REPO/skwhisper/__main__.py" ]]; then
  export PYTHONPATH="$SKWHISPER_REPO${PYTHONPATH:+:$PYTHONPATH}"
  SKWHISPER_CMD=(python3 -m skwhisper)
fi

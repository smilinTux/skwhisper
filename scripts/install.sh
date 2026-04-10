#!/bin/bash
# SKWhisper Installation Script
# Usage: SKCAPSTONE_AGENT=jarvis ./scripts/install.sh [--start]
set -e

AGENT="${SKCAPSTONE_AGENT:-lumina}"
START_FLAG=""

for arg in "$@"; do
    case "$arg" in
        --start) START_FLAG="--start" ;;
        --agent=*) AGENT="${arg#*=}" ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
STATE_DIR="$HOME/.skcapstone/agents/$AGENT/skwhisper"
CONFIG_DIR="$HOME/.skcapstone/agents/$AGENT/config"
SESSIONS_DIR="$HOME/.skcapstone/agents/$AGENT/sessions"

echo "═══ SKWhisper Installer ═══"
echo "Agent: $AGENT"
echo ""

# 1. Install package
echo "→ Installing skwhisper package..."
pip install --user -e "$PROJECT_DIR" --quiet
echo "  Installed: $(which skwhisper)"

# 2. Create agent directories
echo "→ Creating agent directories..."
mkdir -p "$STATE_DIR" "$SESSIONS_DIR"
echo "  State dir:    $STATE_DIR"
echo "  Sessions dir: $SESSIONS_DIR"

# 3. Write per-agent config if not present
if [ ! -f "$CONFIG_DIR/skwhisper.toml" ]; then
    mkdir -p "$CONFIG_DIR"
    AGENT_CAP="$(python3 -c "print('$AGENT'.capitalize())")"
    cat > "$CONFIG_DIR/skwhisper.toml" <<TOML
[paths]
sessions_dir = "~/.skcapstone/agents/$AGENT/sessions"
memory_dir = "~/.skcapstone/agents/$AGENT/memory"
state_dir = "~/.skcapstone/agents/$AGENT/skwhisper"

[agent]
user_label = "User"
agent_label = "$AGENT_CAP"

[ollama]
ollama_url = "http://localhost:11434"
embed_model = "bge-large"
summarize_model = "llama3.2"

[qdrant]
qdrant_url = ""
qdrant_api_key = ""
qdrant_collection = "$AGENT-memory"

[watcher]
poll_interval = 60
idle_threshold = 300
min_messages = 5

[curator]
curate_interval = 1800
top_k = 10
max_whisper_tokens = 2000
TOML
    echo "  Wrote config: $CONFIG_DIR/skwhisper.toml"
    echo "  ⚠  Edit $CONFIG_DIR/skwhisper.toml to set your Ollama/Qdrant endpoints."
else
    echo "  Config exists: $CONFIG_DIR/skwhisper.toml (skipped)"
fi

# 4. Verify Python deps
echo ""
echo "→ Checking dependencies..."
python3 -c "import httpx; print('  httpx: OK')"
python3 -c "import tomllib; print('  tomllib: OK')"

# 5. Test Ollama connectivity (non-fatal)
echo ""
echo "→ Testing connectivity..."
OLLAMA_URL="$(python3 -c "
import tomllib, pathlib, os
p = pathlib.Path(os.path.expanduser('$CONFIG_DIR/skwhisper.toml'))
d = tomllib.loads(p.read_text()) if p.exists() else {}
print(d.get('ollama', {}).get('ollama_url', 'http://localhost:11434'))
" 2>/dev/null || echo 'http://localhost:11434')"
if curl -s -o /dev/null -w "%{http_code}" "$OLLAMA_URL/api/tags" 2>/dev/null | grep -q 200; then
    echo "  Ollama ($OLLAMA_URL): OK"
else
    echo "  ⚠  Ollama not reachable at $OLLAMA_URL — update config before starting daemon"
fi

# 6. Install and enable systemd service via CLI
echo ""
echo "→ Installing systemd user service..."
SKCAPSTONE_AGENT="$AGENT" skwhisper install --agent "$AGENT" $START_FLAG

echo ""
echo "═══ Installation Complete ═══"
echo ""
echo "Commands:"
echo "  SKCAPSTONE_AGENT=$AGENT skwhisper status"
echo "  SKCAPSTONE_AGENT=$AGENT skwhisper digest"
echo "  SKCAPSTONE_AGENT=$AGENT skwhisper curate"
echo "  systemctl --user status skwhisper@$AGENT"
echo "  tail -f $STATE_DIR/daemon.log"

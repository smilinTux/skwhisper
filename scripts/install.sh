#!/bin/bash
# SKWhisper Installation Script
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
STATE_DIR="$HOME/.skcapstone/agents/lumina/skwhisper"

echo "═══ SKWhisper Installer ═══"
echo ""

# 1. Create state directory
echo "→ Creating state directory..."
mkdir -p "$STATE_DIR"

# 2. Verify Python
echo "→ Checking Python..."
python3 --version
python3 -c "import httpx; print('  httpx: OK')"
python3 -c "import tomllib; print('  tomllib: OK')"
echo ""

# 3. Test connectivity
echo "→ Testing Ollama connectivity..."
if curl -s -o /dev/null -w "%{http_code}" http://192.168.0.100:11434/api/tags | grep -q 200; then
    echo "  Ollama: OK"
else
    echo "  ⚠ Ollama not reachable at 192.168.0.100:11434"
fi

echo "→ Testing Qdrant connectivity..."
if curl -sk -o /dev/null -w "%{http_code}" -H "api-key: e4hPZkg0Q899N7x0FmgNPT+s8QvY7a/LOnl0go1QCIQ" https://skvector.skstack01.douno.it/collections | grep -q 200; then
    echo "  Qdrant: OK"
else
    echo "  ⚠ Qdrant not reachable"
fi
echo ""

# 4. Quick test run
echo "→ Running status check..."
cd "$PROJECT_DIR"
PYTHONPATH="$PROJECT_DIR" python3 -m skwhisper status
echo ""

# 5. Install systemd service
echo "→ Installing systemd user service..."
mkdir -p "$HOME/.config/systemd/user"
cp "$PROJECT_DIR/skwhisper.service" "$HOME/.config/systemd/user/skwhisper.service"
systemctl --user daemon-reload
echo "  Service installed."
echo ""

echo "═══ Installation Complete ═══"
echo ""
echo "Commands:"
echo "  # Test digest (one-shot):"
echo "  cd $PROJECT_DIR && PYTHONPATH=. python3 -m skwhisper digest"
echo ""
echo "  # Generate whisper context:"
echo "  cd $PROJECT_DIR && PYTHONPATH=. python3 -m skwhisper curate --stdout"
echo ""
echo "  # Start daemon:"
echo "  systemctl --user start skwhisper"
echo "  systemctl --user enable skwhisper"
echo ""
echo "  # Check logs:"
echo "  tail -f $STATE_DIR/daemon.log"

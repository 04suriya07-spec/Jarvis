#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
#  Javris Universal Start Script
#  Usage:
#    ./start.sh              — server + voice
#    ./start.sh chat         — terminal chat only
#    ./start.sh voice        — voice only
#    ./start.sh gesture      — server + voice + gesture
#    ./start.sh live         — Gemini Live real-time mode
# ─────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JAVRIS_DIR="$(dirname "$SCRIPT_DIR")"

CYAN='\033[0;36m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${CYAN}  J A V R I S${NC}  — starting..."

# Activate virtual environment
VENV="$JAVRIS_DIR/.venv/bin/activate"
if [ -f "$VENV" ]; then
  source "$VENV"
else
  echo "No .venv found — using system Python"
fi

cd "$JAVRIS_DIR"

MODE="${1:-serve}"

case "$MODE" in
  serve|"")
    echo -e "${GREEN}Mode: Server + Voice${NC}"
    exec python main.py serve --voice
    ;;
  chat)
    echo -e "${GREEN}Mode: Terminal Chat${NC}"
    exec python main.py chat
    ;;
  voice)
    echo -e "${GREEN}Mode: Voice Only${NC}"
    exec python main.py voice
    ;;
  gesture)
    echo -e "${GREEN}Mode: Server + Voice + Gesture${NC}"
    exec python main.py serve --voice --gesture
    ;;
  live)
    echo -e "${GREEN}Mode: Gemini Live${NC}"
    exec python main.py live
    ;;
  *)
    echo "Unknown mode: $MODE"
    echo "Valid: serve (default), chat, voice, gesture, live"
    exit 1
    ;;
esac

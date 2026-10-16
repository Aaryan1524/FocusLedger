#!/bin/bash
# FocusLedger — One-command bootstrap, preflight, and launcher.
#
# Usage:
#   ./start.sh               # Set up everything (if needed) and launch the Notch UI
#   ./start.sh --quick       # Launch in Quick Test mode (1-min checkpoints, 2s polling)
#   ./start.sh --onboarding  # Launch directly into the Notch First-Run Onboarding Wizard
#   ./start.sh --verify      # Run the 14-point automated preflight verification suite
#   ./start.sh --demo-report # Render and open the full sample daily report immediately
set -euo pipefail
cd "$(dirname "$0")"

GREEN="\033[32m"
YELLOW="\033[33m"
CYAN="\033[36m"
BOLD="\033[1m"
RESET="\033[0m"

echo -e "${BOLD}FocusLedger${RESET} · 100% Local On-Device Work Session Tracker"
echo "------------------------------------------------------------"

# 1. Python virtual environment + dependencies
if [ ! -x "venv/bin/python" ]; then
  echo -e "${CYAN}==> Creating Python virtual environment (venv)...${RESET}"
  python3 -m venv venv
  ./venv/bin/pip install -q -r requirements.txt
else
  # Fast check that core packages import cleanly
  if ! ./venv/bin/python -c "import mss, Quartz, Vision, requests, jinja2, AppKit" >/dev/null 2>&1; then
    echo -e "${CYAN}==> Installing Python dependencies...${RESET}"
    ./venv/bin/pip install -q -r requirements.txt
  fi
fi

# 2. Build on-device voice helper (Dictate.app) if missing
if [ ! -x "Dictate.app/Contents/MacOS/dictate" ]; then
  echo -e "${CYAN}==> Building on-device Speech helper (Dictate.app)...${RESET}"
  ./build_dictate.sh
fi

# 3. Build macOS app bundle (FocusLedger.app) if missing
if [ ! -x "FocusLedger.app/Contents/MacOS/FocusLedger" ]; then
  echo -e "${CYAN}==> Building macOS application bundle (FocusLedger.app)...${RESET}"
  ./build_app.sh
fi

# 4. Ensure Ollama is running & check Gemma model
MODEL="${FL_MODEL:-gemma3:12b}"
if command -v ollama >/dev/null 2>&1; then
  if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo -e "${CYAN}==> Starting local Ollama server...${RESET}"
    nohup ollama serve >/dev/null 2>&1 &
    sleep 2
  fi
  if ! ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then
    echo -e "${YELLOW}==> Pulling on-device model $MODEL via Ollama...${RESET}"
    ollama pull "$MODEL"
  fi
else
  echo -e "${YELLOW}⚠ Ollama CLI not found in PATH. Install from https://ollama.com if needed.${RESET}"
fi

# 5. Handle CLI flags
MODE="${1:-}"
if [ "$MODE" = "--verify" ] || [ "$MODE" = "--check" ]; then
  exec ./venv/bin/python verify_setup.py
elif [ "$MODE" = "--demo-report" ]; then
  ./venv/bin/python seed.py --out ledger.demo.jsonl
  exec ./venv/bin/python report.py ledger.demo.jsonl --out report.demo.html --open
elif [ "$MODE" = "--quick" ]; then
  echo -e "${GREEN}==> Launching FocusLedger Notch in ⚡ Quick Test Mode (1-min checkpoints)...${RESET}"
  echo "    Look at the top of your screen (under the notch)!"
  pkill -f "notch.py" 2>/dev/null || true
  FL_DEV=1 exec ./venv/bin/python notch.py
elif [ "$MODE" = "--onboarding" ]; then
  echo -e "${GREEN}==> Launching FocusLedger Notch with First-Run Onboarding Wizard...${RESET}"
  pkill -f "notch.py" 2>/dev/null || true
  FL_ONBOARDING=1 exec ./venv/bin/python notch.py --onboarding
else
  echo -e "${GREEN}==> Launching FocusLedger Notch Companion...${RESET}"
  echo "    Click the notch at the top of your screen to interact."
  echo "    (Tip: run './start.sh --quick' for 1-minute test checkpoints, or './start.sh --onboarding' to view setup wizard)"
  pkill -f "notch.py" 2>/dev/null || true
  exec ./venv/bin/python notch.py "$@"
fi

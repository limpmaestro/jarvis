#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
#  Jarvis – Full Installer
#  Usage:  ./scripts/install.sh [--yes]
# ──────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

step()  { printf "\n${BOLD}${CYAN}[%s] %s${NC}\n" "$1" "$2"; }
ok()    { printf "  ${GREEN}✓${NC}  %s\n" "$*"; }
warn()  { printf "  ${YELLOW}!${NC}  %s\n" "$*"; }
fail()  { printf "  ${RED}✗${NC}  %s\n" "$*"; exit 1; }

YES_FLAG=""
[[ "${1:-}" == "--yes" ]] && YES_FLAG=1

confirm() {
    [[ -n "$YES_FLAG" ]] && return 0
    read -rp "  Continue? [y/N] " ans
    [[ "$ans" =~ ^[Yy] ]] || { echo "Aborted."; exit 1; }
}

# ====================================================================== #
step "1/11" "Running environment audit"
bash scripts/audit.sh || true
echo ""
confirm

# ====================================================================== #
step "2/11" "Installing system dependencies"
sudo apt-get update -qq
sudo apt-get install -y -qq \
    build-essential python3-dev portaudio19-dev libportaudio2 \
    ffmpeg libegl1 libgl1 libglib2.0-0 \
    age jq curl git ripgrep zstd >/dev/null
ok "system deps installed"

# ====================================================================== #
step "3/11" "Ensuring Ollama is installed"
if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
    ok "ollama installed"
else
    ok "ollama already installed: $(ollama --version 2>&1)"
fi

# Start ollama serve in the background if not running.
if ! curl -sf http://127.0.0.1:11434/ >/dev/null 2>&1; then
    warn "Starting 'ollama serve' in the background..."
    nohup ollama serve >/dev/null 2>&1 &
    sleep 3
fi

# ====================================================================== #
step "4/11" "Setting up Python environment (uv)"
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Force Python 3.11 — pyproject.toml caps at <3.13 and several deps
# (tflite-runtime via openwakeword, some chromadb wheels) have no cp312 wheels.
# uv downloads a managed Python interpreter if the system one is wrong.
uv python install 3.11 >/dev/null
uv venv --python 3.11 .venv

# Core sync (no [wake] extra — tflite-runtime has no cp312 wheels and even on
# 3.11 it sometimes fails on aarch64/odd glibc; we try it best-effort below).
uv sync --python 3.11
ok "Python venv ready at .venv/ (Python 3.11)"

# Wake-word is optional. Try to install; tolerate failure.
if uv pip install --python .venv/bin/python "openwakeword>=0.6.0" 2>/dev/null; then
    ok "wake-word ([wake] extra) installed"
else
    warn "[wake] extra failed to install — push-to-talk (\$JARVIS_PTT_HOTKEY, default F8) still works"
fi

# ====================================================================== #
step "5/11" "Pulling Ollama models"
ollama pull qwen2.5:14b-instruct-q4_K_M || warn "Pull failed — check VRAM / network"
ollama pull nomic-embed-text:v1.5 || warn "Embed model pull failed"
ok "models pulled"

# ====================================================================== #
step "6/11" "Creating Jarvis Modelfile"
ollama create jarvis -f models/Jarvis.Modelfile 2>/dev/null && ok "jarvis model created" || warn "jarvis model create failed — continuing"

# ====================================================================== #
step "7/11" "Downloading Piper TTS voices"
VOICES_DIR="assets/voices"
mkdir -p "$VOICES_DIR"

download_voice() {
    local name="$1"
    local quality="$2"
    local lang="$3"
    local base_url="https://huggingface.co/rhasspy/piper-voices/resolve/main/${lang}/${name}/${quality}"
    if [ ! -f "$VOICES_DIR/${name}-${quality}.onnx" ]; then
        echo "  Downloading ${name}-${quality}..."
        curl -fsSL -o "$VOICES_DIR/${name}-${quality}.onnx" \
            "${base_url}/${name}-${quality}.onnx" 2>/dev/null || warn "download failed: ${name}-${quality}.onnx"
        curl -fsSL -o "$VOICES_DIR/${name}-${quality}.onnx.json" \
            "${base_url}/${name}-${quality}.onnx.json" 2>/dev/null || true
    fi
}

download_voice "sv_SE-nst" "medium" "sv/sv_SE"
download_voice "en_US-amy" "medium" "en/en_US"
ok "voices ready"

# ====================================================================== #
step "8/11" "Initialising vault + bridge HMAC key"
STATE_DIR="${HOME}/.jarvis/state"
mkdir -p "$STATE_DIR"

if [ ! -f "$STATE_DIR/bridge.hmac" ]; then
    python3 -c "import secrets; print(secrets.token_hex(32))" > "$STATE_DIR/bridge.hmac"
    chmod 600 "$STATE_DIR/bridge.hmac"
    ok "bridge HMAC key generated"
else
    ok "bridge HMAC key already exists"
fi

# Initialise vault via the CLI (best-effort).
.venv/bin/jarvis vault init 2>/dev/null && ok "vault initialised" || warn "vault init skipped (keyring may need dbus)"

# ====================================================================== #
step "9/11" "Installing systemd user service"
SVC_DIR="${HOME}/.config/systemd/user"
mkdir -p "$SVC_DIR"
cp services/systemd/jarvis-core.service "$SVC_DIR/"
systemctl --user daemon-reload
systemctl --user enable jarvis-core.service
ok "jarvis-core.service enabled"

# ====================================================================== #
step "10/11" "Setting up Windows bridge (cross-call)"
if command -v powershell.exe &>/dev/null; then
    BRIDGE_KEY=$(cat "$STATE_DIR/bridge.hmac")
    WIN_USER=$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r\n')
    WIN_APPDATA=$(cmd.exe /c "echo %LOCALAPPDATA%" 2>/dev/null | tr -d '\r\n')
    WIN_JARVIS_DIR="$WIN_APPDATA\\jarvis"

    powershell.exe -Command "
        New-Item -ItemType Directory -Force -Path '$WIN_JARVIS_DIR' | Out-Null
        Set-Content -Path '$WIN_JARVIS_DIR\\bridge.key' -Value '$BRIDGE_KEY'
        Write-Host 'Bridge key written to $WIN_JARVIS_DIR\\bridge.key'
    " 2>/dev/null || warn "bridge key write failed — you may need to do this manually"

    # Register Task Scheduler entry (bridge exe must be built separately).
    ok "Windows bridge key provisioned"
    warn "Build jarvis-bridge.exe (on Windows): cd services/windows-bridge && pip install -r requirements.txt && pyinstaller --onefile bridge.py"
    warn "Then add it to Task Scheduler → Logon trigger → jarvis-bridge.exe"
else
    warn "powershell.exe not found — skipping Windows bridge setup"
fi

# ====================================================================== #
step "11/11" "Starting Jarvis core"
systemctl --user start jarvis-core.service && ok "jarvis-core started" || warn "start failed (check: journalctl --user -u jarvis-core)"
echo ""
journalctl --user -u jarvis-core --no-pager -n 10 2>/dev/null || true

echo ""
printf "${BOLD}${GREEN}Installation complete!${NC}\n"
printf "Try:  ${CYAN}jarvis ask 'Hello, Jarvis.'${NC}\n"
printf "      ${CYAN}jarvis say 'Systems online.'${NC}\n"
printf "      ${CYAN}jarvis hud${NC}\n"
printf "      ${CYAN}jarvis doctor${NC}\n\n"

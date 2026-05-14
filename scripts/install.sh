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
    age jq curl git ripgrep zstd alsa-utils >/dev/null
ok "system deps installed"

# ====================================================================== #
step "3/11" "Ensuring Ollama is reachable"

# Resolve where the Ollama daemon should be reachable.
# Order: explicit OLLAMA_HOST env > WSL loopback default.
OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
export OLLAMA_HOST

# Globally-usable Ollama CLI wrapper. Prefers native Linux binary, falls
# back to Windows ollama.exe (e.g. user installed Ollama on Windows, with
# the install dir under %LOCALAPPDATA% or a OneDrive-redirected folder).
find_windows_ollama_exe() {
    if command -v ollama.exe &>/dev/null; then
        command -v ollama.exe
        return 0
    fi
    local candidate
    for candidate in \
        /mnt/c/Users/*/AppData/Local/Programs/Ollama/ollama.exe \
        /mnt/c/Users/*/OneDrive*/AppData/Local/Programs/Ollama/ollama.exe \
        /mnt/c/Program*Files*/Ollama/ollama.exe; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

OLLAMA_WIN_EXE=""
OLLAMA_MODE=""   # one of: skip | reachable | linux | windows | install

if [[ "${JARVIS_SKIP_OLLAMA_INSTALL:-}" == "1" ]]; then
    OLLAMA_MODE="skip"
    warn "JARVIS_SKIP_OLLAMA_INSTALL=1 — not touching Ollama"
elif curl -sf --max-time 2 "$OLLAMA_HOST" >/dev/null 2>&1; then
    OLLAMA_MODE="reachable"
    ok "ollama daemon already reachable at $OLLAMA_HOST"
elif command -v ollama &>/dev/null; then
    OLLAMA_MODE="linux"
    ok "ollama (linux) already installed: $(ollama --version 2>&1 | head -1)"
elif OLLAMA_WIN_EXE=$(find_windows_ollama_exe); then
    OLLAMA_MODE="windows"
    ok "found Windows-side Ollama: $OLLAMA_WIN_EXE"
    # Try the WSL gateway as the daemon host (works in default NAT mode).
    WIN_HOST_IP=$(ip route show default 2>/dev/null | awk '/default/ {print $3}' | head -1)
    if [[ -n "$WIN_HOST_IP" ]] && curl -sf --max-time 2 "http://${WIN_HOST_IP}:11434" >/dev/null 2>&1; then
        OLLAMA_HOST="http://${WIN_HOST_IP}:11434"
        export OLLAMA_HOST
        ok "routing to Windows Ollama at $OLLAMA_HOST"
    elif curl -sf --max-time 2 http://127.0.0.1:11434 >/dev/null 2>&1; then
        # WSL mirrored networking mode (Windows 11 22H2+ with networkingMode=mirrored).
        ok "Windows Ollama reachable on loopback (mirrored networking)"
    else
        warn "Windows Ollama exe found but daemon not reachable from WSL."
        warn "Start Ollama on Windows (Start menu → Ollama) OR"
        warn "set OLLAMA_HOST=http://<windows-ip>:11434 in your shell, then re-run."
        warn "As a fallback, you can also enable WSL mirrored networking in .wslconfig."
    fi
else
    OLLAMA_MODE="install"
    warn "ollama not found anywhere — installing native Linux build"
    # --retry-all-errors covers transient SSL EOF / connection-reset mid-stream.
    curl --retry 5 --retry-delay 2 --retry-all-errors --connect-timeout 30 -fsSL \
        https://ollama.com/install.sh | sh
    ok "ollama installed"
fi

# Start the Linux daemon if we just installed it (or if it's installed but not running).
if [[ "$OLLAMA_MODE" == "linux" || "$OLLAMA_MODE" == "install" ]]; then
    if ! curl -sf --max-time 2 "$OLLAMA_HOST" >/dev/null 2>&1; then
        warn "Starting 'ollama serve' in the background..."
        nohup ollama serve >/dev/null 2>&1 &
        sleep 3
    fi
fi

# Thin CLI wrapper used by later steps. Routes to whichever ollama we found.
ollama_cli() {
    if command -v ollama &>/dev/null; then
        ollama "$@"
    elif [[ -n "$OLLAMA_WIN_EXE" ]]; then
        "$OLLAMA_WIN_EXE" "$@"
    elif command -v ollama.exe &>/dev/null; then
        ollama.exe "$@"
    else
        warn "ollama CLI not on PATH — skipping: ollama $*"
        return 1
    fi
}

# ====================================================================== #
step "4/11" "Setting up Python environment (uv)"
if ! command -v uv &>/dev/null; then
    curl --retry 5 --retry-delay 2 --retry-all-errors --connect-timeout 30 -LsSf \
        https://astral.sh/uv/install.sh | sh
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
ollama_cli pull qwen2.5:14b-instruct-q4_K_M || warn "Pull failed — check VRAM / network"
ollama_cli pull nomic-embed-text:v1.5 || warn "Embed model pull failed"
ok "models pulled"

# ====================================================================== #
step "6/11" "Creating Jarvis Modelfile"
ollama_cli create jarvis -f models/Jarvis.Modelfile 2>/dev/null && ok "jarvis model created" || warn "jarvis model create failed — continuing"

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
        curl --retry 5 --retry-delay 2 --retry-all-errors --connect-timeout 30 -fsSL \
            -o "$VOICES_DIR/${name}-${quality}.onnx" \
            "${base_url}/${name}-${quality}.onnx" 2>/dev/null || warn "download failed: ${name}-${quality}.onnx"
        curl --retry 5 --retry-delay 2 --retry-all-errors --connect-timeout 30 -fsSL \
            -o "$VOICES_DIR/${name}-${quality}.onnx.json" \
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

#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
#  Jarvis – Environment Audit
#  Run this inside WSL 2 before install.sh.
# ──────────────────────────────────────────────────────────
set -euo pipefail

# --- colours ---
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { printf "  ${GREEN}✓${NC}  %s\n" "$*"; }
warn() { printf "  ${YELLOW}!${NC}  %s\n" "$*"; }
fail() { printf "  ${RED}✗${NC}  %s\n" "$*"; }
hdr()  { printf "\n${BOLD}${CYAN}── %s ──${NC}\n" "$*"; }

# ====================================================================== #
hdr "OS / WSL"

if grep -qi microsoft /proc/version 2>/dev/null; then
    ok "Running inside WSL"
    WSL_VERSION=$(uname -r | grep -oP 'WSL\K\d' || echo "?")
    ok "WSL kernel: $(uname -r)  (WSL ${WSL_VERSION})"
else
    fail "Not running inside WSL. Jarvis requires WSL 2."
fi

. /etc/os-release 2>/dev/null || true
ok "Distro: ${PRETTY_NAME:-unknown}"

# ====================================================================== #
hdr "Hardware / GPU"

if command -v nvidia-smi &>/dev/null; then
    GPU=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "?")
    ok "GPU: $GPU"
    VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | tr -d ' ')
    if [ "${VRAM_MB:-0}" -ge 10000 ]; then
        ok "VRAM ≥ 10 GB — can use large-v3-turbo for STT and 14b LLM"
    elif [ "${VRAM_MB:-0}" -ge 6000 ]; then
        warn "VRAM 6–10 GB — will use medium STT and 7b LLM"
    else
        warn "VRAM < 6 GB — CPU inference recommended (slow)"
    fi
else
    fail "nvidia-smi not found. GPU acceleration unavailable."
    warn "Install the NVIDIA WSL driver from https://developer.nvidia.com/cuda/wsl"
fi

RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
RAM_GB=$(( RAM_KB / 1024 / 1024 ))
ok "RAM: ~${RAM_GB} GB"

# ====================================================================== #
hdr "Ollama"

if command -v ollama &>/dev/null; then
    ok "ollama: $(ollama --version 2>&1)"
    if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        ok "ollama serve is running"
        MODELS=$(curl -sf http://127.0.0.1:11434/api/tags | python3 -c \
            "import sys,json;print(', '.join(m['name'] for m in json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "?")
        ok "pulled models: ${MODELS:-none}"
    else
        warn "ollama is installed but 'ollama serve' is not running"
    fi
else
    warn "ollama not found. install.sh will install it."
fi

# ====================================================================== #
hdr "Python"

if command -v python3 &>/dev/null; then
    ok "python3: $(python3 --version 2>&1)"
else
    fail "python3 not found"
fi

if command -v uv &>/dev/null; then
    ok "uv: $(uv --version 2>&1)"
else
    warn "uv not found. install.sh will install it."
fi

if command -v pip3 &>/dev/null; then
    ok "pip3: $(pip3 --version 2>&1 | head -c60)"
fi

# ====================================================================== #
hdr "System libraries"

for lib in libportaudio2 ffmpeg libegl1 libgl1; do
    if dpkg -s "$lib" &>/dev/null; then
        ok "$lib installed"
    else
        warn "$lib not found (install.sh will install it)"
    fi
done

# ====================================================================== #
hdr "Windows interop"

if command -v cmd.exe &>/dev/null; then
    ok "cmd.exe accessible (WSL interop enabled)"
    WIN_USER=$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r\n')
    ok "Windows user: $WIN_USER"
    ok "Windows home: /mnt/c/Users/$WIN_USER"
else
    fail "cmd.exe not accessible. Enable 'interop' in wsl.conf."
fi

if command -v powershell.exe &>/dev/null; then
    ok "powershell.exe accessible"
else
    warn "powershell.exe not found"
fi

if command -v wslpath &>/dev/null; then
    ok "wslpath available"
fi

# ====================================================================== #
hdr "Audio"

if command -v aplay &>/dev/null; then
    ok "aplay: $(aplay --version 2>&1 | head -1)"
else
    warn "aplay not found"
fi

if command -v pactl &>/dev/null; then
    ok "PulseAudio detected (pactl available)"
elif [ -n "${PULSE_SERVER:-}" ]; then
    ok "PulseAudio server at $PULSE_SERVER"
else
    warn "No PulseAudio/PipeWire detected. Audio may not work."
    warn "See https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps"
fi

# ====================================================================== #
hdr "WSLg (GUI)"

if [ -n "${WAYLAND_DISPLAY:-}" ] || [ -n "${DISPLAY:-}" ]; then
    ok "Display server: DISPLAY=${DISPLAY:-''}, WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-''}"
else
    warn "No DISPLAY or WAYLAND_DISPLAY set. PyQt HUD may not work."
    warn "Upgrade to Windows 11 + WSL 2 for WSLg support."
fi

# ====================================================================== #
hdr "Disk"

AVAIL=$(df -h "$HOME" | awk 'NR==2{print $4}')
ok "Free space on \$HOME: $AVAIL"

# ====================================================================== #
printf "\n${BOLD}Audit complete.${NC}\n"
printf "Run ${CYAN}./scripts/install.sh${NC} to set up Jarvis.\n\n"

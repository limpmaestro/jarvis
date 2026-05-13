#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
#  Jarvis – Uninstaller
# ──────────────────────────────────────────────────────────
set -euo pipefail

echo "This will remove Jarvis services and state."
read -rp "Continue? [y/N] " ans
[[ "$ans" =~ ^[Yy] ]] || exit 0

echo "→ Stopping and disabling systemd service..."
systemctl --user stop jarvis-core.service 2>/dev/null || true
systemctl --user disable jarvis-core.service 2>/dev/null || true
rm -f "${HOME}/.config/systemd/user/jarvis-core.service"
systemctl --user daemon-reload 2>/dev/null || true

echo "→ Removing state directory..."
rm -rf "${HOME}/.jarvis"

echo "→ Removing Windows bridge task (if powershell.exe available)..."
if command -v powershell.exe &>/dev/null; then
    powershell.exe -Command "Unregister-ScheduledTask -TaskName 'JarvisBridge' -Confirm:\$false -ErrorAction SilentlyContinue" 2>/dev/null || true
    powershell.exe -Command "Remove-Item -Recurse -Force \"\$env:LOCALAPPDATA\\jarvis\" -ErrorAction SilentlyContinue" 2>/dev/null || true
fi

echo ""
echo "Jarvis services removed."
echo "The source code at ~/jarvis is untouched — delete it manually if desired."
echo "Ollama + pulled models are also left in place."

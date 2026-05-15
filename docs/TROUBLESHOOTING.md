# Troubleshooting

## 1. "ollama: command not found"

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

## 2. "Connection refused" on `http://127.0.0.1:11434`

Ollama isn't running. Start it:
```bash
ollama serve &
# or, if you installed via systemd:
sudo systemctl start ollama
```

## 3. CUDA out of memory

You're loading a model too large for your VRAM. Switch to a smaller one:
```bash
# Edit models/Jarvis.Modelfile → change FROM to a smaller model
ollama create jarvis -f models/Jarvis.Modelfile
```
See [MODELS.md](MODELS.md) for VRAM-to-model recommendations.

## 4. No audio input / output

WSL 2 + WSLg should forward PulseAudio. Verify:
```bash
pactl info
arecord -d 2 /tmp/test.wav && aplay /tmp/test.wav
```
If `pactl` fails, ensure you're on Windows 11 and WSLg is enabled.

## 5. PyQt HUD doesn't show

Requires WSLg (Windows 11). Check:
```bash
echo $DISPLAY          # should be :0 or :1
echo $WAYLAND_DISPLAY  # should be set
```
If both are empty, PyQt cannot open a window.

## 6. Windows bridge: "HMAC not configured"

The bridge HMAC key must exist at `~/.jarvis/state/bridge.hmac` (WSL)
and `%LOCALAPPDATA%\jarvis\bridge.key` (Windows). Re-run `install.sh`.

## 7. "keyring.errors.NoKeyringError"

On WSL without a dbus session, `keyring` falls back to a plaintext file.
This is expected. The vault is still encrypted with `age`; only the age
identity key is stored in plaintext. If you need dbus:
```bash
sudo apt-get install -y gnome-keyring dbus-x11
eval $(dbus-launch --sh-syntax)
```

## 8. Slow first response

- The LLM model loads into GPU on first call. Subsequent calls are fast.
- faster-whisper also loads on first call. Pre-warm by running `jarvis listen`.

## 9. Bridge refuses connections

Verify the bridge is running on Windows:
```powershell
Get-Process jarvis-bridge -ErrorAction SilentlyContinue
# or:
netstat -an | findstr 48219
```
If not running, start it manually or check Task Scheduler → "JarvisBridge".

## 10. `tflite-runtime` install fails ("no wheels for cp312")

`openwakeword` depends on `tflite-runtime`, which only publishes wheels for
Python 3.11 (no cp312, sometimes no cp313). This is why `install.sh` forces
the venv to Python 3.11 via `uv python install 3.11` + `uv venv --python 3.11`.

If you're seeing this error:
- Re-run `./scripts/install.sh` from a fresh clone — it will rebuild the venv on 3.11.
- Or, run wake-word-less: the [wake] extra is best-effort. Push-to-talk on
  `$JARVIS_PTT_HOTKEY` (default `F8`) continues to work without it.

To manually install just the wake extra later:
```bash
uv pip install --python .venv/bin/python ".[wake]"
```

## 11. Ollama is installed on Windows, not WSL

`install.sh` step 3/11 auto-detects an existing Ollama in this order:

1. `JARVIS_SKIP_OLLAMA_INSTALL=1` → installer leaves Ollama alone entirely.
2. Daemon already reachable on `$OLLAMA_HOST` (default `127.0.0.1:11434`).
3. `ollama` (Linux binary) on `PATH`.
4. `ollama.exe` on `PATH`, or a Windows install under
   `/mnt/c/Users/*/AppData/Local/Programs/Ollama/ollama.exe`,
   `/mnt/c/Users/*/OneDrive*/AppData/Local/Programs/Ollama/ollama.exe`,
   or `/mnt/c/Program*Files*/Ollama/ollama.exe`.
5. Otherwise → install native Linux Ollama.

When a Windows-side install is detected, the installer:
- Tries the WSL gateway IP (`ip route show default | awk '/default/ {print $3}'`)
  as the host and sets `OLLAMA_HOST=http://<gateway>:11434` if reachable.
- Falls back to `127.0.0.1:11434` if you have WSL mirrored networking enabled.
- All subsequent `ollama …` invocations in the installer go through an
  `ollama_cli` wrapper that calls `ollama.exe` if the Linux binary is missing.

If neither path works, start Ollama on Windows (Start menu → Ollama) and either:
- Enable mirrored networking in `%USERPROFILE%\.wslconfig`:
  ```ini
  [wsl2]
  networkingMode=mirrored
  ```
  then `wsl --shutdown` and reopen, or
- Hard-code `OLLAMA_HOST=http://<windows-ip>:11434` in `.env`.

## 12. Running inside Docker Desktop's WSL distro

If `df -h ~` reports only ~37 MB and `nvidia-smi` is missing, you're inside
Docker Desktop's bundled Alpine distro (`docker-desktop` or `docker-desktop-data`).
Those distros are not meant to run user workloads. Install a proper Ubuntu:

```powershell
wsl --install -d Ubuntu-22.04
wsl --set-default Ubuntu-22.04
```

Then clone Jarvis into the new distro's home directory and re-run `install.sh`.

Both `audit.sh` and `install.sh` now detect this distro (ID=alpine or
hostname matches `docker-desktop*`) and abort with a clear message before
touching anything, so you can't accidentally try to install into it.

## 13. `systemctl --user`: "Failed to connect to bus" on WSL

WSL distros do not run systemd by default. `install.sh` step 9/11 detects
this (`systemctl --user is-system-running` returns non-zero) and falls back
to launching `jarvis-core` via `nohup` in step 11/11. That works for the
current session, but Jarvis will not autostart on next login.

To get the full systemd experience (autostart, `journalctl --user -u jarvis-core`):

1. Edit `/etc/wsl.conf` (create it if missing) and add:
   ```ini
   [boot]
   systemd=true
   ```
2. From Windows PowerShell:
   ```powershell
   wsl --shutdown
   ```
3. Reopen your WSL distro. Verify systemd is running:
   ```bash
   systemctl is-system-running   # expect: running (or degraded)
   ```
4. Re-run `./scripts/install.sh`. Step 9/11 will now enable the user service.

If you don't want systemd, the nohup fallback is fine — you'll just have to
run `~/jarvis/.venv/bin/jarvis-core &` manually after each WSL boot
(or add it to your shell rc / wsl.conf `boot.command`).

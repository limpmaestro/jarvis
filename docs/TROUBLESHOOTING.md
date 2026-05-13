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

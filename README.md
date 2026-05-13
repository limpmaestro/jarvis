# Jarvis

> A local, autonomous, voice-driven AI assistant for Windows-via-WSL.
> No cloud. Your GPU. Your disk. Your rules.

Jarvis runs as a `systemd --user` service inside WSL 2, talks to a local
Ollama LLM, listens to your microphone with `faster-whisper`, speaks back
through Piper (Swedish + English), drives your Windows desktop via a tiny
HMAC-signed bridge, remembers things in ChromaDB, and shows its status on
a floating PyQt6 orb. Everything is documented in
[`docs/BLUEPRINT.md`](docs/BLUEPRINT.md) — read that first.

## Quick start (WSL 2 / Ubuntu 22.04+)

```bash
git clone https://github.com/limpmaestro/jarvis ~/jarvis
cd ~/jarvis
./scripts/audit.sh                # inspects your env, prints a report
./scripts/install.sh              # installs everything end-to-end
jarvis say "Systems online."
jarvis ask "Vad är klockan?"
```

The installer is idempotent. Re-running it upgrades models and refreshes the
systemd unit; it never overwrites your vault or memory.

## Highlights

- **Local inference** on your GPU via Ollama, with a custom `Jarvis.Modelfile`
  that establishes a proactive, witty, sysadmin-grade persona.
- **Bilingual voice** (Swedish + English) with automatic language detection
  per utterance.
- **Streaming pipeline**: first audio plays ~80 ms after the first LLM token,
  not after the full answer.
- **Tools**: shell, filesystem (sandboxed), web (Playwright), Windows
  automation (PyAutoGUI via the WSL→Windows bridge), memory.
- **Persistent memory**: ChromaDB with `nomic-embed-text` embeddings + a
  14-day decay on episodic memories.
- **Encrypted secrets vault** (age + OS keyring).
- **Floating HUD orb** (PyQt6) showing state at a glance.
- **OS-native autostart**: systemd-user inside WSL + a Windows Task
  Scheduler trampoline for the bridge.

## Documentation

- [Blueprint](docs/BLUEPRINT.md) — architecture and decisions
- [Architecture](docs/ARCHITECTURE.md) — process diagram + data flow detail
- [Security](docs/SECURITY.md) — threat model and defenses
- [Models](docs/MODELS.md) — recommended Ollama models per VRAM tier
- [Troubleshooting](docs/TROUBLESHOOTING.md) — when things go wrong

## CLI

```
jarvis status        Service status
jarvis logs          Tail logs (journalctl)
jarvis ask <text>    One-shot text→answer (no audio)
jarvis say <text>    Speak text via Piper
jarvis listen        Listen once, transcribe, exit
jarvis hud           Launch the floating orb
jarvis vault         Interactive vault editor
jarvis audit         Re-run environment audit
jarvis serve         Run the core in the foreground (debugging)
```

## License

MIT. See [`LICENSE`](LICENSE).

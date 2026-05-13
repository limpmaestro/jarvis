# Architecture

For a full discussion of every component, see [BLUEPRINT.md](BLUEPRINT.md).
This page is the quick-reference diagram version.

## Process topology

```
                    ┌──────── Windows host ────────┐
                    │                              │
                    │  jarvis-bridge.exe            │
                    │  (PyAutoGUI + FastAPI)        │
                    │  127.0.0.1:48219              │
                    └──────────┬───────────────────┘
                               │ HMAC-signed HTTP
┌──────────────────────────────┼─── WSL 2 ───────────────────────────┐
│                              │                                      │
│  ┌─────────────┐   ┌────────┴───────────┐   ┌───────────────────┐  │
│  │ mic → VAD → │──▶│   JARVIS CORE      │──▶│  Piper TTS        │  │
│  │ STT         │   │   (agent loop)     │   │  → sounddevice    │  │
│  └─────────────┘   │                    │   └───────────────────┘  │
│                    │  ┌──────────────┐  │                          │
│                    │  │  Ollama      │  │   ┌──────────────────┐   │
│                    │  │  (GPU, LLM)  │◀─┤   │  ChromaDB        │   │
│                    │  └──────────────┘  │   │  (memory)        │   │
│                    │  ┌──────────────┐  │   └──────────────────┘   │
│                    │  │  Tools       │  │   ┌──────────────────┐   │
│                    │  │  shell/fs/web│◀─┤   │  Vault (age)     │   │
│                    │  └──────────────┘  │   └──────────────────┘   │
│                    └────────────────────┘                          │
│                              ▲                                     │
│                    unix sock │                                      │
│                    ┌─────────┴──────────┐                          │
│                    │  HUD Orb (PyQt6)   │                          │
│                    └────────────────────┘                          │
└────────────────────────────────────────────────────────────────────┘
```

## IPC contracts

| Path / socket                          | Protocol             | Auth             |
|----------------------------------------|----------------------|------------------|
| `/run/user/$UID/jarvis/core.sock`      | NDJSON RPC           | Unix perms (0600)|
| `http://127.0.0.1:48219`              | HTTP + HMAC          | shared key       |

## Data stored on disk

| Path                                   | What                                   |
|----------------------------------------|----------------------------------------|
| `~/.jarvis/state/chroma/`              | ChromaDB vector store                  |
| `~/.jarvis/state/vault.age`            | Encrypted secrets                      |
| `~/.jarvis/state/audit.jsonl`          | Tool call audit log                    |
| `~/.jarvis/state/bridge.hmac`          | Bridge HMAC key                        |
| `~/.jarvis/state/hud.json`             | HUD window position                    |

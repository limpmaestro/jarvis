# Jarvis — Technical Blueprint

> *"Sometimes you gotta run before you can walk."* — Tony Stark
>
> A local-first, voice-driven, hardware-integrated AI assistant that lives on your
> Windows machine via WSL/Ubuntu. No cloud round-trips for inference, STT, TTS, or
> memory. Everything runs on **your** GPU, on **your** disk, under **your** control.

This document is the canonical reference for the system. Read this before
running `install.sh`. It is intentionally opinionated and verbose; the rest of
the repo follows the decisions made here.

---

## 0. Goals & Non-Goals

### Goals
1. **Latency budget**: < 800 ms wake-word → first audio out for short answers,
   < 2 s for tool-using answers, measured on a single RTX-class GPU.
2. **Offline by default**: no network calls except (a) Ollama model pulls,
   (b) explicit web tool calls invoked by the agent.
3. **Bilingual**: Swedish (primary) + English, automatic language detection
   per utterance.
4. **Computer use**: drive the host Windows desktop (clicks, typing, window
   focus) through the WSL ↔ Windows interop bridge — not a VM, not RDP.
5. **Persistent memory**: ChromaDB local vector store; survives reboots.
6. **OS-native autostart**: runs as a `systemd --user` service inside WSL with
   a Windows Task Scheduler trampoline so it launches on user logon.
7. **Encrypted at rest**: all API keys, refresh tokens, and conversation
   archives are encrypted with an age key locked behind the OS keyring.
8. **Status visible at a glance**: a small always-on-top HUD "orb" that
   pulses with state (idle / listening / thinking / speaking / error).

### Non-Goals
- Cloud SaaS, multi-tenant, or web-app deployment.
- Replacing the user's IDE, browser, or shell. Jarvis *drives* them.
- Training or fine-tuning models. We use off-the-shelf Ollama models +
  prompt engineering + a `Modelfile`.
- Mobile support.

---

## 1. System Architecture

```
┌─────────────────────────── Windows host ────────────────────────────┐
│                                                                     │
│   ┌──────────────┐    audio in/out (WASAPI)    ┌──────────────────┐ │
│   │   Mic / DAC  │ ───────────────────────────▶│ jarvis-bridge.exe │ │
│   └──────────────┘   PyAutoGUI / pywinauto    │  (PowerShell host)│ │
│          ▲             win32 calls            └────────┬──────────┘ │
│          │                                             │            │
│          │ floating HUD orb (PyQt, runs in WSLg)       │ named-pipe │
│          │                                             │ /tmp socket│
│  ┌───────┴──────────────────────────────────────────────▼─────────┐ │
│  │                       WSL 2 (Ubuntu 22.04+)                    │ │
│  │                                                                │ │
│  │  ┌──────────┐  ┌─────────┐  ┌─────────┐  ┌────────┐  ┌──────┐  │ │
│  │  │ STT      │─▶│ Agent   │─▶│  Tools  │─▶│ Memory │  │ Vault│  │ │
│  │  │ whisper  │  │ loop    │  │ (shell, │  │ Chroma │  │ age  │  │ │
│  │  │ + VAD    │  │ + LLM   │  │  fs,    │  │        │  │keyring│ │ │
│  │  └──────────┘  └────┬────┘  │ web,    │  └────────┘  └──────┘  │ │
│  │       ▲             │       │ win)    │                        │ │
│  │       │             ▼       └────┬────┘                        │ │
│  │  ┌──────────┐  ┌─────────────┐   │                             │ │
│  │  │ TTS      │◀─│  Ollama     │◀──┘                             │ │
│  │  │ Piper    │  │  (GPU)      │                                 │ │
│  │  └────┬─────┘  └─────────────┘                                 │ │
│  └───────┼────────────────────────────────────────────────────────┘ │
│          │ PCM-16 stream                                            │
│          ▼                                                          │
│   ┌──────────────┐                                                  │
│   │  Speakers    │                                                  │
│   └──────────────┘                                                  │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.1 Process model

| Process                  | Where        | Lifetime          | Purpose                                |
|--------------------------|--------------|-------------------|----------------------------------------|
| `ollama serve`           | WSL (host)   | systemd-user      | GPU inference                          |
| `jarvis-core`            | WSL          | systemd-user      | STT, agent, TTS, memory, tools         |
| `jarvis-hud`             | WSL (WSLg)   | follows core      | PyQt6 floating orb                     |
| `jarvis-bridge.exe`      | Windows      | Task Scheduler    | PyAutoGUI / win32 automation server    |
| `chromadb` (in-proc)     | WSL          | child of core     | vector store                           |

All inter-process traffic uses local sockets:
- `unix:///run/user/$UID/jarvis/core.sock` for HUD ↔ core
- `tcp://127.0.0.1:48219` for core ↔ Windows bridge (loopback only, HMAC-signed)

### 1.2 Why these choices

- **Ollama** over llama.cpp directly: it already handles GPU offload, model
  swaps, and exposes a stable HTTP API we can target.
- **faster-whisper** over openai-whisper: 4× faster on CUDA, ctranslate2 backend,
  same accuracy.
- **Piper** over Coqui XTTS: Piper is ~50 ms first-byte on CPU, Coqui needs
  GPU + warmup. We keep the GPU free for the LLM.
- **ChromaDB** (DuckDB+parquet backend) over Qdrant: zero ops, embeds in-process.
- **PyQt6** over Electron: a 12 MB native HUD beats a 200 MB Chromium shell.
- **age** over GPG: modern, simple, X25519 keys; pairs with `pass`-style use.

---

## 2. Component contracts

### 2.1 STT — `jarvis.audio.stt`

- Input: 16 kHz mono PCM from `sounddevice` ring buffer.
- Wake-word: `openwakeword` "hey jarvis" model (configurable); push-to-talk
  via global hotkey (`F8` by default, registered via the Windows bridge).
- VAD: `silero-vad` v4, ONNX, CPU. Endpoints utterances on 700 ms silence.
- Model: `faster-whisper` `large-v3-turbo` if GPU has ≥10 GB VRAM, else
  `medium`. Auto-detected by `audit.sh`.
- Language: auto-detect per utterance; falls back to `sv` then `en`.
- Output: `{text: str, language: str, confidence: float, started_at, ended_at}`.

### 2.2 Agent loop — `jarvis.agent.loop`

The agent loop is a **single explicit state machine** (no LangChain). States:
`IDLE → LISTENING → TRANSCRIBING → THINKING → TOOL_CALL → THINKING → SPEAKING → IDLE`.

Each user turn:
1. STT produces text + language.
2. Memory retrieval: top-K=6 chunks from Chroma scored by cosine sim, filtered
   by recency boost (exponential decay, half-life = 14 days).
3. The system prompt + retrieved memory + last 8 turns are sent to Ollama
   with `tools=[...]` (Ollama's function-calling JSON schema).
4. If the model emits a tool call, the dispatcher executes it (see §2.4),
   appends the tool result, and re-prompts.
5. The final assistant message is streamed token-by-token; tokens are
   buffered into sentence-sized chunks that are pipelined into Piper, so
   audio starts playing while the LLM is still generating.
6. After speaking, the full turn is summarized and written back to memory.

System prompt lives in `prompts/system.sv.txt` and `prompts/system.en.txt`,
selected by detected language. Both prompts establish: proactive, witty
British-butler tone; concise; explicit about tool use; refuses dangerous
shell operations without a confirmation phrase.

### 2.3 LLM — Ollama + Modelfile

Default model: `qwen2.5:14b-instruct-q4_K_M` (fits in 12 GB VRAM, strong tool
use, multilingual). Alternative tiers documented in `docs/MODELS.md`.

The `Modelfile` in `models/Jarvis.Modelfile` baselines:
- `FROM qwen2.5:14b-instruct-q4_K_M`
- `PARAMETER num_ctx 8192`
- `PARAMETER temperature 0.4`
- `PARAMETER stop "<|im_end|>"`
- `SYSTEM` block injects the Jarvis persona + tool schema reminders.

### 2.4 Tools — `jarvis.tools`

All tools are plain Python functions registered through a `@tool` decorator
that emits a JSON Schema. Bundled tools:

| Tool             | Description                                                  | Risk |
|------------------|--------------------------------------------------------------|------|
| `shell.run`      | Run a shell command in WSL with timeout + cwd                | high |
| `fs.read`        | Read a UTF-8 file                                            | low  |
| `fs.write`       | Write a UTF-8 file (path must be inside allowed roots)       | med  |
| `fs.search`      | ripgrep across allowed roots                                 | low  |
| `web.search`     | DuckDuckGo HTML scrape via Playwright headless               | low  |
| `web.fetch`      | Fetch + readability-clean a URL                              | low  |
| `win.click`      | Mouse click at (x, y) on Windows desktop                     | high |
| `win.type`       | Type text into the focused Windows window                    | high |
| `win.focus`      | Focus a window by title regex                                | med  |
| `win.screenshot` | Capture the Windows primary monitor → PNG                    | low  |
| `memory.save`    | Force-store a note in long-term memory                       | low  |
| `memory.query`   | Vector search long-term memory                               | low  |

Each call is logged structured JSON to `~/.jarvis/state/audit.jsonl`. Tools
marked `high` require the agent to first speak a confirmation and receive a
user "ja"/"yes" before executing, unless `allow_unattended=true` is set per
session.

### 2.5 Memory — `jarvis.memory`

- Embedder: `nomic-embed-text:v1.5` via Ollama (768-dim, multilingual).
- Store: ChromaDB persistent client at `~/.jarvis/state/chroma/`.
- Collections: `episodic` (per-turn summaries) and `semantic` (notes,
  preferences, project facts).
- Indexing: every turn is summarized into 1–3 sentences by the LLM,
  embedded, and written to `episodic`. Explicit `memory.save` calls go to
  `semantic`.
- Decay: cosine sim is multiplied by `exp(-Δdays / 14)` for `episodic`,
  no decay for `semantic`.

### 2.6 Vault — `jarvis.vault`

- Master key: an `age` X25519 identity stored in the OS keyring (Linux
  Secret Service via `dbus`; on WSL we fall back to a file-backed
  `keyring.backends.file.PlaintextKeyring` only after the user is warned).
- Vault file: `~/.jarvis/state/vault.age` — encrypted JSON object.
- API: `vault.get(name)`, `vault.set(name, value)`, `vault.delete(name)`.
- Never logged; never echoed; values are scrubbed from agent transcripts
  using a deny-list regex before they hit memory.

### 2.7 HUD — `jarvis.hud`

- Frameless, always-on-top PyQt6 window, 96×96 px, transparent background.
- Renders a circular orb with a procedural shader (QtQuick `ShaderEffect`)
  that pulses by current RMS amplitude when listening and by token rate
  when speaking.
- Subscribes to the core's status stream over the unix socket.
- Right-click → context menu: "Mute", "Quit", "Open logs".
- Draggable; position persisted to `~/.jarvis/state/hud.json`.

### 2.8 Windows bridge — `services/windows-bridge`

A tiny FastAPI app packaged with PyInstaller into `jarvis-bridge.exe`. It
listens on `127.0.0.1:48219`, accepts HMAC-signed requests from the WSL
core, and dispatches to `pyautogui`, `pywinauto`, `psutil`, and `mss`.
The HMAC key is generated at install time and stored both in the Windows
DPAPI-protected `%LOCALAPPDATA%\jarvis\bridge.key` and the WSL vault.

---

## 3. Data flow — a full turn

```
0.0s   user: "Jarvis, vad har jag för möten imorgon?"
0.0s   wake-word fires, mic opens
2.1s   VAD endpoint, 1.4s of audio captured
2.2s   faster-whisper transcribes → {sv, "Jarvis, vad har jag för möten imorgon?"}
2.25s  memory retrieval: top-6 chunks (calendar prefs, last meeting)
2.30s  agent → Ollama (qwen2.5:14b) with tools[...]
2.55s  LLM emits tool_call: web.fetch(url=calendar_export)
2.6s   tool result → 2.4 kB JSON of events
2.65s  agent → Ollama (second call) with tool result
2.75s  LLM streams: "Imorgon har du tre möten…"
2.80s  first sentence flushed → Piper → speakers (first audio: ~0.55s after stt end)
3.4s   answer complete, episodic memory written
```

---

## 4. Security model

- **Threat model**: a curious roommate with shell access; a malicious URL
  that tries to make the agent run `rm -rf`; an exfiltration attempt via the
  Windows bridge. Not: a nation-state with kernel access.
- **Defenses**:
  - The shell tool runs through a denylist of patterns
    (`rm -rf /`, `mkfs`, `dd if=`, `:(){:|:&};:` …) and a confirmation phrase
    for anything matching a riskier allow-list.
  - The Windows bridge HMAC-signs every request; replay-protected by a
    nonce + 5 s skew window.
  - Filesystem tools are sandboxed to `JARVIS_ALLOWED_ROOTS` (default:
    `~/Documents`, `~/Downloads`, `~/Desktop`, `/mnt/c/Users/<you>`).
  - The vault never leaves memory unencrypted; the age identity is wiped
    from RAM on shutdown via `mlock`+overwrite.
  - All inbound sockets bind to loopback only.

---

## 5. Performance budget

Measured on RTX 4070 (12 GB), Ryzen 9 7900X, NVMe:

| Stage             | Target  | Notes                                             |
|-------------------|---------|---------------------------------------------------|
| Wake-word → mic   | <50 ms  | openwakeword keeps a 2 s rolling buffer           |
| STT (1.5 s audio) | <250 ms | large-v3-turbo, beam_size=1, vad_filter=False     |
| Memory retrieval  | <30 ms  | Chroma cosine search, K=6, ~10 k vectors          |
| LLM first token   | <300 ms | qwen2.5:14b q4_K_M, num_ctx=8192                  |
| LLM tokens/s      | ≥35     | streaming, GPU offload all layers                 |
| TTS first byte    | <80 ms  | Piper, sv_SE-nst-medium                           |
| End-to-end (no tool) | <800 ms | wake → first audio out                         |

Regressions are caught by `tests/perf/test_latency.py` (run nightly, optional).

---

## 6. Install & lifecycle

### One-line bootstrap (in WSL Ubuntu)

```bash
git clone https://github.com/limpmaestro/jarvis ~/jarvis
cd ~/jarvis && ./scripts/install.sh
```

`install.sh` does, in order:

1. `audit.sh` — print env report, ask "continue? [y/N]" unless `--yes`.
2. `apt-get install` system deps (portaudio, ffmpeg, libegl, etc.).
3. `curl -fsSL https://ollama.com/install.sh | sh` if missing.
4. `uv sync` to materialize the Python env into `.venv`.
5. `ollama pull qwen2.5:14b-instruct-q4_K_M` + `nomic-embed-text`.
6. `ollama create jarvis -f models/Jarvis.Modelfile`.
7. Download Piper voices (sv_SE + en_US) into `assets/voices/`.
8. Generate vault key + bridge HMAC key.
9. Install `~/.config/systemd/user/jarvis-core.service` and enable it.
10. Cross-call `install.ps1` via `powershell.exe` to register the Windows
    bridge as a Task Scheduler logon task.
11. `systemctl --user start jarvis-core` and tail logs for 5 s.

### Lifecycle commands

```bash
jarvis status      # systemctl --user status jarvis-core
jarvis logs        # journalctl --user -u jarvis-core -f
jarvis say "hej"   # direct TTS test
jarvis ask "..."   # one-shot text → answer (no audio)
jarvis hud         # open the floating orb
jarvis vault       # interactive vault editor
jarvis audit       # re-run the env audit
```

---

## 7. Repository layout

```
jarvis/
├── docs/                     # this file + ARCHITECTURE, SECURITY, MODELS, TROUBLESHOOTING
├── models/Jarvis.Modelfile   # Ollama modelfile
├── prompts/                  # system prompts (sv/en)
├── scripts/                  # audit.sh, install.sh, install.ps1, uninstall.sh
├── services/
│   ├── systemd/              # jarvis-core.service
│   └── windows-bridge/       # FastAPI bridge + PyInstaller spec
├── src/jarvis/
│   ├── audio/                # stt, tts, vad, wake
│   ├── agent/                # loop, dispatcher, prompts
│   ├── tools/                # shell, fs, web, win, memory
│   ├── memory/               # chroma wrapper
│   ├── vault/                # age + keyring
│   ├── hud/                  # PyQt6 orb
│   ├── server/               # core IPC server
│   ├── wsl/                  # interop helpers
│   ├── config/               # pydantic settings
│   ├── utils/                # logging, audit log, perf
│   ├── cli.py                # `jarvis ...` entrypoint
│   └── __main__.py
├── tests/
├── assets/                   # voices, icons, HUD shaders
├── pyproject.toml
├── README.md
└── LICENSE
```

---

## 8. Phasing

| Phase | Deliverable                                                       |
|-------|-------------------------------------------------------------------|
| P0    | Blueprint (this doc), repo skeleton, audit.sh                     |
| P1    | Ollama wrapper + Modelfile + CLI `jarvis ask`                     |
| P2    | TTS (Piper) + CLI `jarvis say`                                    |
| P3    | STT (faster-whisper + VAD) + CLI `jarvis listen`                  |
| P4    | Agent loop + tools (shell, fs, web)                               |
| P5    | Memory (Chroma) + vault (age)                                     |
| P6    | Windows bridge (PyAutoGUI) + win.* tools                          |
| P7    | HUD orb (PyQt6)                                                   |
| P8    | systemd + Task Scheduler + install.sh                             |
| P9    | Hardening, tests, perf budgets                                    |

This PR delivers **P0 through P9 as a single maximalist drop**, because that
is what you asked for. Future PRs can iterate on individual phases.

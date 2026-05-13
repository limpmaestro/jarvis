# Security Model

## Threat model

Jarvis is a **personal assistant** on a **single-user workstation**. We
defend against:

1. A curious roommate with shell access to the WSL environment.
2. A malicious URL that social-engineers the agent into running harmful
   commands (prompt injection).
3. A local service on the network trying to issue bridge commands.

We do **not** defend against:
- A kernel-level attacker with root access.
- A supply-chain attack on our Python dependencies.

## Layers of defence

### 1. Shell tool denylist
Patterns matching `rm -rf /`, `mkfs`, `dd` to `/dev/`, fork bombs,
`shutdown`, `reboot`, etc. are refused before execution. See
`src/jarvis/tools/shell.py::_DENY`.

### 2. Tool confirmation
High-risk tools (`shell.run`, `win.click`, `win.type`) require the user
to say "yes" / "ja" before execution, unless the session is set to
`JARVIS_UNATTENDED=true`. The confirmation is spoken by TTS and detected
by STT.

### 3. Filesystem sandboxing
`fs.*` tools only access paths inside `JARVIS_ALLOWED_ROOTS` (default:
`~/Documents`, `~/Downloads`, `~/Desktop`, `/mnt/c/Users`). Paths
outside the allow-list raise `PermissionError`.

### 4. Bridge HMAC
Every request to the Windows bridge is signed with a 256-bit HMAC key
(`SHA-256`), a per-request nonce, and a timestamp. The bridge rejects
replays (> 5 s skew) and invalid signatures.

### 5. Vault encryption
Secrets are encrypted with `age` (X25519). The identity key is stored in
the OS keyring (or a file-backed keyring on WSL without dbus). The vault
file is `0600`.

### 6. Loopback-only sockets
Both the core unix socket and the Windows bridge bind only to `127.0.0.1`.
Nothing is exposed to the LAN.

### 7. Transcript scrubbing
Before writing a turn to long-term memory, the assistant's output is
scanned for known vault keys and their values are masked with `[REDACTED]`.

## Recommendations

- Run WSL 2 (not 1). WSL 2 uses a real Linux kernel with proper isolation.
- Keep your Ollama models up-to-date.
- Do not grant Jarvis `JARVIS_UNATTENDED=true` unless you trust the
  environment (e.g. overnight batch jobs on your desk).
- Review `~/.jarvis/state/audit.jsonl` periodically.

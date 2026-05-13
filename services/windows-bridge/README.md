# Windows Bridge

A small HMAC-signed FastAPI app that runs on the **Windows host** (not in
WSL) and exposes `pyautogui` / `pywinauto` / `mss` to the Jarvis core
running in WSL.

## Build the EXE

From a Windows PowerShell prompt:

```powershell
cd path\to\jarvis\services\windows-bridge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pyinstaller
pyinstaller --onefile bridge.py --name jarvis-bridge
```

The result is `dist\jarvis-bridge.exe`. The WSL-side `install.sh` will
arrange for it to be copied to `%LOCALAPPDATA%\jarvis\` and registered
as a Task Scheduler logon entry.

## Run directly (for development)

```powershell
$env:LOCALAPPDATA\jarvis\bridge.key | Set-Content bridge.key  # ensure key exists
python bridge.py
```

The bridge listens on `127.0.0.1:48219`. It only accepts loopback
connections and rejects requests without a valid HMAC signature.

## HMAC Protocol

Each request must include three headers:

| Header              | Value                                                |
|---------------------|------------------------------------------------------|
| `X-Jarvis-Nonce`    | 16-hex-char random nonce                             |
| `X-Jarvis-Ts`       | Unix timestamp (seconds)                             |
| `X-Jarvis-Sig`      | HMAC-SHA256 of `METHOD\nPATH\nBODY\nNONCE\nTS`      |

The shared secret is the 64-hex-char key in `%LOCALAPPDATA%\jarvis\bridge.key`.
Requests with timestamps more than 5 seconds away from the server's clock
are rejected.

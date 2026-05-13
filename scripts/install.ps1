<#
.SYNOPSIS
    Windows-side installer for Jarvis bridge.
    Run from PowerShell (not WSL).

.DESCRIPTION
    1. Creates %LOCALAPPDATA%\jarvis
    2. Installs Python deps (if pip available)
    3. Registers jarvis-bridge.exe as a logon Task Scheduler entry

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1
#>

$ErrorActionPreference = "Stop"
$JarvisDir = Join-Path $env:LOCALAPPDATA "jarvis"

Write-Host "`n[1/4] Creating directory: $JarvisDir"
New-Item -ItemType Directory -Force -Path $JarvisDir | Out-Null

# Bridge key should already exist (written by install.sh). Verify.
$keyPath = Join-Path $JarvisDir "bridge.key"
if (Test-Path $keyPath) {
    Write-Host "  Bridge key found: $keyPath"
} else {
    Write-Warning "  bridge.key not found. Run install.sh in WSL first."
}

Write-Host "`n[2/4] Installing Python dependencies for the bridge"
$bridgeDir = Join-Path $PSScriptRoot "..\services\windows-bridge"
if (Test-Path (Join-Path $bridgeDir "bridge.py")) {
    pip install fastapi uvicorn pyautogui pygetwindow mss pillow psutil pywinauto 2>$null
} else {
    Write-Warning "  bridge.py not found at $bridgeDir — skipping pip install"
}

Write-Host "`n[3/4] Building jarvis-bridge.exe"
try {
    pip install pyinstaller 2>$null
    Push-Location $bridgeDir
    pyinstaller --onefile bridge.py --name jarvis-bridge 2>$null
    Pop-Location
    $exePath = Join-Path $bridgeDir "dist\jarvis-bridge.exe"
    Copy-Item $exePath $JarvisDir -Force
    Write-Host "  Copied to: $JarvisDir\jarvis-bridge.exe"
} catch {
    Write-Warning "  PyInstaller build failed: $_. You can run bridge.py directly instead."
}

Write-Host "`n[4/4] Registering Task Scheduler logon entry"
$bridgeExe = Join-Path $JarvisDir "jarvis-bridge.exe"
if (Test-Path $bridgeExe) {
    $taskName = "JarvisBridge"
    $action = New-ScheduledTaskAction -Execute $bridgeExe
    $trigger = New-ScheduledTaskTrigger -AtLogon
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

    try {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    } catch {}

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings | Out-Null
    Write-Host "  Registered scheduled task: $taskName"
} else {
    Write-Warning "  jarvis-bridge.exe not found — skipping Task Scheduler."
}

Write-Host "`nDone. The bridge will start automatically on next logon.`n"

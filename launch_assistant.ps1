<#
.SYNOPSIS
  PokerFlex A1 - PowerShell one-click / zero-touch background assistant launcher.

.DESCRIPTION
  Preferred launcher for users who continue in PowerShell on Windows (no git required, pure local dev + run).
  Delegates to launch_assistant.py (single source of truth for defaults + logic) after setting a good PS console environment.

  Hero defaults (same as .bat/.py):
    --tray --background --live + (--real-vision if vision_config.json exists else --simulate-vision) + pos BTN/stack 100/auto-capture + overlay

  Hotkeys (global even when ClubGG or CoinPoker has focus): Ctrl+Alt+A (analyze), S (status), C (capture), O (toggle overlay).

  Multi-client: pass --client coinpoker (or clubgg). Calibrate once per client/table with `python -m pokerflex calibrate --client coinpoker`.

  Tray (default): icon in tray, toasts, menu (Analyze Now / Status / Notes Quick / Open Calibration / Launch GUI / Quit), auto-hide console on Win, "Run at startup" toggle.

  To run:
    - Right-click this file -> Run with PowerShell (or "Run as administrator" for reliable global hotkeys).
    - Or from PS prompt (recommended for dev):
        Set-Location E:\PokerFlex
        .\launch_assistant.ps1
    - With overrides:
        .\launch_assistant.ps1 --client coinpoker --real-vision --tray
    - If execution policy blocks (common): 
        powershell -ExecutionPolicy Bypass -File .\launch_assistant.ps1

  For real tables (after first run): run the calibration wizard once (~2 min) then relaunch.
  For demo (no table, no tesseract, no OCR): just double-click / run — it uses --simulate-vision.

  Stops cleanly on Ctrl+C or tray Quit. State + notes are persisted to the json files (watcher reloads live edits).

.NOTES
  - No git or source control workflow here. Direct local edits + PowerShell + python.
  - A1 brain is the UNAMBIGUOUS default (rich GTO + explo notes + ICM + history + vision pot/bet).
  - Legacy brain only via $env:POKERFLEX_FORCE_LEGACY_BRAIN=1 (debug only).
  - Requires Python on PATH + the package runnable (python -m pokerflex works or pip install -e .).
  - Optional for tray: pip install pystray (graceful fallback if missing).
  - For best emoji/UTF8 in rich A1 output: use Windows Terminal or recent PowerShell 7+.

.LINK
  quickstart.txt
  readme.md
#>

[CmdletBinding()]
param(
    # Pass-through all extra args to the python launcher (e.g. --client coinpoker --real-vision --periodic-capture 8)
    [Parameter(ValueFromRemainingArguments = $true, Position = 0)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $here

# Make PowerShell console friendly for PokerFlex A1 output (emoji, suits, rich text, logs).
# chcp 65001 + UTF8 output encoding helps when not using Windows Terminal.
try {
    $null = chcp 65001 2>$null   # ignore errors on some hosts
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {
    # Non-fatal; many modern PS7 + Windows Terminal already handle UTF8 well.
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host " PokerFlex A1 — PowerShell Launcher (zero-touch)" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Continuing in PowerShell on Windows (local, no git)." -ForegroundColor DarkGray
Write-Host "Delegates to launch_assistant.py for the canonical experience + banners."
Write-Host ""
Write-Host "Quick tips for PS users:" -ForegroundColor Yellow
Write-Host "  • Global hotkeys reliable?  Right-click PowerShell shortcut → Run as administrator, then run this script."
Write-Host "  • Script blocked by policy?  powershell -ExecutionPolicy Bypass -File .\launch_assistant.ps1"
Write-Host "  • CoinPoker: append  --client coinpoker  (e.g. .\launch_assistant.ps1 --client coinpoker --real-vision)"
Write-Host "  • Real vision (after one calib): the script auto-detects vision_config.json and prefers --real-vision."
Write-Host "  • Demo only (no table): just run it — uses safe --simulate-vision with full live E2E."
Write-Host "  • Edit state/notes live: poker_current_state.json (or coinpoker_* / clubgg_* ) + the matching _player_notes.json"
Write-Host "  • Calibrate (once per client/table/skin):  python -m pokerflex calibrate   (or with --client coinpoker)"
Write-Host ""
Write-Host "Hotkeys (global): Ctrl+Alt+A=analyze  |  S=status  |  C=capture  |  O=toggle overlay"
Write-Host "Tray menu (right-click icon): Analyze | Status | Notes | Calibration | GUI | Quit + Run-at-startup toggle"
Write-Host ""

# Forward everything to the real launcher (keeps all defaults, seeding, tray logic, A1 enforcement, CoinPoker wiring etc. in one place).
$pythonArgs = @()
if ($ExtraArgs -and $ExtraArgs.Count -gt 0) {
    $pythonArgs = $ExtraArgs
}

Write-Host "Running: python launch_assistant.py $($pythonArgs -join ' ')" -ForegroundColor Gray
Write-Host "(Full rich banner + ready instructions come from the .py — this is just the PS entry point.)" -ForegroundColor DarkGray
Write-Host ""

try {
    & python launch_assistant.py @pythonArgs
} catch [System.Management.Automation.CommandNotFoundException] {
    Write-Host ""
    Write-Warning "python not found on PATH. Install Python 3, add it to PATH, then retry."
    Write-Host "Or use the full path, e.g.:  & 'C:\Python313\python.exe' launch_assistant.py @pythonArgs"
} catch {
    Write-Host ""
    Write-Warning "Launcher exited with error: $_"
} finally {
    Write-Host ""
    Write-Host "Assistant stopped. (state + notes persisted to the *_current_state.json and *_player_notes.json files)" -ForegroundColor Yellow
    Write-Host "Close this window or press Enter to exit..." -ForegroundColor DarkGray
    try { $null = Read-Host } catch {}
}

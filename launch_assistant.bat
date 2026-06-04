@echo off
setlocal
cd /d "%~dp0"

echo ================================================
echo  PokerFlex A1 - ZERO-TOUCH One-Click Background Assistant
echo ================================================
echo.
echo One-click / double-click for true minimal-input bg A1 real-time (A1 brain + live auto listener).
echo - HERO DEFAULT via launch_assistant.py: tray + live + (real-vision if vision_config.json profile from 'calibrate' else simulate-vision demo w/o table).
echo   Always-visible advice: tray toasts + tiny auto draggable Tk overlay (at-a-glance rich A1 w/ history/ICM/pot/bet).
echo - THE 3 MOST USEFUL HOTKEYS (global while ClubGG or CoinPoker focused): Ctrl+Alt+A (analyze rich A1) | Ctrl+Alt+O (toggle floating always-on compact advice) | Ctrl+Alt+S (status). Tray has Show Last Advice / Toggle Overlay / NIT presets / Calib / GUI.
echo - Edit poker_current_state.json (primary) / clubgg_current_state.json (compat fallback) / coinpoker_* for client; same for notes (watcher ~2s).
echo - For real ClubGG (after first run): run `python -m pokerflex calibrate` once (~2min), then launch_assistant.bat --real-vision (or just launch_assistant.bat if profile present — auto).
echo - For CoinPoker (parallel, 'works for CoinPoker too'): launch_assistant.bat --client coinpoker --real-vision (calibrate once for your CoinPoker table first via python -m pokerflex calibrate)
echo   Tray+coinpoker ex: launch_assistant.bat --tray --client coinpoker --real-vision
echo - Tray is now default (icon + menu: Analyze Now / Status / Notes Quick / Run at startup / Show Console / Quit), quieter, auto-hides console on Win, popups + log for advice. Requires `pip install pystray` (optional; graceful fallback).
echo    Overlay shown automatically in tray for always-visible surface.
echo - Primary zero-touch (pre/post install): python -m pokerflex | pokerflex (after pip -e .) | this .bat/.py
echo - A1 is THE UNAMBIGUOUS default (GTO+explo+ICM+notes+vision auto state + action_history/postflop ICM/vision pot/bet flow); legacy ONLY via POKERFLEX_FORCE_LEGACY_BRAIN=1 (debug, never primary; runner always A1). E2E full suite passed. Production-ready for ClubGG + CoinPoker. Just run + get value.
echo.
echo To stop: close this window or Ctrl+C  (or tray Quit).
echo.
echo (Delegates to launch_assistant.py for single source of truth: tray+live+overlay default, calib gentle suggestion on no profile, 2-note seed, ready banner with 3 hotkeys, full tray menu enhancements.)
echo.

REM True zero-touch HERO: delegate to the .py launcher (which defaults --tray --background --live + real if vision profile else sim,
REM applies good presets + real-robustness auto-defaults when real, passes extras (user can --no-tray --simulate etc to override),
REM reinforces A1 brain, tries pokerflex / -m / shim).
REM This eliminates duplication and ensures .bat double-click gets all future launcher polish.
REM Tray now default for always-visible advice surface.
python launch_assistant.py %*

echo.
echo Assistant exited. State/notes saved.
pause
endlocal

@echo off
setlocal
cd /d "%~dp0"

echo ================================================
echo  PokerFlex — Easy Install (pip + editable)
echo ================================================
echo.
echo This will:
echo   1. pip install -r requirements.txt
echo   2. pip install -e .   (editable install for `pokerflex` CLI + python -m pokerflex)
echo   (Optional for system tray: after above, pip install pystray  or  pip install "pokerflex[tray]")
echo.
echo After success you can use from anywhere (in this shell or new):
echo   python -m pokerflex --help
echo   pokerflex --help   (A1 brain UNAMBIGUOUS default; zero-touch bg via launch_assistant.bat)
echo   (double-click launch_assistant.bat for the one-click demo of live A1 + notes/ICM/explo)
echo.
echo On Windows, for real OCR/vision: install tesseract binary separately.
echo For some hotkey setups: run terminal as Administrator.
echo.

python -m pip install --upgrade pip

pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo ERROR: requirements install failed.
  pause
  exit /b 1
)

pip install -e .
if errorlevel 1 (
  echo.
  echo ERROR: editable install failed. Is setuptools available?
  pause
  exit /b 1
)

echo.
echo ================================================
echo  Install complete!
echo.
echo Primary documented way (A1 brain UNAMBIGUOUS default everywhere, zero flags needed):
echo   python -m pokerflex
echo.
echo After install, the `pokerflex` command also works:
echo   pokerflex --help
echo.
echo One-click demo (background sim live A1 + notes/explo/ICM/hotkeys):
echo   launch_assistant.bat
echo   (or python launch_assistant.py --real-vision for live ClubGG table)
echo.
echo For true background tray (minimized, no console clutter):
echo   (pip install pystray first)
echo   python -m pokerflex --tray --live --simulate-vision ...
echo   (or after build: the .exe --tray)
echo.
echo Standalone packaging (new): python build_exe.py [--onefile] [--noconsole]
echo   See build_exe.py header + "Deploy as background app" in readme for details + tesseract note.
echo.
echo See readme.md / quickstart.txt for full guide (hotkeys, notes, ICM, live mode, new brain default).
echo ================================================
echo.
pause
endlocal

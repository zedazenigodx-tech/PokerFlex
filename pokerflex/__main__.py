"""
PokerFlex top-level convenience entry point (RECOMMENDED LAUNCHER).

From project root (this is the zero-friction way to start the A1 real-time assistant):
  python -m pokerflex
  python -m pokerflex --help
  python -m pokerflex --background --pos BTN --stack 100 --auto-capture
  python -m pokerflex --background --tournament-mode --players-remaining 6 --stack 15

  # One-off analysis (no interactive)
  python -m pokerflex --once --pos BTN --hand AhKs --stack 100 --analyze
  python -m pokerflex --pos SB --hand 76o --stack 12 --tournament-mode --players-remaining 5 --analyze

Launches the A1 brain background / console runner (run_brain.py) with good defaults
(100bb deep, BTN, 2 opponents from CONFIG). Supports ALL run_brain CLI flags.

This is THE recommended launcher for the A1 brain (primary/default) real-time assistant.
- New A1 brain is ALWAYS THE UNAMBIGUOUS DEFAULT (no flags needed; see poker_engine.USE_NEW_BRAIN=True module default (pkg+root shims+all entries); `python -m pokerflex` or `pokerflex` is zero-touch; legacy debug ONLY via POKERFLEX_FORCE_LEGACY_BRAIN=1 env, never primary).
- Interactive console (type help or just hit ENTER to analyze) or --background for hotkey "set and forget".
- python pokerflex.py also works identically (root shim for compat).

ZERO-TOUCH BACKGROUND (true hands-off A1 while playing, auto vision listener + notes/explo/ICM):
  For simplest one-click: double-click launch_assistant.bat (or python launch_assistant.py)
    — always forces --background --live + sim (demo) or --real-vision, good defaults, seeds sample explo note, auto listener for vision state updates + auto rich A1.
  Or direct: python -m pokerflex --background --live --simulate-vision --pos BTN --stack 100 --auto-capture
    (real: ... --live --real-vision --periodic-capture 12 --auto-capture --vision-min-conf 0.28 --vision-min-consec 2 )
  Tray / invisible co-pilot: --tray (or packaged .exe --tray) for system tray icon + menu (Analyze Now, Status, Notes Quick, Run at startup toggle, Show Console, Quit). Hotkeys still global; quieter; popups + log for advice when hidden.
  Hotkeys (ctrl+alt+a etc), notes/explo, ICM/tourney, json watcher, auto state all seamless in bg. End-to-end with new A1 features.

After `pip install -e .`:
  - `python -m pokerflex` (primary documented)
  - `pokerflex` (console script entry point — added via setup.py + pyproject.toml [project.scripts])

The GUI remains available via `python main.py` (now also uses A1 by default via thin shim).
Force legacy exact old output for debug/comparison ONLY (new A1 is default with zero flags; legacy never primary):
  $env:POKERFLEX_FORCE_LEGACY_BRAIN=1; python -m pokerflex   (PowerShell)
  POKERFLEX_FORCE_LEGACY_BRAIN=1 python -m pokerflex        (bash)

See quickstart.txt and readme.md "Getting Started with the A1 Real-Time Assistant" for full guide.
"""
import os
import sys

# Make the package runnable via `python -m pokerflex` even when the pokerflex/
# subdir only contains a subset of modules (dev state). Add project root so we
# can import the real siblings (pokerflex.py's siblings: run_brain, advisor, etc).
# Note: root-level *.py are now thin shims delegating to this package.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Explicit module-level default for the primary `python -m pokerflex` entry point (A1 UNAMBIGUOUS default).
USE_NEW_BRAIN = True
# (reinforced again in main(); `python -m pokerflex` and `pokerflex` CLI are THE zero-touch A1 ways; legacy only if env forced)

# Ensure A1 new brain is the unambiguous default at module load for this launcher entry point.
# (poker_engine.py has the module-level default USE_NEW_BRAIN=True; legacy ONLY via POKERFLEX_FORCE_LEGACY_BRAIN=1 env.
# This + run_brain + launchers reinforce the default.)
try:
    from . import poker_engine as _pe
    if os.environ.get("POKERFLEX_FORCE_LEGACY_BRAIN", "").strip().lower() not in ("1", "true", "yes"):
        _pe.USE_NEW_BRAIN = True
except Exception:
    pass

# Early UTF-8 reconfigure for emoji-rich banners/help on Windows consoles.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

def main():
    # Belt-and-suspenders: ensure the new A1 brain is the UNAMBIGUOUS default experience here (USE_NEW_BRAIN=True).
    # (run_brain.py also reinforces; poker_engine.py now has explicit module default True; legacy ONLY if POKERFLEX_FORCE_LEGACY_BRAIN=1 forced for debug.)
    # Check for force-legacy env ONLY so legacy fallback continues to work when *explicitly* forced (never the default, never primary).
    try:
        from . import poker_engine
        if os.environ.get("POKERFLEX_FORCE_LEGACY_BRAIN", "").strip().lower() not in ("1", "true", "yes"):
            poker_engine.USE_NEW_BRAIN = True
    except Exception:
        try:
            import poker_engine
            if os.environ.get("POKERFLEX_FORCE_LEGACY_BRAIN", "").strip().lower() not in ("1", "true", "yes"):
                poker_engine.USE_NEW_BRAIN = True
        except Exception:
            pass
    # Also force on the root poker_engine shim module explicitly (covers `import poker_engine` after `python -m pokerflex` delegation).
    try:
        if os.environ.get("POKERFLEX_FORCE_LEGACY_BRAIN", "").strip().lower() not in ("1", "true", "yes"):
            import poker_engine as _root_pe_main
            _root_pe_main.USE_NEW_BRAIN = True
    except Exception:
        pass

    # Friendly one-line banner when invoked directly (before full runner output).
    # Helps confirm A1 for users with zero engineering effort (A1 is default).
    # Safe print (some consoles / powershell default encodings choke on emoji).
    if not any(a in ("--help", "-h", "--background", "-b", "--once", "--tray", "--self-test", "--bench", "--calibrate", "calibrate", "--leaks", "leaks", "leak", "review") for a in sys.argv[1:]):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        try:
            print("🧠 PokerFlex A1 — real-time assistant (GTO + 🎯explo + ICM; new brain default).")
            print("   Zero-touch: python -m pokerflex (or `pokerflex` CLI / launch_assistant.bat). Hotkeys: ctrl+alt+a (analyze), s (status), c (capture), o (overlay) — work in bg/live.")
            print("   Hands-off live: --background --live --simulate-vision (demo) or --real-vision. Notes/explo/ICM via 'note' cmd, json, or GUI (presets auto-seed 'nit' for demo explo in launch_assistant). See quickstart.txt.")
            print("   True bg tray UX (optional pystray): --tray (hides console on Win, tray menu + popups + 'run at startup' toggle). Example: python -m pokerflex --tray --live ...")
            print("   Calibrate once for real: python -m pokerflex calibrate ; verify: --self-test / --bench / --show-calibration. Interactive: action, notes edit, icm-sim, set payouts.")
            print("   Production: A1 brain unambiguous default (rich text, no flags); legacy debug via POKERFLEX_FORCE_LEGACY_BRAIN=1 only.")
        except Exception:
            print("[PokerFlex A1] real-time assistant (GTO + explo + ICM). Use --help or see quickstart.txt.")

    # Early subcommand support for zero-touch calibrate (before full delegation):
    # Allows `python -m pokerflex calibrate` (or calib) to launch wizard directly.
    # run_brain also handles --calibrate flag + argv check for full compat.
    argv_tail = sys.argv[1:] if len(sys.argv) > 1 else []
    if argv_tail and argv_tail[0].lower() in ("calibrate", "calib", "calibration"):
        # Support --client after subcommand, e.g. `python -m pokerflex calibrate --client coinpoker`
        calib_cli = None
        for i, a in enumerate(argv_tail[1:], 1):
            if a in ("--client", "-c") and i+1 < len(argv_tail):
                calib_cli = argv_tail[i+1]
                break
            if a.startswith("--client="):
                calib_cli = a.split("=", 1)[1]
                break
        try:
            from . import calibration as _calib
            _calib.run_calibration_wizard(client=calib_cli)
            return
        except Exception as ex:
            print(f"[calib] direct launch failed: {ex}")
            # fallthrough to run_brain which has robust fallback handling

    # Early subcommand support for leaks/review (lightweight; pattern like calibrate).
    # Allows `python -m pokerflex leaks` (or leak/review) to run directly without full bg setup.
    # run_brain.main also handles --leaks + argv for full compat (interactive + flag).
    if argv_tail and argv_tail[0].lower() in ("leaks", "leak", "review"):
        try:
            from .run_brain import do_leak_review as _do_leak
            _do_leak()
            return
        except Exception as ex:
            print(f"[leaks] direct subcommand launch failed: {ex}")
            # fallthrough to run_brain handler

    # Delegate entirely to the full-featured A1 runner.
    # run_brain.main() handles argparse, preload of new brain, hotkeys, watcher, interactive/bg.
    # (run_brain also catches --calibrate / reset / show + subcmd variants and exits early.)
    try:
        from .run_brain import main as _run_brain_main
    except Exception:
        from run_brain import main as _run_brain_main
    _run_brain_main()

if __name__ == "__main__":
    # When invoked as `python -m pokerflex` (or python pokerflex.py via root shim), forward to runner.
    # If extra args were passed on CLI they are already in sys.argv and will be parsed by run_brain.
    main()

"""
PokerFlex A1 Brain - Background Runner / Console Mode — ROOT COMPAT SHIM (A1 default; new is unambiguous primary). Supports --client coinpoker|clubgg (delegates to pkg).

RECOMMENDED: use `python -m pokerflex` (or the `pokerflex` CLI after install).

This root run_brain.py is a thin shim for backward compat so `python run_brain.py` (and docs examples)
continue to work from the project root. It ensures the package is importable and delegates.
All runs default to A1 new brain (USE_NEW_BRAIN=True module default UNAMBIGUOUS in poker_engine + all shims/entries; legacy only via explicit POKERFLEX_FORCE_LEGACY_BRAIN=1 for debug, never primary). `python -m pokerflex` is primary zero-touch.

All implementation (incl --live auto vision with partial/conf/sensitivity/min-conf/partial-min-conf/sim-scenario/real-vision, --vision-debug, robust listener integration with stack/pos auto-extract + deeper tmode stack delta trigger, manual fallback, expanded sim scenarios demo/icm/cash/tourney/mixed, NEW --vision-retries + merge_board_fragment for incremental partials in live; LATEST --vision-preproc + aggressive preproc defaults for real + enhanced OCR/partial recovery in capture) is now in the `pokerflex` package (pokerflex/run_brain.py).
See there for updated docs/comments. (New CLI --vision-debug + --vision-partial-conf + --vision-retries + --vision-preproc for live vision sensitivity/partial/OCR-preproc tuning + capture reliability; sim scenarios + smart merge + preproc for richer E2E tests of notes+ICM+partials+street progression in set-and-forget real/sim vision.)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Explicit module-level default for root run_brain shim (A1 UNAMBIGUOUS default everywhere).
USE_NEW_BRAIN = True

# Reinforce A1 default on shim import for direct python run_brain.py
try:
    if os.environ.get("POKERFLEX_FORCE_LEGACY_BRAIN", "").strip().lower() not in ("1", "true", "yes"):
        import pokerflex.poker_engine as _pe
        _pe.USE_NEW_BRAIN = True
        import poker_engine as _rpe
        _rpe.USE_NEW_BRAIN = True
except Exception:
    pass

from pokerflex.run_brain import main

if __name__ == "__main__":
    main()

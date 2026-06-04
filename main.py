"""
PokerFlex GUI (main.py) — ROOT COMPAT SHIM (A1 brain UNAMBIGUOUS default; new brain is primary everywhere).

RECOMMENDED primary: `python -m pokerflex` for the A1 console/background runner.
The GUI is still available as `python main.py` for users who prefer the windowed form (now powered by A1 new brain THE DEFAULT).

This root main.py is a thin shim so direct `python main.py` continues to work from project root.
Delegates to the packaged GUI in pokerflex/main.py (which uses A1 new brain by default via poker_engine.USE_NEW_BRAIN=True module default; GUI title + output reflect A1).

After packaging/install, you can also `python -m pokerflex.main` in theory, but the root shim + `python main.py` is preserved.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Explicit module-level default for root GUI shim (A1 UNAMBIGUOUS default; GUI shows A1 by default).
USE_NEW_BRAIN = True

# Ensure A1 default even for direct python main.py (GUI uses get_advice which honors the flag).
try:
    if os.environ.get("POKERFLEX_FORCE_LEGACY_BRAIN", "").strip().lower() not in ("1", "true", "yes"):
        import pokerflex.poker_engine as _pe
        _pe.USE_NEW_BRAIN = True
        import poker_engine as _rpe
        _rpe.USE_NEW_BRAIN = True
except Exception:
    pass

from pokerflex.main import main

if __name__ == "__main__":
    main()

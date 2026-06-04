"""
PokerFlex top-level convenience entry point (RECOMMENDED LAUNCHER) — COMPAT SHIM.

Primary ways (see packaging):
  python -m pokerflex                 # documented primary (works from source tree or after install)
  pip install -e . ; pokerflex        # CLI entry point after editable/global install

This root pokerflex.py is a thin backward-compat shim so that
`python pokerflex.py` (and python -m when no package) continues to work from the project root
even without `pip install`.

It ensures the local pokerflex/ package is importable and delegates to the packaged implementation.
All real logic lives in pokerflex/__main__.py and the package modules (A1 default).

From project root:
  python -m pokerflex
  python pokerflex.py   # this shim
  python -m pokerflex --help
  ... (all flags)

Zero-touch bg live A1 (auto everything): double-click launch_assistant.bat or python launch_assistant.py [--real-vision ...]

See readme.md and quickstart.txt for full docs. New A1 brain is THE UNAMBIGUOUS default (USE_NEW_BRAIN=True at module level in poker_engine.py + ALL launchers/entry points/`python -m pokerflex`/GUI; legacy only via POKERFLEX_FORCE_LEGACY_BRAIN=1 for debug, never primary or in normal use).

For zero-touch background A1 assistant (recommended one-click): use launch_assistant.bat (double-click) or python launch_assistant.py (always forces --background --live + good defaults for sim/real vision, auto listener, hotkeys, notes/explo, ICM, watcher).
"""
import os
import sys

# Ensure the local pokerflex/ package (with __init__.py) is discoverable for direct `python pokerflex.py` runs
# (works alongside `python -m pokerflex` which finds the subdir package automatically).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Explicit module-level default here for the root launcher shim (A1 is UNAMBIGUOUS default; legacy never primary).
# Reinforced on the real poker_engine too.
USE_NEW_BRAIN = True

# Delegate to the packaged entry (supports both source tree and after `pip install -e .`)
from pokerflex.__main__ import main

# Reinforce A1 new brain default for any direct `python pokerflex.py` path (module load).
# (poker_engine sets it; this is extra belt for `import poker_engine` side effects or early imports.)
try:
    if os.environ.get("POKERFLEX_FORCE_LEGACY_BRAIN", "").strip().lower() not in ("1", "true", "yes"):
        import pokerflex.poker_engine as _pe
        _pe.USE_NEW_BRAIN = True
        # also the root shim module if someone imported it
        import poker_engine as _root_pe
        _root_pe.USE_NEW_BRAIN = True
except Exception:
    pass

if __name__ == "__main__":
    main()

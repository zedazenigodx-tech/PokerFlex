"""
PokerFlex/pokerflex.py (inside package) — re-export launcher shim (for compat). A1 default.

This file re-exports the entry point logic from __main__.py (A1 default).
The canonical ways are:
  python -m pokerflex
  from pokerflex.__main__ import main
  (root-level pokerflex.py for direct `python pokerflex.py`)

Re-export for any accidental imports; delegates to the real __main__ (A1 default).
"""

from . import __main__ as _main

# A1 is the UNAMBIGUOUS default (reexport of launcher).
USE_NEW_BRAIN = True

def main(*a, **k):
    return _main.main(*a, **k)

if __name__ == "__main__":
    main()

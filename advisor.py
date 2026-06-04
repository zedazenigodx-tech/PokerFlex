"""
PokerFlex A1 - Main GTO Heuristic Advisor (PRIMARY / DEFAULT BRAIN) — ROOT COMPAT SHIM.

RECOMMENDED primary: `python -m pokerflex` (or `from pokerflex.advisor import ...` after install / -e).
The GUI (`python main.py`), runner, and direct get_advice all default to A1 via the thin shim.

This root advisor.py is a thin backward-compat shim so direct `python advisor.py` and
`import advisor` (from project root) continue to work for docs/examples/dev.

All implementation now lives in the `pokerflex` package (pokerflex/advisor.py uses relative imports + new structure).

New A1 brain (via GTOHeuristicAdvisor + preflop/postflop) is the UNAMBIGUOUS default everywhere (USE_NEW_BRAIN=True module default; legacy only via POKERFLEX_FORCE_LEGACY_BRAIN=1 never primary). Use `python -m pokerflex`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokerflex.advisor import *

if __name__ == "__main__":
    print("PokerFlex advisor (A1 primary brain) — use via `python -m pokerflex` or package for full experience.")

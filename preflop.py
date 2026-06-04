"""
PokerFlex A1 - Preflop Strategy Module (part of primary A1 brain) — ROOT COMPAT SHIM.

Handles preflop regimes, open ranges, Nash push/fold + ICM. Used by default (A1 UNAMBIGUOUS; legacy debug only via force).

RECOMMENDED primary usage via the A1 runner / get_advice (new brain UNAMBIGUOUS default).

This root preflop.py is a thin shim for compat so `import preflop` etc from root works.

Implementation in pokerflex/preflop.py .
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokerflex.preflop import *

if __name__ == "__main__":
    print("PokerFlex preflop (A1 primary) — prefer `python -m pokerflex` or package.")

"""
PokerFlex A1 - Postflop Strategy (Strong Heuristic GTO) — primary brain module — ROOT COMPAT SHIM.

Texture-aware, range/nut adv, blockers, explo notes adjustments, sizing. Used by default (A1 UNAMBIGUOUS; legacy only debug fallback).

RECOMMENDED: via advisor / get_advice (new brain UNAMBIGUOUS default) or from pokerflex.postflop

This root postflop.py is thin shim so direct imports / python postflop.py from root continue working.

All logic in pokerflex/postflop.py (pluggable via advisor).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokerflex.postflop import *

if __name__ == "__main__":
    print("PokerFlex postflop (A1 primary) — prefer package or `python -m pokerflex`.")

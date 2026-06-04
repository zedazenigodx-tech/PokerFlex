"""
PokerFlex A1 - Parsing Layer (shared by primary A1 brain + legacy shim when forced for debug ONLY) — ROOT COMPAT SHIM.

Core card parsing, hand classification, position normalization centralized here (used by poker_engine shim + new brain).

RECOMMENDED: from pokerflex.parsing import ...

This root parsing.py is a thin backward-compat shim so direct imports and old scripts continue to work from project root.

All real code in pokerflex/parsing.py (new structure, shared with legacy debug shim only).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokerflex.parsing import *

if __name__ == "__main__":
    print("PokerFlex parsing (A1) — use package imports or python -m pokerflex.")

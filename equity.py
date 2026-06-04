"""
PokerFlex A1 - Equity Calculations (shared by primary A1 brain + legacy shim when forced for debug ONLY) — ROOT COMPAT SHIM.

Central equity (vs random + vs range). Shared so new A1 (default) and legacy (debug) produce consistent numbers.

RECOMMENDED: from pokerflex.equity ...

This root equity.py shim keeps `import equity` working from project root.

Real code: pokerflex/equity.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokerflex.equity import *

if __name__ == "__main__":
    print("PokerFlex equity (A1) — use via package or -m pokerflex.")

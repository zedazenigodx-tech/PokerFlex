"""
PokerFlex A1 - Range Management (core for primary A1 preflop + explo) — ROOT COMPAT SHIM.

Range objects, parse_range, get_open_range, load_preflop_ranges, constants. Shared with legacy (forced debug ONLY, never primary).

RECOMMENDED: from pokerflex.ranges ...

This root ranges.py shim (content was identical) eliminates source duplication.

"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokerflex.ranges import *

if __name__ == "__main__":
    print("PokerFlex ranges (A1) — use package.")

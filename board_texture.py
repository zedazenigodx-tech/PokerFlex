"""
PokerFlex A1 - Board Texture Analyzer (used by primary A1 postflop brain) — ROOT COMPAT SHIM.

Rich deterministic texture (paired, flush/straight categories, dynamic). Used for range/nut adv.

RECOMMENDED via pokerflex.board_texture or through advisor.

This root board_texture.py is thin compat shim.

Implementation centralized in pokerflex/board_texture.py (new structure).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokerflex.board_texture import *

if __name__ == "__main__":
    print("PokerFlex board_texture (A1) — package preferred.")

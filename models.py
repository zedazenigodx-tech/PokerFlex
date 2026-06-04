"""
PokerFlex A1 - Core Data Models (PRIMARY BRAIN) — ROOT COMPAT SHIM.

GameState is the contract/single source of truth.
legacy_to_gamestate bridge (for compat), PlayerNotesManager for explo, Decision/Action etc. (A1 default; legacy only debug).

RECOMMENDED: from pokerflex.models import GameState, legacy_to_gamestate, ...

This root models.py shim ensures old direct imports from project root keep working.

Full implementation + GameState contract in pokerflex/models.py .
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokerflex.models import *

if __name__ == "__main__":
    print("PokerFlex models (A1 GameState etc) — use `python -m pokerflex` / package.")

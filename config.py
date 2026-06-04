"""
PokerFlex A1 Brain Configuration (PRIMARY / UNAMBIGUOUS DEFAULT) — ROOT COMPAT SHIM.

All tunables for A1 brain (unambiguous new default), including force_legacy_brain=False, exploitative_mode, icm_*, runner defaults. Legacy force via POKERFLEX_FORCE_LEGACY_BRAIN=1 env (debug ONLY, never primary or default; A1 is default everywhere).

RECOMMENDED: from pokerflex.config import CONFIG

This root config.py is thin shim for compat (was identical; now delegates to avoid dupe).

"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokerflex.config import *

if __name__ == "__main__":
    print("PokerFlex config (A1) — package is source of truth.")

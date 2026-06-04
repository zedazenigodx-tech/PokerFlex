"""
Simple Voice Input for Grok session — ROOT COMPAT SHIM.

Run: python voice_input.py

RECOMMENDED: python -m pokerflex or from pokerflex.voice_input

This root voice_input.py is thin shim (was in sync).

"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokerflex.voice_input import *

if __name__ == "__main__":
    print("PokerFlex voice_input (A1) — use package / -m .")

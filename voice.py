"""
PokerFlex Voice Module — Integrated voice capture for the Grok session. — ROOT COMPAT SHIM.

Usage: from voice import capture_voice

RECOMMENDED via package: from pokerflex.voice ...

This root voice.py shim for compat (was identical).

"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokerflex.voice import *

if __name__ == "__main__":
    print("PokerFlex voice (A1) — package preferred.")

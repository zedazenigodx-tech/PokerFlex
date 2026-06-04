"""
PokerFlex capture — grab the poker client window (ClubGG/CoinPoker or full screen) to a PNG + real-time vision pipeline. — ROOT COMPAT SHIM.

Multi-client (clubgg default, coinpoker) with 0-touch A1: client abstraction, auto title detect, per-client vision_config_*.json, get_poker_rois etc.
ClubGG ROIs (compat), cv2 detection, pytesseract OCR + fallbacks, simulate_table_state(client=), capture_and_parse(client=), capture_clubgg_image(client=) + capture_poker_image alias.
Used by --live / --auto-capture / GUI for vision. No breakage for ClubGG-only calls.

RECOMMENDED: from pokerflex.capture import ...

This root capture.py is thin compat shim (reexports *) to keep direct usage working. A1 default via python -m pokerflex --live (add --client coinpoker or let auto-detect from title).

Implementation in pokerflex/capture.py (client abstraction added per spec: find/capture/attempt/capture_and_parse/simulate/get_*_rois/load+save vision_config updated + docs; per-client profiles + auto + hints incl "coinpoker" etc; defaults clubgg).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokerflex.capture import *

if __name__ == "__main__":
    print("PokerFlex capture/vision (A1) — use via runner or package import.")

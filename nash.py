"""
PokerFlex Nash solver (nash.py) — ROOT COMPAT SHIM.

Run the solver / matrix builder via:
  python -m pokerflex.nash
or from root: python nash.py (this shim)

Primary app entry is python -m pokerflex (A1 default).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pokerflex.nash import main

if __name__ == "__main__":
    main()

"""
PokerFlex engine (self-tests + A1 UNAMBIGUOUS default + legacy fallback router ONLY when forced for debug) — ROOT COMPAT SHIM.

Run tests: python poker_engine.py (this shim) or python -m pokerflex.poker_engine

Primary: python -m pokerflex  (A1 new brain is THE UNAMBIGUOUS default everywhere — THE zero-touch entry; legacy debug only via POKERFLEX_FORCE_LEGACY_BRAIN=1)
"""
import os
import sys
import runpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Explicit module-level default for this root compat shim (A1 UNAMBIGUOUS default).
# Reinforced from the package which also declares USE_NEW_BRAIN = True at its module level.
# Legacy ONLY via POKERFLEX_FORCE_LEGACY_BRAIN=1 (debug, never primary).
USE_NEW_BRAIN = True
# Belt: re-affirm immediately (in case of import order); all launchers do the same for zero-touch A1.

# Forward public A1 / legacy API so that root-level "import poker_engine" (used by
# launch_assistant.py etc for the env/attr force) sees the symbols and allows
# USE_NEW_BRAIN mutation (harmless for child but makes launcher code paths clean).
# All real impl in pokerflex.poker_engine (A1 new brain UNAMBIGUOUS default).
from pokerflex.poker_engine import (
    USE_NEW_BRAIN,
    get_advice,
    set_explo_notes,
    get_explo_notes,
    use_nit_preset,
    use_station_preset,
    use_aggro_preset,
    clear_explo_notes,
    list_explo_players,
    # also the legacy reexports for direct 'import poker_engine' compat
    parse_cards,
    hand_class,
    hand_class_from_str,
    normalize_position,
    equity_vs_random,
    RANGES,
    POSITIONS,
)

# Belt-and-suspenders for root `import poker_engine` path: ensure module-level default
# USE_NEW_BRAIN=True (A1) unless legacy explicitly forced. This makes `import poker_engine`
# (as used by some launch shims / tests / direct) see unambiguous A1 default too.
# (The package sets it at its load; we re-affirm here for root shim users.)
_FORCE_LEGACY_ENV_ROOT = os.environ.get("POKERFLEX_FORCE_LEGACY_BRAIN", "").strip().lower() in ("1", "true", "yes")
if not _FORCE_LEGACY_ENV_ROOT:
    try:
        import pokerflex.poker_engine as _pkg_pe_for_root
        _pkg_pe_for_root.USE_NEW_BRAIN = True
        # Update our local name binding too (for any code that did `from poker_engine import USE_NEW_BRAIN`)
        # Note: direct attr set on this module will also work for `import poker_engine; poker_engine.USE_NEW_BRAIN = `
        USE_NEW_BRAIN = True
    except Exception:
        pass

if __name__ == "__main__":
    runpy.run_module("pokerflex.poker_engine", run_name="__main__", alter_sys=True)

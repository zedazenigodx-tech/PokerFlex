"""
PokerFlex A1 GTO Brain package.

Primary real-time assistant launcher:
  python -m pokerflex
  pokerflex   (after `pip install -e .` or build + install)

New A1 brain is the unambiguous default (USE_NEW_BRAIN=True module level + everywhere).

See readme.md / quickstart.txt for usage, hotkeys, explo notes, ICM, etc.

After install:
  - `python -m pokerflex` always works (runs __main__.py)
  - `pokerflex` console script (entry point) works for the CLI.
"""
import os

__version__ = "1.0.0"

# Re-export key public API for convenience (new A1 brain UNAMBIGUOUS primary/default).
# Relative imports keep the package self-contained for `python -m pokerflex`
# (from source) or after `pip install -e .` / distribution.
from .poker_engine import (
    get_advice,
    set_explo_notes,
    get_explo_notes,
    use_nit_preset,
    use_station_preset,
    use_aggro_preset,
    clear_explo_notes,
    list_explo_players,
    USE_NEW_BRAIN,
)

# Reinforce A1 default on package import (module reexports the var; value from poker_engine which defaults True).
if os.environ.get("POKERFLEX_FORCE_LEGACY_BRAIN", "").strip().lower() not in ("1", "true", "yes"):
    try:
        from . import poker_engine as _pe_init
        _pe_init.USE_NEW_BRAIN = True
    except Exception:
        pass

from .models import (
    GameState,
    legacy_to_gamestate,
    ActionEvent,
    get_player_notes,
    set_player_notes,
    PlayerNotesManager,
)

from .advisor import get_advisor, format_a1_advice
from .overlay import AdviceOverlay, get_overlay, show_advice

__all__ = [
    "get_advice",
    "get_advisor",
    "format_a1_advice",
    "legacy_to_gamestate",
    "GameState",
    "ActionEvent",
    "set_explo_notes",
    "get_explo_notes",
    "use_nit_preset",
    "use_station_preset",
    "use_aggro_preset",
    "clear_explo_notes",
    "list_explo_players",
    "get_player_notes",
    "set_player_notes",
    "PlayerNotesManager",
    "USE_NEW_BRAIN",
    "AdviceOverlay",
    "get_overlay",
    "show_advice",
    "__version__",
]

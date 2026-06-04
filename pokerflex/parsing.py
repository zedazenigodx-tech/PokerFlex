"""
PokerFlex A1 - Parsing Layer (shared by primary A1 brain + legacy shim for forced debug compat ONLY)

Responsible for turning raw user input (and later vision output) into clean GameState objects.
Core card parsing, hand classification, and position normalization live here
so that poker_engine.py can be a thin router (A1 UNAMBIGUOUS default + legacy compat shim when forced for debug). Primary use: python -m pokerflex .
"""

from typing import List, Dict, Optional, Any
from treys import Card

# Source of truth for ranks/suits (avoid duplication)
from .ranges import RANK_VAL, SUITS, RANK_ORDER


# --------------------------------------------------------------------------- #
# Core parsing helpers (moved from poker_engine.py for centralization)
# These keep legacy get_advice() behavior 100% identical when used by shim (only on force).
# poker_engine re-exports/imports them for A1 (unambiguous default) + legacy fallback (forced) paths.
# --------------------------------------------------------------------------- #

def parse_cards(text):
    """'AhKs' or 'Ah Ks' or 'Ah,Ks' or shorthand class '76o'/'AKs'/'22' -> list of treys card ints. Validates.
    Shorthand like 76o (from docs/CLI examples/current_state.json) is supported by synthesizing
    explicit suited cards (different suits for 'o', same for 's' or pairs). Suits chosen arbitrarily
    but valid (real suits don't matter for preflop nash/ICM, and for postflop the class is re-derived).
    """
    if not text or not text.strip():
        return []
    raw = "".join(ch for ch in text if not ch.isspace() and ch != ",").upper()
    s = raw
    # Support shorthand hand classes e.g. '76o', 'A9s', '22', 'AKo' (len==2 for pairs, len==3 for others)
    if len(raw) in (2, 3):
        r1 = raw[0]
        r2 = raw[1]
        if r1 not in RANK_VAL or r2 not in RANK_VAL:
            pass  # will fail later validation
        else:
            if len(raw) == 2:
                # pair e.g. '22' or 'AA' -> different suits (cards must be unique)
                suit1 = 's'
                suit2 = 'h'
            else:
                third = raw[2]
                is_suited = third == 'S'
                suit1 = 's'
                suit2 = 's' if is_suited else 'h'
            s = r1 + suit1 + r2 + suit2
    if len(s) % 2 != 0:
        raise ValueError(f"'{text}' is not a whole number of cards (need rank+suit each, e.g. AhKs or 76o/AKs/22 shorthand)")
    cards, seen = [], set()
    for i in range(0, len(s), 2):
        rank, suit = s[i].upper(), s[i + 1].lower()
        if rank not in RANK_VAL:
            raise ValueError(f"bad rank '{s[i]}' in '{text}' (use 2-9,T,J,Q,K,A)")
        if suit not in SUITS:
            raise ValueError(f"bad suit '{s[i+1]}' in '{text}' (use s,h,d,c)")
        key = rank + suit
        if key in seen:
            raise ValueError(f"duplicate card {key} in '{text}'")
        seen.add(key)
        cards.append(Card.new(rank + suit))
    return cards


def hand_class(c1_str, c2_str):
    """Two card strings -> normalized class: 'AA', 'AKs', 'AKo', 'T9s'."""
    r1, s1 = c1_str[0].upper(), c1_str[1].lower()
    r2, s2 = c2_str[0].upper(), c2_str[1].lower()
    if RANK_VAL[r1] < RANK_VAL[r2]:
        r1, r2, s1, s2 = r2, r1, s2, s1
    if r1 == r2:
        return r1 + r2
    return r1 + r2 + ("s" if s1 == s2 else "o")


def hand_class_from_str(text):
    s = "".join(ch for ch in text if not ch.isspace() and ch != ",")
    if len(s) != 4:
        raise ValueError("hole hand must be exactly 2 cards, e.g. AhKs")
    return hand_class(s[0:2], s[2:4])


def cards_to_strings(treys_cards):
    """Convert treys ints back to human strings like ['Ah', 'Ks']."""
    return [Card.int_to_str(c) for c in (treys_cards or [])]


_POS_ALIASES = {
    "UTG": "UTG", "EP": "UTG", "UTG1": "UTG", "LJ": "MP", "HJ": "MP",
    "MP": "MP", "MP1": "MP", "MP2": "MP", "CO": "CO", "CUTOFF": "CO",
    "BTN": "BTN", "BU": "BTN", "BUTTON": "BTN", "D": "BTN", "DEALER": "BTN",
    "SB": "SB", "SMALLBLIND": "SB", "BB": "BB", "BIGBLIND": "BB",
}


def normalize_position(text):
    if not text:
        return None
    t = text.upper().replace(" ", "").replace("_", "").replace("-", "")
    return _POS_ALIASES.get(t)


def _street(board):
    """Map board length to street name. Kept for legacy path compat only."""
    return {0: "Preflop", 3: "Flop", 4: "Turn", 5: "River"}.get(len(board))


# --------------------------------------------------------------------------- #
# GameState builder (uses local parsers; fixed card->str conversion bug)
# --------------------------------------------------------------------------- #

def build_game_state(
    position: str = "",
    hand: str = "",
    board: str = "",
    opponents: str = "",
    stack: str = "",
    ante: str = "",
    player_notes: Optional[Dict[str, Any]] = None,
) -> "GameState":
    """
    Main entry point for converting legacy string input into GameState.
    This will get smarter over time.
    """
    # Local import to prevent circular import (models <-> parsing via types)
    from .models import GameState, Board, Street

    hero_cards = parse_cards(hand) if hand.strip() else []
    board_cards = parse_cards(board) if board.strip() else []

    street = Street.PREFLOP if not board_cards else Street(len(board_cards))

    b = Board(cards=cards_to_strings(board_cards), street=street)

    try:
        n_opp = max(1, int("".join(c for c in opponents if c.isdigit()) or 1))
    except Exception:
        n_opp = 1

    try:
        bb = float("".join(c for c in stack if c.isdigit() or c == ".") or 100)
    except Exception:
        bb = 100.0

    try:
        ante_bb = float("".join(c for c in ante if c.isdigit() or c == ".") or 0)
    except Exception:
        ante_bb = 0.0

    pot = 1.5 + ante_bb
    if street != Street.PREFLOP:
        pot += 2.0  # rough assumption of a raise

    gs = GameState(
        hero_hand=cards_to_strings(hero_cards),
        board=b,
        effective_stack=bb,
        num_opponents=n_opp,
        pot=pot,
        hero_position=normalize_position(position) or position,
        action_history=[],  # history via legacy_to or direct append; parsing builder keeps empty for compat
    )
    if player_notes:
        gs.player_notes = dict(player_notes)
    return gs

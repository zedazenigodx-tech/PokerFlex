"""
PokerFlex A1 - Range Management (core for primary A1 preflop + explo)

Handles preflop ranges, Range objects, and basic range operations.
This is a core piece for GTO (A1 default everywhere) + exploitative play. Shared with legacy (forced debug ONLY, never primary) path.
"""

from dataclasses import dataclass, field
from typing import Dict, Set, List, Optional

RANK_ORDER = "23456789TJQKA"
RANK_VAL = {r: i for i, r in enumerate(RANK_ORDER, start=2)}
SUITS = "shdc"

# Current reference ranges (moved from poker_engine.py)
RANGE_TOKENS = {
    "UTG": ["22+", "A2s+", "K9s+", "Q9s+", "J9s+", "T9s", "98s", "87s", "76s",
            "65s", "54s", "AJo+", "KQo"],
    "MP":  ["22+", "A2s+", "K8s+", "Q9s+", "J9s+", "T8s+", "97s+", "86s+",
            "75s+", "65s", "54s", "ATo+", "KJo+", "QJo"],
    "CO":  ["22+", "A2s+", "K5s+", "Q8s+", "J8s+", "T8s+", "97s+", "86s+",
            "75s+", "64s+", "54s", "A8o+", "K9o+", "Q9o+", "J9o+", "T9o"],
    "BTN": ["22+", "A2s+", "K2s+", "Q4s+", "J6s+", "T6s+", "96s+", "85s+",
            "74s+", "64s+", "53s+", "43s", "A2o+", "K7o+", "Q8o+", "J8o+",
            "T8o+", "98o", "87o"],
    "SB":  ["22+", "A2s+", "K2s+", "Q5s+", "J7s+", "T7s+", "96s+", "86s+",
            "75s+", "64s+", "54s", "A4o+", "K8o+", "Q9o+", "J9o+", "T9o"],
}


@dataclass
class Range:
    """
    Represents a poker range with combo weights.
    weights: dict of hand class -> weight (0.0 to 1.0)
    """
    weights: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_tokens(cls, tokens: List[str]) -> "Range":
        """Create a Range from list of range tokens like ['22+', 'AKs']."""
        weights = {}
        for tok in tokens:
            for h in expand_token(tok):
                weights[h] = 1.0
        return cls(weights=weights)

    @classmethod
    def from_hand_list(cls, hands: List[str]) -> "Range":
        """Create from list of specific hand classes."""
        return cls(weights={h: 1.0 for h in hands})

    def total_combos(self) -> float:
        # Approximate: pairs=6, suited=4, offsuit=12
        total = 0.0
        for h, w in self.weights.items():
            if len(h) == 2:  # pair
                total += 6 * w
            elif h[2] == 's':
                total += 4 * w
            else:
                total += 12 * w
        return total

    def pct(self) -> float:
        """Percentage of all possible hands."""
        # Total combos in deck = 1326
        return (self.total_combos() / 1326.0) * 100

    def block(self, blocked: List[str]) -> "Range":
        """Return a new range with hands blocked by specific cards (for future use)."""
        # Simplified: for now just return self. Real version would remove combos containing blocked cards.
        return Range(weights=self.weights.copy())

    def contains(self, hand_class: str) -> bool:
        return hand_class in self.weights and self.weights[hand_class] > 0.0


# Standard ~100bb 6-max RFI reference ranges.
PREFLOP_OPEN_RANGES: Dict[str, Range] = {}


def expand_token(tok: str) -> Set[str]:
    """Expand a range token into a set of hand classes. (moved from poker_engine.py)"""
    tok = tok.strip()
    plus = tok.endswith("+")
    core = tok[:-1] if plus else tok

    if len(core) == 2 and core[0] == core[1]:          # pair
        v = RANK_VAL[core[0]]
        if plus:
            return {r + r for r in RANK_ORDER if RANK_VAL[r] >= v}
        return {core}

    hi, lo, suit = core[0], core[1], core[2]            # XYs / XYo
    hv, lv = RANK_VAL[hi], RANK_VAL[lo]
    if plus:
        return {hi + RANK_ORDER[v - 2] + suit for v in range(lv, hv)}
    return {hi + lo + suit}


def parse_range(tokens: List[str]) -> Set[str]:
    out = set()
    for t in tokens:
        out |= expand_token(t)
    return out


def load_preflop_ranges():
    """Load and expand the reference preflop ranges into Range objects."""
    global PREFLOP_OPEN_RANGES
    PREFLOP_OPEN_RANGES = {}
    for pos, tokens in RANGE_TOKENS.items():
        hand_set = parse_range(tokens)
        PREFLOP_OPEN_RANGES[pos] = Range.from_hand_list(list(hand_set))
    return PREFLOP_OPEN_RANGES


def get_open_range(position: str) -> Range:
    """Returns the Range object for opening from a given position."""
    if not PREFLOP_OPEN_RANGES:
        load_preflop_ranges()
    return PREFLOP_OPEN_RANGES.get(position, Range())


def is_in_open_range(hand_class: str, position: str) -> bool:
    """Quick check if a hand is in the open range for a position."""
    r = get_open_range(position)
    return r.contains(hand_class)


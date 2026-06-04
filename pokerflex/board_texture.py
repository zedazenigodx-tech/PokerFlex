"""
PokerFlex A1 - Board Texture Analyzer (used by primary A1 postflop brain)

This module provides rich, deterministic analysis of board textures.
Used heavily for range advantage, nut advantage, and sizing decisions.
"""

from typing import List, Optional, Tuple
from dataclasses import dataclass
from .models import BoardTexture

# Canonical rank/suit constants (source of truth in ranges.py)
from .ranges import RANK_ORDER, RANK_VAL, SUITS


def _rank_val(r: str) -> int:
    return RANK_VAL.get(r.upper(), 0)


def analyze_board(cards: List[str]) -> BoardTexture:
    """
    Analyze a list of board cards (3, 4 or 5) and return a rich BoardTexture.
    Cards should be like ['Qd', '7h', '2c']
    """
    if not cards:
        return BoardTexture()

    ranks = [c[0].upper() for c in cards]
    suits = [c[1].lower() for c in cards]

    # Pair analysis
    from collections import Counter
    rank_counts = Counter(ranks)
    pairs = [r for r, cnt in rank_counts.items() if cnt >= 2]
    paired = len(pairs) > 0
    pair_rank = max(pairs, key=_rank_val) if pairs else None
    trips = any(cnt >= 3 for cnt in rank_counts.values())
    quads = any(cnt >= 4 for cnt in rank_counts.values())

    # Flush analysis
    suit_counts = Counter(suits)
    max_suit = max(suit_counts.values()) if suit_counts else 0
    if max_suit >= 3:
        flush_category = "monotone"   # flop 3-same or turn/river 3+ same suit = monotone (strong flush draw / made flush boards)
        has_flush_draw = True
    elif max_suit == 2:
        flush_category = "two_tone"
        has_flush_draw = False
    else:
        flush_category = "rainbow"
        has_flush_draw = False

    # Straight / connectivity analysis
    unique_ranks = sorted(set(ranks), key=_rank_val)
    vals = sorted(set(_rank_val(r) for r in ranks))

    # Check for wheel (A-5 straight)
    wheel = False
    if 14 in vals and 5 in vals:  # A and 5
        wheel_vals = [v for v in vals if v <= 5] + [1]  # treat A as 1 for wheel
        wheel = _is_connected(wheel_vals)

    connected_score = _connectivity_score(vals)
    if connected_score >= 3:
        straight_category = "very_connected"
    elif connected_score >= 1.5:
        straight_category = "semi_connected"
    else:
        straight_category = "dry"

    has_straight_draw = connected_score >= 2 or wheel

    # High card
    high_card = max(ranks, key=_rank_val)

    # Dynamic score: how much the board can change on future streets
    # Higher if connected or suited
    dynamic = 0.0
    if straight_category == "very_connected":
        dynamic += 0.4
    elif straight_category == "semi_connected":
        dynamic += 0.25
    if flush_category in ("two_tone", "monotone"):
        dynamic += 0.35
    dynamic = min(dynamic, 1.0)

    # For paired boards, slightly less dynamic usually
    if paired:
        dynamic *= 0.85

    return BoardTexture(
        paired=paired,
        pair_rank=pair_rank,
        flush_category=flush_category,
        straight_category=straight_category,
        high_card=high_card,
        dynamic_score=dynamic,
        has_flush_draw=has_flush_draw,
        has_straight_draw=has_straight_draw,
    )


def _is_connected(vals: List[int]) -> bool:
    """Check if sorted unique vals form a straight."""
    if len(vals) < 3:
        return False
    for i in range(len(vals) - 2):
        if vals[i+2] - vals[i] <= 4:  # 5 cards span at most 4 gaps for straight
            # More precisely for board
            pass
    # Simpler for board texture: check gaps
    gaps = [vals[i+1] - vals[i] for i in range(len(vals)-1)]
    return max(gaps) <= 2 or (len(gaps) >= 2 and sum(gaps[:2]) <= 4)


def _connectivity_score(vals: List[int]) -> float:
    """Rough score of how connected the board is (0-4 range for board)."""
    if len(vals) < 2:
        return 0.0
    gaps = sorted([vals[i+1] - vals[i] for i in range(len(vals)-1)])
    score = 0.0
    for g in gaps:
        if g == 1:
            score += 1.0
        elif g == 2:
            score += 0.6
        elif g == 3:
            score += 0.3
    return score


def board_texture_summary(cards: List[str]) -> str:
    """Quick human readable summary."""
    texture = analyze_board(cards)
    return texture.summary()

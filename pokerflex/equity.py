"""
PokerFlex A1 - Equity Calculations (shared by primary A1 brain + legacy shim when forced for debug ONLY)

Central place for all equity work.
Supports vs-random and proper sampling vs estimated villain Range for A1 heuristic GTO (default path).
"""

import random
from typing import List, Optional, Tuple, Any
import collections
from functools import lru_cache
from treys import Card, Evaluator
from .config import CONFIG
from .ranges import Range, RANK_ORDER, SUITS

# Canonical deck and evaluator for equity work (no longer pulled from poker_engine)
_FULL_DECK = [Card.new(r + s) for r in RANK_ORDER for s in SUITS]
_EVAL = Evaluator()

# --------------------------------------------------------------------------- #
# Smart limited caching for hot equity paths (MC vs range especially).
# Targets common board + range combos in live advisor / postflop calls.
# Uses custom LRU (OrderedDict) with size limit for complex keys (Range not hashable).
# Respects CONFIG.use_cache. Falls back gracefully. No perf regression on cold (first) calls.
# lru_cache used where simple (e.g. vs-random with hashable iters).
# --------------------------------------------------------------------------- #

_MAX_EQUITY_CACHE_SIZE = 256  # bounded to avoid unbounded growth on unique boards/ranges in long sessions
_equity_vs_range_cache: collections.OrderedDict = collections.OrderedDict()
_equity_vs_random_cache: collections.OrderedDict = collections.OrderedDict()


def _make_range_sig(villain_range: Optional[Range]) -> Tuple[Tuple[str, float], ...]:
    """Stable hashable signature for a Range (rounded weights for cache hits on similar)."""
    if not villain_range or not getattr(villain_range, 'weights', None):
        return tuple()
    items = []
    for h, w in sorted(villain_range.weights.items()):
        if w > 0.005:  # ignore tiny
            items.append( (h, round(float(w), 3)) )
    return tuple(items)


def _make_cards_key(cards: List[int]) -> Tuple[int, ...]:
    return tuple(sorted(cards)) if cards else tuple()


def _get_cached_equity_vs_range(hero_cards: List[int], board: List[int], villain_range: Optional[Range], iters: int) -> Optional[float]:
    """Return cached equity if available and use_cache enabled; else None (caller computes)."""
    if not CONFIG.use_cache:
        return None
    try:
        key = (_make_cards_key(hero_cards), _make_cards_key(board), _make_range_sig(villain_range), iters)
        if key in _equity_vs_range_cache:
            _equity_vs_range_cache.move_to_end(key)  # LRU
            return _equity_vs_range_cache[key]
    except Exception:
        pass
    return None


def _put_cached_equity_vs_range(hero_cards: List[int], board: List[int], villain_range: Optional[Range], iters: int, val: float) -> None:
    if not CONFIG.use_cache:
        return
    try:
        key = (_make_cards_key(hero_cards), _make_cards_key(board), _make_range_sig(villain_range), iters)
        _equity_vs_range_cache[key] = val
        _equity_vs_range_cache.move_to_end(key)
        while len(_equity_vs_range_cache) > _MAX_EQUITY_CACHE_SIZE:
            _equity_vs_range_cache.popitem(last=False)
    except Exception:
        pass


def _get_cached_equity_vs_random(hero_cards: List[int], board: List[int], n_opp: int, iters: int) -> Optional[float]:
    if not CONFIG.use_cache:
        return None
    try:
        key = (_make_cards_key(hero_cards), _make_cards_key(board), int(n_opp), int(iters))
        if key in _equity_vs_random_cache:
            _equity_vs_random_cache.move_to_end(key)
            return _equity_vs_random_cache[key]
    except Exception:
        pass
    return None


def _put_cached_equity_vs_random(hero_cards: List[int], board: List[int], n_opp: int, iters: int, val: float) -> None:
    if not CONFIG.use_cache:
        return
    try:
        key = (_make_cards_key(hero_cards), _make_cards_key(board), int(n_opp), int(iters))
        _equity_vs_random_cache[key] = val
        _equity_vs_random_cache.move_to_end(key)
        while len(_equity_vs_random_cache) > _MAX_EQUITY_CACHE_SIZE:
            _equity_vs_random_cache.popitem(last=False)
    except Exception:
        pass


# Optional: simple lru_cache wrapper for pure-random cases with fixed iters (hashable path)
@lru_cache(maxsize=64)
def _equity_vs_random_lru_cached(hero_t: Tuple[int, ...], board_t: Tuple[int, ...], n_opp: int, iters: int) -> float:
    # delegates to core impl (non-cached body) - we call the full func which checks cache first anyway
    # this augments for very hot identical random queries
    return equity_vs_random(list(hero_t), list(board_t), n_opp, iters=iters)  # will hit our dict cache mostly



def equity_vs_random(hero_cards: List[int], board: List[int], n_opp: int, iters: int = None) -> float:
    """
    Hero equity vs n_opp uniformly-random hands on the given board (Monte Carlo).
    This is the canonical implementation (moved out of poker_engine.py).
    A1 new brain (unambiguous default everywhere) and legacy (forced debug) both use it for identical numbers.
    Smart cache (size-limited LRU) for repeated board+iters combos in advisor/live/hot paths.
    """
    if iters is None:
        iters = CONFIG.default_equity_iters
    n_opp = max(1, n_opp)
    iters = int(iters)

    # Check limited custom cache first (respects use_cache)
    cached = _get_cached_equity_vs_random(hero_cards, board, n_opp, iters)
    if cached is not None:
        return cached

    used = set(hero_cards) | set(board or [])
    deck = [c for c in _FULL_DECK if c not in used]
    need_board = 5 - len(board or [])
    draws_per = need_board + 2 * n_opp
    eq = 0.0
    for _ in range(iters):
        drawn = random.sample(deck, draws_per)
        full_board = (board or []) + drawn[:need_board]
        hero_score = _EVAL.evaluate(full_board, hero_cards)
        idx = need_board
        opp_scores = []
        for _k in range(n_opp):
            opp_scores.append(_EVAL.evaluate(full_board, drawn[idx:idx + 2]))
            idx += 2
        best_opp = min(opp_scores)
        if hero_score < best_opp:
            eq += 1.0
        elif hero_score == best_opp:
            ties = sum(1 for s in opp_scores if s == hero_score)
            eq += 1.0 / (ties + 1)
    val = eq / iters
    _put_cached_equity_vs_random(hero_cards, board, n_opp, iters, val)
    return val


def _get_combos_for_hand_class(hand_class: str, used: set) -> List[List[int]]:
    """Expand a hand class (e.g. 'AKs', '22', 'A5o') into list of possible treys [c1, c2] avoiding used cards."""
    combos = []
    if not hand_class or len(hand_class) < 2:
        return combos
    r1 = hand_class[0].upper()
    if len(hand_class) == 2:  # pocket pair
        for i, s1 in enumerate(SUITS):
            for s2 in SUITS[i+1:]:
                c1 = Card.new(r1 + s1)
                c2 = Card.new(r1 + s2)
                if c1 not in used and c2 not in used:
                    combos.append([c1, c2])
    else:
        r2 = hand_class[1].upper()
        is_suited = hand_class[2].lower() == 's'
        for s1 in SUITS:
            for s2 in SUITS:
                if is_suited and s1 != s2:
                    continue
                if not is_suited and s1 == s2:
                    continue
                c1 = Card.new(r1 + s1)
                c2 = Card.new(r2 + s2)
                if c1 not in used and c2 not in used:
                    combos.append([c1, c2])
    return combos


def _sample_villain_combo(villain_range: Range, used: set) -> Optional[List[int]]:
    """Sample one villain combo (as list of 2 treys) consistent with range and used cards. Returns None if impossible."""
    if not villain_range or not villain_range.weights:
        return None
    candidates = []
    weights = []
    for hcls, w in villain_range.weights.items():
        if w <= 0:
            continue
        combs = _get_combos_for_hand_class(hcls, used)
        for comb in combs:
            candidates.append(comb)
            weights.append(float(w))
    if not candidates:
        return None
    # weighted sample
    try:
        idx = random.choices(range(len(candidates)), weights=weights, k=1)[0]
        return candidates[idx]
    except Exception:
        return random.choice(candidates)


def equity_vs_range(hero_cards: List[int], board: List[int], villain_range: Optional[Range], iters: int = None) -> float:
    """
    Monte Carlo equity vs hands sampled from villain_range (respects blockers from hero+board).
    Uses reduced iters + limited runouts for speed in real-time heuristic use.
    Falls back to vs-random if range empty or error.
    Smart size-limited LRU cache on (board + range_sig + iters) for common postflop texture/range combos.
    """
    if villain_range is None or not getattr(villain_range, 'weights', None):
        if iters is None:
            iters = CONFIG.fast_equity_iters
        return equity_vs_random(hero_cards, board, 1, iters=iters)

    if iters is None:
        iters = max(200, CONFIG.fast_equity_iters // 2)  # heuristic speed: ~400 default
    iters = int(iters)

    # Check custom limited cache for vs-range (hot path in postflop/ advisor for repeated boards)
    cached = _get_cached_equity_vs_range(hero_cards, board, villain_range, iters)
    if cached is not None:
        return cached

    used = set(hero_cards) | set(board or [])
    eq = 0.0
    valid_trials = 0
    need_more = 5 - len(board or [])

    for _ in range(iters):
        vill = _sample_villain_combo(villain_range, used)
        if not vill or len(vill) != 2:
            continue
        vill_used = used | set(vill)
        if need_more > 0:
            # Sample remaining board cards (heuristic: 1-2 runouts per villain sample for speed)
            sub_iters = 1 if need_more >= 2 else 2
            for __ in range(sub_iters):
                try:
                    avail = [c for c in _FULL_DECK if c not in vill_used]
                    drawn = random.sample(avail, need_more)
                    full_b = (board or []) + drawn
                    h_score = _EVAL.evaluate(full_b, hero_cards)
                    v_score = _EVAL.evaluate(full_b, vill)
                    if h_score < v_score:
                        eq += 1.0
                    elif h_score == v_score:
                        eq += 0.5
                except Exception:
                    pass
            valid_trials += sub_iters
        else:
            # River or complete board: exact
            try:
                h_score = _EVAL.evaluate(board, hero_cards)
                v_score = _EVAL.evaluate(board, vill)
                if h_score < v_score:
                    eq += 1.0
                elif h_score == v_score:
                    eq += 0.5
                valid_trials += 1
            except Exception:
                pass
    if valid_trials == 0:
        # ultimate fallback
        val = equity_vs_random(hero_cards, board or [], 1, iters=CONFIG.fast_equity_iters)
    else:
        val = eq / valid_trials
    _put_cached_equity_vs_range(hero_cards, board, villain_range, iters, val)
    return val

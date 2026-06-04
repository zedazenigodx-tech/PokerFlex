"""
PokerFlex A1 - Postflop Strategy (Strong Heuristic GTO) — primary brain module

This module implements texture-aware, range-sensitive heuristic decisions (range/nut adv, blockers, explo notes, sizing).
Significant step up from legacy raw equity buckets. Used by default (A1 UNAMBIGUOUS default in all entry points; legacy debug ONLY never primary).
"""

from typing import List, Dict, Tuple, Optional, Any
from .models import GameState, Decision, Action, get_player_notes, ActionEvent
from .config import CONFIG
from .board_texture import BoardTexture
from .ranges import Range, parse_range, get_open_range
from .equity import equity_vs_random, equity_vs_range

from .parsing import parse_cards
from .ranges import RANK_VAL, RANK_ORDER
from treys import Evaluator

_EVAL = Evaluator()
# SUITS / ranks from ranges (no local dupe)


# --------------------------------------------------------------------------- #
# Villain Range Construction (position, action, texture, street aware)
# --------------------------------------------------------------------------- #

def _get_base_tokens_for_spot(hero_pos: str, facing_action: Optional[str], n_opp: int, street_val: int) -> List[str]:
    """Choose sensible base range tokens depending on inferred villain role."""
    hero_pos = (hero_pos or "BTN").upper()
    facing = (facing_action or "").lower().strip()
    is_later_street = street_val >= 4

    # Default: assume hero opened, villain is calling/continuing (wide-ish)
    if hero_pos in ("BTN", "CO"):
        base = ["22+", "A2s+", "K9s+", "Q9s+", "J9s+", "T9s", "98s", "87s", "A9o+", "KTo+", "QTo+", "JTo"]
    elif hero_pos in ("MP", "UTG"):
        base = ["22+", "A4s+", "K9s+", "QTs+", "JTs", "T9s", "98s", "A9o+", "KJo+", "QJo"]
    else:
        base = ["22+", "A2s+", "K9s+", "Q9s+", "JTs", "T9s", "98s", "AJo", "KQo"]

    # Action-based adjustment (facing bet/raise/donk/check-raise)
    if "check-raise" in facing or "cr" in facing:
        # Check-raises are often value-heavy or strong draws on dynamic boards
        base = ["22+", "A9s+", "KTs+", "QTs+", "JTs", "TT+", "AJo", "KQo", "JJ+"]
    elif "donk" in facing:
        # Donking is often weak (bluff or weak made) or trap with nuts; keep wider but cap value
        base = ["22+", "A2s+", "K9s+", "QTs+", "J9s+", "T9s", "98s", "A9o+", "KTo+"]
    elif facing in ("bet", "raise", "cbet"):
        # Villain bet into us (IP or OOP) - tightening + adding draws
        base = ["33+", "A9s+", "KJs+", "QTs+", "JTs", "T9s", "AJo", "KQo", "TT+"]
    elif "call" in facing or "defend" in facing:
        # We bet, they called - their calling range (slightly wider than continuing vs future)
        base = ["22+", "A2s+", "K8s+", "Q9s+", "J9s+", "T8s+", "98s", "A9o+", "K9o+", "QTo+"]
    # else: checked through or we are first to act -> use default caller/continue

    # Street refinement: later streets villain range is stronger / less speculative
    if is_later_street:
        # Drop some weak speculative, keep made + good draws
        filtered = []
        for tok in base:
            if any(x in tok for x in ["22", "33", "44", "55", "A2", "A3", "K8", "Q8"]):
                if "+" in tok or any(p in tok for p in "JQK A"):
                    filtered.append(tok)
            else:
                filtered.append(tok)
        base = filtered or base

    # Multiway: villain ranges tighten (less bluffs, stronger value to continue multiway)
    if n_opp > 1:
        tighten = min(0.45, CONFIG.multiway_tighten_factor * n_opp)
        # crude: truncate low end of list
        cut = max(6, int(len(base) * (1.0 - tighten)))
        base = base[:cut]

    return base


def _adjust_tokens_for_texture(base_tokens: List[str], texture: BoardTexture, street_val: int) -> List[str]:
    """Bias the range toward hands that continue on this texture (suited on flush boards etc)."""
    toks = list(base_tokens)
    if texture.flush_category in ("two_tone", "monotone"):
        # Prefer suited + broadway + Ax suited
        suited_bonus = [t for t in toks if t.endswith("s") or "A" in t[:1]]
        # double weight conceptually by duplicating some
        toks = toks + [t for t in suited_bonus if t.endswith("s")][:len(suited_bonus)]
    if texture.straight_category in ("semi_connected", "very_connected"):
        # Keep connectors
        conn = [t for t in toks if any(x in t for x in ["JTs", "T9s", "98s", "87s", "76s", "QTs", "J9s"])]
        toks = toks + conn
    if texture.paired:
        # More weight to pairs/sets
        pairs = [t for t in toks if len(t) == 2 or t[0] == t[1]]
        toks = toks + pairs * 1
    # De-dupe while preserving order-ish
    seen = set()
    out = []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _get_history_story(state: GameState) -> Dict[str, Any]:
    """
    Structured story extraction from action_history for smarter decisions.
    Returns e.g.:
      {"preflop_villain": "call" or "raise" or "3bet", "flop_villain_first": "check"|"bet"|"donk",
       "is_check_back": bool (called pre + checked flop), "is_donk_lead": bool,
       "prior_aggression": float (0-2+), "last_street_aggressor": "hero"|"villain",
       "check_call_story": bool }
    Used for capped ranges, blocker adjustments, dynamic texture, donk vs check-call detection.
    Empty history -> neutral defaults (current behavior preserved).
    """
    hist: List[ActionEvent] = getattr(state, "action_history", []) or []
    if not hist:
        return {"preflop_villain": None, "flop_villain_first": None, "is_check_back": False,
                "is_donk_lead": False, "prior_aggression": 0.0, "last_street_aggressor": None,
                "check_call_story": False, "events": 0}

    preflop_v = None
    flop_v_first = None
    turn_v_first = None
    river_v_first = None
    agg_score = 0.0
    last_agg = None
    villain_pre_actions = []
    hero_pre_actions = []

    for ev in hist:
        if not isinstance(ev, ActionEvent):
            # tolerate raw dicts
            try:
                ev = ActionEvent.from_dict(ev) if hasattr(ActionEvent, 'from_dict') else None
            except Exception:
                ev = None
        if not ev:
            continue
        st = (ev.street or "").lower()
        ac = (ev.actor or "").lower()
        act = (ev.action or "").lower()
        sz = ev.size or 0.0

        if st == "preflop":
            if ac == "villain":
                villain_pre_actions.append(act)
                if act in ("raise", "3bet", "4bet", "bet"):
                    preflop_v = act
                    agg_score += 1.2 if act in ("3bet", "4bet") else 0.8
                    last_agg = "villain"
                elif act == "call":
                    if not preflop_v:
                        preflop_v = "call"
                    agg_score += 0.3
            elif ac == "hero":
                hero_pre_actions.append(act)
                if act in ("raise", "3bet"):
                    last_agg = "hero"
                    agg_score += 0.8
        elif st == "flop":
            if ac == "villain" and flop_v_first is None:
                flop_v_first = act
                if act in ("bet", "raise", "donk"):
                    agg_score += 1.0
                    last_agg = "villain"
                elif act == "check":
                    agg_score -= 0.1
        elif st == "turn":
            if ac == "villain" and turn_v_first is None:
                turn_v_first = act
                if act in ("bet", "raise"):
                    last_agg = "villain"
                    agg_score += 0.9
        elif st == "river":
            if ac == "villain" and river_v_first is None:
                river_v_first = act
                if act in ("bet", "raise"):
                    last_agg = "villain"

    is_check_back = (preflop_v == "call") and (flop_v_first == "check")
    is_donk = (flop_v_first == "donk") or (flop_v_first == "bet" and preflop_v != "raise" and "call" in villain_pre_actions)
    check_call_story = is_check_back or (preflop_v == "call" and flop_v_first == "call")

    story = {
        "preflop_villain": preflop_v,
        "flop_villain_first": flop_v_first,
        "turn_villain_first": turn_v_first,
        "river_villain_first": river_v_first,
        "is_check_back": is_check_back,
        "is_donk_lead": bool(is_donk),
        "prior_aggression": round(max(0.0, min(3.0, agg_score)), 2),
        "last_street_aggressor": last_agg,
        "check_call_story": check_call_story,
        "events": len(hist),
        "villain_preflop_called": "call" in villain_pre_actions,
    }
    return story


def _estimate_villain_range(state: GameState, texture: BoardTexture) -> Range:
    """
    Strong heuristic villain range estimator.
    Factors: hero position (infers villain role), facing_action (bet/donk/cr), 
    action_history (preflop aggression), texture (flush/straight bias), street, multiway.
    NOW uses structured history via _get_history_story for capped ranges (e.g. check-back after call),
    prior aggression for dynamic adjustments, simple story detection (donk vs check-call).
    """
    from .ranges import parse_range

    hero_pos = state.hero_position or "BTN"
    facing = state.facing_action
    n_opp = max(1, state.num_opponents)
    street_val = state.board.street.value if state.board and state.board.street else 3

    # Base from spot
    base = _get_base_tokens_for_spot(hero_pos, facing, n_opp, street_val)

    # NEW: extract story FIRST so we can use for texture + range adjustments
    story = _get_history_story(state)
    hist = state.action_history or []

    # Dynamic texture adjustment based on prior aggression from history (before texture bias apply)
    agg = story.get("prior_aggression", 0.0)
    if agg > 1.5:
        # aggressive history -> villain continues wider vs texture, treat board as more dynamic for hero decisions
        if texture.dynamic_score < 0.6:
            # bump perceived dynamic a bit (affects call_thresh etc downstream)
            try:
                texture.dynamic_score = min(0.95, float(texture.dynamic_score) + 0.15)
            except Exception:
                pass
    elif agg < 0.4 and story.get("is_check_back"):
        # passive check-back history -> treat as more static/capped
        try:
            texture.dynamic_score = max(0.0, float(getattr(texture, "dynamic_score", 0.0)) - 0.1)
        except Exception:
            pass

    # Texture bias
    base = _adjust_tokens_for_texture(base, texture, street_val)

    # Action history refinement (structured, first-class ActionEvent aware)
    # backward compat crude string for old data
    hist_str = " ".join(str(h).lower() for h in hist)

    if story.get("preflop_villain") in ("3bet", "4bet") or "3bet" in hist_str or "threebet" in hist_str or "3b" in hist_str:
        # Tighten dramatically for 3bet ranges
        base = [t for t in base if any(x in t for x in ["JJ+", "QQ+", "KK", "AA", "AKs", "AQs", "AKo"])] or \
               ["JJ+", "AKs", "AQs", "AKo"]
    elif story.get("preflop_villain") == "4bet" or "4bet" in hist_str:
        base = ["KK+", "AKs", "AKo"]

    # If villain was the preflop aggressor (PFR/3b) and we are calling, value + bluffs
    if story.get("preflop_villain") in ("raise", "3bet") or "aggressor" in hist_str or "pfr" in hist_str:
        # already somewhat captured in base tokens
        pass

    # NEW: check-back / called-pre + check flop -> capped range (no overpairs/sets often)
    if story.get("is_check_back"):
        # cap: remove some high value that would cbet, keep medium pairs + draws + some air
        base = [t for t in base if not any(x in t for x in ["AA", "KK", "QQ", "JJ", "AKs"])] or base
        base = base + ["22-99", "A9s-A2s", "KTs", "QTs"]  # capped-ish adds
        # reduce overall value density for range comp
    if story.get("check_call_story"):
        # very capped / passive line
        base = [t for t in base if any(x in t for x in ["pairs<JJ", "suited connectors", "Ax suited", "KQs", "QTs", "JTs", "weak pairs"])] or base

    # Donk lead story: polarized (strong or bluffy), less merged value
    if story.get("is_donk_lead"):
        # bias toward nuts + air; caller adjusts downstream
        pass

    hand_set = parse_range(base)
    r = Range.from_hand_list(list(hand_set))

    # Apply blocker removal at Range level (crude rank block; exact combo block happens in equity sampling)
    hero_ranks = {c[0].upper() for c in (state.hero_hand or [])}
    if hero_ranks:
        # reduce weight for classes using blocked ranks (simple heuristic)
        new_weights = {}
        for h, w in r.weights.items():
            blocked = False
            for rk in hero_ranks:
                if rk in h:
                    blocked = True
                    break
            if not blocked:
                new_weights[h] = w
            else:
                new_weights[h] = w * 0.6  # partial weight reduction
        r = Range(weights=new_weights)
    return r


# --------------------------------------------------------------------------- #
# Pluggable Exploitative Range Adjuster (rule/heuristic based, no ML)
# Takes optional player_notes (from GameState or passed), returns adjusted
# villain Range + modifiers dict for decision logic.
# Examples:
#   - High fold_to_cbet (nit): shrink villain continuing range (lower weights
#     on marginal/weak hands) -> higher fold equity implicit. Boost bet freq.
#   - Low fold_to_cbet (station): reduce bet freq / bluffs, value bet tighter.
#   - High AF: villain wider when betting into us -> hero calls tighter.
# This modifies the Range used for eq_vs_range, comp, blockers, adv calcs.
# The mods allow decision engine (_get_postflop_action) to change thresholds.
# Fully optional; if notes empty or explo off -> identity (no change).
# --------------------------------------------------------------------------- #

def _is_marginal_continuation_hand(hclass: str, texture: BoardTexture) -> bool:
    """Heuristic: is this hand class a 'weak/marginal' continuer that a nit might fold to cbet?"""
    if not hclass or len(hclass) < 2:
        return False
    r1 = hclass[0].upper()
    r2 = hclass[1].upper() if len(hclass) > 1 else r1
    suited = len(hclass) > 2 and hclass[2].lower() == 's'
    pair = r1 == r2
    v1, v2 = RANK_VAL.get(r1, 0), RANK_VAL.get(r2, 0)
    maxv = max(v1, v2)
    # low pairs, low suited connectors/gappers, weak Ax/Kx on non-A/K boards are fold candidates on cbet
    if pair and maxv <= 8:  # 88 or lower
        return True
    if not pair:
        if maxv <= 9 and not suited:  # weak offsuit
            return True
        if suited and maxv <= 8:  # low suited
            return True
        if "A" in (r1, r2) and maxv < 12 and not suited:  # weak ATo etc
            return True
    # texture specific
    if texture.flush_category == "rainbow" and texture.straight_category == "dry":
        if suited and maxv <= 10:
            return True
    if texture.paired and not pair:
        if maxv <= 9:
            return True
    return False


def apply_exploitative_range_adjuster(
    villain_range: Range,
    notes: Optional[Dict[str, Any]],
    texture: BoardTexture,
    context: Optional[Dict[str, Any]] = None
) -> Tuple[Range, Dict[str, float]]:
    """
    Core pluggable adjuster.
    Returns (possibly-modified Range with adjusted weights, and exploit_mods dict).
    Mods keys used downstream: 'bet_freq_mult', 'bluff_more', 'value_only',
    'vs_bet_tighter', 'call_thresh_delta', 'notes_used'.
    Builds directly on Range (weights manipulation) + GameState notes.
    """
    context = context or {}
    if not notes or not isinstance(notes, dict) or len(notes) == 0:
        return villain_range, {"notes_used": False}

    # Support both flat notes or {"villain": notes_dict}
    n = notes
    if "villain" in notes and isinstance(notes["villain"], dict):
        n = notes["villain"]
    elif "default_villain" in notes and isinstance(notes.get("default_villain"), dict):
        n = notes["default_villain"]

    # Extract key stats (with fallbacks). Prefer base if specific dry/wet were never set (0.5 default case)
    ftc = float(n.get("fold_to_cbet", n.get("fold_to_cbet_dry", 0.5)))
    ftc_dry = float(n.get("fold_to_cbet_dry", ftc))
    ftc_wet = float(n.get("fold_to_cbet_wet", ftc))
    # If dry/wet still at pure default (0.5) while base ftc was explicitly set higher/lower, inherit from base.
    # This fixes quick 'note foo fold_to_cbet 0.78' (without setting dry/wet) so it affects texture-aware cbet exploits.
    if abs(ftc_dry - 0.5) < 0.001:
        ftc_dry = ftc
    if abs(ftc_wet - 0.5) < 0.001:
        ftc_wet = ftc
    af = float(n.get("aggression_factor", 1.0))
    # choose based on texture roughly
    is_dry = (texture.flush_category == "rainbow" and texture.straight_category == "dry" and texture.dynamic_score < 0.4)
    fold_c = ftc_dry if is_dry else (ftc_wet if texture.dynamic_score > 0.5 else ftc)

    mods: Dict[str, float] = {"notes_used": True, "fold_to_cbet": fold_c, "af": af}

    # Start with copy of weights
    new_weights = dict(villain_range.weights)

    # --- NIT / high folder exploit: shrink continuing range ---
    if fold_c >= CONFIG.exploit_fold_cbet_high:
        shrink_factor = min(0.85, (fold_c - 0.5) * 1.6)  # how aggressively to downweight marginals
        pruned = 0
        for h, w in list(new_weights.items()):
            if w <= 0:
                continue
            if _is_marginal_continuation_hand(h, texture):
                new_w = max(0.02, w * (1.0 - shrink_factor))
                new_weights[h] = new_w
                if new_w < 0.08:
                    pruned += 1
        # also slightly reduce overall air-ish
        mods["villain_continuing_range_shrunk"] = shrink_factor
        mods["bet_freq_mult"] = min(CONFIG.exploit_bet_freq_boost_max + 1.0, 1.0 + (fold_c - 0.5) * 1.4)
        mods["bluff_more"] = 1.0
        mods["fold_equity_boost"] = round((fold_c - 0.5) * 0.6, 3)
        if pruned > 0:
            mods["pruned_marginal"] = float(pruned)

    # --- CALLING STATION / low folder exploit: do NOT shrink (or slightly widen defense assumption) ---
    elif fold_c <= CONFIG.exploit_fold_cbet_low:
        # Make range "stickier": boost weights on some marginals so comp shows more air? or just use mods
        # For eq calc we can leave or slightly inflate low end to represent they call wider.
        for h, w in list(new_weights.items()):
            if _is_marginal_continuation_hand(h, texture) and w > 0:
                new_weights[h] = min(1.0, w * 1.15)  # they stick with more
        mods["villain_continuing_range_widened"] = 0.15
        mods["bet_freq_mult"] = max(0.55, 1.0 - (0.5 - fold_c) * 1.8)
        mods["bluff_less"] = 1.0
        mods["value_only"] = 1.0
        mods["call_thresh_delta"] = +0.08

    # --- Aggression factor adjustments (affects facing their bets more) ---
    if af >= CONFIG.exploit_af_high:
        mods["vs_bet_tighter"] = 1.0
        mods["call_thresh_delta"] = mods.get("call_thresh_delta", 0.0) + 0.07
    elif af < 0.7:
        # passive nit: their betting range is value heavy -> when they bet, fold more
        mods["vs_bet_tighter"] = 1.0
        mods["call_thresh_delta"] = mods.get("call_thresh_delta", 0.0) + 0.12

    # Rebuild Range only if meaningfully changed
    changed = any(abs(new_weights.get(h, 0) - villain_range.weights.get(h, 0)) > 0.001 for h in set(list(new_weights) + list(villain_range.weights)))
    if changed:
        adjusted_range = Range(weights={h: w for h, w in new_weights.items() if w > 0.01})
    else:
        adjusted_range = villain_range

    mods["adjusted_range_combos"] = round(adjusted_range.total_combos(), 1)
    return adjusted_range, mods


# --------------------------------------------------------------------------- #
# Hand / Range Classification for Advantages, Blockers, Buckets (heuristic)
# --------------------------------------------------------------------------- #

def _get_board_components(board_cards: List[str]) -> Tuple[List[str], List[str], List[int]]:
    """Return ranks (upper), suits (lower), and integer values for the board."""
    if not board_cards:
        return [], [], []
    ranks = [c[0].upper() for c in board_cards]
    suits = [c[1].lower() for c in board_cards]
    vals = [RANK_VAL.get(r, 0) for r in ranks]
    return ranks, suits, vals


def _hand_class_connects_well(hclass: str, branks: List[str], bsuits: List[str], bvals: List[int], texture: BoardTexture) -> Tuple[float, bool, bool]:
    """
    Heuristic strength score (0-10), is_nutty, has_strong_draw for a hand class vs board.
    Pure rank/suit logic, fast, no evaluator needed for range sweep.
    """
    if not hclass or len(hclass) < 2:
        return 0.0, False, False
    score = 1.0
    is_nutty = False
    has_strong_draw = False

    r1 = hclass[0].upper()
    r2 = hclass[1].upper() if len(hclass) > 1 else r1
    suited = len(hclass) > 2 and hclass[2].lower() == 's'
    pair = r1 == r2
    v1, v2 = RANK_VAL.get(r1, 0), RANK_VAL.get(r2, 0)
    maxv, minv = max(v1, v2), min(v1, v2)

    # Pair strength
    if pair:
        if r1 in branks:
            # set or better
            score = 7.5
            if texture.paired and r1 == texture.pair_rank:
                score = 9.0  # full house potential or quads
                is_nutty = True
            else:
                is_nutty = (v1 >= 10)  # high set
        else:
            # overpair or underpair
            board_high = max(bvals) if bvals else 0
            if maxv > board_high:
                score = 6.0  # overpair
                is_nutty = maxv >= 12
            else:
                score = 3.5  # underpair

    # Suited flush potential
    board_suit_count = {}
    for s in bsuits:
        board_suit_count[s] = board_suit_count.get(s, 0) + 1
    flush_suit = None
    for s, cnt in board_suit_count.items():
        if cnt >= 2:
            flush_suit = s
            break
    hero_suit = hclass[2].lower() if suited else None
    if suited and flush_suit and hero_suit == flush_suit:
        if texture.flush_category == "monotone":
            score = max(score, 8.5)
            is_nutty = (maxv >= 12 or r1 == "A")  # nut flush possible
            has_strong_draw = True
        elif texture.flush_category == "two_tone":
            score = max(score, 5.5)
            has_strong_draw = True

    # Straight / connectivity
    if not pair:
        board_set = set(bvals)
        # connectors / broadway that make straight or draw
        if maxv - minv <= 4 or minv + 1 in board_set or maxv - 1 in board_set:
            if texture.straight_category == "very_connected":
                score = max(score, 6.5)
                has_strong_draw = True
            elif texture.straight_category == "semi_connected":
                score = max(score, 4.5)
                has_strong_draw = (maxv >= 10)

    # Top pair / good kicker
    if not pair and r1 in branks:
        # hero has top or good pair
        board_high_rank = max(branks, key=lambda x: RANK_VAL.get(x, 0)) if branks else "2"
        if r1 == board_high_rank or RANK_VAL.get(r1, 0) >= RANK_VAL.get(board_high_rank, 0) - 1:
            score = max(score, 5.0)
            if v2 >= 10 or r2 in "AKQ":
                score = max(score, 6.5)
                is_nutty = (r1 == board_high_rank and v2 >= 11)

    # Ace high / broadway on dry
    if r1 == "A" and not (pair or (suited and flush_suit)):
        score = max(score, 3.0)
        if texture.straight_category == "dry" and texture.flush_category == "rainbow":
            score = max(score, 4.0)

    # Cap and return
    score = min(10.0, max(0.5, score))
    return score, is_nutty, has_strong_draw


def _compute_range_composition(villain_range: Range, board_cards: List[str], texture: BoardTexture) -> Dict[str, float]:
    """Sweep villain range (hand classes) and estimate % in value, nutted, draws, air buckets. Fast heuristic."""
    if not villain_range or not villain_range.weights:
        return {"value_pct": 0.3, "nut_pct": 0.1, "draw_pct": 0.2, "air_pct": 0.5, "avg_strength": 3.5, "total_combos": 0.0}
    # Early exit for tiny ranges (perf)
    if len(villain_range.weights) <= 3:
        # direct small case, no need full sweep math
        return {"value_pct": 0.4, "nut_pct": 0.2, "draw_pct": 0.3, "air_pct": 0.3, "avg_strength": 5.0, "total_combos": float(len(villain_range.weights)*6)}

    branks, bsuits, bvals = _get_board_components(board_cards)
    value = 0.0
    nut = 0.0
    draw = 0.0
    air = 0.0
    strength_sum = 0.0
    total_w = 0.0

    for hcls, w in villain_range.weights.items():
        if w <= 0:
            continue
        # Approximate combo weight (pairs 6, s 4, o 12)
        if len(hcls) == 2:
            combo_w = 6.0 * w
        elif len(hcls) > 2 and hcls[2].lower() == 's':
            combo_w = 4.0 * w
        else:
            combo_w = 12.0 * w

        sc, is_n, has_d = _hand_class_connects_well(hcls, branks, bsuits, bvals, texture)
        strength_sum += sc * combo_w

        if sc >= 6.5 or is_n:
            value += combo_w
            if is_n:
                nut += combo_w
        elif has_d or sc >= 4.0:
            draw += combo_w
        else:
            air += combo_w
        total_w += combo_w

    if total_w <= 0:
        total_w = 1.0
    return {
        "value_pct": value / total_w,
        "nut_pct": nut / total_w,
        "draw_pct": draw / total_w,
        "air_pct": air / total_w,
        "avg_strength": strength_sum / total_w,
        "total_combos": total_w,
    }


def _compute_blocker_score(hero_hand: List[str], villain_range: Range, texture: BoardTexture, board_cards: List[str]) -> float:
    """
    Positive = good blockers (block villain value/nuts more than bluffs).
    Negative = bad blockers (block bluffs, villain has more value).
    Rough combo count based.
    """
    if not hero_hand or len(hero_hand) != 2 or not villain_range:
        return 0.0
    if not getattr(villain_range, 'weights', None) or len(villain_range.weights) < 2:
        return 0.0  # early exit, negligible blockers from tiny range
    branks, bsuits, _ = _get_board_components(board_cards)
    hero_r1, hero_s1 = hero_hand[0][0].upper(), hero_hand[0][1].lower()
    hero_r2, hero_s2 = hero_hand[1][0].upper(), hero_hand[1][1].lower()

    blocked_value = 0.0
    blocked_bluff = 0.0

    for hcls, w in villain_range.weights.items():
        if w <= 0: continue
        if len(hcls) == 2:
            cw = 6.0 * w
        elif len(hcls) > 2 and hcls[2].lower() == 's':
            cw = 4.0 * w
        else:
            cw = 12.0 * w

        sc, is_nut, _ = _hand_class_connects_well(hcls, branks, bsuits, [], texture)
        is_value_like = (sc >= 6.0 or is_nut)

        # Does this class use one of hero's cards?
        uses_hero = False
        if hero_r1 in hcls:
            uses_hero = True
        if hero_r2 in hcls and hero_r1 != hero_r2:
            uses_hero = True
        # suit blocker for flush boards
        if texture.flush_category != "rainbow" and len(hcls) > 2:
            if (hcls[2].lower() == hero_s1 and hero_r1 in hcls) or (hcls[2].lower() == hero_s2 and hero_r2 in hcls):
                uses_hero = True

        if uses_hero:
            if is_value_like:
                blocked_value += cw
            else:
                blocked_bluff += cw

    total_blocked = blocked_value + blocked_bluff
    if total_blocked < 1:
        return 0.0
    # good if block more value than bluffs (relative)
    score = (blocked_value - blocked_bluff) / max(total_blocked, 1.0)
    return max(-1.0, min(1.0, score))


def _compute_range_and_nut_advantage(hero_eq: float, comp: Dict[str, float], texture: BoardTexture) -> Tuple[float, float]:
    """
    range_adv: hero's estimated equity edge vs the range (positive good for hero).
    nut_adv: who has more "nutted" portion of range (positive = hero has nut advantage).
    Very heuristic: use composition + eq proxy.
    """
    # range advantage proxy: if hero has decent eq and villain has lots of air, positive
    air = comp.get("air_pct", 0.4)
    val_v = comp.get("value_pct", 0.25)
    nut_v = comp.get("nut_pct", 0.08)
    avg_str = comp.get("avg_strength", 4.0)

    range_adv = (hero_eq - 0.5) * 1.6
    # boost if villain capped (lots air, few value)
    range_adv += (air - 0.35) * 0.6
    range_adv -= (val_v - 0.28) * 0.5
    range_adv = max(-0.45, min(0.45, range_adv))

    # nut adv: compare "effective nuts" - here we don't have hero nut freq directly, use texture + eq hints
    # positive if board favors hero's likely holdings (e.g. we are PFR on dry)
    nut_adv = 0.0
    if texture.paired:
        nut_adv -= 0.1  # sets for callers often
    if texture.flush_category == "monotone":
        nut_adv -= 0.15  # flushes for suited callers
    if texture.straight_category == "very_connected":
        nut_adv -= 0.1
    # if our eq high on dry board, assume we have nut advantage
    if hero_eq > 0.58 and texture.dynamic_score < 0.35:
        nut_adv += 0.18
    nut_adv += (0.5 - nut_v) * 0.4   # if villain has low nut%, we have relative nut adv
    nut_adv = max(-0.35, min(0.35, nut_adv))
    return range_adv, nut_adv


# --------------------------------------------------------------------------- #
# Sizing and Action Logic
# --------------------------------------------------------------------------- #

def _recommended_sizing(texture: BoardTexture, spr: float, range_adv: float, nut_adv: float,
                        eq: float, bet_to_call: float, multiway: bool, street_val: int) -> float:
    """Return pot fraction for a bet (0.25 - 1.5+)."""
    if bet_to_call > 0:
        # sizing when raising
        base = 0.8
    else:
        base = CONFIG.default_cbet_size if street_val == 3 else CONFIG.default_barrel_size

    # Texture
    if texture.flush_category == "rainbow" and texture.straight_category == "dry":
        base = CONFIG.cbet_dry_size
    elif texture.dynamic_score > 0.55 or texture.flush_category in ("two_tone", "monotone"):
        base = CONFIG.cbet_wet_size
    if texture.paired:
        base = CONFIG.cbet_paired_size

    # Advantage adjustments
    adv_factor = (range_adv + nut_adv * 0.7) * CONFIG.range_adv_bet_boost
    base += adv_factor

    # SPR / commitment
    if spr < 2.0:
        base = min(1.6, max(0.9, base + 0.4))  # bigger or shove-ish
    elif spr < CONFIG.overbet_spr_threshold and (nut_adv > 0.1 or eq > 0.65):
        base = min(1.3, base + 0.25)

    # Multiway smaller bets
    if multiway:
        base *= 0.82

    # Street: slightly larger barrels sometimes
    if street_val >= 4 and eq > 0.55:
        base = min(1.1, base * 1.05)

    # Clamp
    return max(0.33, min(1.6, round(base, 2)))


def _classify_hero_strength(hero_hand: List[str], board_cards: List[str], texture: BoardTexture) -> Dict[str, Any]:
    """Return rich hand classification for hero using treys + heuristic."""
    info = {"bucket": "unknown", "score": 4.0, "is_strong_value": False, "is_draw": False, "is_nut": False}
    if not hero_hand or len(hero_hand) != 2 or not board_cards:
        return info
    try:
        h = parse_cards("".join(hero_hand))
        b = parse_cards("".join(board_cards))
        score = _EVAL.evaluate(b, h)
        rc = _EVAL.get_rank_class(score)
        made = _EVAL.class_to_string(rc).lower()

        branks, bsuits, bvals = _get_board_components(board_cards)
        r1, r2 = hero_hand[0][0].upper(), hero_hand[1][0].upper()
        v1, v2 = RANK_VAL.get(r1, 0), RANK_VAL.get(r2, 0)
        board_high = max(bvals) if bvals else 0

        sc = 4.0
        if "straight flush" in made or "quad" in made or "full" in made:
            sc = 9.5
            info["is_nut"] = True
        elif "flush" in made:
            sc = 8.0
            info["is_nut"] = (max(v1, v2) >= 11)
        elif "straight" in made:
            sc = 7.5
        elif "three" in made or "set" in made or "trips" in made:
            sc = 8.0
            info["is_nut"] = (r1 == r2 and RANK_VAL.get(r1, 0) >= board_high - 1)
        elif "two pair" in made:
            sc = 6.5
        elif "pair" in made:
            sc = 5.0
            if max(v1, v2) > board_high:
                sc = 6.2  # overpair
            elif max(v1, v2) == board_high:
                sc = 5.8  # top pair
            info["is_strong_value"] = sc >= 5.8
        else:
            sc = 2.5  # high card or weak

        # draws (simple check using board texture + our cards)
        suited_hero = hero_hand[0][1].lower() == hero_hand[1][1].lower()
        if texture.has_flush_draw and suited_hero:
            info["is_draw"] = True
            sc = max(sc, 4.8)
        if texture.has_straight_draw:
            # rough if we have connecting cards
            if abs(v1 - v2) <= 3 or any(abs(v1 - bv) <= 2 or abs(v2 - bv) <= 2 for bv in bvals):
                info["is_draw"] = True
                sc = max(sc, 4.5)

        info["score"] = min(10.0, sc)
        info["bucket"] = made
        info["is_strong_value"] = info["is_strong_value"] or info["score"] >= 6.5
        info["is_nut"] = info["is_nut"] or info["score"] >= 9.0
    except Exception:
        pass
    return info


def _get_postflop_action(state: GameState, texture: BoardTexture, villain_range: Range,
                         eq: float, eq_vs_range: float, comp: Dict[str, float],
                         range_adv: float, nut_adv: float, blocker_score: float,
                         hero_strength: Dict[str, Any],
                         explo_mods: Optional[Dict[str, float]] = None,
                         icm_adj: Optional[Dict[str, Any]] = None) -> Tuple[Action, List[Action], List[str], Dict[str, float]]:
    """
    Core decision engine. Returns primary Action, list of alts, explanation parts, updated metrics.
    icm_adj (from nash.get_postflop_icm_adjustments) applied for short-stack tournament spots:
      - call_thresh += call_thresh_delta (tighter marginal calls)
      - semi/bluff thresh += bluff_thresh_delta
      - bet_freq *= aggression_mult
      - sizing *= protection_size_mult when protecting
      - metrics get icm_factor + icm_adjusted so A1 output tags postflop ICM too.
    """
    explanation_parts = [f"Texture: {texture.summary()}"]
    explo_mods = explo_mods or {}
    if explo_mods.get("notes_used"):
        explanation_parts.append("EXPLOIT MODE: using player notes for range adjustment")
    icm_adj = icm_adj or {"icm_active": False, "icm_factor": 0.0}
    if icm_adj.get("icm_active"):
        explanation_parts.append(f"ICM short-stack (factor~{icm_adj.get('icm_factor',0):.2f}) — adjusted thresholds/sizing for bubble survival")
    metrics: Dict[str, float] = {
        "equity_vs_random": round(eq, 4),
        "equity_vs_range": round(eq_vs_range, 4),
        "range_advantage": round(range_adv, 3),
        "nut_advantage": round(nut_adv, 3),
        "blocker_score": round(blocker_score, 3),
        "villain_value_pct": round(comp.get("value_pct", 0), 3),
        "villain_nut_pct": round(comp.get("nut_pct", 0), 3),
        "villain_air_pct": round(comp.get("air_pct", 0), 3),
        "villain_avg_str": round(comp.get("avg_strength", 0), 2),
        "spr": round(state.spr, 2),
        "texture_dynamic": round(texture.dynamic_score, 3),
        "hero_strength": round(hero_strength.get("score", 0), 1),
    }
    if explo_mods.get("notes_used"):
        metrics["explo_notes_used"] = 1.0
        if "bet_freq_mult" in explo_mods:
            metrics["explo_bet_freq_mult"] = round(explo_mods["bet_freq_mult"], 3)
        if "fold_to_cbet" in explo_mods:
            metrics["explo_fold_to_cbet"] = round(explo_mods["fold_to_cbet"], 3)
    if icm_adj.get("icm_active"):
        metrics["icm_factor"] = round(float(icm_adj.get("icm_factor", 0)), 3)
        metrics["icm_adjusted"] = 1.0
        if icm_adj.get("call_thresh_delta"):
            metrics["icm_call_delta"] = round(icm_adj["call_thresh_delta"], 3)

    pot = state.pot
    bet_to_call = state.bet_to_call
    spr = state.spr
    n_opp = state.num_opponents
    multi = n_opp > 1
    facing = (state.facing_action or "").lower()
    street_val = state.board.street.value

    story = _get_history_story(state)  # for dynamic decisions / story awareness (donk vs c/c, capped etc)

    alts: List[Action] = []

    if bet_to_call > 0:
        # ================================= FACING A BET =================================
        pot_odds = state.pot_odds
        metrics["pot_odds"] = round(pot_odds, 3)

        # Special cases: check-raise and donk
        if "check-raise" in facing or "cr" in facing:
            # Facing CR: villain usually very strong. Tighten calling standards.
            call_thresh = 0.62
            if nut_adv > 0.12 or hero_strength["is_nut"]:
                call_thresh = 0.48
            if eq_vs_range > call_thresh or (hero_strength["is_draw"] and texture.dynamic_score > 0.5 and eq_vs_range > 0.42):
                action = Action(action_type="call", reasoning="Call vs CR with sufficient equity / nut advantage.")
                explanation_parts.append(f"Call vs check-raise (eqr~{eq_vs_range*100:.0f}%)")
                alts.append(Action(action_type="raise", size_pot=2.2, reasoning="Occasional raise as bluff or for value if nutted"))
            else:
                action = Action(action_type="fold", reasoning="Facing check-raise - range is strong, insufficient equity.")
                explanation_parts.append(f"Fold to check-raise (eqr~{eq_vs_range*100:.0f}%)")
            return action, alts, explanation_parts, metrics

        if "donk" in facing:
            # Donk lead: often polarized (nuts or bluffs). Hero can raise wider for value or as bluff catcher raise.
            if hero_strength["is_strong_value"] or eq_vs_range > 0.58:
                sz = 2.0 if spr < 4 else 1.6
                action = Action(action_type="raise", size_pot=sz, reasoning="Raise donk for value - donk range polarized.")
                explanation_parts.append(f"Raise donk (size ~{sz:.1f}x)")
                alts.append(Action(action_type="call", reasoning="Call as trap with medium"))
            elif eq_vs_range > 0.48 or (blocker_score > 0.15 and eq_vs_range > 0.40):
                action = Action(action_type="call", reasoning="Call donk lead (range may be capped or bluffy).")
                explanation_parts.append(f"Call donk (eqr~{eq_vs_range*100:.0f}%)")
            else:
                action = Action(action_type="fold", reasoning="Fold to donk - insufficient vs polarized range.")
                explanation_parts.append("Fold to donk")
            return action, alts, explanation_parts, metrics

        # Standard facing bet (cbet, probe, barrel)
        call_thresh = pot_odds + 0.06  # small edge for position / future
        if texture.dynamic_score > 0.55:
            call_thresh -= 0.08  # more implied / draw equity on wet boards
        if multi:
            call_thresh += 0.07  # tighter multiway

        # History-aware: vs check-back / capped villain (called pre checked flop), hero can call wider
        if story.get("is_check_back") or story.get("check_call_story"):
            call_thresh -= 0.06  # capped range -> better pot odds / implied
            explanation_parts.append("vs capped check-back range (history)")
        if story.get("is_donk_lead"):
            call_thresh -= 0.04  # donk often polarized/bluffy
            explanation_parts.append("vs donk lead (polarized per story)")
        if story.get("prior_aggression", 0) > 1.8:
            call_thresh += 0.05  # aggro history -> value heavier

        # Exploitative: notes can force tighter calls (vs aggro or station who bets for value more)
        call_delta = float(explo_mods.get("call_thresh_delta", 0.0) or 0.0)
        if call_delta:
            call_thresh += call_delta
        if explo_mods.get("vs_bet_tighter"):
            call_thresh += 0.05
            explanation_parts.append("Explo: tighter vs bet (notes: high AF or passive nit betting range capped strong)")

        # ICM short stack adjustments (deeper support): tighter calls for marginal equity under survival pressure
        icm_call_d = float(icm_adj.get("call_thresh_delta", 0.0) or 0.0) if icm_adj.get("icm_active") else 0.0
        if icm_call_d:
            call_thresh += icm_call_d
            explanation_parts.append(f"ICM: tighter call thresh (+{icm_call_d:.3f}) for short-stack bubble")

        if hero_strength["is_nut"] or eq_vs_range > 0.72:
            action = Action(action_type="raise", size_pot=2.4 if spr > 3 else 1.0,
                            reasoning="Raise for value / build pot with nuts vs bet.")
            explanation_parts.append(f"Raise for value (eqr~{eq_vs_range*100:.0f}%)")
            alts.append(Action(action_type="call", reasoning="Call smaller"))
        elif eq_vs_range > call_thresh or (hero_strength["is_draw"] and texture.dynamic_score > 0.45 and eq_vs_range > max(0.36, pot_odds - 0.05)):
            # Explo: if value_only (station), only call if much stronger
            if explo_mods.get("value_only") and not hero_strength.get("is_strong_value") and eq_vs_range < 0.58:
                action = Action(action_type="fold", reasoning="Explo fold: vs station only continue with strong (notes).")
                explanation_parts.append("Explo: folded marginal vs station (value bet only for us later)")
            else:
                action = Action(action_type="call", reasoning="Call with equity, draws, or vs capped range.")
                explanation_parts.append(f"Call (eqr~{eq_vs_range*100:.0f}%, pot odds ~{pot_odds*100:.0f}%)")
                if eq_vs_range > 0.58 and not multi:
                    alts.append(Action(action_type="raise", size_pot=2.0, reasoning="Raise for value/thin"))
        else:
            action = Action(action_type="fold", reasoning="Fold - behind villain betting range + poor pot odds / texture.")
            explanation_parts.append(f"Fold (eqr~{eq_vs_range*100:.0f}%)")
        return action, alts, explanation_parts, metrics

    else:
        # ================================= NO BET TO US (check or bet decision) =================================
        # Low SPR special
        if spr < 1.8 and eq_vs_range > 0.48:
            sz = min(1.8, 1.0 + (spr - 1.0))
            action = Action(action_type="bet", size_pot=sz, reasoning="Low SPR - bet/commit with equity.")
            explanation_parts.append(f"Bet {sz*100:.0f}% (low SPR commit)")
            return action, alts, explanation_parts, metrics

        # Decide whether to bet and sizing
        bet_freq = 0.5
        if range_adv > 0.08 or nut_adv > 0.08:
            bet_freq += 0.25
        if hero_strength["is_strong_value"]:
            bet_freq = 0.95
        if hero_strength["is_draw"] and texture.dynamic_score > 0.5:
            bet_freq += 0.2
        if multi:
            bet_freq -= 0.15

        # EXPLOITABLE ADJUSTMENTS from notes (key for nit vs station etc)
        bet_mult = float(explo_mods.get("bet_freq_mult", 1.0) or 1.0)
        if bet_mult != 1.0:
            bet_freq = min(0.98, bet_freq * bet_mult)
            explanation_parts.append(f"Explo bet-freq x{bet_mult:.2f} (from player notes)")
        if explo_mods.get("bluff_more"):
            # lower effective threshold for semi bluffs
            pass  # we will adjust the should_bet condition below
        if explo_mods.get("value_only") or explo_mods.get("bluff_less"):
            # discourage bluffs
            bet_freq *= 0.65
            explanation_parts.append("Explo: value bet / check more (notes: low fold-to-cbet / calling station)")

        semi_thresh = CONFIG.semi_bluff_threshold
        if explo_mods.get("bluff_more"):
            semi_thresh = max(0.22, semi_thresh - 0.12)  # allow lower eq bluffs because of fold equity
            explanation_parts.append("Explo: bluff more (high fold-to-cbet note -> nit)")

        # ICM: raise semi-bluff bar (more fold equity required; lower aggression on marginals)
        if icm_adj.get("icm_active"):
            semi_thresh += float(icm_adj.get("bluff_thresh_delta", 0.0) or 0.0)
            bet_mult_icm = float(icm_adj.get("aggression_mult", 1.0) or 1.0)
            if bet_mult_icm != 1.0:
                bet_freq = min(0.98, bet_freq * bet_mult_icm)
                explanation_parts.append(f"ICM: aggression x{bet_mult_icm:.2f} (short bubble survival)")

        should_bet = (eq_vs_range >= semi_thresh or hero_strength["is_strong_value"]) and bet_freq > 0.35

        if should_bet:
            size = _recommended_sizing(texture, spr, range_adv, nut_adv, eq_vs_range,
                                       bet_to_call, multi, street_val)
            # Adjust for hero strength bucket
            if hero_strength["is_nut"]:
                size = min(1.4, size + 0.15)
            elif hero_strength["is_strong_value"]:
                size = max(size, 0.55)
            elif hero_strength["is_draw"]:
                size = max(0.4, min(0.65, size * 0.9))

            # ICM protection boost (short stack): larger sizes to protect equity / build when ahead
            if icm_adj.get("icm_active"):
                prot_m = float(icm_adj.get("protection_size_mult", 1.0) or 1.0)
                if prot_m > 1.01:
                    size = min(1.6, size * prot_m)
                    explanation_parts.append(f"ICM: protection size x{prot_m:.2f}")

            action = Action(
                action_type="bet",
                size_pot=round(size, 2),
                reasoning="Bet for value, protection, or semi-bluff based on range/nut adv + texture."
            )
            explanation_parts.append(f"Bet {size*100:.0f}% pot (range_adv={range_adv:+.2f}, nut_adv={nut_adv:+.2f})")

            # Alternatives
            small_sz = max(0.33, size - 0.2)
            alts.append(Action(action_type="bet", size_pot=round(small_sz, 2), reasoning="Smaller sizing for pot control / more calls"))
            if size > 0.9 and spr > 3:
                alts.append(Action(action_type="check", reasoning="Check for pot control / trap"))
        else:
            action = Action(
                action_type="check",
                reasoning="Check back - marginal equity or behind range; pot control."
            )
            explanation_parts.append(f"Check (eqr~{eq_vs_range*100:.0f}%, range_adv={range_adv:+.2f})")
            if eq_vs_range > 0.42 and not multi:
                alts.append(Action(action_type="bet", size_pot=0.4, reasoning="Probe bet as bluff or thin"))

        return action, alts, explanation_parts, metrics


# --------------------------------------------------------------------------- #
# Main Entry Point
# --------------------------------------------------------------------------- #

def get_postflop_decision(state: GameState, player_notes: Optional[Dict[str, Any]] = None) -> Decision:
    """
    Strong Heuristic GTO postflop decision (A1 primary brain).
    Rich range estimation, range/nut advantage, blockers, sophisticated sizing,
    special handling for donk/check-raise/multiway, rich Decision with metrics + explanation.
    """
    if not state.hero_hand or len(state.hero_hand) != 2 or not state.board.cards:
        return Decision(
            primary_action=Action(action_type="check", reasoning="Incomplete information"),
            explanation="Need hero hand + board for postflop.",
            confidence=0.0
        )

    texture = state.board.texture()
    villain_range = _estimate_villain_range(state, texture)

    # ICM short-stack postflop support (deeper than pure preflop push/fold)
    # When tmode + short (<=20bb), compute factor (respecting explicit + payout_structure via models/legacy),
    # then fetch lightweight adjustments for call thresh, bluff bars, aggression, protection.
    # These are applied in _get_postflop_action; metrics get "icm_factor" + "icm_adjusted" so
    # format_a1_advice surfaces "ICM-adjusted" tags on postflop too.
    icm_adj: Dict[str, Any] = {"icm_active": False, "icm_factor": 0.0}
    bb = float(getattr(state, "effective_stack", 100.0) or 100.0)
    tmode = bool(getattr(state, "tournament_mode", False))
    explicit_icm = float(getattr(state, "icm_factor", 0.0) or 0.0)
    if (tmode or explicit_icm > 0) and bb <= 22:
        try:
            from . import nash as _nash
            icm_f = explicit_icm
            if icm_f <= 0.0:
                n_rem = getattr(state, "players_remaining", None)
                if n_rem is None or n_rem < 2:
                    n_rem = (getattr(state, "num_opponents", 1) or 1) + 1
                is_ft = (n_rem or 99) <= 9
                ps = getattr(state, "payout_structure", None) or None
                icm_f = _nash.get_icm_factor(n_rem or 6, bb, is_final_table=is_ft, payout_structure=ps)
            if icm_f > 0:
                ps = getattr(state, "payout_structure", None) or None
                icm_adj = _nash.get_postflop_icm_adjustments(
                    bb, icm_f,
                    pot=getattr(state, "pot", 1.5),
                    bet_to_call=getattr(state, "bet_to_call", 0.0),
                    street_val=getattr(state.board, "street", None).value if getattr(state, "board", None) else 3,
                    payout_structure=ps,
                )
                icm_adj["icm_factor"] = icm_f  # ensure top level
        except Exception:
            icm_adj = {"icm_active": False, "icm_factor": 0.0}

    # Exploitative adjustment (pluggable) if notes or global mode enabled
    explo_mods: Dict[str, float] = {}
    effective_notes = player_notes or getattr(state, "player_notes", None) or {}
    if effective_notes or CONFIG.exploitative_mode:
        # If only mode flag but no specific notes, try manager default "villain"
        if not effective_notes and CONFIG.exploitative_mode:
            effective_notes = get_player_notes("villain")
        villain_range, explo_mods = apply_exploitative_range_adjuster(
            villain_range, effective_notes, texture,
            context={"street": state.board.street.value, "bet_to_call": state.bet_to_call, "position": state.hero_position}
        )

    # Early exit heuristics for hot paths: obvious spots can short-circuit expensive range sweeps / eq_vs_range MC
    # (range comp, blocker, full adv calc) while still producing correct rich Decision. Preserves A1 logic.
    bet_to_call_early = state.bet_to_call
    spr_early = state.spr
    n_opp_early = max(1, state.num_opponents)
    street_early = state.board.street.value if getattr(state.board, 'street', None) else 3
    if bet_to_call_early <= 0 and spr_early < 1.5:
        # Low SPR no bet facing: almost always bet/commit if any equity; skip heavy analysis
        try:
            hero_t = parse_cards("".join(state.hero_hand))
            board_t = parse_cards("".join(state.board.cards))
            eq_quick = equity_vs_random(hero_t, board_t, n_opp_early, iters=CONFIG.fast_equity_iters)
        except Exception:
            eq_quick = 0.5
        sz = min(1.8, 1.0 + (spr_early - 1.0))
        act = Action(action_type="bet", size_pot=sz, reasoning="Low SPR commit (early exit heuristic).")
        return Decision(primary_action=act, explanation="Low SPR <1.5 no bet to call — bet/commit with equity (early).", confidence=0.8,
                        metrics={"spr": round(spr_early,2), "equity_vs_random": round(eq_quick,4)}, texture_summary=texture.summary())
    if not villain_range or not getattr(villain_range, 'weights', None):
        # No range info: fall back to random eq only, skip vs-range + comp sweeps
        try:
            hero_t = parse_cards("".join(state.hero_hand))
            board_t = parse_cards("".join(state.board.cards))
            eq_r = equity_vs_random(hero_t, board_t, n_opp_early, iters=CONFIG.fast_equity_iters)
        except Exception:
            eq_r = 0.5
        # delegate to action logic but with dummy comp (cheap path)
        dummy_comp = {"value_pct": 0.3, "nut_pct": 0.1, "draw_pct": 0.2, "air_pct": 0.5, "avg_strength": 3.5, "total_combos": 0.0}
        dummy_adv = (0.0, 0.0)
        dummy_block = 0.0
        dummy_hero = _classify_hero_strength(state.hero_hand, state.board.cards, texture)
        prim, alts, exps, mets = _get_postflop_action(state, texture, villain_range or Range(), eq_r, eq_r, dummy_comp, dummy_adv[0], dummy_adv[1], dummy_block, dummy_hero, explo_mods={})
        return Decision(primary_action=prim, alternatives=alts, explanation=" | ".join(exps), confidence=0.65, metrics=mets, texture_summary=texture.summary())

    # Parse cards
    try:
        hero_treys = parse_cards("".join(state.hero_hand))
        board_treys = parse_cards("".join(state.board.cards))
    except Exception:
        hero_treys = []
        board_treys = []

    # Equity
    eq = equity_vs_random(hero_treys, board_treys, state.num_opponents, iters=CONFIG.default_equity_iters)
    eq_vs_r = equity_vs_range(hero_treys, board_treys, villain_range, iters=CONFIG.fast_equity_iters)

    # Composition + advantages + blockers
    comp = _compute_range_composition(villain_range, state.board.cards, texture)
    range_adv, nut_adv = _compute_range_and_nut_advantage(eq_vs_r, comp, texture)
    blocker_score = _compute_blocker_score(state.hero_hand, villain_range, texture, state.board.cards)

    # Hero hand classification
    hero_str = _classify_hero_strength(state.hero_hand, state.board.cards, texture)

    # Expose story for rich output / metrics
    story = _get_history_story(state)

    # Core decision
    primary, alts, exp_parts, metrics = _get_postflop_action(
        state, texture, villain_range, eq, eq_vs_r, comp, range_adv, nut_adv, blocker_score, hero_str,
        explo_mods=explo_mods,
        icm_adj=icm_adj if icm_adj.get("icm_active") else None
    )

    # Enrich metrics and explanation
    metrics["confidence_internal"] = 0.78
    if story.get("events"):
        metrics["history_events"] = float(story["events"])
        metrics["history_agg"] = story.get("prior_aggression", 0.0)
        if story.get("is_check_back"):
            metrics["history_capped"] = 1.0
        if story.get("is_donk_lead"):
            metrics["history_donk"] = 1.0
        story_tag = 'check-back' if story.get('is_check_back') else ('donk' if story.get('is_donk_lead') else ('check-call' if story.get('check_call_story') else ('aggro' if story.get('prior_aggression',0)>1 else 'passive')))
        exp_parts.append(f"story:{story_tag}")
    exp = " | ".join(exp_parts)

    # Add human-friendly summary to explanation
    if "bet" in primary.action_type:
        exp += f" | Villain range ~{comp['total_combos']:.0f} combos ({comp['value_pct']*100:.0f}% value)"
    if abs(blocker_score) > 0.12:
        exp += f" | Blockers: {'good' if blocker_score > 0 else 'bad'} ({blocker_score:+.2f})"

    confidence = 0.72 + (0.08 if abs(range_adv) > 0.1 else 0) + (0.05 if hero_str.get("is_nut") else 0)
    confidence = min(0.92, max(0.55, confidence))

    hand_cls = ""
    try:
        if state.hero_hand and len(state.hero_hand) == 2:
            from .parsing import hand_class
            hand_cls = hand_class(state.hero_hand[0], state.hero_hand[1])
        else:
            hand_cls = "".join(state.hero_hand)
    except Exception:
        try:
            hand_cls = "".join(state.hero_hand)
        except Exception:
            hand_cls = "??"

    return Decision(
        primary_action=primary,
        alternatives=alts,
        explanation=exp,
        confidence=round(confidence, 2),
        metrics=metrics,
        texture_summary=texture.summary(),
        hand_class=hand_cls,
    )


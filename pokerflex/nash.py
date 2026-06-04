"""Nash push/fold solver — computed equilibria, not copied charts.

Used by the primary A1 brain (preflop short-stack + ICM; THE UNAMBIGUOUS DEFAULT) and preserved for legacy fallback path (forced debug ONLY, never primary).

Heads-up (SB vs BB) push/fold is a genuinely *solved* problem, so this computes
the chip-EV Nash equilibrium directly from equities rather than hard-coding a
chart. That makes the short-stack advice actually correct.

  - Equities come from a one-time precomputed 169x169 preflop all-in equity
    matrix (cached to equity_matrix.json), so solving any depth afterwards is
    instant.
  - ICM support: get_icm_factor (now with concrete payout_structure e.g. [0.5,0.3,0.2]
    or standard_payout_curve) for tournament_mode / final tables / bubbles.
    Basic model adjusts EV thresholds for preflop short (<=~18bb push/fold):
    marginal shoves tighter, calls looser under ICM pressure.
    - Deeper short-stack ICM (new): get_postflop_icm_adjustments + wiring for 8-20bb
    flop/turn near bubble/final. Lightweight approx adjusts call thresholds (tighter
    marginals), bluff bars, aggression, protection sizing, fold equity reqs.
    Consulted by postflop when tournament_mode + short. Simple independent model
    (no full solver). simulate_shortstack_icm_ev helper for $EV impact of shove/call.
    payout_structure now concretely supported (defaults 50/30/20 etc for 6-9p; passed
    down to factor + postflop adj). Keep factor simple/optional; full complex ICM out of scope.
  - HONEST LIMITS (surfaced, not hidden):
      * Multiway short-stack is NOT solved here yet (needs the
        independent-caller approximation) — heads-up only.
      * No antes yet. Tournaments have antes, which widen ranges; a no-ante
        Nash runs slightly tight. Next refinement.
      * Deep stacks: full ICM (not just push/fold) is complex; note it in
        advisor when tournament_mode + deep regime.

Run `python nash.py` to build/refresh the matrix and print verification solves.
"""
import json
import os
import random
from itertools import combinations
from typing import Optional
from treys import Card, Evaluator

# Canonical rank/suit constants (source of truth in ranges.py)
from .ranges import RANK_ORDER, SUITS
_EVAL = Evaluator()
_HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE = os.path.join(_HERE, "equity_matrix.json")
_FULL_DECK = [Card.new(r + s) for r in RANK_ORDER for s in SUITS]


# --------------------------------------------------------------------------- #
# Hand classes & combos
# --------------------------------------------------------------------------- #
def all_classes():
    """The 169 canonical starting-hand classes (pairs, suited, offsuit)."""
    r, n, out = RANK_ORDER, len(RANK_ORDER), []
    for i in range(n - 1, -1, -1):
        for j in range(n - 1, -1, -1):
            hi, lo = r[max(i, j)], r[min(i, j)]
            if i == j:
                out.append(hi + lo)            # pair
            elif i > j:
                out.append(hi + lo + "s")      # suited
            else:
                out.append(hi + lo + "o")      # offsuit
    return out


def class_combos(cls):
    """Concrete card combos (lists of treys ints) for a hand class."""
    if len(cls) == 2:                                   # pair -> 6 combos
        cards = [Card.new(cls[0] + s) for s in SUITS]
        return [list(c) for c in combinations(cards, 2)]
    hi, lo, t = cls[0], cls[1], cls[2]
    if t == "s":                                        # suited -> 4
        return [[Card.new(hi + s), Card.new(lo + s)] for s in SUITS]
    return [[Card.new(hi + s1), Card.new(lo + s2)]      # offsuit -> 12
            for s1 in SUITS for s2 in SUITS if s1 != s2]


_CLASSES = all_classes()
_COMBOS = {c: class_combos(c) for c in _CLASSES}
_COMBO_COUNT = {c: len(v) for c, v in _COMBOS.items()}
TOTAL_COMBOS = 1326.0   # C(52,2)


# --------------------------------------------------------------------------- #
# Equity matrix (precomputed once, cached)
# --------------------------------------------------------------------------- #
def build_matrix(iters=1500, seed=0, progress=False):
    """Monte-Carlo preflop all-in equity for every class pair. hero win+0.5*tie."""
    rng = random.Random(seed)
    eq = {}
    pairs = [(a, b) for a in range(len(_CLASSES)) for b in range(a, len(_CLASSES))]
    for k, (a, b) in enumerate(pairs):
        ca, cb = _CLASSES[a], _CLASSES[b]
        combos_a, combos_b = _COMBOS[ca], _COMBOS[cb]
        wins, n = 0.0, 0
        for _ in range(iters):
            ha = combos_a[rng.randrange(len(combos_a))]
            hb = None
            for _try in range(25):
                cand = combos_b[rng.randrange(len(combos_b))]
                if cand[0] not in ha and cand[1] not in ha:
                    hb = cand
                    break
            if hb is None:
                continue
            used = {ha[0], ha[1], hb[0], hb[1]}
            board = []
            while len(board) < 5:
                c = _FULL_DECK[rng.randrange(52)]
                if c not in used:
                    used.add(c)
                    board.append(c)
            sa, sb = _EVAL.evaluate(board, ha), _EVAL.evaluate(board, hb)
            wins += 1.0 if sa < sb else (0.5 if sa == sb else 0.0)
            n += 1
        e = wins / n if n else 0.5
        eq[ca + "|" + cb] = e
        eq[cb + "|" + ca] = 1.0 - e
        if progress and k % 2000 == 0:
            print(f"  matrix {k}/{len(pairs)} pairs…", flush=True)
    return eq


def load_matrix(rebuild=False, iters=1500):
    if not rebuild and os.path.exists(_CACHE):
        with open(_CACHE, encoding="utf-8") as f:
            return json.load(f)
    print(f"Building equity matrix (iters={iters})… one-time, ~couple minutes.")
    eq = build_matrix(iters=iters, progress=True)
    with open(_CACHE, "w", encoding="utf-8") as f:
        json.dump(eq, f)
    print(f"Cached -> {_CACHE}")
    return eq


# --------------------------------------------------------------------------- #
# Solver
# --------------------------------------------------------------------------- #
def equity_vs_range(hero_cls, range_set, eq):
    num = den = 0.0
    for o in range_set:
        w = _COMBO_COUNT[o]
        num += w * eq[hero_cls + "|" + o]
        den += w
    return num / den if den else 0.5


def range_pct(range_set):
    return 100.0 * sum(_COMBO_COUNT[c] for c in range_set) / TOTAL_COMBOS


def solve_hu(stack_bb, eq, iters=400, ante=0.0, icm_factor=0.0):
    """Heads-up chip-EV (or ICM-adjusted) Nash push/fold via fictitious play.

    Returns (jam, call) sets of hand classes.

    `ante` is a big-blind ante in bb (posted by BB — the common modern format);
    0 = no ante. It is dead money, so it widens both ranges.
    `icm_factor` > 0 enables basic ICM pressure adjustment (for tournament_mode /
    final tables / bubbles). It does *not* run full $ICM (that requires payout
    curve + all stack sizes + resulting-stack ICM recalc on every outcome).
    Instead it uses a simple, fast factor to tweak EV thresholds inside the
    best-response:
      - Marginal shoves become tighter (extra EV required to risk busting
        under pay-jump pressure).
      - Calls become looser (caller gets implicit ICM benefit from
        potentially laddering by eliminating shover).

    SB (button) shoves S or folds; BB calls or folds.
      SB folds:            EV = -0.5
      SB shoves, BB folds: EV = +(1 + ante)
      SB shoves, called:   EV = S*(2E-1)
      BB folds:            EV = -(1 + ante)
      BB calls:            EV = S*(2E'-1)  -> call iff E' > 0.5 - (1+ante)/(2S)

    Pure best-response cycles at short stacks, so each player best-responds to
    the running AVERAGE of the opponent's play (fictitious play), which
    converges to the equilibrium.
    """
    S = float(stack_bb)
    bb_dead = 1.0 + ante                   # BB's committed blind + ante
    thr = 0.5 - bb_dead / (2.0 * S)
    icm_factor = max(0.0, float(icm_factor or 0.0))
    if icm_factor > 0:
        # Loosen calls: lower the equity threshold needed to call
        thr = thr - (icm_factor * 0.09)
        thr = max(0.28, min(0.49, thr))
    cc = _COMBO_COUNT
    classes = _CLASSES
    sb_avg = {h: 0.5 for h in classes}     # avg P(SB jams h)
    bb_avg = {h: 0.5 for h in classes}     # avg P(BB calls h)

    def weq(h, wts, wsum):                 # equity of h vs a combo*prob-weighted range
        if wsum <= 0:
            return 0.5
        return sum(w * eq[h + "|" + o] for o, w in wts.items()) / wsum

    for t in range(1, iters + 1):
        bb_w = {o: bb_avg[o] * cc[o] for o in classes}
        bb_wsum = sum(bb_w.values())
        C = bb_wsum / TOTAL_COMBOS
        # SB best response (shove decision)
        sb_br = {}
        for h in classes:
            chip_ev = (1.0 - C) * bb_dead + C * (S * (2.0 * weq(h, bb_w, bb_wsum) - 1.0))
            fold_ev = -0.5
            barrier = fold_ev
            if icm_factor > 0:
                # Tighter shoves: demand extra +EV to justify the ICM downside of busting
                barrier = fold_ev + (icm_factor * 0.28)
            sb_br[h] = 1.0 if chip_ev > barrier else 0.0

        sb_w = {o: sb_avg[o] * cc[o] for o in classes}
        sb_wsum = sum(sb_w.values())
        bb_br = {h: (1.0 if weq(h, sb_w, sb_wsum) > thr else 0.0) for h in classes}

        step = 1.0 / (t + 1)
        for h in classes:
            sb_avg[h] += (sb_br[h] - sb_avg[h]) * step
            bb_avg[h] += (bb_br[h] - bb_avg[h]) * step

    jam = {h for h in classes if sb_avg[h] >= 0.5}
    call = {h for h in classes if bb_avg[h] >= 0.5}
    return jam, call


def solve_multiway_shove(stack_bb, k, eq, ante=0.0, icm_factor=0.0):
    """First-in open-shove range for a non-blind seat with k players behind.

    APPROXIMATION (independent callers): each of the k players behind is assumed
    to call with the heads-up call range at this depth, independently; when
    called, hero's equity is taken vs one such caller. Ignores multiway equity
    dilution — ICM is approximated via icm_factor threshold adjustment only.
    Returns (jam_set, c) where c is each opponent's assumed call frequency.
    """
    S = float(stack_bb)
    icm_factor = max(0.0, float(icm_factor or 0.0))
    # Pass icm_factor down so proxy HU caller ranges are also ICM-adjusted (consistent)
    _, call = solve_hu(stack_bb, eq, ante=ante, icm_factor=icm_factor)
    c = sum(_COMBO_COUNT[o] for o in call) / TOTAL_COMBOS
    p_fold_all = (1.0 - c) ** k
    dead = 1.5 + ante                                  # SB + BB + BB-ante won when all fold
    jam = set()
    for h in _CLASSES:
        E = equity_vs_range(h, call, eq)
        ev = p_fold_all * dead + (1.0 - p_fold_all) * S * (2.0 * E - 1.0)
        barrier = 0.0
        if icm_factor > 0:
            # Tighter open-shoves under ICM: require a buffer of +chipEV
            barrier = icm_factor * 0.05
        if ev > barrier:
            jam.add(h)
    return jam, c


# --------------------------------------------------------------------------- #
# Basic ICM model (initial short-stack push/fold support)
# --------------------------------------------------------------------------- #
def standard_payout_curve(n: int, paid_places: Optional[int] = None) -> list:
    """Rough standard MTT payout fractions for places 1..n (0 for unpaid).
    Sum to ~1.0. Used for future full $ICM; for now the factor estimator
    derives a simple pressure scalar from n + final table.
    """
    if paid_places is None:
        # For small final tables pay most or all; for larger use ~20-25% rule of thumb
        if n <= 9:
            paid_places = max(3, n - 1)  # e.g. 6h pays 5? but cap reasonable; 9h pays ~8 or adjust
        else:
            paid_places = max(3, min(n, int(round(n * 0.22))))
    paid_places = min(paid_places, n)
    if paid_places < 2 or n < 2:
        return [1.0] + [0.0] * (n - 1)
    # Simple power-law weights favoring top payouts (common approx)
    weights = [1.0 / (place ** 0.82) for place in range(1, paid_places + 1)]
    total = sum(weights)
    payouts = [w / total for w in weights] + [0.0] * (n - paid_places)
    return payouts


def get_icm_factor(n_remaining: int, stack_bb: float = 10.0, is_final_table: bool = False, payout_structure: Optional[list] = None) -> float:
    """Heuristic to select a basic icm_factor [0.0, ~0.30] for the spot.
    Higher = more ICM pressure (tighter marginal shoves, looser calls).
    - 0.0  : pure chip-EV (default, cash or no pay jumps)
    - 0.08-0.15 : moderate final table / bubble pressure
    - 0.20+ : high ICM (near big pay jump, 3-6 players left, short stacks)
    Used by preflop when tournament_mode=True or CONFIG.icm_enabled.
    Now accepts optional payout_structure (e.g. [0.5,0.3,0.2]) for concrete support;
    steeper top-heavy payouts slightly increase the pressure scalar (used for
    postflop short-stack ICM approx too).
    """
    if n_remaining <= 2:
        return 0.0  # HU payouts are linear in stack fraction => chip-EV == ICM-EV
    f = 0.0
    if is_final_table or n_remaining <= 9:
        f += 0.10
    if n_remaining <= 6:
        f += 0.08
    if n_remaining <= 4:
        f += 0.05
    # ICM pressure most relevant for short-mid stacks in push/fold (pay jumps bite)
    if 4 <= stack_bb <= 18:
        f += 0.04
    # Rough extra from fewer paid relative to field (steeper curve)
    f += min(0.06, 1.8 / max(2, n_remaining))
    # Concrete payout support: top-heavy structures (common MTT) -> extra ICM pressure for survival
    if payout_structure and isinstance(payout_structure, (list, tuple)) and len(payout_structure) >= 2:
        try:
            ps = [float(x) for x in payout_structure if x is not None]
            if ps:
                top = ps[0]
                if top >= 0.42:
                    f += 0.025
                elif top >= 0.35:
                    f += 0.015
                # extra if bottom paid places get very little
                if len(ps) >= 3 and (ps[-1] or 0) < 0.08:
                    f += 0.01
        except Exception:
            pass
    return round(max(0.0, min(0.32, f)), 3)


def get_postflop_icm_adjustments(
    stack_bb: float,
    icm_factor: float = 0.0,
    pot: float = 1.5,
    bet_to_call: float = 0.0,
    street_val: int = 3,
    payout_structure: Optional[list] = None,
) -> dict:
    """Lightweight postflop ICM approximation (usable for 8-20bb stacks on flop/turn
    near bubble/final table). Adjusts equity targets, fold equity requirements,
    call thresholds, aggression, and protection sizing for marginal spots.

    Simple scalar model driven by icm_factor (from get_icm_factor or explicit).
    Uses payout_structure (if provided) for extra pressure when top-heavy.
    Returns deltas/mults that postflop heuristics consult (e.g. call_thresh += delta,
    bet_freq *= mult, size *= protection_mult).

    When inactive (deep stack or icm_factor=0), returns {"icm_active": False}.
    This is *not* a full ICM solver (no full tree of future streets/stacks); it's
    a fast heuristic boost for "deep in a tournament, short, bubble" use-case.
    """
    icm_f = max(0.0, float(icm_factor or 0.0))
    S = float(stack_bb)
    if icm_f <= 0.0 or S > 22 or S < 4:
        return {"icm_active": False, "icm_factor": 0.0}

    adj = {
        "icm_active": True,
        "icm_factor": round(icm_f, 3),
        "call_thresh_delta": 0.0,
        "bluff_thresh_delta": 0.0,
        "aggression_mult": 1.0,
        "protection_size_mult": 1.0,
        "fold_equity_mult": 1.0,
        "note": "ICM short-stack approx (tighter marginal calls, lower bluff freq, protect)",
    }

    base_pressure = icm_f * (1.15 if 8 <= S <= 18 else 0.75)
    # Facing bet: ICM survival bias -> tighter calls on marginal equity (preserve stack for payjumps)
    # (differs slightly from preflop caller looseness, which benefits from potential elim/ladder)
    adj["call_thresh_delta"] = round(0.045 * base_pressure + (0.025 if S < 13 else 0.01), 3)

    # Betting / semi-bluff: higher bar (need more eq or fold equity to justify bustout risk)
    adj["bluff_thresh_delta"] = round(0.04 * base_pressure, 3)
    adj["aggression_mult"] = max(0.62, round(1.0 - 0.95 * base_pressure, 2))

    # Low-SPR / commitment: boost sizing for protection (deny eq when ahead; ICM values current equity realization)
    if bet_to_call <= 0 or (S / max(pot or 1.0, 1.0)) < 3.0:
        adj["protection_size_mult"] = round(1.0 + 0.65 * min(0.9, base_pressure), 2)

    adj["fold_equity_mult"] = round(1.0 + 0.55 * base_pressure, 2)

    # Payout concrete: top-heavy (e.g. 50/30/20) amplifies caution vs flat 40/25/20/10/5
    if payout_structure and len(payout_structure) >= 2:
        try:
            ps = [float(x) for x in payout_structure if x is not None]
            if ps and ps[0] > 0.40:
                adj["call_thresh_delta"] = round(adj["call_thresh_delta"] + 0.012, 3)
                adj["aggression_mult"] = max(0.58, adj["aggression_mult"] * 0.92)
                adj["note"] += " (top-heavy payouts)"
        except Exception:
            pass

    return adj


def simulate_shortstack_icm_ev(
    n_remaining: int,
    hero_stack_bb: float,
    pot_bb: float = 2.0,
    equity: float = 0.5,
    action: str = "shove",
    payout_structure: Optional[list] = None,
    players_behind: int = 1,
) -> dict:
    """Small ICM sim helper (for CLI 'icm-sim' / direct use).
    Returns approx chipEV vs ICM $EV impact of a shove/call/fold in the *current*
    payout for the spot. Illustrative only (crude independent model; no full
    multiway future-street recursion). High value for "what does ICM say my
    marginal shove is worth in $ near bubble?"

    Example usage (from run_brain or python):
      from pokerflex.nash import simulate_shortstack_icm_ev, standard_payout_curve
      ev = simulate_shortstack_icm_ev(6, 12, 3.5, 0.47, "shove", [0.5,0.3,0.2])
      print(ev)
    """
    n = max(2, int(n_remaining or 6))
    payouts = list(payout_structure) if payout_structure else standard_payout_curve(n)
    while len(payouts) < n:
        payouts.append(0.0)
    payouts = [float(p) for p in payouts[:n]]
    total_p = sum(payouts) or 1.0
    payouts = [p / total_p for p in payouts]

    S = float(hero_stack_bb)
    pot = float(pot_bb or 2.0)
    eq = max(0.01, min(0.99, float(equity or 0.5)))
    k = max(1, int(players_behind or 1))

    # crude current place approx
    total_assumed = max(S * 1.8, S * n * 0.55 + 15)
    hero_frac = max(0.02, min(0.85, S / total_assumed))
    place = max(1, min(n, int(round(1 + (1 - hero_frac) * (n - 1)))))
    icm_now = payouts[place - 1] if place - 1 < len(payouts) else payouts[-1]

    results = {"n_remaining": n, "payouts_used": [round(p * 100, 1) for p in payouts[:min(6, len(payouts))]] }

    if action.lower().startswith(("shove", "push", "allin", "jam")):
        # approx fold equity (higher k behind -> lower p_fold_all)
        p_fold = max(0.08, 0.72 - (k - 1) * 0.13)
        win_fold = pot * 1.15
        win_called = S * (2 * eq - 1) + (pot * 0.6)
        chip_ev = p_fold * win_fold + (1 - p_fold) * win_called

        # ICM outcomes (stack deltas -> place shift)
        new_s_fold = S + win_fold
        new_frac_f = min(0.88, new_s_fold / (total_assumed + win_fold * 0.8))
        new_place_f = max(1, min(n, int(round(1 + (1 - new_frac_f) * (n - 1)))))
        icm_fold = payouts[new_place_f - 1] if new_place_f - 1 < len(payouts) else 0.0

        icm_lose = payouts[-1] if n > 1 else 0.0
        icm_win_called = icm_fold  # approx (win the pot+)
        icm_ev = p_fold * icm_fold + (1 - p_fold) * (eq * icm_win_called + (1 - eq) * icm_lose)

        # demo $ impact (scale to 1000 unit pool; user can mentally * real prize pool /1000)
        delta_units = (icm_ev - icm_now)
        dollar_est = round(delta_units * 1000, 1)
        results.update({
            "action": "shove",
            "chip_ev_bb": round(chip_ev, 2),
            "icm_ev_approx": round(icm_ev, 4),
            "icm_dollar_impact_est": dollar_est,
            "note": "Light ICM approx: pressure often shrinks +chipEV spots (bustout -> 0 payout risk). Scale est by your pool.",
        })
    elif action.lower() == "fold":
        chip_ev = -0.5
        # fold may ladder slightly in pure ICM (others eliminate each other)
        icm_ev = min(0.99, icm_now * 1.01) if n > 3 else icm_now
        results.update({
            "action": "fold",
            "chip_ev_bb": chip_ev,
            "icm_ev_approx": round(icm_ev, 4),
            "icm_dollar_impact_est": round((icm_ev - icm_now) * 1000, 1),
            "note": "Fold preserves stack/ladder chance under ICM (but gives up dead money).",
        })
    else:
        results.update({
            "action": action,
            "chip_ev_bb": 0.0,
            "icm_ev_approx": icm_now,
            "icm_dollar_impact_est": 0.0,
            "note": "Stub for non-shove/fold; use for shove/call/fold comparisons.",
        })

    results["hero_stack_bb"] = S
    results["pot_bb"] = pot
    return results


# --------------------------------------------------------------------------- #
# Public decision API (cached per stack)
# --------------------------------------------------------------------------- #
_MATRIX = None
_HU_CACHE = {}
_MW_CACHE = {}


def _matrix():
    global _MATRIX
    if _MATRIX is None:
        _MATRIX = load_matrix()
    return _MATRIX


def _solved_hu(stack_bb, ante, icm_factor=0.0):
    icm_f = round(float(icm_factor or 0.0), 4)
    key = (int(round(stack_bb)), round(float(ante), 2), icm_f)
    if key not in _HU_CACHE:
        _HU_CACHE[key] = solve_hu(key[0], _matrix(), ante=key[1], icm_factor=icm_f)
    return _HU_CACHE[key]


def _solved_mw(stack_bb, k, ante, icm_factor=0.0):
    icm_f = round(float(icm_factor or 0.0), 4)
    key = (int(round(stack_bb)), int(k), round(float(ante), 2), icm_f)
    if key not in _MW_CACHE:
        _MW_CACHE[key] = solve_multiway_shove(key[0], key[1], _matrix(), ante=key[2], icm_factor=icm_f)
    return _MW_CACHE[key]


def hu_decision(position, hand_class, stack_bb, ante=0.0, icm_factor=0.0):
    """Heads-up push/fold decision. position: 'SB' (shover) or 'BB' (caller).

    icm_factor: 0.0 for pure chip-EV (default). >0 applies basic ICM threshold
    adjustments (see solve_hu). Use nash.get_icm_factor(...) to auto-pick for
    a final table / tournament spot.

    Returns (action, detail_dict) or (None, reason) if not a HU push/fold spot.
    The returned dict now may include 'icm_factor' for downstream.
    """
    pos = (position or "").upper()
    icm_f = float(icm_factor or 0.0)
    jam, call = _solved_hu(stack_bb, ante, icm_f)
    extra = {"icm_factor": icm_f} if icm_f > 0 else {}
    if pos == "SB":
        act = "SHOVE" if hand_class in jam else "FOLD"
        det = {"role": "shove/fold", "jam_pct": range_pct(jam)}
        det.update(extra)
        return act, det
    if pos == "BB":
        act = "CALL" if hand_class in call else "FOLD"
        det = {"role": "call vs shove", "call_pct": range_pct(call)}
        det.update(extra)
        return act, det
    return None, "heads-up push/fold needs SB (shover) or BB (caller)"


def multiway_shove_decision(hand_class, stack_bb, k, ante=0.0, icm_factor=0.0):
    """Approximate first-in open-shove decision with k players behind (k >= 1).

    icm_factor: see hu_decision.
    """
    icm_f = float(icm_factor or 0.0)
    jam, c = _solved_mw(stack_bb, k, ante, icm_f)
    extra = {"icm_factor": icm_f} if icm_f > 0 else {}
    act = "SHOVE" if hand_class in jam else "FOLD"
    det = {"role": "open-shove (approx)", "jam_pct": range_pct(jam),
           "caller_pct": 100.0 * c, "players_behind": k}
    det.update(extra)
    return act, det


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #
def main():
    """Run verification / matrix build (exposed for shims and `python -m pokerflex.nash`)."""
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    eq = load_matrix(rebuild=("--rebuild" in sys.argv))

    print("\n=== matrix sanity (known all-in equities) ===")
    checks = [("AA", "KK", "~82%"), ("AA", "AKs", "~88%"), ("AKs", "QQ", "~46%"),
              ("AKo", "22", "~48%"), ("JTs", "AKo", "~41%")]
    for a, b, note in checks:
        print(f"  {a} vs {b}: {eq[a+'|'+b]*100:5.1f}%   (expect {note})")

    print("\n=== HU Nash push/fold solves ===")
    for S in (5, 8, 10, 12, 15, 20, 25):
        jam, call = solve_hu(S, eq)
        print(f"  {S:2}bb:  SB jams {range_pct(jam):4.1f}%   |   BB calls {range_pct(call):4.1f}%")

    print("\n=== antes widen ranges (10bb, BB-ante) ===")
    for a in (0.0, 0.5, 1.0):
        jam, call = solve_hu(10, eq, ante=a)
        print(f"  ante={a:.1f}:  SB jams {range_pct(jam):4.1f}%   |   BB calls {range_pct(call):4.1f}%")

    print("\n=== multiway open-shove (approx, 10bb, no ante; more behind -> tighter) ===")
    for k in (1, 2, 4, 8):
        jam, c = solve_multiway_shove(10, k, eq)
        print(f"  {k} behind:  shove {range_pct(jam):4.1f}%   (each assumed to call ~{c*100:.0f}%)")

    print("\n=== spot decisions ===")
    for pos, hand, S in [("SB", "72o", 10), ("SB", "K9o", 10), ("BB", "A5o", 10),
                         ("BB", "QJs", 10), ("SB", "A2o", 20), ("BB", "22", 20)]:
        act, det = hu_decision(pos, hand, S)
        print(f"  {pos} {hand} @ {S}bb -> {act}   ({det})")

    # ----------------------------------------------------------------------- #
    # ICM vs chip-EV comparison (key for task: short-stack push/fold ICM)
    # ----------------------------------------------------------------------- #
    print("\n=== ICM vs chip-EV (basic factor adjustment) ===")
    print("   icm_factor=0 is pure chip-EV; >0 applies threshold tweaks for tournaments.")
    for S in (8, 10, 12):
        print(f"  --- {S}bb HU ---")
        for icmf in (0.0, 0.10, 0.18):
            jam, call = solve_hu(S, eq, icm_factor=icmf)
            print(f"    factor={icmf:.2f}: SB jam {range_pct(jam):4.1f}% | BB call {range_pct(call):4.1f}%")

    print("\n=== 6-handed final table 10bb example (task requirement) ===")
    print("   (6 players, ~10bb effective, final table => moderate-high ICM pressure)")
    n6 = 6
    f_est = get_icm_factor(n6, 10.0, is_final_table=True)
    print(f"   auto-estimated icm_factor for this spot: {f_est}")
    for icmf in (0.0, f_est, 0.20):
        jam, call = solve_hu(10, eq, icm_factor=icmf)
        print(f"    HU factor={icmf:.2f}: SB jams {range_pct(jam):4.1f}% | BB calls {range_pct(call):4.1f}%")
    print("    Multiway open-shove (k=5 behind for UTG in 6h):")
    for icmf in (0.0, f_est):
        jam, c = solve_multiway_shove(10, 5, eq, icm_factor=icmf)
        print(f"      factor={icmf:.2f}: jam {range_pct(jam):4.1f}% (caller proxy ~{c*100:.0f}%)")

    # Payout concrete + deeper ICM (postflop + sim helper) demo
    print("\n=== Concrete payout_structure + deeper short ICM (postflop approx + sim helper) ===")
    p50_30_20 = [0.50, 0.30, 0.20]
    p40_25_20_10_5 = [0.40, 0.25, 0.20, 0.10, 0.05]
    f_p = get_icm_factor(6, 12.0, is_final_table=True, payout_structure=p50_30_20)
    print(f"   6h 12bb w/ 50/30/20 payouts -> icm_factor={f_p}")
    adj = get_postflop_icm_adjustments(12.0, f_p, pot=5.5, bet_to_call=0.0, street_val=3, payout_structure=p50_30_20)
    print(f"   postflop ICM adj (flop, 12bb): call+={adj['call_thresh_delta']}, bluff+={adj['bluff_thresh_delta']}, agg_mult={adj['aggression_mult']}, protect_mult={adj['protection_size_mult']}")
    print(f"     active={adj['icm_active']} note: {adj.get('note','')}")
    ev = simulate_shortstack_icm_ev(6, 12, pot_bb=4.0, equity=0.46, action="shove", payout_structure=p50_30_20, players_behind=2)
    print(f"   icm-sim (shove 12bb vs 2 behind, 46% eq, 50/30/20): chipEV={ev['chip_ev_bb']}bb, ICM$est={ev['icm_dollar_impact_est']} (pool=1000u), payouts={ev['payouts_used']}")
    print(f"     {ev.get('note','')}")
    f_flat = get_icm_factor(9, 15, payout_structure=p40_25_20_10_5)
    print(f"   9h 15bb w/ flatter 40/25/20/10/5 -> icm_factor={f_flat} (less pressure than top-heavy)")

    print("\n=== ICM decision diffs (example hands at 6h 10bb final table) ===")
    for pos, hand in [("SB", "A9o"), ("SB", "KJo"), ("BB", "A5o"), ("BB", "Q9s"),
                      ("SB", "55"), ("BB", "JTs")]:
        act0, d0 = hu_decision(pos, hand, 10, icm_factor=0.0)
        act1, d1 = hu_decision(pos, hand, 10, icm_factor=f_est)
        diff = " *** CHANGED ***" if act0 != act1 else ""
        print(f"  {pos} {hand}: chipEV={act0}  icm~{f_est}={act1}{diff}")

    print("\n=== Using standard_payout_curve (for future full ICM) ===")
    print(f"  6-player payouts (approx): {[round(p*100,1) for p in standard_payout_curve(6)]}")
    print(f"  9-player payouts (approx): {[round(p*100,1) for p in standard_payout_curve(9)]}")


if __name__ == "__main__":
    main()

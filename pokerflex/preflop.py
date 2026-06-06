"""
PokerFlex A1 - Preflop Strategy Module (part of primary A1 brain)

Handles preflop regimes, open ranges, and delegates short stack decisions to the Nash solver (with ICM).
Used by default via GTOHeuristicAdvisor (new brain primary path).
Legacy shim preserved for compat (when forced via env ONLY for debug, never primary).
"""

from typing import Optional, Tuple
from .models import GameState, Decision, Action
from .ranges import get_open_range, is_in_open_range, load_preflop_ranges
from .config import CONFIG

# These can be tuned in config later
PUSH_FOLD_MAX_BB = 15
MID_MAX_BB = 25


def get_preflop_regime(bb: Optional[float]) -> str:
    """Route a preflop decision to the strategy regime for this stack depth."""
    if bb is None:
        return "unknown"
    if bb <= PUSH_FOLD_MAX_BB:
        return "push_fold"
    if bb <= MID_MAX_BB:
        return "mid"
    return "deep"


def get_preflop_decision(state: GameState) -> Decision:
    """
    Main preflop decision entry point for the new A1 brain.
    Uses reference ranges for deep stacks, delegates to Nash for short stacks.
    """
    if not state.hero_hand or len(state.hero_hand) != 2:
        return Decision(
            primary_action=Action(action_type="fold", reasoning="Invalid hand"),
            explanation="Need 2 hole cards.",
            confidence=1.0,
            hand_class="??"
        )

    # Get hand class from central parser (moved out of poker_engine)
    from .parsing import hand_class
    try:
        hand_class_str = hand_class(state.hero_hand[0], state.hero_hand[1])
    except Exception:
        hand_class_str = "??"

    bb = state.effective_stack
    pos = state.hero_position
    n_opp = state.num_opponents
    regime = get_preflop_regime(bb)

    # Enhanced: notes affect preflop opens/3bets more dynamically (postflop was primary before).
    # Pull from state (set by advisor) or manager. No effect / pure GTO when absent or default.
    # Uses preflop_* keys + fold_to_cbet / 3bet_freq for hero steal/3b/defend heuristics.
    effective_notes = getattr(state, "player_notes", None) or {}
    if not effective_notes:
        try:
            from .models import get_player_notes
            effective_notes = get_player_notes("villain") or {}
        except Exception:
            effective_notes = {}
    explo_pre = ""
    preflop_mult = 1.0
    if effective_notes and any(effective_notes.get(k) not in (None, 0.5, 1.0, 0.08, "") for k in ("preflop_open_tight", "preflop_3bet_freq", "3bet_freq", "fold_to_cbet")):
        t3b = float(effective_notes.get("preflop_3bet_freq", effective_notes.get("3bet_freq", 0.08)))
        tight = float(effective_notes.get("preflop_open_tight", 1.0))
        ftc = float(effective_notes.get("fold_to_cbet", effective_notes.get("fold_to_cbet_dry", 0.5)))
        if t3b <= 0.04:
            preflop_mult = 1.18
            explo_pre = " (🎯EXPLOIT vs nit: wider steal/3b bluffs)"
        elif t3b >= 0.16:
            preflop_mult = 0.88
            explo_pre = " (🎯EXPLOIT vs aggro: 3b for value only, fold more bluffs)"
        if tight > 1.15 and pos in ("CO", "BTN", "SB"):
            preflop_mult *= 1.12
            explo_pre += " ; steal wider (tight villain)"
        elif tight < 0.85:
            preflop_mult *= 0.92
            explo_pre += " ; defend tighter"
        if ftc > 0.7 and regime != "push_fold":
            explo_pre += " (folds post: realize more vs c/r)"

    # NEW: account for hero's own aggressive play style (user feedback)
    # If "hero" notes present (e.g. from GUI "I play aggressive"), loosen hero's ranges/sizing
    hero_notes = effective_notes.get("hero", {}) if isinstance(effective_notes, dict) else {}
    hero_mult = 1.0
    hero_anno = hero_notes.get("hero_anno", "") if hero_notes else ""
    if hero_notes:
        h_agg = float(hero_notes.get("aggression_factor", hero_notes.get("preflop_open_tight", 1.0)))
        if h_agg > 1.2 or hero_notes.get("preflop_open_tight", 1.0) < 0.9:
            hero_mult = 1.15
            if not hero_anno:
                hero_anno = " (hero is aggressive: wider opens/3b, bigger sizing)"
        if hero_notes.get("preflop_open_tight", 1.0) > 1.1:
            hero_mult *= 0.9
            hero_anno = " (hero is nitty: tighter than default)"
    if hero_anno and not hero_anno.startswith(" "):
        hero_anno = " " + hero_anno

    if effective_notes:
        # ensure state carries for downstream / format
        if not getattr(state, "player_notes", None):
            try:
                state.player_notes = dict(effective_notes)
            except Exception:
                pass

    if regime == "push_fold":
        from . import nash
        ante_bb = float(getattr(state, "ante_bb", 0.0) or 0.0)
        ante_tag = f" · BB-ante {ante_bb:g}bb" if ante_bb > 0 else " · no ante"

        # ICM support for tournament mode / final tables (short stacks only for now)
        # Respect explicit icm_factor from GameState (e.g. from run_brain --icm-factor or legacy_to override)
        # before falling back to auto from tournament_mode / CONFIG.icm_enabled.
        icm_factor = float(getattr(state, "icm_factor", 0.0) or 0.0)
        icm_note = ""
        if icm_factor <= 0.0:
            tmode = getattr(state, "tournament_mode", False) or getattr(CONFIG, "icm_enabled", False)
            if tmode:
                n_rem = getattr(state, "players_remaining", None)
                if n_rem is None or n_rem < 2:
                    n_rem = (n_opp or 1) + 1
                is_ft = (n_rem <= getattr(CONFIG, "icm_final_table_players", 9))
                try:
                    icm_factor = nash.get_icm_factor(n_rem, bb, is_final_table=is_ft)
                except Exception:
                    icm_factor = float(getattr(CONFIG, "icm_default_factor", 0.10))
        if icm_factor > 0:
            icm_note = f" · ICM factor~{icm_factor:.2f}"
            # future: could also inspect state.payout_structure / stack_sizes here for richer model

        if n_opp <= 2 and pos in ("SB", "BB"):
            act, det = nash.hu_decision(pos, hand_class_str, bb, ante_bb, icm_factor=icm_factor)
            action_type = "bet" if act == "SHOVE" else "fold"
            explanation = (
                f"Short stack ({bb}bb) — PUSH/FOLD regime. "
                f"Nash: {act} — {hand_class_str} is "
                f"{'in' if act == 'SHOVE' else 'outside'} the {bb}bb "
                f"{'SB jam' if pos == 'SB' else 'BB call'} range "
                f"({det.get('jam_pct', det.get('call_pct', 0)):.0f}% of hands). "
                f"(exact heads-up Nash · chip-EV{ante_tag}{icm_note}){explo_pre}"
            )
            m = {"nash_action": act, "regime": "push_fold"}
            if icm_factor > 0:
                m["icm_factor"] = icm_factor
            if effective_notes:
                m["explo_notes_used"] = 1.0
                m["explo_preflop_mult"] = round(preflop_mult, 3)
            sz = bb if act == "SHOVE" else None
            return Decision(
                primary_action=Action(action_type=action_type, size_bb=sz, reasoning="Nash push/fold"),
                explanation=explanation,
                confidence=0.95,
                hand_class=hand_class_str,
                metrics=m
            )
        else:
            act, det = nash.multiway_shove_decision(hand_class_str, bb, n_opp, ante_bb, icm_factor=icm_factor)
            action_type = "bet" if act == "SHOVE" else "fold"
            explanation = (
                f"Short stack ({bb}bb) — Open-shove: {act} — {hand_class_str} is "
                f"{'in' if act == 'SHOVE' else 'outside'} the {bb}bb open-jam range "
                f"({det.get('jam_pct', 0):.0f}% of hands, {n_opp} behind). "
                f"(multiway APPROXIMATION · indep. callers ~{det.get('caller_pct', 0):.0f}%{ante_tag}{icm_note}){explo_pre}"
            )
            m = {"nash_action": act, "regime": "push_fold"}
            if icm_factor > 0:
                m["icm_factor"] = icm_factor
            if effective_notes:
                m["explo_notes_used"] = 1.0
                m["explo_preflop_mult"] = round(preflop_mult, 3)
            sz = bb if act == "SHOVE" else None
            return Decision(
                primary_action=Action(action_type=action_type, size_bb=sz, reasoning="Nash multiway shove approx"),
                explanation=explanation,
                confidence=0.8,
                hand_class=hand_class_str,
                metrics=m
            )

    # Deep or mid stack - use reference open ranges
    # Now with dynamic notes adjustment for opens/3bets (wider steal vs nitty, etc)
    # FIX: much less nitty in multi-way limped pots (common tournament complaint)
    # When 3+ have entered before you (limpers/callers), especially in position + tournament (antes + dead money),
    # play significantly wider than unopened open-ranges. Don't fold marginal hands just because not "open range".
    # PT4 NL100+ derived (from pokertracker4 hands, *position-specific*):
    # Wins (clear good lines only): HJ/MP (AQo 3bet +6.5bb), BTN/CO (86s steal +2.5bb), CO/HJ (AJo iso vs limp +10.78bb).
    # Leaks (tighter/GTO): SB (44 call vs raise then fold = lost $), late vs 3bet + river overcall (JTs big loss).
    # New rule per your update: aggro (hero_mult, 3bet AQo/AJs, dead-money iso/steal) ONLY from winning positions (HJ/CO/BTN).
    # From SB/BB/early: base ranges + fold vs action (no extra looseness).
    WIN_POS = ("CO", "BTN", "HJ", "MP")
    bet_to_call = float(getattr(state, "bet_to_call", 0.0) or 0.0)
    pot = float(getattr(state, "pot", 1.5) or 1.5)
    facing_raise = bet_to_call > 0.5
    dead_money_spot = (pot > 3.0 or n_opp >= 2)
    in_winning_pos = pos in WIN_POS
    if pos in ("UTG", "MP", "CO", "BTN", "SB", "BB"):
        in_range = is_in_open_range(hand_class_str, pos)
        multiway_limped = (n_opp >= 3)
        if facing_raise:
            if hero_mult > 1.05 and in_winning_pos and hand_class_str in ("AQo", "AQs", "AJs", "KQs", "AKs", "AKo", "99", "TT", "JJ", "QQ"):
                # 3bet only the PT4 winning lines from winning positions.
                size = round(max(3.8 * hero_mult * max(bet_to_call, 2.0), 8.0), 1)
                action = Action(
                    action_type="bet",
                    size_bb=size,
                    reasoning=f"3bet {hand_class_str} (PT4 NL100 AQo 3bet win from {pos})"
                )
                explanation = (
                    f"{hand_class_str} — 3bet. PT4 NL100 (pokertracker4): AQo 3bet from late (HJ/CO) took +6.5bb pre vs small open. "
                    "Applied only in your winning positions (HJ/CO/BTN). Size ~" + f"{size}bb."
                )
            else:
                # Losing positions or non-premium vs raise: fold. Directly addresses SB 44 call leak + loose JTs vs 3bet.
                action = Action(action_type="fold", reasoning="fold vs raise (PT4: tighter GTO from SB/early or vs 3bet; wins were late pos aggressor)")
                explanation = (
                    f"{hand_class_str} — fold to raise. "
                    "PT4 analysis: SB defends (44) lost; calling 3bets then overcalling in late also lost big. "
                    "Aggro only from winning pos (CO/BTN/HJ) with the observed hands (AQo+). Base GTO otherwise."
                )
        elif in_range:
            size = 2.5 * (hero_mult if in_winning_pos else 1.0)
            action = Action(
                action_type="bet",
                size_bb=round(size, 1),
                reasoning=f"{hand_class_str} is in the {pos} open range (A1 reference)."
            )
            explanation = f"Standard open size ~{size:.1f}bb."
        elif (multiway_limped or dead_money_spot) and in_winning_pos:
            # Wide raise / iso / steal ONLY winning late positions (matches CO 86s, HJ/CO AJo/AQo lines).
            size = 3.5 * hero_mult
            action = Action(
                action_type="bet",
                size_bb=round(size, 1),
                reasoning=f"Raise/iso vs dead money ({pos} winning pos, {n_opp} in)"
            )
            explanation = (
                f"{hand_class_str} — raise (your PT4 winning line from {pos}). "
                "NL100 wins: 86s CO after folds, AJo iso vs limp, AQo 3bet. Dead money + late pos = +EV. "
                "SB/early excluded (your losing spots — play GTO ranges)."
            )
            tmode = getattr(state, "tournament_mode", False) or (getattr(state, "icm_factor", 0.0) or 0) > 0
            if tmode:
                explanation += " (Overlay beats ICM tighten.)"
        else:
            action = Action(
                action_type="fold",
                reasoning="fold (not winning pos or outside range)"
            )
            explanation = f"{hand_class_str} — fold (unopened or from non-winning position per PT4 results; tighter from SB/early)."
        if regime == "mid":
            explanation += f"\n(≈{bb}bb mid — deep ranges approx.)"
        if explo_pre:
            explanation += explo_pre
        if hero_anno:
            explanation += hero_anno
        m = {"in_open_range": float(in_range), "regime": regime, "multiway_limped": float(multiway_limped), "facing_raise": float(facing_raise), "pt4_derived": 1.0, "winning_pos": float(in_winning_pos)}
        if effective_notes:
            m["explo_notes_used"] = 1.0
            m["explo_preflop_mult"] = round(preflop_mult, 3)
        if hero_notes:
            m["hero_notes_used"] = 1.0
            m["hero_mult"] = round(hero_mult, 3)
        return Decision(
            primary_action=action,
            explanation=explanation,
            confidence=0.88 if (in_range or (in_winning_pos and (facing_raise or multiway_limped or dead_money_spot))) else 0.78,
            hand_class=hand_class_str,
            metrics=m
        )
    else:
        # BB or unknown
        explanation = "BB: no open range — you defend vs a raise. (Facing-action ranges not yet modeled.)"
        if regime == "mid":
            explanation += f"\n(≈{bb}bb mid-stack — using deep open ranges as an approximation.)"
        if explo_pre:
            explanation += explo_pre
        m = {"regime": regime}
        if effective_notes:
            m["explo_notes_used"] = 1.0
            m["explo_preflop_mult"] = round(preflop_mult, 3)
        return Decision(
            primary_action=Action(action_type="check", reasoning="Defend in BB or unknown position"),
            explanation=explanation,
            confidence=0.5,
            hand_class=hand_class_str,
            metrics=m
        )

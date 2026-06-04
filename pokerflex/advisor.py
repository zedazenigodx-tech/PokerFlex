"""
PokerFlex A1 - Main GTO Heuristic Advisor (PRIMARY / DEFAULT BRAIN)

This is now the central/recommended brain for real-time advice.
- Used by default via poker_engine.get_advice (USE_NEW_BRAIN=True module-level default; unambiguous everywhere; legacy debug only).
- Delegates to preflop.py (ranges + nash ICM) + postflop.py (texture + range/nut adv heuristics).
- format_a1_advice produces clean rich text compatible with GUI (main.py) and console (no legacy disclaimers in normal A1 use).
- Supports explo notes, ICM/tournament, board texture etc.

Legacy fallback path preserved exactly in poker_engine for compat/debug (env/CONFIG force) ONLY. New A1 is the UNAMBIGUOUS default everywhere (python -m pokerflex, GUI, all entry points). All output in default path is rich A1.
"""

from typing import Optional, Dict, Any, List
from .models import GameState, Decision, Action, get_player_notes
from .config import CONFIG
from .preflop import get_preflop_decision
from .postflop import get_postflop_decision
from .board_texture import analyze_board
from .equity import equity_vs_random


class GTOHeuristicAdvisor:
    """
    The main entry point for the A1 brain (now primary/default).

    Orchestrates:
    - Board texture analysis (board_texture)
    - Preflop: ranges + nash push/fold + ICM
    - Postflop: range estimation, equity vs range, blocker/range/nut adv, sizing, explo adjustments
    - Rich Decision for text (format_a1_advice) + future structured use (overlay/voice)
    """

    def __init__(self):
        self.config = CONFIG
        # Preload ranges (from preflop module now)
        from .preflop import load_preflop_ranges as _load
        _load()

    def advise(self, state: GameState, player_notes: Optional[Dict[str, Any]] = None, use_exploits: Optional[bool] = None, action_history: Optional[List[Dict[str, Any]]] = None) -> Decision:
        """
        Main decision function.
        Phase 1/2: Basic preflop using new ranges + texture awareness for postflop stub.
        Supports optional player_notes for exploitative adjustments (GTO vs Explo toggleable).
        If player_notes provided or CONFIG.exploitative_mode or use_exploits=True, postflop will adjust villain ranges.
        action_history: if provided, merged/appended to state.action_history (full history passed through for
                        multi-street decisions, blocker awareness, capped ranges on check-backs etc).
        """
        hand_classes = self._get_hand_classes(state.hero_hand)
        hand_class = hand_classes[0] if hand_classes else "??"
        texture = state.board.texture() if state.board.cards else None

        # Determine effective notes: passed > state > manager lookup
        effective_notes = player_notes or getattr(state, "player_notes", None)
        if not effective_notes and (use_exploits or CONFIG.exploitative_mode):
            effective_notes = get_player_notes("villain")

        # Ensure full action_history is honored / merged if passed explicitly to advise (in addition to state)
        if action_history:
            try:
                for ev in action_history:
                    state.append_action(ev)
            except Exception:
                # fallback direct
                if not isinstance(getattr(state, "action_history", None), list):
                    state.action_history = []
                for ev in action_history:
                    if isinstance(ev, dict):
                        state.action_history.append(ev)  # will be normalized on use / post
                    else:
                        state.action_history.append(ev)

        if state.street.value == 0:  # PREFLOP
            # (preflop notes support limited; pass-through for future 3bet etc adjustments)
            if effective_notes and not getattr(state, "player_notes", None):
                state.player_notes = effective_notes
            return get_preflop_decision(state)

        else:
            # Postflop - delegate with notes for explo range adjuster
            return get_postflop_decision(state, player_notes=effective_notes)

    def _get_hand_classes(self, hero_hand: list) -> list:
        """Convert hero cards (as strings like 'Ah', 'Ks') to hand class (delegates to central parser)."""
        if not hero_hand or len(hero_hand) != 2:
            return ["??"]
        try:
            from .parsing import hand_class
            return [hand_class(hero_hand[0], hero_hand[1])]
        except Exception:
            return ["??"]


# Global instance for easy access
_ADVISOR: Optional[GTOHeuristicAdvisor] = None


def get_advisor() -> GTOHeuristicAdvisor:
    global _ADVISOR
    if _ADVISOR is None:
        _ADVISOR = GTOHeuristicAdvisor()
    return _ADVISOR


def format_a1_advice(state: "GameState", decision: "Decision") -> str:
    """
    Produce rich, human-readable text output from A1 Decision + GameState.
    This is the default output for get_advice() when USE_NEW_BRAIN=True (everywhere normal).
    Matches familiar emoji/header style while adding A1 details (texture, SPR, range/nut adv, explo, ICM, confidence).
    Clean, consistent: no duplicate action lines, proper ✅/❌ marks, utf8-safe. No disclaimers.
    """
    from .models import Street  # local to avoid any issues
    from .parsing import parse_cards
    from .equity import equity_vs_random

    hand_str = " ".join(state.hero_hand) if state.hero_hand else "??"
    cls = getattr(decision, "hand_class", "") or "??"
    n_opp = getattr(state, "num_opponents", 1)
    bb = getattr(state, "effective_stack", 100)
    street = "Preflop" if state.street == Street.PREFLOP else {3: "Flop", 4: "Turn", 5: "River"}.get(state.street.value, "Postflop")

    action = decision.primary_action
    act_type_raw = (action.action_type or "check").upper()
    size_info = ""
    if action.size_pot is not None:
        size_info = f" ({action.size_pot*100:.0f}% pot)"
    elif action.size_bb is not None:
        size_info = f" ({action.size_bb:.1f}bb)"

    # Nicer action verbs to match legacy style + short stack shove
    act_type = act_type_raw
    if state.street == Street.PREFLOP:
        if act_type_raw == "BET":
            if bb <= 15:
                act_type = "SHOVE" if action.size_bb and action.size_bb >= bb * 0.8 else "RAISE"
            else:
                act_type = "OPEN / RAISE"
        elif act_type_raw in ("CHECK", "CALL"):
            act_type = "DEFEND / CALL" if state.hero_position == "BB" else act_type_raw
        # FOLD stays FOLD
    else:
        if act_type_raw == "BET":
            act_type = "BET / C-BET"
        elif act_type_raw == "CALL":
            act_type = "CALL"
        # leave FOLD / CHECK / RAISE

    # Choose mark to match legacy convention (✅ good/actionable, ❌ fold, 💡 neutral/check)
    positive = {"OPEN", "RAISE", "SHOVE", "BET", "BET / C-BET", "CALL", "DEFEND / CALL"}
    if act_type in positive or any(p in act_type for p in ("OPEN", "RAISE", "BET", "SHOVE", "CALL", "DEFEND")):
        mark = "✅"
    elif "FOLD" in act_type:
        mark = "❌"
    else:
        mark = "💡"

    header = f"🎯 {street}  |  {hand_str} ({cls})  |  {n_opp} opp  |  {bb:g}bb  [A1 Brain]"
    lines = [header]

    # Primary line (clean, no dups from inner expl)
    primary = f"{mark} {act_type}{size_info} — {action.reasoning or ''}".strip()
    if primary.endswith("—"):
        primary = primary[:-1].strip()
    lines.append(primary)

    # Explanation (pure details from brain; preflop cleaned of leading marks)
    if decision.explanation:
        for line in decision.explanation.splitlines():
            lines.append("   " + line if line.strip() else "")

    # Texture / extras (legacy-like 🃏)
    if getattr(decision, "texture_summary", None):
        lines.append(f"🃏 Board texture: {decision.texture_summary}")

    # Metrics (always try to surface equity for parity with legacy usefulness)
    m = getattr(decision, "metrics", {}) or {}
    eq = m.get("equity_vs_random") or m.get("equity")
    if eq is None and state.hero_hand and len(state.hero_hand) == 2:
        # Fallback compute for preflop / cases without (light iters for speed)
        try:
            h = parse_cards("".join(state.hero_hand))
            b = parse_cards("".join(state.board.cards)) if getattr(state.board, "cards", None) else []
            eq = equity_vs_random(h, b, n_opp, iters=800)  # fast
        except Exception:
            eq = None
    if eq is not None:
        try:
            lines.append(f"📊 Equity vs random: {float(eq)*100:.1f}%")
        except Exception:
            pass

    if m:
        if "spr" in m:
            try:
                lines.append(f"   SPR: {float(m['spr']):.2f}")
            except Exception:
                pass
        if "texture_dynamic" in m:
            try:
                lines.append(f"   Dynamic: {float(m['texture_dynamic']):.2f}")
            except Exception:
                pass
        if "in_open_range" in m:
            lines.append(f"   In open range: {bool(m['in_open_range'])}")
        if "nash_action" in m:
            lines.append(f"   Nash: {m['nash_action']}")
        if "regime" in m:
            lines.append(f"   Regime: {m['regime']}")
        if m.get("explo_notes_used"):
            lines.append(f"   🎯 EXPLOIT: notes active (fold_to_cbet~{m.get('explo_fold_to_cbet', '?')}, bet_mult={m.get('explo_bet_freq_mult', '?')})")
        if "icm_factor" in m and float(m.get("icm_factor", 0)) > 0:
            try:
                icmf = float(m["icm_factor"])
                tag = " (postflop ICM-adjusted)" if state.street.value != 0 and m.get("icm_adjusted") else ""
                lines.append(f"   ICM factor: {icmf:.2f} (tournament mode / adjusted Nash){tag}")
            except Exception:
                pass
        elif getattr(state, "tournament_mode", False) and getattr(state, "effective_stack", 100) <= 20:
            # surface even if not in metrics (e.g. some paths)
            try:
                prem = getattr(state, "players_remaining", None) or "?"
                lines.append(f"   ICM context: tournament short-stack (players_rem~{prem}; use explicit icm/payouts for factor)")
            except Exception:
                pass

        # Expose short history line in rich A1 output when action_history present (multi-street awareness)
        h_ev = m.get("history_events") or 0
        if h_ev and float(h_ev) > 0:
            hagg = m.get("history_agg", 0)
            tag = ""
            if m.get("history_capped"):
                tag = " capped"
            elif m.get("history_donk"):
                tag = " donk"
            lines.append(f"   History: {int(h_ev)} events (agg~{hagg}{tag})")
        else:
            ah = getattr(state, "action_history", None)
            if ah:
                try:
                    ah_list = state.get_action_history_dicts() if hasattr(state, "get_action_history_dicts") else ah
                    short = " ".join(
                        f"{str( (e.get('street') if isinstance(e,dict) else getattr(e,'street','?')) )[:1]}:{str( (e.get('actor') if isinstance(e,dict) else getattr(e,'actor','v')) )[0]}:{ (e.get('action') if isinstance(e,dict) else getattr(e,'action','?')) }"
                        for e in (ah_list[-3:] if isinstance(ah_list, (list,tuple)) else [])
                    )
                    if short.strip():
                        lines.append(f"   History: {short}")
                except Exception:
                    pass

    # Confidence
    if decision.confidence:
        lines.append(f"   (confidence: {decision.confidence*100:.0f}%)")

    # Clean end — rich A1 (no legacy tags/disclaimers ever in normal new brain path); details above.
    lines.append("")

    return "\n".join(lines)

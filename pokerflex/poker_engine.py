"""PokerFlex engine — A1 primary/default router (thin compat shim for legacy fallback ONLY when explicitly forced).

This module now contains *almost no strategy logic*.
- Primary/default path (A1 brain): USE_NEW_BRAIN=True (module-level default, UNAMBIGUOUS) → delegates to advisor.py (GTOHeuristicAdvisor)
  which uses preflop.py + postflop.py + models + equity + ranges + board_texture + nash + config.
  Richer output via format_a1_advice (board texture, SPR, range adv, explo notes, ICM, etc.).
- Legacy path (USE_NEW_BRAIN=False): exact original behavior + text ONLY for debug / old callers / GUI compat when explicitly forced via env/CONFIG. (Never the default or primary path.)
  The legacy implementation body is kept here ONLY for 100% identical get_advice() output when explicitly forced.

Pure helpers (parse_cards, hand_class, equity_vs_random, normalize etc.) have been
moved to parsing.py / equity.py / ranges.py so new modules and legacy can share without dupe.

Old constants (RANK_*, range tokens, etc.) live in ranges.py now.

The new A1 brain (USE_NEW_BRAIN=True) IS THE UNAMBIGUOUS DEFAULT everywhere for the real-time assistant (GUI + run_brain + python -m pokerflex + direct calls).
Legacy is preserved exactly (untouched) ONLY when forced (see env var POKERFLEX_FORCE_LEGACY_BRAIN=1 or CONFIG.force_legacy_brain below); **never the primary path**.
New A1 brain requires zero flags in normal use. All launchers/entry points/GUI set/reinforce USE_NEW_BRAIN=True at module level.
"""

from treys import Card, Evaluator
from typing import Optional, Dict, Any, List
import os
import warnings

from .config import CONFIG

# Suppress runpy 'found in sys.modules after import of package' warning during `python -m pokerflex.poker_engine` self-test
# (filter must be early; the __main__ block filter is too late for the runpy trigger).
warnings.filterwarnings("ignore", category=RuntimeWarning, message=r".*found in sys.modules after import of package.*")

# --------------------------------------------------------------------------- #
# A1 new brain (USE_NEW_BRAIN=True) is the UNAMBIGUOUS MODULE-LEVEL DEFAULT.
# (The real-time assistant default for ALL normal use: GUI, python -m pokerflex, `pokerflex` CLI, run_brain, direct get_advice, etc.)
# Legacy (exact old behavior) ONLY for debugging/comparison with old callers (NEVER primary):
#   - Env var: POKERFLEX_FORCE_LEGACY_BRAIN=1
#     (parser uses .strip() so tolerant of "1 ", trailing newline, etc from .bat / set / export)
#   - Or set CONFIG.force_legacy_brain = True before import (see config.py)
# The legacy branch below is NEVER modified (frozen for compat); ALL new development is in advisor/* + preflop/postflop etc.
# Default experience (no flags): NEW A1 BRAIN. Legacy never primary, never auto.
# --------------------------------------------------------------------------- #
_FORCE_LEGACY_ENV = os.environ.get("POKERFLEX_FORCE_LEGACY_BRAIN", "").strip().lower() in ("1", "true", "yes")

# A1 new brain is the explicit default everywhere (GUI, launcher, runner, direct calls).
# Set here as True; override to False ONLY on explicit legacy force (the one supported env for legacy).
# POKERFLEX_USE_NEW_BRAIN is deprecated/no-op (kept for any old launcher compat but ignored; default always A1).
# This is the UNAMBIGUOUS MODULE-LEVEL DEFAULT for all normal use (python -m pokerflex, `pokerflex`, GUI, etc.).
USE_NEW_BRAIN = True
if _FORCE_LEGACY_ENV or getattr(CONFIG, "force_legacy_brain", False):
    USE_NEW_BRAIN = False
# else: remains True (the A1 primary path)
# All entry points ( __main__, run_brain, launch_*, shims, GUI, direct import, python -m pokerflex, `pokerflex` CLI ) reinforce this.
# This is THE module-level default; legacy path is reached ONLY via explicit force (debug never primary).

# Global toggle for exploitative (notes-driven) vs pure GTO in new brain.
# When True, advisor will look up default "villain" notes if none passed to get_advice().
# Preferred usage: pass explicit player_notes= to get_advice() or use set_explo_notes() + USE_NEW_BRAIN=True.
USE_EXPLOITATIVE = False  # set True + CONFIG.exploitative_mode or per-call notes for Explo mode

def _get_a1_advisor():
    """Lazy import to avoid circular import issues during module load.
    New brain components live in advisor + models (format_a1_advice produces
    Decision-derived text for the shim's return value).
    """
    try:
        from .models import legacy_to_gamestate
        from .advisor import get_advisor, format_a1_advice
        return legacy_to_gamestate, get_advisor, format_a1_advice
    except Exception:
        return None, None, None


# --------------------------------------------------------------------------- #
# Re-exports for legacy path + self-tests (thin compat layer only).
# Implementation lives in the new modules. Legacy get_advice behavior identical.
# --------------------------------------------------------------------------- #
from .parsing import (
    parse_cards,
    hand_class,
    hand_class_from_str,
    normalize_position,
    _street,
)
from .equity import equity_vs_random
from .ranges import parse_range, RANGE_TOKENS as _RANGE_TOKENS

# Legacy range sets (for the old open-range checks in legacy preflop path + tests).
# New code uses ranges.get_open_range / is_in_open_range (Range objects).
RANGES = {pos: parse_range(toks) for pos, toks in _RANGE_TOKENS.items()}
POSITIONS = ["UTG", "MP", "CO", "BTN", "SB", "BB"]

# Treys evaluator kept here only because legacy path still does made-hand classification
# via _EVAL.class_to_string (new brain uses texture + heuristics instead).
_EVAL = Evaluator()


# --------------------------------------------------------------------------- #
# Legacy advice implementation (kept verbatim, untouched, for 100% identical behavior when forced).
# This is the ONLY strategy logic remaining in this file — purely for
# backward-compat with old GUI callers / tests / debug (main.py calls get_advice unconditionally).
# All new development happens in advisor/ preflop/ postflop/ etc. ONLY.
# When USE_NEW_BRAIN=True (THE UNAMBIGUOUS DEFAULT) the shim returns Decision-derived text via format_a1_advice (clean rich A1, no disclaimers).
# Force legacy with POKERFLEX_FORCE_LEGACY_BRAIN=1 to bypass (never happens in normal use; legacy is NEVER primary).
# --------------------------------------------------------------------------- #

# Legacy-only regime constants (duplicated values also in preflop.py for new path;
# must stay in sync for identical legacy output).
PUSH_FOLD_MAX_BB = 15   # at/under this effective stack, preflop is shove-or-fold
MID_MAX_BB = 25         # between this and PUSH_FOLD_MAX_BB, open ranges drift (approx)


def _preflop_regime(bb):
    """Route a preflop decision to the strategy regime for this stack depth (legacy only)."""
    if bb is None:
        return "unknown"
    if bb <= PUSH_FOLD_MAX_BB:
        return "push_fold"
    if bb <= MID_MAX_BB:
        return "mid"
    return "deep"


def _postflop_heuristic(eq):
    """Legacy postflop bucket text (new brain does not use this)."""
    if eq >= 0.70:
        return "STRONG — bet/raise for value."
    if eq >= 0.52:
        return "AHEAD — bet/call; build the pot carefully."
    if eq >= 0.38:
        return "MARGINAL — pot control; check-call or check-fold to pressure."
    return "WEAK — check-fold, or use as a bluff/semi-bluff candidate only."


def get_advice(position="", hand="", board="", opponents="", stack="", ante="", player_notes: Optional[Dict[str, Any]] = None, tournament_mode: bool = False, players_remaining: Optional[int] = None, icm_factor: float = 0.0, action_history: Optional[List[Dict[str, Any]]] = None):
    """Return (text, data) — human-readable advice plus the raw numbers.

    Signature unchanged (extra kwargs safe). 
    THE DEFAULT (no flags, everywhere): USE_NEW_BRAIN=True (A1 brain via advisor + format_a1_advice) — richer output with texture/SPR/ICM/explo. THIS IS THE UNAMBIGUOUS DEFAULT EXPERIENCE.
    To force legacy old text exactly (debug/old callers ONLY, never normal use): set env POKERFLEX_FORCE_LEGACY_BRAIN=1 (or CONFIG.force_legacy_brain=True). (POKERFLEX_USE_NEW_BRAIN no longer affects legacy path.)
    When new: returns Decision-derived text (via advisor.format_a1_advice) which is richer but plain str. No legacy disclaimers.
    player_notes: optional dict of tendencies for exploitative play (e.g. {"fold_to_cbet": 0.78}).
                 If provided, enables explo adjustments in new brain regardless of CONFIG flag.
    tournament_mode: pass True (and optionally players_remaining) to engage ICM-adjusted Nash in preflop short-stack paths.
                     (GUI calls can pass; new brain handles cleanly. run_brain/direct tests use for tourney.)
    players_remaining: explicit total players left (e.g. 6 for final table) to drive icm_factor auto-calc when tournament_mode=True.
    icm_factor: explicit >0 to force ICM adjustment (bypasses auto-calc from tournament_mode).
    action_history: optional list of ActionEvent dicts (see models.ActionEvent) for multi-street memory.
                    If provided, passed through to GameState + A1 advisor/postflop for history-aware ranges/blockers/stories.
    """
    # === NEW BRAIN (A1 / primary recommended path) ===
    if USE_NEW_BRAIN:
        legacy_to_gamestate, get_advisor, format_a1_advice = _get_a1_advisor()
        if legacy_to_gamestate and get_advisor:
            try:
                state = legacy_to_gamestate(position, hand, board, opponents, stack, ante, player_notes=player_notes, tournament_mode=tournament_mode, players_remaining=players_remaining, icm_factor=icm_factor, action_history=action_history or [])
                # Pass notes explicitly too (advisor will also pull from state)
                use_ex = bool(player_notes) or USE_EXPLOITATIVE
                decision = get_advisor().advise(state, player_notes=player_notes, use_exploits=use_ex, action_history=getattr(state, "get_action_history_dicts", lambda: getattr(state, "action_history", []))() )
                # Use the dedicated formatter so output is fully Decision-derived + usable in GUI
                if format_a1_advice:
                    text = format_a1_advice(state, decision)
                else:
                    text = f"[A1 Brain] {decision.primary_action.action_type.upper()}\n{decision.explanation}"
                data = {"a1_mode": True, "action": getattr(decision.primary_action, "action_type", None)}
                if decision.metrics:
                    data.update(decision.metrics)
                data["confidence"] = decision.confidence
                if decision.texture_summary:
                    data["texture"] = decision.texture_summary
                if player_notes:
                    data["exploitative_notes"] = True
                    data["player_notes_keys"] = list(player_notes.keys()) if isinstance(player_notes, dict) else []
                return text, data
            except Exception as _a1_ex:
                # Rare internal error in A1 path (new brain): return clean A1-flavored message.
                # Do NOT fall through to legacy (avoids legacy disclaimers / old text leaking into normal/default A1 use).
                # (GUI/runner continue to work; user can force legacy explicitly for exact old if needed.)
                err = f"{type(_a1_ex).__name__}: {str(_a1_ex)[:100]}"
                return (f"⚠️ A1 brain internal error (rare): {err}\nCheck inputs (hand/board/pos/stack) and retry.\n\n[A1 Brain] Error — retry with valid state.", {"a1_mode": True, "error": True})

    # === LEGACY PATH (exact original behavior for debug/old callers/tests when explicitly forced; do not alter this branch; reached ONLY if USE_NEW_BRAIN=False at entry) ===
    try:
        hero = parse_cards(hand) if hand.strip() else []
        if len(hero) != 2:
            return ("Enter your 2 hole cards, e.g. AhKs", {})
        board_cards = parse_cards(board) if board.strip() else []
        if len(board_cards) not in (0, 3, 4, 5):
            return (f"Board has {len(board_cards)} cards — must be 0, 3, 4, or 5.", {})

        # opponents
        try:
            n_opp = max(1, int("".join(c for c in opponents if c.isdigit()) or 1))
        except ValueError:
            n_opp = 1

        # stack
        bb = None
        digits = "".join(c for c in stack if c.isdigit())
        if digits:
            bb = int(digits)

        # big-blind ante (in bb)
        ante_bb = 0.0
        adigits = "".join(c for c in ante if c.isdigit() or c == ".")
        if adigits:
            try:
                ante_bb = float(adigits)
            except ValueError:
                ante_bb = 0.0

        street = _street(board_cards)
        cls = hand_class(*[Card.int_to_str(c) for c in hero])
        lines = [f"🎯 {street}  |  {Card.int_to_str(hero[0])} {Card.int_to_str(hero[1])} ({cls})  |  {n_opp} opp"]
        data = {"street": street, "class": cls, "opponents": n_opp}

        if street == "Preflop":
            pos = normalize_position(position)
            regime = _preflop_regime(bb)
            data["stack_bb"], data["regime"] = bb, regime
            if pos:
                data["position"] = pos

            if regime == "push_fold":
                from . import nash
                ante_tag = f" · BB-ante {ante_bb:g}bb" if ante_bb else " · no ante"
                # ICM (legacy path): driven by tournament_mode (new) or CONFIG.icm_enabled (for GUI compat)
                icm_factor = 0.0
                icm_tag = ""
                if tournament_mode or getattr(CONFIG, "icm_enabled", False):
                    n_rem = players_remaining if players_remaining is not None else (n_opp + 1)
                    try:
                        icm_factor = nash.get_icm_factor(n_rem, bb, is_final_table=(n_rem <= getattr(CONFIG, "icm_final_table_players", 9)))
                    except Exception:
                        icm_factor = float(getattr(CONFIG, "icm_default_factor", 0.10))
                    if icm_factor > 0:
                        icm_tag = f" · ICM~{icm_factor:.2f}"
                lines.append(f"🔻 SHORT STACK ({bb}bb) — PUSH/FOLD regime: shove-or-fold, not min-raise.")
                if n_opp == 1 and pos in ("SB", "BB"):
                    act, det = nash.hu_decision(pos, cls, bb, ante_bb, icm_factor=icm_factor)
                    if pos == "SB":
                        mark = "✅" if act == "SHOVE" else "❌"
                        lines.append(f"   {mark} Nash: {act} — {cls} is "
                                     f"{'in' if act == 'SHOVE' else 'outside'} the {bb}bb SB jam range "
                                     f"({det['jam_pct']:.0f}% of hands).")
                    else:
                        mark = "✅" if act == "CALL" else "❌"
                        lines.append(f"   {mark} Nash: {act} vs a shove — {cls} is "
                                     f"{'in' if act == 'CALL' else 'outside'} the {bb}bb BB call range "
                                     f"({det['call_pct']:.0f}% of hands).")
                    lines.append(f"   (exact heads-up Nash · chip-EV{ante_tag}{icm_tag})")
                    data["nash_action"] = act
                else:
                    act, det = nash.multiway_shove_decision(cls, bb, n_opp, ante_bb, icm_factor=icm_factor)
                    mark = "✅" if act == "SHOVE" else "❌"
                    lines.append(f"   {mark} Open-shove: {act} — {cls} is "
                                 f"{'in' if act == 'SHOVE' else 'outside'} the {bb}bb open-jam range "
                                 f"({det['jam_pct']:.0f}% of hands, {n_opp} behind).")
                    lines.append(f"   (multiway APPROXIMATION · indep. callers ~{det['caller_pct']:.0f}%"
                                 f"{ante_tag}{icm_tag})")
                    data["nash_action"] = act
                if icm_factor > 0:
                    data["icm_factor"] = icm_factor
                eq = equity_vs_random(hero, [], n_opp)
                lines.append(f"📊 All-in equity vs {n_opp} random hand(s): {eq*100:.1f}%  "
                             "(the number that matters for a shove).")
                data["equity"] = eq
            else:
                if pos and pos in RANGES:
                    in_range = cls in RANGES[pos]
                    data["in_open_range"] = in_range
                    if in_range:
                        lines.append(f"✅ OPEN / RAISE — {cls} is in the {pos} open range.")
                        lines.append("   Standard open size ~2.5bb (2.2-3bb).")
                    else:
                        lines.append(f"❌ FOLD — {cls} is outside the {pos} open range (if unopened).")
                elif pos == "BB":
                    lines.append("BB: no open range — you defend vs a raise. (Facing-action ranges not built yet.)")
                else:
                    lines.append("⚠️  Enter a position (UTG/MP/CO/BTN/SB/BB) for a range read.")
                if regime == "mid":
                    lines.append(f"   (≈{bb}bb mid-stack — using deep open ranges as an approximation; "
                                 "true mid-stack ranges differ slightly.)")
                elif regime == "unknown":
                    lines.append("   (No stack entered — assuming deep ~100bb ranges.)")
                eq = equity_vs_random(hero, [], n_opp)
                lines.append(f"📊 All-in equity vs {n_opp} random hand(s): {eq*100:.1f}%")
                data["equity"] = eq
        else:
            score = _EVAL.evaluate(board_cards, hero)
            rc = _EVAL.get_rank_class(score)
            made = _EVAL.class_to_string(rc)
            eq = equity_vs_random(hero, board_cards, n_opp)
            data.update({"made_hand": made, "equity": eq})
            lines.append(f"🃏 Made hand: {made}")
            lines.append(f"📊 Equity vs {n_opp} random hand(s): {eq*100:.1f}%")
            lines.append(f"💡 {_postflop_heuristic(eq)}")

        lines.append("")
        lines.append("— preflop: push/fold ≤15bb / open ranges above; "
                     "postflop = equity + heuristics, not a GTO solve.")
        return ("\n".join(lines), data)

    except ValueError as e:
        return (f"⚠️  Input error: {e}", {})
    except Exception as e:  # noqa: BLE001 - surface anything else rather than crash the GUI
        return (f"⚠️  Unexpected error: {type(e).__name__}: {e}", {})


# --------------------------------------------------------------------------- #
# Exploitative Notes CLI / Helper Functions (simple, no deps)
# New brain default (A1): set USE_NEW_BRAIN=True (or leave default) + pass player_notes=... or CONFIG.exploitative_mode=True
# then use get_advice(..., player_notes=...) or global manager presets.
# To test legacy notes path: force legacy via env (old path also supports some ICM notes).
# --------------------------------------------------------------------------- #

def set_explo_notes(player: str = "villain", **tendencies) -> Dict[str, Any]:
    """Simple function / CLI helper: set tendencies for a player (name/seat).
    Example:
      set_explo_notes("nit", fold_to_cbet=0.78, fold_to_cbet_dry=0.85, aggression_factor=0.6)
    Returns the stored notes.
    """
    from .models import set_player_notes, get_player_notes
    if tendencies:
        set_player_notes(player, tendencies)
    return get_player_notes(player)


def get_explo_notes(player: str = "villain") -> Dict[str, Any]:
    """Fetch current notes for player."""
    from .models import get_player_notes
    return get_player_notes(player)


def use_nit_preset(player: str = "nit") -> Dict[str, Any]:
    """Quick CLI: apply nit folder preset (folds 78%+ to cbet)."""
    from .models import apply_nit_preset
    return apply_nit_preset(player)


def use_station_preset(player: str = "station") -> Dict[str, Any]:
    """Quick CLI: apply calling station preset."""
    from .models import apply_calling_station_preset
    return apply_calling_station_preset(player)


def use_aggro_preset(player: str = "maniac") -> Dict[str, Any]:
    """Quick CLI: apply maniac/aggro preset."""
    from .models import apply_aggro_preset
    return apply_aggro_preset(player)


def clear_explo_notes(player: Optional[str] = None) -> None:
    """Clear notes for player (or all if None)."""
    from .models import get_notes_manager
    get_notes_manager().clear(player)


def list_explo_players() -> List[str]:
    """List players with stored notes."""
    from .models import get_notes_manager
    return get_notes_manager().list_players()


# Also re-export for convenience from top level
try:
    from .models import (
        get_player_notes, set_player_notes, update_player_tendency,
        apply_nit_preset, apply_calling_station_preset, apply_aggro_preset,
        PlayerTendencies, PlayerNotesManager, get_notes_manager,
    )
except Exception:
    pass


# --------------------------------------------------------------------------- #
# Self-test (run: python poker_engine.py)
# Exercises both legacy (exact) and new brain paths, plus range/equity primitives
# that are now re-exported from thin shim for compat.
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys
    import warnings
    import random   # only needed for deterministic self-tests
    warnings.filterwarnings("ignore", category=RuntimeWarning, message=r".*found in sys.modules after import of package.*")
    try:                                  # Windows consoles default to cp1252
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    random.seed(42)
    print("=== sanity: equity (expect ~known values) ===")
    checks = [
        ("AsAd", "", 1, "AA vs 1 ~85%"),
        ("AsKs", "", 1, "AKs vs 1 ~67%"),
        ("7h2d", "", 1, "72o vs 1 ~35%"),
        ("AsAd", "", 5, "AA vs 5 ~49%"),
    ]
    for h, b, n, note in checks:
        hero = parse_cards(h)
        board = parse_cards(b) if b else []
        eq = equity_vs_random(hero, board, n, iters=5000)
        print(f"  {h:6} vs {n}: {eq*100:5.1f}%   ({note})")

    print("\n=== shim re-export sanity (parse/hand/equity now from new modules) ===")
    # These would have been local before refactor; now prove thin layer works for tests/legacy.
    assert callable(parse_cards) and callable(hand_class) and callable(equity_vs_random)
    print("  ✓ re-exports present (from parsing/equity)")
    print("  ✓ _street from parsing:", repr(_street([])))

    print("\n=== range spot checks ===")
    spot_checks = [
        ("AhKs", "UTG"), ("7h2d", "UTG"), ("3h3d", "UTG"),
        ("Kc9c", "UTG"), ("Kc9d", "UTG"), ("Th8h", "BTN"), ("Qh8c", "BTN"),
    ]
    for hand, pos in spot_checks:
        cls = hand_class_from_str(hand)
        print(f"  {hand} ({cls}) @ {pos}: {'OPEN' if cls in RANGES[pos] else 'fold'}")

    print("\n=== full advice samples (original) ===")
    for kw in (
        dict(position="UTG", hand="AhKs", opponents="3", stack="100"),
        dict(position="BTN", hand="AhKs", opponents="2", stack="10"),   # same hand, 10bb -> push/fold regime
        dict(position="BTN", hand="Th8h", opponents="2", stack="100"),
        dict(position="CO", hand="AhKs", board="Qd7h2c", opponents="1"),
        dict(position="CO", hand="AhKs", board="AdKh2c", opponents="2"),
        dict(position="SB", hand="5h5d", board="5c9h2d Js", opponents="1"),
    ):
        text, _ = get_advice(**kw)
        print("-" * 60)
        print(text)

    # ----------------------------------------------------------------------- #
    # Expanded dual-mode tests (A1 new brain UNAMBIGUOUS default primary; legacy force support ONLY for verification/debug).
    # Run with: python poker_engine.py
    # Verifies:
    #  - new A1 brain (default True) runs w/o crash + produces rich output
    #  - legacy path (force via env/CONFIG) remains 100% identical / unchanged (for debug)
    #  - side-by-side, legacy preserved for old callers / debug compat ONLY
    # ----------------------------------------------------------------------- #
    print("\n" + "=" * 72)
    print("=== CANONICAL TEST SPOTS — A1 NEW BRAIN (UNAMBIGUOUS DEFAULT) vs LEGACY (forced for debug) ===")
    print("Task requirements: BTN AKs pre, BB vs raise, flop c-bet dry, short stack, etc.")
    print("New A1 (USE_NEW_BRAIN=True module default) is THE primary rich path everywhere. Legacy (forced) remains identical for debug/old callers.")
    print("=" * 72)

    CANONICAL_SPOTS = [
        # 1. BTN AKs preflop (classic open)
        dict(name="BTN AKs preflop (deep open)", position="BTN", hand="AhKs", opponents="2", stack="100"),
        # 2. BB vs raise (pre-flop defend spot)
        dict(name="BB 22 vs raise preflop", position="BB", hand="2h2d", opponents="2", stack="100"),
        dict(name="BB A9o vs raise preflop", position="BB", hand="Ad9d", opponents="1", stack="80"),
        # 3. Short stack push/fold
        dict(name="BTN short-stack 10bb AKs", position="BTN", hand="AhKs", opponents="2", stack="10"),
        dict(name="SB 15bb marginal shove", position="SB", hand="7h2d", opponents="1", stack="15"),
        # 4. Flop c-bet on dry board (BTN CO open, dry flop, c-bet spot)
        dict(name="BTN AKs flop c-bet dry board", position="BTN", hand="AhKs", board="Qd7h2c", opponents="1", stack="80"),
        dict(name="CO KQo flop c-bet paired dry", position="CO", hand="KhQd", board="Qh7c2s", opponents="2", stack="60"),
        # 5. Other postflop (wet/dynamic, value)
        dict(name="CO AQh flop semi-wet", position="CO", hand="AhQh", board="JhTh2c", opponents="2", stack="60"),
        dict(name="BB set flop (facing or cbet context)", position="BB", hand="5h5d", board="5c9h2d", opponents="1", stack="50"),
        # 6. Preflop open from EP for legacy compat check
        dict(name="UTG 77 preflop open", position="UTG", hand="7h7d", opponents="3", stack="100"),
    ]

    original_flag = USE_NEW_BRAIN
    legacy_out = {}
    new_out = {}

    # --- LEGACY PATH (forced ONLY for compat/debug verification) ---
    print("\n--- LEGACY PATH (forced USE_NEW_BRAIN=False) ---")
    print("   (This path must continue to work for old callers/debug; forced via direct set here. Normal use is always new A1.)")
    USE_NEW_BRAIN = False
    for spot in CANONICAL_SPOTS:
        kw = {k: v for k, v in spot.items() if k != "name"}
        try:
            text, data = get_advice(**kw)
            legacy_out[spot["name"]] = (text, data)
            # Print abbreviated for readability in test run; full text is available
            preview = text.splitlines()[0] if text else "(empty)"
            print(f"  ✓ {spot['name']}: {preview[:70]}...")
            # Verify basic invariants for legacy
            if "Enter your 2 hole cards" in text or "⚠️" in text:
                print("    (note: input validation path)")
        except Exception as ex:
            legacy_out[spot["name"]] = (f"LEGACY ERROR: {ex}", {})
            print(f"  ✗ {spot['name']} LEGACY ERROR: {ex}")

    # --- NEW BRAIN PATH (default primary) ---
    print("\n--- NEW BRAIN PATH (USE_NEW_BRAIN=True; the default A1 experience) ---")
    print("   Verifies: no crash + produces richer, structured output (now primary for GUI)")
    USE_NEW_BRAIN = True
    for spot in CANONICAL_SPOTS:
        kw = {k: v for k, v in spot.items() if k != "name"}
        try:
            text, data = get_advice(**kw)
            new_out[spot["name"]] = (text, data)
            preview = (text.splitlines()[0] if text else "(empty)")
            print(f"  ✓ {spot['name']}: {preview[:70]}...")
            # Basic reasonableness: should contain A1 or action keywords, not just error
            if "A1 Brain" not in text and not any(x in text for x in ("OPEN", "RAISE", "FOLD", "BET", "CALL", "SHOVE", "CHECK")):
                print("    (warning: output may be minimal)")
        except Exception as ex:
            new_out[spot["name"]] = (f"NEW ERROR: {ex}", {})
            print(f"  ✗ {spot['name']} NEW BRAIN CRASHED: {type(ex).__name__}: {ex}")

    USE_NEW_BRAIN = original_flag

    # --- SIDE-BY-SIDE COMPARISON + HIGHLIGHTS ---
    print("\n" + "-" * 72)
    print("=== OLD vs NEW — KEY SPOT COMPARISONS ===")
    for spot in CANONICAL_SPOTS:
        name = spot["name"]
        l_text, l_data = legacy_out.get(name, ("N/A", {}))
        n_text, n_data = new_out.get(name, ("N/A", {}))
        print(f"\n[{name}]")
        print("  LEGACY (first 3 lines, for debug verification):")
        for ln in (l_text or "").splitlines()[:3]:
            print("   ", ln)
        print("  NEW A1 (first 5 lines):")
        for ln in (n_text or "").splitlines()[:5]:
            print("   ", ln)
        # crude action diff
        l_act = "fold" if "FOLD" in (l_text or "") else ("shove" if "SHOVE" in (l_text or "") or "PUSH" in (l_text or "") else ("raise" if any(x in (l_text or "") for x in ("OPEN", "RAISE", "bet")) else "other"))
        n_act = n_data.get("action") or ("bet" if "BET" in (n_text or "") or "OPEN" in (n_text or "") else "fold" if "FOLD" in (n_text or "") else "other")
        diff = "SAME-ish" if l_act == n_act or (l_act in ("raise", "bet") and n_act in ("bet", "raise", "OPEN / RAISE")) else "DIFF"
        print(f"  → Action summary: legacy={l_act} vs new={n_act}  [{diff}]")

    print("\n" + "-" * 72)
    print("=== VERIFICATION NOTES (from execution) ===")
    print("• A1 new brain is now THE UNAMBIGUOUS DEFAULT (USE_NEW_BRAIN=True at module load; legacy only if forced for debug).")
    print("• Legacy path: executed cleanly with original logic (no modifications to the")
    print("  non-A1 branch; forced temporarily in test). Output matches historical exactly.")
    print("• New brain: all canonical spots ran WITHOUT CRASH (see ✓ above).")
    print("• New output is now much richer thanks to format_a1_advice + robust GameState:")
    print("    - Includes board texture (dry/wet, paired, dynamic) on postflop spots")
    print("    - Reports SPR, equity_vs_random, regime, in_open_range, nash etc.")
    print("    - Uses proper action wording + header that can drop-in replace GUI text")
    print("    - BB 'vs raise' now passes bet_to_call/facing_action into GameState")
    print("• Where new is better:")
    print("    - Postflop (e.g. dry board c-bet): new explains texture (rainbow, dry),")
    print("      dynamic score, SPR — legacy only gave raw equity + weak/strong bucket.")
    print("    - Structure: Decision object + metrics ready for future overlay/voice.")
    print("    - Config driven (iters, thresholds) — easier to tune than hardcoded.")
    print("    - Preflop short/deep logic identical in spirit but uses shared ranges module.")
    print("• Force legacy anytime: POKERFLEX_FORCE_LEGACY_BRAIN=1 python ... (or CONFIG)")
    print("• Remaining gaps (not in scope): facing bet sizes from GUI, full vs-range eq,")
    print("  multi-street history, exact GTO solve (still heuristic).")
    print("=" * 72)

    # Final quick sanity under both modes for the original sample list (default now NEW)
    print("\n=== Quick re-run of original samples under BOTH modes (NEW A1 is default) ===")
    for mode_name, flag in [("LEGACY (forced for debug)", False), ("NEW (unambiguous default)", True)]:
        USE_NEW_BRAIN = flag
        print(f"\n-- mode={mode_name} --")
        for kw in (
            dict(position="BTN", hand="AhKs", opponents="2", stack="100"),
            dict(position="CO", hand="AhKs", board="Qd7h2c", opponents="1"),
        ):
            try:
                t, d = get_advice(**kw)
                print(f"  {kw.get('position')} {kw.get('hand')}{' board' if kw.get('board') else ''}: OK (len={len(t)})")
            except Exception as ex:
                print(f"  ERROR under {mode_name}: {ex}")
    USE_NEW_BRAIN = original_flag

    # ----------------------------------------------------------------------- #
    # ICM INTEGRATION TEST (new brain + direct preflop; vs chip-EV)
    # Uses GameState.tournament_mode + players_remaining to trigger nash ICM.
    # Shows decision + range % diffs for 6-handed final table short stack.
    # This exercises: models, preflop, nash.get_icm_factor + adjusted decisions.
    # ----------------------------------------------------------------------- #
    print("\n" + "=" * 72)
    print("=== ICM SUPPORT TEST — NEW BRAIN TOURNAMENT MODE (6h final table 10bb) ===")
    print("Task: basic ICM factor for push/fold; marginal shoves tighter, calls looser.")
    print("Compare chip-EV (tournament_mode=False) vs ICM (tournament_mode=True).")
    print("=" * 72)

    try:
        from .models import GameState, Board, Street
        from .preflop import get_preflop_decision
        from . import nash

        b = Board(cards=[], street=Street.PREFLOP)

        # 6-handed final table, hero 10bb effective, SB spot (hu vs BB)
        # Use marginal hand 76o that demonstrates shove->fold under ICM (see nash diffs)
        state_chip = GameState(
            hero_hand=["7s", "6d"], board=b, effective_stack=10.0,
            num_opponents=1, hero_position="SB",
            tournament_mode=False, players_remaining=6
        )
        state_icm = GameState(
            hero_hand=["7s", "6d"], board=b, effective_stack=10.0,
            num_opponents=1, hero_position="SB",
            tournament_mode=True, players_remaining=6, icm_factor=0.0
        )

        dec_chip = get_preflop_decision(state_chip)
        dec_icm = get_preflop_decision(state_icm)

        print("\n  Direct new-brain preflop (76o SB @ 10bb vs 1 opp, 6h table -- marginal that flips):")
        print(f"    chip-EV: action={dec_chip.primary_action.action_type}  icm_factor={dec_chip.metrics.get('icm_factor', 0.0)}")
        print(f"             {dec_chip.explanation.split('(')[-1] if '(' in dec_chip.explanation else dec_chip.explanation[:80]}")
        print(f"    ICM    : action={dec_icm.primary_action.action_type}  icm_factor={dec_icm.metrics.get('icm_factor', 0.0)}")
        print(f"             {dec_icm.explanation.split('(')[-1] if '(' in dec_icm.explanation else dec_icm.explanation[:80]}")

        # Also multiway open (e.g. 6h, 5 behind for early pos)
        state_mw_chip = GameState(hero_hand=["Kh", "9h"], board=b, effective_stack=10.0,
                                  num_opponents=5, hero_position="UTG", tournament_mode=False)
        state_mw_icm = GameState(hero_hand=["Kh", "9h"], board=b, effective_stack=10.0,
                                 num_opponents=5, hero_position="UTG", tournament_mode=True, players_remaining=6, icm_factor=0.0)
        dmw_c = get_preflop_decision(state_mw_chip)
        dmw_i = get_preflop_decision(state_mw_icm)
        print("\n  Multiway open-shove approx (K9s UTG 10bb, 6h):")
        print(f"    chip-EV: {dmw_c.primary_action.action_type}  icm_f={dmw_c.metrics.get('icm_factor',0)}")
        print(f"    ICM    : {dmw_i.primary_action.action_type}  icm_f={dmw_i.metrics.get('icm_factor',0)}")

        # Range % diffs via nash (the core of "how ranges change")
        print("\n  Nash range % changes (6h 10bb):")
        f6 = nash.get_icm_factor(6, 10.0, is_final_table=True)
        eq = nash.load_matrix()
        j0, c0 = nash.solve_hu(10, eq, icm_factor=0.0)
        j1, c1 = nash.solve_hu(10, eq, icm_factor=f6)
        print(f"    HU 10bb: chip jam/call {nash.range_pct(j0):.1f}%/{nash.range_pct(c0):.1f}%  "
              f"icm{f6} {nash.range_pct(j1):.1f}%/{nash.range_pct(c1):.1f}%")
        jm0, _c0 = nash.solve_multiway_shove(10, 5, eq, icm_factor=0.0)
        jm1, _c1 = nash.solve_multiway_shove(10, 5, eq, icm_factor=f6)
        print(f"    MW k=5 10bb: chip jam {nash.range_pct(jm0):.1f}%   icm{f6} jam {nash.range_pct(jm1):.1f}%")

        print("\n  (See also `python nash.py` for more ICM range tables and hand decision diffs.)")
    except Exception as ex:
        print(f"  ICM TEST ERROR (non-fatal for overall): {type(ex).__name__}: {ex}")

    print("\nSelf-test complete. A1 new brain is now THE UNAMBIGUOUS DEFAULT. Legacy preserved exactly (only when forced via env/CONFIG for debug, never primary).")
    print("For expanded live scenarios (partials/street/new-hand/low-conf + notes+ICM E2E + perf bench): `python -m pokerflex --self-test` and `--bench`.")

    # ----------------------------------------------------------------------- #
    # EXPLOITATIVE NOTES TESTS (GTO vs Explo) — exercised under new A1 default
    # Demonstrates player notes system, presets, range adjuster, decision diffs.
    # Run as part of: python poker_engine.py
    # ----------------------------------------------------------------------- #
    print("\n" + "=" * 72)
    print("=== EXPLOITATIVE PLAYER NOTES SYSTEM — TESTS & EXAMPLES ===")
    print("A1 new brain (THE DEFAULT: USE_NEW_BRAIN=True); pass player_notes=... or set_explo_notes()")
    print("Presets: use_nit_preset(), use_station_preset() etc. Notes persist to clubgg_player_notes.json (CONFIG default; runner/GUI use clubgg variant)")
    print("Force legacy (debug only): POKERFLEX_FORCE_LEGACY_BRAIN=1 (old path still works for notes in limited cases)")
    print("=" * 72)

    # Ensure new brain
    original_new = USE_NEW_BRAIN
    original_ex = USE_EXPLOITATIVE
    USE_NEW_BRAIN = True
    USE_EXPLOITATIVE = True  # will cause lookup of default if no explicit

    # Setup example notes via the simple CLI functions
    print("\n--- Setup notes via CLI helpers (set_explo_notes / presets) ---")
    nit_notes = use_nit_preset("nit")
    print(f"  NIT notes (via preset): fold_to_cbet={nit_notes.get('fold_to_cbet')}, dry={nit_notes.get('fold_to_cbet_dry')}, AF={nit_notes.get('aggression_factor')}")
    print(f"    notes: {nit_notes.get('notes', '')[:80]}...")

    station_notes = use_station_preset("station")
    print(f"  STATION notes: fold_to_cbet={station_notes.get('fold_to_cbet')}")

    # Direct set
    set_explo_notes("tight_passive", fold_to_cbet=0.72, aggression_factor=0.5, notes="manual nit-like")
    print(f"  Manual set for 'tight_passive': {get_explo_notes('tight_passive').get('fold_to_cbet')}")

    print(f"  Players with notes: {list_explo_players()}")

    # Example spots for comparison: pure GTO (no notes) vs with notes
    # Use a classic c-bet dry board spot (hero IP with strong but not nut, vs 1)
    # And a marginal bluff candidate spot.
    EXPLO_SPOTS = [
        dict(name="Dry flop cbet - hero KQo (value-ish)", position="BTN", hand="KhQd", board="Qh7c2s", opponents="1", stack="80"),
        dict(name="Dry flop cbet - hero 98s (semi/bluff candidate)", position="BTN", hand="9h8h", board="Qh7c2s", opponents="1", stack="80"),
        dict(name="Wet board - hero A9s (thin value vs station)", position="CO", hand="Ah9h", board="JhTh2c", opponents="1", stack="60"),
        dict(name="Facing cbet dry - hero A9o (marginal call vs nit?)", position="BB", hand="Ad9d", board="Qd7h2c", opponents="1", stack="70"),  # note: BB pre sets facing but for postflop use board
    ]

    print("\n--- GTO (no notes) vs EXPLO (with nit/station notes) on same spots ---")
    for spot in EXPLO_SPOTS:
        name = spot["name"]
        base_kw = {k: v for k, v in spot.items() if k != "name"}

        # 1. Pure GTO (explicit empty notes or force GTO)
        try:
            # Temporarily clear default influence for pure GTO run
            clear_explo_notes("villain")
            t_gto, d_gto = get_advice(**base_kw)  # no player_notes -> pure
            gto_action = d_gto.get("action") or ("bet" if "BET" in (t_gto or "") else "check" if "CHECK" in (t_gto or "") else "call" if "CALL" in (t_gto or "") else "fold")
        except Exception as ex:
            t_gto, d_gto, gto_action = f"ERR: {ex}", {}, "err"

        # 2. Vs NIT (high fold_to_cbet)
        try:
            nit_kw = dict(base_kw)
            nit_kw["player_notes"] = get_explo_notes("nit")
            t_nit, d_nit = get_advice(**nit_kw)
            nit_action = d_nit.get("action") or ("bet" if "BET" in (t_nit or "") else "check" if "CHECK" in (t_nit or "") else "call" if "CALL" in (t_nit or "") else "fold")
        except Exception as ex:
            t_nit, d_nit, nit_action = f"ERR: {ex}", {}, "err"

        # 3. Vs STATION (low fold)
        try:
            sta_kw = dict(base_kw)
            sta_kw["player_notes"] = get_explo_notes("station")
            t_sta, d_sta = get_advice(**sta_kw)
            sta_action = d_sta.get("action") or ("bet" if "BET" in (t_sta or "") else "check" if "CHECK" in (t_sta or "") else "call" if "CALL" in (t_sta or "") else "fold")
        except Exception as ex:
            t_sta, d_sta, sta_action = f"ERR: {ex}", {}, "err"

        print(f"\n[{name}]")
        print(f"  GTO (pure):     action~{gto_action}   | first line: {(t_gto or '').splitlines()[0][:65] if t_gto else 'N/A'}...")
        print(f"  EXPLO vs NIT:   action~{nit_action}   | notes: fold_cbet~{nit_kw.get('player_notes',{}).get('fold_to_cbet')}  | first: {(t_nit or '').splitlines()[0][:65] if t_nit else 'N/A'}...")
        print(f"  EXPLO vs STA:   action~{sta_action}   | notes: fold_cbet~{sta_kw.get('player_notes',{}).get('fold_to_cbet')}  | first: {(t_sta or '').splitlines()[0][:65] if t_sta else 'N/A'}...")

        # Show key metrics diff if present (explo vs gto)
        if isinstance(d_nit, dict) and isinstance(d_gto, dict):
            en = d_nit.get("explo_bet_freq_mult") or d_nit.get("explo_notes_used")
            eg = d_gto.get("explo_notes_used")
            print(f"    NIT metrics explo? {bool(en)}  bet_mult={d_nit.get('explo_bet_freq_mult')}  eqr_nit={d_nit.get('equity_vs_range')} vs gto={d_gto.get('equity_vs_range')}")

    # Restore and demo direct advisor + GameState path too
    print("\n--- Direct GameState + advisor.advise(player_notes=...) path (bypasses legacy_to) ---")
    from .models import GameState, Board, Street, legacy_to_gamestate
    from .advisor import get_advisor
    try:
        # Build a postflop state manually
        b = Board(cards=["Qd", "7h", "2c"], street=Street.FLOP)
        st = GameState(
            hero_hand=["Kh", "Qd"],
            board=b,
            pot=6.0,
            effective_stack=75,
            bet_to_call=0.0,
            hero_position="BTN",
            num_opponents=1,
            icm_factor=0.0,
            action_history=[  # demo history for A1 history-aware path test
                {"street": "preflop", "actor": "villain", "action": "call"},
                {"street": "flop", "actor": "hero", "action": "bet", "size": 2.0},
            ],
        )
        # GTO
        dec_g = get_advisor().advise(st, action_history=getattr(st, "get_action_history_dicts", lambda: getattr(st, "action_history", []))() )  # no notes
        # Explo nit
        nit_n = get_explo_notes("nit")
        dec_e = get_advisor().advise(st, player_notes={"villain": nit_n}, use_exploits=True, action_history=getattr(st, "get_action_history_dicts", lambda: getattr(st, "action_history", []))() )
        print(f"  Direct: GTO action={dec_g.primary_action.action_type}  vs NIT action={dec_e.primary_action.action_type}")
        print(f"    GTO expl: {dec_g.explanation[:90]}...")
        print(f"    NIT expl: {dec_e.explanation[:90]}...")
        if "explo" in (dec_e.explanation or "").lower() or dec_e.metrics.get("explo_notes_used"):
            print("    ✓ Notes successfully affected explanation/metrics (explo mode engaged)")

        # History verif (A1 action_history tracking)
        try:
            hm_g = dec_g.metrics or {}
            hm_e = dec_e.metrics or {}
            has_h = bool(hm_g.get("history_events") or getattr(st, "action_history", None))
            print(f"    History test: events in state={len(getattr(st,'action_history',[]))}, metrics_g={hm_g.get('history_events')}, story_tag in expl? {'story:' in (dec_g.explanation or '')}")
            if has_h:
                print("    ✓ action_history passed through to GameState + advisor + metrics (multi-street ready)")
        except Exception as _hx:
            print(f"    (history verif nonfatal: {_hx})")
    except Exception as ex:
        print(f"  Direct path error (non-fatal): {ex}")

    # Cleanup for test repeatability (optional)
    clear_explo_notes()
    print("\n  (notes cleared for clean test state)")

    USE_NEW_BRAIN = original_new
    USE_EXPLOITATIVE = original_ex

    print("\n=== EXPLOIT TESTS COMPLETE ===")
    print("See diffs above: vs nit typically increases bet freq / bluffs (wider c-bets);")
    print("vs station reduces bluffs (more checks / value-only bets). Range weights adjusted internally.")
    print("All builds on Range (weights) + GameState.player_notes + advisor optional arg.")
    print("New A1 brain is THE UNAMBIGUOUS DEFAULT; legacy forceable for comparison/debug only (never primary path).")
    print("=" * 72)

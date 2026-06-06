"""Verify the position-specific PT4 strats in the A1 brain.
Reconstructs two real hands from the NL100 session.
Run with the project venv python.
"""
import sys
from pathlib import Path

# Ensure we can import pokerflex package
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokerflex.models import GameState, Board, Street
from pokerflex.preflop import get_preflop_decision
from pokerflex.advisor import format_a1_advice

def make_state(hand, pos, bet_to_call=0.0, pot=2.5, n_opp=3, notes=None):
    b = Board(cards=[], street=Street.PREFLOP)
    s = GameState(
        hero_hand=hand,
        board=b,
        pot=pot,
        effective_stack=100.0,
        bet_to_call=bet_to_call,
        hero_position=pos,
        num_opponents=n_opp,
        tournament_mode=False,
        player_notes={"hero": notes or {"aggression_factor": 1.5, "hero_anno": "PT4 test"}},
    )
    return s

print("=== VERIFY PT4 POSITION-SPECIFIC STRATS (NL100 hands) ===\n")

# Case 1: Winning pos CO, AQo facing small open (the +6.5bb 3bet hand)
print("Case 1: CO + AQo vs small raise (PT4 win line, should 3BET/raise)")
s1 = make_state(["Ac", "Qd"], "CO", bet_to_call=2.5, pot=4.0, n_opp=2)
d1 = get_preflop_decision(s1)
print(format_a1_advice(s1, d1))
print("Primary action:", d1.primary_action.action_type, "size=", d1.primary_action.size_bb)
assert d1.primary_action.action_type in ("bet", "raise"), "Expected raise/3bet in winning pos"
print("✅ PASS\n")

# Case 2: SB + 44 facing raise (the leak hand, should FOLD even with hero aggro)
print("Case 2: SB + 44 vs raise (PT4 leak, should FOLD tighter GTO)")
s2 = make_state(["4c", "4h"], "SB", bet_to_call=5.0, pot=7.0, n_opp=3)
d2 = get_preflop_decision(s2)
print(format_a1_advice(s2, d2))
print("Primary action:", d2.primary_action.action_type)
assert d2.primary_action.action_type == "fold", "Expected fold from SB (losing pos)"
print("✅ PASS\n")

# Case 3: CO + 86s unopened or low bet (steal win line)
print("Case 3: CO + 86s (PT4 CO steal win, should RAISE)")
s3 = make_state(["8d", "6d"], "CO", bet_to_call=0.0, pot=1.5, n_opp=2)
d3 = get_preflop_decision(s3)
print(format_a1_advice(s3, d3))
print("Primary action:", d3.primary_action.action_type, "size=", d3.primary_action.size_bb)
assert d3.primary_action.action_type in ("bet", "raise"), "Expected raise from CO winning pos"
print("✅ PASS\n")

print("All verifications passed. The 420x420 ANALYZE NOW will now respect winning vs losing positions from your PT4 NL100 hands.")

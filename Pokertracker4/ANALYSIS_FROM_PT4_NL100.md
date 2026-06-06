# PT4 Hand Analysis — PokerFlex A1 Strats (position-specific)

**Source**: `pokertracker4/ClubGG/Ms Thomson BOMB POTZ - $1 NL (7 max) - 202603012303.txt`
**Stake**: NL100 (0.5/1 blinds) — matches your "mostly NL100+NL200 and NL50" filter. Bomb pot variant (extra dead money every hand).
**Rule applied (original + your update)**: ONLY clear lines where "something good happened" (you won bb, profitable aggression). 
**Your latest clarification**: 
- Positions you win a lot from → integrate the aggressive strat (wider opens/3bets/isos, hero aggro).
- Positions you lose a lot from → play tighter / more GTO (base ranges, fold vs action, no hero looseness).

## Parsed Hero Results (key hands only; full parser in parse_hero_positions.py)

Wins (clear +EV aggro):
- HJ/MP (seat4/btn7): AcQd — raised to 10.43 (3bet over c971e6 small raise), took $6.5 uncontested pre. **+6.5bb**
- BTN/CO (seat4/btn5): 8d6d — raised 1.5 to 2.5 after folds, won $2.5. **CO steal with suited gapper**
- CO/HJ (seat4/btn6): AdJs — raised 1.5 to 2.5 vs 1 limp (babf65d0), checked flop/turn on drawy Qs8h9sTs, called river $2.14 small bet, won $10.78 with Q-high flush. **+10.78bb iso + realize**
- (Parser noise on one; the JTs hand below was actually a big loss)

Losses / leaks (tighter needed):
- SB (seat4/btn3): 4c4h — called $4.5 vs c971e6 raise + 245.. call, check-called flop JdQs6d small bet, check-fold turn Js + big bet. Invested and lost the calls. **SB defend leak**
- HJ/MP late (seat4/btn7): JhTh — open-raised $2-3, called 3bet to $9 + BB call, check flop Jd3h2c, called turn donk $20.62, called river $51.55 overbet on paired board, lost to quads (~$78+ invested, huge pot to villain). **Over-call vs 3bet + spewy river call in bloated pot (even from "winning" pos the postflop was the leak; pre open itself standard)**

Other hands: mostly folds pre (correct). No strong win signals from SB/BB/UTG/early.

**Position signal (small but clear sample)**:
- Winning a lot: HJ, CO, BTN (late position initiative, 3bet, iso vs limp/dead $).
- Losing / play GTO: SB (defending), and vs 3bet over your opens (don't call light then spew).

## Implemented Strats (only the above, position-gated)

In `pokerflex/preflop.py:get_preflop_decision` (used by ANALYZE NOW in the 420x420 app + all paths):

- `WIN_POS = ("CO", "BTN", "HJ", "MP")`
- **When in winning pos + hero aggro (the checkbox default True, sets aggression_factor 1.5 + hero_anno)**:
  - Facing small raise/open (bet_to_call >0.5): 3bet AQo/AQs/AJs/KQs/AKs/AKo/99+ (directly from the AQo 3bet win). Sizing ~3.8x * hero_mult (larger when aggro). Explanation calls out the exact PT4 hand.
  - Unopened or dead money (limps/antes/bomb overlay, pot>3 or n_opp>=2): raise/iso/steal with in-range + the multiway bypass now gated to WIN_POS. Uses 86s CO steal and AJo iso as examples in text. Size 3.5bb * hero_mult.
  - hero_mult=1.15 applied to sizing only in these pos.
- **When NOT in winning pos (SB, BB, UTG/early) or marginal hand vs action**:
  - Facing raise: fold (even if "in_range" like 44). Avoids exactly the SB 44 call leak and loose JTs vs 3bet.
  - No dead_money wide raise from SB.
  - hero_mult ignored or forced to 1.0 for sizing/conditions.
  - Falls back to strict is_in_open_range or explicit fold + explanation citing "PT4 leaks were here; tighter GTO".
- Metrics now include "winning_pos": 1.0/0.0 and "pt4_derived".
- Explanations in decisions reference the specific hands/positions so you see why.

In `pokerflex/main.py` (the 420x420 "CHECK CURRENT HAND" app):
- Hero aggro checkbox still defaults on.
- When on, the persisted "hero" notes now include the position-specific anno: "PT4 NL100: aggro ONLY winning pos (HJ/CO/BTN) — 3bet AQo, CO 86s steal, AJo iso. SB/early: tighter GTO (your leaks)."
- This flows to effective_notes → preflop hero_notes.

ranges.py base ranges left mostly as-is (already loose on BTN/CO with 85s+/86s+ etc., which covered the 86s).

No changes to postflop yet (the JTs loss was mostly postflop overcall; preflop module is the quick win for "strats").

## Notes / Caveats
- Sample = 1 NL100 bomb pot session (ClubGG). Limited hands. "Winning alot" is directional from the 3 clear profitable preflop aggression lines.
- Bomb pots inflate dead money → the "raise wide in position vs money in" is extra +EV here vs standard cash, but the late-pos initiative principle transfers to normal NL50/100/200 (your requested stakes).
- The huge loss hand shows that even from CO/HJ, calling 3bets light + big river calls with TP weak is -EV. Our preflop now suggests fold vs raise for non-premiums from anywhere (good default until we add better vs-3bet logic).
- When you drop more NL50/NL100/NL200 exports into pokertracker4/ (different sites/clients), re-run analysis or tell me the new winning positions and I'll refine the WIN_POS list + hand classes.
- The 420x420 ANALYZE NOW button + real SS will now use this: if table shows you in CO with AQo facing a raise + hero aggro on → 3bet. If SB with 44 facing → fold.

This is the direct, scoped implementation of your request (no other features). Only clear good lines from the specified stakes/positions.

Next: drop more hands or test live with the small app window. Launch with launch_new_app.bat if needed.

"""Quick parser to map Hero positions and results from the PT4 NL100 session.
Focus: which positions Hero wins/loses from. Only clear lines.
"""
import re
from pathlib import Path

path = Path("pokertracker4/ClubGG/Ms Thomson BOMB POTZ - $1 NL (7 max) - 202603012303.txt")
txt = path.read_text(encoding="utf8", errors="ignore")

# Split on hand starts
hand_starts = list(re.finditer(r"Poker Hand #(ring_\d+):", txt))
results = []

for i, m in enumerate(hand_starts):
    start = m.start()
    end = hand_starts[i+1].start() if i+1 < len(hand_starts) else len(txt)
    h = txt[start:end]

    if "Dealt to Hero" not in h:
        continue

    hid = m.group(1)
    btn_match = re.search(r"Seat #(\d+) is the button", h)
    btn = int(btn_match.group(1)) if btn_match else None

    hero_seat_m = re.search(r"Seat (\d+): Hero", h)
    hseat = int(hero_seat_m.group(1)) if hero_seat_m else None

    # Rough 7-max position from button. Seats usually increase away from button preflop order.
    # Common: button acts last pre. If hseat close after btn in numbering, late.
    pos = "UNK"
    if btn is not None and hseat is not None:
        diff = (hseat - btn) % 7
        # Heuristic based on observed hands + standard
        if diff == 0 or diff == 6:  # hero on or right after button often BTN/CO in practice here
            pos = "BTN/CO"
        elif diff in (1, 5):
            pos = "CO/HJ"
        elif diff in (2, 4):
            pos = "HJ/MP"
        elif diff == 3:
            pos = "MP/UTG"
        else:
            pos = f"off{ diff}"

    # Special case explicit blinds from text
    if "Hero: posts small blind" in h:
        pos = "SB"
    if "Hero: posts big blind" in h and "SB" not in pos:
        pos = "BB"

    # Result
    collected = re.search(r"Hero collected \$([0-9.]+)", h)
    showed_won = "Hero showed" in h and "and won" in h
    showed_lost = "Hero showed" in h and "and lost" in h
    folded = "Hero: folds" in h or "folded before Flop" in h or "folded on the" in h

    if collected:
        outcome = f"WON {collected.group(1)}bb"
    elif showed_won:
        outcome = "WON (showdown)"
    elif showed_lost:
        outcome = "LOST (showdown)"
    elif folded:
        outcome = "fold"
    else:
        outcome = "neutral/in"

    # Key action
    acts = re.findall(r"Hero: (raises [^ ]+|calls \$[0-9.]+|folds|checks|bets)", h)
    key_act = acts[0] if acts else ""

    results.append({
        "id": hid,
        "pos": pos,
        "hseat": hseat,
        "btn": btn,
        "action": key_act,
        "outcome": outcome
    })

# Print
print("=== HERO HANDS BY POSITION (only clear win/loss matter) ===")
for r in results:
    print(f"{r['id']}: pos={r['pos']:8} seat{r['hseat']}/btn{r['btn']} | {r['action'] or '':20} | {r['outcome']}")

print("\n=== WINS (clear +EV lines) ===")
for r in results:
    if "WON" in r["outcome"]:
        print(f"  {r['pos']:8} : {r['id']} {r['action']} {r['outcome']}")

print("\n=== LOSSES ===")
for r in results:
    if "LOST" in r["outcome"]:
        print(f"  {r['pos']:8} : {r['id']} {r['action']} {r['outcome']}")

print("\n=== POSITION WIN RATE SIGNAL (small sample) ===")
from collections import Counter, defaultdict
wins = defaultdict(int)
losses = defaultdict(int)
for r in results:
    p = r['pos']
    if "WON" in r["outcome"]: wins[p] += 1
    if "LOST" in r["outcome"]: losses[p] += 1
for p in set(list(wins.keys()) + list(losses.keys())):
    print(f"  {p:8} wins={wins[p]} losses={losses[p]}")

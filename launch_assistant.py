#!/usr/bin/env python
"""
PokerFlex A1 one-click / zero-touch launcher (cross-platform friendly).
Run: python launch_assistant.py
Or double-click if .py associated with python. (Or launch_assistant.bat)

THE HERO / PRIMARY zero-touch experience: tray + live + simulate (demo, no table needed) OR real-vision (auto if vision_config.json profile from calibrate exists).
Delivers always-visible advice surface (tray toasts + auto lightweight draggable Tk overlay in tray mode) + full A1 (GTO+explo notes+ICM+action_history+vision pot/bet) in bg.
Hotkeys global, live auto state+analyze, json live edit, notes.

Defaults now: --tray --background --live [--real-vision if profile else --simulate-vision] --pos BTN --stack 100 --auto-capture
After first run (esp for real tables): run `python -m pokerflex calibrate` (or pokerflex calibrate) — 2-min wizard. Then re-run for reliable hands-off real vision.

Pass extra args on CLI to customize without editing: e.g. python launch_assistant.py --simulate-vision --no-tray --periodic-capture 10 ...

Uses prefer: bare `pokerflex` (after pip install -e .) > python -m pokerflex (primary) > root pokerflex.py shim.
All paths default to new A1 brain (unambiguous).
"""
import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

# Explicit default: new A1 brain is UNAMBIGUOUS default for this launcher entry point.
# (reinforced in child + poker_engine module level = True)
USE_NEW_BRAIN = True
# This + .bat makes double-click / python launch_assistant.py THE ultimate zero-touch for bg live A1 (notes/ICM/explo/hotkeys all active).

# Zero-touch one-click experience: ALWAYS use --background + --live for the A1 real-time brain.
# Default to --simulate-vision (demo, no table/OCR/window needed; auto listener cycles realistic
# states incl ICM + partials, auto state updates, auto rich A1 advice with notes/explo + ICM).
# Seamless: if caller passes --real-vision/--real , switch to real vision path + robust auto-defaults.
# Presets (--pos --stack --auto-capture) ensure immediate usability; vision/live will auto-update pos/stack/hand/board.
# Extras appended last so user overrides (e.g. ... --real-vision --live-poll-secs 8) with 0 edits to this file.
# This + simplified .bat gives true minimal-input / double-click bg A1 assistant.
# Polished + E2E verified (direct, runner --bg/--live/--sim, GUI, packaging, self-tests, legacy via shim, notes/ICM persistence/watcher).
# Tray support: pass --tray (e.g. launch_assistant.py --tray or --tray --real-vision) for system tray UX (optional pystray).
EXTRA = sys.argv[1:] if len(sys.argv) > 1 else []
has_real = any(x in ("--real-vision", "--real") for x in EXTRA)
has_sim = any(x in ("--simulate-vision", "--sim-vision") for x in EXTRA)
has_tray = any(x in ("--tray",) for x in EXTRA)
has_no_tray = any(x in ("--no-tray",) for x in EXTRA)
# Support --client coinpoker|clubgg forward (for CoinPoker 0-touch same as ClubGG)
has_client = False
client_val = None
for i, x in enumerate(EXTRA):
    if x == "--client" and i + 1 < len(EXTRA):
        has_client = True
        client_val = EXTRA[i+1]
        break
    if x.startswith("--client="):
        has_client = True
        client_val = x.split("=", 1)[1]
        break

def _has_vision_profile() -> bool:
    """Detect if user has run calibrate (vision_config.json present in cwd or ~/.pokerflex).
    If yes, default to --real-vision for the hero 0-touch experience (real table reading).
    Otherwise safe --simulate-vision (full live demo w/o table/OCR/tesseract needed).
    """
    try:
        candidates = [
            "vision_config.json",
            os.path.join(HERE, "vision_config.json"),
            os.path.expanduser("~/.pokerflex/vision_config.json"),
        ]
        for p in candidates:
            if p and os.path.exists(p):
                return True
    except Exception:
        pass
    return False

FLAGS = ["--background", "--live"]
# Hero default: tray for minimal always-visible advice (toast + auto tiny Tk overlay) + quiet bg.
# Tray is graceful (falls back if no pystray installed).
if not has_tray and not has_no_tray:
    FLAGS = ["--tray"] + FLAGS  # put --tray first so it sets QUIET etc early in runner
# Client: forward if user passed --client coinpoker (or clubgg explicit). Default in runner is clubgg for compat.
if has_client and client_val:
    FLAGS = ["--client", client_val] + FLAGS
# Vision default: real if profile (post-calibrate) else simulate. User EXTRA overrides win (appended last).
use_real = has_real or (not has_sim and _has_vision_profile())
if use_real:
    FLAGS += ["--real-vision"]
elif not has_real:
    FLAGS += ["--simulate-vision"]  # 0-touch safe default for full end-to-end live sim flow
FLAGS += ["--pos", "BTN", "--stack", "100", "--auto-capture"]
# Companion: auto lightweight overlay for at-a-glance advice (tiny Tk) when tray (default hero) or explicit. Harmless if no tk.
if (not has_no_tray) and "--overlay" not in EXTRA:
    FLAGS = FLAGS + ["--overlay"]

if has_real or use_real:
    # Good robustness defaults for real ClubGG (consec debounce prevents flicker from marginal OCR;
    # min-conf + medium sens for stable auto-apply only on reliable reads; manual/json/hotkey always fallback).
    # These fire with --real-vision for true zero-touch real play (user can still pass their tuned values after to override).
    # LATEST: aggressive preproc for better real OCR on stylized/low-contrast ClubGG cards -> more reliable partials for auto state/analyze.
    # (Applies for explicit --real or auto from vision profile in hero launch.)
    FLAGS += ["--vision-min-conf", "0.28", "--vision-min-consec", "2", "--vision-sensitivity", "medium", "--vision-retries", "5", "--vision-preproc", "aggressive"]

    # Friendly 0-touch nudge: if no calibration profile yet, remind user (non-fatal).
    try:
        import os as _os
        calib = _os.path.exists("vision_config.json") or _os.path.exists(_os.path.expanduser("~/.pokerflex/vision_config.json"))
        if not calib:
            print("  [note] No vision_config.json found yet. For best real-vision results on your table, run `python -m pokerflex calibrate` in another window (or after this launch). The listener will still work with built-in ROIs.")
    except Exception:
        pass

# Append user-provided extras (later in argv wins in argparse for repeated flags/values).
if EXTRA:
    # do not forward launch-only controls (e.g. --no-tray is for deciding default here; runner has no such arg)
    launch_only = {"--no-tray"}
    extra_fwd = [x for x in EXTRA if x not in launch_only]
    FLAGS = FLAGS + extra_fwd

print("=" * 60)
print(" PokerFlex A1 - HERO ZERO-TOUCH one-click background assistant (tray + live + A1 brain)")
print("  (seamless: GTO + explo notes + ICM/tourney + hotkeys + watcher + auto vision state updates + auto-analyze)")
print("  Hotkeys (GLOBAL - works while ClubGG / CoinPoker focused): ctrl+alt+a=analyze | s=status | c=capture | o=toggle floating overlay")
print("  Live edit: poker_current_state.json (primary) / clubgg_current_state.json (compat fallback) / coinpoker_* for --client coinpoker ; same for player_notes.json (auto-reload ~2s)")
print("  HERO DEFAULTS (no args needed): --tray --background --live + ( --real-vision if vision_config.json profile exists else --simulate-vision ) + pos BTN 100bb + auto-capture")
print("    Tray = always-visible advice (toasts on analyze + auto tiny draggable Tk overlay window for at-a-glance A1 while playing) + quiet bg + menu (Analyze/Status/Notes/Startup/Quit) + console auto-hide on Win.")
print("    Overlay + toasts persist last advice summary; full rich A1 (incl action_history, postflop ICM, vision pot/bet) in log + Show Console.")
print("  After FIRST RUN (for real tables/skins): run `python -m pokerflex calibrate` (or pokerflex calibrate) - ~2min wizard. Re-launch for reliable real-vision hands-off (auto uses your ROIs/templates).")
print("  Tray / true bg polish: default now (icon + menu). Requires `pip install pystray` (optional, graceful fallback to quiet bg if absent). Hotkeys + live 100% active.")
print("  Real vision auto-defaults (when chosen): --vision-retries 5 + --vision-min-consec 2 + aggressive preproc + smart partial merge (deeper hands-off OCR for ClubGG/CoinPoker).")
print("  For explicit real (no profile): python launch_assistant.py --real-vision   (or --tray --real-vision)")
print("  CoinPoker (same 0-touch, same brain): python launch_assistant.py --client coinpoker --real-vision --tray")
print("    Calibrate separately for CoinPoker tables (`--client coinpoker` in wizard or auto-detect).")
print("  Multi-client support: --client coinpoker|clubgg (auto from window title). Uses client-prefixed files or generic poker_* (legacy clubgg_ fallback). Calib + live per client.")
print("  Override e.g. no tray or force sim: python launch_assistant.py --no-tray --simulate-vision")
print("  Pass extras anytime (no edit): python launch_assistant.py --real-vision --periodic-capture 10 --vision-min-conf 0.25 --vision-partial-conf 0.18 --vision-min-consec 2 --vision-debug --vision-retries 5 --vision-preproc aggressive")
print("  CoinPoker: python launch_assistant.py --client coinpoker --real-vision  (or --client coinpoker --live --real-vision via python -m pokerflex)")
print("  Sim variety: --sim-scenario mixed|cash|tourney|icm|noisy  (with --vision-debug for live vision tuning logs; 'noisy' for real-vision-like OCR noise harden tests)")
print("  A1 brain is THE UNAMBIGUOUS default everywhere (rich GTO+notes+ICM+explo+history; legacy ONLY via POKERFLEX_FORCE_LEGACY_BRAIN=1 for debug, never primary)")
print("  One-click / minimal-input zero-touch: double-click launch_assistant.bat (or .py) | python -m pokerflex --bg --live ... | pokerflex (post pip -e .)")
print("  Tray one-click: launch_assistant.bat (now defaults tray+live)  (edit .bat or pass --client coinpoker --real-vision for hands-off CoinPoker; same for ClubGG)")
print("  Copy-paste CoinPoker: python launch_assistant.py --client coinpoker ; or with tray+real: python launch_assistant.py --tray --client coinpoker --real-vision")
print("  Verify full (incl live vision+noisy, history, postflop ICM, calib): python -m pokerflex --self-test ; --bench")
print("  All cmds (calibrate, --tray, --self-test, --bench, icm-sim, action, notes edit, set payouts) in help/status/docs.")
print("  FULL E2E VERIFIED + PRODUCTION-READY (A1 default, tray/live/overlay, all bg modes, GUI, packaging, self-tests, notes/ICM/vision pot+bet+history). Just run it and get value.")
print("=" * 60)
print()

# Final zero-touch convenience for background app: seed sample explo note (nit) if notes file absent OR empty (e.g. after self-test clear_explo_notes() or first write).
# This lets first-time users immediately see 🎯 EXPLOIT tags + notes-driven range adjust in live/hotkey analyzes,
# without any manual json edit. (Real users override by editing clubgg_player_notes.json / poker_player_notes.json / coinpoker_*.json live; watcher picks up.)
# State file also touched for convenience (runner will populate on first analyze).
# Client-aware: if --client coinpoker passed, seed coinpoker_ files (separate state/notes); else clubgg_ to keep ClubGG paths identical for existing users.
try:
    import json, os as _os
    cval = (client_val or "clubgg").lower() if has_client else "clubgg"
    if cval == "coinpoker":
        notes_path = "coinpoker_player_notes.json"
        state_path = "coinpoker_current_state.json"
    else:
        notes_path = "clubgg_player_notes.json"
        state_path = "clubgg_current_state.json"
    # note: runner will use generic poker_* primary with clubgg_ fallback load for compat when client=clubgg/no-client

    seed_notes = False
    if not _os.path.exists(notes_path):
        seed_notes = True
    else:
        try:
            if _os.path.getsize(notes_path) < 5:
                seed_notes = True
            else:
                with open(notes_path, "r", encoding="utf-8") as _cf:
                    _data = json.load(_cf)
                    if not isinstance(_data, dict) or len(_data) == 0:
                        seed_notes = True
        except Exception:
            seed_notes = True
    if seed_notes:
        sample = {
            "nit": {
                "fold_to_cbet": 0.78,
                "fold_to_cbet_dry": 0.85,
                "aggression_factor": 0.6,
                "notes": "sample nit for demo — folds too much to cbets; A1 will exploit by betting wider for value/bluff"
            },
            "station": {
                "fold_to_cbet": 0.35,
                "fold_to_cbet_dry": 0.25,
                "aggression_factor": 1.8,
                "notes": "sample station — calls too wide; A1 exploits with thinner value / fewer bluffs vs this player"
            }
        }
        with open(notes_path, "w", encoding="utf-8") as _nf:
            json.dump(sample, _nf, indent=2)
        print(f"[note] Seeded sample explo notes 'nit' + 'station' in {notes_path} (for immediate [EXPLOIT] demo in A1 output + tray quick presets). Edit json live to customize.")
    if not _os.path.exists(state_path):
        with open(state_path, "w", encoding="utf-8") as _sf:
            # seed with sample action_history + pot/bet to demo full flow (history, vision pot/bet, postflop ICM) in first A1 analyze / overlay / toast even before live or user action cmds.
            json.dump({
                "position": "BTN", "hand": "", "board": "", "opponents": "2", "stack": "100",
                "action_history": [
                    {"street": "preflop", "actor": "villain", "action": "raise", "size": 2.5},
                    {"street": "preflop", "actor": "hero", "action": "call", "size": 2.5}
                ],
                "pot": "5.0", "facing_bet": "0", "bet_to_call": "0",
                "_seeded": True
            }, _sf, indent=2)
except Exception as _seed_ex:
    pass  # non-fatal, runner/GUI will handle
print()

# Gentle auto-detect + suggestion for calibrate (key for "just run it" real table success; no hard error).
# If no profile, sim is used (perfect demo). User sees this once on first launch.
try:
    if not _has_vision_profile():
        print("ℹ️  No vision_config.json profile detected yet.")
        print("    • For demo / 0-touch (no table/OCR/tesseract needed): just play — sim cycles realistic hands + auto A1 (notes+ICM+history) every poll.")
        print("    • For real ClubGG/CoinPoker (hands-off table reading): run calibration ONCE → `python -m pokerflex calibrate` (or use tray menu 'Open Calibration' after launch). Pass --client coinpoker to wizard if needed.")
        print("      ~2 minutes wizard saves your ROIs + card templates. Then relaunch (or with --real-vision --client coinpoker) for best OCR/partials/confidence.")
        print("    Tray will remind; --show-calibration to inspect current profile anytime.")
except Exception:
    pass
print()

# === NICE "READY" BANNER (the ultimate just-run-it experience) ===
print("[OK] READY TO PLAY - your zero-touch working product is launching now.")
print("   1. (first time real table?) Use tray 'Open Calibration' or `python -m pokerflex calibrate` once.")
print("   2. Play ClubGG or CoinPoker (table visible for real-vision; use --client coinpoker).")
print("   3. Use hotkeys or tray (no need to look at console). Edit notes json live.")
print("   THE 3 MOST USEFUL HOTKEYS (global - work even with ClubGG / CoinPoker focused):")
print("     * Ctrl+Alt+A  - Analyze now (rich A1: action+reason+ICM/EXPLOIT+history; updates overlay+log+toast)")
print("     * Ctrl+Alt+O  - Toggle floating always-on advice box (compact: action + key reason + tags; draggable, topmost)")
print("     * Ctrl+Alt+S  - Status (current + notes effects)")
print("   Tray (right-click icon): Show Last Advice (persisted rich) | Toggle Overlay | Quick NIT/STATION presets | Open Calibration | Launch GUI | Analyze | Quit")
print("   Full rich A1 (incl. postflop ICM + action history) always available via overlay / tray Show Last / pokerflex_tray.log / last_advice.txt")
print("   For CoinPoker: pass --client coinpoker (e.g. via launcher or python -m pokerflex --client coinpoker --live --real-vision)")
print("=" * 60)
print()

# Zero-touch convenience: THE primary documented launcher is `python -m pokerflex` (works pre/post install from source).
# After `pip install -e .` (or install.bat) the bare `pokerflex` cmd (entry point) is even more zero-touch (no python).
# To ensure the *current source tree edits* are used (even if old 'pokerflex' in PATH points to stale install/venv), we prefer python -m pokerflex (it does path magic to use local package).
# This is THE zero-touch way for the background A1 assistant (new brain default everywhere; seeds explo note for instant notes/ICM/explo demo in live).
# Fallback chain for source-tree / pre-install / post-install robustness. Bare only if no module (rare).
cmd = None
launch_desc = None
# 1. Prefer python -m pokerflex (primary documented, always gets the live package from cwd/editable after cd HERE)
use_module = False
try:
    import importlib.util
    if importlib.util.find_spec("pokerflex") is not None:
        use_module = True
except Exception:
    use_module = False
if use_module:
    cmd = [sys.executable, "-m", "pokerflex"] + FLAGS
    launch_desc = "python -m pokerflex (primary zero-touch launcher; source-tree safe)"
if not cmd:
    # 2. Try bare `pokerflex` cmd (best after global pip install -e . outside tree)
    try:
        import shutil
        if shutil.which("pokerflex"):
            cmd = ["pokerflex"] + FLAGS
            launch_desc = "pokerflex (zero-touch CLI entry point after install)"
    except Exception:
        pass
if not cmd:
    # 3. Root shim fallback
    cmd = [sys.executable, "pokerflex.py"] + FLAGS
    launch_desc = "root pokerflex.py (source-tree bootstrap compat)"
print("Running:", " ".join(cmd), f"({launch_desc})")
print("  (true zero-touch background A1: listener auto-starts for vision-driven updates; hotkeys + json watcher coexist; minimize & play)")
print()

# Ensure A1 new brain UNAMBIGUOUS default in the child process.
# Module-level default in poker_engine.py is True (A1 primary); legacy ONLY via POKERFLEX_FORCE_LEGACY_BRAIN=1 for debug (never primary).
# Explicitly ensure the force-legacy env is NOT set (unless user already set it for debug), and reinforce via package import.
env = os.environ.copy()
# Clear any accidental legacy force for normal launcher use (user can override before calling script if they want debug legacy).
# POKERFLEX_USE_NEW_BRAIN is obsolete (harmless, ignored).
if "POKERFLEX_FORCE_LEGACY_BRAIN" not in env or env.get("POKERFLEX_FORCE_LEGACY_BRAIN", "").strip().lower() not in ("1", "true", "yes"):
    env["POKERFLEX_FORCE_LEGACY_BRAIN"] = ""  # ensure default new brain path (A1 unambiguous)
try:
    from pokerflex import poker_engine as _pe_pkg
    if os.environ.get("POKERFLEX_FORCE_LEGACY_BRAIN", "").strip().lower() not in ("1", "true", "yes"):
        _pe_pkg.USE_NEW_BRAIN = True
except Exception:
    try:
        import pokerflex.poker_engine as _pe_pkg
        if os.environ.get("POKERFLEX_FORCE_LEGACY_BRAIN", "").strip().lower() not in ("1", "true", "yes"):
            _pe_pkg.USE_NEW_BRAIN = True
    except Exception:
        pass
# Also cover root-level `import poker_engine` shim (for any direct compat paths or tests)
try:
    if os.environ.get("POKERFLEX_FORCE_LEGACY_BRAIN", "").strip().lower() not in ("1", "true", "yes"):
        import poker_engine as _root_pe_la
        _root_pe_la.USE_NEW_BRAIN = True
except Exception:
    pass

try:
    subprocess.run(cmd, check=False, env=env)
except KeyboardInterrupt:
    print("\nStopped.")
finally:
    print("Assistant stopped. (state + notes persisted)")

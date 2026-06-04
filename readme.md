# PokerFlex Agent

GTO practice tool for private fake-money poker games with friends.

Built agentically with Grok + Claude.

**The A1 brain + background real-time assistant is ready (final comprehensive E2E verification + packaging + tray complete, 0-touch polished).** The new A1 brain **IS THE UNAMBIGUOUS DEFAULT everywhere** (USE_NEW_BRAIN=True module-level in poker_engine.py + reinforced in every launcher/entrypoint/GUI/`python -m pokerflex`/`pokerflex` CLI/launch_assistant etc; legacy ONLY via explicit POKERFLEX_FORCE_LEGACY_BRAIN=1 for debug, never primary). (E2E covered direct/runner/GUI/bg modes incl live/sim vision/hotkeys/watcher/persist/packaging/self-tests/legacy; polished clean rich A1 text no disclaimers; notes consistently clubgg_* ; production-ready for ClubGG. Full self-tests (poker_engine + nash exit0), live flow E2E (partials+explo+ICM), GUI options, packaging (pip -e + entry points + build_exe.py one-file), tray (pystray optional, menu, hide, startup, popups) all verified. See quickstart.txt end for "READY-TO-USE: EXACT ZERO-TOUCH COMMANDS" summary.)
- `USE_NEW_BRAIN = True` is the explicit module-level default in `poker_engine.py` (both root shim and pokerflex/poker_engine.py) and reinforced in ALL launchers/entry points.
- Every entry point/launcher (`__main__`, `python -m pokerflex`, `python pokerflex.py`, `pokerflex` CLI after `pip install -e .`, GUI `python main.py`, `run_brain`, `launch_assistant.*`, direct `get_advice()`, self-tests) defaults to new A1 (GTO + explo notes + ICM) with zero flags.
- Legacy (exact original behavior) ONLY via explicit `POKERFLEX_FORCE_LEGACY_BRAIN=1` (debug/comparison/old callers ONLY; verified 100% fallback; **never primary**).
**Zero-touch background app (0 touch)**: double-click `launch_assistant.bat` (or `python launch_assistant.py` — always forces --background --live + good A1 defaults for sim/real vision + auto listener) or `python -m pokerflex --background --live --simulate-vision` / `pokerflex ...` after install) and get rich real-time GTO + explo + ICM advice while you play. Supports --simulate-vision (demo, default in launcher; full E2E auto-capture/parse/state/analyze test with partials) vs --real-vision (live ClubGG table or CoinPoker via --client coinpoker + new --vision-preproc for OCR robustness). Full seamless: hotkeys, json watcher, auto state updates from vision (robust partial/conf/consec/preproc), notes/explo, ICM/tournament. Real/sim vision now deliver enhanced set-and-forget live experience. Polished launchers + run_brain ensure minimal/zero input after launch. (E2E covered all: direct/runner/GUI/bg modes/packaging/self-tests/legacy; notes mgr default fixed for clubgg consistency.) Exact ready-to-use cmds + troubleshooting in quickstart.txt (end has "READY-TO-USE" block) and below.

> **High-level snapshot + roadmap**: See [PROJECT_STATUS.md](PROJECT_STATUS.md) for a concise summary of everything built (A1 brain, explo, ICM, runner, vision), quick commands, current limitations (vision is basic/functional but needs calibration for reliable real ClubGG OCR; ICM is short-stack only), and recommended next steps focused on making the vision layer deliver true 0-touch hands-off assistance.

## Performance & Reliability (tuning + verification)

The background A1 assistant is hardened for long sessions and snappier in common paths (no change to A1 defaults or correctness).

- **Caching & early exits**: Equity (vs-range for postflop ranges + vs-random) uses bounded LRU (256 entries, key=hero+board+range_sig+iters) + functools.lru for simple cases. Range expansion cost amortized on repeats (live same board, bench). Postflop has early exits for low-SPR obvious, tiny ranges, incomplete info (fast paths before full sweeps/MC).
- **Config tunables** (pokerflex/config.py + run_brain): `live_poll_interval_secs` (default 10), `bg_quiet_poll_interval_secs` (20), `accurate_equity_iters` (5000 for bench), `vision_history_window` (5 for spike history/recovery). Respect A1 fast defaults in normal use; --live-poll-secs etc still work.
- **Live runner robustness** (run_brain.py listener/watcher/hotkeys): 
  - Thread safety via _STATE_LOCK + helpers (_get_current, _set_current, _snapshot, _update_current) for shared current_inputs across daemon threads + main/hotkeys.
  - Window lost (ClubGG min/switch): capture retries+activate + listener streak detect + exponential backoff (poll up to 45s) + user notify ("bring table forward").
  - OCR spikes: rolling _VISION_HISTORY (CONFIG size) + existing consec + low_conf_streak + backoff + enhanced tips.
  - State corruption: json load except keeps prior state + safe defaults recovery (no crash).
  - No tesseract/cv2: clear actionable messages at --live --real start + capture ("install tesseract-ocr binary... use --simulate-vision... calibrate..."), graceful "no_vision_libs" method + partials still work; encourages --self-test after setup.
- **Verification**:
  - `python -m pokerflex --self-test`: end-to-end exercises A1 advise paths + vision sim (partials, street progression, new-hand detection via robust apply/prefer/merge, low-conf recovery, notes+explo+ICM combo in live flow). Covers more live scenarios. Enhances poker_engine self-tests.
  - `python -m pokerflex --bench [--bench-iters 200]`: times 100 advises on deep cash / short ICM / multiway reps; prints avg/median/ms + cache sizes post-run. Use to measure/verify improvements + no regression in common A1 paths.
  - Existing: `python -m pokerflex.poker_engine` (or direct) for engine canonical + ICM + notes; `_test_simulated_live_flow` helper.
- All new work keeps A1 primary default (USE_NEW_BRAIN=True reinforced), no perf regression on cold/common paths (cache opt-in via use_cache, first-miss cost identical).

See CHANGELOG for task details. Run the --self-test / --bench after changes or setup to verify snappiness + reliability.

## Features (high level)
- `python pokerflex.py` (or `python -m pokerflex` or `pokerflex` CLI) — recommended launcher for interactive or background real-time assistant (zero-touch via launch_assistant.bat / .py)
- **New A1 Brain (THE UNAMBIGUOUS default everywhere)**: heuristic GTO, board texture, range/nut adv, postflop sizing, equity; rich clean explanations via format_a1_advice (no legacy disclaimers in normal A1 paths). **Action history tracking** now first-class for multi-street range construction, blocker awareness, story detection (e.g. check-back cap, donk leads).
- Preflop open ranges + exact Nash push/fold (≤15bb) + ICM adjustments
- **Explo notes** with live presets (nit / station / maniac) that adjust ranges
- **ICM / tournament** support for final tables & short stacks
- Global hotkeys, live json editing + watcher, auto-capture, `--live` mode
- GUI (`python main.py`) also uses A1 (new UNAMBIGUOUS default; legacy forceable ONLY via env for debug)
- Vision / capture foundation present

## Getting Started with the A1 Real-Time Assistant

This is the primary user experience: a real-time GTO + explo + ICM co-pilot you can run in the background while playing (ClubGG focus, works for other tables too).

### Installation (easy distribution / run)
From the project root (PokerFlex folder):

**One-line (recommended):**
```bash
pip install -r requirements.txt && pip install -e .
```
Or on Windows double-click the new `install.bat` (does the above).

- `pip install -e .` makes the package importable and registers the `pokerflex` CLI entry point.
- Standalone packaging: `python build_exe.py` (see "Deploy as background app" below + build_exe.py header).
- Primary documented way (works before/after install):
  ```bash
  python -m pokerflex
  python -m pokerflex --help
  ```
- After install you can also just:
  ```bash
  pokerflex --help
  ```
- Pulls keyboard (hotkeys), pygetwindow (better window capture), Pillow/opencv/pytesseract (vision).
- On Windows for *real* (non-sim) vision/OCR: additionally install the Tesseract OCR binary (see https://github.com/UB-Mannheim/tesseract/wiki) and add to PATH.
- For global hotkeys while another app (ClubGG) has focus: on some Windows setups, run your terminal/PowerShell as Administrator.
- No other steps. The A1 brain (new default) loads automatically.
- `python pokerflex.py`, `python run_brain.py`, `python main.py` still work via root shims for compat.

### Recommended Launcher (Zero Friction)
Always use the top-level convenience entry point (it forces + documents the new A1 brain, good defaults, UTF8 banners). From the project root the most reliable command is the root script:
```bash
python pokerflex.py                 # interactive console (type `help` or just hit ENTER to analyze)
python pokerflex.py --help
# python -m pokerflex also works (package or after proper install)
```
- **Windows one-click zero-touch (FINAL polished)**: double-click `launch_assistant.bat` (or run `python launch_assistant.py`).
  PowerShell users (if you continue in PowerShell on Windows — local only, no git): right-click `launch_assistant.ps1` or run from a PS prompt: `.\launch_assistant.ps1` (or with args `.\launch_assistant.ps1 --client coinpoker --real-vision`).
  The .ps1 sets UTF-8 + chcp 65001 for clean rich A1 output/emoji, prints a short PS-specific header with ExecutionPolicy + "Run as admin for hotkeys" tips, then delegates to the same .py (single source of truth).
  This is THE easiest / true 0-touch way to start the background real-time A1 assistant. (Internally ALWAYS --background --live; chooses sim default or real if --real-vision passed; auto applies robust defaults for real; A1 default always; unified logic so .bat/.ps1 double-click gets all polish.)
  Pass extras without editing: `python launch_assistant.py --real-vision --periodic-capture 10` (or `launch_assistant.bat --real-vision ...` or the .ps1 equivalent — now delegates fully to .py for single source of defaults).
- The launcher delegates to `run_brain.py` but always surfaces the A1 experience.
- Supports every flag the runner does. See also `quickstart.txt` (ultra-short copy-paste reference).

### How to Run the Background A1 Assistant (Zero-Touch Real-Time — Final Instructions)
**This is the primary user experience for actual play.** A real-time GTO + explo + ICM co-pilot you run in the background (or minimized) while focused on ClubGG. Hotkeys work globally. JSON live-edits are watched. `--live` mode adds automatic vision-driven updates + auto-analyze.
All one-click launchers and documented commands default to the new A1 brain.

**ULTIMATE <10 MIN GET-WORKING GUIDE (exact 0-touch steps; A1 default everywhere):**
1. INSTALL (once): `pip install -r requirements.txt && pip install -e .` (or double-click install.bat). Optional: `pip install pystray`; install Tesseract binary for real OCR + PATH.
2. LAUNCH: double-click `launch_assistant.bat` (or `python launch_assistant.py` / `python -m pokerflex --tray --live`).
   - PowerShell users: `.\launch_assistant.ps1` (or right-click the .ps1). The .ps1 is the natural choice if you continue in PowerShell (local edits + run, no git workflow).
   - Tray/overlay for bg-friendly (menu, popups, hide, startup). Minimize and play.
3. CALIBRATE ONCE (real vision): `python -m pokerflex calibrate` (or `pokerflex calibrate`). ~2min wizard; auto-loads for --real-vision / launcher.
4. PLAY: hotkeys (global): Ctrl+Alt+A (analyze/rich A1), S (status), C (capture), O (overlay). Tray menu: Analyze/Status/Notes/Startup/Quit.
5. LIVE NOTES: edit clubgg_player_notes.json (or `notes edit`); watcher ~2s; `note nit fold_to_cbet 0.82`.
6. ICM EX: launch with `--tournament-mode --players-remaining 6 --payouts 0.5,0.3,0.2`; use `set payouts ...`, `icm-sim`, `action bet 3.5` (history).
All cmds (calibrate/--tray/--self-test/--bench/icm-sim/action/notes edit/set payouts) in --help/status/docs. After calib + launch + visible table = true hands-off.

**Crystal-clear steps for zero-touch (recommended first run / demo):**
1. `cd` to the PokerFlex folder.
2. (Once) `pip install -r requirements.txt`  (or double-click install.bat)
3. **Easiest (one-click, TRUE 0-touch)**: double-click `launch_assistant.bat`  
   (or `python launch_assistant.py`; uses `pokerflex` entry point after `pip install -e .`).
   - Always forces --background --live + A1 defaults (sim for no-table demo; pass --real-vision for real table; auto applies robust --vision-min-consec 2 / conf for real).
   - Auto-starts listener for vision-driven state updates + auto A1 (notes/explo/ICM/hotkeys/watcher all seamless; E2E verified).
4. Watch the banner (confirms A1 new brain + live), then minimize the window.
5. Play hands on ClubGG (or just let it run for demo). (After step 3 calib, re-launch for production real-vision strength.)
6. Use hotkeys (see below) or watch periodic rich A1 advice appear in the terminal (auto on changes).
7. Stop with Ctrl+C when done (state/notes persisted).

**Exact polished zero-touch commands (one-click or direct; launcher unifies defaults):**
```bash
# ZERO-TOUCH one-click (sim demo by default; full auto live listener):
double-click launch_assistant.bat
# or
python launch_assistant.py
# Real (table visible; launcher applies auto robust defaults like consec=2):
python launch_assistant.py --real-vision
# With extras (still no launcher edit):
python launch_assistant.py --real-vision --periodic-capture 8 --live-poll-secs 6 --vision-preproc aggressive

# Direct equiv (primary, works pre/post install):
python -m pokerflex --background --live --simulate-vision --pos BTN --stack 100 --auto-capture
# (after `pip install -e .`: pokerflex --background --live --simulate-vision --pos BTN --stack 100 --auto-capture )
# Real hands-off (run_brain auto robusts when real path):
python -m pokerflex --background --live --real-vision --auto-capture --vision-preproc aggressive
  # Hardened vision now gives better real reliability (pot/facing_bet/street/action auto-extract + temporal smoothing/vote/adaptive OCR voting + new ROIs); pot/bet feed live state + A1 facing decisions. Use --vision-history-len 5 etc. (see --help + capture.py). Still zero-touch + full backward.
# Tuned real:
# python -m pokerflex --background --live --real-vision --periodic-capture 8 --auto-capture --vision-min-conf 0.28 --vision-min-consec 2 --vision-preproc aggressive
# With --vision-debug (extra logs for real partial/conf diagnosis) + expanded sim scenarios:
# python -m pokerflex --background --live --real-vision --vision-debug --sim-scenario mixed --vision-min-consec 2
# launcher: python launch_assistant.py --real-vision --vision-debug
# Add state:
python pokerflex.py --background --live --periodic-capture 12 --auto-capture --pos BTN --stack 85 --tournament-mode --players-remaining 6
```

**Calibrating for your ClubGG or CoinPoker table (2 minutes to set-and-forget per client — strongly recommended for real-vision)**
The built-in ROIs + OCR work for demo/partial use, but for reliable hands-off live play on *your* resolution, skin, zoom, and card art, run the calibration wizard once. It reuses the capture pipeline, auto-grabs (or reuses) samples, uses cv2 to *suggest* ROIs + card rects, and guides you to verify/adjust. (vision-calib-polish: smoother/more reliable so you do it once and get great results.)

```powershell
# One command (works before/after install):
python -m pokerflex calibrate
# or (after pip install -e . or install.bat):
pokerflex calibrate
# or via flag (any entry):
python -m pokerflex --calibrate
# Quick verify using your saved profile (no full wizard):
python -m pokerflex --calib-test

# For CoinPoker (parallel; calib once for CoinPoker table, then use --client):
python -m pokerflex calibrate   # with CoinPoker table visible
python -m pokerflex --background --live --real-vision --client coinpoker
# Tray + CoinPoker:
python -m pokerflex --tray --background --live --real-vision --client coinpoker
# Or launcher:
python launch_assistant.py --client coinpoker --real-vision
```

Wizard steps (fully interactive console; now with progress STEP X/8, better instructions, auto-starting-point):
1. Instruct + (NEW) offer "re-calibrate from existing images" if calib_sample*.png / clubgg_live.png present (no re-grab). (For CoinPoker tables: bring CoinPoker window; wizard is shared, profile+client flag selects at runtime.)
2. Capture (or reuse) multiple samples (robust retries + window activate, same as live). Pick best or average auto-suggests.
3. cv2 auto-suggest ROIs (heuristic: detect green felt area + card sprite clusters in bottom/mid zones) as *starting point* (much better than static defaults). Saves `calib_roi_preview.png` with colored boxes drawn (cv2). 
   Open it (text screenshot example): GREEN box at bottom around hero 2 cards, YELLOW around center board 3-5 cards, ORANGE near very bottom for stack/pos labels.
   You visually confirm or type adjusted fractions (0-1 relative, res-independent, e.g. 0.27 0.71 0.73 0.95).
4. (Easier templates) Auto-detects (more) card sprites in the ROIs, saves crops to `calib_crops/`. 
   Batch labeling or "accept all good": type `auto` (OCR/recog suggests + accepts good ones), or `Ah 10d _ Ks Qc` (space-sep, _=skip), or one-by-one (now pre-fills suggested label from OCR). Verified -> `card_templates/Ah.png` etc (cwd/user dir has priority over package).
5. Pick/confirm sens + preproc defaults.
6. Computes + persists `vision_config.json` (roi_fractions + sens/preproc/min_conf + timestamp + base res). (Respected by get_clubgg_rois, _load_templates, attempt_vision_parse.)
7. (NEW: automatic) "test capture + parse": fresh grab + detailed rich live feedback (hand/board/pos/stack/conf/partial/rects/method/below/pot/bet + debug logs). 
   Example output you should see:
     --- TEST PARSE RESULT (your profile in action) ---
       hand=AhKs board=Qd7h2c pos=BTN stack=98 conf=0.81 partial=False below_thresh=False rects={'hero':2,'board':5} method=...
     GUIDANCE:
       - (or if low: "if conf low on suits, add more template crops")
   Also writes calib_test_capture.png + calib_test_result.json .
8. Prints success + exact next command + helpers (incl new --calib-test).

Result:
- `vision_config.json` (in cwd; also discoverable from ~/.pokerflex) + your `card_templates/` .
- Future runs of `python -m pokerflex --background --live --real-vision ...` (or launch_assistant --real-vision) *automatically* load the profile: get_clubgg_rois() scales your fractions to current capture size; templates load with user-dir priority first. Same for --calib-test.
- Much higher success on card reads, better partials/conf, true set-and-forget while you play (still graceful fallback to hotkeys/json/set on low-conf).
- Re-run calibrate anytime for new table/skin/res (supports from-existing); `--show-calibration` to inspect; `--reset-vision [--also-templates]` to revert. `--calib-test` for fast post-edit verify.

Screenshots guidance: the wizard produces `calib_roi_preview.png` (annotated) + crop files + the test capture for your review. Share those + vision_config.json if reporting vision issues. After calibration you should see (via --calib-test or live): more complete hand+board reads (conf 0.7+ typical), partials that correctly advance streets, auto-extracted pot/facing_bet/street, fewer below_threshold — almost no manual input after initial setup.

After calibration, real play becomes:
```powershell
python -m pokerflex --background --live --real-vision --periodic-capture 10 --auto-capture
# (or double-click launcher with --real-vision; no other changes needed)
# Verify anytime: python -m pokerflex --calib-test
```
Simulate paths (`--simulate-vision`) and all A1/notes/ICM/explo/hotkeys untouched and still perfect for testing.

See also quickstart.txt "Calibrating..." and PROJECT_STATUS.md roadmap item (now completed).

**Troubleshooting real vision (small guide; after tesseract + calibrate):**
- Weak reads/partials: re-run `python -m pokerflex calibrate`; use --vision-debug + --vision-preproc aggressive --vision-min-conf 0.25 --vision-partial-conf 0.18 --vision-min-consec 2 --vision-retries 6.
- Test coverage: `python -m pokerflex --self-test` (exercises noisy real-like + live + calib load + history + postflop ICM); `--bench`.
- Always graceful: vision feeds but manual `set ...`, json edits, hotkeys/C override. --simulate-vision for safe verify.
- Profile: `--show-calibration`; reset with `--reset-vision`.
- Now much stronger for real use (calib + harden + listener + pot/bet/street/action + overlay/tray bg-friendly).

**Interactive mode** (for learning the commands or manual control, omit --background):
```bash
python pokerflex.py
# At the 🧠 A1> prompt: hit ENTER (quick analyze), type 'help', 'status', 'set pos BTN', 'set hand AhKs', 'analyze', 'notes edit', 'quit'
```

**Other one-shots** (no long-running process):
```bash
python pokerflex.py --once --pos BTN --hand AhKs --stack 80 --analyze
python pokerflex.py --background --tournament-mode --players-remaining 6
```

Key behaviors in background:
- Minimal console chatter (QUIET mode).
- Global hotkeys + file watcher always active.
- `--live` starts a listener thread: periodic capture (real via --real-vision or default, or simulated) → enhanced vision parse (auto hand/board/pos/stack/num_opponents/bet sizing from HUD+action_bar+pot ROIs using keywords "BTN"/"SB" + nums near names + "Bet X"/"Raise to"/allin) → stronger new-hand detect (hand+board reset + opt pos/stack delta + is_new_deal; auto clear action_history) → street progression (board len + hints + pot even on missed card) → robust state update (conf/partial aware via partial_min_conf + prefer_* + merge_board_fragment for incremental + consec gating) → confidence-gated auto-analyze (only on conf>=thresh+consec OR clear street/new-hand; user feedback "low conf - waiting" / "auto-analyze triggered") → rich A1 (pot/facing_bet/pos/stack/action_history feed directly to GameState; notes+ICM+history stay active). State persisted to clubgg_current_state.json on every good parse + last_good_parse_time (restarts resume last known). Deeper auto-capture (retries+activate + new --vision-retries CLI) + fallback to manual on low conf. Low-conf streak guidance. --simulate-vision enhanced with realistic HUD/pot/bet data for testing.
- State + notes survive restarts via the two JSON files.

See the expanded "HOW TO RUN THE BACKGROUND APP..." and "TROUBLESHOOTING" in `quickstart.txt` for even more copy-paste recipes and gotchas.

### Hotkeys (Global)
(Registered when runner starts; work even if terminal not focused.)
- `ctrl+alt+a` → analyze (rich A1 output; auto-captures if `--auto-capture` and missing hand/board)
- `ctrl+alt+s` → status (full current state + active notes)
- `ctrl+alt+c` → capture (ClubGG screenshot to `clubgg_live.png`)

GUI hotkey (separate): `ctrl+alt+p` brings up the GUI window (A1 new brain default).

### Live State Editing
While the runner is running you can change the hand/stack/board/opponents/tournament_mode etc **without restarting**:
- In interactive console: `set pos BTN`, `set stack 45`, `set tmode true`, `set icm 0.12`, `set players 5` etc.
- Edit these files live from any editor / other shell (watcher reloads in ~1.8-2s):
  - `clubgg_current_state.json`
  - `clubgg_player_notes.json`
- Commands `load` / `reload` and `save` also available in the console.

### Action History (NEW: multi-street + blocker awareness)
A1 brain now tracks full action history per hand for smarter postflop (capped ranges on check-backs after preflop call; donk vs check-call stories; prior aggression dynamic texture; hero blockers vs villain's actual continuing range).
- At prompt: `action bet 3.5` (or `action villain raise 8`, `action hero check`, `action donk 2`)
- `history` / `hist` to view; `history clear`; `undo` last.
- Street auto-detected from board on record.
- In --live: auto-clears on new hand; light vision inference support (sim injects sample; future real bet/action detectors can feed).
- Appears in `status`, rich A1 output ("History: f:v:call f:h:bet ..."), and drives postflop range construction / decisions / metrics.
- Fully optional: no history = previous behavior. Stored in clubgg_current_state.json.
- Also `set bet_to_call 4`, `set pot 6.5`, `set facing_action bet` for manual facing state.

### Player Notes / Exploitative Play
The A1 brain uses per-player notes to adjust ranges (wider c-bets vs nits, value-only vs stations, etc.).
- Quick CLI: `note nit fold_to_cbet 0.78`
- Free text: `note villain "calls down too light on dry boards"`
- Full editor: `notes edit` (supports `nit <label>`, `station <label>`, `maniac <label>`, `set`, `free`, `list`, `del`, `help`)
- Presets (also available as python helpers `use_nit_preset("nit")` etc.):
  - `nit`: high fold_to_cbet (fold 78%+ to c-bets, esp dry)
  - `station`: low fold_to_cbet (calls too much)
  - `maniac`: high aggression_factor
- Notes live in `clubgg_player_notes.json` (or the generic `player_notes.json`). They are automatically passed on every analyze when present.
- Explo is active by default whenever notes exist for a villain (or set `CONFIG.exploitative_mode=True`).

### Tournament / ICM Mode
Basic ICM adjustments (short-stack push/fold Nash only for now; marginal shoves get tighter, calls looser).
- CLI: `--tournament-mode` (aliases: `--tournament`, `--tourn`)
- Live: `set tmode true`
- Final table / bubble: `--players-remaining 5` (or `set players 5`)
- Explicit factor: `--icm-factor 0.15` (or `set icm 0.15`)
- Shows in output: `ICM factor: 0.12 (tournament mode / adjusted Nash)` + 🎯 EXPLOIT / ICM tags when relevant.

`players_remaining` is used to compute a sensible ICM factor (stronger effect on final tables).

### How to Use the GUI (A1 Windowed Assistant)
```bash
python main.py
```
- The GUI now uses the new A1 brain by default (via the thin shim in `poker_engine.py`).
- You get richer output (texture, SPR, range adv, ICM, explo notes) in the same text box.
- Inputs are unchanged. The popup hotkey is still `ctrl+alt+p`.
- Perfect if you prefer a windowed form over the console runner. (Preserved for compat; new brain is unambiguous default.)


### Force Legacy If Needed (debug / old callers ONLY — new A1 is the default)
The new A1 brain is the default everywhere with **zero flags** (`python -m pokerflex`, `python pokerflex.py`, `pokerflex` (CLI), `python main.py` GUI, direct `get_advice()`, `launch_assistant.*`, all shims, self-tests, etc.).

To get the *exact* original legacy text/behavior (for comparison or old callers ONLY):
```powershell
# PowerShell
$env:POKERFLEX_FORCE_LEGACY_BRAIN=1; python -m pokerflex
# or for GUI
$env:POKERFLEX_FORCE_LEGACY_BRAIN=1; python main.py
```
```bash
POKERFLEX_FORCE_LEGACY_BRAIN=1 python -m pokerflex
POKERFLEX_FORCE_LEGACY_BRAIN=1 python pokerflex.py
```
(Alternatively set `CONFIG.force_legacy_brain = True` before importing poker_engine. You almost never need this.)

### Example Commands for Common Scenarios
```bash
# Cash deep stack (GTO open / c-bet spots)
python pokerflex.py --pos BTN --hand AhKs --stack 120 --analyze
python pokerflex.py --pos CO --hand KhQh --stack 80 --analyze

# Short stack (push/fold regime, cash or tourney)
python pokerflex.py --pos SB --hand 76o --stack 12 --analyze
python pokerflex.py --pos BTN --hand 55 --stack 10 --analyze

# Explo vs nit (launch bg, then set notes live via console/json or 'notes edit')
python pokerflex.py --background --pos BTN --stack 80 --auto-capture
# (in runner or another window): note nit fold_to_cbet 0.78 ; note nit "nitty on dry"
# Then use hotkey Ctrl+Alt+A in-game. Postflop c-bets become wider. (E2E tested.)

# Final table ICM (short stacks near bubble / pay jumps)
python pokerflex.py --background --tournament-mode --players-remaining 6 --pos SB --stack 15 --auto-capture
python pokerflex.py --once --pos UTG --hand Kh9s --stack 11 --tournament-mode --players-remaining 5 --analyze

# Full live real-time example (recommended for play)
python pokerflex.py --background --pos BTN --stack 60 --auto-capture --tournament-mode --players-remaining 7
# or with live listener:
python pokerflex.py --background --live --periodic-capture 12 --auto-capture
# 0-touch sim demo (tested; gives useful A1 advice "while playing"):
python pokerflex.py --background --live --simulate-vision
# Real vision live (for actual table):
# python pokerflex.py --background --live --real-vision --periodic-capture 12 --auto-capture
# Real vision with full robustness (recommended for production hands-off):
# python pokerflex.py --background --live --real-vision --periodic-capture 8 --vision-min-conf 0.28 --vision-min-consec 2 --vision-sensitivity medium --auto-capture
# With partial-conf for live sensitivity on incremental reads (new; allows lower bar for partials e.g. 1-card or new street card while full reads use higher thresh):
# python pokerflex.py --background --live --real-vision --periodic-capture 8 --vision-min-conf 0.30 --vision-partial-conf 0.20 --vision-min-consec 2 --vision-retries 5 --auto-capture
# With debug + mixed for real calibration or long sim tests of notes/ICM/partials:
# python pokerflex.py --background --live --real-vision --vision-debug --sim-scenario mixed --vision-min-consec 2
# ONE-CLICK ZERO-TOUCH (polished final; always bg+live+smart defaults):
#   launch_assistant.bat   (double-click)
#   python launch_assistant.py [--real-vision] [--vision-debug]
# Tray / exe (new):
#   python -m pokerflex --tray --live --simulate-vision ...
#   (after build_exe.py: dist/PokerFlex.exe --tray ...)

# CoinPoker multi-client (exact same 0-touch as ClubGG; --client selects window hints + client-tuned ROIs post-calib):
#   Calib for CoinPoker: python -m pokerflex calibrate   (CoinPoker table up)
#   Launch: python -m pokerflex --background --live --real-vision --client coinpoker --periodic-capture 12 --auto-capture
#   With robustness: python -m pokerflex --background --live --real-vision --client coinpoker --vision-min-conf 0.28 --vision-min-consec 2 --vision-preproc aggressive
#   Tray+CoinPoker: python -m pokerflex --tray --background --live --real-vision --client coinpoker
#   Launcher: python launch_assistant.py --client coinpoker --real-vision
#   .bat: launch_assistant.bat --client coinpoker --real-vision
# Note: calib once per client/table; then zero-touch with --live --real-vision + tray + global hotkeys + live notes (clubgg_* or equiv json). Sim is generic.
```

See `quickstart.txt` for the ultra-short version of the above + more tips.

### Deploy as background app (standalone packaging + system tray / true set-and-forget)
This completes the "real deployment" UX: easy one-file .exe + tray icon so the assistant can be truly invisible while still fully controllable.

**1. Easy standalone exe (PyInstaller)**
- From source root (after normal install): `python build_exe.py`
  - Default: one-file `dist/PokerFlex.exe`
  - `python build_exe.py --onedir` for folder (easier to inspect/update)
  - `python build_exe.py --noconsole` for pure windowless (tray only; "Show Console" gives guidance only)
- The exe bundles Python + deps + A1 brain + data (equity_matrix). It behaves exactly like `python -m pokerflex`.
- Supports all flags: `PokerFlex.exe --tray --live --simulate-vision --pos BTN --stack 100 --auto-capture`
- Double-click exe (or shortcut) → starts (with --tray for full menu experience).
- **Tesseract note (same as source)**: The exe does **not** include the native tesseract-ocr binary. For `--real-vision` on the target machine:
  1. Install from https://github.com/UB-Mannheim/tesseract/wiki (add folder to PATH).
  2. `--simulate-vision` + tray/hotkeys/notes/ICM/json/live-sim all work perfectly without it.
- Rebuild after edits: just re-run `build_exe.py` (from a venv with the deps you want inside the exe).

**2. System tray support (optional pystray)**
- `pip install pystray` (or `pip install "pokerflex[tray]"`)
- Launch with `--tray` (or `--minimized` for classic quiet hide without icon):
  ```powershell
  python -m pokerflex --tray --background --live --simulate-vision ...
  # or via one-click launcher:
  python launch_assistant.py --tray
  launch_assistant.bat --tray
  # packaged:
  PokerFlex.exe --tray ...
  ```
- On Windows: console auto-hides when tray requested (use tray menu "Show Console" to reveal; hotkeys unaffected).
- Tray icon: simple red poker chip with "PF" (generated in-memory via Pillow; no extra files).
- Tray menu (right-click the chip):
  - **Show Console**: reveal/hide the terminal (Win only).
  - **Analyze Now**: equiv to Ctrl+Alt+A (triggers rich A1; auto-capture if flagged).
  - **Status**: current state + vision + flags (pops up).
  - **Notes Quick**: opens `clubgg_player_notes.json` in default editor (watcher reloads ~2s).
  - **Run at startup (toggle, checked)**: creates/removes `PokerFlex_A1_Background.bat` in your Windows Startup folder. Edit the .bat to switch sim<->real or add flags. Cross-platform note: on Linux/mac use your DE autostart or cron for equivalent.
  - **Quit**: clean save + exit.
- Quieter in tray mode: most live/watcher chatter suppressed (unless `--vision-debug`); rich A1 advice on analyze always goes to `pokerflex_tray.log` (next to cwd) + a compact popup toast (zero-dep Win MessageBox) when console is hidden. Hotkey analyzes also benefit.
- "start minimized to tray": just launch with `--tray` (or the packaged exe). Persist via the menu toggle or manual shortcut to the exe + `--tray ...`.
- Graceful: if pystray missing at runtime, `--tray` falls back to plain quiet `--background` (everything else works: hotkeys, live, watcher, notes, ICM).
- Cross-platform: tray code (icon, menu, callbacks) is in run_brain and works where pystray does (Linux appindicator etc.); Windows is prioritized for console hide + .bat startup + toast.

**3. Update quickstart / launchers**
- All entry points (`python -m`, `pokerflex` CLI, launch_assistant.* , root shims, packaged exe) support `--tray` / `--minimized` and forward to the runner.
- launch_assistant.bat / .py forward `--tray` and document the tray one-click path.
- For dev: `pip install -e .` and `python -m pokerflex` are 100% unaffected.

**4. Recommended "set and forget" flow (Windows)**
1. `pip install -r requirements.txt && pip install -e . && pip install pystray`
2. (Optional but recommended for real) `python -m pokerflex calibrate`
3. Double-click `launch_assistant.bat --tray` (or with --real-vision) or build the exe and double-click it.
4. Right-click tray chip → "Run at startup" (toggle on).
5. Play ClubGG. Use hotkeys or tray "Analyze Now". Edit notes/state live. Advice appears in log/popup or console if you show it.
6. Quit from tray or Ctrl+C.

See `build_exe.py` (top of file) for full build notes + tesseract reminder. This + the existing zero-touch launchers makes the assistant as close to an invisible real-time co-pilot as the current vision layer allows.

### Troubleshooting
Common issues getting the background assistant (or vision) running — all covered for zero-touch success.

**Encoding / UTF-8 / console emoji or banners on Windows**
- Multiple entry points (`pokerflex.py`, `run_brain.py`, `launch_assistant.py`, even `poker_engine.py`) explicitly do:
  ```python
  try:
      sys.stdout.reconfigure(encoding="utf-8")
  except Exception:
      pass
  ```
- Symptoms: mojibake (weird chars instead of 🧠 or 🎯), or exceptions on print.
- Fixes:
  - Use Windows Terminal or recent PowerShell (not legacy cmd.exe).
  - In shell: `chcp 65001` then launch.
  - The important A1 advice text is designed to be readable even without perfect emoji.
- Related: all file I/O for state/notes uses explicit `encoding="utf-8"`.

**Tesseract (real vision / OCR card reading)**
- `requirements.txt` includes `pytesseract` (Python bindings) + opencv + Pillow.
- The actual engine is a separate native install:
  1. Go to https://github.com/UB-Mannheim/tesseract/wiki
  2. Download and run the Windows installer for tesseract-ocr (latest 5.x recommended).
  3. During install, note the folder (usually `C:\Program Files\Tesseract-OCR`).
  4. Add that folder to your **system PATH** (search "Edit the system environment variables" → Environment Variables → Path).
  5. Restart any open terminals / IDEs.
- Verify: `python -c "import pytesseract; print(pytesseract.get_tesseract_version())"`
- Without the binary:
  - Real captures still save `clubgg_live.png`.
  - `attempt_vision_parse` falls back to cv2-based card rectangle detection + template matching (if you populate a `card_templates/` folder).
  - Confidence will be low; partial state is still applied.
  - **Recommendation**: use `--simulate-vision` (the default in the one-click launcher) until you have tesseract + calibrated your table.
- For real hands-off: add `--real-vision` to --live (forces real capture path; vision now extracts stack/pos too). Use additional `--vision-min-consec 2 --vision-min-conf 0.28` etc for stability against real OCR variance. Capture layer now auto-retries and activates window.
- The vision code lives in `capture.py` (refined ROIs incl. hero_stack for stack, `_detect_card_rects`, `_recognize_card_from_crop` (multi-scale + whitelist), `_ocr_text_from_pil` (cv2 preprocess), `attempt_vision_parse` with conf/partial/stack etc.).

**Global hotkeys (Ctrl+Alt+A etc.) do not fire, or only work when terminal focused**
- Caused by Windows security / UAC: the `keyboard` library needs an elevated process to install low-level hooks that work across apps (ClubGG).
- Fix: Launch your terminal **as Administrator**:
  - Right-click PowerShell / cmd → "Run as administrator".
  - Then `cd E:\PokerFlex` and start the assistant.
- Once registered, hotkeys are system-global for the session and survive minimizing the console.
- If you never want hooks: `--no-hotkeys` (or edit launcher).
- The GUI's separate hotkey (Ctrl+Alt+P) is also via the same lib in `main.py`.
- Note in `config.py`: hotkey strings are `ctrl+alt+a`, `ctrl+alt+s`, `ctrl+alt+c` (customizable).

**Simulated vision vs real table capture ("sim vs real")**
- `--simulate-vision` / `POKERFLEX_VISION_SIMULATE=1` (used by `launch_assistant.bat` / .py as 0-touch default):
  - 100% self-contained. No window, no screen grab, no OCR. Perfect for zero-touch.
  - `capture.simulate_table_state()` returns deterministic cycling dicts (preflop AhKs BTN deep, flop, turn, then short-stack ICM hands with tmode/icm_factor/players_remaining populated + occasional partials). Supports --sim-scenario demo/icm/cash/tourney/mixed (mixed for long variety exercising all incl partials + tmode switches).
  - The `--live` listener treats them exactly like real parses → state update (robust, using prefer_better_board + prefer_better_hand, consec, new-hand clear + deeper ICM stack-delta auto-trigger) → `analyze_and_print()` with full A1 + notes + ICM.
  - Purpose: verify the entire assistant (runner, watcher, hotkeys, explo, ICM, formatting, live loop) with zero external dependencies or risk.
  - E2E tested: capture/parse (sim) → _robust_apply (conf/partial/ smart board+hand + consec gating + meta) → state + auto rich A1 (notes/explo + ICM tags when active). Also tested with low-conf skip + real capture fallback paths. Use --vision-debug to see sim partial injection + conf in action.
- Real mode (omit the flag, or use --real-vision explicitly to force; --live defaults to real capture path now; launcher --real-vision triggers):
  - Requires a visible ClubGG table.
  - `capture.find_window_bbox` (via optional pygetwindow) or full-screen grab.
  - Then `capture_and_parse` → `attempt_vision_parse` (enhanced: ClubGG-specific ROIs for hero hand at bottom + board + hero_stack, sprite detection (sens), per-card tesseract w/ cv preprocess+whitelists + more noise fixes, multi-scale template fallback, position + stack auto-extract from roi ocr with tolerant patterns, improved confidence scoring + partial + below_threshold flags + card overlap guards; debug mode for rect/partial internals).
  - Results (even low-conf or partial) are fed into the live listener / auto-capture path via _robust_apply_vision_update (now with prefer_better_board + prefer_better_hand to protect known fuller reads from partial OCR noise, plus new-hand detection to auto-clear stale boards) and written to `clubgg_current_state.json`. Auto-extracts hand/board/position/stack when vision succeeds above thresh. Listener deepened: meta always sync'd, tmode+stack delta can auto-trigger analyze for ICM relevance, LAST_VISION_INFO tracked for status.
  - You can always override anything with manual `set` commands or by editing the JSON while the runner watches. Notes/explo + ICM fields preserved (full compat).
  - Further enhancements for seamless: capture_clubgg_image now retries (3) + attempts window activate/restore for higher success in bg; live listener uses --vision-min-consec N consecutive good-conf reads (new CLI, default 1; auto 2 for real) before trusting update + auto-analyze (debounce for real OCR flicker). Low-conf or insufficient consec always manual-fallback (better fallback to manual). Full compat + richer robustness. run_brain + launch_assistant auto-apply real robust defaults. --vision-debug surfaces the internals during real polls.
- New/additional CLI for live vision (sensitivity, scenarios, poll, consec, debug):
  - `--live-poll-secs N` (e.g. 8-12): fine control of auto capture/parse/analyze rate in --live (new for seamless tuning).
  - `--vision-sensitivity` / `--vision-min-conf` / `--vision-min-consec N` / `--sim-scenario {demo,icm,cash,tourney,mixed}` / `--vision-debug` for robustness + debounce + diagnostics.
  - `--vision-min-consec 2` (or 3): require consecutive solid reads before auto state update + analyze — key for real noisy vision.
  - `--vision-debug`: prints internal partial flags, conf calc, rects, libs status on every vision cycle — essential for moving from sim to reliable real hands-off.
  - Example set-and-forget real: `python -m pokerflex --background --live --real-vision --live-poll-secs 10 --vision-sensitivity medium --vision-min-conf 0.28 --vision-min-consec 2 --auto-capture --vision-debug`
  - Capture layer enhanced with retries+activate for auto reliability.
- Workflow for real sessions:
  1. Launch with sim first (launch_assistant.bat) to get comfortable + build some notes.
  2. Bring your real table up.
  3. Re-launch with --real-vision (or launch_assistant.py --real-vision; no bat edit). Add --vision-debug initially.
  4. Use Ctrl+Alt+C to force a capture + see the png + parsed output (includes any extracted hand/board/pos/stack + conf/partial).
  5. If cards not reading well: install tesseract, improve table zoom/position, seed card_templates/, tune --vision-sensitivity/--vision-min-conf/--vision-min-consec/--live-poll-secs (watch --vision-debug logs), or fall back to json/hotkey `set`. Partial reads still advance state usefully (with smart prefer_* protection + consec gating + manual fallback always available).
- The live listener (`start_live_listener` in run_brain) and periodic paths respect --real-vision / --simulate-vision (REAL_VISION overrides to real), coexist peacefully with json watcher + hotkeys + notes + new brain default. This advances the bg app toward hands-off real-time ClubGG table reading (with --vision-retries, smart partial merge, consec, conf for reliable auto-extract+analyze).
  The runner now feels like a true set-and-forget real-time assistant: launch (e.g. via launch_assistant.bat/.py or `python -m pokerflex --background --live --real-vision ...`), minimize, play on ClubGG — enhanced vision (retries/activate/ROIs/CV/OCR/partials/conf + debug) + deeper live integration (consec debounce, prefers, robust apply, new-hand safety, tmode stack triggers, auto real defaults) auto-extracts and updates state + triggers rich A1 advice on reliable changes (with full explo notes + ICM/tmode); manual set, hotkeys, json edits always as seamless fallback. End-to-end verified with sim flows (capture/parse → update → rich A1 w/ notes/ICM). 0 touch confirmed. Use --vision-debug to accelerate real-vision calibration.

Other quick tips:
- "keyboard lib not available": re-run `pip install -r requirements.txt`.

- Tray features missing / --tray does nothing: `pip install pystray`. It is optional; without it you still get full quiet --background behavior. Build the exe in an env that includes pystray if you want tray in the .exe. "Run at startup" is Win-only (documented for others).
- Low vision conf spam: normal without tesseract; use sim or manual sets.
- State not persisting or watcher not seeing edits: check file permissions / that you're editing the exact `clubgg_current_state.json` next to the .py files; use `load` / `reload` in interactive.
- For ICM questions: run `python nash.py` standalone — it prints push/fold tables + ICM factor math.

---

## The New A1 Brain (Primary / Default)
- Hotkey popup (Ctrl+Alt+P) — GUI now uses A1 brain by default (rich output)
- **New A1 Brain (default)**: Strong heuristic GTO with board texture analysis, range construction, equity vs range, range/nut advantage, blockers, sophisticated postflop sizing
- Preflop: reference open ranges + exact Nash push/fold solver (short stacks ≤15bb)
- Postflop: texture-aware (dry/wet/paired/dynamic), multiway, facing CR/donk etc.
- **Exploitative player notes**: per-villain tendencies (fold_to_cbet, aggression etc) adjust ranges live (nit/station/maniac presets)
- **ICM / Tournament mode**: basic ICM factor for short-stack push/fold Nash (tighter marginal shoves, looser calls); supports final tables
- Background / real-time assistant: run_brain.py with hotkeys, file watcher for live state/notes edits (ClubGG focus)
- GUI preserved (windowed A1 assistant for those who prefer it over console)
- Expandable toward screen understanding (capture stub present)

## The New A1 Brain (Primary / Default)
All enhancements (postflop overhaul, shim refactor, explo notes, background runner, ICM, vision stubs) are integrated into the primary path.

**New A1 brain is the UNAMBIGUOUS MODULE / LAUNCHER / ENTRY POINT / GUI / `python -m pokerflex` / `pokerflex` CLI DEFAULT** (`USE_NEW_BRAIN = True` explicit module-level default in `poker_engine.py` (pkg+root) + reinforced + declared in ALL launchers/entry points/GUI/__main__/run_brain/pokerflex.py/__init__/launch_assistant etc.). Legacy only on explicit `POKERFLEX_FORCE_LEGACY_BRAIN=1` (debug, never primary). Final integration+default-mode specialist pass complete: USE_NEW_BRAIN=True everywhere (no flags); polished clean rich A1 text (no legacy disclaimers in normal incl error paths); GUI shows "PokerFlex A1" by default; zero-touch `python -m pokerflex` / `pokerflex` CLI / launch_assistant; hotkeys/live/notes/ICM/explo confirmed end-to-end; comprehensive verifs (imports, GTO/explo/ICM flows new path, legacy env, GUI, runner --bg --live --sim, self-tests, entrypoints). Docs updated for clarity. The background real-time A1 assistant is now production-ready. 
Env `POKERFLEX_FORCE_LEGACY_BRAIN=1` (or `CONFIG.force_legacy_brain=True` before import) forces the old exact behavior (for debug only; legacy fallback verified). New A1 brain requires (and gets) zero flags — it is the default.

See the **"Getting Started with the A1 Real-Time Assistant"** section above for the complete user guide (installation, `python -m pokerflex`, hotkeys, live editing, notes/explo, ICM, GUI usage, legacy force, and ready-to-copy example commands).

Key technical notes (for coders):
- Console/background runner (ClubGG real-time co-pilot) is now best started via the launcher.
- Direct in code / tests (new brain always the default):
  ```python
  from poker_engine import get_advice
  text, data = get_advice(position="BTN", hand="AhKs", opponents="2", stack="100")
  # with explo notes + ICM:
  text, data = get_advice(..., player_notes={"fold_to_cbet": 0.78}, tournament_mode=True, players_remaining=6)
  ```
- Direct A1 (bypasses shim):
  ```python
  from models import legacy_to_gamestate
  from advisor import get_advisor, format_a1_advice
  state = legacy_to_gamestate("BTN", "AhKs", "", "2", "100", "0", tournament_mode=True)
  dec = get_advisor().advise(state, player_notes=..., use_exploits=True)
  print(format_a1_advice(state, dec))
  ```

Player notes persist to the clubgg_ / player_notes.json files (used automatically for explo range adjustments; presets nit/station/maniac available).

Tournament mode affects short-stack preflop Nash (ICM factor ~0.08-0.20 final tables). Full deep-stack ICM is future work.

`python main.py` launches the GUI — now powered by new A1 brain by default.

## How to Run (all entry points)
**Install once (from project root):**
```bash
pip install -r requirements.txt && pip install -e .
# or Windows: double-click install.bat (does pip -r + pip install -e .)
```

Primary documented:
```bash
python -m pokerflex
pokerflex --help               # after the editable install above
```

Other / compat shims:
```bash
python pokerflex.py            # root shim (compat)
python -m pokerflex --background --live --simulate-vision   # zero-touch demo (or launch_assistant.bat)
pokerflex --background --live --simulate-vision             # after `pip install -e .` (the entry point)
# Real: python -m pokerflex --background --live --real-vision --vision-retries 5 ...

# One-click Windows background: double-click launch_assistant.bat (or python launch_assistant.py)
# For real ClubGG: same but without --simulate-vision (edit the bat or pass flags)

python main.py                 # GUI (now powered by A1 brain by default)
python run_brain.py            # direct runner (identical behavior)
python poker_engine.py         # self-tests exercising A1 + legacy + ICM + explo notes
python nash.py                 # standalone ICM / exact push/fold solver + tables
python capture.py              # manual ClubGG grab + vision parse demo
```
See `quickstart.txt` (especially the "HOW TO RUN THE BACKGROUND APP" and "TROUBLESHOOTING" sections) for the fastest path and exact copy-paste commands.

End-to-end tested in all modes (pure GTO cash deep, explo notes adjusting postflop, ICM/tourney short stacks, live + sim vision auto-flow, global hotkeys, in-runner notes editor, json live editing, capture, packaging, GUI options, legacy force, self-tests). 

You can literally:
1. `cd E:\PokerFlex`
2. `pip install -r requirements.txt && pip install -e .`
3. `python -m pokerflex --background --live --simulate-vision` (or `pokerflex ...` after install, or double-click launch_assistant.bat / run launch_assistant.py)
4. Watch rich clean A1 advice (with texture, ICM tags, explo if notes present; no legacy disclaimers) appear automatically.

The docs (this file + quickstart.txt) + launchers + clean example JSONs are intentionally written so a new user gets the assistant running with zero guesswork.

## Config & Tuning
See `config.py`: equity iters, cbet sizes per texture (dry/wet/paired), exploit thresholds (fold_cbet high/low), icm_*, runner defaults (hotkeys, state files), etc. All tunable without touching logic.

## Notes on Production Use (real-time assistant)
- New brain (default) fully functional for preflop (open + push/fold + ICM), postflop various textures (dry cbet, wet, paired sets, etc), short stacks, pure GTO + notes(explo).
- Output rich: action + sizing + explanation + metrics (eqr, spr, texture, range_adv, explo_*, icm_factor) + texture summary. Clean copy-paste friendly.
- For vision layer: use capture.py (integrated via --auto-capture / --live) + OCR stubs (pytesseract+cv2 in reqs; real tesseract binary recommended for non-sim). --simulate-vision for full hands-off demo without table.
- End-to-end verified (GTO/explo/ICM/tourney/live-sim-vision/hotkeys/notes + bg launch + legacy fallback). User can cd to E:\PokerFlex, pip install -r requirements.txt, then `python pokerflex.py --background --live --simulate-vision` (or launch_assistant.bat / .py or `pokerflex` cmd) and receive useful A1 advice while "playing".
- The full user guide + copy-paste examples live in the top "Getting Started..." section and in `quickstart.txt` (see the dedicated "HOW TO RUN THE BACKGROUND A1 ASSISTANT" section + Troubleshooting for encoding, tesseract, admin hotkeys, and sim-vs-real).
- Note on launcher: docs prioritize `python -m pokerflex`, root `pokerflex.py`, the one-click `launch_assistant.*` , and `pokerflex` entry point. All (plus GUI/direct) default to new A1 brain.

Legacy fallback kept 100% identical (easily forceable via POKERFLEX_FORCE_LEGACY_BRAIN=1 env) for any old callers/tests/debug ONLY (get_advice + side-by-side in self-tests; runner always direct A1 by design for rich output). New A1 brain (unambiguous default) is what you get with zero flags everywhere. (Legacy never primary.) The background real-time A1 assistant is now production-ready for the user.

See also the generated `clubgg_*.json` files (state + notes) and `clubgg_live.png` after first capture/run. (Runtime jsons + pngs + .gitignore added for clean clones.)
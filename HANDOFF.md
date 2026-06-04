# PokerFlex — Post Go-Dark Handoff / "What's Left" Summary

**Date**: 2026-06 (resume after interruption)  
**Status**: Core product **production-ready and shipped** (A1 brain + real-time bg assistant + multi-client ClubGG/CoinPoker + calib + tray/overlay + voice + leaks/review + history + notes/explo + ICM + packaging + launchers + docs + verifs). GitHub: https://github.com/zedazenigodx-tech/PokerFlex . All self-tests + bench green. A1 is UNAMBIGUOUS default (USE_NEW_BRAIN=True enforced everywhere; legacy only via explicit env for debug).

**Last verified on resume**: `python -m pokerflex --self-test` (exit 0, full E2E incl noisy vision, history, postflop ICM, calib paths, voice parser, leaks) + git clean.

This document is the concise handoff artifact (for Claude or any future agent/dev) of remaining scope. Prior phases delivered the 0-touch killer app; these are explicit nice-to-haves / deeper expansions.

---

## Core Is Complete — What You Get Today (0-Touch)

- Strong heuristic A1 brain (preflop Nash push/fold + ICM short, postflop texture/range/nut/blockers/history-aware sizing + rich formatted advice).
- Explo notes (multi-villain, live presets nit/station/maniac + customs, preflop+postflop effect, rich `notes edit` sub-REPL + GUI table + CLI `note` + json watcher).
- ICM (short-stack + lightweight postflop adjustments + concrete `--payouts`, `icm-sim` helper).
- Background runner: hotkeys (ctrl+alt+a/s/c/o/v), json live edit (~2s watcher), `--live` + auto-analyze on changes, `--simulate-vision` / `--real-vision`, state+notes persist.
- Vision: full calib wizard (`python -m pokerflex calibrate`), client-aware (ClubGG + CoinPoker via `--client`), hardened partial/conf/consec/preproc/history/pot/bet/street/action inference. Post-calib: reliable set-and-forget for hero+board+some context.
- UX: one-click `launch_assistant.bat` / `.ps1` / `.py`, tray (pystray) + popups/toasts/overlay (always-on compact advice), `pokerflex` CLI + `python -m`, GUI, build_exe.py standalone.
- Verif: `--self-test` / `--bench`, full docs (readme + quickstart + PROJECT_STATUS + this + CHANGELOG).
- Zero engineering: cd, install once (or double-click install.bat), double-click launcher, (optional calib + tesseract for real vision), play with hotkeys or hands-off.

**Key entry points that must stay A1-primary** (reinforce on any change): `pokerflex/poker_engine.py`, `pokerflex/__main__.py`, `pokerflex/run_brain.py`, launchers, `main.py` (GUI), shims, direct `get_advice`.

---

## Prioritized Remaining Work (Nice-to-Haves)

Ranked by user-visible impact for "true invisible co-pilot" + feasibility. All build on the solid foundation (no breakage to A1 default, runner, notes, ICM, vision pipeline, tests).

### P1 — Richer Real Vision (Highest leverage for hands-off)
**Goal**: Move from "hero hand + board + partial context" to reliable villain info + bet sizing + positions/stacks without constant overrides.
- Deeper villain holdings (range inference from action history + board texture + observed actions; or simple card OCR for visible villain cards in some skins).
- More robust / complete bet-size + facing-action OCR + auto `action_history` population (already improved for facing_bet/pot/street; push further for raise sizes, multiple villains, pot updates on every street).
- Auto seat/pos + stack reads for all (currently hero-focused + some; enables auto notes keying e.g. "seat3_nit").
- **Why now**: Calib + capture layer + `attempt_vision_parse` + listener (`_robust_apply`, prefer_*, merge, history) are mature. Add per-ROI villain regions or action log inference.
- **Key files**:
  - `pokerflex/capture.py` (new ROIs for villains, enhanced bet/pot OCR regions, `_parse_action_text`, `_extract_villain_cards`, client-specific hints).
  - `pokerflex/models.py` (GameState: richer `villain_ranges` or observed cards dict, extend ActionEvent).
  - `pokerflex/run_brain.py` (feed new vision fields into state + auto `action ...` records; surface in status).
  - `pokerflex/advisor.py` + `postflop.py` (consume richer state for better range construction / blockers / history story).
  - `pokerflex/calibration.py` (extend wizard to label villain regions / sample more crops if needed).
- **Verification**: Extend `--self-test` noisy sim with villain data; `--calib-test`; manual real table after re-calib; `python -m pokerflex --background --live --real-vision --vision-debug`.
- **Effort**: Medium (vision is the variable part). Start with bet-size completeness + auto-action inference (big win for postflop).
- **Impact**: Transforms from "useful with occasional set/json" to near-zero-touch live.

### P2 — Full (or Much Deeper) ICM Solver
**Goal**: Beyond lightweight short-stack bubble factor + postflop adj.
- True ICM EV for deeper stacks / more complex payout structures (bubble, final 3-9 players, varying stack depths).
- Integrate into preflop Nash (already has some) + postflop decisions (fold equity, call thresholds, sizing) more aggressively.
- UI: live `icm-sim` already exists for short; expand to "what's my $EV for this range vs calling range given payouts/stacks".
- **Key files**:
  - `pokerflex/nash.py` (new `icm_ev` or `solve_icm_pushfold_full` or Monte-Carlo / DP for payouts; `get_postflop_icm_adjustments` enhancements; keep lightweight path for speed).
  - `pokerflex/advisor.py` + preflop/postflop (pass full icm context, adjust more params).
  - `pokerflex/run_brain.py` + models (expose `payouts` more, `icm-sim` richer output, persist in state json).
- **Verification**: Add deep ICM scenarios to `--self-test` / poker_engine self-tests; compare vs known ICM tables or simple sims; `icm-sim` extended.
- **Effort**: Medium-High (ICM math is subtle; start with 3-6 player exact for common final tables, fallback to factor for deep).
- **Impact**: Huge for tournament players (the current short-stack support already differentiates; full makes it pro-level).
- **Note**: Explicitly scoped out of go-dark as "full complex deep-stack ICM solver".

### P3 — Advanced Leak / Review + Session Persistence
**Goal**: Turn "basic leaks cmd" (already shipped) into a real review tool + cross-session value.
- Full hand history import/export (from logs or manual entry; auto from runner if logging actions taken).
- Persistent player profiles (beyond per-run notes json; e.g. ~/.pokerflex/profiles/ or db, aggregate stats over sessions).
- Advanced leak DB: tag spots (e.g. "missed cbet vs nit on dry"), EV loss estimates, trends ("your cbet freq vs station is 62% vs GTO 48%").
- Better `leaks` / `review` output (charts? simple ascii + suggestions; "replay hand" with A1 vs actual).
- **Key files**: `pokerflex/run_brain.py` (optional session log mode), `pokerflex/models.py` (PlayerProfile / LeakDB), new or extend `leaks` command, perhaps a simple `review.py` or in advisor.
- **Verification**: `--self-test` coverage for review paths; manual "leaks" after simulated bad plays.
- **Effort**: Medium (builds directly on existing `last_advice.txt`, action_history, notes, `leaks` cmd).
- **Impact**: Turns the assistant into a study/review coach, not just live advisor. High retention value.

### P4 — More Clients / Skins + Auto-Detect Polish
**Goal**: "Works out of the box for any poker client" (beyond current ClubGG + CoinPoker).
- Add 1-2 more popular (e.g. generic "generic" full-screen + common others; or specific like Ignition/others if titles known).
- Improve auto client detection (title + window class hints, fallback prompts).
- Per-client default vision profiles (ship some "good enough" without user calib, or easy "adopt common" ).
- **Key files**: `pokerflex/capture.py` (expand SUPPORTED_CLIENTS, hints, ROIs), calibration wizard, run_brain banner/status, docs/examples.
- **Verification**: New --client smoke in self-test; launch with unknown title falls back gracefully.
- **Effort**: Low-Medium per client (the abstraction is done).
- **Impact**: Broader user base; "just works" story.

### P5 — Packaging / Installer Polish + "True Set and Forget"
**Goal**: Lower the last 5% friction for non-dev users.
- Optional: Inno Setup / NSIS / simple .msi (or PyInstaller + installer script) that bundles tesseract note + PATH hint + desktop/startup shortcuts + sample .bat.
- Better first-run: auto-seed vision? or detect tesseract and offer calib prompt.
- "Run at startup" already in tray menu (edits Startup .bat); make it more robust + cross-platform.
- Exe icon / version info polish in build_exe.py.
- **Key files**: `build_exe.py`, new installer script or .iss, launch_assistant.*, docs install section, perhaps `pokerflex/__main__.py` first-run hooks.
- **Verification**: Fresh Windows machine (or VM) install flow; exe + tray double-click works; no python required for packaged.
- **Effort**: Medium (packaging is already viable; installer is the "production" last mile).
- **Impact**: Makes it feel like a real app, not "Python project you run".

### P6 — Richer Presentation / Always-Available Surfaces (Overlay already basic; go further)
**Goal**: Less console dependency.
- Enhance the floating overlay (already delivered as lightweight Tk always-on-top): make it prettier (customtkinter? themed), show more (SPR, key reason, explo tag, history mini), draggable + resizable + per-street collapse.
- Toast notifications on new advice (even without tray?).
- Optional HUD injection (hard, anti-cheat risk — scope carefully or as "study mode only").
- Web dashboard or simple local server for remote review (future).
- Voice output (TTS read the advice on hotkey/analyze).
- **Key files**: `pokerflex/overlay.py` (or in run_brain), new voice_tts, tray callbacks, perhaps a small `hud.py`.
- **Verification**: `--tray --overlay`, hotkey toggle, visual in real run.
- **Effort**: Low for polish on existing overlay; higher for TTS/injection.
- **Impact**: "Invisible co-pilot" feel — glance without alt-tab or console focus.

### Other / Lower Priority
- Hybrid solver hook (call external GTO solver like Pio or custom for exact spots on demand; cache results).
- Full persistent cross-session player DB + cloud sync (notes + leak stats).
- More preflop note dynamicism (currently good for postflop; expand open/3bet/push ranges from notes even more).
- Performance: more aggressive caching, optional GPU for equity if MC heavy, faster Nash for very wide multiway.
- Tests: dedicated vision integration tests (beyond sim), property-based for advisor, leak review goldens.
- Docs: video quickstart or animated GIFs of live flow.

---

## Handoff Guidelines for Any Agent (Critical — Preserve What Ships)

1. **A1 is never optional**: Every change must keep `USE_NEW_BRAIN=True` as module default + reinforced in **all** launchers/entrypoints/GUI/runner/shims/tests. Legacy only via `POKERFLEX_FORCE_LEGACY_BRAIN=1` (and never promoted). Run full import/launcher checks after edits.
2. **Always run verification after changes**:
   - `python -m pokerflex --self-test` (must exit 0; covers new paths).
   - `python -m pokerflex --bench` (no regression in hot paths).
   - Manual: launch_assistant flow, `notes edit`, live --real-vision (if table), `leaks`, voice cmds, `icm-sim`, tray.
   - For vision: `python -m pokerflex calibrate` (wizard smoke), `--calib-test`.
3. **Docs + CHANGELOG mandatory**: Update readme.md (top snapshot + examples), quickstart.txt (commands), PROJECT_STATUS.md (limitations/roadmap), CHANGELOG.md (under Unreleased), this HANDOFF if scope changes. Add copy-paste recipes.
4. **Multi-client & state files**: Respect --client (clubgg vs coinpoker vs future) for window/ROI/state json naming (poker_* generic fallback; client-prefixed primary). Calib per-client.
5. **No new heavy deps** without strong justification (current: numpy/opencv/pytesseract/keyboard/pygetwindow/pillow/customtkinter/pystray optional). Prefer stdlib + what's already pulled.
6. **Windows/PowerShell first** (user primary env): test .ps1, chcp/UTF8, admin hotkeys, tray, exe. Gitbash/cmd secondary.
7. **State is json + watcher**: Edits to *_current_state.json / *_player_notes.json must be live-reloaded. Persist on clean exit.
8. **Graceful degradation**: No tesseract/cv2 → still fully functional via hotkeys/json/sim. Low-conf vision never corrupts state (manual always wins).
9. **Edit existing patterns**: Prefer extending run_brain command parser, advisor formatters, capture helpers over new modules when possible.

---

## Quick Start for Next Agent Session

```powershell
cd E:\PokerFlex
# (or clone https://github.com/zedazenigodx-tech/PokerFlex )
pip install -r requirements.txt && pip install -e .
# Verify
python -m pokerflex --self-test
python -m pokerflex --bench
# One-click bg demo
.\launch_assistant.ps1   # or double-click .bat ; or python launch_assistant.py --tray
# Real vision path (after tesseract + calib)
python -m pokerflex calibrate
python -m pokerflex --background --live --real-vision --client coinpoker --periodic-capture 10 --auto-capture
```

To pick up: read this HANDOFF + PROJECT_STATUS.md (Current Limitations + Roadmap sections) + recent CHANGELOG entries + top of run_brain.py / capture.py / advisor.py.

**Suggested first task on resume**: P1 bet-size / auto-action completeness in vision + listener (immediate value for postflop users, leverages existing history/action code).

---

**End of handoff**. Product is solid; these extensions make it even better. All core "go dark" goals achieved. Resume from here with confidence — tests + A1 enforcement + docs discipline will keep quality high.

(Generated/updated on resume; prior swarm delivered voice + leaks + bet-vision + final verifs.)

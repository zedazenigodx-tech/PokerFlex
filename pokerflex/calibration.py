"""
PokerFlex Vision/OCR Calibration Wizard (A1 real-time ClubGG / CoinPoker assistant, 0-touch).

One-command zero-touch entry: `python -m pokerflex calibrate` (or `pokerflex calibrate`, or --calibrate flag).
Supports --client clubgg|coinpoker (or auto-detect from first sample window title).
Guides the user through a ~2 minute "set and forget" process for reliable hands-off real-vision use.
Full compat for ClubGG; new support for bringing CoinPoker table window for its ROIs/templates.

IMPROVED (vision-calib-polish): progress indicators (STEP X/Y), better step-by-step instructions,
multiple samples + pick-best or auto-suggest from cv2 (felt+cards heuristic) as ROI starting point,
easier template collection (more crops, batch labels like "Ah 10d _ Ks" or "auto" for accept-all-good with OCR-suggest,
pre-filled suggested labels), auto test capture+parse AFTER save (rich results + specific guidance e.g. "if conf low on suits, add more template crops"),
"re-calibrate from existing images" mode (reuses prior calib_sample*.png / clubgg_live.png etc, no re-grab).
Now stores "client" in vision_config.json; uses generalized capture for samples; post-calib test uses client; show status reports client.
Re-calib for specific client supported.

Flow (interactive console, cv2-assisted previews/crops where possible):
1. Instruct + offer re-calib-from-existing if prior samples present.
2. Capture (or reuse) multiple sample PNGs (uses generalized capture_clubgg_image + client).
3. Auto-suggest ROIs via cv2 felt/card detect on chosen sample as *starting point* (better than static); preview + confirm/adjust loop.
4. Auto-detect (more) card sprites, show crops, batch labeling or "auto" accept good OCR-suggested, or one-by-one with suggestions.
5. Choose/persist tuned defaults (sens, min_conf, preproc).
6. Persist full vision_config.json (roi_fractions + client + meta) in cwd (and loadable from ~/.pokerflex).
7. *Auto* "test capture + parse" (fresh, using client) + rich print + actionable guidance ("if conf low on suits...").
8. Success + exact command for --live --real-vision --client X (which now prefers the profile automatically).

After: live runner / capture.get_poker_rois (new generalized client-aware) / get_clubgg_rois (wrapper for compat) / _load_templates / attempt_vision_parse automatically use user's tuned values (higher reliability for skin/res).
vision_config + card_templates respected (user cwd > ~/.pokerflex > pkg). 
Simulate-vision, notes, ICM, A1 paths, existing partial logic 100% untouched. --calib-test CLI for quick verify.

Also provides helpers callable directly.
"""

import os
import sys
import time
import json
import glob  # stdlib, for re-calib-from-existing + fallback samples (no new deps)
from datetime import datetime

# Safe relative imports for package use (python -m pokerflex or direct)
# Note: imported capture helpers are now client-aware (support clubgg|coinpoker via param; generalized capture used for samples).
# get_clubgg_rois etc updated to generalized version accepting client= (for wizard calls via generate_* and direct test).
try:
    from .capture import (
        capture_clubgg_image,
        capture_calibration_samples,
        generate_roi_preview,
        generate_card_crops,
        save_card_template_from_crop,
        save_vision_config,
        load_vision_config,
        get_clubgg_rois,
        get_poker_rois,  # new generalized version (client-aware); get_clubgg_rois is compat wrapper around it
        attempt_vision_parse,
        set_vision_params,
        ensure_user_dirs,
        _normalize_card_token,
        suggest_auto_rois,
        suggest_label_for_crop,
        VISION_SENSITIVITY,
        VISION_PREPROC,
        VISION_DEBUG,
        DEFAULT_CLIENT,
        find_window_bbox,
    )
except Exception:
    # Fallback for direct script or shim runs
    from pokerflex.capture import (  # type: ignore
        capture_clubgg_image,
        capture_calibration_samples,
        generate_roi_preview,
        generate_card_crops,
        save_card_template_from_crop,
        save_vision_config,
        load_vision_config,
        get_clubgg_rois,
        get_poker_rois,  # new generalized version (client-aware); get_clubgg_rois is compat wrapper around it
        attempt_vision_parse,
        set_vision_params,
        ensure_user_dirs,
        _normalize_card_token,
        suggest_auto_rois,
        suggest_label_for_crop,
        VISION_SENSITIVITY,
        VISION_PREPROC,
        VISION_DEBUG,
        DEFAULT_CLIENT,
        find_window_bbox,
    )


def _safe_input(prompt: str, default: str = "") -> str:
    """Robust input that handles EOF / Ctrl+C / pipes gracefully in wizard."""
    try:
        val = input(prompt)
        return val.strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[calib] input cancelled, using default / aborting step.")
        return default
    except Exception:
        return default


def _parse_fractions_line(line: str, default4: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Parse '0.27 0.71 0.73 0.95' into 4-tuple of floats in [0,1] clamped, else default."""
    try:
        parts = [float(p) for p in line.replace(",", " ").split() if p.strip()]
        if len(parts) == 4:
            return tuple(max(0.0, min(1.0, p)) for p in parts)
    except Exception:
        pass
    return default4


def run_calibration_wizard(client: str | None = None) -> None:
    """Full guided interactive calibration flow. Zero-touch start, production UX.
    Now with progress, multiple samples, auto-ROI cv2 suggest, easier batch+auto templates,
    auto post-save test+guidance, and re-calibrate-from-existing-images mode.
    Supports explicit client or auto-detect from capture sample window title.
    """
    if client is None:
        client = DEFAULT_CLIENT
    client = str(client).lower()
    if client not in ("clubgg", "coinpoker"):
        client = DEFAULT_CLIENT
    cname = "CoinPoker" if client == "coinpoker" else "ClubGG"

    # Detect client from active window title using generalized find (if not explicitly set to non-default).
    # This allows `python -m pokerflex calibrate` to auto pick coinpoker if its window is frontmost.
    if client == DEFAULT_CLIENT:
        try:
            det = find_window_bbox(client=None)  # let it auto inside
            if det:
                if len(det) == 3:
                    _b, title, matched = det
                    if matched in ("clubgg", "coinpoker"):
                        client = matched
                        cname = "CoinPoker" if client == "coinpoker" else "ClubGG"
                        print(f"[calib-detect] Detected client '{client}' from window: {title}")
                elif len(det) == 2:
                    _b, title = det
                    # fallback heuristic if no matched returned
                    tlow = (title or "").lower()
                    if any(h in tlow for h in ("coinpoker", "coin poker")):
                        client = "coinpoker"
                        cname = "CoinPoker"
                        print(f"[calib-detect] Heuristic detected coinpoker from: {title}")
                    elif any(h in tlow for h in ("clubgg", "club")):
                        client = "clubgg"
                        cname = "ClubGG"
                        print(f"[calib-detect] Heuristic detected clubgg from: {title}")
        except Exception:
            pass  # no pygetwindow or no window; keep chosen/default

    print("=" * 64)
    print(" PokerFlex A1 — Vision/OCR Calibration Wizard  (STEP 1/8)")
    print(f"  For reliable hands-off {cname} use with --live --real-vision --client {client}")
    print("  ~2 minutes to set-and-forget per client/table. Uses your exact table res/skin/cards.")
    print("  (cv2-assisted previews + crops + auto-suggest; tesseract helps but not required for templates)")
    print("  Multi-client: calib once for your CoinPoker table (bring its window); full ClubGG compat.")
    print("  Client will be stored in vision_config.json and used for capture/test/parse.")
    print("=" * 64)
    print()

    # Step 0: check existing
    existing = load_vision_config(force_reload=True, client=client)  # client-aware load (supports per-client config files)
    if existing:
        prior_client = existing.get("client") or "unknown"
        print("Note: Existing calibration profile detected.")
        print(f"  (at {existing.get('calibrated_at', 'prior')}; client={prior_client})")
        ans = _safe_input("Overwrite with new calibration? [Y/n] ", "y").lower()
        if ans not in ("", "y", "yes"):
            print("Aborted (kept existing). Use --reset-vision to clear, or --show-calibration.")
            return
    print()

    # === NEW: re-calibrate from existing images mode (no new capture if user has prior grabs) ===
    # Look for prior calib samples or common captures in cwd (user friendly, no hard fs walk)
    existing_imgs = []
    for pat in ("calib_sample*.png", "clubgg_live*.png", "clubgg_capture*.png", "calib_test_capture.png"):
        existing_imgs.extend(glob.glob(pat))
    existing_imgs = sorted(set([p for p in existing_imgs if os.path.isfile(p)]), key=os.path.getmtime, reverse=True)[:6]
    use_existing = False
    primary_sample = None
    samples = []
    if existing_imgs:
        print("STEP 0b (re-calib mode): Found prior sample images:")
        for i, p in enumerate(existing_imgs, 1):
            print(f"  {i}. {p}  (mtime recent)")
        print("  (These can be re-used for ROI/templating without new screen grab — ideal for 're-calibrate from existing'.)")
        ans = _safe_input("Re-calibrate from existing images (skip fresh capture)? [y/N]: ", "n").lower()
        if ans in ("y", "yes"):
            use_existing = True
            # pick primary (default most recent)
            pick = _safe_input(f"  Use which as primary? [1-{len(existing_imgs)}, default=1 most recent]: ", "1")
            try:
                idx = max(0, min(len(existing_imgs)-1, int(pick)-1))
            except Exception:
                idx = 0
            primary_sample = existing_imgs[idx]
            # allow more than one for variety (user can pick best later)
            samples = existing_imgs[:3]  # top 3 recent
            print(f"  Using existing primary: {primary_sample}")
            print(f"  Additional for reference/pick: {samples}")
    print()

    # Step 1: instructions (improved, with what-to-expect)
    print("STEP 1/8: Prepare your table  (or using existing images above)")
    print("  - Open ClubGG *or* CoinPoker, sit at a table (cash or tourney).")
    print("  - Make the window fully visible (not minimized, not covered).")
    print("  - Use your normal play resolution, zoom level, and lighting.")
    print("  - Cards should be clear and reasonably sized on screen.")
    print("  WHAT TO EXPECT: wizard will capture (or reuse) 2-3 samples, use cv2 to *auto-suggest*")
    print("    ROIs based on felt color + card clusters (GREEN box ~hero bottom, YELLOW~board center).")
    print("    Then you visually inspect calib_roi_preview.png and confirm/adjust fractions (res-independent).")
    print("    Crops shown for easy batch labeling or 'auto' accept-OCR-suggested.")
    print("  MULTI-CLIENT: same wizard for CoinPoker — just have CoinPoker table up; use --client coinpoker at launch time (calib profile is client/table specific).")
    if not use_existing:
        _ = _safe_input("Press ENTER when ready to capture fresh samples (table must be forward)... ", "")
    else:
        _ = _safe_input("Press ENTER to proceed with EXISTING samples for re-calib (no grab)... ", "")
    print()

    # Step 2: capture samples (reuse robust logic) — or skip if re-using
    print("STEP 2/8: Capture (or select) sample image(s)")
    if not use_existing:
        samples = capture_calibration_samples(count=3, client=client)  # generalized capture + client (coinpoker aware)
    if not samples:
        print("[calib] No samples (capture failed or no existing). Try bringing table forward and rerun, or place a PNG as clubgg_live.png.")
        # fallback to any png that might be a table shot
        fallbacks = [p for p in glob.glob("*.png") if os.path.isfile(p) and any(k in p.lower() for k in ("clubgg", "calib", "live", "capture"))]
        sample = fallbacks[0] if fallbacks else None
        if not sample:
            print("Aborting wizard.")
            return
        samples = [sample]
    # pick primary (for ROI preview + main crops); support "best of" or first
    if len(samples) > 1 and not primary_sample:
        print("Multiple samples captured/reused:")
        for i, s in enumerate(samples, 1):
            print(f"  {i}. {s}")
        pick = _safe_input("  Which to use as PRIMARY for ROI adjust + card crops? (number or ENTER=1): ", "1")
        try:
            pidx = max(0, min(len(samples)-1, int(pick)-1))
            primary_sample = samples[pidx]
        except Exception:
            primary_sample = samples[0]
    elif not primary_sample:
        primary_sample = samples[0]
    sample = primary_sample
    print(f"Using primary sample for ROI/crops: {sample}")
    # NEW: offer auto-suggest average from all if >1
    if len(samples) > 1:
        ans_avg = _safe_input("  Average auto-ROI suggestions across samples (instead of single)? [y/N]: ", "n").lower()
        if ans_avg in ("y", "yes"):
            # will compute later in roi step
            print("  (Will compute median auto-suggest from all samples as starting point.)")
            samples_for_suggest = samples
        else:
            samples_for_suggest = [sample]
    else:
        samples_for_suggest = [sample]
    print()

    # Step 3: ROIs guided (IMPROVED: cv2 auto-suggest from felt/cards as starting point + multi-sample support + progress)
    print("STEP 3/8: Hero hand / board / stack ROI identification & confirm (auto-suggest + adjust)")
    try:
        from PIL import Image as _PILImage
        pil_img = _PILImage.open(sample)
        sw, sh = pil_img.size
    except Exception:
        sw, sh = 1920, 1080

    # NEW: start from cv2 auto-suggest (felt area + card rect clusters) instead of pure static
    # Supports "average" from multiple samples if user chose
    auto_fracs_list = []
    _sfs = samples_for_suggest if 'samples_for_suggest' in locals() else [sample]
    for sp in _sfs:
        try:
            sug = suggest_auto_rois(sp)
            if sug:
                auto_fracs_list.append(sug)
        except Exception:
            pass
    if auto_fracs_list:
        # simple median per key for multi-sample average
        def _median_fracs(flist, key):
            vals = []
            for f in flist:
                if key in f and len(f[key]) == 4:
                    vals.append(f[key])
            if not vals:
                return None
            # median componentwise
            med = []
            for i in range(4):
                col = sorted(v[i] for v in vals)
                med.append(col[len(col)//2])
            return tuple(med)
        auto_hero = _median_fracs(auto_fracs_list, "hero") or (0.275, 0.715, 0.725, 0.94)
        auto_board = _median_fracs(auto_fracs_list, "board") or (0.17, 0.355, 0.83, 0.595)
        auto_stack = _median_fracs(auto_fracs_list, "hero_stack") or (0.36, 0.905, 0.64, 0.985)
        print("  cv2 auto-suggested ROIs (felt+card detect heuristic) as STARTING point:")
        print(f"    hero~{auto_hero}  board~{auto_board}  stack~{auto_stack}")
        if len(auto_fracs_list) > 1:
            print("    (median across your samples)")
    else:
        auto_hero = (0.275, 0.715, 0.725, 0.94)
        auto_board = (0.17, 0.355, 0.83, 0.595)
        auto_stack = (0.36, 0.905, 0.64, 0.985)

    # initial rois from auto or built-in get (get will load any prior but we override)
    rois = {
        "hero": (int(sw * auto_hero[0]), int(sh * auto_hero[1]), int(sw * auto_hero[2]), int(sh * auto_hero[3])),
        "board": (int(sw * auto_board[0]), int(sh * auto_board[1]), int(sw * auto_board[2]), int(sh * auto_board[3])),
        "hero_stack": (int(sw * auto_stack[0]), int(sh * auto_stack[1]), int(sw * auto_stack[2]), int(sh * auto_stack[3])),
        "full": (0, 0, sw, sh),
    }

    # preview (uses current rois)
    preview = generate_roi_preview(sample, rois, out_path="calib_roi_preview.png", client=client)
    print(f"  Annotated preview saved: {preview}")
    print("  >>> Open 'calib_roi_preview.png' NOW to visually inspect the colored boxes <<<")
    print("    GREEN = hero hand area (bottom, expect 2 cards side-by-side)")
    print("    YELLOW = board area (center, expect 3-5 community cards)")
    print("    ORANGE = hero stack/pos label area (very bottom, for auto stack OCR)")
    print("  (Auto-suggest used cv2 green-felt + card rect clustering as smart default; your table may vary slightly.)")
    print()

    hero_f = auto_hero
    board_f = auto_board
    stack_f = auto_stack

    # compute current fracs from rois for this sample (for adjust loop)
    def _frac_from_bbox(b, w, h):
        l, t, r, bb = b
        return (l / w, t / h, r / w, bb / h)

    # seed from current rois (auto based)
    hero_f = _frac_from_bbox(rois.get("hero", (int(sw*hero_f[0]), int(sh*hero_f[1]), int(sw*hero_f[2]), int(sh*hero_f[3]))), sw, sh)
    board_f = _frac_from_bbox(rois.get("board", (int(sw*board_f[0]), int(sh*board_f[1]), int(sw*board_f[2]), int(sh*board_f[3]))), sw, sh)
    stack_f = _frac_from_bbox(rois.get("hero_stack", (int(sw*stack_f[0]), int(sh*stack_f[1]), int(sw*stack_f[2]), int(sh*stack_f[3]))), sw, sh)

    adjusted = False
    while True:
        ans = _safe_input("Do the boxes in the preview cover your cards/board/stack labels well? [Y/n/adjust] ", "y").lower()
        if ans in ("", "y", "yes"):
            break
        if ans.startswith("a"):
            print("  Adjust (enter 4 space-separated 0-1 fractions left top right bottom, or blank=keep):")
            hline = _safe_input("    hero   (e.g. 0.26 0.70 0.74 0.96): ", "")
            if hline.strip():
                hero_f = _parse_fractions_line(hline, hero_f)
                adjusted = True
            bline = _safe_input("    board  (e.g. 0.15 0.34 0.85 0.60): ", "")
            if bline.strip():
                board_f = _parse_fractions_line(bline, board_f)
                adjusted = True
            sline = _safe_input("    stack  (e.g. 0.34 0.90 0.66 0.99): ", "")
            if sline.strip():
                stack_f = _parse_fractions_line(sline, stack_f)
                adjusted = True
            # rebuild rois + preview
            new_rois = {
                "hero": (int(sw * hero_f[0]), int(sh * hero_f[1]), int(sw * hero_f[2]), int(sh * hero_f[3])),
                "board": (int(sw * board_f[0]), int(sh * board_f[1]), int(sw * board_f[2]), int(sh * board_f[3])),
                "hero_stack": (int(sw * stack_f[0]), int(sh * stack_f[1]), int(sw * stack_f[2]), int(sh * stack_f[3])),
                "full": (0, 0, sw, sh),
            }
            rois = new_rois
            preview = generate_roi_preview(sample, rois, out_path="calib_roi_preview.png", client=client)
            print("  Updated preview generated. Re-inspect calib_roi_preview.png .")
        else:
            print("  (Keeping proposed / auto-suggested.)")
            break
    print(f"  Final fractions (will scale to any capture size): hero={hero_f}, board={board_f}, stack={stack_f}")
    print()

    # Step 4: card templates (IMPROVED: show MORE crops, batch labeling, "auto" accept-all-good with OCR-suggest prefill, progress)
    print("STEP 4/8: Card sprite templates (for template-match fallback + higher conf)")
    print("  Auto-detecting card-like rects inside the (tuned) ROIs — now more permissive to surface MORE candidates for you.")
    print("  Crops saved to calib_crops/. You will label verified ones -> card_templates/ (cwd priority for --real-vision).")
    # use higher max to show more crops (easier collection)
    crops = generate_card_crops(sample, rois, max_per_area=6, client=client)
    total_crops = sum(len(v) for v in crops.values())
    print(f"  Found {total_crops} candidate crops in calib_crops/ (hero + board).")
    if total_crops == 0:
        print("  (No strong rects detected — you can still manually place Ah.png etc in card_templates/ later.)")
    verified_templates = []
    all_crops_flat = []
    for area in ("hero", "board"):
        for cp in crops.get(area, []):
            all_crops_flat.append((area, cp))
    if all_crops_flat:
        print("  >>> List of crops (open the PNGs in file explorer or viewer):")
        for i, (ar, cp) in enumerate(all_crops_flat, 1):
            print(f"    {i}. [{ar}] {cp}")
        print()
        print("  EASY LABELING OPTIONS:")
        print("    - Type 'auto' : auto-suggest labels via OCR/recog for all, accept the good ones (batch 'accept all good').")
        print("    - Enter batch labels (space sep, same order): e.g. Ah 10d _ Ks Qc _  (use _ or skip or blank for bad)")
        print("    - Or ENTER for classic one-by-one (now with suggested defaults pre-filled).")
        print("    - 'q' anytime to finish early.")
        batch = _safe_input("Batch / auto / one-by-one? (auto or e.g. 'Ah 10d skip Ks' or ENTER): ", "").strip().lower()
        if batch == "auto" or batch == "a":
            print("  Auto mode: suggesting labels (OCR + template match) and accepting confident ones...")
            for area, cp in all_crops_flat:
                sug = None
                try:
                    sug = suggest_label_for_crop(cp)
                except Exception:
                    sug = None
                print(f"    Crop: {cp}  suggested={sug or '(none)'}")
                if sug:
                    norm = _normalize_card_token(sug)
                    if norm:
                        dest = save_card_template_from_crop(norm, cp)
                        if dest:
                            verified_templates.append(norm)
                            print("      -> accepted as template")
                else:
                    print("      -> no good suggestion, skipped (add manually later if needed)")
        elif batch and batch not in ("o", "one", "one-by-one", ""):
            # parse batch line
            labs = batch.replace(",", " ").split()
            for i, (area, cp) in enumerate(all_crops_flat):
                if i >= len(labs):
                    break
                lab = labs[i]
                if lab.lower() in ("q", "quit"):
                    break
                if not lab or lab.lower() in ("skip", "s", "_", ".", ""):
                    continue
                norm = _normalize_card_token(lab)
                if not norm:
                    print(f"      (Invalid '{lab}' for {cp}, skipping.)")
                    continue
                dest = save_card_template_from_crop(norm, cp)
                if dest:
                    verified_templates.append(norm)
                    print(f"      Batch accepted {norm} from {cp}")
        else:
            # classic one-by-one, but improved with suggestions as default
            print("  One-by-one (ENTER accepts suggestion if shown; type skip/ENTER for bad):")
            for area, cp in all_crops_flat:
                sug = None
                try:
                    sug = suggest_label_for_crop(cp)
                except Exception:
                    pass
                prompt_def = sug or "skip"
                print(f"    Crop file: {cp}")
                lab = _safe_input(f"      Label? (e.g. Ah or 10d; suggested [{prompt_def}]): ", prompt_def)
                if lab.lower() in ("q", "quit"):
                    break
                if not lab or lab.lower() in ("skip", "s", "_", ""):
                    continue
                norm = _normalize_card_token(lab)
                if not norm:
                    print("      (Invalid label, skipping.)")
                    continue
                dest = save_card_template_from_crop(norm, cp)
                if dest:
                    verified_templates.append(norm)
    print("  (Optional) Manually drop any additional exact card crops into ./card_templates/ now (named Ah.png etc).")
    _ = _safe_input("  Press ENTER when ready to proceed (templates in cwd/card_templates/ take priority over pkg)... ", "")
    print(f"  Verified/collected templates this run: {verified_templates or '(none — using OCR only or prior)'}")
    print()

    # Step 5: defaults
    print("STEP 5: Tuned runtime defaults (for your setup)")
    sens = VISION_SENSITIVITY
    pre = VISION_PREPROC
    ans = _safe_input(f"  Sensitivity for real OCR? (low/medium/high) [{sens}]: ", sens)
    if ans in ("low", "medium", "high"):
        sens = ans
    ans = _safe_input(f"  Preproc level? (off/light/aggressive) [{pre}]: ", pre)
    if ans in ("off", "light", "aggressive"):
        pre = ans
    min_conf = 0.28
    pmin = 0.20
    print(f"  Using min_conf={min_conf} (partials {pmin}) — good starting point; tune later via --vision-* if needed.")
    print()

    # Step 6: persist (profile now also includes any extra ROIs if user wants in future)
    print("STEP 6/8: Save calibration profile")
    cfg = {
        "version": 1,
        "client": client,
        "calibrated_resolution": [sw, sh],
        "roi_fractions": {
            "hero": list(hero_f),
            "board": list(board_f),
            "hero_stack": list(stack_f),
        },
        "sensitivity": sens,
        "min_conf": min_conf,
        "partial_min_conf": pmin,
        "preproc": pre,
        "notes": "Calibrated via wizard (vision-calib-polish) for this user's ClubGG or CoinPoker table/res/skin. Auto-loaded by capture.get_poker_rois (generalized new version) / get_clubgg_rois (compat wrapper), _load_templates, attempt_vision_parse and live runner for --real-vision --client XXX. card_templates/ (cwd) has priority. Re-calib from existing supported. Use --client coinpoker for CoinPoker tables (calib once per).",
    }
    saved_path = save_vision_config(cfg, client=client)  # use client for possible vision_config_<client>.json + stored key; generalized save
    # also apply immediately
    try:
        set_vision_params(sensitivity=sens, min_conf=min_conf, partial_min_conf=pmin, preprocess=pre)
    except Exception:
        pass
    print(f"  Profile written: {saved_path}")
    # ensure templates cache refreshed for immediate test
    try:
        # force reload on next _get by clearing (internal but safe)
        import pokerflex.capture as _cap
        _cap._CARD_TEMPLATES = None
    except Exception:
        pass
    print()

    # Step 7: AUTO test capture + parse with rich feedback + guidance (no more optional; always after save)
    print("STEP 7/8: Auto test capture + parse (rich results on your tuned settings + guidance)")
    print("  Capturing fresh real frame (table must be visible for this verification step)...")
    test_path = None
    try:
        test_path = capture_clubgg_image(output_path="calib_test_capture.png", delay=1, silent=False, retries=3, activate=True, client=client)
    except Exception as ex:
        print(f"  (capture issue: {ex}; trying last primary sample as fallback for test)")
        test_path = sample
    print("  Parsing with calibrated ROIs + current params (debug on for rich output)...")
    parsed = {}
    try:
        set_vision_params(debug=True)
        parsed = attempt_vision_parse(test_path, silent=False, sensitivity=sens, min_conf=min_conf, partial_min_conf=pmin, debug=True, preprocess=pre, client=client)
        print("  --- TEST PARSE RESULT (your profile in action) ---")
        print(f"    hand={parsed.get('hand') or '(none)'}  board={parsed.get('board') or '(none)'}")
        print(f"    pos={parsed.get('position') or '(none)'}  stack={parsed.get('stack') or '(none)'}")
        potstr = f" pot={parsed.get('pot')}" if parsed.get('pot') else ""
        betstr = f" bet={parsed.get('facing_bet')}" if parsed.get('facing_bet') else ""
        print(f"    conf={parsed.get('confidence')}  partial={parsed.get('partial')}  below_thresh={parsed.get('below_threshold')}{potstr}{betstr}")
        print(f"    rects={parsed.get('detected_card_rects')}  method={parsed.get('method')}")
        print(f"    image_size={parsed.get('image_size')}")
        if parsed.get('raw_cards'):
            print(f"    raw_cards={parsed.get('raw_cards')}")
        if parsed.get('villain_count') or parsed.get('street'):
            print(f"    extra: street={parsed.get('street')} villains={parsed.get('villain_count')}")
        print("  --------------------------------------------------")
        # RICH GUIDANCE (key for 0-touch polish)
        conf = parsed.get("confidence") or 0.0
        guidance = []
        if conf < 0.45 or parsed.get("below_threshold"):
            guidance.append("Low conf or below threshold: re-run calibrate with better lighting/zoom, or use --vision-debug on live to inspect.")
        if not parsed.get("hand") or len(str(parsed.get("hand"))) < 4:
            guidance.append("Hero hand weak: ensure bottom cards clear in your ROI; consider adding exact card crops to card_templates/.")
        if not parsed.get("board") or len(str(parsed.get("board"))) < 6:
            guidance.append("Board partial: center ROI may need tweak, or add board card templates.")
        # suit-specific common gotcha
        raw = parsed.get("raw_cards") or []
        if raw and any(len(str(c)) < 2 or str(c)[-1] not in "shdc" for c in raw if c):
            guidance.append("Suits missing or low conf: OCR struggles on small pips — add more template crops (real grabs of your exact cards) to card_templates/ for match fallback.")
        if parsed.get("method") and "ocr" not in str(parsed.get("method")).lower() and not parsed.get("raw_cards"):
            guidance.append("No OCR/tmpl hits: confirm tesseract installed (system binary), or add 4-8 good templates.")
        if guidance:
            print("  GUIDANCE:")
            for g in guidance:
                print(f"    - {g}")
        else:
            print("  Looks solid! (High conf + full reads = great post-calib experience.)")
        print("  (Test image: calib_test_capture.png ; re-calib or --calib-test anytime to re-verify.)")
    except Exception as ex:
        print(f"  Test parse error (non-fatal): {ex}")
    finally:
        try:
            set_vision_params(debug=False)
        except Exception:
            pass
    # also persist a small result snapshot for user reference
    try:
        with open("calib_test_result.json", "w", encoding="utf-8") as f:
            json.dump({"parsed": parsed, "profile": saved_path, "at": datetime.utcnow().isoformat() + "Z"}, f, indent=2)
        print("  (Saved calib_test_result.json for your records.)")
    except Exception:
        pass
    print()

    # Step 8: done + usage
    print("=" * 64)
    print(" CALIBRATION COMPLETE — set and forget enabled  (STEP 8/8)")
    print(f"  Saved: {saved_path}")
    print("  card_templates/ (your verified sprites) now used with priority by live vision.")
    print("  vision_config.json respected by get_poker_rois (generalized) / get_clubgg_rois (wrapper) / _load_templates / attempt_vision_parse.")
    print()
    print("NEXT: Use your tuned profile automatically:")
    print("  python -m pokerflex --background --live --real-vision --auto-capture")
    print("  # or with launcher:")
    print("  python launch_assistant.py --real-vision")
    print("  # or bare (after pip install -e .):")
    print("  pokerflex --background --live --real-vision [--client coinpoker]")
    print()
    print("VERIFY / HELPERS:")
    print("  python -m pokerflex --calib-test          # NEW: quick non-interactive parse demo using current profile + guidance")
    print("  python -m pokerflex --show-calibration     # view active profile/ROIs/templates")
    print("  python -m pokerflex --reset-vision         # revert to built-in (or --reset-vision --also-templates)")
    print("  python -m pokerflex calibrate [--client coinpoker]  # re-run wizard (or from existing images) anytime; supports re-calib per client")
    print()
    print("Tips: Use --vision-debug first time with real to see conf/partials/rects.")
    print("      Add more card_templates/*.png from future grabs (or re-calib) for even better suit fallback.")
    print("      ROIs are fractions -> work across slight res/zoom changes (re-calib only if skin/layout changes a lot).")
    print("      Simulate-vision (--simulate-vision) unchanged for safe testing / no-table use.")
    print("=" * 64)
    print("Zero-touch real-time A1 assistant now dramatically more reliable for *your* ClubGG or CoinPoker skin (use --client coinpoker for the latter).")
    print("After calibration you should see: higher % of full hand+board reads, better partial street advances, usable auto pot/bet, fewer manual overrides.")
    print("CoinPoker: python -m pokerflex calibrate --client coinpoker ; then python -m pokerflex --tray --background --live --real-vision --client coinpoker")
    print()


def run_calib_test() -> None:
    """Simple non-interactive CLI helper for `python -m pokerflex --calib-test`.
    Loads current profile (vision_config + templates), does a quick real capture (or falls back to latest sample),
    runs attempt_vision_parse with debug, prints RICH results + targeted guidance.
    Perfect post-calib verification or quick "is my profile working?" without full wizard.
    Respects --simulate? No: this is specifically for real profile test (use --simulate-vision in normal for sim).
    Compatible: no new deps.
    """
    print("=" * 64)
    print(" PokerFlex — Calib Test (quick profile verify + parse demo)")
    print("  Uses active vision_config.json + card_templates (if present).")
    print("=" * 64)
    try:
        from .capture import (
            show_vision_calibration_status, load_vision_config,
            capture_clubgg_image, attempt_vision_parse, set_vision_params,
            DEFAULT_CLIENT,
        )
    except Exception:
        from pokerflex.capture import (  # type: ignore
            show_vision_calibration_status, load_vision_config,
            capture_clubgg_image, attempt_vision_parse, set_vision_params,
            DEFAULT_CLIENT,
        )
    # show status first (client-aware)
    try:
        info = show_vision_calibration_status(silent=False, client=cli)
    except Exception as ex:
        print(f"[calib-test] status warning: {ex}")
        info = {}
    load_vision_config(force_reload=True, client=cli)
    # pick sens etc from loaded or defaults; use client from status/profile for test capture/parse (per task)
    sens = info.get("sensitivity") or VISION_SENSITIVITY
    pre = info.get("preproc") or VISION_PREPROC
    cli = info.get("client") or DEFAULT_CLIENT
    if cli not in ("clubgg", "coinpoker"):
        cli = DEFAULT_CLIENT
    cname = "CoinPoker" if cli == "coinpoker" else "ClubGG"
    # find a test image: prefer fresh capture, else recent local png
    test_path = None
    print(f"Capturing fresh frame for test ( {cname} table forward recommended, using client={cli} )...")
    try:
        test_path = capture_clubgg_image(output_path="calib_test_capture.png", delay=0, silent=False, retries=2, activate=True, client=cli)
    except Exception as ex:
        print(f"  Capture warn: {ex}")
    if not test_path or not os.path.exists(test_path):
        cands = sorted(glob.glob("calib_sample*.png") + glob.glob("clubgg_live*.png") + glob.glob("calib_test_capture.png"), key=os.path.getmtime, reverse=True)
        if cands:
            test_path = cands[0]
            print(f"  Using existing: {test_path}")
        else:
            print("  No image available for parse test. (Run calibrate or capture first.)")
            return
    print(f"Using image: {test_path}")
    print("Parsing with current profile + debug...")
    try:
        set_vision_params(debug=True, preprocess=pre)
        parsed = attempt_vision_parse(test_path, silent=False, sensitivity=sens, debug=True, preprocess=pre, client=cli)
        print("--- CALIB-TEST PARSE RESULT ---")
        print(f"  hand={parsed.get('hand') or '(none)'} board={parsed.get('board') or '(none)'}")
        print(f"  pos={parsed.get('position') or '(none)'} stack={parsed.get('stack') or '(none)'}")
        print(f"  conf={parsed.get('confidence')} partial={parsed.get('partial')} below={parsed.get('below_threshold')}")
        print(f"  rects={parsed.get('detected_card_rects')} method={parsed.get('method')}")
        if parsed.get("pot") or parsed.get("facing_bet"):
            print(f"  pot={parsed.get('pot')} bet={parsed.get('facing_bet')} street={parsed.get('street')}")
        if parsed.get("raw_cards"):
            print(f"  raw={parsed.get('raw_cards')}")
        print("-------------------------------")
        # guidance mirroring wizard
        conf = float(parsed.get("confidence") or 0)
        g = []
        if conf < 0.5 or parsed.get("below_threshold"):
            g.append("Low conf: after calibrate, if still low try --vision-preproc aggressive or add templates.")
        if (not parsed.get("hand") or len(str(parsed.get("hand") or "")) < 4) and (not parsed.get("board") or len(str(parsed.get("board") or "")) < 6):
            g.append("Weak reads: re-calibrate (or use existing images mode), ensure tesseract, good lighting; suits often improved by card_templates/.")
        raw = parsed.get("raw_cards") or []
        if any((isinstance(c, str) and len(c) < 2) for c in raw):
            g.append("If conf low on suits, add more template crops (real screenshots of your cards) to card_templates/ for robust match.")
        if g:
            print("GUIDANCE:")
            for gg in g:
                print(f"  - {gg}")
        else:
            print("Profile test: looks usable for --live --real-vision.")
    except Exception as ex:
        print(f"[calib-test] parse error: {ex}")
    finally:
        try:
            set_vision_params(debug=False)
        except Exception:
            pass
    print("Done. For full interactive: python -m pokerflex calibrate")
    print("=" * 64)


def main():
    """Allow `python -m pokerflex.calibration` or direct run."""
    # Early reinforce A1 (no effect on calib)
    try:
        os.environ.setdefault("POKERFLEX_QUIET_CALIB", "1")
    except Exception:
        pass
    cli = None
    for i, a in enumerate(sys.argv[1:], 0):
        if a in ("--client",) and i+1 < len(sys.argv)-1:
            cli = sys.argv[i+2] if sys.argv[i+1] == a else sys.argv[i+1]
            break
        if a.startswith("--client="):
            cli = a.split("=",1)[1]
            break
    run_calibration_wizard(client=cli)


if __name__ == "__main__":
    main()
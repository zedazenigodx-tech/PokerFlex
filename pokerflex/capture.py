"""PokerFlex capture — grab the poker client window (ClubGG / CoinPoker or full screen) to a PNG + real-time vision pipeline.

Client abstraction for 0-touch background real-time A1 (exact same philosophy as ClubGG for CoinPoker):
- clients: 'clubgg' (default for backward compat), 'coinpoker'
- WINDOW_HINT supports str or list; per-client via CLIENT_WINDOW_HINTS ("coinpoker", "coin poker", "coinpoker table" etc.)
- find_window_bbox accepts client= or auto-detects from title (if 'coinpoker' in title.lower() -> coinpoker mode)
- get_poker_rois(client="clubgg", width, height) generalized; get_clubgg_rois kept as thin wrapper for compat
- capture_clubgg_image (name preserved + client= param) and internals; update to capture_poker_image style optional
- attempt_vision_parse / capture_and_parse / simulate_table_state: accept + pass client=
- load/save vision_config support per-client profiles e.g. vision_config_coinpoker.json (or "client" key inside); store client in config
- default fractions same (~hero 0.27-0.72 bottom, board center); slight CoinPoker if known or via per-client calib override
- find/capture robust for both; set_vision_params ok as-is (per-client via its vision_config)
- No breakage existing ClubGG calls (all default client="clubgg")
- Root shim capture.py thin reexport also updated for doc.

ClubGG / CoinPoker table capture (window detection via pygetwindow if present) + save for calibration.
Also the home of the working basic vision layer used by run_brain --live / --auto-capture / tray.

Usage (capture only):
    python capture.py
    # CoinPoker: ensure table window visible (title has "coinpoker"); auto or use client='coinpoker'

Enhanced functional vision (no longer pure stub):
- get_poker_rois(client="clubgg", width, height) / get_clubgg_rois (wrapper): client-tuned (or shared default) hero (bottom ~0.27-0.72) / board (center) regions scaled to image + pot/action_bar/hud ROIs (calib + per-client vision_config aware).
- attempt_vision_parse(client=...): ROI crops + cv2 card-sprite contour detection + per-card tesseract OCR
  (tuned psm) + simple template-match fallback. Handles unicode suits, partial reads, confidence.
  NEW: sensitivity (low/med/high), min_conf, 'partial' flag, below_threshold, tuned CV/OCR for robustness.
  FURTHER (this enhancement): more OCR noise tolerance in normalize/parse, dedup+overlap guards, new prefer_better_board() helper for robust partial board (non-downgrade on noisy reads) + merge_board_fragment() for true incremental street reads (vision fragment append).
  Additional (background app enhancement pass): prefer_better_hand(), capture retries+window activate/restore for auto reliability, improved tolerant stack/pos extraction regex+keywords, --vision-retries CLI. All support deeper runner live integration.
  LATEST (seamless real-time ClubGG hands-off): added --vision-preproc (off/light/aggressive) CLI + VISION_PREPROC + enhanced _ocr preproc (CLAHE, adaptive, bilateral for low-contrast ClubGG sprites); deeper partial recovery in _parse/_normalize (better 1-card/isolated suit pairing); refined conf credit + merge for incremental boards; live listener + robust apply use it for auto-extract/update/analyze. Better fallback (graceful low-conf/partial, manual always wins). Full compat notes/explo/ICM/tmode.
  HARDENED + CLIENT: multi-frame... + client abstraction passed to rois/parse/capture for CoinPoker 0-touch parity (auto-detect, per-client calib json). Compat preserved 100%.
- _parse_card_tokens + _normalize... robust to OCR noise on graphical cards.
- simulate_table_state(client=...): deterministic cycling states for safe --simulate-vision live tests. Generic (same states for CoinPoker or ClubGG); client= just tags output and affects only real-capture paths.
  Now injects occasional partial reads + incremental-only board cards to test conf/thresh/partial + street-merge paths. (client stored in sim output for parity)
- capture_and_parse(client=...): unified entry for live flows (real capture or sim). Forwards sens/min_conf + client to capture/parse.
- Simple card template loader (_load_templates) — ready for user-provided 'card_templates/Ah.png' etc.
- set_vision_params(): runtime tune from runner CLI (applies across; per-client config loads its sens/preproc).

The pipeline now auto-extracts hand/board/position from live ClubGG or CoinPoker screenshots for A1 brain (default via python -m pokerflex --live ; for coin use --client coinpoker or auto title detect).
Requires tesseract-ocr binary in PATH for OCR (pip package alone insufficient); cv2 helps detection.
Falls back gracefully; partial results (e.g. flop only, 1 hole) still update live state.
See attempt_vision_parse docstring for before/after + new robustness (conf thresholds + manual fallback support).
Deeply integrated with run_brain live listener + auto-capture for hands-off real-time. Same for CoinPoker after calib.

Deps: Pillow, opencv-python, pytesseract (in requirements.txt). pygetwindow optional but recommended.
"""
import os
import re
import time
import json
import collections
import glob  # for finding existing calib images in re-calib mode (stdlib)
from datetime import datetime
from PIL import ImageGrab

try:
    from PIL import Image
    HAS_PIL = True
except Exception:
    HAS_PIL = False

try:
    import cv2  # type: ignore
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False

try:
    import pytesseract  # type: ignore
    HAS_TESSERACT = True
except Exception:
    HAS_TESSERACT = False


# Vision pipeline tunables for robustness in real-time ClubGG / CoinPoker use (live runner, client abstracted).
# sensitivity: "low" accepts more partial/ noisy reads (aggressive updates),
#              "medium" balanced, "high" strict (fewer spurious auto-updates, better rect/ocr filters).
# min_conf used by callers (e.g. runner live listener) to decide auto-apply vs fallback manual.
VISION_SENSITIVITY = "medium"
MIN_CONF_DEFAULT = 0.20
PARTIAL_MIN_CONF_DEFAULT = 0.15  # dedicated default for partial reads (lower to allow incremental street reads in live); runtime via set + CLI --vision-partial-conf
VISION_DEBUG = False  # set via set_vision_params(debug=True) or CLI --vision-debug for extra internal logs on partials/conf/fallbacks
VISION_PREPROC = "light"  # "off" | "light" | "aggressive" : controls OCR image enhancement level for real ClubGG vision robustness (light=balanced upscale+binarize; aggressive adds CLAHE+filters for low-contrast sprites/HUD; off=raw). Further enhances partial reads + conf reliability for live auto state updates. CLI: --vision-preproc ; forwarded from runner.

# HARDENED VISION (this pass): multi-frame temporal smoothing + adaptive preproc + pot/bet/street/action extraction + improved OCR voting for ClubGG/CoinPoker reliability (client abstracted).
# VISION_HISTORY_LEN: short rolling history for vote stable hand/board, new-deal vs board-progress detection, conf decay, streak.
#   e.g. 4-6 typical; higher smooths more but lags genuine changes slightly. CLI --vision-history-len passthrough in runner.
# VISION_ADAPTIVE_PREPROC: if True, _auto_choose_preproc() inspects image stats (contrast via std, brightness, sharpness) + recent conf history to pick/boost level (still respects base VISION_PREPROC).
#   Adds deskew, better CLAHE params, color/felt normalization (green bias for table), more filters for stylized sprites/low-light/resize skins/occlusion.
# VISION_OCR_VOTING: enables per-crop multi-psm (more modes) + image_to_data conf aggregation + weighted vote + fusion with template match score. Secondary full-image OCR fallback for HUD labels (villain pos/stacks).
# VISION_STREET_ACTION: enable extract_bet_info / extract_pot + detect street/action hints from bet UI text, pot numbers, button labels ("Call X", "Pot", "Bet") to auto populate facing_bet/pot/street/action_hint (reduces manual in live facing decisions).
# These + smooth_vision_state + merge_board_fragment + existing prefer_* give much better real ClubGG auto state (pot/bet usable for future SPR/odds in A1).
VISION_HISTORY_LEN = 5
VISION_ADAPTIVE_PREPROC = True
VISION_OCR_VOTING = True
VISION_STREET_ACTION = True

# =============================================================================
# Multi-client support (ClubGG + CoinPoker + similar poker clients)
# Same 0-touch philosophy: calib once per client/table, then --live --real-vision
# works for both. Opponents know you use it — no issue.
# =============================================================================

SUPPORTED_CLIENTS = ("clubgg", "coinpoker")

CLIENT_WINDOW_HINTS = {
    "clubgg": ["clubgg", "club", "ggpoker", "club gg", "clubgg table"],
    "coinpoker": ["coinpoker", "coin poker", "coinpoker table", "coinpoker poker"],
}

CLIENT_DEFAULT_NAMES = {
    "clubgg": "ClubGG",
    "coinpoker": "CoinPoker",
}

# Default client (backward compat with all previous ClubGG usage)
DEFAULT_CLIENT = "clubgg"

# Client-specific default ROI fractions (used only if no vision_config.json; wizard for coinpoker will persist tuned ones).
# These are starting heuristics; post-calib the stored roi_fractions (client-agnostic in structure) override.
# Calib wizard for CoinPoker uses detection + user adjust to store appropriate fractions + "client" marker.
CLIENT_DEFAULT_ROI_FRACS = {
    "clubgg": {
        "hero": (0.275, 0.715, 0.725, 0.94),
        "board": (0.17, 0.355, 0.83, 0.595),
        "hero_stack": (0.36, 0.905, 0.64, 0.985),
        "pot": (0.32, 0.26, 0.68, 0.34),
        "action_bar": (0.28, 0.82, 0.72, 0.90),
        "hud": (0.08, 0.22, 0.92, 0.52),
    },
    "coinpoker": {
        "hero": (0.28, 0.705, 0.72, 0.935),
        "board": (0.185, 0.365, 0.815, 0.585),
        "hero_stack": (0.355, 0.902, 0.645, 0.982),
        "pot": (0.325, 0.265, 0.675, 0.345),
        "action_bar": (0.285, 0.815, 0.715, 0.895),
        "hud": (0.09, 0.215, 0.91, 0.505),
    },
}

# NEW tunables for this harden (real-OCR reliability on varied ClubGG skins/res/zoom/lighting/felt):
# template boost strengthens user+pkg card_templates after calib (post _recognize).
# suit color heuristic: pre-OCR red/black detect on crop to filter/ bias suit OCR (h/d red, s/c black).
# detection morph + multiscale: better contours for card borders (typical thin frame on ClubGG cards) across green/blue/red felts + zoom.
# auto scale: make min/max_area + min_w/h tolerant by scaling from calib base res (or default 1920x1080); less brittle ROI/detect.
# rank whitelist central for ocr cfgs + parsers + 10/T.
VISION_TEMPLATE_CONF_BOOST = 0.12
VISION_SUIT_COLOR_HEURISTIC = True
VISION_DETECTION_MORPH = True
VISION_DETECTION_MULTISCALE = True
VISION_AUTO_SCALE_ROIS = True
VISION_RANK_WHITELIST = "23456789TJQKA10"
DEFAULT_BASE_RES = (1920, 1080)
# Internal history (populated by attempt_vision_parse on every call; used by smooth + live listener)
_VISION_HISTORY = collections.deque(maxlen=VISION_HISTORY_LEN)  # list of recent full parse dicts (for voting, decay, deal detection)
# For conf history (used by adaptive + decay)
_RECENT_CONFS = collections.deque(maxlen=8)

# Calibration support: vision_config.json (or vision_config_coinpoker.json etc) (user-tuned ROIs as fractions for scale-invariance across resolutions/skins/clients,
# plus sens/preproc defaults + "client" key). Loaded with priority to cwd for easy per-session, also ~/.pokerflex/ .
# get_poker_rois() / get_clubgg_rois() and template loader auto-prefer calibrated values when present (per-client profile takes precedence when client specified).
# This makes post-calib `... --live --real-vision --client coinpoker` (or auto) use your exact table layout/card art for high-reliability hands-off.
# Simulate paths untouched (bypass before ROI use). Non-breaking: absent config = original heuristics. Client stored in saved profile.
VISION_CONFIG = None
VISION_CONFIG_CLIENT = None
CALIBRATED_ROI_FRACTIONS = None  # e.g. {"hero": [0.275,0.715,0.725,0.94], ...} from user's confirmed sample
CALIBRATED_BASE_RES = None       # [w, h] at calibration time (for ref/logging)
CALIBRATED_AT = None
CALIBRATED_CLIENT = None         # "clubgg" | "coinpoker" — stored in vision_config.json by wizard; reported in status; used for client-aware capture/ROIs/defaults post-calib.


OUT = "clubgg_capture.png"
WINDOW_HINT = "ClubGG"   # substring (str) or list[str] matched against window titles; per-client overrides via CLIENT_WINDOW_HINTS; supports auto for coinpoker
DELAY = 3                # seconds to bring the table to the front


def set_vision_params(sensitivity: str | None = None, min_conf: float | None = None, debug: bool | None = None, partial_min_conf: float | None = None, preprocess: str | None = None, history_len: int | None = None, adaptive: bool | None = None, ocr_voting: bool | None = None, street_action: bool | None = None, template_conf_boost: float | None = None, suit_color_heur: bool | None = None, detection_morph: bool | None = None, detection_multiscale: bool | None = None, auto_scale_rois: bool | None = None):
    """Update global vision sensitivity / thresholds at runtime (called by runner on CLI flags).
    Affects _detect, _recognize heuristics + confidence calc for more/less robust partial handling.
    Sensitivity tunes internal CV/OCR acceptance; min_conf / partial_min_conf advisory (callers decide apply).
    partial_min_conf: dedicated lower bar for partial reads (1-hole/flop-only) in live sensitivity tuning.
    debug=True enables extra prints inside attempt_vision_parse for diagnosing partial reads / conf in live flows.
    preprocess: "off"/"light"/"aggressive" for OCR preproc robustness (new for further hands-off real vision on ClubGG / CoinPoker).
    NEW (hardened): history_len resizes the rolling _VISION_HISTORY for temporal smoothing/voting.
    adaptive: toggle VISION_ADAPTIVE_PREPROC (auto image-stat driven preproc choice + deskew/felt norm etc).
    ocr_voting / street_action: enable/disable the multi-psm voting and pot/bet/street/action extractors.
    NEW (this task): template_conf_boost, suit_color_heur, detection_morph/multiscale, auto_scale_rois for card sprite/OCR/skin/zoom harden.
    Client abstraction: per-client vision_config_*.json (loaded in get_poker_rois) can persist+restore sens/preproc on load for that client; set applies to current session.
    """
    global VISION_SENSITIVITY, MIN_CONF_DEFAULT, VISION_DEBUG, PARTIAL_MIN_CONF_DEFAULT, VISION_PREPROC
    global VISION_HISTORY_LEN, VISION_ADAPTIVE_PREPROC, VISION_OCR_VOTING, VISION_STREET_ACTION, _VISION_HISTORY
    global VISION_TEMPLATE_CONF_BOOST, VISION_SUIT_COLOR_HEURISTIC, VISION_DETECTION_MORPH, VISION_DETECTION_MULTISCALE, VISION_AUTO_SCALE_ROIS
    if sensitivity in ("low", "medium", "high"):
        VISION_SENSITIVITY = sensitivity
    if min_conf is not None:
        try:
            MIN_CONF_DEFAULT = max(0.0, min(1.0, float(min_conf)))
        except Exception:
            pass
    if partial_min_conf is not None:
        try:
            PARTIAL_MIN_CONF_DEFAULT = max(0.0, min(1.0, float(partial_min_conf)))
        except Exception:
            pass
    if debug is not None:
        VISION_DEBUG = bool(debug)
    if preprocess in ("off", "light", "aggressive"):
        VISION_PREPROC = preprocess
    if history_len is not None:
        try:
            n = max(1, min(12, int(history_len)))
            VISION_HISTORY_LEN = n
            if _VISION_HISTORY.maxlen != n:
                _VISION_HISTORY = collections.deque(list(_VISION_HISTORY)[-n:], maxlen=n)
        except Exception:
            pass
    if adaptive is not None:
        VISION_ADAPTIVE_PREPROC = bool(adaptive)
    if ocr_voting is not None:
        VISION_OCR_VOTING = bool(ocr_voting)
    if street_action is not None:
        VISION_STREET_ACTION = bool(street_action)
    if template_conf_boost is not None:
        try:
            VISION_TEMPLATE_CONF_BOOST = max(0.0, min(0.5, float(template_conf_boost)))
        except Exception:
            pass
    if suit_color_heur is not None:
        VISION_SUIT_COLOR_HEURISTIC = bool(suit_color_heur)
    if detection_morph is not None:
        VISION_DETECTION_MORPH = bool(detection_morph)
    if detection_multiscale is not None:
        VISION_DETECTION_MULTISCALE = bool(detection_multiscale)
    if auto_scale_rois is not None:
        VISION_AUTO_SCALE_ROIS = bool(auto_scale_rois)


def _get_vision_config_candidates(client: str | None = None) -> list[str]:
    """Priority order for vision_config.json (or per-client vision_config_coinpoker.json etc): cwd first (user session friendly), then home dir, then package.
    If client specified (e.g. "coinpoker"), client-specific names are searched first (vision_config_coinpoker.json), then generic.
    Calibration (per client) writes client-specific or generic cwd for zero-config discoverability + auto load by client.
    Stores "client" key in the json.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    names = ["vision_config.json"]
    c = (client or "").lower().strip().replace(" ", "_").replace("-", "_")
    if c and c != "clubgg" and c in ("coinpoker",):
        names = [f"vision_config_{c}.json"] + names
    cands = []
    for n in names:
        cands.extend([
            os.path.join(os.getcwd(), n),
            os.path.expanduser(os.path.join("~", ".pokerflex", n)),
            os.path.join(here, n),
        ])
    # dedup preserving order
    seen = set()
    uniq = []
    for x in cands:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def load_vision_config(force_reload: bool = False, client: str | None = None) -> dict | None:
    """Load persisted calibration profile if present (first existing candidate, preferring per-client e.g. vision_config_coinpoker.json when client= given).
    Sets module globals for roi fractions, base res, and also syncs sens/preproc if in config.
    Safe no-op if absent or corrupt. Called by get_poker_rois/get_clubgg_rois + runner start + wizard.
    Stores the effective client in VISION_CONFIG_CLIENT (and CALIBRATED_CLIENT for compat).
    """
    global VISION_CONFIG, CALIBRATED_ROI_FRACTIONS, CALIBRATED_BASE_RES, CALIBRATED_AT, VISION_SENSITIVITY, VISION_PREPROC, VISION_CONFIG_CLIENT, CALIBRATED_CLIENT
    eff_cached = VISION_CONFIG_CLIENT or CALIBRATED_CLIENT
    if VISION_CONFIG is not None and not force_reload and (client is None or eff_cached == client or eff_cached == (client or DEFAULT_CLIENT)):
        return VISION_CONFIG
    for cand in _get_vision_config_candidates(client):
        if os.path.exists(cand):
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                VISION_CONFIG = cfg
                eff_client = cfg.get("client") or client or DEFAULT_CLIENT
                VISION_CONFIG_CLIENT = eff_client
                CALIBRATED_CLIENT = eff_client
                if CALIBRATED_CLIENT and CALIBRATED_CLIENT.lower() not in SUPPORTED_CLIENTS:
                    CALIBRATED_CLIENT = DEFAULT_CLIENT
                    VISION_CONFIG_CLIENT = DEFAULT_CLIENT
                fracs = cfg.get("roi_fractions") or cfg.get("rois")  # support both for compat
                if isinstance(fracs, dict):
                    # normalize to list of 4 floats if needed
                    CALIBRATED_ROI_FRACTIONS = {}
                    for k, v in fracs.items():
                        if isinstance(v, (list, tuple)) and len(v) == 4:
                            CALIBRATED_ROI_FRACTIONS[k] = [float(x) for x in v]
                        elif k in ("hero", "board", "hero_stack") and isinstance(v, (list, tuple)) and len(v) == 4:
                            CALIBRATED_ROI_FRACTIONS[k] = [float(x) for x in v]
                res = cfg.get("calibrated_resolution") or cfg.get("resolution")
                if isinstance(res, (list, tuple)) and len(res) >= 2:
                    CALIBRATED_BASE_RES = [int(res[0]), int(res[1])]
                CALIBRATED_AT = cfg.get("calibrated_at")
                # sync runtime defaults from profile if user saved tuned ones (non-destructive to CLI overrides)
                if "sensitivity" in cfg and cfg["sensitivity"] in ("low", "medium", "high"):
                    VISION_SENSITIVITY = cfg["sensitivity"]
                if "preproc" in cfg and cfg["preproc"] in ("off", "light", "aggressive"):
                    VISION_PREPROC = cfg["preproc"]
                if VISION_DEBUG:
                    print(f"[vision] loaded calibration from {cand} (client={VISION_CONFIG_CLIENT}, res={CALIBRATED_BASE_RES})")
                return VISION_CONFIG
            except Exception as ex:
                if VISION_DEBUG:
                    print(f"[vision] failed to load {cand}: {ex}")
                continue
    VISION_CONFIG = None
    VISION_CONFIG_CLIENT = client or DEFAULT_CLIENT
    CALIBRATED_CLIENT = VISION_CONFIG_CLIENT
    return None


def save_vision_config(cfg: dict, path: str | None = None, client: str | None = None) -> str:
    """Persist the calibration profile (rois as fractions preferred for res-independence, sens, preproc, etc).
    Writes to cwd/vision_config.json by default, or vision_config_<client>.json (e.g. vision_config_coinpoker.json) if client given and path=None.
    Also ensures parent for ~/.pokerflex .
    Returns the path written. Stores "client" in the cfg.
    """
    if path is None:
        c = (client or "").lower().strip().replace(" ", "_")
        if c and c != "clubgg" and c in ("coinpoker",):
            fname = f"vision_config_{c}.json"
            path = os.path.join(os.getcwd(), fname)
        else:
            path = _get_vision_config_candidates(client or None)[0]
    pdir = os.path.dirname(path)
    if pdir:
        os.makedirs(pdir, exist_ok=True)
    # enrich with meta
    cfg = dict(cfg)  # copy
    cfg.setdefault("version", 1)
    cfg.setdefault("calibrated_at", datetime.utcnow().isoformat() + "Z")
    if client:
        cfg["client"] = client
    elif "client" not in cfg:
        cfg["client"] = DEFAULT_CLIENT
    if "calibrated_resolution" not in cfg and CALIBRATED_BASE_RES:
        cfg["calibrated_resolution"] = CALIBRATED_BASE_RES
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, sort_keys=True)
        # refresh module cache
        global VISION_CONFIG, VISION_CONFIG_CLIENT, CALIBRATED_CLIENT
        VISION_CONFIG = cfg
        eff = cfg.get("client") or client or DEFAULT_CLIENT
        VISION_CONFIG_CLIENT = eff
        CALIBRATED_CLIENT = eff
        if VISION_DEBUG or not os.environ.get("POKERFLEX_QUIET_CALIB"):
            print(f"[vision] saved calibration profile to {path} (client={eff})")
        return path
    except Exception as ex:
        print(f"[vision] ERROR saving config to {path}: {ex}")
        raise


def reset_vision_calibration(also_templates: bool = False, client: str | None = None) -> list[str]:
    """Remove vision_config.json (and per-client vision_config_coinpoker.json etc) candidates (and optionally card_templates user dirs).
    Reverts to built-in ROIs + pkg templates. Used by --reset-vision helper.
    If client given, targets that client's config primarily (but always cleans generics too for full reset).
    Returns list of removed paths.
    """
    removed = []
    # clean for specified + all supported to be thorough
    clients_to_clean = [client] if client else []
    clients_to_clean += [c for c in SUPPORTED_CLIENTS if c not in clients_to_clean]
    seen_cands = set()
    for c in clients_to_clean:
        for cand in _get_vision_config_candidates(c):
            if cand in seen_cands:
                continue
            seen_cands.add(cand)
            try:
                if os.path.exists(cand):
                    os.remove(cand)
                    removed.append(cand)
            except Exception:
                pass
    # also the no-arg generics explicitly (in case)
    for cand in _get_vision_config_candidates(None):
        if cand not in seen_cands:
            seen_cands.add(cand)
            try:
                if os.path.exists(cand):
                    os.remove(cand)
                    removed.append(cand)
            except Exception:
                pass
    global VISION_CONFIG, CALIBRATED_ROI_FRACTIONS, CALIBRATED_BASE_RES, CALIBRATED_AT, VISION_CONFIG_CLIENT, CALIBRATED_CLIENT
    VISION_CONFIG = CALIBRATED_ROI_FRACTIONS = CALIBRATED_BASE_RES = CALIBRATED_AT = VISION_CONFIG_CLIENT = CALIBRATED_CLIENT = None
    if also_templates:
        for tdir in [
            os.path.join(os.getcwd(), "card_templates"),
            os.path.expanduser(os.path.join("~", ".pokerflex", "card_templates")),
        ]:
            try:
                if os.path.isdir(tdir):
                    # remove contents but keep dir (or rm tree safe)
                    for fn in os.listdir(tdir):
                        try:
                            os.remove(os.path.join(tdir, fn))
                        except Exception:
                            pass
                    removed.append(tdir + "/*")
            except Exception:
                pass
    return removed


def show_vision_calibration_status(silent: bool = False, client: str | None = None) -> dict:
    """Print (unless silent) and return summary of current calibration state.
    Used by --show-calibration. Includes loaded config, effective ROIs, template counts/paths, client.
    Supports client= to load/show status for specific client's profile (e.g. coinpoker).
    """
    load_vision_config(force_reload=True, client=client)
    tmpls = _get_card_templates()  # triggers load
    tcount = len(tmpls)
    tdir_used = None
    # find which tdir was picked (recompute quickly)
    candidates = [
        os.path.join(os.getcwd(), "card_templates"),
        os.path.expanduser(os.path.join("~", ".pokerflex", "card_templates")),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "card_templates"),
    ]
    for c in candidates:
        if os.path.isdir(c) and any(f.lower().endswith((".png",".jpg")) for f in os.listdir(c) if os.path.isfile(os.path.join(c,f))):
            tdir_used = c
            break
    eff_client = VISION_CONFIG_CLIENT or CALIBRATED_CLIENT or (VISION_CONFIG.get("client") if VISION_CONFIG else None) or DEFAULT_CLIENT
    info = {
        "config_loaded": bool(VISION_CONFIG),
        "config_path": None,
        "calibrated_at": CALIBRATED_AT,
        "client": eff_client,
        "base_resolution": CALIBRATED_BASE_RES,
        "roi_fractions": CALIBRATED_ROI_FRACTIONS,
        "templates_count": tcount,
        "templates_dir": tdir_used,
        "sensitivity": VISION_SENSITIVITY,
        "preproc": VISION_PREPROC,
    }
    for cand in _get_vision_config_candidates(client or eff_client):
        if os.path.exists(cand):
            info["config_path"] = cand
            break
    if not silent:
        print("=== PokerFlex Vision Calibration Status ===")
        if info["config_loaded"] and info["config_path"]:
            print(f"  Active profile: {info['config_path']}")
            print(f"  Calibrated at: {info['calibrated_at'] or 'unknown'}")
            print(f"  Client: {info.get('client', DEFAULT_CLIENT)}")
            print(f"  Base res: {info['base_resolution']}")
            if info["roi_fractions"]:
                for k, fr in info["roi_fractions"].items():
                    print(f"    {k}: fractions={fr}")
            print(f"  Runtime sens={info['sensitivity']} preproc={info['preproc']}")
        else:
            cname = CLIENT_DEFAULT_NAMES.get(eff_client, eff_client)
            print(f"  No user calibration profile loaded (using built-in {cname} ROIs + defaults).")
            print("  Run `python -m pokerflex calibrate` (or --calibrate) to tune for your table.")
            print(f"  (Supports clients clubgg|coinpoker; use --client coinpoker or auto-detect for CoinPoker.)")
        print(f"  Card templates active: {tcount} (from {info['templates_dir'] or 'none'})")
        print("  (After calibration, --live --real-vision uses your ROIs/templates automatically for higher reliability per client.)")
        print("===========================================")
    return info


def _detect_client_from_title(title: str | None) -> str | None:
    """Helper: inspect window title to decide client (coinpoker takes precedence on keyword match for auto)."""
    if not title:
        return None
    t = title.lower()
    coin_keys = ["coinpoker", "coin poker", "coinpoker table", "coinpoker poker"]
    if any(k in t for k in coin_keys):
        return "coinpoker"
    club_keys = ["clubgg", "club gg", "club", "ggpoker", "clubgg table"]
    if any(k in t for k in club_keys):
        return "clubgg"
    return None


def find_window_bbox(hint_or_client=None, client=None):
    """Return ((left, top, right, bottom), title, matched_client) for a supported poker client window, or None.
    Accepts client= explicitly ("clubgg"|"coinpoker").
    If client=None, auto-detects from any visible window titles (if 'coinpoker' in title.lower() use coinpoker mode).
    hint_or_client: legacy hint str (or list[str] for WINDOW_HINT support) to match titles; if provided overrides default client hints for matching (but auto client still influences if not explicit).
    Uses CLIENT_WINDOW_HINTS + extras for "coinpoker", "coin poker", "coinpoker table" etc.
    Prefers largest visible window. pygetwindow recommended (pip install pygetwindow).
    Always returns 3-tuple on success for client awareness (callers handle 2-tuple legacy gracefully).
    """
    try:
        import pygetwindow as gw
    except ImportError:
        return None

    # Resolve client: explicit client > detect from passed hint if it is client name > auto from titles > default
    if client is None:
        if isinstance(hint_or_client, str) and hint_or_client.lower() in SUPPORTED_CLIENTS:
            client = hint_or_client.lower()
        else:
            client = None
            try:
                for ww in gw.getAllWindows():
                    mc = _detect_client_from_title(ww.title)
                    if mc:
                        client = mc
                        break
            except Exception:
                pass
            if client is None:
                client = DEFAULT_CLIENT
    client = str(client).lower() if client else DEFAULT_CLIENT
    if client not in SUPPORTED_CLIENTS:
        client = DEFAULT_CLIENT

    # Build hints: if explicit hint (str or list) use it (for custom/override), else client's
    if hint_or_client and isinstance(hint_or_client, (list, tuple)):
        base_hints = [str(h) for h in hint_or_client]
    elif hint_or_client and isinstance(hint_or_client, str) and hint_or_client.lower() not in SUPPORTED_CLIENTS:
        base_hints = [hint_or_client]
    else:
        base_hints = list(CLIENT_WINDOW_HINTS.get(client, CLIENT_WINDOW_HINTS[DEFAULT_CLIENT]))

    # Add common fallbacks + ensure coin hints as specified
    all_hints = list(base_hints)
    if client == "clubgg":
        for e in ["club", "clubgg", "ggpoker", "club gg", "clubgg table"]:
            if e not in all_hints:
                all_hints.append(e)
    elif client == "coinpoker":
        for e in ["coinpoker", "coin poker", "coinpoker table", "coinpoker poker"]:
            if e not in all_hints:
                all_hints.append(e)
    # also always allow generic poker if broad
    for e in ["poker", "table"]:
        if e not in all_hints:
            all_hints.append(e)

    wins = []
    for h in all_hints:
        for w in gw.getAllWindows():
            title = (w.title or "")
            tlow = title.lower()
            if h.lower() in tlow and w.width > 100 and w.height > 100:
                mc = _detect_client_from_title(title) or client
                wins.append((w, mc))

    if not wins:
        return None

    # largest area first, prefer non-minimized
    wins.sort(key=lambda item: (0 if getattr(item[0], 'isMinimized', False) else 1, item[0].width * item[0].height), reverse=True)
    w, matched_client = wins[0]
    return (w.left, w.top, w.left + w.width, w.top + w.height), w.title, matched_client


def main():
    print(f"PokerFlex capture — grabbing in {DELAY}s. Bring the poker table (ClubGG/CoinPoker) to the front…")
    for i in range(DELAY, 0, -1):
        print(f"  {i}…", flush=True)
        time.sleep(1)

    found = find_window_bbox(WINDOW_HINT)
    matched = DEFAULT_CLIENT
    if found:
        if len(found) >= 3:
            bbox, title, matched = found
        elif len(found) == 2:
            bbox, title = found
            matched = DEFAULT_CLIENT
        else:
            bbox, title = found, ""
        cname = CLIENT_DEFAULT_NAMES.get(matched, matched)
        print(f"Found {cname} window: '{title}'  bbox={bbox}")
        img = ImageGrab.grab(bbox=bbox)
    else:
        cname = CLIENT_DEFAULT_NAMES.get(matched, "poker")
        print(f"No {cname} window located (pygetwindow not installed, or window not found) "
              "— grabbing full screen instead.")
        img = ImageGrab.grab(all_screens=True)

    img.save(OUT)
    print(f"Saved {OUT}  ({img.width}x{img.height}px). Send me this file to calibrate the reader.")


def capture_clubgg_image(
    output_path: str = OUT,
    window_hint: str | list | None = None,
    delay: int = 0,
    silent: bool = False,
    retries: int = 1,
    activate: bool = True,
    client: str = None,
) -> str:
    """
    Reusable non-interactive (or lightly interactive) poker window / screen grab (ClubGG or CoinPoker).
    Returns the path to the saved image. (Name kept for compat; internally client-abstracted.)

    Used by run_brain.py for the optional auto-capture stub (manual review for now;
    future: feed to OCR / vision layer to auto-populate GameState).
    FURTHER ENHANCED for seamless real-time: retries + optional window activate/restore
    (brings table forward if pygetwindow available) to increase success rate of auto-captures
    in background/live use without user intervention. Graceful if no pygetwindow.

    Supports client="coinpoker" or "clubgg" (default clubgg for full backward compat).
    - delay: seconds to sleep before grab (0 for instant / from runner cmd)
    - silent: suppress prints (for library use)
    - retries: number of re-attempts on window-not-found (helps transient focus issues)
    - activate: try to .restore() + .activate() the window before grab (improves ROI capture fidelity)
    - client: "clubgg" | "coinpoker" — determines window hints (auto from title if omitted) and reporting
    - window_hint: str or list[str] override (for WINDOW_HINT compat); if None uses per-client default
    """
    if client is None:
        client = DEFAULT_CLIENT
    if window_hint is None:
        chints = CLIENT_WINDOW_HINTS.get(client, CLIENT_WINDOW_HINTS[DEFAULT_CLIENT])
        window_hint = chints[0] if chints else WINDOW_HINT
    if delay > 0 and not silent:
        cname = CLIENT_DEFAULT_NAMES.get(client, "poker")
        print(f"PokerFlex capture — grabbing in {delay}s. Bring the {cname} table to the front…")
        for i in range(delay, 0, -1):
            print(f"  {i}…", flush=True)
            time.sleep(1)
    elif delay > 0:
        time.sleep(delay)

    found = None
    title = ""
    bbox = None
    matched_client = client or DEFAULT_CLIENT
    for attempt in range(retries + 1):
        found = find_window_bbox(window_hint, client=client)
        if found:
            if len(found) == 3:
                bbox, title, matched_client = found
            else:
                bbox, title = found[0], found[1]
            # Further robustness: attempt to bring window forward for reliable capture in bg/live
            if activate:
                try:
                    import pygetwindow as gw
                    for ww in gw.getAllWindows():
                        t = (ww.title or "").lower()
                        if title and (title.lower() in t or t in title.lower()) and ww.width > 100:
                            try:
                                if getattr(ww, "isMinimized", False):
                                    ww.restore()
                                ww.activate()
                            except Exception:
                                pass
                            try:
                                time.sleep(0.12)
                            except Exception:
                                pass
                            break
                except Exception:
                    pass  # no pygetwindow or activate fail: still proceed with bbox we have
            break
        else:
            if attempt < retries:
                if not silent:
                    cname = CLIENT_DEFAULT_NAMES.get(matched_client or DEFAULT_CLIENT, "table")
                    print(f"[capture] {cname} window not found (attempt {attempt+1}/{retries+1}), retrying briefly...")
                try:
                    time.sleep(0.25)
                except Exception:
                    pass
            continue

    if found and bbox:
        if not silent:
            cname = CLIENT_DEFAULT_NAMES.get(matched_client or DEFAULT_CLIENT, "poker")
            print(f"Found {cname} window: '{title}'  bbox={bbox}")
        img = ImageGrab.grab(bbox=bbox)
    else:
        if not silent:
            cname = CLIENT_DEFAULT_NAMES.get(matched_client or DEFAULT_CLIENT, "poker")
            print(f"No {cname} window located (pygetwindow not installed, or window not found after retries) "
                  "— grabbing full screen instead.")
        img = ImageGrab.grab(all_screens=True)

    img.save(output_path)
    if not silent:
        print(f"Saved {output_path}  ({img.width}x{img.height}px).")
    return output_path


# Alias for clarity / future (delegates; keeps capture_clubgg_image name for zero-breakage)
def capture_poker_image(*args, **kwargs) -> str:
    """Generalized capture (see capture_clubgg_image for full docs + client= support)."""
    return capture_clubgg_image(*args, **kwargs)


# =============================================================================
# Vision / OCR + CV layer for real-time poker table reading (ClubGG / CoinPoker, enhanced pipeline)
# Now provides functional basic auto-extract for --live / --auto-capture in run_brain.
# Client-abstracted: window finding (with auto title detect) + ROI heuristics (get_poker_rois per client) for hero (bottom) + board (center).
# Card detection via cv2 contours (sprite rects) + per-card OCR/templatematch.
# Robust: partial reads (e.g. only flop or 1 hole), confidence, always-safe dict, fallbacks.
# Template loader ready (drop PNGs in card_templates/ named Ah.png etc for matchTemplate).
# Per-client vision_config profiles auto used when client passed.
# =============================================================================

# Card suit unicode + letter normalization (ClubGG / CoinPoker sprites often yield symbols or letters via OCR)
SUIT_MAP = {
    "s": "s", "h": "h", "d": "d", "c": "c",
    "♠": "s", "♥": "h", "♦": "d", "♣": "c",
    "S": "s", "H": "h", "D": "d", "C": "c",
}
RANK_MAP = {"10": "T", "t": "T", "1": "T"}  # handle 10->T and partial OCR of '10'


def _normalize_card_token(tok: str) -> str | None:
    """Turn 'Ah', 'A♥', '10d', 'Ks', 'A h' loose etc into canonical 'Ah' (or None if invalid).
    FURTHER ROBUST: tolerant to common OCR noise on ClubGG sprites (l/I/1 for T/10, o/O/0 for 10, etc).
    Extra partial support: isolated rank or suit attempts, common bleed like 'A h' '1 0s'.
    """
    if not tok:
        return None
    t = "".join(ch for ch in tok.strip().upper() if ch.isalnum() or ch in "♠♣♥♦")
    if len(t) < 2:
        # very partial single-char + later recovery in parse
        return None
    # OCR noise fixes for 10/T (very common on small card text) + better disambig: catch 'lO' '10' '1 0' 'T0' bleed, 'l0' etc
    t = t.replace("O", "0").replace("o", "0").replace("I", "1").replace("l", "1").replace("L", "1").replace("Q", "0")
    t = re.sub(r"1[\s\W_]*0", "10", t)  # '1 0' '1-0' '1_0' etc ->10
    t = re.sub(r"T[\s\W_]*0", "T0", t)  # rare
    t = re.sub(r"[1lI][\s\W_]*[oO0]", "10", t)
    # rank (allow 10) + suit ; unicode recovery (suits kept from clean)
    m = re.match(r"^(10|[2-9TJQKA])([SHDC♠♣♥♦])$", t)
    if not m:
        m = re.match(r"^([2-9TJQKA]|10)([SHDC♠♣♥♦shdc])$", t)
    if not m:
        # extra tolerant for partial OCR e.g. '1 0 d' already cleaned, or 'T0' no; 'A s' handled upstream
        m = re.match(r"^([2-9TJQKA1])(0?)([SHDC♠♣♥♦shdc])$", t)
        if m:
            r = m.group(1)
            if r == "1" or (m.group(2) == "0"):
                r = "T"
            s = m.group(3)
            # reconstruct
            t = r + s
            m = re.match(r"^(10|[2-9TJQKA])([SHDC♠♣♥♦shdc])$", t)
    if not m:
        # additional partial recovery: rank then suit separated or with junk e.g. 'A h' after clean
        m = re.match(r"^([2-9TJQKA])([SHDC♠♣♥♦shdc])$", t)
    if not m:
        # last 10/T catch e.g. lone '10' or 'T' + suit separate handled in parse, here '10s' variant
        m = re.match(r"^(10)([SHDC♠♣♥♦shdc])$", t)
    if not m:
        return None
    r, s = m.group(1).upper(), m.group(2)
    if r in ("10", "1"):
        r = "T"
    s_norm = SUIT_MAP.get(s.lower() if isinstance(s, str) else s, None)
    if not s_norm:
        s_norm = s.lower() if s.lower() in "shdc" else None
    if not s_norm:
        return None
    card = r + s_norm
    if r in "23456789TJQKA" and s_norm in "shdc":
        return card
    return None


def _parse_card_tokens(text: str) -> list[str]:
    """Improved extraction for poker card tokens from OCR (or any text).
    Supports unicode suits (♥ etc from card art OCR), 10/T, mixed case, deduped in appearance order.
    FURTHER ROBUST for partial/ noisy ClubGG OCR: added tolerant patterns, noise cleanup pass.
    Better support for 1-card partials and separated rank/suit (common on small ROI crops).
    Uses/enforces VISION_RANK_WHITELIST indirectly via normalize + extra 10/T patterns.
    """
    if not text:
        return []
    found = []
    # Pre-clean common OCR junk for cards
    cleaned = text.replace(" ", "").replace("\n", " ")
    # Strong pattern: rank immediately followed (opt space) by suit sym/letter
    pat = re.compile(r"(?i)(10|[2-9TJQKA])\s*([SHDC♠♣♥♦])")
    for m in pat.finditer(cleaned):
        tok = m.group(1) + m.group(2)
        norm = _normalize_card_token(tok)
        if norm and norm not in found:
            found.append(norm)
    if not found:
        # legacy loose fallback + extra tolerant (e.g. 10 with noise, single char bleed)
        pat2 = re.compile(r"(10|[2-9TJQKA1lIoO])([SHDC♠♣♥♦shdc]?)", re.IGNORECASE)
        for m in pat2.finditer(cleaned):
            r, s = m.group(1).upper(), (m.group(2) or "").lower()
            if r in ("10", "1", "I", "L", "O"):
                r = "T"
            if r == "T" and s in "shdc♠♣♥♦":
                card = r + s
            else:
                card = r + s if s else ""
            if len(card) == 2 and card not in found:
                # re-norm for safety
                n = _normalize_card_token(card)
                if n and n not in found:
                    found.append(n)
    # one more pass for isolated rank+suit separated by junk
    if len(found) < 2:
        pat3 = re.compile(r"(?i)([2-9TJQKA1])\s*0?\s*([SHDC♠♣♥♦])")
        for m in pat3.finditer(text):
            tok = m.group(1) + m.group(2)
            norm = _normalize_card_token(tok)
            if norm and norm not in found:
                found.append(norm)
    # even more partial-tolerant: try to pair leftover ranks with nearby suits in raw text (for 1-card reads)
    if len(found) < 2:
        ranks = re.findall(r"(?i)\b(10|[2-9TJQKA1])\b", text)
        suits = re.findall(r"[SHDC♠♣♥♦shdc]", text)
        for i, r in enumerate(ranks[:2]):
            rr = "T" if r.upper() in ("10","1","I","L","O") else r.upper()
            ss = suits[i].lower() if i < len(suits) else "s"  # default safe
            ss = SUIT_MAP.get(ss, ss)
            if ss not in "shdc": ss = "s"
            cand = rr + ss
            n = _normalize_card_token(cand)
            if n and n not in found:
                found.append(n)
    # extra 10/T noisy recovery (e.g. '10' split or '1O' 'l0' in raw ocr text)
    if len(found) < 2:
        for m in re.finditer(r"(?i)(10|1[\s\W]*0|T[\s\W]*0|[1lI][\s\W]*[oO0])\s*([SHDC♠♣♥♦shdc]?)", text):
            r = "T"
            s = (m.group(2) or "s").lower()
            ss = SUIT_MAP.get(s, s)
            if ss not in "shdc": ss = "s"
            cand = r + ss
            n = _normalize_card_token(cand)
            if n and n not in found:
                found.append(n)
    # LATEST partial robustness for real vision (1-hole or very noisy crops): recover single rank or suit-only if other pass missed; pair adjacent in text
    if len(found) < 1:
        # last-ditch isolated (e.g. just "A" + later suit, or lone "Ks" fragment)
        for m in re.finditer(r"(?i)([2-9TJQKA1])\s*0?\s*([SHDC♠♣♥♦]?)", text):
            r = m.group(1).upper()
            s = (m.group(2) or "s").lower()
            if r in ("10","1","I","L","O"): r="T"
            ss = SUIT_MAP.get(s, s)
            if ss not in "shdc": ss="s"
            cand = r + ss
            n = _normalize_card_token(cand)
            if n and n not in found:
                found.append(n)
                if len(found) >= 2: break
    return found


def _scale_bbox(bbox: tuple | list, src_w: int, src_h: int, dst_w: int, dst_h: int) -> tuple[int, int, int, int]:
    """Scale a pixel bbox from one resolution to another (used for calibrated profiles)."""
    if not bbox or len(bbox) != 4:
        return bbox
    l, t, r, b = [float(x) for x in bbox]
    if src_w <= 0 or src_h <= 0:
        return int(l), int(t), int(r), int(b)
    sx = float(dst_w) / src_w
    sy = float(dst_h) / src_h
    return (int(l * sx), int(t * sy), int(r * sx), int(b * sy))


def get_poker_rois(width: int, height: int, client: str = "clubgg") -> dict:
    """Generalized poker client ROIs (for ClubGG default or CoinPoker etc).
    Hero cards ~ bottom-center (0.27-0.72 range), board ~ horizontal center.
    Default fractions same or slight CoinPoker tuned (see CLIENT_DEFAULT_ROI_FRACS); calib always overrides via per-client vision_config_*.json (stores "client").
    Returns absolute pixel bboxes. Works for similar aspect; full capture recommended.
    Added pot/action/hud etc for auto-extract in live vision.
    client passed down to load_vision_config for per-client profile selection.
    """
    if client is None:
        client = "clubgg"
    client = str(client).lower()
    if client not in SUPPORTED_CLIENTS:
        client = DEFAULT_CLIENT
    load_vision_config(client=client)  # per-client profile (e.g. vision_config_coinpoker.json) or generic with matching client key
    # after load, if profile specifies different client, honor it (but we passed to prefer file)
    eff_client = VISION_CONFIG_CLIENT or CALIBRATED_CLIENT or client or DEFAULT_CLIENT
    if eff_client not in SUPPORTED_CLIENTS:
        eff_client = client
    if width <= 0 or height <= 0:
        width, height = 1920, 1080
    w, h = width, height

    # Client-aware default built-in fractions (overridden by any CALIBRATED_ROI_FRACTIONS from vision_config*.json)
    d = CLIENT_DEFAULT_ROI_FRACS.get(eff_client, CLIENT_DEFAULT_ROI_FRACS[DEFAULT_CLIENT])
    hero_f = d["hero"]
    board_f = d["board"]
    stack_f = d["hero_stack"]
    pot_f = d["pot"]
    action_bar_f = d["action_bar"]
    hud_f = d["hud"]
    bet_f = d.get("bet") or action_bar_f  # ensure 'bet' text region (falls to action_bar; calib can override; follows pot/action_bar pattern exactly)

    fracs = CALIBRATED_ROI_FRACTIONS or {}
    if fracs:
        # use calibrated fractions if provided (preferred post-calib, client-specific file)
        if "hero" in fracs and len(fracs["hero"]) == 4:
            hero_f = tuple(fracs["hero"])
        if "board" in fracs and len(fracs["board"]) == 4:
            board_f = tuple(fracs["board"])
        if "hero_stack" in fracs and len(fracs["hero_stack"]) == 4:
            stack_f = tuple(fracs["hero_stack"])
        # support new hardened rois in calib profiles (non-breaking if absent)
        if "pot" in fracs and len(fracs["pot"]) == 4:
            pot_f = tuple(fracs["pot"])
        if "action_bar" in fracs and len(fracs["action_bar"]) == 4:
            action_bar_f = tuple(fracs["action_bar"])
        if "bet" in fracs and len(fracs["bet"]) == 4:
            bet_f = tuple(fracs["bet"])
        if "hud" in fracs and len(fracs["hud"]) == 4:
            hud_f = tuple(fracs["hud"])

    # Compute pixel from (possibly calibrated) fractions
    hero = (int(w * hero_f[0]), int(h * hero_f[1]), int(w * hero_f[2]), int(h * hero_f[3]))
    board = (int(w * board_f[0]), int(h * board_f[1]), int(w * board_f[2]), int(h * board_f[3]))
    hero_stack = (int(w * stack_f[0]), int(h * stack_f[1]), int(w * stack_f[2]), int(h * stack_f[3]))
    pot = (int(w * pot_f[0]), int(h * pot_f[1]), int(w * pot_f[2]), int(h * pot_f[3]))
    action_bar = (int(w * action_bar_f[0]), int(h * action_bar_f[1]), int(w * action_bar_f[2]), int(h * action_bar_f[3]))
    hud = (int(w * hud_f[0]), int(h * hud_f[1]), int(w * hud_f[2]), int(h * hud_f[3]))
    bet = (int(w * bet_f[0]), int(h * bet_f[1]), int(w * bet_f[2]), int(h * bet_f[3]))  # 'bet'/'action' text region for bet size / facing OCR (smallest add; reuses action_bar frac if no specific)

    rois = {
        "hero": hero,
        "board": board,
        "hero_stack": hero_stack,
        "pot": pot,
        "action_bar": action_bar,
        "bet": bet,
        "hud": hud,
        "full": (0, 0, w, h),
    }
    # If config had absolute bboxes (legacy/old profiles), scale them from base to current (overrides fractions if present)
    if VISION_CONFIG and isinstance(VISION_CONFIG.get("rois"), dict) and CALIBRATED_BASE_RES:
        src_w, src_h = CALIBRATED_BASE_RES
        for k in ("hero", "board", "hero_stack", "pot", "action_bar", "bet", "hud"):
            if k in VISION_CONFIG["rois"]:
                try:
                    absb = VISION_CONFIG["rois"][k]
                    if isinstance(absb, (list, tuple)) and len(absb) == 4:
                        scaled = _scale_bbox(absb, src_w, src_h, w, h)
                        rois[k] = scaled
                except Exception:
                    pass
    return rois


def get_clubgg_rois(width: int, height: int, client: str = None) -> dict:
    """Backward-compat wrapper around get_poker_rois.
    Defaults to client='clubgg' (or passed client) so all prior calls like get_clubgg_rois(w, h) continue to work unchanged.
    """
    c = client or "clubgg"
    return get_poker_rois(width, height, client=c)


def suggest_auto_rois(image_path: str) -> dict:
    """Auto-ROI suggestion (heuristic, cv2-based) as smart starting point for calibration wizard.
    Detects green felt area + card-like sprite clusters in bottom (hero) and mid (board) zones.
    Returns roi_fractions dict (same shape as CALIBRATED_ROI_FRACTIONS) or built-in defaults if
    no cv2 / no image / detection fails. Used to give user a better-than-hardcoded initial guess
    (detect felt + cards) so fewer manual adjusts needed; user still confirms/adjusts + preview.
    Fully optional; graceful no-op. No new hard deps (cv2 already soft-dep for vision).
    """
    defaults = {
        "hero": [0.275, 0.715, 0.725, 0.94],
        "board": [0.17, 0.355, 0.83, 0.595],
        "hero_stack": [0.36, 0.905, 0.64, 0.985],
        "pot": [0.32, 0.26, 0.68, 0.34],
        "action_bar": [0.28, 0.82, 0.72, 0.90],
        "bet": [0.28, 0.82, 0.72, 0.90],
        "hud": [0.08, 0.22, 0.92, 0.52],
    }
    if not HAS_CV2 or not image_path or not os.path.exists(image_path):
        return defaults
    try:
        import numpy as np
        cvimg = cv2.imread(image_path)
        if cvimg is None or cvimg.size == 0:
            return defaults
        h, w = cvimg.shape[:2]
        # Heuristic 1: green felt detection (ClubGG / CoinPoker tables are typically green felt)
        hsv = cv2.cvtColor(cvimg, cv2.COLOR_BGR2HSV)
        # Broad green range tolerant to lighting/skins (hue ~ green poker felt)
        lower = np.array([30, 30, 30])
        upper = np.array([90, 255, 255])
        felt_mask = cv2.inRange(hsv, lower, upper)
        # Dilate a bit to fill table area
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        felt_mask = cv2.dilate(felt_mask, kernel, iterations=1)
        contours, _ = cv2.findContours(felt_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        felt_bbox = None
        if contours:
            largest = max(contours, key=cv2.contourArea)
            if cv2.contourArea(largest) > (w * h * 0.1):  # meaningful table portion
                felt_bbox = cv2.boundingRect(largest)
        # Heuristic 2: detect card rects (reuse tuned low-sens detector on full image)
        rects = _detect_card_rects(cvimg, None, min_area=500, max_area=30000, sensitivity="low")
        # Classify into zones (fractions of height, tolerant)
        hero_cands = [r for r in rects if r[1] > h * 0.60]  # bottom 40%
        board_cands = [r for r in rects if (h * 0.28 < r[1] < h * 0.62) and (r[1] + r[3] < h * 0.70)]
        # Compute group bboxes + padding (small frac pad for safety)
        pad_x, pad_y = 0.015, 0.025  # ~1.5% horiz, 2.5% vert

        def group_bbox(cands, img_w, img_h):
            if not cands:
                return None
            xs = [r[0] for r in cands]
            ys = [r[1] for r in cands]
            ws = [r[2] for r in cands]
            hs = [r[3] for r in cands]
            l = max(0, int(min(xs) - pad_x * img_w))
            t = max(0, int(min(ys) - pad_y * img_h))
            r = min(img_w, int(max(xs[i] + ws[i] for i in range(len(xs))) + pad_x * img_w))
            b = min(img_h, int(max(ys[i] + hs[i] for i in range(len(ys))) + pad_y * img_h))
            if r <= l or b <= t:
                return None
            return (l, t, r, b)

        def to_fracs(bbox, img_w, img_h):
            if not bbox:
                return None
            l, t, r, b = bbox
            return [round(l / img_w, 4), round(t / img_h, 4), round(r / img_w, 4), round(b / img_h, 4)]

        hero_b = group_bbox(hero_cands, w, h)
        board_b = group_bbox(board_cands, w, h)
        # stack: below hero group or default zone; use bottom-center heuristic
        stack_b = None
        if hero_cands:
            hy = max(r[1] + r[3] for r in hero_cands)
            stack_b = (int(w * 0.34), int(hy + 2), int(w * 0.66), min(h, int(hy + h * 0.08)))
        elif felt_bbox:
            fl, ft, fr, fb = felt_bbox
            stack_b = (int(w * 0.34), int(fb - h * 0.12), int(w * 0.66), int(fb - 4))
        # pot/action/hud keep defaults or rough from felt if avail (non critical for cards)
        pot_b = None
        if felt_bbox:
            fl, ft, fr, fb = felt_bbox
            pot_b = (int(w * 0.30), int(ft + (fb - ft) * 0.18), int(w * 0.70), int(ft + (fb - ft) * 0.28))

        fracs = dict(defaults)  # start from defaults
        hf = to_fracs(hero_b, w, h)
        if hf:
            fracs["hero"] = hf
        bf = to_fracs(board_b, w, h)
        if bf:
            fracs["board"] = bf
        sf = to_fracs(stack_b, w, h)
        if sf:
            fracs["hero_stack"] = sf
        pf = to_fracs(pot_b, w, h)
        if pf:
            fracs["pot"] = pf
        # hud/action_bar remain defaults (text regions less critical for auto card detect)
        # clamp all
        for k in list(fracs.keys()):
            fracs[k] = [max(0.0, min(1.0, float(v))) for v in fracs[k]]
        return fracs
    except Exception:
        return defaults


def _crop_pil(pil_img: "Image", bbox: tuple[int, int, int, int]):
    l, t, r, b = bbox
    return pil_img.crop((l, t, r, b))


def _load_templates() -> dict:
    """Card template loader (for cv2.matchTemplate fallback / calibration).
    Priority (user first for post-calib reliability):
      1. cwd/card_templates/   (easiest for user to drop files; wizard writes here)
      2. ~/.pokerflex/card_templates/
      3. next to capture.py / package card_templates/
      4. plain "card_templates" relative
    Scans for 'Ah.png', '10d.png', 'Ks.jpg' etc. (or user named after calib verify).
    Returns { 'Ah': cv2_img, ... } or {} .
    Wizard populates user dir; live --real-vision benefits immediately (higher conf on match).
    ENSURED: always called after load_vision_config in key paths; user dirs take precedence.
    """
    # Ensure config (ROIs) is also fresh when templates considered (non-breaking)
    try:
        load_vision_config()
    except Exception:
        pass
    templates: dict = {}
    if not HAS_CV2:
        return templates
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.getcwd(), "card_templates"),                    # cwd/user highest priority
        os.path.expanduser(os.path.join("~", ".pokerflex", "card_templates")),  # user global
        os.path.join(here, "card_templates"),                           # package
        "card_templates",                                               # relative
    ]
    tdir = next((c for c in candidates if os.path.isdir(c)), None)
    if not tdir:
        return templates
    try:
        for fname in sorted(os.listdir(tdir)):
            if not fname.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                continue
            base = os.path.splitext(fname)[0].upper()
            m = re.match(r"^(10|[2-9TJQKA])([SHDC])$", base, re.IGNORECASE)
            if not m:
                continue
            r, s = m.group(1).upper(), m.group(2).lower()
            if r == "10":
                r = "T"
            key = r + s
            fpath = os.path.join(tdir, fname)
            try:
                tmpl = cv2.imread(fpath, cv2.IMREAD_COLOR)
                if tmpl is not None and tmpl.size > 0:
                    templates[key] = tmpl
            except Exception:
                pass
    except Exception:
        pass
    return templates


_CARD_TEMPLATES = None


def _get_card_templates() -> dict:
    global _CARD_TEMPLATES
    if _CARD_TEMPLATES is None:
        _CARD_TEMPLATES = _load_templates()
    return _CARD_TEMPLATES


def _get_template_match_score(card_cv, templates: dict | None, sens: str | None = None) -> float:
    """Standalone tmpl score for post-detect boost (used in attempt to credit conf when template matches, even if OCR path picked).
    Stronger integration: always attempt on crops after rect detect.
    """
    if not templates or not HAS_CV2 or card_cv is None or getattr(card_cv, 'size', 0) == 0:
        return 0.0
    try:
        best = -1.0
        gcard = cv2.cvtColor(card_cv, cv2.COLOR_BGR2GRAY) if card_cv.ndim == 3 else card_cv
        for key, tmpl in templates.items():
            if tmpl is None: continue
            try:
                gt = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY) if tmpl.ndim == 3 else tmpl
                scs = [0.85, 0.95, 1.0, 1.1, 1.2] if (sens or VISION_SENSITIVITY) != "high" else [0.95, 1.0, 1.05]
                for sc in scs:
                    nw = max(8, int(gt.shape[1] * sc))
                    nh = max(8, int(gt.shape[0] * sc))
                    if nw > gcard.shape[1] or nh > gcard.shape[0]: continue
                    gts = cv2.resize(gt, (nw, nh), interpolation=cv2.INTER_AREA)
                    r = cv2.matchTemplate(gcard, gts, cv2.TM_CCOEFF_NORMED)
                    _, mv, _, _ = cv2.minMaxLoc(r)
                    if mv > best: best = mv
            except: continue
        return max(0.0, float(best))
    except Exception:
        return 0.0


def _detect_card_rects(cvimg, roi_bbox: tuple | None = None, min_area: int = 800, max_area: int = 22000, sensitivity: str | None = None) -> list[tuple]:
    """Computer vision: locate individual card sprite rectangles (contour based).
    Filters on size + poker-card aspect ratio (~0.55-0.9 w/h for portrait cards).
    Works inside an optional roi_bbox. Returns [(x,y,w,h), ...] sorted left-to-right, deduped.
    This is the 'locate cards spatially' piece for proper ordering (hero left/right, board L->R).

    HARDENED (this task): better aspect filtering (tighter around real card ~0.71 w/h + extent rect check),
    multi-scale contours (for zoom/skin/res variance on ClubGG), morphological ops (close/open tuned for
    typical card borders/frames on green/blue/red felt backgrounds).
    Skin/zoom tolerance: auto-scale min/max_area + minw/h from CALIBRATED_BASE_RES (or DEFAULT_BASE_RES)
    so detection less brittle across user res/zoom after calib or default. More aggressive auto scale.
    """
    if not HAS_CV2 or cvimg is None:
        return []
    sens = sensitivity or VISION_SENSITIVITY
    # tune filters by sensitivity for robustness to partials / noise
    if sens == "high":
        min_area = max(min_area, 1400)
        max_area = min(max_area, 18000)
        ar_lo, ar_hi = 0.58, 0.85
        min_w, min_h = 16, 24
        thr_range = list(range(135, 215, 20))
    elif sens == "low":
        min_area = max(400, min_area - 300)
        max_area = max_area + 4000
        ar_lo, ar_hi = 0.50, 0.92
        min_w, min_h = 12, 18
        thr_range = list(range(110, 235, 15))
    else:
        ar_lo, ar_hi = 0.55, 0.88
        min_w, min_h = 14, 22
        thr_range = list(range(125, 225, 18))

    h, w = cvimg.shape[:2]
    sub = cvimg
    offx = offy = 0
    if roi_bbox:
        l, t, r, b = roi_bbox
        l = max(0, min(l, w))
        r = max(l, min(r, w))
        t = max(0, min(t, h))
        b = max(t, min(b, h))
        if r > l and b > t:
            sub = cvimg[t:b, l:r]
            offx, offy = l, t
    if sub is None or sub.size == 0:
        return []

    # NEW: auto scale areas/dims from calib base (or default) for zoom/res/skin tolerance -- more aggressive
    scale_ref = 1.0
    if VISION_AUTO_SCALE_ROIS:
        try:
            bw, bh = (CALIBRATED_BASE_RES if CALIBRATED_BASE_RES else DEFAULT_BASE_RES)
            if bw > 0 and bh > 0 and w > 0 and h > 0:
                # geometric mean scale for linear dims; area will * sq
                scale_ref = ((float(w) / bw) * (float(h) / bh)) ** 0.5
        except Exception:
            scale_ref = 1.0
    area_scale = max(0.25, min(4.0, scale_ref ** 2))
    min_area = max(200, int(min_area * area_scale))
    max_area = int(max_area * area_scale)
    min_w = max(8, int(min_w * scale_ref))
    min_h = max(10, int(min_h * scale_ref))

    gray = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
    all_rects = []
    # Multi-scale + multiple thresholds + inverse (for dark-bordered ClubGG sprites) + morph for felt variants
    scales = [0.75, 1.0, 1.3] if VISION_DETECTION_MULTISCALE else [1.0]
    for sc in scales:
        try:
            if abs(sc - 1.0) > 0.01:
                sub_sc = cv2.resize(sub, None, fx=sc, fy=sc, interpolation=cv2.INTER_LINEAR)
                gsc = cv2.cvtColor(sub_sc, cv2.COLOR_BGR2GRAY)
            else:
                sub_sc = sub
                gsc = gray
            # Multiple thresholds + inverse help on varying felt/card contrast (green/blue/red skins)
            for thr in thr_range:
                for inv in (False, True):
                    flag = cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY
                    _, bw = cv2.threshold(gsc, thr, 255, flag)
                    if VISION_DETECTION_MORPH:
                        # tuned morph for ClubGG card borders: close to solidify outer frame (common thin border on sprites),
                        # open to drop felt noise specks. RECT kernel good for card rects.
                        try:
                            ksz = 3 if sc > 1.0 else 2
                            km = cv2.getStructuringElement(cv2.MORPH_RECT, (ksz, ksz))
                            bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, km, iterations=1)
                            bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, km, iterations=1)
                        except Exception:
                            pass
                    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for c in contours:
                        x, y, ww, hh = cv2.boundingRect(c)
                        # map back from scale
                        if abs(sc - 1.0) > 0.01:
                            x = int(x / sc)
                            y = int(y / sc)
                            ww = int(ww / sc)
                            hh = int(hh / sc)
                        area = ww * hh
                        if area < min_area or area > max_area or hh == 0:
                            continue
                        ar = ww / float(hh)
                        if not (ar_lo < ar < ar_hi):
                            continue
                        if ww < min_w or hh < min_h:
                            continue
                        # better rect filter: extent (filled ratio) rejects noisy non-card contours
                        try:
                            carea = cv2.contourArea(c)
                            rect_area = float(ww * hh)
                            extent = (carea / rect_area) if rect_area > 0 else 0.0
                            if extent < 0.68:
                                continue
                        except Exception:
                            pass
                        all_rects.append((x + offx, y + offy, ww, hh))
        except Exception:
            continue
    # sort + simple non-max overlap suppression (left to right primary) + iou-ish for better dedup on multi-scale
    all_rects.sort(key=lambda r: (r[0], r[1]))
    filtered = []
    for r in all_rects:
        if not filtered:
            filtered.append(r)
            continue
        x, y, ww, hh = r
        px, py, pw, ph = filtered[-1]
        # close horizontally and vertically overlapping? keep the bigger one
        if abs(x - px) < (min(ww, pw) * 0.65) and abs(y - py) < max(hh, ph) * 0.75:
            if ww * hh > pw * ph:
                filtered[-1] = r
            continue
        # extra: rough iou filter for multi-scale duplicates
        ix1, iy1 = max(x, px), max(y, py)
        ix2, iy2 = min(x + ww, px + pw), min(y + hh, py + ph)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        union = ww * hh + pw * ph - inter
        if union > 0 and (inter / union) > 0.35:
            if ww * hh > pw * ph:
                filtered[-1] = r
            continue
        filtered.append(r)
    return filtered


def _ocr_text_from_pil(pil_img, config: str = "--psm 6 --oem 3") -> str:
    if not (HAS_TESSERACT and pil_img is not None):
        return ""
    try:
        prep = pil_img
        base_level = VISION_PREPROC
        # NEW: adaptive choice (uses image stats + recent confs for ClubGG variance: resize, skin, light, felt)
        preproc_level = _auto_choose_preproc(pil_img, base_level, list(_RECENT_CONFS)) if VISION_ADAPTIVE_PREPROC else base_level
        # Preprocess for better OCR on ClubGG graphical card sprites / HUD text (cv2 preferred for contrast/upscale)
        # HARDENED: now supports adaptive (auto based on stats), + deskew + felt norm + tuned CLAHE params + more.
        # light (default): upscale + otsu binary + light dilate (good balance, prior behavior)
        # aggressive: adds CLAHE (local contrast), bilateral/median denoise, adaptive thresh, extra dilate/erosion tries, optional invert pass.
        # off: minimal (raw crop) for debug/comparison. Improves real-vision partial reads (1-card, flop fragments) + overall conf so live listener auto-updates more reliably with fallback still active.
        if HAS_CV2 and preproc_level != "off":
            try:
                import numpy as np  # transitive from opencv-python
                cv = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
                gray = cv2.cvtColor(cv, cv2.COLOR_BGR2GRAY)
                # NEW deskew for angled cards/HUD on table move/resize
                if preproc_level in ("light", "aggressive"):
                    try:
                        gray = _deskew_gray(gray)
                    except Exception:
                        pass
                # 2x upscale helps small rank/suit text common on poker clients
                gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                if preproc_level == "aggressive":
                    # HARDENED CLAHE params (slightly stronger clip for stylized low-contrast ClubGG cards)
                    try:
                        clahe = cv2.createCLAHE(clipLimit=2.8, tileGridSize=(6, 6))
                        gray = clahe.apply(gray)
                    except Exception:
                        pass
                    # bilateral filter to denoise while preserving edges (card borders/ranks)
                    try:
                        gray = cv2.bilateralFilter(gray, 5, 30, 30)
                    except Exception:
                        pass
                    # median for salt/pepper from compression
                    try:
                        gray = cv2.medianBlur(gray, 3)
                    except Exception:
                        pass
                    # felt color norm (helps different skins / low light green felt bg)
                    try:
                        gray = _normalize_for_felt(gray)
                    except Exception:
                        pass
                elif preproc_level == "light":
                    # light felt touch even on light
                    try:
                        gray = _normalize_for_felt(gray)
                    except Exception:
                        pass
                # High-contrast binary (Otsu works well for white text on dark / colored card regions)
                _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                # Light dilation to connect broken OCR chars (e.g. split '10' or suit pips)
                ksize = 3 if preproc_level == "aggressive" else 2
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (ksize, ksize))
                bw = cv2.dilate(bw, kernel, iterations=1 if preproc_level != "aggressive" else 2)
                if preproc_level == "aggressive":
                    # extra cleanup for aggressive: close small holes, adaptive fallback if needed
                    try:
                        kernel2 = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                        bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel2, iterations=1)
                    except Exception:
                        pass
                    # try adaptive thresh as alt for stubborn regions (merge later if useful)
                    try:
                        ad = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
                        # keep otsu primary but blend lightly not needed; use as prep option would be overkill
                    except Exception:
                        pass
                prep = Image.fromarray(bw)
            except Exception:
                prep = pil_img  # graceful, fall to raw pil
        elif preproc_level == "off":
            prep = pil_img
        return pytesseract.image_to_string(prep, config=config) or ""
    except Exception:
        return ""


def _get_image_stats(pil_img) -> dict:
    """Compute simple image statistics for adaptive preproc choice (low light, low contrast, blur etc for ClubGG stylized cards/felt).
    Uses cv2 if avail (np from it); graceful fallback. Stats drive auto preproc level + deskew decision.
    """
    stats = {"brightness": 128.0, "contrast": 40.0, "sharpness": 50.0, "has_color": True, "w": 100, "h": 100}
    if pil_img is None:
        return stats
    try:
        w, h = pil_img.size
        stats["w"], stats["h"] = w, h
        if HAS_CV2:
            import numpy as np
            cv = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(cv, cv2.COLOR_BGR2GRAY)
            stats["brightness"] = float(np.mean(gray))
            stats["contrast"] = float(np.std(gray))
            # laplacian proxy for sharpness / focus (good for low-light blur detect)
            try:
                lap = cv2.Laplacian(gray, cv2.CV_64F).var()
                stats["sharpness"] = float(min(200.0, lap))
            except Exception:
                stats["sharpness"] = 50.0
            # rough color vs gray for felt normalization
            b, g, r = cv2.split(cv)
            color_var = float(np.std([np.mean(b), np.mean(g), np.mean(r)]))
            stats["has_color"] = color_var > 8.0
        else:
            # PIL fallback approx
            gray = pil_img.convert("L")
            px = list(gray.getdata())
            if px:
                m = sum(px) / len(px)
                stats["brightness"] = m
                stats["contrast"] = (sum(abs(p - m) for p in px) / len(px)) or 30.0
    except Exception:
        pass
    return stats


def _auto_choose_preproc(pil_img, base_level: str = None, recent_confs: list | None = None) -> str:
    """Adaptive preproc chooser (builds on VISION_PREPROC + VISION_ADAPTIVE_PREPROC).
    Inspects stats + recent conf history: low contrast/brightness/sharp -> 'aggressive' (boost CLAHE/deskew/denoise).
    High quality image -> can down to 'light' or respect base.
    Returns one of "off"|"light"|"aggressive". Used inside _ocr and attempt for real captures.
    """
    base = base_level or VISION_PREPROC
    if not VISION_ADAPTIVE_PREPROC or not pil_img:
        return base
    stats = _get_image_stats(pil_img)
    conf_trend = 0.0
    if recent_confs:
        try:
            recent = [float(c) for c in recent_confs if c is not None]
            if len(recent) >= 2:
                conf_trend = sum(recent[-2:]) / 2 - (sum(recent[:2]) / max(1, len(recent)-2)) if len(recent) > 3 else 0
        except Exception:
            pass
    # decision logic for stylized ClubGG: low contrast or dim or blurry -> aggressive for better OCR on sprites
    low_contrast = stats.get("contrast", 50) < 28
    low_bright = stats.get("brightness", 120) < 70 or stats.get("brightness", 120) > 210  # too dark or washed
    low_sharp = stats.get("sharpness", 60) < 25
    recent_low_conf = (recent_confs and len(recent_confs) > 0 and sum(float(c or 0) for c in recent_confs[-3:]) / max(1, min(3, len(recent_confs))) < 0.35)
    if low_contrast or low_bright or low_sharp or recent_low_conf or conf_trend < -0.15:
        return "aggressive"
    if base == "off":
        return "off"
    # otherwise keep or bump base lightly
    return base


def _deskew_gray(gray):
    """Simple deskew for better OCR on rotated/angled ClubGG card text or HUD (common on table resize/skew).
    Uses minAreaRect or hough; returns rotated gray or original on fail. Only for pre-OCR crops.
    """
    if not HAS_CV2 or gray is None:
        return gray
    try:
        import numpy as np
        # threshold for text edges
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        coords = np.column_stack(np.where(bw > 0))
        if coords.shape[0] < 20:
            return gray
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        if abs(angle) < 0.6 or abs(angle) > 30:
            return gray  # negligible or extreme
        (h, w) = gray.shape[:2]
        M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        deskewed = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        return deskewed
    except Exception:
        return gray


def _normalize_for_felt(gray_or_bgr):
    """Color / contrast norm targeted at green felt backgrounds + stylized card art (helps low light / diff skins).
    Returns processed gray for OCR path.
    """
    if not HAS_CV2:
        return gray_or_bgr
    try:
        import numpy as np
        if gray_or_bgr.ndim == 3:
            g = cv2.cvtColor(gray_or_bgr, cv2.COLOR_BGR2GRAY)
        else:
            g = gray_or_bgr
        # light CLAHE always here for felt (even if not aggressive base)
        try:
            clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(6, 6))
            g = clahe.apply(g)
        except Exception:
            pass
        # simple green bias suppression (if original color available upstream) - here just hist eq lite
        g = cv2.equalizeHist(g)
        return g
    except Exception:
        return gray_or_bgr


def _get_card_suit_color_hint(card_cv) -> str | None:
    """Simple color-based suit heuristic (red vs black) for ClubGG card sprites.
    Inspects lower portion of crop (where large suit pip/symbol usually rendered) for r-dominant vs others.
    Returns 'red' (hearts/diamonds) or 'black' (spades/clubs) or None.
    Used before/during OCR+parse to filter mismatched suit OCR (e.g. 'As' on red crop -> distrust or bias),
    improves robustness on low-contrast/colored felt/varied skins where suit glyph OCR fails but color is clear.
    """
    if not VISION_SUIT_COLOR_HEURISTIC or not HAS_CV2 or card_cv is None or getattr(card_cv, 'size', 0) == 0:
        return None
    try:
        import numpy as np
        h, w = card_cv.shape[:2]
        # focus bottom ~45% (big pip common on ClubGG cards) + avoid pure white border
        y0 = int(h * 0.52)
        x0, x1 = int(w * 0.15), int(w * 0.85)
        roi = card_cv[y0:, x0:x1] if y0 < h and x0 < x1 else card_cv
        if roi.size == 0 or roi.ndim != 3:
            return None
        # avg per channel
        avg_b = float(np.mean(roi[:, :, 0]))
        avg_g = float(np.mean(roi[:, :, 1]))
        avg_r = float(np.mean(roi[:, :, 2]))
        # red suit if r clearly dominates (tuned loose for stylized art / lighting)
        if avg_r > (avg_g + 12) and avg_r > (avg_b + 12):
            return "red"
        # else assume black (or very dark); neutral if all low contrast
        if (avg_r + avg_g + avg_b) > 60:
            return "black"
        return None
    except Exception:
        return None


def _apply_suit_color_to_candidate(card: str, color: str | None) -> str:
    """If color heuristic available and mismatches card's OCR suit, demote or leave (ambiguous h/d or s/c).
    For simple: if mismatch, return original but caller can lower weight; here just identity for compat.
    (Can extend later to rank+color only if needed, but full disambig still needs OCR letter.)
    """
    if not card or len(card) != 2 or not color:
        return card
    s = card[1].lower()
    is_red = s in ("h", "d")
    is_black = s in ("s", "c")
    if color == "red" and is_black:
        # mismatch; for now return as-is (weight will be reduced upstream); could map s->h d->? but risk wrong
        return card
    if color == "black" and is_red:
        return card
    return card


def _recognize_card_from_crop(card_pil, card_cv=None, templates: dict | None = None, sensitivity: str | None = None) -> str | None:
    """Recognize a single card crop: prefer tuned OCR (card whitelist friendly), fallback to template match.
    Returns 'Ah' style or None on failure / low conf.
    Robust to partial reads: more OCR configs + relaxed template score on 'low' sens; stricter on 'high'.
    Handles common ClubGG OCR noise (e.g. split 10, unicode, single char bleed).
    NEW: card-specific whitelist configs for rank/suit only; multi-scale template matching.
    HARDENED (this task): always try matchTemplate BEFORE or alongside OCR (stronger integration);
    if high tmpl score (>=0.82) short-circuit return for speed+reliability (user templates from calib win);
    add more PSM modes (incl 10/12) + oem 1+3 combos; use central VISION_RANK_WHITELIST; color-based suit
    heuristic (red/black) applied to bias/weight ocr cands before vote (filter color-mismatch suits);
    better 10/T disambig via enhanced parser + whitelist; unicode suits in whitelist+map.
    Template match boosts final conf (see attempt + VISION_TEMPLATE_CONF_BOOST).
    """
    sens = sensitivity or VISION_SENSITIVITY
    # Card-focused configs: more PSM (incl 10 for sparse, 12 for sparse text) + oem 1 (LSTM only good for modern) +3 ;
    # whitelist from global + unicode + 10 for better 10/T ; restricts junk on stylized ClubGG sprites.
    wl = VISION_RANK_WHITELIST + "SHDCAshdc♠♥♦♣"
    ocr_cfgs = [
        f"--psm 7 --oem 3 -c tessedit_char_whitelist={wl}",
        f"--psm 11 --oem 3 -c tessedit_char_whitelist={wl}",
        f"--psm 6 --oem 3 -c tessedit_char_whitelist={wl}",
        f"--psm 10 --oem 1 -c tessedit_char_whitelist={wl}",
        f"--psm 12 --oem 3 -c tessedit_char_whitelist={wl}",
        "--psm 8 --oem 3",
        f"--psm 13 --oem 1 -c tessedit_char_whitelist={wl}",
    ]
    if sens == "low":
        ocr_cfgs = ocr_cfgs + [
            f"--psm 4 --oem 3 -c tessedit_char_whitelist={wl}",
            "--psm 3 --oem 3",
            "--psm 0 --oem 1",
        ]  # more permissive for partials/noisy
    elif sens == "high":
        ocr_cfgs = [
            f"--psm 7 --oem 3 -c tessedit_char_whitelist={wl}",
            f"--psm 11 --oem 3 -c tessedit_char_whitelist={wl}",
            f"--psm 6 --oem 3 -c tessedit_char_whitelist={wl}",
            f"--psm 10 --oem 1 -c tessedit_char_whitelist={wl}",
        ]  # focused, less hallucination

    # STRONGER TEMPLATE: always compute first (before OCR) for high-conf short circuit + fusion; user+pkg win on match
    tmpl_pick = None
    tmpl_score = 0.0
    tmpl_thresh = 0.72 if sens == "high" else (0.55 if sens == "low" else 0.62)
    high_tmpl_thresh = 0.82  # strong integration: trust template heavily if excellent match (calib templates)
    if templates and HAS_CV2 and card_cv is not None:
        try:
            best_key = None
            best_score = -1.0
            gcard = cv2.cvtColor(card_cv, cv2.COLOR_BGR2GRAY) if card_cv.ndim == 3 else card_cv
            for key, tmpl in templates.items():
                if tmpl is None:
                    continue
                try:
                    gt = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY) if tmpl.ndim == 3 else tmpl
                    # Multi-scale: try resize template to better fit crop (handles ClubGG zoom/res differences)
                    scales = [0.80, 0.92, 1.0, 1.10, 1.22] if sens != "high" else [0.92, 1.0, 1.08]
                    for sc in scales:
                        try:
                            new_w = max(8, int(gt.shape[1] * sc))
                            new_h = max(8, int(gt.shape[0] * sc))
                            if new_w > gcard.shape[1] or new_h > gcard.shape[0]:
                                continue
                            gt_s = cv2.resize(gt, (new_w, new_h), interpolation=cv2.INTER_AREA)
                            res = cv2.matchTemplate(gcard, gt_s, cv2.TM_CCOEFF_NORMED)
                            _, mv, _, _ = cv2.minMaxLoc(res)
                            if mv > best_score:
                                best_score = mv
                                best_key = key
                        except Exception:
                            continue
                except Exception:
                    continue
            if best_key and best_score >= tmpl_thresh:
                tmpl_pick = best_key
                tmpl_score = float(best_score)
                if best_score >= high_tmpl_thresh:
                    # strong template match -> return early (before heavy ocr), high reliability for real skins
                    return tmpl_pick
        except Exception:
            pass

    # Color heuristic (red/black) BEFORE heavy OCR/voting: get once, use to weight/filter ocr cands
    color = _get_card_suit_color_hint(card_cv)

    candidates = []  # (card, ocr_weight, src)
    ocr_weight_sum = 0.0
    if VISION_OCR_VOTING and HAS_TESSERACT:
        # multi-psm voting + conf aggregation + oem combos + color bias
        for cfg in ocr_cfgs:
            try:
                txt = _ocr_text_from_pil(card_pil, cfg)
                # try data for confs (secondary full for labels done upstream)
                data_conf = 0.6
                try:
                    if HAS_TESSERACT:
                        d = pytesseract.image_to_data(card_pil, config=cfg, output_type=pytesseract.Output.DICT)
                        cs = [int(c) for c in d.get("conf", []) if str(c).isdigit() and int(c) > 0]
                        if cs:
                            data_conf = (sum(cs) / len(cs)) / 100.0
                except Exception:
                    pass
                cards = _parse_card_tokens(txt)
                if cards:
                    c = cards[0]
                    w = max(0.3, min(0.99, data_conf))
                    # apply color heuristic: reduce weight on color-suit mismatch (e.g. black OCR suit on red crop)
                    c = _apply_suit_color_to_candidate(c, color)
                    if color:
                        s = c[1] if len(c) > 1 else ""
                        is_red = s in "hd"
                        is_black = s in "sc"
                        if (color == "red" and is_black) or (color == "black" and is_red):
                            w *= 0.55  # penalize mismatch, still allow if other strong signals
                    candidates.append((c, w, "ocr"))
                    ocr_weight_sum += w
            except Exception:
                continue
    else:
        # legacy single pass
        for cfg in ocr_cfgs:
            txt = _ocr_text_from_pil(card_pil, cfg)
            cards = _parse_card_tokens(txt)
            if cards:
                c = cards[0]
                c = _apply_suit_color_to_candidate(c, color)
                candidates.append((c, 0.7, "ocr"))
                break

    # pick best from ocr votes (majority weighted)
    ocr_pick = None
    ocr_best_w = -1.0
    if candidates:
        from collections import defaultdict
        vote = defaultdict(float)
        for c, w, _ in candidates:
            vote[c] += w
        ocr_pick = max(vote.items(), key=lambda kv: kv[1])[0] if vote else None
        ocr_best_w = vote.get(ocr_pick, 0.5) if ocr_pick else 0.5
        # final color bias on pick: if mismatch prefer tmpl if avail
        if ocr_pick and color:
            s = ocr_pick[1] if len(ocr_pick)>1 else ""
            if (color=="red" and s in "sc") or (color=="black" and s in "hd"):
                if tmpl_pick:
                    return tmpl_pick

    # FUSION + vote decision (HARDENED, template always considered)
    if ocr_pick and tmpl_pick:
        # fuse: prefer if both agree, or weight ocr higher + tmpl bonus; template boost feeds conf later
        if ocr_pick == tmpl_pick:
            return ocr_pick
        fused_ocr = ocr_best_w + (0.25 if tmpl_score > 0.6 else 0)
        fused_tmpl = tmpl_score + 0.15
        if fused_ocr >= fused_tmpl:
            return ocr_pick
        return tmpl_pick
    if ocr_pick:
        return ocr_pick
    if tmpl_pick:
        return tmpl_pick
    # last legacy single if voting off or nothing
    for cfg in ocr_cfgs:
        txt = _ocr_text_from_pil(card_pil, cfg)
        cards = _parse_card_tokens(txt)
        if cards:
            c = cards[0]
            c = _apply_suit_color_to_candidate(c, color)
            return c
    return None


def attempt_vision_parse(image_path: str, silent: bool = False, sensitivity: str | None = None, min_conf: float = 0.0, partial_min_conf: float = 0.0, debug: bool | None = None, preprocess: str | None = None, history_len: int | None = None, client: str = None) -> dict:
    """Client-aware (clubgg|coinpoker default clubgg) vision parse: image -> ROIs (get_poker_rois(client) or get_clubgg_rois wrapper) -> card rect detection (cv) ->
    per-card recognition (tesseract OCR on crops preferred, template fallback + HARDENED voting) ->
    hand (bottom 2), board (center 0-5), position (text labels) + pot, facing_bet, street, action_hint, villain_count, bet_to_call, facing_action (from bet ROI + improved extract).
    client= passed to get_poker_rois + load_vision_config (selects per-client profile) + attached to result.

    Returns rich dict always safe for live state updates:
      {'hand': 'AhKs', 'board': 'Qd7h2c', 'position': 'BTN', 'confidence': 0.72,
       'raw_cards': [...], 'detected_card_rects': {'hero':2,'board':3}, 'method': 'roi+cv+ocr',
       'partial': True/False, 'pot': '12.5', 'facing_bet': '4', 'street': 'flop', 'action_hint': 'facing_call', 'client': ..., ...}

    HARDENED (this task) for real-OCR reliability on varied ClubGG / CoinPoker skins/res/zoom/lighting/felt:
    - Card sprite _detect_card_rects: better aspect (tighter ~0.71), multi-scale contours, morph ops for borders, auto-scale area/w/h from calib base (aggressive) + default for zoom tolerance.
    - OCR robustness in _ocr_text_from_pil + attempt: more PSM (4/6/7/8/10/11/12/13) + oem(1+3), simple color-based suit (red/black heuristic pre-vote), better 10/T disambig+unicode recovery, rank whitelist.
    - Template matching stronger: _get_template... + always try matchTemplate on crops before/alongside OCR in _recognize (high-score short-circuit), boost conf via VISION_TEMPLATE_CONF_BOOST.
    - Pot/bet hardened: extract_pot_size/extract_bet_info now handle "Pot: 12.50", "Call 4.5", "Raise To 12", $ / bb-only, more regex + _parse_amt tolerant.
    - New tunables in globals + set_vision_params (template_conf_boost, suit_color_heur, detection_* , auto_scale).
    - simulate updated w/ more noisy partials; all feeds to live listener (pot/facing_bet/street/action_hint) for A1 future facing.
    - 100% compat for simulate, calib profiles, partials, notes, ICM, history, A1 default.
    - Uses ROIs + extract_ + detect_street... + adaptive etc.
    Callers (esp live listener) benefit immediately: pot/bet auto in state for future advisor facing decisions.

    Preserves 100% backward for hand/board/pos/stack/partial/simulate/notes/ICM/A1 (omit client or use default).
    """
    if debug is not None or preprocess is not None:
        try:
            set_vision_params(debug=debug, preprocess=preprocess)
        except Exception:
            pass
    if not image_path or not os.path.exists(image_path):
        return {"confidence": 0.0, "reason": "no_image", "client": client or DEFAULT_CLIENT}

    if client is None:
        client = (VISION_CONFIG or {}).get("client") or CALIBRATED_CLIENT or DEFAULT_CLIENT
    if client not in SUPPORTED_CLIENTS:
        client = DEFAULT_CLIENT

    # ENSURE per-client vision_config (vision_config_coinpoker.json etc) + card_templates respected (load + template cache)
    try:
        load_vision_config(force_reload=False, client=client)
        # templates loaded on demand via _get_card_templates below
    except Exception:
        pass

    result: dict = {"confidence": 0.0}
    pil_img = None
    cv_img = None
    try:
        pil_img = Image.open(image_path)
        w, h = pil_img.size
        result["image_size"] = [w, h]
        rois = get_poker_rois(w, h, client=client)
        result["rois"] = {k: list(v) for k, v in rois.items()}
        result["client"] = client
        if HAS_CV2:
            cv_img = cv2.imread(image_path)
    except Exception as ex:
        if not silent:
            print(f"[vision] load error: {ex}")
        return {"confidence": 0.0, "error": str(ex), "client": client or DEFAULT_CLIENT}

    sens = sensitivity or VISION_SENSITIVITY
    result["sensitivity"] = sens
    # NEW: sync history len if passed (for live CLI)
    if history_len is not None:
        try:
            set_vision_params(history_len=history_len)
        except Exception:
            pass
    # ensure adaptive/preproc globals respected (set may have been called)
    pre = preprocess or VISION_PREPROC
    if pre in ("off", "light", "aggressive"):
        # note: actual auto happens inside _ocr_text_from_pil via _auto_choose
        pass

    # Full image OCR (good for position labels, any text HUD, fallback cards)
    full_ocr = ""
    if HAS_TESSERACT and pil_img is not None:
        full_ocr = _ocr_text_from_pil(pil_img, "--psm 6 --oem 3")
        # also try one more oem/psm for HUD robustness (concat for extractors)
        try:
            full_ocr += " " + _ocr_text_from_pil(pil_img, "--psm 11 --oem 1")
        except Exception:
            pass
        if not silent:
            preview = (full_ocr[:220] + "...") if len(full_ocr) > 220 else full_ocr
            print(f"[vision] tesseract full-image: {preview!r}")

    cards_from_full = _parse_card_tokens(full_ocr)

    # Dedicated ROI OCRs early (hero/board/stack crops) for richer text used by pos/stack/card fallbacks
    # HARDENED: also OCR new pot/action/hud ROIs for bet/pot extraction, street/action hints, villain HUD labels
    roi_ocr_text = ""
    roi_ocrs = {}
    if HAS_TESSERACT and pil_img is not None:
        try:
            hroi = rois.get("hero")
            if hroi:
                hcrop = _crop_pil(pil_img, hroi)
                ht = _ocr_text_from_pil(hcrop, "--psm 6")
                roi_ocr_text += " " + ht
                roi_ocrs["hero"] = ht
            broi = rois.get("board")
            if broi:
                bcrop = _crop_pil(pil_img, broi)
                bt = _ocr_text_from_pil(bcrop, "--psm 6")
                roi_ocr_text += " " + bt
                roi_ocrs["board"] = bt
            sroi = rois.get("hero_stack")
            if sroi:
                scrop = _crop_pil(pil_img, sroi)
                st = _ocr_text_from_pil(scrop, "--psm 7")
                roi_ocr_text += " " + st
                roi_ocrs["hero_stack"] = st
            # NEW rois (HARDENED: more PSM + oem for pot/bet/action HUD text robustness on varied ClubGG UI skins)
            extra_psms = ["--psm 6 --oem 3", "--psm 7 --oem 3", "--psm 11 --oem 1", "--psm 4 --oem 3"]
            for k in ("pot", "action_bar", "bet", "hud"):
                r = rois.get(k)
                if r:
                    try:
                        c = _crop_pil(pil_img, r)
                        best_t = ""
                        for pcfg in (["--psm 6" if k != "action_bar" else "--psm 7"] + extra_psms):
                            try:
                                tt = _ocr_text_from_pil(c, pcfg)
                                if len(tt) > len(best_t) or (re.search(r'\d', tt) and not re.search(r'\d', best_t)):
                                    best_t = tt
                            except: pass
                        t = best_t or _ocr_text_from_pil(c, "--psm 6" if k != "action_bar" else "--psm 7")
                        roi_ocr_text += " " + t
                        roi_ocrs[k] = t
                    except Exception:
                        pass
        except Exception:
            pass
    cards_from_roi = _parse_card_tokens(roi_ocr_text)
    # merge for fallbacks
    for c in cards_from_roi:
        if c not in cards_from_full:
            cards_from_full.append(c)

    # Position from any visible text labels (improved: more variants + hero cues + roi text)
    # FURTHER: expanded keywords + mappings for real ClubGG labels (small blind etc); prefer specific over generic
    pos_cand = None
    ocr_u = ((full_ocr or "") + " " + (roi_ocr_text or "")).upper()
    pos_candidates = [
        ("BTN", "BUTTON", "DEALER", "DLR"),
        ("CO", "CUTOFF", "CUT"),
        ("HJ", "HIJACK"),
        ("MP", "MIDDLE", "MP2", "MP1"),
        ("UTG", "UNDER", "UTG+1", "UTG1"),
        ("SB", "SMALL BLIND", "SMALL", "SB"),
        ("BB", "BIG BLIND", "BIG", "BB"),
        ("HERO", "YOU", "ME"),
    ]
    for group in pos_candidates:
        for cand in group:
            if cand in ocr_u:
                # map to canonical short
                if "BTN" in group or "BUTTON" in group or "DEALER" in group:
                    pos_cand = "BTN"
                elif "CO" in group or "CUTOFF" in group:
                    pos_cand = "CO"
                elif "HJ" in group:
                    pos_cand = "HJ"
                elif "MP" in group:
                    pos_cand = "MP"
                elif "UTG" in group:
                    pos_cand = "UTG"
                elif "SB" in group or "SMALL" in group:
                    pos_cand = "SB"
                elif "BB" in group or "BIG" in group:
                    pos_cand = "BB"
                else:
                    pos_cand = group[0]
                break
        if pos_cand:
            break
    if pos_cand:
        result["position"] = pos_cand

    # Stack extraction from ROI/full OCR text (supports "125", "100.5", "80bb" etc -> numeric bb string for runner state)
    # FURTHER ENHANCED for real-time robustness: more tolerant patterns for ClubGG HUDs (incl "Stack:125", "eff 80bb", "$125.5", "125 BBs", "effective stack 100", "pot 80" ignore, leading $ or text labels)
    stack_ocr_src = (full_ocr or "") + " " + (roi_ocr_text or "")
    stack_cand = None
    # Primary tolerant patterns (labels + units + optional $ + decimals)
    for m in re.finditer(r"(?i)(?:stack|eff|effective|hero|bb|chips?)?\s*[:=\-]?\s*[\$]?\b(\d{1,4}(?:\.\d{1,2})?)\s*(?:bb|BB|bBs|bb's|BBs|chips?)?\b", stack_ocr_src):
        try:
            val = float(m.group(1))
            if 1.0 < val < 5000:
                if stack_cand is None or val > float(stack_cand):
                    stack_cand = str(int(val) if val == int(val) else round(val, 1))
        except Exception:
            pass
    for m in re.finditer(r"[\$]?\b(\d{1,4}(?:\.\d{1,2})?)\s*(?:bb|BB|bb's|BBs)?\b", stack_ocr_src, re.IGNORECASE):
        try:
            val = float(m.group(1))
            if 1.0 < val < 5000:
                if stack_cand is None or val > float(stack_cand):
                    stack_cand = str(int(val) if val == int(val) else round(val, 1))
        except Exception:
            pass
    # fallback broader if nothing
    if not stack_cand:
        for m in re.finditer(r"\b(\d{1,4}(?:\.\d)?)\b", stack_ocr_src):
            try:
                val = float(m.group(1))
                if 1.0 < val < 5000:
                    if stack_cand is None or val > float(stack_cand):
                        stack_cand = str(int(val) if val == int(val) else round(val, 1))
            except Exception:
                pass
    if stack_cand:
        result["stack"] = stack_cand

    # NEW (hardened vision): extract pot, facing bet, street/action hints, villain info from enhanced roi_ocr + full.
    # Uses dedicated extract_* + detect_ helpers + new ROIs. Populates for live listener auto state (usable for facing decisions).
    # Always additive; graceful if no text. Also runs secondary full-ocr for HUD villain labels.
    if VISION_STREET_ACTION:
        try:
            pot_val = extract_pot_size(full_ocr, roi_ocr_text)
            if pot_val:
                result["pot"] = pot_val
            bet_info = extract_bet_info(full_ocr, roi_ocr_text, roi_ocrs.get("bet") or roi_ocrs.get("action_bar", ""))
            for kk in ("facing_bet", "call_amount", "action_hint", "bet_to", "bet_to_call"):
                if bet_info.get(kk):
                    result[kk] = bet_info[kk]
            street_act = detect_street_and_action(pil_img, full_ocr, roi_ocrs)
            for kk in ("street", "action_hint"):
                if street_act.get(kk) and kk not in result:
                    result[kk] = street_act[kk]
            # villain HUD parse + ENHANCED auto position / stack / num_opponents extraction from HUD (hud ROI + OCR)
            # Uses keywords like "BTN", "SB", numbers near names (e.g. "fish (CO) 85", "v1 BTN 120.0", "Hero SB 40")
            # Populates position (hero), stack (tolerant), opponents/villain_count for live listener.
            # Graceful fallback: if vision/HUD misses, caller (run_brain _robust) keeps user preset or last known from current_inputs.
            hud_txt = (roi_ocrs.get("hud", "") or "") + " " + (full_ocr or "")
            if hud_txt:
                hud_u = hud_txt.upper()
                vpos = []
                for grp in [("BTN", "BUTTON", "DEALER", "DLR"), ("CO", "CUTOFF", "CUT"), ("HJ", "HIJACK"), ("MP", "MIDDLE"), ("UTG", "UNDER"), ("SB", "SMALL BLIND", "SMALL"), ("BB", "BIG BLIND", "BIG")]:
                    for c in grp:
                        if c in hud_u:
                            vpos.append(grp[0])
                            break
                # Enhanced: parse "name pos stack" style entries near names for accurate opp count + hero pos detection
                # e.g. regex catches player labels + pos + nearby numeric stack
                player_entries = re.findall(r'([A-Za-z][\w_]{1,12})\s*[\(\[]?\s*(BTN|SB|BB|CO|HJ|MP|UTG|BUTTON|SMALL|BIG|DEALER)\s*[\)\]]?\s*[\$]?\s*(\d{1,4}(?:\.\d{1,2})?)', hud_txt, re.IGNORECASE)
                if player_entries:
                    # count as villains (hero usually also appears or separate; conservative use #entries or + adjust)
                    vcount = max(1, min(9, len(player_entries)))
                    normed = []
                    for _, ptag, _ in player_entries:
                        p = ptag.upper()
                        if 'BTN' in p or 'DEAL' in p: normed.append('BTN')
                        elif 'SB' in p or 'SM' in p: normed.append('SB')
                        elif 'BB' in p or 'BI' in p: normed.append('BB')
                        elif 'CO' in p or 'CUT' in p: normed.append('CO')
                        elif 'HJ' in p: normed.append('HJ')
                        elif 'MP' in p: normed.append('MP')
                        elif 'UTG' in p or 'UND' in p: normed.append('UTG')
                    if normed:
                        result["villain_positions"] = ",".join(list(dict.fromkeys(normed))[:5])
                    result["villain_count"] = str(vcount)
                    result["opponents"] = str(max(1, vcount))  # feed directly for GameState
                    # if hero pos not yet, try detect if HUD labels hero seat e.g. "Hero BTN 99" or your name pattern (common in clubgg HUD)
                    if not result.get("position"):
                        for name, ptag, _ in player_entries:
                            if re.search(r'(hero|you|me|seat0|user|player_you)', name, re.I):
                                p = ptag.upper()
                                if 'BTN' in p or 'DEAL' in p: result["position"] = "BTN"
                                elif 'SB' in p or 'SM' in p: result["position"] = "SB"
                                elif 'BB' in p or 'BI' in p: result["position"] = "BB"
                                elif 'CO' in p: result["position"] = "CO"
                                elif 'HJ' in p: result["position"] = "HJ"
                                elif 'MP' in p: result["position"] = "MP"
                                elif 'UTG' in p: result["position"] = "UTG"
                                break
                else:
                    # fallback count using nums near pos keywords (original rough + improved)
                    nums = re.findall(r"\b(\d{1,3})\b", hud_txt)
                    vcount = max(1, min(9, len([n for n in nums if 1 < int(n) < 400]) // 2 or len(vpos) or 2))
                    if vpos:
                        result["villain_positions"] = ",".join(vpos[:4])
                    result["villain_count"] = str(vcount)
                    result["opponents"] = str(vcount)
                # also try hero pos from hud labels if still missing (keywords + context)
                if not result.get("position"):
                    for grp in [("BTN", "BUTTON", "DEALER"), ("SB", "SMALL"), ("BB", "BIG"), ("CO", "CUTOFF"), ("HJ",), ("MP",), ("UTG",)]:
                        for c in grp:
                            if c in hud_u:
                                if "BTN" in grp or "BUTTON" in grp or "DEALER" in grp:
                                    result["position"] = "BTN"
                                elif "SB" in grp or "SMALL" in grp:
                                    result["position"] = "SB"
                                elif "BB" in grp or "BIG" in grp:
                                    result["position"] = "BB"
                                elif "CO" in grp:
                                    result["position"] = "CO"
                                else:
                                    result["position"] = grp[0]
                                break
                        if result.get("position"):
                            break
                # stack from hud numbers near names too (supplement hero_stack roi)
                if not result.get("stack"):
                    for m in re.finditer(r'(?:hero|you|me|seat)\s*[\(\[]?\s*(?:BTN|SB|BB|CO)?\s*[\)\]]?\s*[\$]?\s*(\d{1,4}(?:\.\d{1,2})?)', hud_txt, re.I):
                        try:
                            val = float(m.group(1))
                            if 1 < val < 5000:
                                result["stack"] = str(int(val) if val == int(val) else round(val, 1))
                                break
                        except Exception:
                            pass
        except Exception:
            pass

    # === Core improvement: ROI-guided card sprite detection + per-crop recognition ===
    templates = _get_card_templates()
    hand_cards: list[str] = []
    board_cards: list[str] = []
    det = {"hero": 0, "board": 0}
    tmpl_boost_acc = 0.0

    if HAS_CV2 and cv_img is not None:
        # Hero (bottom) - expect up to 2; pass sens for robust partials (1-card hands ok)
        hrects = _detect_card_rects(cv_img, rois.get("hero"), min_area=1100, max_area=20000, sensitivity=sens)
        det["hero"] = len(hrects)
        for rx, ry, rw, rh in hrects[:2]:
            try:
                cpil = _crop_pil(pil_img, (rx, ry, rx + rw, ry + rh))
                ccv = cv_img[ry : ry + rh, rx : rx + rw]
                rec = _recognize_card_from_crop(cpil, ccv, templates, sensitivity=sens)
                if rec and rec not in hand_cards:
                    hand_cards.append(rec)
                # always try tmpl on crop for stronger integration + conf boost when matches (post calib)
                try:
                    tsc = _get_template_match_score(ccv, templates, sens)
                    if tsc >= 0.60:
                        tmpl_boost_acc += min(VISION_TEMPLATE_CONF_BOOST, (tsc - 0.5) * 0.3)
                except Exception:
                    pass
            except Exception:
                pass

        # Board (center) - 0/3/4/5 ; allow partial (flop only) for live street updates
        brects = _detect_card_rects(cv_img, rois.get("board"), min_area=550, max_area=14000, sensitivity=sens)
        det["board"] = len(brects)
        for rx, ry, rw, rh in sorted(brects, key=lambda t: t[0])[:5]:
            try:
                cpil = _crop_pil(pil_img, (rx, ry, rx + rw, ry + rh))
                ccv = cv_img[ry : ry + rh, rx : rx + rw]
                rec = _recognize_card_from_crop(cpil, ccv, templates, sensitivity=sens)
                if rec and rec not in board_cards:
                    board_cards.append(rec)
                try:
                    tsc = _get_template_match_score(ccv, templates, sens)
                    if tsc >= 0.60:
                        tmpl_boost_acc += min(VISION_TEMPLATE_CONF_BOOST, (tsc - 0.5) * 0.3)
                except Exception:
                    pass
            except Exception:
                pass

    # Fallback / supplement using full OCR tokens if spatial method under-detected (common pre-calib)
    # Enhanced: support even more partial (e.g. 1-card hand)
    if len(hand_cards) < 2 or len(board_cards) < 3:
        for c in cards_from_full:
            if len(hand_cards) < 2 and c not in hand_cards:
                hand_cards.append(c)
            elif len(board_cards) < 5 and c not in board_cards:
                board_cards.append(c)

    # FURTHER ROBUSTNESS for partial reads + real ClubGG: dedup, prevent hand<->board bleed (OCR on borders/ROIs)
    # This makes partial reads (flop-only, 1-hole) safer to apply without corrupting state.
    if hand_cards:
        seen = set()
        hand_cards = [c for c in hand_cards if not (c in seen or seen.add(c))]
    if board_cards:
        seen = set()
        board_cards = [c for c in board_cards if not (c in seen or seen.add(c))]
    hand_set = set(hand_cards)
    board_cards = [c for c in board_cards if c not in hand_set]

    hand = "".join(hand_cards[:2]) if hand_cards else ""
    board = "".join(board_cards[:5]) if board_cards else ""

    if hand:
        result["hand"] = hand
    if board:
        result["board"] = board
    if hand_cards or board_cards:
        result["raw_cards"] = hand_cards + board_cards

    result["detected_card_rects"] = det
    # Mark partial reads explicitly (enables runner to decide update vs full-hand req)
    result["partial"] = (len(hand_cards) < 2 or len(board_cards) < 3) and bool(hand or board)

    # When parsing board/hand, also attempt to infer current facing_action and bet_to_call from the image text (bet amount facing hero).
    # Uses same extract as pot (gated VISION_STREET_ACTION; additive only if good text; graceful no-overwrite if absent/low).
    # Follows exact current patterns for pot/bet_to_call/facing_action/street in capture + _robust_apply.
    if VISION_STREET_ACTION:
        try:
            bsrc = (roi_ocrs or {}).get("bet") or (roi_ocrs or {}).get("action_bar", "") or ""
            bet_info3 = extract_bet_info(full_ocr or "", roi_ocr_text or "", bsrc)
            if bet_info3.get("bet_to_call") and not result.get("bet_to_call"):
                result["bet_to_call"] = bet_info3.get("bet_to_call")
            ah = bet_info3.get("action_hint") or result.get("action_hint")
            if ah and not result.get("facing_action"):
                a = str(ah).lower()
                if "raise" in a:
                    result["facing_action"] = "raise"
                elif "bet" in a or "allin" in a:
                    result["facing_action"] = "bet"
                elif "check" in a:
                    result["facing_action"] = "check"
                else:
                    result["facing_action"] = str(ah)[:20]
        except Exception:
            pass

    # Street progression detection (in capture for direct feed to parsed state):
    # Use board length + action hints + pot changes to infer street even if vision misses one card or label.
    # This + merge + prefer in robust allows live listener to know street reliably for A1 history/street-aware advice.
    # Called even on partial boards (e.g. only flop visible but high pot + facing may hint later street, but board len primary).
    if not result.get("street"):
        bstr = result.get("board", "") or ""
        bc = len("".join(c for c in bstr if c.isalnum())) // 2
        if bc >= 5:
            result["street"] = "river"
        elif bc >= 4:
            result["street"] = "turn"
        elif bc >= 3:
            result["street"] = "flop"
        else:
            result["street"] = "preflop"
    # cross-ref with pot/action_hint for robustness if board len low but pot/action suggest postflop (rare, vision board miss)
    try:
        if result.get("pot") and result.get("street") == "preflop":
            pv = float(str(result["pot"]).strip())
            if pv > 4.0 and (result.get("facing_bet") or "bet" in str(result.get("action_hint", "")).lower()):
                result["street"] = "flop"  # conservative advance
    except Exception:
        pass
    # ensure opponents always present for wiring
    if not result.get("opponents") and result.get("villain_count"):
        result["opponents"] = result["villain_count"]

    # Confidence heuristic (partial credit for incomplete streets; higher when tesseract + rects align)
    # Robust: gives credit for partials so live can advance on street changes (board only etc)
    # ENHANCED: credit stack extract, roi_ocr success, rect-to-recognized ratio, templates
    # FURTHER for seamless real-time: slightly higher partial credit + debug log so conf thresh
    # can still trigger auto-analyze usefully on incremental reads (e.g. turn card only) without
    # being too noisy (runner still gates via min_conf + consec).
    conf = 0.0
    if hand:
        conf += 0.40 if len(hand_cards) >= 2 else 0.26  # partial hand still gives value (bumped)
    if board:
        bn = len(board_cards)
        if bn >= 5:
            conf += 0.42
        elif bn >= 3:
            conf += 0.32  # bump for reliable flop reads
        elif bn > 0:
            conf += 0.20  # incremental/partial board now more credited for street progression
    if det["hero"] or det["board"]:
        conf += 0.10
    # rect success ratio bonus (more reliable when detection + recognition align)
    total_rects = det.get("hero", 0) + det.get("board", 0)
    rec_success = (len(hand_cards) + len(board_cards))
    if total_rects > 0:
        ratio = min(1.0, rec_success / max(1, total_rects))
        conf += 0.08 * ratio
    if pos_cand:
        conf += 0.08
    if stack_cand:
        conf += 0.06  # stack read adds trust for live state
    # NEW conf credit for pot/bet/action/street/villain reads (makes live auto-apply more likely when useful data present)
    if result.get("pot"):
        conf = min(0.99, conf + 0.05)
    if result.get("facing_bet") or result.get("action_hint"):
        conf = min(0.99, conf + 0.06)
    if result.get("street") or result.get("villain_count"):
        conf = min(0.98, conf + 0.04)
    if roi_ocr_text and (hand or board or pos_cand or stack_cand):
        conf = min(0.99, conf + 0.05)
    if templates:
        conf = min(0.98, conf + 0.04)
    if tmpl_boost_acc > 0:
        conf = min(0.99, conf + tmpl_boost_acc)  # boost when template matched on detected crops (stronger post-calib)
    if (hand or board) and HAS_TESSERACT:
        conf = min(0.96, conf + 0.12)
    # slight boost/pen for sens? (low sens may inflate a bit, high penalize noise)
    if sens == "low":
        conf = min(0.95, conf + 0.03)
    elif sens == "high":
        conf = max(0.05, conf - 0.02)
    result["confidence"] = round(min(1.0, max(0.0, conf)), 2)

    # Apply caller min_conf (FURTHER enhanced for partials): use partial_min_conf if this read is partial (1-hole or <3 board),
    # else main min_conf. Still return the (partial) data, but flag 'below_threshold' for runner's manual-fallback logic.
    # This gives live listener + auto-capture finer control over partial reads vs full (e.g. accept marginal flop read at lower bar).
    # Use module PARTIAL_MIN... if caller passed 0 (default) for partial case.
    pmin = partial_min_conf if partial_min_conf > 0 else PARTIAL_MIN_CONF_DEFAULT
    use_thresh = pmin if (result.get("partial")) else (min_conf if min_conf > 0 else MIN_CONF_DEFAULT)
    if result["confidence"] < use_thresh:
        result["below_threshold"] = True
    result["method"] = "roi_cv_ocr_templates" if (HAS_CV2 and HAS_TESSERACT) else ("cv_rects_only" if HAS_CV2 else "ocr_only" if HAS_TESSERACT else "no_vision_libs")
    # Note: robustness (sens, partial, thresh + dedicated partial_min) fully wired for runner --live set-and-forget; real OCR best with tesseract + templates.

    # NEW: update rolling history (for temporal smooth across live polls), apply smooth_vision_state (vote, deal detect, decay)
    try:
        _RECENT_CONFS.append(result.get("confidence", 0.0))
        hist_entry = {k: result.get(k) for k in ("hand", "board", "position", "stack", "pot", "facing_bet", "action_hint", "street", "confidence", "partial")}
        _VISION_HISTORY.append(hist_entry)
        smoothed = smooth_vision_state(result, use_global_history=True)
        # merge smoothed signals back (prefer if they improved stability without losing info)
        for k in ("hand", "board", "pot", "facing_bet", "action_hint", "street", "confidence", "is_new_deal", "board_progress", "stability", "vote_stability", "conf_decay"):
            if k in smoothed and smoothed.get(k):
                result[k] = smoothed[k]
    except Exception:
        pass

    if not silent:
        stk = result.get("stack")
        stkstr = f" stack={stk}" if stk else ""
        potstr = f" pot={result.get('pot')}" if result.get("pot") else ""
        betstr = f" bet={result.get('facing_bet')}" if result.get('facing_bet') else ""
        actstr = f" act={result.get('action_hint')}" if result.get('action_hint') else ""
        if hand or board or pos_cand or any(det.values()) or stk or result.get("pot") or result.get("facing_bet"):
            pflag = " partial" if result.get("partial") else ""
            bflag = " below_thresh" if result.get("below_threshold") else ""
            print(f"[vision] ClubGG parse: hand={hand or '(none)'} board={board or '(none)'} pos={pos_cand or '(none)'}"
                  f"{stkstr}{potstr}{betstr}{actstr} conf={result['confidence']} rects={det} method={result['method']}{pflag}{bflag}")
        else:
            print(f"[vision] no card/pos tokens (conf={result['confidence']}); rects={det}. "
                  f"Install tesseract-ocr binary for best results, or add card_templates/. Partial state ok for live.")
    if VISION_DEBUG and not silent:
        print(f"[vision][debug] partial={result.get('partial')} below={result.get('below_threshold')} conf_raw={result['confidence']} sens={sens} libs:cv={HAS_CV2} tess={HAS_TESSERACT} hand_cards={hand_cards} board_cards={board_cards} pot={result.get('pot')} bet={result.get('facing_bet')}")

    return result


def prefer_better_board(old_b: str, new_b: str) -> str:
    """Robust helper for partial read handling in live/auto flows.
    Given possibly-partial board reads (from vision or sim), return the 'better' (longer/more complete) one.
    Prevents a noisy partial read (e.g. only flop on a turn street) from downgrading a previously
    reliably read fuller board. Supports incremental reads (new card only) by preferring known longer
    OR by smart-merging continuation fragments (e.g. old flop + new '5s' fragment -> full turn board).
    Called from runner's _robust_apply (and usable in auto-capture paths) for seamless street progression.
    Never loses info; falls back safely.
    """
    o = (old_b or "").strip().replace(" ", "")
    n = (new_b or "").strip().replace(" ", "")
    if not o:
        return n
    if not n:
        return o
    if n == o:
        return o
    ou = o.upper()
    nu = n.upper()
    # Prefer the longer/more complete board (vision on current street should see at least as many)
    if len(nu) > len(ou):
        return n
    if len(ou) > len(nu):
        # NEW: try smart merge for incremental-only reads (e.g. vision returns only turn/river card(s))
        # this allows partial 'new card only' reads to advance the board state in live listener.
        merged = merge_board_fragment(o, n)
        if len(merged) > len(o):
            return merged
        # keep known longer unless new is plausible superset (rare for partial)
        # but if n is prefix or continuation fragment, still keep fuller o
        if ou.startswith(nu) or nu.startswith(ou[-2:]) or nu in ou:
            return o
        return n  # different length-same? but we checked >
    # same len, different content -> trust the 'new' read (street might have changed? but rare mid-hand)
    return n


def prefer_better_hand(old_h: str, new_h: str) -> str:
    """Robust helper (mirror of prefer_better_board) for partial hand reads in live/auto flows.
    Given possibly-partial hole card reads (vision reads only 'Ah' or one card due to occlusion/OCR noise),
    return the 'better' (longer / more complete) one when safe.
    - Prefers longer read.
    - If new_h is a prefix/partial of known old full hand (e.g. 'Ah' vs prior 'AhKs'), keep the reliable old full.
    - Prevents noisy one-card reads from downgrading a good prior full hand read on same street/deal.
    - Supports street-independent hand persistence while still allowing genuine new-hand full reads.
    - Called from runner _robust_apply_vision_update (and auto-capture) for seamless real-time robustness.
    - Complements partial flag + conf thresh + manual fallback.
    Never loses info; falls back safely. Enhances 'handle partial reads' for set-and-forget.
    """
    o = (old_h or "").strip().replace(" ", "")
    n = (new_h or "").strip().replace(" ", "")
    if not o:
        return n
    if not n:
        return o
    if n == o:
        return o
    ou = o.upper()
    nu = n.upper()
    if len(nu) > len(ou):
        return n
    if len(ou) > len(nu):
        # keep known longer unless new is plausible superset/continuation (rare); else prefer prior full
        if ou.startswith(nu) or nu in ou:
            return o
        # different cards? trust new (possible new hand or correction)
        return n
    # same len different -> new may be better read/correction
    return n


def merge_board_fragment(old_board: str, fragment: str) -> str:
    """Further robustness for partial/incremental board reads (common in real vision on streets).
    If 'fragment' (e.g. '5s' or '5s8h' from vision spotting only the new card(s)) can be appended
    to 'old_board' (e.g. 'Qd7h2c') without duplicating cards and forms a plausible longer board,
    return the merged (old + new cards). Used to advance state on 'only latest cards visible' reads.
    Falls back to old or new if merge unsafe. Complements prefer_better_board.
    Called from updated prefer + runner robust paths for true street progression in hands-off live.
    """
    o = (old_board or "").strip().replace(" ", "")
    f = (fragment or "").strip().replace(" ", "")
    if not o:
        return f
    if not f:
        return o
    if f == o:
        return o
    if len(f) > len(o):
        return f  # new is fuller anyway
    # try to see if f is continuation (non-overlapping suffix addition)
    # remove any leading overlap; use case-insensitive for safety but preserve original casing from vision/sim
    ou = o.upper()
    fu = f.upper()
    merged = o
    for i in range(len(f), 0, -2):  # step by card (2 chars)
        cand = f[:i]
        cu = cand.upper()
        if ou.endswith(cu):
            # overlap, append the rest (preserve f casing)
            rest = f[i:]
            if rest and len(rest) % 2 == 0:
                # validate no dups (case-insen)
                new_cards = [rest[j:j+2] for j in range(0, len(rest), 2)]
                if not any(c.upper() in ou for c in new_cards):
                    merged = o + rest
                    break
            else:
                break
        else:
            # no overlap at this prefix, try append whole if no common cards
            new_cards = [f[j:j+2] for j in range(0, len(f), 2) if len(f) > j+1]
            overlap = any(c.upper() in ou for c in new_cards)
            if not overlap and all(len(c)==2 for c in new_cards):
                merged = o + f
                break
    # final sanity: only valid cards, max 5, dedup preserve order (tolerate case)
    seen = set()
    clean = []
    for j in range(0, len(merged), 2):
        c = merged[j:j+2]
        cu = c.upper()
        if len(cu) == 2 and cu[0] in "23456789TJQKA" and cu[1] in "SHDC" and cu not in seen:
            seen.add(cu)
            clean.append(c)  # keep original case from input
            if len(clean) >= 5:
                break
    return "".join(clean)


# =============================================================================
# NEW hardened helpers (extract_bet_info, pot, street/action hints, smooth_vision_state)
# For much better live ClubGG: auto pot/facing_bet for facing decisions, villain HUD,
# street/action from UI text, multi-frame vote + new-deal detection using merge + history.
# Called from attempt_vision_parse; results flow to run_brain live listener + current_inputs.
# Preserve full backward: old keys unchanged, new are additive (pot/facing_bet etc optional).
# =============================================================================

def extract_pot_size(ocr_text: str, roi_ocr: str = "") -> str | None:
    """Robust pot size extractor from full/roi OCR text. Looks for 'Pot', numbers near it, $ or bb.
    Returns e.g. '12.5' or None. Used for live pot in state (SPR/odds future use).
    Tolerant to ClubGG HUD variations. HARDENED: more styles "Pot: 12.50", "Pot 12.50", "total pot $xx", bb suffix.
    """
    src = (ocr_text or "") + " " + (roi_ocr or "")
    if not src.strip():
        return None
    def _parse_amt(txt: str) -> float | None:
        if not txt: return None
        t = re.sub(r'(?i)\b(?:bb|BB)\s*', '', txt)  # improved for bet/pot: '5.5','12','$4.00','bb 3.2' etc (pattern as in extract_bet_info)
        t = re.sub(r'[\$,]', '', t)
        m = re.search(r'\b(\d{1,4}(?:\.\d{1,2})?)\b', t)
        if m:
            try:
                v = float(m.group(1))
                if 0.1 < v < 20000: return v
            except: pass
        return None
    # prefer labeled pot : "Pot: 12.50", "Pot 12.50", "total pot", "main pot"
    for m in re.finditer(r"(?i)(?:pot|total pot|main pot|side pot)\s*[:=\-]?\s*[\$]?\s*(\d{1,4}(?:\.\d{1,2})?(?:\s*bb)?)\b", src):
        v = _parse_amt(m.group(1) or m.group(0))
        if v and 0.5 < v < 10000:
            return str(int(v) if v == int(v) else round(v, 1))
    # more variants "Pot 12.50" standalone labeled
    for m in re.finditer(r"(?i)\bpot\b\s*[\$]?\s*(\d{1,4}(?:\.\d{1,2})?(?:\s*bb)?)\b", src):
        v = _parse_amt(m.group(1))
        if v and 0.5 < v < 10000:
            return str(int(v) if v == int(v) else round(v, 1))
    # unlabeled large central number after board-ish (fallback)
    for m in re.finditer(r"[\$]?\b(\d{1,4}(?:\.\d{1,2})?(?:\s*bb)?)\b\s*(?:pot|bb|chips?)?", src, re.IGNORECASE):
        v = _parse_amt(m.group(1) or m.group(0))
        if v and 1.5 < v < 5000:  # typical pot range
            return str(int(v) if v == int(v) else round(v, 1))
    return None


def extract_bet_info(ocr_text: str, roi_ocr: str = "", action_roi_ocr: str = "") -> dict:
    """Extract current facing bet / call amount + hints from bet UI elements + pot text.
    Looks for 'Call X', 'to call', 'Bet 3.5', 'Raise to 12', 'Bet', 'Raise to Y', all-in indicators, numbers near action bar / hero.
    Returns dict with 'facing_bet', 'action_hint', 'call_amount', 'bet_to', 'bet_to_call' etc (strings or None).
    Greatly improves live facing spots (postflop especially) without manual 'set facing'.
    Handles common ClubGG action bar phrasing reliably.
    Improved regex for bet amts e.g. '5.5','12','$4.00','bb 3.2'; detects facing_bet vs facing_raise vs check (w/ 'bet' ROI).
    """
    src = " ".join([ocr_text or "", roi_ocr or "", action_roi_ocr or ""])
    res = {"facing_bet": None, "call_amount": None, "action_hint": None, "bet_to": None, "bet_to_call": None}
    if not src.strip():
        return res
    u = src.upper()
    def _parse_amt(txt: str) -> float | None:
        if not txt: return None
        t = re.sub(r'(?i)\b(?:bb|BB)\s*', '', txt)  # improved: bb 3.2, BB12, 4.5bb etc (before/after)
        t = re.sub(r'[\$,]', '', t).strip()
        m = re.search(r'\b(\d{1,4}(?:\.\d{1,2})?)\b', t)
        if m:
            try:
                v = float(m.group(1))
                if 0.1 < v < 10000: return v
            except: pass
        return None
    # Improved: specific patterns first for "Bet X", "Raise to Y", "Call X", "Raise To 12", all-in. More reliable extraction.
    candidates = []
    # 1. explicit raise to / raise To (common for bet_to_call , "Raise To 12")
    for m in re.finditer(r"(?i)(?:raise\s*to|RAISE\s*TO|raise-to|raise to)\s*[\$]?\s*(\d{1,4}(?:\.\d{1,2})?(?:\s*bb)?)\b", src):
        v = _parse_amt(m.group(1))
        if v and 0.5 < v < 2000:
            candidates.append((v, "raise_to"))
            res["bet_to"] = str(int(v) if v == int(v) else round(v, 1))
    # 2. Bet X.Y (specific for postflop sizing , "Bet 4.5")
    for m in re.finditer(r"(?i)(?:^|[\s(])(?:bet|Bet|BET)\s*[\$]?\s*(\d{1,4}(?:\.\d{1,2})?(?:\s*bb)?)\b", src):
        v = _parse_amt(m.group(1))
        if v and 0.5 < v < 2000:
            candidates.append((v, "bet"))
    # 3. Call / to call / "Call 4.5"
    for m in re.finditer(r"(?i)(?:call|to call|CALL|TO CALL)\s*[\$]?\s*(\d{1,4}(?:\.\d{1,2})?(?:\s*bb)?)\b", src):
        v = _parse_amt(m.group(1))
        if v and 0.5 < v < 2000:
            candidates.append((v, "call"))
    # 4. "Call 4.5 (pot)" or amount then label
    for m in re.finditer(r"[\$]?\s*(\d{1,4}(?:\.\d{1,2})?(?:\s*bb)?)\s*(?:to call|call|CALL|bet|BET)", src):
        v = _parse_amt(m.group(1))
        if v and 0.5 < v < 2000:
            candidates.append((v, "call" if "call" in (m.group(0) or "").lower() else "bet"))
    # 5. all-in indicators (may have amount or not; treat as large facing bet for decisions)
    allin_amt = None
    for m in re.finditer(r"(?i)(?:all[- ]?in|ALL[- ]?IN|allin|ALLIN| a/i |AI\s)(?:[\$]?\s*(\d{1,4}(?:\.\d{1,2})?(?:\s*bb)?)?)", src):
        v = _parse_amt(m.group(1) or "")
        if v and 0.5 < v < 2000:
            allin_amt = v
            candidates.append((v, "allin"))
        elif not m.group(1):
            candidates.append((99.0, "allin"))
    # pick best (prefer explicit raise/call/bet over generic)
    if candidates:
        # prefer raise_to or call over plain bet if multiple
        best = sorted(candidates, key=lambda x: (0 if x[1] in ("raise_to","call","allin") else 1, -x[0]) )[0]
        val = best[0]
        res["facing_bet"] = str(int(val) if val == int(val) else round(val, 1))
        if best[1] == "call":
            res["call_amount"] = res["facing_bet"]
        if best[1] == "raise_to":
            res["bet_to"] = res["facing_bet"]
    # generic fallback numbers near bet/call keywords (as before) + $ bb
    if not res.get("facing_bet"):
        for pat in [
            r"[\$]?\s*(\d{1,4}(?:\.\d{1,2})?(?:\s*bb)?)\s*(?:to call|call|CALL|bet|BET|raise|RAISE)",
            r"(?i)(?:bet|raise|call)\s*[\$]?\s*(\d{1,4}(?:\.\d{1,2})?(?:\s*bb)?)\b",
            r"[\$]?\s*(\d{1,4}(?:\.\d{1,2})?)\s*(?:to call|call)",
        ]:
            for m in re.finditer(pat, src):
                v = _parse_amt(m.group(1) or m.group(0))
                if v and 0.5 < v < 2000:
                    res["facing_bet"] = str(int(v) if v == int(v) else round(v, 1))
                    break
            if res["facing_bet"]:
                break
    # action hints (improved for bet phrasing + allin; detect facing_bet vs facing_raise vs check per task)
    if "CALL" in u or "to call" in u.lower():
        res["action_hint"] = "facing_call"
    elif re.search(r"(?i)\braise\b", src) or "RAISE" in u:
        res["action_hint"] = "facing_raise"
    elif "BET" in u or re.search(r"(?i)\bbet\b", src):
        res["action_hint"] = "facing_bet"
    elif "CHECK" in u:
        res["action_hint"] = "check_option"
    elif "ALL" in u and ("IN" in u or "AI" in u):
        res["action_hint"] = "facing_allin" if res.get("facing_bet") else "facing_bet"
    elif res.get("facing_bet"):
        res["action_hint"] = "facing_bet"
    # normalize bet_to_call for runner GameState / facing (wires to A1)
    if res.get("facing_bet"):
        res["bet_to_call"] = res["facing_bet"]
    if res.get("bet_to") and not res.get("bet_to_call"):
        res["bet_to_call"] = res["bet_to"]
    # secondary bet_to raise (ensure)
    if not res.get("bet_to"):
        for m in re.finditer(r"(?i)raise to\s*[\$]?\s*(\d{1,4}(?:\.\d{1,2})?(?:\s*bb)?)\b", src):
            v = _parse_amt(m.group(1))
            if v and 0.5 < v < 2000:
                res["bet_to"] = str(int(v) if v == int(v) else round(v, 1))
                if not res.get("bet_to_call"):
                    res["bet_to_call"] = res["bet_to"]
    return res


def detect_street_and_action(pil_img, full_ocr: str, rois_ocr: dict | None = None) -> dict:
    """Attempt to infer current street + facing action from image (board len + UI bet elements + pot text).
    Reduces need for manual overrides in live. Returns {'street': 'flop', 'action_hint': 'facing_call', ...}
    Uses len(board) from upstream + ocr keywords on action_bar/pot/hud + button text.
    """
    hints = {"street": None, "action_hint": None, "facing_bet": None}
    ocr = (full_ocr or "") + " " + " ".join((rois_ocr or {}).values())
    u = ocr.upper()
    # street from common labels or infer later from board len in caller
    if "FLOP" in u or "flop" in ocr.lower():
        hints["street"] = "flop"
    elif "TURN" in u:
        hints["street"] = "turn"
    elif "RIVER" in u:
        hints["street"] = "river"
    # action from buttons / text
    bet_info = extract_bet_info(ocr, "", (rois_ocr or {}).get("bet") or (rois_ocr or {}).get("action_bar", ""))
    if bet_info.get("action_hint"):
        hints["action_hint"] = bet_info["action_hint"]
        hints["facing_bet"] = bet_info.get("facing_bet")
    # if no explicit, look for check/bet/fold keywords (facing bet vs raise etc)
    if not hints.get("action_hint"):
        if "CHECK" in u:
            hints["action_hint"] = "check"
        elif "RAISE" in u or "raise" in ocr.lower():
            hints["action_hint"] = "facing_raise"
        elif "BET" in u or re.search(r"(?i)\bbet\b", ocr):
            hints["action_hint"] = "facing_bet"
        elif "FOLD" in u and "CALL" not in u:
            hints["action_hint"] = "facing_raise"
    return hints


def smooth_vision_state(current: dict, use_global_history: bool = True) -> dict:
    """Multi-frame / temporal smoothing + new-deal vs board-progress detection.
    Keeps short _VISION_HISTORY (or passed), votes on most stable hand/board across recent parses,
    applies conf decay on streaks of low reads, uses merge_board_fragment + prefer_* logic for incremental.
    Detects 'new_deal' (hand change + board reset-ish) vs 'progress' (same hand, board longer).
    Returns augmented current with 'smoothed_hand', 'smoothed_board', 'is_new_deal', 'deal_progress',
    'stability' (0-1 vote agreement), 'conf_decay' etc. Always safe, falls back to current.
    Deepens streak handling (runner already uses consec; here for vision conf adjustment).
    """
    if not current:
        return current
    hist = list(_VISION_HISTORY) if use_global_history else []
    smoothed = dict(current)  # copy
    hand = str(current.get("hand", "") or "").strip().replace(" ", "").upper()
    board = str(current.get("board", "") or "").strip().replace(" ", "").upper()
    conf = float(current.get("confidence", 0.0) or 0.0)

    # collect recent for vote (exclude current if dup)
    recent_hands = [str(h.get("hand", "") or "").strip().replace(" ", "").upper() for h in hist[-VISION_HISTORY_LEN:]]
    recent_boards = [str(b.get("board", "") or "").strip().replace(" ", "").upper() for b in hist[-VISION_HISTORY_LEN:]]
    recent_confs = [float(c.get("confidence", 0) or 0) for c in hist[-4:]]

    # vote stable
    from collections import Counter
    h_vote = Counter([h for h in recent_hands + [hand] if h])
    b_vote = Counter([b for b in recent_boards + [board] if b])
    stable_h = h_vote.most_common(1)[0][0] if h_vote else hand
    stable_b = b_vote.most_common(1)[0][0] if b_vote else board
    stability = 0.5
    if hand and h_vote:
        stability = min(1.0, h_vote.get(hand, 0) / max(1, sum(h_vote.values())))
    if board and b_vote:
        stability = (stability + min(1.0, b_vote.get(board, 0) / max(1, sum(b_vote.values())))) / 2

    # apply smoothed if high agreement and current partial/low
    partial = bool(current.get("partial"))
    if stability > 0.65 and (partial or conf < 0.6):
        if stable_h and len(stable_h) >= len(hand or ""):
            smoothed["hand"] = stable_h  # prefer stable voted
        if stable_b and len(stable_b) >= len(board or ""):
            smoothed["board"] = stable_b
        smoothed["stability"] = round(stability, 2)

    # new deal vs board progressed detection (key for live auto clear / analyze trigger)
    is_new_deal = False
    is_progress = False
    old_hand = ""
    old_board = ""
    if hist:
        prev = hist[-1]
        old_hand = str(prev.get("hand", "") or "").strip().replace(" ", "").upper()
        old_board = str(prev.get("board", "") or "").strip().replace(" ", "").upper()
    if hand and old_hand and hand != old_hand:
        # hand changed
        if not board or len(board) <= 2 or (old_board and len(board) < len(old_board)):
            is_new_deal = True
            smoothed["is_new_deal"] = True
            # clear board if not provided with new hand (vision may lag)
            if not current.get("board"):
                smoothed["board"] = ""
    elif hand and old_hand and hand == old_hand and board and old_board:
        if len(board) > len(old_board):
            is_progress = True
            smoothed["board_progress"] = True
            # use merge if vision gave fragment
            merged = merge_board_fragment(old_board, board)
            if len(merged) > len(board):
                smoothed["board"] = merged
    smoothed["is_new_deal"] = is_new_deal
    smoothed["board_progress"] = is_progress

    # conf decay over time / streak
    decay = 1.0
    if recent_confs:
        low_streak = 0
        for c in reversed(recent_confs):
            if c < 0.45:
                low_streak += 1
            else:
                break
        if low_streak >= 2:
            decay = max(0.6, 1.0 - 0.12 * low_streak)
    smoothed["conf_decay"] = round(decay, 2)
    if decay < 1.0 and "confidence" in smoothed:
        try:
            smoothed["confidence"] = round(float(smoothed["confidence"]) * decay, 2)
        except Exception:
            pass

    # record streak-ish for runner
    smoothed["vote_stability"] = round(stability, 2)
    return smoothed


def simulate_table_state(step: int = 0, scenario: str = "demo", client: str = None) -> dict:
    """Return simulated live table state for --live / --simulate-vision testing.
    No real capture/OCR needed. Cycles deterministic demo sequences so the runner's
    live listener can exercise: capture->parse->state update->auto-analyze flow.

    Includes support for tournament_mode / icm / notes-compat (notes are separate).
    Used by run_brain when POKERFLEX_VISION_SIMULATE=1 or --simulate-vision flag.
    GENERIC (client-agnostic): works for both ClubGG and CoinPoker -- the 'client' param
    (passed via capture_and_parse etc) only affects real paths (window hints + ROIs in get_poker_rois).
    Sim always returns the same realistic hands/boards/partials/ICM for E2E testing of live flow.
    Accepts + stores client= (defaults clubgg) in output state for full parity with real capture_and_parse path.

    Call with incrementing step for 'live' progression (preflop -> postflop etc).
    Now also exercises partial reads occasionally for robustness testing of conf/partial/fallback paths.
    Supports expanded sim scenarios via CLI --sim-scenario: demo (default mix), icm, cash (deep no tmode),
    tourney (ICM focused), mixed (alternates for variety in long live runs), noisy (real-vision-like OCR noise/
    garbles/jitter for testing harden + robust listener + history + postflop ICM paths in --self-test / --live).
    CoinPoker users: use same --sim-scenario ; real CoinPoker use --client coinpoker (or auto) + calib.
    """
    if client is None:
        client = DEFAULT_CLIENT
    demo_seq = [
        # hand 1 preflop BTN deep
        {"hand": "AhKs", "board": "", "position": "BTN", "opponents": "2", "stack": "100", "ante": "0",
         "tournament_mode": "false", "icm_factor": "0.0", "players_remaining": "", "note": "new deal preflop"},
        # flop
        {"hand": "AhKs", "board": "Qd7h2c", "position": "BTN", "opponents": "2", "stack": "97", "ante": "0",
         "tournament_mode": "false", "icm_factor": "0.0", "players_remaining": "", "note": "flop c-bet IP dry",
         "action_history": [{"street": "preflop", "actor": "villain", "action": "call"}, {"street": "flop", "actor": "hero", "action": "bet", "size": 2.5}] },
        # turn
        {"hand": "AhKs", "board": "Qd7h2c5s", "position": "BTN", "opponents": "2", "stack": "94", "ante": "0",
         "tournament_mode": "false", "icm_factor": "0.0", "players_remaining": "", "note": "turn barrel"},
        # river (full board for street progression test)
        {"hand": "AhKs", "board": "Qd7h2c5s8h", "position": "BTN", "opponents": "2", "stack": "92", "ante": "0",
         "tournament_mode": "false", "icm_factor": "0.0", "players_remaining": "", "note": "river decision"},
        # new hand short ICM spot (use explicit rank+suit so parse_cards succeeds in new A1 brain + legacy_to)
        {"hand": "7s6h", "board": "", "position": "SB", "opponents": "4", "stack": "14", "ante": "0.5",
         "tournament_mode": "true", "icm_factor": "0.18", "players_remaining": "6", "note": "ICM short push/fold vs 4"},
        # flop in ICM hand
        {"hand": "7s6h", "board": "Ks9d3c", "position": "SB", "opponents": "3", "stack": "12", "ante": "0.5",
         "tournament_mode": "true", "icm_factor": "0.18", "players_remaining": "6", "payout_structure": "0.5,0.3,0.2", "note": "postflop ICM (w/ concrete 50/30/20 payouts -> deeper adj)"},
        # river ICM for full street + ICM continuity test
        {"hand": "7s6h", "board": "Ks9d3c4h2c", "position": "SB", "opponents": "3", "stack": "10", "ante": "0.5",
         "tournament_mode": "true", "icm_factor": "0.18", "players_remaining": "6", "note": "ICM river"},
    ]
    icm_seq = [
        {"hand": "As9h", "board": "", "position": "BTN", "opponents": "5", "stack": "11", "ante": "1",
         "tournament_mode": "true", "icm_factor": "0.22", "players_remaining": "7", "note": "final table bubble push"},
        {"hand": "As9h", "board": "Qh8s2d", "position": "BTN", "opponents": "3", "stack": "9", "ante": "1",
         "tournament_mode": "true", "icm_factor": "0.22", "players_remaining": "7", "note": "ICM cbet?"},
    ]
    cash_seq = [
        {"hand": "KdQd", "board": "", "position": "CO", "opponents": "3", "stack": "120", "ante": "0",
         "tournament_mode": "false", "icm_factor": "0.0", "players_remaining": "", "note": "cash deep open"},
        {"hand": "KdQd", "board": "JhTc2s", "position": "CO", "opponents": "2", "stack": "115", "ante": "0",
         "tournament_mode": "false", "icm_factor": "0.0", "players_remaining": "", "note": "cash flop draw"},
    ]
    tourney_seq = [
        {"hand": "A9o", "board": "", "position": "BTN", "opponents": "6", "stack": "13", "ante": "0.75",
         "tournament_mode": "true", "icm_factor": "0.25", "players_remaining": "8", "note": "tourney pushfold"},
        {"hand": "A9o", "board": "K72r", "position": "BTN", "opponents": "4", "stack": "11", "ante": "0.75",
         "tournament_mode": "true", "icm_factor": "0.25", "players_remaining": "8", "payout_structure": "0.40,0.25,0.20,0.10,0.05", "note": "tourney post ICM (w/ 40/25/20/10/5 payouts for ICM factor+postflop)"},
    ]
    if scenario == "icm":
        seq = icm_seq
    elif scenario == "cash":
        seq = cash_seq
    elif scenario == "tourney":
        seq = tourney_seq
    elif scenario == "noisy":
        # real-vision-like noise scenario: uses demo base + heavy OCR-style corruptions below (misreads, jitter, typos)
        # for testing harden paths in parse/robust/ listener / history / partial recovery. See run_brain --self-test.
        seq = demo_seq
    elif scenario == "mixed":
        # cycle through variety for long-running live tests
        base = demo_seq + icm_seq + cash_seq
        seq = base
    else:
        seq = demo_seq
    state = seq[step % len(seq)].copy()
    # remove internal 'note'
    state.pop("note", None)
    # For live integration: attach high confidence so logs/UI treat sim as trusted source
    if "confidence" not in state:
        state["confidence"] = 0.95
    # Occasionally simulate a partial read (e.g. 1 hole card only, or flop-only) to test runner's
    # partial handling + conf threshold fallback-to-manual logic end-to-end.
    # FURTHER ENHANCED for robust live: more frequent injection (covers hand+board+river partials), lower confs,
    # incremental new-card-only for river/turn (e.g. board='5s' or '5s8h') to exercise NEW merge_board_fragment +
    # prefer_better_board + _robust + consec + new-hand-clear + auto-analyze for true street progression.
    # Works with --sim-scenario mixed/tourney for rich ICM+notes E2E tests in live listener.
    partial_inj = False
    if (step % 4 == 1) or (scenario in ("mixed", "demo", "noisy") and step % 6 == 0):
        # partial hand example (1 card)
        orig_h = state.get("hand", "AhKs")
        state["hand"] = orig_h[:2] if len(orig_h) > 2 else orig_h  # e.g. "Ah" only
        state["confidence"] = 0.38  # mid-low to exercise thresh + partial_min_conf
        partial_inj = True
    if (step % 3 == 0) or (scenario in ("mixed", "noisy") and step % 5 == 1):
        # board partial (flop-only or ONLY the new card(s) for incremental street test, incl river)
        if state.get("board"):
            full_board = state["board"]
            bl = len(full_board)
            if bl > 6 and (step % 4 == 0):
                # simulate vision only spotting the latest added card(s) (common on marginal reads / river)
                state["board"] = full_board[-2:]  # e.g. just "8h" or "8hQc"
            elif bl >= 4:
                state["board"] = full_board[:6]  # first 3 cards (flop) even mid-hand
            else:
                state["board"] = full_board[:2] if bl > 2 else full_board  # very partial
            state["confidence"] = min(state.get("confidence", 0.9), 0.55)
            partial_inj = True
    # NEW varied realistic noisy partials for testing (OCR-like errors, low conf, 10/T misreads, partial suits, pot/bet noisy strings)
    if scenario in ("noisy", "mixed") and (step % 5 == 2 or step % 9 == 0):
        # simulate noisy OCR partials e.g. missing suit or 10/T glitch, 1-card board frag, very low conf
        if state.get("board") and len(state["board"]) >= 4:
            # e.g. "Qd7" (flop missing last suit) or just new card
            state["board"] = state["board"][:4] if len(state["board"]) > 4 else state["board"][:2]
            state["confidence"] = min(state.get("confidence", 0.6), 0.32)
            partial_inj = True
        if state.get("hand") and len(state.get("hand", "")) == 4 and step % 4 == 0:
            state["hand"] = state["hand"][:2]  # 1 hole noisy
            state["confidence"] = 0.29
            partial_inj = True
        # inject pot/bet variants that exercise the hardened extractors (even tho sim bypasses ocr, for direct state variety + future ocr tests)
        # note: bet examples for improved _extract (regex): '5.5', '12', '$4.00', 'bb 3.2' etc (tested via --simulate-vision)
        try:
            state["pot"] = ["12.5", "Pot: 8.0", "15", "4.5bb", "22.50"][step % 5]
            state["facing_bet"] = ["4.5", "Call 3.25", "Raise To 12", "6.0", "$2.5"][step % 5]
            state["action_hint"] = "facing_call" if step % 2 else "facing_bet"
        except: pass
    if partial_inj:
        state["partial"] = True
        # occasionally force even lower for testing fallback paths
        if step % 7 == 2:
            state["confidence"] = min(state.get("confidence", 0.5), 0.22)
    # debug aid
    if VISION_DEBUG:
        state["_sim_scenario"] = scenario
    # ENHANCED for task (live-listener-smarts): emit more realistic HUD/pot/bet data (e.g. "Bet 3.5" style via decimals, raise-to, facing_allin, pot progression, HUD pos/stack/opp)
    # + is_new_deal + pos/stack deltas on deal transitions (tests stronger new-hand detect combining hand+board_reset+delta).
    # + street always, bet_to_call etc. So --simulate-vision --live now produces rich realistic data for auto pos/stack/num_opp/bet/facing/street/new-hand/analyze gating.
    # Non-breaking additive; partials/noise paths untouched.
    try:
        bn = len(state.get("board", "") or "") // 2
        pot_base = 1.5 + (bn * 3.5) + (float(state.get("stack", 100)) * 0.008)
        if bn == 0:
            pot_base = round(1.5 + float(state.get("ante", "0")) * max(1.0, float(state.get("opponents", "2"))), 1)
        state["pot"] = str(round(max(1.0, pot_base), 1))
        if bn >= 1:
            base_bet = round(2.0 + bn * 1.25 + ((step % 4) - 1) * 0.5, 1)  # realistic 2.5 3.0 3.5 4.5 etc
            if step % 7 == 2 and bn >= 2:
                base_bet = round(float(state.get("pot", "8")) * 0.6, 1)
                state["facing_bet"] = str(base_bet)
                state["bet_to"] = str(base_bet)
                state["bet_to_call"] = str(base_bet)
                state["action_hint"] = "facing_bet"
            elif step % 11 == 0 and scenario in ("mixed", "tourney", "demo"):
                state["facing_bet"] = str(round(float(state.get("stack", "15")) * 0.9, 1))
                state["bet_to_call"] = state["facing_bet"]
                state["action_hint"] = "facing_allin"
            else:
                state["facing_bet"] = str(base_bet)
                state["bet_to_call"] = str(base_bet)
                state["action_hint"] = "facing_call" if bn == 1 and step % 3 != 1 else "facing_bet"
        state["street"] = ["preflop", "flop", "turn", "river"][min(bn, 3)]
        if not state.get("opponents"):
            state["opponents"] = state.get("villain_count", "2")
        state["villain_count"] = state.get("opponents", "2")
        # is_new_deal + delta for stronger new hand logic test (hand change + board reset + (opt) pos/stack delta)
        if step == 0 or (step > 0 and step % 4 == 0) or bn == 0:
            state["is_new_deal"] = True
            poss = ["BTN", "SB", "BB", "CO", "HJ", "UTG", "MP"]
            if state.get("position") in poss:
                try:
                    idx = poss.index(state["position"])
                    state["position"] = poss[(idx + 1) % len(poss)]
                except Exception:
                    state["position"] = "BTN"
            try:
                stf = float(state.get("stack", 50))
                d = - (1.0 + (step % 3) * 0.5) if str(state.get("tournament_mode", "false")).lower() in ("true","1") else -2.5
                state["stack"] = str(max(2, round(stf + d, 1)))
            except Exception:
                pass
        for kk in ("stack", "position", "opponents", "villain_count", "pot", "facing_bet", "bet_to_call"):
            if kk in state and state[kk] is not None:
                state[kk] = str(state[kk])
        if state.get("position"):
            state["position"] = str(state["position"]).upper()[:6]
    except Exception:
        pass
    # legacy light injection (for old test compat)
    if step % 3 == 0 or (scenario in ("mixed", "demo") and step % 2 == 0):
        try:
            bn = len(state.get("board", "") or "") // 2
            if not state.get("pot"):
                pot_base = 1.5 + (bn * 3.5) + (float(state.get("stack", 100)) * 0.01)
                state["pot"] = str(round(max(1.5, pot_base), 1))
            if bn >= 1 and not state.get("facing_bet"):
                state["facing_bet"] = str(round(2.5 + bn * 1.5, 1))
                state["action_hint"] = "facing_call" if bn == 1 else "facing_bet"
            if not state.get("street"):
                state["street"] = ["preflop", "flop", "turn", "river"][min(bn, 3)]
            if not state.get("villain_count"):
                state["villain_count"] = state.get("opponents", "2")
        except Exception:
            pass
    state = dict(state)  # copy
    state.setdefault("client", client or DEFAULT_CLIENT)
    return state


def capture_and_parse(
    output_path: str = OUT,
    window_hint: str = None,
    delay: int = 0,
    silent: bool = False,
    simulate: bool = False,
    sim_step: int = 0,
    sim_scenario: str = "demo",
    sensitivity: str | None = None,
    min_conf: float = 0.0,
    partial_min_conf: float = 0.0,
    debug: bool | None = None,
    preprocess: str | None = None,
    retries: int = 3,
    history_len: int | None = None,
    client: str = None,
) -> tuple[str | None, dict]:
    """One-call helper used by runner for auto/live flows: capture (real or sim) + vision parse.
    Returns (saved_image_path or None, parsed_state_dict).
    If simulate=True, skips real grab and uses simulate_table_state (for --live tests / dev).
    Forwards sensitivity/min_conf/partial_min_conf to attempt_vision_parse for live robustness tuning (partial reads,
    conf thresholds, fallback decisions in runner). partial_min_conf allows separate (usually lower) bar for 1-card/flop-only.
    debug forwarded to enable extra diagnostics in live vision (use --vision-debug).
    preprocess: forwarded for OCR preproc level (new --vision-preproc for live sensitivity; "light" default good for most, "aggressive" for tricky real ClubGG/CoinPoker contrast).
    retries: passed to real capture_clubgg_image (higher for hands-off bg/live auto-captures).
    history_len: NEW for temporal smoothing (vision history length for vote/new-deal in smooth_vision_state).
    client: "clubgg"|"coinpoker" (default clubgg); passed to capture_clubgg_image (window find/hints/auto-detect) + attempt (ROIs + per-client calib) + simulate. No breakage if omitted.
    """
    if debug is not None or preprocess is not None or history_len is not None:
        try:
            set_vision_params(debug=debug, preprocess=preprocess, history_len=history_len)
        except Exception:
            pass
    if client is None:
        client = DEFAULT_CLIENT

    if simulate:
        parsed = simulate_table_state(sim_step, sim_scenario, client=client)
        if not silent:
            print(f"[vision] SIMULATE mode step={sim_step} scenario={sim_scenario}: {parsed}")
        parsed = dict(parsed)  # copy
        parsed["client"] = client
        # still 'touch' a capture path for compatibility (last known image)
        return output_path, parsed

    try:
        # Further auto-capture robustness for live hands-off: use retries + activate so real vision
        # succeeds more often without user bringing window manually each time. Caller (live runner) can bump retries.
        path = capture_clubgg_image(
            output_path=output_path,
            window_hint=window_hint,
            delay=delay,
            silent=silent,
            retries=max(1, int(retries)),
            activate=True,
            client=client,
        )
        parsed = attempt_vision_parse(path, silent=silent, sensitivity=sensitivity, min_conf=min_conf, partial_min_conf=partial_min_conf, debug=debug, preprocess=preprocess, history_len=history_len, client=client)
        # Attach partial_min for runner convenience (even if attempt used main min_conf for its below flag)
        if parsed and partial_min_conf > 0:
            parsed["_partial_min_conf"] = partial_min_conf
        if parsed:
            parsed["client"] = client
        return path, parsed
    except Exception as ex:
        if not silent:
            print(f"[vision] capture_and_parse failed: {ex}")
        return None, {}


# =============================================================================
# Calibration helpers (for calibration.py wizard + direct use).
# Reusable capture, preview gen (cv2/pil annotated for user guidance), card crop assist.
# Non-intrusive: existing flows (incl simulate) unaffected.
# =============================================================================

def ensure_user_dirs() -> tuple[str, str]:
    """Ensure cwd-based user dirs for config and templates (wizard friendly)."""
    calib_dir = os.path.join(os.getcwd(), "calib_crops")
    tdir = os.path.join(os.getcwd(), "card_templates")
    os.makedirs(calib_dir, exist_ok=True)
    os.makedirs(tdir, exist_ok=True)
    # also ensure ~/.pokerflex for global user profile if wanted
    try:
        os.makedirs(os.path.expanduser(os.path.join("~", ".pokerflex")), exist_ok=True)
    except Exception:
        pass
    return calib_dir, tdir


def capture_calibration_samples(count: int = 2, base_prefix: str = "calib_sample", client: str = None) -> list[str]:
    """Capture N fresh samples using the robust (generalized) capture_clubgg_image (retries+activate + client).
    Instructs user first via prints. Returns list of saved paths.
    Used by wizard step 2. Multiple samples help user pick best lighting/zoom for template/ROI confirm.
    Now client-aware for CoinPoker (or clubgg); detects if client=None via find_window.
    """
    if client is None:
        client = DEFAULT_CLIENT
    cname = CLIENT_DEFAULT_NAMES.get(client, "table")
    paths = []
    ensure_user_dirs()
    print("=== Calibration: Capture samples ===")
    print(f"Have your {cname} table visible (not minimized, good lighting, your normal play resolution/zoom).")
    for i in range(count):
        p = f"{base_prefix}_{i+1:03d}.png"
        print(f"  Capturing sample {i+1}/{count} (bring {cname} table forward if needed)...")
        try:
            path = capture_clubgg_image(
                output_path=p,
                delay=(3 if i == 0 else 0),
                silent=False,
                retries=3,
                activate=True,
                client=client,
            )
            paths.append(path)
            if i < count - 1:
                time.sleep(1.2)
        except Exception as ex:
            print(f"  [warn] sample {i+1} capture issue: {ex}")
    print(f"  Saved samples: {paths}")
    return paths


def _pil_draw_rect(pil_img, bbox, label: str, color=(255, 0, 0)):
    """Draw labeled rect on PIL image copy (fallback if no cv2 for preview)."""
    try:
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(pil_img)
        l, t, r, b = bbox
        draw.rectangle([l, t, r, b], outline=color, width=3)
        # label
        try:
            f = ImageFont.load_default()
        except Exception:
            f = None
        draw.text((l + 4, t + 4), label, fill=color, font=f)
    except Exception:
        pass  # best effort
    return pil_img


def generate_roi_preview(image_path: str, rois: dict | None = None, out_path: str = "calib_roi_preview.png", client: str = None) -> str:
    """Generate annotated preview PNG with ROIs drawn (hero/board/stack boxes + labels).
    Uses cv2 if available (richer), else PIL. Helps user visually confirm/adjust during wizard.
    Returns path to preview.
    client: passed through to get_poker_rois / get_clubgg_rois wrapper (for coinpoker-aware default ROIs if no explicit rois + per-client calib).
    """
    if client is None:
        client = DEFAULT_CLIENT
    if not os.path.exists(image_path):
        return ""
    ensure_user_dirs()
    if rois is None:
        try:
            pil = Image.open(image_path)
            w, h = pil.size
            rois = get_poker_rois(w, h, client=client)
        except Exception:
            rois = {}
    try:
        if HAS_CV2:
            cvimg = cv2.imread(image_path)
            if cvimg is None:
                raise RuntimeError("cv read fail")
            h, w = cvimg.shape[:2]
            colors = {"hero": (0, 255, 0), "board": (255, 255, 0), "hero_stack": (0, 165, 255), "full": (128, 128, 128)}
            for name, bbox in rois.items():
                if name == "full" or not bbox:
                    continue
                l, t, r, b = [int(x) for x in bbox]
                col = colors.get(name, (200, 200, 200))
                cv2.rectangle(cvimg, (l, t), (r, b), col, 3)
                cv2.putText(cvimg, name.upper(), (l + 5, max(15, t + 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
            cv2.imwrite(out_path, cvimg)
            print(f"[calib] ROI preview (cv2) saved: {out_path}")
            return out_path
        else:
            pil = Image.open(image_path).convert("RGB")
            for name, bbox in (rois or {}).items():
                if name == "full" or not bbox:
                    continue
                pil = _pil_draw_rect(pil, bbox, name.upper(), color=(0, 200, 0) if name == "hero" else (200, 200, 0))
            pil.save(out_path)
            print(f"[calib] ROI preview (pil) saved: {out_path}")
            return out_path
    except Exception as ex:
        print(f"[calib] preview gen issue: {ex}")
        return image_path  # fallback to raw


def generate_card_crops(image_path: str, rois: dict | None = None, out_dir: str | None = None, max_per_area: int | None = None, client: str = None) -> dict:
    """Auto-detect card rects inside (tuned) ROIs on the sample, crop & save individual sprite PNGs to calib_crops/.
    Returns {'hero': [path0, path1], 'board': [p0..]} for wizard to prompt labels on.
    Reuses internal _detect_card_rects + crops (same logic as live parse).
    ENHANCED for easier template collection: during calib use even more permissive detect + higher max
    (show more crops), caller can request more via max_per_area. Wizard uses this for "show more crops".
    client: passed to get_poker_rois / get_clubgg_rois wrapper (CoinPoker / client specific ROIs when auto).
    """
    if client is None:
        client = DEFAULT_CLIENT
    if not os.path.exists(image_path):
        return {}
    cdir, _ = ensure_user_dirs()
    if out_dir:
        cdir = out_dir
        os.makedirs(cdir, exist_ok=True)
    crops: dict = {"hero": [], "board": []}
    maxh = max_per_area or 4
    maxb = max_per_area or 8
    try:
        pil = Image.open(image_path)
        w, h = pil.size
        if rois is None:
            rois = get_poker_rois(w, h, client=client)
        cvimg = None
        if HAS_CV2:
            cvimg = cv2.imread(image_path)
        sens = "low"  # during calib, be permissive to find candidate sprites (more for user choice)
        for area in ("hero", "board"):
            roi = rois.get(area)
            if not roi or cvimg is None:
                continue
            rects = _detect_card_rects(cvimg, roi, sensitivity=sens)
            limit = maxh if area == "hero" else maxb
            for idx, (x, y, ww, hh) in enumerate(rects[:limit]):
                try:
                    cpil = pil.crop((x, y, x + ww, y + hh))
                    cname = f"{area}_card_{idx:02d}.png"
                    cpath = os.path.join(cdir, cname)
                    cpil.save(cpath)
                    crops[area].append(cpath)
                except Exception:
                    pass
    except Exception as ex:
        print(f"[calib] card crop gen issue: {ex}")
    return crops


def save_card_template_from_crop(label: str, crop_path: str, templates_dir: str | None = None) -> str | None:
    """Copy/convert a user-verified crop (from wizard) into card_templates/<LABEL>.png .
    Normalizes name (Ah.png etc). Returns dest path or None.
    """
    if not label or not os.path.exists(crop_path):
        return None
    _, tdir = ensure_user_dirs()
    if templates_dir:
        tdir = templates_dir
        os.makedirs(tdir, exist_ok=True)
    key = label.strip().upper()
    m = re.match(r"^(10|[2-9TJQKA])([SHDC])$", key, re.IGNORECASE)
    if not m:
        # try normalize
        n = _normalize_card_token(key)
        if n:
            key = n
        else:
            return None
    r, s = key[0], key[1]
    if r == "10":
        r = "T"
    safe_key = r + s.lower()
    dest = os.path.join(tdir, f"{safe_key}.png")
    try:
        img = Image.open(crop_path).convert("RGB")
        # optional light normalize size for matching (keep aspect, reasonable card size)
        if HAS_CV2:
            try:
                import numpy as _np  # local, safe; np transitive via opencv
                cv = cv2.cvtColor(_np.array(img), cv2.COLOR_RGB2BGR)
            except Exception:
                pass
        # resize to ~ standard card crop height ~120-180px for template consistency (keeps detail)
        maxh = 160
        if img.height > maxh:
            ratio = maxh / float(img.height)
            neww = max(1, int(img.width * ratio))
            img = img.resize((neww, maxh), Image.LANCZOS)
        img.save(dest)
        print(f"[calib] saved template {safe_key}.png -> {dest}")
        # invalidate cache so next _get picks it up
        global _CARD_TEMPLATES
        _CARD_TEMPLATES = None
        return dest
    except Exception as ex:
        print(f"[calib] template save fail for {label}: {ex}")
        return None


def suggest_label_for_crop(crop_path: str, templates: dict | None = None, sensitivity: str | None = None) -> str | None:
    """Suggest a card label (e.g. 'Ah') for a calib crop PNG using the same recog/OCR path as live vision.
    Used by wizard for "accept all good" (auto-suggest then verify/accept) and pre-filled defaults in labeling.
    Returns normalized token or None. Graceful if no libs. Reuses _recognize_card_from_crop internally.
    """
    if not crop_path or not os.path.exists(crop_path):
        return None
    try:
        pil = Image.open(crop_path).convert("RGB")
        cv = None
        if HAS_CV2:
            try:
                cv = cv2.imread(crop_path)
            except Exception:
                cv = None
        tmpls = templates or _get_card_templates()
        sens = sensitivity or "low"  # calib: permissive
        rec = _recognize_card_from_crop(pil, cv, tmpls, sensitivity=sens)
        if rec:
            return rec
        # fallback direct ocr parse if recog gave none
        txt = _ocr_text_from_pil(pil, "--psm 7")
        cands = _parse_card_tokens(txt)
        if cands:
            return cands[0]
    except Exception:
        pass
    return None


if __name__ == "__main__":
    main()

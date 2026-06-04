"""
PokerFlex A1 Brain Configuration (PRIMARY / UNAMBIGUOUS DEFAULT)

All tunable parameters for the Strong Heuristic GTO engine (new A1 brain, default path).
This makes iteration much easier without touching logic code.

See also: force_legacy_brain (for forcing old shim path), exploitative_mode, icm_* etc.
"""

from dataclasses import dataclass

@dataclass
class GTOConfig:
    # Equity simulation settings
    default_equity_iters: int = 3000          # Good balance of speed vs accuracy for real-time
    fast_equity_iters: int = 800              # For very quick estimates
    accurate_equity_iters: int = 5000         # For --bench accurate or high-precision paths (no regression on default fast paths)

    # Configurable poll rates per mode (live real-time vs bg quiet set-and-forget)
    live_poll_interval_secs: float = 10.0     # responsive for --live hands-off (tunable via --live-poll-secs still honored)
    bg_quiet_poll_interval_secs: float = 20.0 # slower for periodic/bg when not actively listening, conserves CPU

    # Vision history for OCR spike / low-conf recovery heuristics (used in run_brain live + robust apply)
    vision_history_window: int = 5            # keep last N vision reads for streak/backoff decisions (partials, new-hand, corruption recovery)

    # Board texture thresholds
    dynamic_board_threshold: float = 0.45     # Boards above this are considered dynamic

    # Postflop decision thresholds (will be refined heavily in Phase 4)
    strong_hand_equity: float = 0.68
    good_hand_equity: float = 0.52
    marginal_hand_equity: float = 0.38

    # Bet sizing defaults (in bb or pot multiples)
    default_cbet_size: float = 0.65           # 65% pot c-bet
    default_barrel_size: float = 0.75         # Turn/river barrel size
    overbet_threshold: float = 1.2            # When to consider overbetting

    # Multiway adjustments
    multiway_tighten_factor: float = 0.12     # How much tighter ranges get per extra player

    # Postflop sizing and thresholds (A1 strong heuristic GTO)
    cbet_dry_size: float = 0.70               # larger on dry static for value/protection
    cbet_wet_size: float = 0.45               # smaller on dynamic/wet to realize equity
    cbet_paired_size: float = 0.55
    barrel_default_size: float = 0.65
    overbet_spr_threshold: float = 2.5        # SPR below which consider larger sizes or shoves
    value_threshold: float = 0.60             # equity-ish proxy for pure value
    semi_bluff_threshold: float = 0.38        # for barreling draws on good texture

    # Range/nut adv tuning
    range_adv_bet_boost: float = 0.15         # extra sizing from positive range adv

    # General
    use_cache: bool = True
    debug: bool = False

    # Force the legacy fallback brain path even when new brain (A1) is primary UNAMBIGUOUS default (for debugging / exact old output comparison ONLY). Never set for normal use. New A1 is always default.
    # Preferred: set env var POKERFLEX_FORCE_LEGACY_BRAIN=1 (or =true). CONFIG flag works if set before importing poker_engine.
    # When True, poker_engine.get_advice will use the exact original legacy implementation branch.
    # NOTE: new A1 brain (USE_NEW_BRAIN=True) is always the module default; this flag/env only for legacy.
    force_legacy_brain: bool = False

    # -----------------------------------------------------------------------
    # ICM / Tournament support (initial implementation: short-stack push/fold only)
    # Full ICM for deep stacks / complex payout calcs / all streets is future work.
    # Use via:
    #   - CONFIG.icm_enabled = True (affects legacy + new when no per-state override)
    #   - For new A1 brain: GameState(tournament_mode=True, players_remaining=N, ...)
    #     preflop will auto-estimate icm_factor using nash.get_icm_factor()
    #   - Or pass explicit icm_factor to nash.*_decision() for fine control.
    # Basic model adjusts EV thresholds: marginal shoves tighter, calls looser.
    # -----------------------------------------------------------------------
    icm_enabled: bool = False
    icm_default_factor: float = 0.12          # used when icm_enabled and no better estimate
    icm_final_table_players: int = 9
    icm_assume_paid_places: int = 0           # 0 = auto (~15-18%)

    # -----------------------------------------------------------------------
    # Exploitative mode (GTO vs Explo toggle). When True (or notes passed),
    # advisor/postflop will use player_notes via the range adjuster.
    # -----------------------------------------------------------------------
    exploitative_mode: bool = False
    exploit_fold_cbet_high: float = 0.65      # above this fold_to_cbet -> folder/nit exploit (bet wider)
    exploit_fold_cbet_low: float = 0.35       # below -> calling station (bet narrower, value only)
    exploit_af_high: float = 1.8              # high aggression_factor -> adjust call-downs etc.
    exploit_bet_freq_boost_max: float = 0.45  # cap on how much we boost bet freq from notes

    # ------------------------------------------------------------------
    # Background / console runner (run_brain.py) defaults & integration
    # These are used by the ClubGG / CoinPoker background A1 assistant for quick starts,
    # state persistence, notes, and capture stub. Tune here for your typical
    # poker session (e.g. 100bb deep, 6-max-ish). Use --client clubgg or --client coinpoker.
    # Calibrate once per client/table (python -m pokerflex calibrate -- for CoinPoker too), then 0-touch --live --real-vision + tray + hotkeys + notes.
    # (Files default to poker_* or clubgg_* for backward; multi-client via --client in capture/run_brain.)
    # ------------------------------------------------------------------
    default_position: str = "BTN"
    default_stack_bb: float = 100.0
    default_num_opponents: int = 2
    default_ante_bb: float = 0.0
    player_notes_file: str = "poker_player_notes.json"
    runner_state_file: str = "poker_current_state.json"
    capture_output: str = "poker_live.png"
    hotkey_analyze: str = "ctrl+alt+a"
    hotkey_status: str = "ctrl+alt+s"
    hotkey_capture: str = "ctrl+alt+c"
    hotkey_overlay: str = "ctrl+alt+o"  # toggle lightweight always-on floating advice overlay (compact A1)

    # Vision hardening tunables (for capture.py + run_brain live; exposed here for central config + future GUI).
    # Values here are module defaults; runner --live etc override via CLI / set_vision_params.
    # history_len enables temporal smoothing / vote / new-deal detection.
    # adaptive + ocr_voting + street_action enable the hardened preproc/OCR/pot-bet extract paths.
    vision_history_len: int = 5
    vision_adaptive_preproc: bool = True
    vision_ocr_voting: bool = True
    vision_street_action: bool = True  # pot, facing_bet, street, action_hint auto-extract from image for live facing usability

    # NEW (this task) vision tunables for real-OCR harden on ClubGG / CoinPoker (card detect, template, suit color, scale, etc).
    # Used by capture.set_vision_params + runner wiring; also seed from CONFIG if desired in future.
    # Works identically for --client coinpoker (calib per-client produces client-aware vision_config).
    vision_template_conf_boost: float = 0.12
    vision_suit_color_heuristic: bool = True
    vision_detection_morph: bool = True
    vision_detection_multiscale: bool = True
    vision_auto_scale_rois: bool = True
    vision_rank_whitelist: str = "23456789TJQKA10"


# Global config instance (can be overridden later if needed)
CONFIG = GTOConfig()

"""
PokerFlex A1 - Core Data Models (PRIMARY BRAIN - UNAMBIGUOUS DEFAULT)

These are the central abstractions for the Strong Heuristic GTO brain (A1 default everywhere).
GameState is the single source of truth; used by advisor, preflop, postflop.
legacy_to_gamestate bridges old GUI inputs (main.py, tests) to new A1 brain (unambiguous default path; `python -m pokerflex` etc). Legacy path only for forced debug compat (never primary).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any, Union
import json
from pathlib import Path

from .config import CONFIG  # for consistent default notes file (clubgg_player_notes.json for runner/GUI compat)


class Street(Enum):
    PREFLOP = 0
    FLOP = 3
    TURN = 4
    RIVER = 5


@dataclass(frozen=True)
class BoardTexture:
    """Rich description of the board texture."""
    paired: bool = False
    pair_rank: Optional[str] = None
    flush_category: str = "rainbow"          # rainbow | two_tone | monotone
    straight_category: str = "dry"           # dry | semi_connected | very_connected
    high_card: str = "A"
    dynamic_score: float = 0.0               # 0.0 (static) to 1.0 (very dynamic)
    has_flush_draw: bool = False
    has_straight_draw: bool = False

    def summary(self) -> str:
        parts = []
        if self.paired:
            parts.append(f"paired ({self.pair_rank})")
        parts.append(self.flush_category)
        parts.append(self.straight_category)
        return ", ".join(parts)


@dataclass
class Board:
    """Represents the current community cards."""
    cards: List[str]                         # e.g. ["Qd", "7h", "2c"]
    street: Street

    _texture: Optional[BoardTexture] = None

    def texture(self) -> BoardTexture:
        """Lazily compute texture using the dedicated analyzer."""
        if self._texture is None:
            from .board_texture import analyze_board
            self._texture = analyze_board(self.cards)
        return self._texture


@dataclass
class ActionEvent:
    """
    First-class structured event for action_history tracking.
    Enables multi-street memory for smarter range construction, blocker
    awareness, aggression history, and story detection (e.g. donk vs check-call).
    Use via GameState.action_history (list of these, or dicts for compat/json).
    """
    street: str                          # "preflop" | "flop" | "turn" | "river"
    actor: str                           # "hero" | "villain" | "unknown"
    action: str                          # "check" | "bet" | "call" | "raise" | "fold" | "shove" | "3bet" etc (lowercased)
    size: Optional[float] = None         # bet/raise size in bb (absolute)
    pot_before: Optional[float] = None   # pot size before this action (bb)

    def to_dict(self) -> Dict[str, Any]:
        """For json serialization / state files / legacy compat."""
        d: Dict[str, Any] = {"street": self.street, "actor": self.actor, "action": self.action}
        if self.size is not None:
            d["size"] = float(self.size)
        if self.pot_before is not None:
            d["pot_before"] = float(self.pot_before)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ActionEvent":
        """Robust parse from dict (tolerates missing keys, string nums)."""
        if not isinstance(d, dict):
            d = {}
        street = str(d.get("street", d.get("st", "preflop"))).lower().strip()
        actor = str(d.get("actor", d.get("who", "unknown"))).lower().strip()
        action = str(d.get("action", d.get("act", ""))).lower().strip()
        size = None
        if d.get("size") is not None:
            try:
                size = float(d.get("size"))
            except Exception:
                size = None
        potb = None
        if d.get("pot_before") is not None:
            try:
                potb = float(d.get("pot_before"))
            except Exception:
                potb = None
        return cls(street=street or "preflop", actor=actor or "unknown", action=action or "unknown", size=size, pot_before=potb)


@dataclass
class GameState:
    """
    The single source of truth for any decision.

    Designed to work with both manual input (current GUI) and future vision input.
    All fields should be Optional where reasonable so partial data still works.
    """
    hero_hand: List[str]                     # ["Ah", "Ks"]
    board: Board

    # Betting / stack info
    pot: float = 1.5                           # in big blinds
    effective_stack: float = 100.0             # in big blinds
    bet_to_call: float = 0.0                   # current bet facing hero

    # Positional / player info
    hero_position: str = "BTN"
    num_opponents: int = 1

    # ICM / tournament context (short-stack push/fold + deeper postflop ICM approx)
    # When tournament_mode=True, preflop/postflop consult nash.get_icm_factor (now
    # supports concrete payout_structure) and get_postflop_icm_adjustments for
    # 8-20bb spots on bubble/final. payout_structure e.g. [0.5,0.3,0.2] or
    # [0.40,0.25,0.20,0.10,0.05] for 6-9 players; used to modulate factor/adj.
    # stack_sizes for future richer; icm_factor explicit override.
    # See nash.py for get_postflop_icm_adjustments + simulate_shortstack_icm_ev.
    tournament_mode: bool = False
    players_remaining: Optional[int] = None
    stack_sizes: List[float] = field(default_factory=list)       # bb, e.g. [hero, v1, v2, ...]
    payout_structure: List[float] = field(default_factory=list)  # e.g. [0.50, 0.30, 0.20] or 40/25/20/10/5 etc; concrete support in factor+postflop ICM
    icm_factor: float = 0.0                                      # explicit override (>0 forces ICM adjustment even without tournament_mode)
    ante_bb: float = 0.0                                             # big blind ante (dead money), used in short-stack Nash + pot calcs

    # Action context
    facing_action: Optional[str] = None        # "bet", "check-raise", "donk", etc.
    action_history: List[ActionEvent] = field(default_factory=list)  # first-class; accepts List[Dict] via __post_init__ / from_dict for json/compat

    # Optional future fields
    villain_ranges: Dict[str, Any] = field(default_factory=dict)  # placeholder for now
    player_notes: Dict[str, Any] = field(default_factory=dict)    # e.g. {"villain": {"fold_to_cbet": 0.75, ...}, "notes": "nit"} or flat tendencies for primary villain. Populated for explo play.

    def __post_init__(self):
        """Normalize action_history to List[ActionEvent] (accepts raw dicts from json/state/legacy)."""
        if not isinstance(self.action_history, list):
            self.action_history = []
            return
        norm: List[ActionEvent] = []
        for item in self.action_history:
            if isinstance(item, ActionEvent):
                norm.append(item)
            elif isinstance(item, dict):
                try:
                    norm.append(ActionEvent.from_dict(item))
                except Exception:
                    # fallback: keep raw dict for extreme compat (history consumers should handle)
                    # but prefer typed; create minimal
                    try:
                        norm.append(ActionEvent(street=str(item.get("street","preflop")), actor=str(item.get("actor","unknown")), action=str(item.get("action",""))))
                    except Exception:
                        pass  # drop unparsable
            # ignore other types
        self.action_history = norm

    def append_action(self, event: Union[ActionEvent, Dict[str, Any], None]) -> None:
        """Append (and normalize) an action event. Idempotent-safe for history tracking."""
        if event is None:
            return
        if not isinstance(self.action_history, list):
            self.action_history = []
        if isinstance(event, dict):
            try:
                ev = ActionEvent.from_dict(event)
            except Exception:
                ev = ActionEvent(street=str(event.get("street", "preflop")), actor=str(event.get("actor", "unknown")), action=str(event.get("action", "")))
        elif isinstance(event, ActionEvent):
            ev = event
        else:
            return
        self.action_history.append(ev)

    def clear_action_history(self) -> None:
        """Reset for new hand (called on deal in runner/live)."""
        self.action_history = []

    def get_action_history_dicts(self) -> List[Dict[str, Any]]:
        """Return copy as plain dicts (for json, status, passing)."""
        out = []
        for e in (self.action_history or []):
            if isinstance(e, ActionEvent):
                out.append(e.to_dict())
            elif isinstance(e, dict):
                out.append(dict(e))
            else:
                out.append({"raw": str(e)})
        return out

    @property
    def street(self) -> Street:
        return self.board.street

    @property
    def spr(self) -> float:
        if self.bet_to_call > 0:
            return self.effective_stack / self.bet_to_call
        return self.effective_stack / max(self.pot, 1.0)

    @property
    def pot_odds(self) -> float:
        if self.bet_to_call <= 0:
            return 0.0
        return self.bet_to_call / (self.pot + self.bet_to_call)


@dataclass
class Action:
    """Represents a recommended action."""
    action_type: str                         # fold, check, call, bet, raise, shove
    size_bb: Optional[float] = None
    size_pot: Optional[float] = None         # size as multiple of pot
    reasoning: str = ""


@dataclass
class Decision:
    """
    Output of the GTOHeuristicAdvisor.
    Rich enough for both text display and future structured use (voice, overlay, etc.).
    """
    primary_action: Action
    alternatives: List[Action] = field(default_factory=list)
    explanation: str = ""
    confidence: float = 0.0
    metrics: Dict[str, float] = field(default_factory=dict)   # equity, range_adv, nut_adv, blockers, etc.
    texture_summary: str = ""
    hand_class: str = ""


# Helper for legacy compatibility
def legacy_to_gamestate(
    position: str,
    hand: str,
    board: str,
    opponents: str,
    stack: str,
    ante: str,
    player_notes: Optional[Dict[str, Any]] = None,
    tournament_mode: bool = False,
    players_remaining: Optional[int] = None,
    icm_factor: float = 0.0,
    payout_structure: Optional[list] = None,
    action_history: Optional[List[Dict[str, Any]]] = None,
    bet_to_call: Optional[float] = None,
    pot: Optional[float] = None,
    facing_action: Optional[str] = None,
) -> GameState:
    """
    Robust bridge from the old string-based GUI/legacy input to GameState.
    Handles messy user input (e.g. "100bb", "1.5", "2", empty fields).
    Sets reasonable defaults for pot/bet_to_call so new brain produces sensible
    advice for common spots (open-raise, short-stack, BB defend, postflop c-bet).
    This is the primary construction path used by get_advice (USE_NEW_BRAIN=True default).

    New ICM fields (tournament_mode, players_remaining, icm_factor, payout_structure) default to cash-game / chip-EV behavior.
    Callers (run_brain, tests, advisor) can pass tournament_mode=True (auto-computes icm via nash.get_icm_factor
    using players_remaining + payout_structure) or explicit icm_factor>0 or payout e.g. [0.5,0.3,0.2]
    to engage deeper short-stack ICM (preflop Nash + postflop threshold/sizing adjustments for 8-20bb bubble spots).
    Concrete payout examples: 50/30/20 (6p), 40/25/20/10/5 (9p). See nash.simulate_shortstack_icm_ev too.
    """
    from .parsing import parse_cards, normalize_position, cards_to_strings  # use central parser (no longer from poker_engine)

    # Parse cards safely (robust to bad input)
    parsed_hero = []
    try:
        if hand and hand.strip():
            parsed_hero = parse_cards(hand)
    except Exception:
        parsed_hero = []
    hero = cards_to_strings(parsed_hero)

    parsed_board = []
    try:
        if board and board.strip():
            parsed_board = parse_cards(board)
    except Exception:
        parsed_board = []
    board_cards = cards_to_strings(parsed_board)

    street = Street.PREFLOP if not board_cards else Street(len(board_cards))

    b = Board(cards=board_cards, street=street)

    # Opponents
    try:
        n_opp = max(1, int("".join(c for c in opponents if c.isdigit()) or 1))
    except Exception:
        n_opp = 1

    # Stack (bb)
    try:
        bb = float("".join(c for c in stack if c.isdigit() or c == ".") or 100)
    except Exception:
        bb = 100.0

    # Ante robust (handles "1.5", "1bb", "0", "", " 1.0 ")
    try:
        adigits = "".join(c for c in (ante or "") if c.isdigit() or c == ".")
        ante_bb = float(adigits) if adigits else 0.0
    except Exception:
        ante_bb = 0.0

    # Pot estimation: preflop ~1.5 + ante. Postflop add a bit for typical raised pot.
    pot = 1.5 + ante_bb
    if street != Street.PREFLOP:
        pot += 2.5  # rough (open + cbet context) — sufficient for heuristic SPR/odds

    # bet_to_call + facing: legacy GUI provides no explicit bet size/facing info.
    # Default 0 (we are IP or checked-to, or preflop opener).
    # Special case: BB preflop is typically "vs raise" in test spots.
    bet_to_call = 0.0
    facing_action = None
    pos_norm = normalize_position(position) or (position or "").upper() or "BTN"
    if pos_norm == "BB" and street == Street.PREFLOP:
        bet_to_call = 2.5  # assume standard raise to call
        facing_action = "bet"
        pot = 4.0 + ante_bb  # bb + raise

    # Allow explicit overrides (from runner action cmds, live state, or direct GameState users).
    # This makes 'action villain bet 4.5' able to set realistic facing/pot for current decision.
    if pot is not None:
        try:
            pot = float(pot)
        except Exception:
            pass  # keep computed
    if bet_to_call is not None:
        try:
            bet_to_call = float(bet_to_call)
        except Exception:
            pass
    if facing_action is not None:
        facing_action = str(facing_action) if facing_action else None

    # Derive a sensible players_remaining for ICM estimator if not supplied
    n_rem = players_remaining if players_remaining is not None else (n_opp + 1)

    # Compute effective icm_factor (supports deeper ICM): if not explicit, and tmode, use nash.get_icm_factor
    # with players + payout_structure (now concrete). This ensures preflop (and postflop via advisor) see
    # payout-modulated factor even if caller didn't precompute. Payout can be list or "0.5,0.3,0.2" str.
    eff_icm = float(icm_factor or 0.0)
    ps_for_icm = payout_structure
    if isinstance(ps_for_icm, str):
        try:
            ps_for_icm = [float(x.strip()) for x in ps_for_icm.replace(";", ",").split(",") if x.strip()]
        except Exception:
            ps_for_icm = None
    if eff_icm <= 0.0 and (tournament_mode or getattr(CONFIG, "icm_enabled", False)):
        try:
            from . import nash as _nash
            is_ft = (n_rem or 99) <= getattr(CONFIG, "icm_final_table_players", 9)
            eff_icm = _nash.get_icm_factor(n_rem or 6, bb, is_final_table=is_ft, payout_structure=ps_for_icm)
        except Exception:
            eff_icm = float(getattr(CONFIG, "icm_default_factor", 0.10)) if tournament_mode else 0.0

    # Normalize payout for GameState (list of float)
    ps_norm = []
    if ps_for_icm and isinstance(ps_for_icm, (list, tuple)):
        try:
            ps_norm = [float(x) for x in ps_for_icm if x is not None]
        except Exception:
            ps_norm = []
    elif payout_structure and isinstance(payout_structure, (list, tuple)):
        try:
            ps_norm = [float(x) for x in payout_structure if x is not None]
        except Exception:
            ps_norm = []

    gs = GameState(
        hero_hand=hero,
        board=b,
        effective_stack=bb,
        num_opponents=n_opp,
        pot=pot,
        bet_to_call=bet_to_call,
        facing_action=facing_action,
        hero_position=pos_norm,
        tournament_mode=tournament_mode,
        players_remaining=n_rem,
        icm_factor=eff_icm,
        payout_structure=ps_norm,
        ante_bb=ante_bb,
        action_history=action_history or [],
    )
    if player_notes:
        gs.player_notes = dict(player_notes)  # copy
    # History normalized by GameState.__post_init__ (dicts -> ActionEvent list)
    # Also ensure explicit pot/bet overrides took (in case post_init or other mutated)
    if pot is not None:
        try: gs.pot = float(pot)
        except Exception: pass
    if bet_to_call is not None:
        try: gs.bet_to_call = float(bet_to_call)
        except Exception: pass
    if facing_action is not None:
        gs.facing_action = facing_action
    return gs


# =============================================================================
# Basic Exploitative Player Notes System (lightweight, heuristic, no ML)
# =============================================================================

@dataclass
class PlayerTendencies:
    """
    Simple dataclass model for per-player tendencies / notes.
    Values are floats typically 0.0-1.0 (frequencies) or >1 for factors.
    Used to drive exploitative range adjustments vs pure GTO.
    Enhanced for multi-villain (seat/pos/name keys), preflop dynamic too.
    """
    player_key: str = "default_villain"
    fold_to_cbet: float = 0.50
    fold_to_cbet_dry: float = 0.50
    fold_to_cbet_wet: float = 0.50
    aggression_factor: float = 1.00   # (bets+raises)/calls ; >1.0 loose-aggressive
    cbet_freq: float = 0.55
    threebet_freq: float = 0.08
    fold_to_3bet: float = 0.55
    call_down_freq: float = 0.45
    overfold_factor: float = 0.0      # observed extra folding beyond population
    preflop_open_tight: float = 1.0   # >1.0 villain opens tighter (hero can steal wider)
    preflop_3bet_freq: float = 0.08   # villain 3bet freq (affects hero 3b/4b/fold decisions)
    notes: str = ""                   # free-form human notes

    def to_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items()}
        return d


class PlayerNotesManager:
    """
    Simple storage for player notes/tendencies.
    - In-memory dict
    - Optional JSON persistence (defaults to CONFIG.player_notes_file = clubgg_player_notes.json for runner + GUI + send-to-runner compat; falls back to generic player_notes.json if needed)
    - Keyed by normalized player name or seat/position (e.g. 'nit', 'seat3', 'btn_villain', 'seat2_co') — supports vision-provided seat/pos/name when available.
    - Provides presets for common explo types (nit, station, aggro) + user-defined custom named profiles.
    - Edit history tracking for audit / undo feel in editor UX.
    - export/import for backup/share.
    - describe_effect for live preview ("nit: cbet freq now 35% wider value range on dry").
    - Fully toggleable: if no notes or GTO mode, no effect.
    """
    def __init__(self, persist_path: Optional[str] = None):
        if persist_path is None:
            persist_path = getattr(CONFIG, "player_notes_file", "clubgg_player_notes.json")
        self.persist_path = persist_path
        self._notes: Dict[str, Dict[str, Any]] = {}
        self._edit_history: List[Dict[str, Any]] = []
        self._custom_presets: Dict[str, Dict[str, Any]] = {}
        self.load()

    def _normalize_key(self, player: str) -> str:
        if not player or not str(player).strip():
            player = "default_villain"
        k = str(player).strip().lower().replace(" ", "_").replace("/", "_")[:40]
        # Enhance multi-villain: support explicit seat/pos like 'seat3', 'btn', 'co_villain'
        if k.startswith("seat") or k in ("btn", "sb", "bb", "utg", "mp", "co", "hj"):
            pass  # already good for vision seat/pos keys
        return k

    def get_notes(self, player: str = "villain") -> Dict[str, Any]:
        """Return merged defaults + stored tendencies for this player."""
        k = self._normalize_key(player)
        defaults = {
            "fold_to_cbet": 0.50,
            "fold_to_cbet_dry": 0.50,
            "fold_to_cbet_wet": 0.50,
            "aggression_factor": 1.00,
            "cbet_freq": 0.55,
            "3bet_freq": 0.08,
            "fold_to_3bet": 0.55,
            "call_down_freq": 0.45,
            "overfold_factor": 0.0,
            "preflop_open_tight": 1.0,
            "preflop_3bet_freq": 0.08,
            "notes": "",
        }
        stored = self._notes.get(k, {})
        merged = defaults.copy()
        merged.update({kk: vv for kk, vv in stored.items() if kk in defaults or kk == "notes" or "factor" in kk or "preflop" in kk})
        # allow extra custom keys (e.g. user free fields)
        for kk, vv in stored.items():
            if kk not in merged:
                merged[kk] = vv
        return merged

    def _record_history(self, player: str, key: str, old: Any, new: Any) -> None:
        """Track edit history (for UX preview/audit in editor)."""
        self._edit_history.append({
            "ts": __import__("time").time(),
            "player": self._normalize_key(player),
            "key": key,
            "old": old,
            "new": new,
        })
        # keep last 50
        if len(self._edit_history) > 50:
            self._edit_history = self._edit_history[-50:]

    def set_notes(self, player: str, tendencies: Dict[str, Any]) -> None:
        """Overwrite/update tendencies for player. Clamps freqs, saves.
        Special: setting 'fold_to_cbet' base also propagates to _dry/_wet unless they are explicitly different.
        This makes quick 'note nit fold_to_cbet 0.78' (or set) work for all textures as expected.
        Records history for enhanced UX.
        """
        k = self._normalize_key(player)
        if k not in self._notes:
            self._notes[k] = {}
        for key, val in tendencies.items():
            old = self._notes[k].get(key)
            if isinstance(val, (int, float)) and key not in ("notes", "player_key"):
                # clamp reasonable
                if "factor" in key or "af" in key.lower() or "tight" in key.lower():
                    val = max(0.2, min(3.5, float(val)))
                else:
                    val = max(0.0, min(1.0, float(val)))
            self._notes[k][key] = val
            if old != val:
                self._record_history(player, key, old, val)
        # Propagate base fold_to_cbet to texture specifics if only base provided (or they match old default)
        if "fold_to_cbet" in self._notes[k]:
            base = self._notes[k]["fold_to_cbet"]
            for spec in ("fold_to_cbet_dry", "fold_to_cbet_wet"):
                if spec not in self._notes[k] or abs(float(self._notes[k].get(spec, 0.5)) - 0.5) < 0.001:
                    oldspec = self._notes[k].get(spec)
                    self._notes[k][spec] = base
                    if oldspec != base:
                        self._record_history(player, spec, oldspec, base)
        self.save()

    def update_tendency(self, player: str, key: str, value: Any) -> Dict[str, Any]:
        k = self._normalize_key(player)
        if k not in self._notes:
            self._notes[k] = {}
        old = self._notes[k].get(key)
        self._notes[k][key] = value
        if old != value:
            self._record_history(player, key, old, value)
        # Propagate base fold_to_cbet (from CLI 'note p fold_to_cbet X' etc) to dry/wet for consistent explo on textures
        if key == "fold_to_cbet" and isinstance(value, (int, float)):
            base = float(value)
            for spec in ("fold_to_cbet_dry", "fold_to_cbet_wet"):
                if spec not in self._notes[k] or abs(float(self._notes[k].get(spec, 0.5)) - 0.5) < 0.001:
                    oldspec = self._notes[k].get(spec)
                    self._notes[k][spec] = base
                    if oldspec != base:
                        self._record_history(player, spec, oldspec, base)
        self.save()
        return self.get_notes(player)

    def add_free_note(self, player: str, text: str) -> None:
        k = self._normalize_key(player)
        if k not in self._notes:
            self._notes[k] = {}
        prev = self._notes[k].get("notes", "") or ""
        new = (prev + " | " + str(text)).strip(" |") if prev else str(text)
        old = prev
        self._notes[k]["notes"] = new
        if old != new:
            self._record_history(player, "notes", old, new)
        self.save()

    def list_players(self) -> List[str]:
        # filter out internal meta keys like _custom_presets
        return sorted([kk for kk in self._notes.keys() if not kk.startswith("_")])

    def load(self) -> None:
        if not self.persist_path:
            return
        p = Path(self.persist_path)
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        # support legacy + new: presets stored under meta key
                        if "_custom_presets" in data:
                            self._custom_presets = data.pop("_custom_presets", {}) or {}
                        if "_edit_history" in data:  # optional persisted history (rare)
                            self._edit_history = data.pop("_edit_history", []) or []
                        self._notes = {kk: vv for kk, vv in data.items() if not str(kk).startswith("_")}
            except Exception:
                self._notes = {}

    def save(self) -> None:
        if not self.persist_path:
            return
        try:
            p = Path(self.persist_path)
            tosave = dict(self._notes)
            if self._custom_presets:
                tosave["_custom_presets"] = self._custom_presets
            # do not persist full history to keep json small (in-mem only for session UX)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(tosave, f, indent=2, sort_keys=True)
        except Exception:
            pass  # silent fail for robustness in poker session

    def clear(self, player: Optional[str] = None) -> None:
        if player:
            k = self._normalize_key(player)
            self._notes.pop(k, None)
        else:
            self._notes.clear()
        self.save()

    # --- Enhanced: multi-villain seat/pos/name support (vision ready) ---
    def get_notes_by_seat_or_name(self, seat: Optional[int] = None, name: Optional[str] = None, position: Optional[str] = None) -> Dict[str, Any]:
        """Flexible lookup for when vision/OCR provides seat number, name, or position label.
        E.g. seat=3, pos='BTN' -> tries 'seat3_btn' then 'seat3' then 'btn'.
        Falls back to 'villain' / default.
        """
        candidates = []
        if name:
            candidates.append(name)
        if seat is not None:
            seatk = f"seat{int(seat)}"
            candidates.append(seatk)
            if position:
                candidates.append(f"{seatk}_{str(position).lower()}")
                candidates.append(f"{str(position).lower()}_seat{int(seat)}")
        if position:
            candidates.append(str(position).lower())
        for cand in candidates:
            k = self._normalize_key(cand)
            if k in self._notes:
                return self.get_notes(cand)
        # default
        return self.get_notes(name or "villain")

    # --- Enhanced UX: live effect preview (used by runner editor + status) ---
    def describe_effect(self, player: str = "villain") -> str:
        """Return a concise live-preview string of how this note profile affects decisions.
        Example: 'nit: cbet freq now 35% wider value range on dry ; call down lighter vs aggro'
        Safe, always returns something useful even for neutral/defaults.
        """
        n = self.get_notes(player)
        ftc = float(n.get("fold_to_cbet", n.get("fold_to_cbet_dry", 0.5)))
        af = float(n.get("aggression_factor", 1.0))
        cbf = float(n.get("cbet_freq", 0.55))
        t3b = float(n.get("preflop_3bet_freq", n.get("3bet_freq", 0.08)))
        tight = float(n.get("preflop_open_tight", 1.0))
        parts = []
        if ftc >= 0.65:
            boost = min(55, int(round((ftc - 0.5) * 140)))
            parts.append(f"cbet freq now {boost}% wider value range on dry")
        elif ftc <= 0.38:
            red = min(45, int(round((0.5 - ftc) * 140)))
            parts.append(f"value bet only, {red}% less bluffs (station)")
        else:
            parts.append("cbet ~population")
        if af >= 1.7:
            parts.append(f"call down lighter vs high AF={af:.1f}")
        elif af <= 0.7:
            parts.append("vs passive: bet thinner for value")
        if t3b >= 0.18:
            parts.append("preflop: 3bet/4bet lighter (aggro villain)")
        elif t3b <= 0.04:
            parts.append("preflop: steal/3bet bluff wider (nit villain)")
        if abs(tight - 1.0) > 0.15:
            if tight > 1.1:
                parts.append("preflop opens: villain tighter -> hero steals more")
            else:
                parts.append("preflop: villain loose -> defend tighter")
        if not parts or len(parts) == 1 and parts[0] == "cbet ~population":
            parts = ["neutral vs population (GTO default)"]
        free = str(n.get("notes", ""))[:30]
        suffix = f" | notes: {free}" if free else ""
        return f"{self._normalize_key(player)}: " + " ; ".join(parts) + suffix

    # --- Enhanced: export / import (backup, share profiles, multi-session) ---
    def export_notes(self, path: Optional[str] = None) -> Dict[str, Any]:
        """Return (and optionally write) full export including customs (no history)."""
        data = {
            "_exported_at": __import__("time").time(),
            "_version": "enhanced-notes-v1",
            "notes": dict(self._notes),
            "custom_presets": dict(self._custom_presets),
        }
        if path:
            try:
                pp = Path(path)
                with open(pp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass
        return data

    def import_notes(self, data: Dict[str, Any], merge: bool = True, apply_to_mgr: bool = True) -> int:
        """Import notes (and presets). merge=True keeps existing keys. Returns #players imported."""
        imported = 0
        if not isinstance(data, dict):
            return 0
        src_notes = data.get("notes", data)  # support raw or wrapped export
        if not merge:
            self._notes = {}
        for kk, vv in (src_notes or {}).items():
            if str(kk).startswith("_"):
                continue
            nk = self._normalize_key(kk)
            if isinstance(vv, dict):
                self._notes[nk] = dict(vv)
                imported += 1
        if "custom_presets" in data:
            cps = data.get("custom_presets") or {}
            if not merge:
                self._custom_presets = {}
            self._custom_presets.update({self._normalize_key(k): v for k, v in cps.items() if isinstance(v, dict)})
        if apply_to_mgr:
            self.save()
        return imported

    # --- Custom user-defined named profiles/presets (beyond 3 builtins) ---
    def save_custom_preset(self, name: str, template: Dict[str, Any]) -> str:
        """Save a reusable custom profile. e.g. 'my_co_nit': {'fold_to_cbet':0.72, ...}"""
        nk = self._normalize_key(name)
        clean = {k: v for k, v in (template or {}).items() if k != "player_key"}
        self._custom_presets[nk] = clean
        self.save()
        return nk

    def apply_custom_preset(self, player: str, preset_name: str) -> Dict[str, Any]:
        nk = self._normalize_key(preset_name)
        if nk in self._custom_presets:
            self.set_notes(player, self._custom_presets[nk])
            return self.get_notes(player)
        # fallback try builtin name match
        low = preset_name.lower()
        if "nit" in low:
            return self.apply_nit_preset(player)
        if "station" in low or "call" in low:
            return self.apply_calling_station_preset(player)
        if "aggro" in low or "maniac" in low:
            return self.apply_aggro_preset(player)
        return self.get_notes(player)

    def list_presets(self) -> List[str]:
        """All available named profiles: builtins + user customs."""
        builtins = ["nit", "station", "maniac"]
        customs = sorted(self._custom_presets.keys())
        return builtins + [c for c in customs if c not in builtins]

    def get_edit_history(self, player: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Recent edits (for editor UX 'history' command)."""
        h = self._edit_history
        if player:
            pk = self._normalize_key(player)
            h = [e for e in h if e.get("player") == pk]
        return list(reversed(h[-limit:]))

    # Convenience presets for testing / quick setup (unchanged behavior, now record history + support preflop keys)
    def apply_nit_preset(self, player: str = "nit") -> Dict[str, Any]:
        self.set_notes(player, {
            "fold_to_cbet": 0.78,
            "fold_to_cbet_dry": 0.85,
            "fold_to_cbet_wet": 0.62,
            "aggression_factor": 0.55,
            "3bet_freq": 0.025,
            "preflop_3bet_freq": 0.025,
            "preflop_open_tight": 1.35,
            "call_down_freq": 0.22,
            "notes": "NIT: overfolds vs c-bets (esp dry boards), low aggression, tight preflop 3bet. Exploit by c-betting wide + thin value."
        })
        return self.get_notes(player)

    def apply_calling_station_preset(self, player: str = "station") -> Dict[str, Any]:
        self.set_notes(player, {
            "fold_to_cbet": 0.28,
            "fold_to_cbet_dry": 0.22,
            "fold_to_cbet_wet": 0.35,
            "aggression_factor": 0.65,
            "call_down_freq": 0.78,
            "3bet_freq": 0.04,
            "preflop_3bet_freq": 0.04,
            "preflop_open_tight": 0.75,
            "notes": "CALLING STATION: calls too much, low folds to cbet, poor fold equity for our bluffs. Exploit: value bet thinner? No: bet only strong value, check medium, reduce bluffs."
        })
        return self.get_notes(player)

    def apply_aggro_preset(self, player: str = "maniac") -> Dict[str, Any]:
        self.set_notes(player, {
            "fold_to_cbet": 0.42,
            "aggression_factor": 2.8,
            "cbet_freq": 0.82,
            "3bet_freq": 0.22,
            "preflop_3bet_freq": 0.22,
            "preflop_open_tight": 0.8,
            "call_down_freq": 0.35,
            "notes": "MANIAC/AGGRESSIVE: high AF, over c-bets, light 3bets. Exploit: call down lighter, raise more for value/thin, 3bet bluff less vs them?"
        })
        return self.get_notes(player)


# Singleton manager (global for session; reset in tests if needed)
_notes_manager: Optional[PlayerNotesManager] = None


def get_notes_manager() -> PlayerNotesManager:
    global _notes_manager
    if _notes_manager is None:
        _notes_manager = PlayerNotesManager()
    return _notes_manager


def get_player_notes(player: str = "villain") -> Dict[str, Any]:
    """Public API: fetch tendencies for a player (by name, seat, 'villain', etc)."""
    return get_notes_manager().get_notes(player)


def set_player_notes(player: str, tendencies: Dict[str, Any]) -> None:
    """Public API: store tendencies."""
    get_notes_manager().set_notes(player, tendencies)


def update_player_tendency(player: str, key: str, value: Any) -> Dict[str, Any]:
    """Public API: single key update."""
    return get_notes_manager().update_tendency(player, key, value)


def apply_nit_preset(player: str = "nit") -> Dict[str, Any]:
    return get_notes_manager().apply_nit_preset(player)


def apply_calling_station_preset(player: str = "station") -> Dict[str, Any]:
    return get_notes_manager().apply_calling_station_preset(player)


def apply_aggro_preset(player: str = "maniac") -> Dict[str, Any]:
    return get_notes_manager().apply_aggro_preset(player)


# --- Enhanced public API for multi-villain / history / export/import / presets / preview (no breakage) ---
def get_notes_by_seat_or_name(seat: Optional[int] = None, name: Optional[str] = None, position: Optional[str] = None) -> Dict[str, Any]:
    return get_notes_manager().get_notes_by_seat_or_name(seat=seat, name=name, position=position)

def describe_explo_effect(player: str = "villain") -> str:
    """Live preview string for UX (editor, status, GUI)."""
    return get_notes_manager().describe_effect(player)

def save_custom_preset(name: str, template: Dict[str, Any]) -> str:
    return get_notes_manager().save_custom_preset(name, template)

def apply_custom_preset(player: str, preset_name: str) -> Dict[str, Any]:
    return get_notes_manager().apply_custom_preset(player, preset_name)

def list_all_presets() -> List[str]:
    return get_notes_manager().list_presets()

def export_player_notes(path: Optional[str] = None) -> Dict[str, Any]:
    return get_notes_manager().export_notes(path)

def import_player_notes(data: Dict[str, Any], merge: bool = True) -> int:
    return get_notes_manager().import_notes(data, merge=merge)

def get_notes_edit_history(player: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    return get_notes_manager().get_edit_history(player, limit)

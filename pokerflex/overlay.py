"""
PokerFlex lightweight always-on advice overlay (optional, graceful).
Small always-on-top floating window (uses stdlib tkinter — no new hard deps).
Shows compact A1: primary action + key reason + ICM/EXPLOIT tags.
Toggle via hotkey (ctrl+alt+o), tray menu, or API.
Updates automatically on every analyze (hotkey or live auto).
Rich full A1 (incl history + postflop ICM) remains in log / last_advice.txt / console / tray Status.

Keep tiny + non-intrusive: small fixed size, topmost, draggable titlebar, minimal UI.
Auto-hides on quit; persists position lightly (best-effort).
"""

import os
import threading
import time
from typing import Optional, Dict

# No hard deps beyond stdlib (tkinter ships with python; ctk used elsewhere in app but not here for lightness).

_HAS_TK = False
try:
    import tkinter as tk
    from tkinter import font as tkfont
    _HAS_TK = True
except Exception:
    _HAS_TK = False


class AdviceOverlay:
    """Compact always-on-top advice floater. Thread-safe update from other threads via after()."""

    def __init__(self):
        self.root: Optional["tk.Tk"] = None
        self.visible: bool = False
        self._drag_data = {"x": 0, "y": 0}
        self.lbl_action: Optional["tk.Label"] = None
        self.lbl_reason: Optional["tk.Label"] = None
        self.lbl_tags: Optional["tk.Label"] = None
        self.lbl_header: Optional["tk.Label"] = None
        self._last_compact: Dict[str, str] = {"action": "—", "reason": "waiting for analyze...", "tags": ""}
        self._full_advice: str = ""
        self._lock = threading.Lock()
        self._mainloop_thread: Optional[threading.Thread] = None

    def _ensure_root(self):
        if not _HAS_TK:
            return False
        if self.root is not None:
            return True
        try:
            self.root = tk.Tk()
            self.root.title("PF A1")
            # Always on top, even over fullscreen ClubGG
            self.root.attributes("-topmost", True)
            try:
                self.root.attributes("-toolwindow", True)  # hides from taskbar on Win
            except Exception:
                pass
            self.root.overrideredirect(True)  # borderless for compact poker-co-pilot look
            self.root.geometry("340x82+1200+60")  # default top-rightish; user drags
            self.root.configure(bg="#0f1117")
            self.root.resizable(False, False)

            # Styling (console/poker dark theme, high contrast)
            try:
                hdr_font = tkfont.Font(family="Consolas", size=9, weight="bold")
                act_font = tkfont.Font(family="Consolas", size=13, weight="bold")
                small_font = tkfont.Font(family="Consolas", size=9)
            except Exception:
                hdr_font = ("Consolas", 9, "bold")
                act_font = ("Consolas", 13, "bold")
                small_font = ("Consolas", 9)

            # Header bar (draggable)
            header = tk.Frame(self.root, bg="#1f2533", height=18)
            header.pack(fill="x", side="top")
            header.pack_propagate(False)
            # Client-aware header (ClubGG / CoinPoker / generic) - parsed from rich text or default
            self.lbl_header = tk.Label(header, text="🧠 PokerFlex A1 (ClubGG + CoinPoker) — last advice  (drag • ctrl+alt+o toggle)", fg="#7aa2f7", bg="#1f2533", font=hdr_font, anchor="w", padx=6)
            self.lbl_header.pack(fill="x", side="left", expand=True)

            # Bind drag to header and labels
            for w in (header, self.lbl_header):
                w.bind("<ButtonPress-1>", self._start_drag)
                w.bind("<B1-Motion>", self._do_drag)
                w.bind("<Double-Button-1>", lambda e: self.hide())

            # Content area
            content = tk.Frame(self.root, bg="#0f1117")
            content.pack(fill="both", expand=True, padx=4, pady=(2, 4))

            self.lbl_action = tk.Label(content, text="✅ RAISE — waiting...", fg="#e0e7ff", bg="#0f1117", font=act_font, anchor="w", justify="left", wraplength=330)
            self.lbl_action.pack(fill="x", padx=4, pady=(0, 1))

            self.lbl_reason = tk.Label(content, text="key reason / board texture / notes", fg="#a3bffa", bg="#0f1117", font=small_font, anchor="w", justify="left", wraplength=330)
            self.lbl_reason.pack(fill="x", padx=4, pady=(0, 1))

            self.lbl_tags = tk.Label(content, text="ICM / EXPLOIT", fg="#f6ad55", bg="#0f1117", font=small_font, anchor="w")
            self.lbl_tags.pack(fill="x", padx=4, pady=(0, 2))

            # Tiny footer hint (non-clickable)
            foot = tk.Label(self.root, text="full rich A1 (history+postflop ICM) → tray > Show Last / log / console", fg="#4a5568", bg="#0f1117", font=("Consolas", 7), anchor="e")
            foot.pack(fill="x", side="bottom", padx=4, pady=(0, 1))

            # Double-click content hides (quick dismiss)
            for w in (content, self.lbl_action, self.lbl_reason, self.lbl_tags):
                w.bind("<Double-Button-1>", lambda e: self.hide())

            # Initial paint
            self._paint()

            # Allow Esc to hide (when focused)
            self.root.bind("<Escape>", lambda e: self.hide())

            self.root.protocol("WM_DELETE_WINDOW", self.hide)
            return True
        except Exception:
            self.root = None
            return False

    def _start_drag(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _do_drag(self, event):
        if not self.root:
            return
        x = self.root.winfo_x() + event.x - self._drag_data["x"]
        y = self.root.winfo_y() + event.y - self._drag_data["y"]
        self.root.geometry(f"+{x}+{y}")

    def _paint(self):
        with self._lock:
            c = self._last_compact
        if self.lbl_action:
            self.lbl_action.config(text=c.get("action", "—"))
        if self.lbl_reason:
            self.lbl_reason.config(text=c.get("reason", ""))
        if self.lbl_tags:
            tags = c.get("tags", "")
            self.lbl_tags.config(text=tags if tags else "GTO • no active notes/ICM")

    def _safe_after(self, ms: int, func):
        """Call func on tk thread if root exists."""
        if self.root:
            try:
                self.root.after(ms, func)
            except Exception:
                pass

    def show(self):
        if not _HAS_TK:
            return
        def _do_show():
            if not self._ensure_root():
                return
            try:
                self.root.deiconify()
                self.root.lift()
                self.root.attributes("-topmost", True)  # re-assert
                self.visible = True
                self._paint()
            except Exception:
                pass
        if threading.current_thread() is threading.main_thread():
            _do_show()
        else:
            self._safe_after(0, _do_show)

    def hide(self):
        def _do_hide():
            if self.root:
                try:
                    self.root.withdraw()
                except Exception:
                    pass
            self.visible = False
        if self.root and threading.current_thread() is not threading.main_thread():
            self._safe_after(0, _do_hide)
        else:
            _do_hide()

    def toggle(self):
        if self.visible:
            self.hide()
        else:
            self.show()

    def update_advice(self, compact: Dict[str, str], full_text: str = ""):
        """Thread-safe update. Call from analyze/hotkey/live threads."""
        with self._lock:
            self._last_compact = {
                "action": compact.get("action", "—")[:110],
                "reason": compact.get("reason", "")[:80],
                "tags": compact.get("tags", "")[:60],
            }
            if full_text:
                self._full_advice = full_text[:4000]
        def _do_update():
            self._paint()
            if self.visible and self.root and self.lbl_header:
                try:
                    self.root.lift()
                    self.root.attributes("-topmost", True)
                    # Dynamic client header from rich A1 text (supports CoinPoker/ClubGG)
                    client = "A1"
                    if full_text:
                        low = full_text.lower()
                        if "coinpoker" in low:
                            client = "CoinPoker"
                        elif "clubgg" in low:
                            client = "ClubGG"
                    self.lbl_header.config(text=f"🧠 PokerFlex {client} — last advice  (drag • ctrl+alt+o toggle)")
                except Exception:
                    pass
        self._safe_after(0, _do_update)

    def get_last_full(self) -> str:
        with self._lock:
            return self._full_advice or "(no advice yet — use hotkey A or tray Analyze)"

    def stop(self):
        def _do_stop():
            if self.root:
                try:
                    self.root.quit()
                    self.root.destroy()
                except Exception:
                    pass
            self.root = None
            self.visible = False
        self._safe_after(0, _do_stop)


# Module singletons (lazy)
_OVERLAY: Optional[AdviceOverlay] = None
_OVERLAY_THREAD: Optional[threading.Thread] = None


def _get_overlay() -> Optional[AdviceOverlay]:
    global _OVERLAY
    if not _HAS_TK:
        return None
    if _OVERLAY is None:
        _OVERLAY = AdviceOverlay()
    return _OVERLAY


def _start_overlay_thread():
    """Start the tk mainloop in its own daemon thread (once)."""
    global _OVERLAY_THREAD
    ov = _get_overlay()
    if ov is None or ov.root is not None or (_OVERLAY_THREAD and _OVERLAY_THREAD.is_alive()):
        return
    def _runner():
        try:
            if ov._ensure_root():
                ov.root.mainloop()
        except Exception:
            pass
    _OVERLAY_THREAD = threading.Thread(target=_runner, daemon=True, name="PokerFlexOverlay")
    _OVERLAY_THREAD.start()
    # give it a moment to init
    time.sleep(0.05)


def toggle_overlay() -> bool:
    """Toggle the floating advice box. Returns True if overlay support present."""
    ov = _get_overlay()
    if not ov:
        return False
    _start_overlay_thread()
    ov.toggle()
    return True


def show_overlay() -> bool:
    ov = _get_overlay()
    if not ov:
        return False
    _start_overlay_thread()
    ov.show()
    return True


def hide_overlay() -> bool:
    ov = _get_overlay()
    if not ov:
        return False
    ov.hide()
    return True


def update_overlay(rich_a1_text: str):
    """Extract compact + push update (safe from any thread; starts thread if needed)."""
    ov = _get_overlay()
    if not ov:
        return
    _start_overlay_thread()
    compact = _make_compact_advice(rich_a1_text)
    ov.update_advice(compact, rich_a1_text)


def _make_compact_advice(rich: str) -> Dict[str, str]:
    """Compact extractor for floating box from rich format_a1_advice output.
    Prioritizes the primary ✅/❌ line + reason + tags for ICM/exploit/history.
    """
    if not rich or not rich.strip():
        return {"action": "— no advice —", "reason": "run analyze (ctrl+alt+a)", "tags": ""}
    lines = [l.rstrip() for l in rich.splitlines() if l.strip()]
    action_line = "—"
    reason = ""
    tags = []
    for i, ln in enumerate(lines):
        if any(sym in ln for sym in ("✅", "❌", "💡")) and ("—" in ln or " - " in ln or "–" in ln):
            action_line = ln.strip()
            # next non-empty often continues reason or is indented detail
            if i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt and not nxt.startswith(("🃏", "📊", "   ", "🎯", "ICM", "History")):
                    reason = nxt[:75]
            break
    # Fallback: use first header-ish or first line
    if action_line == "—":
        for ln in lines:
            if "🎯" in ln or "Preflop" in ln or "Flop" in ln or "Turn" in ln or "River" in ln:
                action_line = ln.strip()[:85]
                break
        if action_line == "—" and lines:
            action_line = lines[0][:85]

    # Tags from rich text (history, ICM, EXPLOIT already in A1 output)
    low = rich.lower()
    if "🎯 exploit" in low or "exploit" in low:
        tags.append("🎯EXPLOIT")
    if "icm" in low or "tournament" in low:
        tags.append("ICM")
    if "history:" in low:
        tags.append("HIST")
    if "postflop icm" in low:
        tags.append("POST-ICM")
    tag_str = " ".join(tags) if tags else "GTO"

    # Trim action for box
    if len(action_line) > 95:
        action_line = action_line[:92] + "…"

    return {
        "action": action_line,
        "reason": reason or "(see full in log / tray Status / console)",
        "tags": tag_str,
    }


def is_overlay_available() -> bool:
    return _HAS_TK


# =============================================================================
# Compat API expected by run_brain scaffolding (and tray/hotkey integration)
# =============================================================================

def get_overlay() -> Optional[AdviceOverlay]:
    """Return the singleton overlay instance (creates lazily)."""
    return _get_overlay()


def show_advice(text: str):
    """Compat: show/refresh overlay with given (rich or compact) text.
    Called from analyze path when OVERLAY_MODE.
    Starts the overlay thread if needed and updates with compact extraction.
    """
    ov = _get_overlay()
    if not ov:
        return
    _start_overlay_thread()
    # Always treat as rich A1 for best compact extraction (incl history/ICM)
    compact = _make_compact_advice(text)
    ov.update_advice(compact, text)
    # In overlay mode we gently ensure visible on first real advice (non-annoying)
    if not ov.visible:
        try:
            ov.show()
        except Exception:
            pass


# Compat alias expected by existing run_brain import ("update_overlay as _show...")
update_overlay = show_advice

# Also re-export the full control set for tray menu / hotkey use
__all__ = [
    "AdviceOverlay", "get_overlay", "show_advice", "update_overlay",
    "toggle_overlay", "show_overlay", "hide_overlay", "is_overlay_available",
]


# For direct test: python -m pokerflex.overlay
if __name__ == "__main__":
    print("PokerFlex overlay test (tk). Press ctrl+alt+o in other session or run with live runner.")
    if not _HAS_TK:
        print("tkinter unavailable — overlay disabled.")
    else:
        print("Creating demo overlay...")
        ov = _get_overlay()
        _start_overlay_thread()
        sample = """🎯 Preflop  |  Ah Ks (AKs)  |  2 opp  |  100bb  [A1 Brain]
✅ OPEN / RAISE (2.5bb) — strong hand, position, fold equity
   🃏 Board texture: n/a (preflop)
   📊 Equity vs random: 65.2%
   SPR: 39.00
   🎯 EXPLOIT: notes active (fold_to_cbet~0.78, bet_mult=1.25)
   ICM factor: 0.12 (tournament mode / adjusted Nash)
   History: 0 events
   (confidence: 82%)
"""
        ov.update_advice(_make_compact_advice(sample), sample)
        ov.show()
        print("Overlay shown (topmost compact). Close window or double-click to hide. This demo thread will sleep 8s.")
        time.sleep(8)
        print("Demo end (overlay thread continues until process exit).")

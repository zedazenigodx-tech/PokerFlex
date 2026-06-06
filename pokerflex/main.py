import customtkinter as ctk
import keyboard
import threading
import json
import os
import time
from datetime import datetime
from .poker_engine import get_advice

try:
    from .capture import CLIENT_WINDOW_HINTS, DEFAULT_CLIENT
    HAS_CAPTURE_CONSTS = True
except Exception:
    CLIENT_WINDOW_HINTS = {
        "clubgg": ["clubgg", "club", "ggpoker", "club gg", "clubgg table"],
        "coinpoker": ["coinpoker", "coin poker", "coinpoker table", "coinpoker poker"],
    }
    DEFAULT_CLIENT = "clubgg"
    HAS_CAPTURE_CONSTS = False

try:
    from PIL import Image
    HAS_PIL = True
except Exception:
    HAS_PIL = False
    Image = None

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Hide the console window on Windows when launched with python.exe (so only the clean GUI app window is visible)
# COMMENTED OUT FOR DEBUGGING - so you can see console + any traceback when it crashes
# try:
#     import ctypes
#     ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
# except Exception:
#     pass

def _log(msg):
    """Debug log to file so we can see why the app might close unexpectedly."""
    try:
        import datetime
        with open("gui_debug.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat()} - {msg}\n")
    except Exception:
        pass

import traceback

# Explicit module-level default (A1 UNAMBIGUOUS) for the GUI entry.
USE_NEW_BRAIN = True

# POKERFLEX "CHECK CURRENT HAND" APP (iterated):
# - Dedicated window instead of the small A1 overlay + spacebar (50/50, fails when terminal stuck/focus/other keys).
# - Big mouse-press button "🖱️ CHECK CURRENT HAND". Click it on your terms -> table focus + fresh real SS + vision parse + A1 -> prominent FOLD/RAISE/CALL + details instantly.
# - The window recognizes key logs: while focused, key presses are logged in a box at bottom; Enter or 'c' also triggers the check (reliable because this window is focused).
# - "instantly get a call back to the script" with the answer. All on your schedule, via mouse (primary) in this app window.
# New brain A1 default.


class PokerFlex:
    def __init__(self):
        _log("PokerFlex.__init__ started")
        self.app = ctk.CTk()
        self.app.title("PokerFlex — ANALYZE NOW")
        self.app.geometry("420x420")

        # Catch Tkinter callback errors (which can happen in binds/afters) and log them instead of crashing silently
        def _handle_tk_exception(exc, val, tb):
            _log(f"Tk callback exception: {exc} {val}")
            _log(''.join(traceback.format_exception(exc, val, tb)))
        self.app.report_callback_exception = _handle_tk_exception

        # Log when the window is closed (by user or code)
        def _on_closing():
            _log("WM_DELETE_WINDOW / on_closing called - window is being destroyed")
            self.app.destroy()
        self.app.protocol("WM_DELETE_WINDOW", _on_closing)

        # Marker to confirm the app actually launched (for debugging launch issues)
        try:
            with open("gui_launched.txt", "w", encoding="utf-8") as f:
                f.write(f"GUI launched at {__import__('datetime').datetime.now().isoformat()}\n")
        except Exception:
            pass

        self.last_capture_path = None
        self.last_parsed = {}
        self._sim_step = 0

        self.build_ui()
        # bind_hotkeys()  # commented temporarily - global hotkey may interfere with mainloop or cause early exit in some setups
        # self.bind_hotkeys()

        # Sensible quick defaults for options (non-destructive)
        try:
            self.notes_key_entry.insert(0, "nit")
            if hasattr(self, 'hero_aggro_var'):
                self.hero_aggro_var.set(True)  # user is aggressive
            # tmode/icm off by default for cash GTO start; user flips for tourneys
        except Exception:
            pass

        # Bring this full dedicated app window to the front on launch (so user sees the new clean "Check Current Hand" app instead of only the small A1 overlay)
        self.app.after(600, self._bring_to_front)
        _log("__init__ completed, about to return to main() for mainloop")

        # Ensure the window is visible and stays up (robust against early close)
        try:
            self.app.deiconify()
            self.app.update_idletasks()
            self.app.lift()
            self.app.focus_force()
            self.app.after(100, lambda: self.app.lift() if self.app.winfo_exists() else None)
        except Exception as ex:
            _log(f"visibility setup error: {ex}")

    def build_ui(self):
        _log("build_ui started")
        # === TINY HEADER for 400x400 ===
        ctk.CTkLabel(self.app, text="🧠 PokerFlex ANALYZE NOW", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(4, 1))

        # === TINY CONTROLS (essentials only) ===
        ctrlbar = ctk.CTkFrame(self.app)
        ctrlbar.pack(pady=(0, 2), padx=8, fill="x")

        self.client_var = ctk.StringVar(value="clubgg")
        ctk.CTkLabel(ctrlbar, text="Table:", font=ctk.CTkFont(size=9)).pack(side="left", padx=2)
        ctk.CTkOptionMenu(ctrlbar, variable=self.client_var, values=["clubgg", "coinpoker"], width=70, height=20).pack(side="left", padx=1)

        self.explo_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(ctrlbar, text="Notes", variable=self.explo_var, width=50, height=20).pack(side="left", padx=2)

        self.hero_aggro_var = ctk.BooleanVar(value=True)  # default: user is aggressive, per feedback
        ctk.CTkCheckBox(ctrlbar, text="Hero aggro", variable=self.hero_aggro_var, width=65, height=20).pack(side="left", padx=2)

        ctk.CTkLabel(ctrlbar, text="Note:", font=ctk.CTkFont(size=8)).pack(side="left", padx=1)
        self.notes_key_entry = ctk.CTkEntry(ctrlbar, width=50, height=18)
        self.notes_key_entry.pack(side="left", padx=1)
        self.notes_key_entry.insert(0, "nit")

        ctk.CTkButton(ctrlbar, text="NIT", width=22, height=18, command=lambda: self._apply_preset("nit")).pack(side="left", padx=1)
        ctk.CTkButton(ctrlbar, text="Sta", width=20, height=18, command=lambda: self._apply_preset("station")).pack(side="left", padx=1)

        ctk.CTkButton(ctrlbar, text="⚙", width=18, height=18, command=self._show_options_dialog).pack(side="right", padx=1)

        # compat
        self.live_var = ctk.BooleanVar(value=False)
        self.inputs = {}
        self.tourn_var = ctk.BooleanVar(value=False)
        self.icm_entry = ctk.CTkEntry(self.app, width=1, height=1)  # hidden shims for logic
        self.players_rem_entry = ctk.CTkEntry(self.app, width=1, height=1)

        # === THE BUTTON (main thing, prominent even in small window) ===
        self.analyze_btn = ctk.CTkButton(
            self.app,
            text="🖱️ ANALYZE NOW",
            command=self.analyze_now,
            height=48,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#16a34a",
            hover_color="#15803d"
        )
        self.analyze_btn.pack(pady=4, padx=8, fill="x")

        ctk.CTkLabel(self.app, text="Mouse click = real SS + A1 decision (FOLD/RAISE/CALL)", font=ctk.CTkFont(size=8), text_color="#64748b").pack(pady=(0, 2))

        # === STATUS (tiny) ===
        self.status_label = ctk.CTkLabel(self.app, text="Ready. Table front → click button for SS + decision.", font=ctk.CTkFont(size=8))
        self.status_label.pack(pady=(0, 2))

        # === DECISION BANNER (big text, compact) ===
        dec_frame = ctk.CTkFrame(self.app, fg_color="#111827", border_width=1, border_color="#374151")
        dec_frame.pack(pady=2, padx=6, fill="x")
        self.decision_label = ctk.CTkLabel(dec_frame, text="— ANALYZE NOW —", font=ctk.CTkFont(size=14, weight="bold"), text_color="#e5e7eb")
        self.decision_label.pack(pady=1)
        self.decision_detail = ctk.CTkLabel(dec_frame, text="Decision + size will appear here", font=ctk.CTkFont(size=8), text_color="#6b7280")
        self.decision_detail.pack(pady=(0, 2))

        # === PREVIEW + PARSED (tiny side-by-side) ===
        preview_row = ctk.CTkFrame(self.app)
        preview_row.pack(pady=2, padx=6, fill="x")

        img_frame = ctk.CTkFrame(preview_row)
        img_frame.pack(side="left", padx=(0, 2))
        self.preview_label = ctk.CTkLabel(
            img_frame,
            text="No SS yet.\nClick button.",
            width=140, height=90,
            fg_color="#111827", corner_radius=4
        )
        self.preview_label.pack(padx=2, pady=1)
        self.preview_label.bind("<Button-1>", lambda e: self._open_last_capture())

        parsed_frame = ctk.CTkFrame(preview_row)
        parsed_frame.pack(side="left", fill="both", expand=True)
        self.parsed_info_frame = ctk.CTkFrame(parsed_frame, fg_color="transparent")
        self.parsed_info_frame.pack(fill="both", expand=True, padx=2, pady=1)
        self._update_parsed_labels({})

        # === TINY LOG + KEY LOG ===
        self.output_box = ctk.CTkTextbox(self.app, height=60, font=ctk.CTkFont(size=8, family="Consolas"))
        self.output_box.pack(pady=2, padx=6, fill="x")

        key_frame = ctk.CTkFrame(self.app)
        key_frame.pack(pady=(1, 2), padx=6, fill="x")
        self.key_log_box = ctk.CTkTextbox(key_frame, height=22, font=ctk.CTkFont(size=7, family="Consolas"))
        self.key_log_box.pack(fill="x", padx=2, pady=1)
        self.key_log_box.insert("end", "Keys here (focus win). Enter/c triggers.\n")

        # === MINIMAL ACTIONS + HELP ===
        actions = ctk.CTkFrame(self.app)
        actions.pack(pady=1, padx=6, fill="x")
        ctk.CTkButton(actions, text="Re-analyze", command=self._reanalyze_last, height=18, width=60).pack(side="left", padx=1)
        ctk.CTkButton(actions, text="Capture only", command=self._capture_only, height=18, width=60).pack(side="left", padx=1)
        ctk.CTkButton(actions, text="🗑️ Clear", command=self._clear_results, height=18, width=52).pack(side="left", padx=1)
        ctk.CTkButton(actions, text="Options", command=self._show_options_dialog, height=18, width=50).pack(side="left", padx=1)

        # Tiny help
        ctk.CTkLabel(self.app, text="Table front → ANALYZE NOW (mouse). 🗑️ Clear = wipe screenshot + results for fresh start. Images saved on disk. Calibrate for best.", font=ctk.CTkFont(size=6), text_color="#64748b").pack(pady=(1, 2), padx=4)

        # Bind keys for trigger
        self.app.bind("<Key>", self._on_app_key)
        self.app.bind("<Return>", lambda e: self.analyze_now())
        self.app.bind("<c>", lambda e: self.analyze_now())
        self.app.bind("<C>", lambda e: self.analyze_now())
        _log("build_ui completed")

    def bind_hotkeys(self):
        try:
            keyboard.add_hotkey('ctrl+alt+p', self.popup)
            _log("global hotkey ctrl+alt+p bound for popup")
        except Exception as ex:
            _log(f"could not bind global hotkey (maybe runner already has hooks, or no keyboard lib): {ex}")

    def popup(self):
        self.app.deiconify()
        self.app.lift()
        self.app.focus_force()

    def _bring_to_front(self):
        """Force this full dedicated app window to the front on launch so the user sees the clean 'Check Current Hand' GUI (with the big mouse button) instead of only the small old A1 overlay."""
        _log("_bring_to_front callback fired")
        try:
            self.app.lift()
            self.app.focus_force()
            _log("_bring_to_front done (lift/focus only, no topmost to avoid conflicts)")
        except Exception as ex:
            _log(f"_bring_to_front error: {ex}")

    # === NEW CLEAN APP CORE: ANALYZE NOW with real screenshot ===

    def _focus_poker_table(self):
        """Best-effort: bring the poker client window to front before screenshot (makes the SS reliable for the 'next call')."""
        try:
            import pygetwindow as gw
            client = self.client_var.get() if hasattr(self, 'client_var') else DEFAULT_CLIENT
            hints = CLIENT_WINDOW_HINTS.get(client, CLIENT_WINDOW_HINTS.get(DEFAULT_CLIENT, []))
            for w in gw.getAllWindows():
                t = (getattr(w, 'title', '') or '').lower()
                if any(h in t for h in hints) and getattr(w, 'visible', False):
                    try:
                        w.activate()
                        time.sleep(0.3)
                    except Exception:
                        pass
                    return True
        except Exception:
            pass  # pygetwindow optional or not installed; capture.py will fallback to full grab
        return False

    def _on_app_key(self, event):
        """Log keys recognized while this window has focus. This is the reliable 'key logs' surface (local to the app, no terminal/global hotkey flakiness)."""
        try:
            ts = time.strftime("%H:%M:%S")
            key_info = f"{ts} key={getattr(event, 'keysym', '?')} char={getattr(event, 'char', '')} state={getattr(event, 'state', 0)}"
            if hasattr(self, "key_log_box") and self.key_log_box:
                self.key_log_box.insert("end", key_info + "\n")
                self.key_log_box.see("end")
            # Optional: log to main output on special keys if wanted
            # if event.keysym in ('F1', 'F5'):
            #     self.output_box.insert("end", f"[key] {key_info}\n")
        except Exception:
            pass

    def analyze_now(self):
        """Primary action: take real screenshot of table, parse vision, run A1, show preview + advice. Triggered by mouse click on the big button (or Enter/'c' when this window focused)."""
        _log("analyze_now (button press or key) called")
        if self.analyze_btn.cget("state") == "disabled":
            return
        self._focus_poker_table()
        self.analyze_btn.configure(state="disabled", text="CAPTURING + ANALYZING…")
        self.status_label.configure(text="📸 Focused table (if found) • Grabbing fresh screen (real) … vision + A1 running")
        # Reset prominent decision while working
        if hasattr(self, "decision_label"):
            self.decision_label.configure(text="ANALYZING CURRENT HAND...", text_color="#eab308")
        if hasattr(self, "decision_detail"):
            self.decision_detail.configure(text="Taking screenshot of the table right now + running full A1 analysis. Result in a few seconds.")
        self.output_box.delete("1.0", "end")
        self.output_box.insert("end", "⏳ CHECK CURRENT HAND: fresh screenshot → vision parse → A1 brain (GTO + notes + ICM)\n\n")

        client = self.client_var.get()

        def work():
            cap_path = None
            parsed = {}
            text = ""
            data_out = {}
            err = None
            try:
                from .capture import capture_and_parse

                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                out_name = f"pokerflex_analyze_{ts}.png"
                # Force REAL capture (simulate=False), manual trigger = permissive confs for best chance of usable data
                cap_path, parsed = capture_and_parse(
                    output_path=out_name,
                    simulate=False,
                    silent=True,
                    client=client,
                    min_conf=0.05,
                    partial_min_conf=0.05,
                    retries=3,
                )
                self.last_capture_path = cap_path
                self.last_parsed = parsed or {}

                # Collect A1 options from the clean topbar controls
                tmode = bool(self.tourn_var.get())
                prem = self.players_rem_entry.get().strip()
                players_remaining = int("".join(c for c in prem if c.isdigit()) or 0) or None
                icm_str = self.icm_entry.get().strip()
                try:
                    icm_factor = float(icm_str) if icm_str else 0.0
                except Exception:
                    icm_factor = 0.0

                player_notes = None
                if self.explo_var.get():
                    key = self.notes_key_entry.get().strip() or "villain"
                    try:
                        from .models import get_player_notes
                        player_notes = get_player_notes(key)
                    except Exception:
                        player_notes = {"notes": f"explo key={key}"}

                # Incorporate user's own aggressive style (from "how aggressive i play")
                if getattr(self, 'hero_aggro_var', None) and self.hero_aggro_var.get():
                    # PT4 NL100+ (pokertracker4 folder) derived: 3bet AQo vs opens took pot; iso 86s + AJo vs limp in dead money (bomb pot NL100 session).
                    # Only clear winning aggro lines included (the river spew JTs hand ignored).
                    hero_n = {
                        "aggression_factor": 1.5,
                        "preflop_open_tight": 0.8,
                        "hero_anno": "PT4 NL100: aggro ONLY winning pos (HJ/CO/BTN) — 3bet AQo, CO 86s steal, AJo iso. SB/early: tighter GTO (your leaks)."
                    }
                    if player_notes:
                        player_notes = dict(player_notes)
                        player_notes["hero"] = hero_n
                    else:
                        player_notes = {"hero": hero_n}
                    try:
                        from .models import set_player_notes
                        set_player_notes("hero", hero_n)
                    except Exception:
                        pass

                # Pull from vision parse (real SS)
                pos = str(parsed.get("position", "") or "").strip()
                hand = str(parsed.get("hand", "") or "").strip()
                board = str(parsed.get("board", "") or "").strip()
                opps = str(parsed.get("opponents", "") or "2").strip()
                stack = str(parsed.get("stack", "") or "100").strip()
                ante = str(parsed.get("ante", "") or "0").strip()

                text, data_out = get_advice(
                    position=pos,
                    hand=hand,
                    board=board,
                    opponents=opps,
                    stack=stack,
                    ante=ante,
                    player_notes=player_notes,
                    tournament_mode=tmode,
                    players_remaining=players_remaining,
                    icm_factor=icm_factor,
                )
            except Exception as ex:
                err = str(ex)

            # Back to UI thread
            try:
                self.app.after(0, lambda: self._show_analyze_result(text, data_out, parsed, cap_path, err))
            except Exception:
                # mainloop not ready or destroyed (tests / shutdown); fallback to sync if possible
                pass

        threading.Thread(target=work, daemon=True).start()

    def _show_analyze_result(self, text, data_out, parsed, img_path, err=None):
        self.analyze_btn.configure(state="normal", text="🖱️ CHECK CURRENT HAND")
        if err:
            self.status_label.configure(text=f"⚠️ Analyze failed — see output")
            if hasattr(self, "decision_label"):
                self.decision_label.configure(text="ERROR - CHECK LOG BELOW", text_color="#ef4444")
            if hasattr(self, "decision_detail"):
                self.decision_detail.configure(text=str(err)[:80])
            self.output_box.insert("end", f"\n⚠️ ERROR during capture/vision/A1:\n{err}\n\n")
            self.output_box.insert("end", "Tips: Ensure poker table window is visible (bring to front). Run calibrate for your table. Check tesseract in PATH. Try Capture only button.\n")
            return

        ts = time.strftime("%H:%M:%S")
        vconf = parsed.get("vision_conf") or parsed.get("conf") or 0.0
        client = parsed.get("client", self.client_var.get())
        self.status_label.configure(text=f"✅ Analyzed {ts}  |  client={client}  |  vision_conf~{float(vconf):.2f}  |  Press again for next street")

        # Update image preview
        self._load_preview(img_path)

        # Update compact vision parse summary
        self._update_parsed_labels(parsed or {})

        # Show A1 text (rich)
        self.output_box.delete("1.0", "end")
        if text:
            self.output_box.insert("end", text)
        else:
            self.output_box.insert("end", "(no text from A1 — check last_advice.txt or re-run)\n")

        # === Prominent DECISION banner (the clear fold/raise/call answer you asked for) ===
        try:
            t = (text or "").upper()
            action = "ANALYZED"
            color = "#e5e7eb"
            detail = ""
            if "FOLD" in t:
                action = "FOLD"
                color = "#ef4444"
            elif "CALL" in t:
                action = "CALL"
                color = "#3b82f6"
            elif any(x in t for x in ["RAISE", "SHOVE", "JAM", "BET"]):
                action = "RAISE / BET"
                color = "#22c55e"
            # Try to pull a size/reason snippet for the sub label
            for line in (text or "").splitlines():
                lu = line.upper()
                if any(k in lu for k in ["RAISE", "CALL", "FOLD", "SHOVE", "JAM", "BET", "✅", "❌"]):
                    detail = line.strip()[:90]
                    break
            if hasattr(self, "decision_label"):
                self.decision_label.configure(text=action, text_color=color)
            if hasattr(self, "decision_detail"):
                self.decision_detail.configure(text=detail or "See full log below for reasons, size, texture, confidence etc.")
        except Exception:
            pass

        # Append compact A1 metrics (same style as before)
        if data_out and isinstance(data_out, dict):
            extras = []
            if data_out.get("texture") or data_out.get("texture_summary"):
                extras.append(f"texture={data_out.get('texture') or data_out.get('texture_summary')}")
            m = data_out.get("metrics") or {}
            spr = data_out.get("spr") or m.get("spr")
            if spr:
                try:
                    extras.append(f"SPR={float(spr):.2f}")
                except Exception:
                    pass
            if "confidence" in data_out:
                try:
                    extras.append(f"conf={float(data_out['confidence'])*100:.0f}%")
                except Exception:
                    pass
            if data_out.get("exploitative_notes") or data_out.get("explo_notes_used"):
                extras.append("🎯EXPLO")
            if "icm_factor" in data_out and float(data_out.get("icm_factor", 0)) > 0:
                try:
                    extras.append(f"ICM~{float(data_out['icm_factor']):.2f}")
                except Exception:
                    pass
            if extras:
                self.output_box.insert("end", "\n— A1 metrics: " + " | ".join(extras))

        # Share with rest of system (overlay / last_advice consumers / runner if watching)
        try:
            with open("last_advice.txt", "w", encoding="utf-8") as f:
                f.write(text or "")
            # Also drop a state snapshot so runner can pick if wanted
            state = {
                "position": parsed.get("position", ""),
                "hand": parsed.get("hand", ""),
                "board": parsed.get("board", ""),
                "opponents": parsed.get("opponents", ""),
                "stack": parsed.get("stack", ""),
                "ante": parsed.get("ante", ""),
                "_from_analyze_now": True,
                "_ts": time.time(),
            }
            with open("pokerflex_last_analyze_state.json", "w", encoding="utf-8") as sf:
                json.dump(state, sf, indent=2)
        except Exception:
            pass

    def _show_error(self, msg):
        self.analyze_btn.configure(state="normal", text="🖱️ CHECK CURRENT HAND")
        self.status_label.configure(text="⚠️ Error — see details")
        self.output_box.insert("end", f"\n⚠️ {msg}\n")

    def _load_preview(self, img_path):
        if not img_path or not os.path.exists(img_path) or not HAS_PIL or Image is None:
            self.preview_label.configure(text="(no preview image or PIL missing)", image=None)
            self.preview_label.image = None
            return
        try:
            pil_img = Image.open(img_path)
            # Thumbnail for UI preview
            max_w, max_h = 400, 210
            pil_img.thumbnail((max_w, max_h), Image.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=pil_img.size)
            self.preview_label.configure(image=ctk_img, text="")
            self.preview_label.image = ctk_img  # retain reference
        except Exception as ex:
            self.preview_label.configure(text=f"(preview load failed: {ex})", image=None)
            self.preview_label.image = None

    def _update_parsed_labels(self, parsed):
        # Rebuild compact info each time (simple, no stale widgets)
        for child in list(self.parsed_info_frame.winfo_children()):
            child.destroy()

        if not parsed:
            ctk.CTkLabel(self.parsed_info_frame, text="(no parse yet — CHECK CURRENT HAND will populate from real screenshot)", font=ctk.CTkFont(size=10), text_color="#64748b").pack(anchor="w", padx=4)
            return

        items = [
            ("Position", parsed.get("position")),
            ("Hand", parsed.get("hand")),
            ("Board", parsed.get("board")),
            ("Opponents", parsed.get("opponents")),
            ("Stack (bb)", parsed.get("stack")),
            ("Pot", parsed.get("pot")),
            ("To call", parsed.get("bet_to_call")),
            ("Street", parsed.get("street")),
            ("Vision conf", f"{float(parsed.get('vision_conf', parsed.get('conf', 0))):.2f}" if parsed.get('vision_conf') or parsed.get('conf') else None),
        ]
        for label, val in items:
            if val not in (None, "", "None"):
                row = ctk.CTkFrame(self.parsed_info_frame, fg_color="transparent")
                row.pack(fill="x", pady=1)
                ctk.CTkLabel(row, text=f"{label}:", width=90, anchor="w", font=ctk.CTkFont(size=10, weight="bold")).pack(side="left")
                ctk.CTkLabel(row, text=str(val)[:28], font=ctk.CTkFont(size=10)).pack(side="left", padx=4)

        # note on partials
        if parsed.get("partial") or parsed.get("below_threshold"):
            ctk.CTkLabel(self.parsed_info_frame, text="⚠️ partial/low-conf read — manual verify cards if needed", font=ctk.CTkFont(size=9), text_color="#f59e0b").pack(anchor="w", padx=4, pady=2)

    def _open_last_capture(self):
        p = self.last_capture_path
        if p and os.path.exists(p):
            try:
                if os.name == "nt":
                    os.startfile(p)
                else:
                    import subprocess
                    subprocess.call(["open", p])
            except Exception as ex:
                self.output_box.insert("end", f"\n[Could not open image: {ex}]\n")
        else:
            self.output_box.insert("end", "\n[No capture file to open yet]\n")

    def _reanalyze_last(self):
        """Re-run A1 on the last captured image (no new SS) — useful if options changed."""
        if not self.last_capture_path or not os.path.exists(self.last_capture_path):
            self.output_box.insert("end", "\n[No previous capture to re-analyze]\n")
            return
        self.analyze_btn.configure(state="disabled", text="RE-ANALYZING…")
        if hasattr(self, "decision_label"):
            self.decision_label.configure(text="RE-ANALYZING LAST HAND...", text_color="#eab308")
        if hasattr(self, "decision_detail"):
            self.decision_detail.configure(text="Re-running A1 on previous screenshot with current options...")
        self.status_label.configure(text="Re-running A1 on last screenshot (no new grab)")

        parsed = self.last_parsed or {}
        client = self.client_var.get()

        def work():
            text = ""
            data_out = {}
            err = None
            try:
                # Re-parse the image (in case) but mainly re-run advice with current options
                from .capture import attempt_vision_parse
                # Parse again with current client to refresh parsed if wanted
                reparsed = attempt_vision_parse(self.last_capture_path, silent=True, client=client, min_conf=0.0, partial_min_conf=0.0) or parsed
                self.last_parsed = reparsed

                tmode = bool(self.tourn_var.get())
                prem = self.players_rem_entry.get().strip()
                players_remaining = int("".join(c for c in prem if c.isdigit()) or 0) or None
                icm_str = self.icm_entry.get().strip()
                try:
                    icm_factor = float(icm_str) if icm_str else 0.0
                except Exception:
                    icm_factor = 0.0

                player_notes = None
                if self.explo_var.get():
                    key = self.notes_key_entry.get().strip() or "villain"
                    try:
                        from .models import get_player_notes
                        player_notes = get_player_notes(key)
                    except Exception:
                        player_notes = {"notes": f"explo key={key}"}

                pos = str(reparsed.get("position", "") or "").strip()
                hand = str(reparsed.get("hand", "") or "").strip()
                board = str(reparsed.get("board", "") or "").strip()
                opps = str(reparsed.get("opponents", "") or "2").strip()
                stack = str(reparsed.get("stack", "") or "100").strip()
                ante = str(reparsed.get("ante", "") or "0").strip()

                text, data_out = get_advice(
                    position=pos, hand=hand, board=board, opponents=opps,
                    stack=stack, ante=ante, player_notes=player_notes,
                    tournament_mode=tmode, players_remaining=players_remaining, icm_factor=icm_factor,
                )
            except Exception as ex:
                err = str(ex)

            try:
                self.app.after(0, lambda: self._show_analyze_result(text, data_out, self.last_parsed, self.last_capture_path, err))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _capture_only(self):
        """Just grab a screenshot + parse, populate preview/parsed, no full A1 run (for setup/calib check)."""
        self._focus_poker_table()
        self.status_label.configure(text="📸 Capture only (vision parse, no A1 decision)…")
        self.output_box.delete("1.0", "end")
        self.output_box.insert("end", "📸 Capture-only mode (real screenshot + vision). Good for testing table visibility / calibrate.\n")

        client = self.client_var.get()

        def work():
            err = None
            path = None
            parsed = {}
            try:
                from .capture import capture_and_parse
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                out_name = f"pokerflex_analyze_{ts}.png"
                path, parsed = capture_and_parse(
                    output_path=out_name, simulate=False, silent=True, client=client,
                    min_conf=0.05, partial_min_conf=0.05, retries=2
                )
                self.last_capture_path = path
                self.last_parsed = parsed or {}
            except Exception as ex:
                err = str(ex)

            try:
                self.app.after(0, lambda: self._after_capture_only(path, parsed, err))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _after_capture_only(self, path, parsed, err):
        self.status_label.configure(text="Capture done — use CHECK CURRENT HAND (mouse) for full decision or Re-analyze")
        if err:
            self.output_box.insert("end", f"⚠️ Capture failed: {err}\n")
            return
        self._load_preview(path)
        self._update_parsed_labels(parsed or {})
        self.output_box.insert("end", f"✅ Captured to {path}\nParsed keys: {list((parsed or {}).keys())[:10]}...\n(Now click CHECK CURRENT HAND (mouse) or Re-analyze to get A1 advice with current options.)\n")

    def _clear_results(self):
        """Clear the current screenshot preview + ALL results (decision banner, parsed info, output log).

        "Clear screenshot" + "clear everything" in one small button.
        - Resets preview image to placeholder.
        - Neutralizes the big FOLD/RAISE decision banner.
        - Clears the dynamic parsed labels.
        - Wipes the log/output textbox (fresh start).
        - Resets in-memory last_capture / last_parsed so Re-analyze is disabled until next grab.
        - Does NOT delete any saved pokerflex_analyze_*.png files or last_advice.json (history preserved on disk).
        """
        # Re-enable main button
        if hasattr(self, "analyze_btn"):
            self.analyze_btn.configure(state="normal", text="🖱️ ANALYZE NOW")

        # Neutral decision banner
        if hasattr(self, "decision_label"):
            self.decision_label.configure(text="— ANALYZE NOW —", text_color="#e5e7eb")
        if hasattr(self, "decision_detail"):
            self.decision_detail.configure(text="Decision + size will appear here")

        # Clear the screenshot preview explicitly
        if hasattr(self, "preview_label"):
            self.preview_label.configure(text="No SS yet.\nClick button (or Clear to reset).", image=None)
            self.preview_label.image = None

        # Parsed info back to initial empty state
        if hasattr(self, "parsed_info_frame"):
            self._update_parsed_labels({})

        # Full clear of the log / output area
        if hasattr(self, "output_box"):
            self.output_box.delete("1.0", "end")
            self.output_box.insert("end", "🗑️ Cleared (screenshot + results).\nReady for a fresh table screenshot.\n")

        # Status
        if hasattr(self, "status_label"):
            self.status_label.configure(text="Cleared. Bring table front → ANALYZE NOW for new real SS + A1.")

        # Reset in-memory state (so no stale re-analyze of old hand)
        self.last_capture_path = None
        self.last_parsed = {}

        _log("UI + results cleared (clear screenshot / clear everything)")

    def _show_manual_inputs(self):
        """Fallback: show the classic manual-entry inputs + analyze (no auto SS). Opens toplevel to keep main UI clean."""
        try:
            win = ctk.CTkToplevel(self.app)
            win.title("PokerFlex — Manual Entry (no auto screenshot)")
            win.geometry("520x420")

            ctk.CTkLabel(win, text="Manual fields (fallback if vision struggles or for testing). Capture button here still uses sim by default.", font=ctk.CTkFont(size=11)).pack(pady=6)

            frame = ctk.CTkFrame(win)
            frame.pack(pady=4, padx=12, fill="x")

            self._manual_inputs = {}
            fields = [
                ("Position", "BTN"),
                ("Hand", "AhKs"),
                ("Board", "Qd7h2c"),
                ("Opponents", "2"),
                ("Stack (bb)", "100"),
                ("Ante (bb)", "0"),
            ]
            for field, default in fields:
                ctk.CTkLabel(frame, text=f"{field}:").pack(anchor="w", padx=8, pady=(4,0))
                e = ctk.CTkEntry(frame, height=28)
                e.pack(fill="x", padx=8, pady=2)
                e.insert(0, default)
                self._manual_inputs[field] = e

            # reuse existing option vars by reference (tourn etc live on self)
            optf = ctk.CTkFrame(win)
            optf.pack(fill="x", padx=12, pady=4)
            ctk.CTkCheckBox(optf, text="Tourney / ICM", variable=self.tourn_var).pack(side="left", padx=4)
            ctk.CTkCheckBox(optf, text="Use explo notes", variable=self.explo_var).pack(side="left", padx=4)

            btns = ctk.CTkFrame(win)
            btns.pack(pady=8)
            ctk.CTkButton(btns, text="Analyze from these fields (no SS)", command=lambda: self._manual_analyze_from_win(win)).pack(side="left", padx=6)
            ctk.CTkButton(btns, text="Close", command=win.destroy).pack(side="left", padx=6)

            ctk.CTkLabel(win, text="Tip: For real screenshot use the main CHECK CURRENT HAND button (mouse click). This path bypasses vision.", font=ctk.CTkFont(size=9), text_color="#64748b").pack(pady=4)
        except Exception as ex:
            self.output_box.insert("end", f"\n[manual inputs dialog error: {ex}]\n")

    def _manual_analyze_from_win(self, win):
        # collect and call the original analyze path (which expects self.inputs)
        try:
            # temporarily provide self.inputs for the existing analyze() method
            self.inputs = {k: v for k, v in self._manual_inputs.items()}
            self.output_box.delete("1.0", "end")
            self.output_box.insert("end", "[manual entry path — no screenshot]\n")
            self.analyze()  # reuses existing logic + threading + _show
            win.destroy()
        except Exception as ex:
            self.output_box.insert("end", f"manual analyze err: {ex}\n")

    def _show_notes_editor(self):
        """Quick access to notes (reuses existing advanced table in a toplevel to keep main clean)."""
        try:
            # Reuse the refresh logic; build a compact version of the notes table in toplevel
            win = ctk.CTkToplevel(self.app)
            win.title("PokerFlex — Explo Notes (live)")
            win.geometry("860x420")
            ctk.CTkLabel(win, text="Multi-villain notes (edits save live to json; used on next CHECK CURRENT HAND if 'Use notes' checked)", font=ctk.CTkFont(size=11)).pack(pady=4)

            self._notes_win_frame = ctk.CTkScrollableFrame(win, height=280, width=820)
            self._notes_win_frame.pack(fill="both", expand=True, padx=8, pady=4)

            # copy of refresh but targeting this frame
            self._refresh_notes_table(target_frame=self._notes_win_frame)

            btns = ctk.CTkFrame(win)
            btns.pack(fill="x", padx=8, pady=4)
            ctk.CTkButton(btns, text="🔄 Refresh", command=lambda: self._refresh_notes_table(target_frame=self._notes_win_frame)).pack(side="left", padx=3)
            ctk.CTkButton(btns, text="➕ Add key", command=self._add_villain_key).pack(side="left", padx=3)
            ctk.CTkButton(btns, text="💾 Save", command=self._save_notes_live).pack(side="left", padx=3)
            ctk.CTkButton(btns, text="🧹 Clear all", command=self._clear_all_notes_table).pack(side="left", padx=3)
            ctk.CTkButton(btns, text="Close", command=win.destroy).pack(side="right", padx=3)
        except Exception as ex:
            self.output_box.insert("end", f"\n[notes editor err: {ex}]\n")

    def _show_options_dialog(self):
        """Simple dialog for full options (ICM details, open advanced notes). Keeps main UI clean for the button press flow."""
        try:
            win = ctk.CTkToplevel(self.app)
            win.title("PokerFlex - More Options")
            win.geometry("480x260")
            ctk.CTkLabel(win, text="Additional options for the next CHECK CURRENT HAND", font=ctk.CTkFont(size=12, weight="bold")).pack(pady=8)

            row = ctk.CTkFrame(win)
            row.pack(fill="x", padx=12, pady=4)
            ctk.CTkLabel(row, text="Players remaining:").pack(side="left", padx=4)
            e_pr = ctk.CTkEntry(row, width=60)
            e_pr.pack(side="left", padx=2)
            e_pr.insert(0, self.players_rem_entry.get() or "6")
            ctk.CTkLabel(row, text="ICM factor:").pack(side="left", padx=8)
            e_icm = ctk.CTkEntry(row, width=60)
            e_icm.pack(side="left", padx=2)
            e_icm.insert(0, self.icm_entry.get() or "0.0")

            def apply():
                self.players_rem_entry.delete(0, "end")
                self.players_rem_entry.insert(0, e_pr.get())
                self.icm_entry.delete(0, "end")
                self.icm_entry.insert(0, e_icm.get())
                self.tourn_var.set(True)  # assume if setting players
                win.destroy()
                self.output_box.insert("end", "✅ Options updated for next check. Click the big button.\n")

            ctk.CTkButton(win, text="Apply to next check", command=apply).pack(pady=6)

            ctk.CTkButton(win, text="Open full explo notes table", command=lambda: (win.destroy(), self._show_notes_editor())).pack(pady=4)
            ctk.CTkButton(win, text="Close", command=win.destroy).pack(pady=2)

            ctk.CTkLabel(win, text="These affect the A1 brain when you next press CHECK CURRENT HAND (mouse).", font=ctk.CTkFont(size=9), text_color="#64748b").pack(pady=4)
        except Exception as ex:
            self.output_box.insert("end", f"options dialog err: {ex}\n")

    # small adapter so _refresh_notes_table can target a passed frame (for toplevel) or the (nonexistent) main one
    def _refresh_notes_table(self, target_frame=None):
        frame = target_frame or getattr(self, "notes_table_frame", None)
        if frame is None:
            return
        for child in list(frame.winfo_children()):
            child.destroy()
        try:
            from .models import get_notes_manager, describe_explo_effect
            mgr = get_notes_manager()
            players = mgr.list_players() or []
            if not players:
                ctk.CTkLabel(frame, text="(no notes — add via quick buttons above or here)", font=ctk.CTkFont(size=10)).pack(anchor="w", padx=4)
                return
            hdr = ctk.CTkFrame(frame)
            hdr.pack(fill="x", pady=(0,1))
            cols = [("Key", 68), ("f2c", 42), ("dry", 42), ("wet", 42), ("AF", 42), ("cbet%", 46), ("notes", 180), ("", 160)]
            for txt, w in cols:
                ctk.CTkLabel(hdr, text=txt, width=w, font=ctk.CTkFont(size=9, weight="bold")).pack(side="left", padx=1)
            for p in players[:10]:
                n = mgr.get_notes(p)
                row = ctk.CTkFrame(frame)
                row.pack(fill="x", pady=0)
                ctk.CTkLabel(row, text=str(p)[:11], width=68, font=ctk.CTkFont(size=9)).pack(side="left", padx=1)
                for fld, ww in [("fold_to_cbet",42), ("fold_to_cbet_dry",42), ("fold_to_cbet_wet",42), ("aggression_factor",42), ("cbet_freq",46)]:
                    val = n.get(fld, 0)
                    try:
                        vs = f"{float(val):.2f}"
                    except Exception:
                        vs = str(val)[:5]
                    ctk.CTkLabel(row, text=vs, width=ww, font=ctk.CTkFont(size=9)).pack(side="left", padx=1)
                nt = str(n.get("notes", ""))[:28].replace("\n", " ")
                ctk.CTkLabel(row, text=nt, width=180, font=ctk.CTkFont(size=8)).pack(side="left", padx=1)
                ctk.CTkButton(row, text="Edit", width=36, height=18, font=ctk.CTkFont(size=9), command=lambda pp=p, f=frame: self._edit_villain_notes(pp, target_frame=f)).pack(side="left", padx=1)
                ctk.CTkButton(row, text="NIT", width=30, height=18, font=ctk.CTkFont(size=8), command=lambda pp=p: self._apply_preset_to("nit", pp)).pack(side="left", padx=1)
                ctk.CTkButton(row, text="Sta", width=28, height=18, font=ctk.CTkFont(size=8), command=lambda pp=p: self._apply_preset_to("station", pp)).pack(side="left", padx=1)
                ctk.CTkButton(row, text="✕", width=20, height=18, font=ctk.CTkFont(size=9), fg_color="red", command=lambda pp=p, f=frame: (self._delete_villain(pp), self._refresh_notes_table(target_frame=f))).pack(side="left", padx=1)
                try:
                    eff = describe_explo_effect(p)
                    ctk.CTkLabel(row, text=eff.split(":",1)[-1][:30] if ":" in eff else eff[:30], font=ctk.CTkFont(size=7), text_color="gray").pack(side="left", padx=2)
                except Exception:
                    pass
        except Exception as ex:
            ctk.CTkLabel(frame, text=f"(notes refresh err: {ex})", font=ctk.CTkFont(size=9)).pack()

    def _edit_villain_notes(self, player_key, target_frame=None):
        try:
            from .models import get_notes_manager
            mgr = get_notes_manager()
            n = mgr.get_notes(player_key)
            win = ctk.CTkToplevel(self.app)
            win.title(f"Edit notes: {player_key}")
            win.geometry("520x300")
            ctk.CTkLabel(win, text=f"Editing: {player_key} (live to json; affects next CHECK CURRENT HAND)").pack(pady=4)
            fields = {}
            rowf = ctk.CTkFrame(win)
            rowf.pack(fill="x", padx=8)
            for i, (lab, key) in enumerate([("fold_to_cbet", "fold_to_cbet"), ("dry", "fold_to_cbet_dry"), ("wet", "fold_to_cbet_wet"), ("AF", "aggression_factor"), ("cbet%", "cbet_freq")]):
                ctk.CTkLabel(rowf, text=lab).grid(row=0, column=i, padx=2)
                e = ctk.CTkEntry(rowf, width=58)
                e.grid(row=1, column=i, padx=2)
                e.insert(0, str(n.get(key, "")))
                fields[key] = e
            ctk.CTkLabel(win, text="Free notes:").pack(anchor="w", padx=8, pady=(6,0))
            free_e = ctk.CTkEntry(win, width=480)
            free_e.pack(padx=8)
            free_e.insert(0, str(n.get("notes", "")))
            def do_save():
                try:
                    tend = {}
                    for k, e in fields.items():
                        val = e.get().strip()
                        if val:
                            try: tend[k] = float(val)
                            except: tend[k] = val
                    if free_e.get().strip():
                        tend["notes"] = free_e.get().strip()
                    mgr.set_notes(player_key, tend)
                    self.output_box.insert("end", f"✅ Saved notes for '{player_key}'.\n")
                    self._refresh_notes_table(target_frame=target_frame)
                    win.destroy()
                except Exception as ex:
                    self.output_box.insert("end", f"save err: {ex}\n")
            ctk.CTkButton(win, text="Save live", command=do_save).pack(pady=8)
            ctk.CTkButton(win, text="Cancel", command=win.destroy).pack()
        except Exception as ex:
            self.output_box.insert("end", f"edit notes err: {ex}\n")

    # --- A1 helper methods (simple, no new deps) ---

    def _apply_preset(self, preset: str):
        """Apply a simple explo preset via models (writes to clubgg_player_notes.json). Sets key + refreshes full table view."""
        key = self.notes_key_entry.get().strip() or preset
        self.notes_key_entry.delete(0, "end")
        self.notes_key_entry.insert(0, key)
        try:
            from .models import apply_nit_preset, apply_calling_station_preset, apply_aggro_preset
            if preset == "nit":
                notes = apply_nit_preset(key)
            elif preset == "station":
                notes = apply_calling_station_preset(key)
            else:
                notes = apply_aggro_preset(key)
            self.explo_var.set(True)
            self.output_box.insert("end", f"\n✅ Preset '{preset}' applied for key '{key}'.\n  fold_to_cbet={notes.get('fold_to_cbet')}  notes: {notes.get('notes','')[:60]}...\n  (explo checkbox auto-enabled; will pass to A1 on next CHECK CURRENT HAND)\n")
            self._refresh_notes_table()
        except Exception as ex:
            self.output_box.insert("end", f"⚠️ Preset error (notes may still work if set): {ex}\n")

    def _apply_preset_to(self, preset: str, player_key: str):
        """For notes editor rows."""
        try:
            from .models import apply_nit_preset, apply_calling_station_preset, apply_aggro_preset
            if preset == "nit":
                notes = apply_nit_preset(player_key)
            elif preset == "station":
                notes = apply_calling_station_preset(player_key)
            else:
                notes = apply_aggro_preset(player_key)
            self.explo_var.set(True)
            self.notes_key_entry.delete(0, "end")
            self.notes_key_entry.insert(0, player_key)
            self.output_box.insert("end", f"\n✅ Table preset '{preset}' for '{player_key}'\n")
            self._refresh_notes_table()
        except Exception as ex:
            self.output_box.insert("end", f"table preset err: {ex}\n")

    # (old heavy notes table code removed for clean primary UI; adapters + toplevel editor in _show_notes_editor provide the functionality when needed)

    def _copy_output(self):
        try:
            txt = self.output_box.get("1.0", "end").strip()
            if not txt:
                return
            self.app.clipboard_clear()
            self.app.clipboard_append(txt)
            # brief non-modal feedback
            orig_title = self.app.title()
            self.app.title(orig_title + "  [copied]")
            self.app.after(1200, lambda: self.app.title(orig_title))
        except Exception as ex:
            # fallback: put msg in output
            self.output_box.insert("end", f"\n[Copy failed: {ex}]")

    def _send_to_runner(self):
        """Write current inputs + A1 options to clubgg_current_state.json so background runner watcher picks it up (~2s)."""
        try:
            if self.inputs:
                data = {k: v.get().strip() for k, v in self.inputs.items()}
            else:
                # clean app path: use last vision parse
                p = self.last_parsed or {}
                data = {
                    "Position": p.get("position", ""),
                    "Hand": p.get("hand", ""),
                    "Board": p.get("board", ""),
                    "Opponents": p.get("opponents", ""),
                    "Stack (bb)": p.get("stack", ""),
                    "Ante (bb)": p.get("ante", ""),
                }
            state = {
                "position": data.get("Position", "") or (self.last_parsed or {}).get("position", ""),
                "hand": data.get("Hand", "") or (self.last_parsed or {}).get("hand", ""),
                "board": data.get("Board", "") or (self.last_parsed or {}).get("board", ""),
                "opponents": data.get("Opponents", "") or (self.last_parsed or {}).get("opponents", ""),
                "stack": data.get("Stack (bb)", "") or (self.last_parsed or {}).get("stack", ""),
                "ante": data.get("Ante (bb)", "") or (self.last_parsed or {}).get("ante", ""),
                "tournament_mode": "true" if self.tourn_var.get() else "false",
                "icm_factor": (self.icm_entry.get().strip() or "0.0"),
                "players_remaining": (self.players_rem_entry.get().strip() or ""),
            }
            # Also write a last-sent marker
            state["_sent_from_gui"] = True
            state["_ts"] = __import__("time").time()

            # Target the runner's state file (use CWD for packaged/distrib friendly UX; same as run_brain).
            # GUI run from project root or user cwd will write editable jsons there.
            data_dir = os.getcwd()
            state_path = os.path.join(data_dir, "clubgg_current_state.json")
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)

            # Enhanced: always sync FULL multi-villain notes set (from mgr) to clubgg_player_notes.json on Send.
            # This makes "Send to runner" fully powerful for the table view + custom profiles. Runner watcher picks live.
            # Still supports single key for legacy quick path; no breakage.
            try:
                from .models import get_notes_manager
                mgr = get_notes_manager()
                all_notes = {p: mgr.get_notes(p) for p in mgr.list_players()}
                # also include customs if present
                if getattr(mgr, "_custom_presets", None):
                    all_notes["_custom_presets"] = mgr._custom_presets
                notes_path = os.path.join(data_dir, "clubgg_player_notes.json")
                with open(notes_path, "w", encoding="utf-8") as nf:
                    json.dump(all_notes, nf, indent=2)
                synced_keys = list(mgr.list_players())
                state["_notes_synced"] = ",".join(synced_keys[:4]) or "none"
                if len(synced_keys) > 4:
                    state["_notes_synced"] += f"+{len(synced_keys)-4}"
            except Exception:
                # fallback to old single-key behavior
                if self.explo_var.get():
                    key = (self.notes_key_entry.get().strip() or "villain")
                    try:
                        from .models import get_player_notes
                        notes = get_player_notes(key)
                        notes_path = os.path.join(data_dir, "clubgg_player_notes.json")
                        existing = {}
                        if os.path.exists(notes_path):
                            try:
                                with open(notes_path, "r", encoding="utf-8") as nf:
                                    existing = json.load(nf) or {}
                            except Exception:
                                existing = {}
                        existing[key] = notes
                        with open(notes_path, "w", encoding="utf-8") as nf:
                            json.dump(existing, nf, indent=2)
                        state["_notes_synced"] = key
                    except Exception:
                        pass

            msg = f"✅ Sent state to runner (clubgg_current_state.json). If `python -m pokerflex --background` (or run_brain) is running, watcher will reload in ~2s.\n   tmode={state['tournament_mode']}  icm={state['icm_factor']}  players={state['players_remaining']}"
            if state.get("_notes_synced"):
                msg += f"  + FULL notes table synced ({state['_notes_synced']}) to clubgg_player_notes.json (live explo)"
            self.output_box.delete("1.0", "end")
            self.output_box.insert("end", msg + "\n")
        except Exception as ex:
            self.output_box.delete("1.0", "end")
            self.output_box.insert("end", f"⚠️ Send to runner failed: {ex}\n")

    def analyze(self):
        if self.inputs:
            data = {k: v.get().strip() for k, v in self.inputs.items()}
        else:
            p = self.last_parsed or {}
            data = {
                "Position": p.get("position", ""),
                "Hand": p.get("hand", ""),
                "Board": p.get("board", ""),
                "Opponents": str(p.get("opponents", "")),
                "Stack (bb)": str(p.get("stack", "")),
                "Ante (bb)": str(p.get("ante", "")),
            }
        self.output_box.delete("1.0", "end")
        self.output_box.insert("end", "⏳ Analyzing with A1 brain…\n")

        # Live mode: prefill from capture (sim for safety / no-deps crash in GUI env)
        if self.live_var.get():
            try:
                from .capture import capture_and_parse
                _, parsed = capture_and_parse(simulate=True, silent=True, sim_step=self._sim_step, sim_scenario="demo")
                self._sim_step += 1
                if parsed:
                    mapping = [
                        ("Position", "position"), ("Hand", "hand"), ("Board", "board"),
                        ("Opponents", "opponents"), ("Stack (bb)", "stack"), ("Ante (bb)", "ante"),
                    ]
                    for gui_k, p_k in mapping:
                        if p_k in parsed and parsed[p_k] not in (None, "") and gui_k in getattr(self, "inputs", {}):
                            self.inputs[gui_k].delete(0, "end")
                            self.inputs[gui_k].insert(0, str(parsed[p_k]))
                    if "tournament_mode" in parsed:
                        self.tourn_var.set(str(parsed.get("tournament_mode", "")).lower() in ("true","1","yes"))
                    if "icm_factor" in parsed:
                        self.icm_entry.delete(0, "end"); self.icm_entry.insert(0, str(parsed["icm_factor"]))
                    if parsed.get("players_remaining"):
                        self.players_rem_entry.delete(0, "end"); self.players_rem_entry.insert(0, str(parsed["players_remaining"]))
                    data = {k: v.get().strip() for k, v in self.inputs.items()}  # refresh after fill
                    self.output_box.insert("end", "[live] fields auto-filled from sim capture\n")
            except Exception as ex:
                self.output_box.insert("end", f"[live capture skipped: {ex}]\n")

        # Collect A1 options
        tmode = bool(self.tourn_var.get())
        prem = self.players_rem_entry.get().strip()
        players_remaining = int("".join(c for c in prem if c.isdigit()) or 0) or None
        icm_str = self.icm_entry.get().strip()
        try:
            icm_factor = float(icm_str) if icm_str else 0.0
        except Exception:
            icm_factor = 0.0

        player_notes = None
        if self.explo_var.get():
            key = self.notes_key_entry.get().strip() or "villain"
            try:
                from .models import get_player_notes
                player_notes = get_player_notes(key)
                # if only defaults and no custom, still pass (advisor will see explo_notes_used if flag)
            except Exception:
                player_notes = {"notes": f"explo key={key} (manager unavailable)"}

        def work():
            text, data_out = get_advice(
                position=data.get("Position", ""),
                hand=data.get("Hand", ""),
                board=data.get("Board", ""),
                opponents=data.get("Opponents", ""),
                stack=data.get("Stack (bb)", ""),
                ante=data.get("Ante (bb)", ""),
                player_notes=player_notes,
                tournament_mode=tmode,
                players_remaining=players_remaining,
                icm_factor=icm_factor,
            )
            # marshal back onto the Tk main thread
            self.app.after(0, lambda: self._show(text, data_out))

        threading.Thread(target=work, daemon=True).start()

    def _show(self, text, data=None):
        self.output_box.delete("1.0", "end")
        self.output_box.insert("end", text)
        # Optional: surface a couple key A1 metrics as a compact footer line if not already obvious in text
        if data and isinstance(data, dict):
            extras = []
            if data.get("texture") or data.get("texture_summary"):
                extras.append(f"texture={data.get('texture') or data.get('texture_summary')}")
            if "spr" in data or (data.get("metrics") and "spr" in (data.get("metrics") or {})):
                spr = data.get("spr") or (data.get("metrics") or {}).get("spr")
                if spr: extras.append(f"SPR={float(spr):.2f}")
            if "confidence" in data:
                extras.append(f"conf={float(data['confidence'])*100:.0f}%")
            if data.get("exploitative_notes") or data.get("explo_notes_used"):
                extras.append("🎯EXPLO")
            if "icm_factor" in data and float(data.get("icm_factor", 0)) > 0:
                extras.append(f"ICM~{float(data['icm_factor']):.2f}")
            if extras:
                self.output_box.insert("end", "\n— A1 metrics: " + " | ".join(extras))

def main():
    """Entry point for `python -m pokerflex.main` or shims."""
    _log("main() called, creating PokerFlex instance")
    try:
        app = PokerFlex()
        _log("PokerFlex instance created, entering mainloop() - window should stay open until user closes it")
        app.app.mainloop()
        _log("mainloop() exited normally (user closed window)")
    except Exception as ex:
        _log(f"EXCEPTION in main(): {ex}")
        _log(traceback.format_exc())
        # Force console visible on crash for debugging (reverse hide)
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 1)  # SW_SHOWNORMAL
        except:
            pass
        print("\n\n=== GUI CRASHED ===")
        print(f"Error: {ex}")
        print("Full traceback above in logs or console.")
        print("Check gui_debug.log and gui_launched.txt in the folder.")
        # Also try to show in a simple message if possible
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("PokerFlex GUI Error", f"App crashed:\n{ex}\n\nSee gui_debug.log for details.\n\nCheck the console window for traceback.")
            root.destroy()
        except:
            pass
        input("\nPress Enter to close this console...")
        raise


if __name__ == "__main__":
    main()
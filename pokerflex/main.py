import customtkinter as ctk
import keyboard
import threading
import json
import os
from .poker_engine import get_advice

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Explicit module-level default (A1 UNAMBIGUOUS) for the GUI entry (even though delegates to poker_engine.get_advice which honors the flag).
# GUI always shows/uses A1 by default ("PokerFlex A1" titles, rich output, notes/ICM/explo options).
USE_NEW_BRAIN = True

# NOTE: get_advice defaults to the advanced A1 brain (USE_NEW_BRAIN=True explicit module-level default in poker_engine.py + ALL launchers/entry points/GUI/`python -m pokerflex`).
# THIS IS THE UNAMBIGUOUS DEFAULT EXPERIENCE for the app (including when launched via python -m pokerflex or main.py or pokerflex CLI).
# GUI transparently benefits from richer A1 output (texture, SPR, range advantage, ICM, explo notes,
# better postflop heuristics, etc.) via the thin shim. Legacy behavior is 100% preserved *only if forced*
# via POKERFLEX_FORCE_LEGACY_BRAIN=1 env var (or CONFIG.force_legacy_brain=True) for debugging ONLY.
#
# ENHANCED for assistant use case (still simple + backward compat):
# - Explicit UI for tournament_mode/ICM, player notes (explo via key + presets), live capture toggle.
# - Analyze passes full params to get_advice so new brain uses them (ICM, notes for explo range adjust).
# - Output is rich format_a1_advice text: [A1 Brain], texture, SPR, confidence, 🎯 EXPLOIT, ICM factor etc.
# - "Copy to clipboard" + "Send to background runner" (writes clubgg_current_state.json for runner watcher).
# - Hotkey popup (ctrl+alt+p) preserved. Live mode uses capture_and_parse (sim by default for safety).
# - Titles/labels updated to A1. Direct calls already went through shim; now UI surfaces the controls.


class PokerFlex:
    def __init__(self):
        self.app = ctk.CTk()
        self.app.title("PokerFlex A1 — GTO + Explo Assistant")
        self.app.geometry("1000x820")

        self.build_ui()
        self.bind_hotkeys()

        self._sim_step = 0  # for cycling live sim captures in demo mode

        # Prefill sensible A1 demo defaults (non-destructive; user can clear)
        try:
            self.inputs["Position"].insert(0, "BTN")
            self.inputs["Hand"].insert(0, "AhKs")
            self.inputs["Board"].insert(0, "Qd7h2c")
            self.inputs["Opponents"].insert(0, "1")
            self.inputs["Stack (bb)"].insert(0, "80")
            self.inputs["Ante (bb)"].insert(0, "0")
            # Example A1 options (commented for pure GTO start; uncomment to demo ICM/explo on launch)
            # self.tourn_var.set(False)
            # self.players_rem_entry.insert(0, "6")
            # self.icm_entry.insert(0, "0.0")
            self.notes_key_entry.insert(0, "nit")
            # self.explo_var.set(False)  # flip True + preset button to engage explo
            # self.live_var.set(False)
        except Exception:
            pass  # safe if fields change

    def build_ui(self):
        ctk.CTkLabel(self.app, text="PokerFlex A1", font=ctk.CTkFont(size=36, weight="bold")).pack(pady=12)
        ctk.CTkLabel(self.app, text="Real-time GTO + Explo Co-Pilot — A1 Brain  |  ctrl+alt+p to bring up", font=ctk.CTkFont(size=14)).pack(pady=(0,16))

        # Core input frame (input fields preserved for compat)
        frame = ctk.CTkFrame(self.app)
        frame.pack(pady=6, padx=30, fill="x")

        fields = [
            ("Position", "UTG / MP / CO / BTN / SB / BB"),
            ("Hand", "your 2 hole cards, e.g. AhKs"),
            ("Board", "community cards, e.g. Qd7h2c  (blank preflop)"),
            ("Opponents", "number of players still in, e.g. 2"),
            ("Stack (bb)", "effective stack in big blinds, e.g. 100"),
            ("Ante (bb)", "big-blind ante, e.g. 1   (0 if none)"),
        ]
        self.inputs = {}

        for field, hint in fields:
            ctk.CTkLabel(frame, text=f"{field}:").pack(anchor="w", padx=20, pady=(8,0))
            entry = ctk.CTkEntry(frame, placeholder_text=hint, height=32)
            entry.pack(fill="x", padx=20, pady=(2,8))
            self.inputs[field] = entry

        # === A1 Assistant Options (new for tournament/ICM, explo notes, live) ===
        opts = ctk.CTkFrame(self.app)
        opts.pack(pady=8, padx=30, fill="x")

        ctk.CTkLabel(opts, text="A1 Assistant Options", font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=12, pady=(6,2))

        # Row 1: Tournament / ICM
        row1 = ctk.CTkFrame(opts)
        row1.pack(fill="x", padx=8, pady=2)
        self.tourn_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(row1, text="Tournament mode / ICM", variable=self.tourn_var, width=180).pack(side="left", padx=8)
        ctk.CTkLabel(row1, text="Players rem:").pack(side="left", padx=(12,4))
        self.players_rem_entry = ctk.CTkEntry(row1, placeholder_text="e.g. 6", width=60)
        self.players_rem_entry.pack(side="left", padx=2)
        ctk.CTkLabel(row1, text="ICM factor:").pack(side="left", padx=(12,4))
        self.icm_entry = ctk.CTkEntry(row1, placeholder_text="0.0 or 0.15", width=70)
        self.icm_entry.pack(side="left", padx=2)
        ctk.CTkLabel(row1, text="(auto if tmode+players)").pack(side="left", padx=6)

        # Row 2: Explo / Player notes (simple text entry + presets kept for quick single-key; table below for full multi-villain)
        row2 = ctk.CTkFrame(opts)
        row2.pack(fill="x", padx=8, pady=2)
        self.explo_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(row2, text="Exploitative (use notes)", variable=self.explo_var, width=180).pack(side="left", padx=8)
        ctk.CTkLabel(row2, text="Quick key:").pack(side="left", padx=(8,4))
        self.notes_key_entry = ctk.CTkEntry(row2, placeholder_text="nit / station / villain / seat3 / btn_villain", width=140)
        self.notes_key_entry.pack(side="left", padx=2)
        # Quick preset buttons (still work; now also feed the full table view)
        ctk.CTkButton(row2, text="NIT", width=42, command=lambda: self._apply_preset("nit")).pack(side="left", padx=2)
        ctk.CTkButton(row2, text="Station", width=52, command=lambda: self._apply_preset("station")).pack(side="left", padx=2)
        ctk.CTkButton(row2, text="Aggro", width=46, command=lambda: self._apply_preset("maniac")).pack(side="left", padx=2)
        ctk.CTkButton(row2, text="Clear", width=42, command=self._clear_notes).pack(side="left", padx=2)

        # === ENHANCED NOTES / EXPLOITATIVE SYSTEM UX: proper expandable table/list view for multi-villain ===
        # Columns: villain key, fold_to_cbet, fold_dry, fold_wet, agg_factor, cbet_freq, free_notes. Per-row add/edit/delete, apply presets, save live.
        # "Send to runner" syncs full notes set. Changes live (mgr auto-save + watcher in runner). No breakage to old single key / nit/station / 🎯EXPLOIT.
        notes_table = ctk.CTkFrame(opts)
        notes_table.pack(fill="x", padx=8, pady=(2,4))
        ctk.CTkLabel(notes_table, text="Explo Notes Table (multi-villain: keys=names/seats/pos; live table + effects; syncs on Send/Analyze)", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=6, pady=(2,1))

        self.notes_table_frame = ctk.CTkScrollableFrame(notes_table, height=95, width=940)
        self.notes_table_frame.pack(fill="x", padx=4, pady=2)

        tbl_btns = ctk.CTkFrame(notes_table)
        tbl_btns.pack(fill="x", padx=4, pady=1)
        ctk.CTkButton(tbl_btns, text="🔄 Refresh table", width=110, command=self._refresh_notes_table).pack(side="left", padx=3)
        ctk.CTkButton(tbl_btns, text="➕ Add villain key", width=120, command=self._add_villain_key).pack(side="left", padx=3)
        ctk.CTkButton(tbl_btns, text="💾 Save live (all)", width=110, command=self._save_notes_live).pack(side="left", padx=3)
        ctk.CTkButton(tbl_btns, text="🧹 Clear all notes", width=110, command=self._clear_all_notes_table).pack(side="left", padx=3)
        ctk.CTkLabel(tbl_btns, text="Per-row: Edit fields / apply preset / del. Use runner 'notes edit' for advanced (history, custom profiles, preview).", font=ctk.CTkFont(size=9)).pack(side="left", padx=8)

        # initial populate
        try:
            self._refresh_notes_table()
        except Exception:
            pass

        # Row 3: Live mode toggle
        row3 = ctk.CTkFrame(opts)
        row3.pack(fill="x", padx=8, pady=2)
        self.live_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(row3, text="Live mode (auto-capture on Analyze — uses sim for safety; toggle real via edit if wanted)", variable=self.live_var, width=520).pack(side="left", padx=8)
        ctk.CTkButton(row3, text="Capture now", width=90, command=self._do_capture_fill).pack(side="left", padx=8)

        # Primary action row (analyze + new assistant buttons)
        btnrow = ctk.CTkFrame(self.app)
        btnrow.pack(pady=10, padx=30, fill="x")

        ctk.CTkButton(btnrow, text="Analyze & Get A1 Advice", command=self.analyze, height=42, font=ctk.CTkFont(size=15, weight="bold")).pack(side="left", padx=6, expand=True, fill="x")
        ctk.CTkButton(btnrow, text="📋 Copy to clipboard", command=self._copy_output, height=42).pack(side="left", padx=6)
        ctk.CTkButton(btnrow, text="➡️ Send to background runner", command=self._send_to_runner, height=42).pack(side="left", padx=6)

        self.output_box = ctk.CTkTextbox(self.app, height=320, font=ctk.CTkFont(size=14))
        self.output_box.pack(pady=10, padx=30, fill="both", expand=True)

        # Footer hint
        ctk.CTkLabel(self.app, text="A1: texture • SPR • conf • 🎯EXPLOIT (notes table live) • ICM • [A1]. Notes table: multi-villain + per-row presets/edit; Send syncs all notes. Runner 'notes edit' for previews/customs. 0-touch live via watcher.", font=ctk.CTkFont(size=10)).pack(pady=(0,8))

    def bind_hotkeys(self):
        keyboard.add_hotkey('ctrl+alt+p', self.popup)

    def popup(self):
        self.app.deiconify()
        self.app.lift()
        self.app.focus_force()

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
            self.output_box.delete("1.0", "end")
            self.output_box.insert("end", f"✅ Preset '{preset}' applied for key '{key}'.\n  fold_to_cbet={notes.get('fold_to_cbet')}  notes: {notes.get('notes','')[:60]}...\n  (explo checkbox auto-enabled; will pass to A1 on Analyze)\n")
            self._refresh_notes_table()
        except Exception as ex:
            self.output_box.delete("1.0", "end")
            self.output_box.insert("end", f"⚠️ Preset error (notes may still work if set): {ex}\n")

    # --- Enhanced multi-villain notes table UX helpers (live, per-row presets, edit via simple toplevel) ---
    def _refresh_notes_table(self):
        """Rebuild the expandable table/list rows from current mgr (supports multi keys like seatX, names, pos)."""
        if not hasattr(self, "notes_table_frame") or self.notes_table_frame is None:
            return
        for child in list(self.notes_table_frame.winfo_children()):
            child.destroy()
        try:
            from .models import get_notes_manager, describe_explo_effect
            mgr = get_notes_manager()
            players = mgr.list_players() or []
            if not players:
                ctk.CTkLabel(self.notes_table_frame, text="(no notes — quick NIT/Station above or Add key below; also 'notes edit' in runner for rich UX)", font=ctk.CTkFont(size=10)).pack(anchor="w", padx=4)
                return
            # simple header row
            hdr = ctk.CTkFrame(self.notes_table_frame)
            hdr.pack(fill="x", pady=(0,1))
            cols = [("Key", 68), ("f2c", 42), ("dry", 42), ("wet", 42), ("AF", 42), ("cbet%", 46), ("free_notes", 155), ("", 200)]
            for txt, w in cols:
                ctk.CTkLabel(hdr, text=txt, width=w, font=ctk.CTkFont(size=9, weight="bold")).pack(side="left", padx=1)
            for p in players[:8]:  # cap for UI
                n = mgr.get_notes(p)
                row = ctk.CTkFrame(self.notes_table_frame)
                row.pack(fill="x", pady=0)
                ctk.CTkLabel(row, text=str(p)[:11], width=68, font=ctk.CTkFont(size=9)).pack(side="left", padx=1)
                for fld, ww in [("fold_to_cbet",42), ("fold_to_cbet_dry",42), ("fold_to_cbet_wet",42), ("aggression_factor",42), ("cbet_freq",46)]:
                    val = n.get(fld, 0)
                    try:
                        vs = f"{float(val):.2f}"
                    except Exception:
                        vs = str(val)[:5]
                    ctk.CTkLabel(row, text=vs, width=ww, font=ctk.CTkFont(size=9)).pack(side="left", padx=1)
                nt = str(n.get("notes", ""))[:22].replace("\n", " ")
                ctk.CTkLabel(row, text=nt, width=155, font=ctk.CTkFont(size=8)).pack(side="left", padx=1)
                # actions per row: edit (full), presets, del. Live update table after.
                ctk.CTkButton(row, text="Edit", width=38, height=18, font=ctk.CTkFont(size=9), command=lambda pp=p: self._edit_villain_notes(pp)).pack(side="left", padx=1)
                ctk.CTkButton(row, text="NIT", width=32, height=18, font=ctk.CTkFont(size=8), command=lambda pp=p: self._apply_preset_to("nit", pp)).pack(side="left", padx=1)
                ctk.CTkButton(row, text="Sta", width=28, height=18, font=ctk.CTkFont(size=8), command=lambda pp=p: self._apply_preset_to("station", pp)).pack(side="left", padx=1)
                ctk.CTkButton(row, text="Agg", width=28, height=18, font=ctk.CTkFont(size=8), command=lambda pp=p: self._apply_preset_to("maniac", pp)).pack(side="left", padx=1)
                ctk.CTkButton(row, text="✕", width=22, height=18, font=ctk.CTkFont(size=9), fg_color="red", command=lambda pp=p: self._delete_villain(pp)).pack(side="left", padx=1)
                # effect tag inline (compact)
                try:
                    eff = describe_explo_effect(p)
                    short_eff = eff.split(":",1)[-1][:35] if ":" in eff else eff[:35]
                    ctk.CTkLabel(row, text=short_eff, font=ctk.CTkFont(size=7), text_color="gray").pack(side="left", padx=2)
                except Exception:
                    pass
        except Exception as ex:
            ctk.CTkLabel(self.notes_table_frame, text=f"(table refresh err: {ex})", font=ctk.CTkFont(size=9)).pack()

    def _apply_preset_to(self, preset: str, player_key: str):
        """Apply preset directly to a row's villain key (from table). Refreshes table + enables explo."""
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
            self.output_box.delete("1.0", "end")
            self.output_box.insert("end", f"✅ Table: '{preset}' for '{player_key}'\n  {notes.get('notes','')[:70]}...\n")
            self._refresh_notes_table()
        except Exception as ex:
            self.output_box.insert("end", f"table preset err: {ex}\n")

    def _edit_villain_notes(self, player_key: str):
        """Simple toplevel editor for a row: fields for main tendencies + free notes. Save live updates table."""
        try:
            from .models import get_notes_manager
            mgr = get_notes_manager()
            n = mgr.get_notes(player_key)
            win = ctk.CTkToplevel(self.app)
            win.title(f"Edit notes: {player_key}")
            win.geometry("520x320")
            ctk.CTkLabel(win, text=f"Editing multi-villain key: {player_key} (live save to clubgg_player_notes.json)").pack(pady=4)
            fields = {}
            rowf = ctk.CTkFrame(win)
            rowf.pack(fill="x", padx=8)
            for i, (lab, key) in enumerate([
                ("fold_to_cbet", "fold_to_cbet"), ("dry", "fold_to_cbet_dry"), ("wet", "fold_to_cbet_wet"),
                ("AF", "aggression_factor"), ("cbet%", "cbet_freq"), ("3b%", "3bet_freq")
            ]):
                ctk.CTkLabel(rowf, text=lab).grid(row=0, column=i, padx=2)
                e = ctk.CTkEntry(rowf, width=60)
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
                            try:
                                tend[k] = float(val)
                            except:
                                tend[k] = val
                    if free_e.get().strip():
                        tend["notes"] = free_e.get().strip()
                    mgr.set_notes(player_key, tend)
                    self.output_box.insert("end", f"✅ Saved live edits for '{player_key}'.\n")
                    self._refresh_notes_table()
                    win.destroy()
                except Exception as ex:
                    self.output_box.insert("end", f"edit save err: {ex}\n")
            ctk.CTkButton(win, text="Save live + close", command=do_save).pack(pady=8)
            ctk.CTkButton(win, text="Apply NIT to this", command=lambda: (mgr.apply_nit_preset(player_key), self._refresh_notes_table(), win.destroy())).pack()
            ctk.CTkButton(win, text="Cancel", command=win.destroy).pack(pady=2)
            # also show current effect preview
            try:
                from .models import describe_explo_effect
                ctk.CTkLabel(win, text=f"Current effect: {describe_explo_effect(player_key)}", font=ctk.CTkFont(size=9)).pack(pady=4)
            except Exception:
                pass
        except Exception as ex:
            self.output_box.insert("end", f"edit dialog err: {ex}\n")

    def _delete_villain(self, player_key: str):
        try:
            from .models import get_notes_manager
            get_notes_manager().clear(player_key)
            self.output_box.insert("end", f"🧹 Deleted notes for '{player_key}'.\n")
            self._refresh_notes_table()
        except Exception as ex:
            self.output_box.insert("end", f"del err: {ex}\n")

    def _add_villain_key(self):
        # simple prompt via entry in output or use dialog
        try:
            key = self.notes_key_entry.get().strip()
            if not key:
                # fallback: use a default new
                key = "new_villain"
            from .models import get_notes_manager
            mgr = get_notes_manager()
            mgr.set_notes(key, {"notes": "added from GUI table"})
            self.notes_key_entry.delete(0, "end")
            self.notes_key_entry.insert(0, key)
            self.explo_var.set(True)
            self.output_box.insert("end", f"➕ Added key '{key}' (edit row or use presets).\n")
            self._refresh_notes_table()
        except Exception as ex:
            self.output_box.insert("end", f"add key err: {ex}\n")

    def _save_notes_live(self):
        try:
            from .models import get_notes_manager
            mgr = get_notes_manager()
            mgr.save()
            self.output_box.insert("end", "💾 Notes saved live (mgr). Runner watcher will pick if running.\n")
            self._refresh_notes_table()
        except Exception as ex:
            self.output_box.insert("end", f"save err {ex}\n")

    def _clear_all_notes_table(self):
        try:
            from .poker_engine import clear_explo_notes
            clear_explo_notes()
            self.output_box.delete("1.0", "end")
            self.output_box.insert("end", "🧹 All notes cleared (table refreshed).\n")
            self._refresh_notes_table()
        except Exception as ex:
            self.output_box.insert("end", f"clear all err: {ex}\n")

    def _clear_notes(self):
        try:
            from .poker_engine import clear_explo_notes
            clear_explo_notes()
            key = self.notes_key_entry.get().strip() or "villain"
            self.output_box.delete("1.0", "end")
            self.output_box.insert("end", f"🧹 Cleared notes (including for '{key}').\n")
            if hasattr(self, "_refresh_notes_table"):
                self._refresh_notes_table()
        except Exception as ex:
            self.output_box.delete("1.0", "end")
            self.output_box.insert("end", f"Clear notes error: {ex}\n")

    def _do_capture_fill(self):
        """Manual capture button: populate core fields from capture (sim by default for GUI safety)."""
        self.output_box.delete("1.0", "end")
        self.output_box.insert("end", "📸 Capturing (simulated for demo safety)...\n")
        try:
            from .capture import capture_and_parse
            # Use simulate=True by default (safe, no window req). User can edit capture.py call or runner for real.
            path, parsed = capture_and_parse(simulate=True, silent=True, sim_step=self._sim_step, sim_scenario="demo")
            self._sim_step += 1
            if parsed:
                mapping = [
                    ("Position", "position"),
                    ("Hand", "hand"),
                    ("Board", "board"),
                    ("Opponents", "opponents"),
                    ("Stack (bb)", "stack"),
                    ("Ante (bb)", "ante"),
                ]
                filled = []
                for gui_k, p_k in mapping:
                    if p_k in parsed and parsed[p_k] not in (None, ""):
                        self.inputs[gui_k].delete(0, "end")
                        val = str(parsed[p_k])
                        self.inputs[gui_k].insert(0, val)
                        filled.append(f"{gui_k}={val}")
                # Also pull assistant options if present in parsed state
                if "tournament_mode" in parsed:
                    self.tourn_var.set(str(parsed["tournament_mode"]).lower() in ("true", "1", "yes", "t"))
                if "icm_factor" in parsed:
                    self.icm_entry.delete(0, "end")
                    self.icm_entry.insert(0, str(parsed["icm_factor"]))
                if "players_remaining" in parsed and parsed["players_remaining"]:
                    self.players_rem_entry.delete(0, "end")
                    self.players_rem_entry.insert(0, str(parsed["players_remaining"]))
                self.output_box.insert("end", f"✅ Filled: {', '.join(filled) or 'no changes'}\n(Use real capture by running runner --live --real-vision (or --live without --simulate); edit this to simulate=False)\n")
            else:
                self.output_box.insert("end", "No parsed state from capture.\n")
        except Exception as ex:
            self.output_box.insert("end", f"⚠️ Capture fill failed (install vision deps if real capture wanted): {ex}\nTry manual entry or run with --live --real-vision (or without --simulate) in runner.\n")

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
            data = {k: v.get().strip() for k, v in self.inputs.items()}
            state = {
                "position": data.get("Position", ""),
                "hand": data.get("Hand", ""),
                "board": data.get("Board", ""),
                "opponents": data.get("Opponents", ""),
                "stack": data.get("Stack (bb)", ""),
                "ante": data.get("Ante (bb)", ""),
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
        data = {k: v.get().strip() for k, v in self.inputs.items()}
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
                        if p_k in parsed and parsed[p_k] not in (None, ""):
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
    app = PokerFlex()
    app.app.mainloop()


if __name__ == "__main__":
    main()
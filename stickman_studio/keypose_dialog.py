"""The Key Poses window of 03 PLAY / FIX (upgrade Phase 6). Opened with K or KEY POSES… in the player.

Left: frames the rules suggest (with the reason), to ACCEPT (with a label) or REJECT. Right: your key poses
(accepted and marked by hand), to go to, relabel or remove. MARK marks the frame the player is on. Every change is
saved at once in key_poses.json next to the trace; trace.json is never touched.
"""
import tkinter as tk
from tkinter import ttk

import hud
import keyposes as kp

RULES = [("first_last", "First and last frame", None),
         ("direction", "Direction change (head, hands, feet) of at least", ("direction_deg", 45, 170, 5, "°")),
         ("extension", "Limb at full reach, standing out by at least", ("extension_prom", 0.1, 0.9, 0.05, "of its range")),
         ("angles", "Elbow / knee / torso angle min or max, standing out by", ("angle_prom", 10, 90, 5, "°")),
         ("sudden", "Sudden change in a joint's speed of at least", ("sudden_ratio", 1.5, 6.0, 0.5, "×")),
         ("stationary", "Body still: every joint slower than", ("still_speed", 0.01, 0.3, 0.01, "bones / frame"))]


class KeyPoseDialog:
    def __init__(self, player):
        self.p = player
        self.job = None
        self.data = player.kp_data
        self.win = w = tk.Toplevel(player.win.winfo_toplevel(), bg=hud.BG)
        w.title("Key poses")
        w.transient(player.win.winfo_toplevel())
        w.resizable(False, False)
        w.protocol("WM_DELETE_WINDOW", self.close)
        P = dict(padx=14)
        hud.Header(w, "Key poses").pack(fill="x", pady=(12, 2), **P)
        hud.label(w, "Suggestions come from simple rules on your coordinates and the thresholds below (no AI): each "
                     "one says why. Labels are yours to choose. Saved at once in key_poses.json next to the trace.",
                  fg=hud.DIM, font=hud.SMALL, anchor="w", justify="left", wraplength=880).pack(fill="x", pady=(0, 8),
                                                                                              **P)
        # ---- rules and thresholds
        rf = tk.Frame(w, bg=hud.BG)
        rf.pack(fill="x", **P)
        st = self.data["settings"]
        self.on, self.val, self.val_lbl = {}, {}, {}
        for r, (key, text, thr) in enumerate(RULES):
            v = tk.BooleanVar(value=bool(st.get(key, True)))
            ttk.Checkbutton(rf, text=text, variable=v, command=self.settings_changed).grid(row=r, column=0,
                                                                                          sticky="w")
            self.on[key] = v
            if thr:
                name, lo, hi, step, unit = thr
                dv = tk.DoubleVar(value=float(st.get(name, kp.DEFAULTS[name])))
                sc = tk.Scale(rf, from_=lo, to=hi, resolution=step, orient="horizontal", variable=dv, length=180,
                              command=lambda e: self.settings_changed())
                hud.style_scale(sc)
                sc.grid(row=r, column=1, padx=(10, 6), sticky="w")
                lbl = hud.label(rf, "", fg=hud.DIM, font=hud.SMALL, anchor="w", width=22)
                lbl.grid(row=r, column=2, sticky="w")
                self.val[name], self.val_lbl[name] = dv, (lbl, unit)
        self.show_values()

        # ---- the two lists
        lists = tk.Frame(w, bg=hud.BG)
        lists.pack(fill="x", pady=(12, 0), **P)
        left = tk.Frame(lists, bg=hud.BG)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(lists, bg=hud.BG)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))
        self.sug_title = hud.label(left, "", font=hud.BOLD, anchor="w")
        self.sug_title.pack(fill="x")
        self.sug = self.listbox(left)
        sb = tk.Frame(left, bg=hud.BG)
        sb.pack(fill="x", pady=(4, 0))
        hud.Button(sb, "Go to", lambda: self.go_to(self.sug_frame()), padx=8, font=hud.SMALL).pack(side="left")
        hud.Button(sb, "Accept", self.accept, kind="red", padx=8, font=hud.SMALL).pack(side="left", padx=4)
        hud.Button(sb, "Reject", self.reject, padx=8, font=hud.SMALL).pack(side="left")
        hud.Button(sb, "Accept All", self.accept_all, padx=8, font=hud.SMALL).pack(side="left", padx=4)
        self.restore_btn = hud.Button(sb, "", self.restore_rejected, padx=8, font=hud.SMALL)
        self.restore_btn.pack(side="right")

        self.mine_title = hud.label(right, "", font=hud.BOLD, anchor="w")
        self.mine_title.pack(fill="x")
        self.mine = self.listbox(right)
        mb = tk.Frame(right, bg=hud.BG)
        mb.pack(fill="x", pady=(4, 0))
        hud.Button(mb, "Go to", lambda: self.go_to(self.mine_frame()), padx=8, font=hud.SMALL).pack(side="left")
        hud.Button(mb, "Relabel", self.relabel, padx=8, font=hud.SMALL).pack(side="left", padx=4)
        hud.Button(mb, "Remove", self.remove, padx=8, font=hud.SMALL).pack(side="left")

        # ---- label + mark
        bar = tk.Frame(w, bg=hud.BG)
        bar.pack(fill="x", pady=(12, 0), **P)
        hud.label(bar, "LABEL", font=hud.BOLD).pack(side="left")
        self.label = tk.StringVar(value=kp.LABELS[0])
        self.label_box = ttk.Combobox(bar, textvariable=self.label, values=kp.LABELS, width=22)
        self.label_box.pack(side="left", padx=8)
        hud.label(bar, "(pick one or type your own; used by Accept, Relabel and Mark)", fg=hud.DIM,
                  font=hud.SMALL).pack(side="left")
        mk = tk.Frame(w, bg=hud.BG)
        mk.pack(fill="x", pady=(8, 0), **P)
        self.mark_btn = hud.Button(mk, "", self.mark_current, kind="red", padx=10)
        self.mark_btn.pack(side="left")
        self.status = hud.label(mk, "", fg=hud.GREEN, font=hud.SMALL, anchor="w")
        self.status.pack(side="left", padx=12)
        cb = tk.Frame(w, bg=hud.BG)
        cb.pack(fill="x", pady=12, **P)
        hud.Button(cb, "Close", self.close).pack(side="right")
        self.sug.bind("<<ListboxSelect>>", lambda e: self.pick_label(self.sug_item()))
        self.mine.bind("<<ListboxSelect>>", lambda e: self.pick_label(self.mine_item()))
        self.sug.bind("<Double-Button-1>", lambda e: self.go_to(self.sug_frame()))
        self.mine.bind("<Double-Button-1>", lambda e: self.go_to(self.mine_frame()))
        w.bind("<Escape>", lambda e: self.close())
        self.refresh()
        self.tick()

    def listbox(self, parent):
        lb = tk.Listbox(parent, height=9, bg=hud.PANEL, fg=hud.TEXT, selectbackground=hud.RED,
                        selectforeground="#ffffff", font=hud.SMALL, activestyle="none", highlightthickness=1,
                        highlightbackground=hud.LINE, bd=0, exportselection=False, width=60)
        lb.pack(fill="both", expand=True)
        return lb

    # ---- settings
    def show_values(self):
        for name, dv in self.val.items():
            lbl, unit = self.val_lbl[name]
            v = dv.get()
            txt = f"{v * 100:.0f}% {unit}" if name == "extension_prom" else f"{v:g} {unit}"
            lbl.configure(text=txt)

    def settings_changed(self):
        self.show_values()
        st = self.data["settings"]
        for key, v in self.on.items():
            st[key] = bool(v.get())
        for name, dv in self.val.items():
            st[name] = float(dv.get())
        if self.job is not None:
            self.win.after_cancel(self.job)
        self.job = self.win.after(200, self.apply_settings)

    def apply_settings(self):
        self.job = None
        self.p.update_key_poses()
        self.save("Settings saved.")
        self.refresh()

    # ---- lists
    def refresh(self):
        self.open = kp.open_suggestions(self.p.kp_suggest, self.data)
        self.sug.delete(0, "end")
        for s in self.open:
            self.sug.insert("end", f" f{s['frame']:>3}   {s['label']}   ·   {s['why']}")
        self.sug_title.configure(text=f"Suggested  ({len(self.open)})")
        poses = sorted(self.data["poses"], key=lambda q: q["frame"])
        self.mine.delete(0, "end")
        for q in poses:
            how = "marked by you" if q.get("source") == "manual" else "accepted"
            self.mine.insert("end", f" f{q['frame']:>3}   {q['label']}   ·   {how}")
        self.mine_title.configure(text=f"Your Key Poses  ({len(poses)})")
        n = len(self.data["rejected"])
        self.restore_btn.configure(text=f"Restore Rejected ({n})", state="normal" if n else "disabled")
        self.p.draw_line()

    def tick(self):
        """Keep MARK's frame number in step with the player."""
        if not self.win.winfo_exists():
            return
        f = self.p.current_frame()
        self.mark_btn.configure(text=f"Mark Frame {f}")
        self.win.after(250, self.tick)

    def sug_item(self):
        sel = self.sug.curselection()
        return self.open[sel[0]] if sel and sel[0] < len(self.open) else None

    def sug_frame(self):
        s = self.sug_item()
        return s["frame"] if s else None

    def mine_item(self):
        sel = self.mine.curselection()
        poses = sorted(self.data["poses"], key=lambda q: q["frame"])
        return poses[sel[0]] if sel and sel[0] < len(poses) else None

    def mine_frame(self):
        q = self.mine_item()
        return q["frame"] if q else None

    def pick_label(self, item):
        if item:
            self.label.set(item["label"])

    # ---- actions
    def save(self, text):
        try:
            kp.save(self.p.tdir, self.data)
            self.status.configure(text=text, fg=hud.GREEN)
        except OSError as e:
            self.status.configure(text=f"Couldn't save key_poses.json: {e}", fg=hud.RED_HI)

    def go_to(self, frame):
        if frame is not None:
            self.p.pause()
            self.p.seek(frame)

    def accept(self):
        s = self.sug_item()
        if not s:
            self.status.configure(text="Pick a suggestion first.", fg=hud.AMBER)
            return
        kp.mark(self.data, s["frame"], self.label.get().strip() or s["label"], "suggested", s["why"])
        self.save(f"Frame {s['frame']} is a key pose: {self.label.get()}.")
        self.refresh()

    def accept_all(self):
        for s in list(self.open):
            kp.mark(self.data, s["frame"], s["label"], "suggested", s["why"])
        self.save(f"Accepted {len(self.open)} suggestion(s) with their suggested labels.")
        self.refresh()

    def reject(self):
        s = self.sug_item()
        if not s:
            self.status.configure(text="Pick a suggestion first.", fg=hud.AMBER)
            return
        kp.reject(self.data, s["frame"])
        self.save(f"Frame {s['frame']} won't be suggested again (Restore Rejected brings it back).")
        self.refresh()

    def restore_rejected(self):
        self.data["rejected"] = []
        self.save("Rejected suggestions are back.")
        self.refresh()

    def relabel(self):
        q = self.mine_item()
        if not q:
            self.status.configure(text="Pick one of your key poses first.", fg=hud.AMBER)
            return
        kp.mark(self.data, q["frame"], self.label.get().strip() or q["label"], q.get("source", "manual"),
                q.get("why", ""))
        self.save(f"Frame {q['frame']} relabelled: {self.label.get()}.")
        self.refresh()

    def remove(self):
        q = self.mine_item()
        if not q:
            self.status.configure(text="Pick one of your key poses first.", fg=hud.AMBER)
            return
        kp.unmark(self.data, q["frame"])
        self.save(f"Frame {q['frame']} is no longer a key pose.")
        self.refresh()

    def mark_current(self):
        f = self.p.current_frame()
        label = self.label.get().strip() or "other"
        kp.mark(self.data, f, label, "manual", "marked by hand")
        between = "" if f in [k for k, _ in self.p.keys] else " (between traced frames)"
        self.save(f"Frame {f} marked as {label}{between}.")
        self.refresh()

    def close(self):
        if self.job is not None:
            try:
                self.win.after_cancel(self.job)
            except tk.TclError:
                pass
            self.apply_settings()
        self.p.kp_dialog = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass

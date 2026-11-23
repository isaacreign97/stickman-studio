"""The Analytics window (upgrade Phase 8). Opened from GAME SETTINGS (ANALYTICS on a move) or 03 PLAY / FIX (A).

Displacement, velocity, acceleration, joint angles and angular change, movement duration, trajectories and the
intervals between frames and key poses, in pixels, bone lengths, metres or game units, using the frame rate.
Read-only, except SAVE CSV… which writes the file you choose.
"""
import os
import tkinter as tk
from tkinter import filedialog, ttk

import analytics as an
import compare as cmp
import hud
import keyposes as kp
import trace_io
import trace_player as tp

GW, GH = 900, 180
DATA = [("keys", "Traced key frames"), ("frames", "Every frame, as Play shows it")]


class AnalyticsDialog:
    def __init__(self, root, folder, title="", on_close=None, frames_dir=None):
        self.root, self.dir, self.on_close = root, folder, on_close   # folder: the trace's (a character's) folder
        self.res = None
        self.poses = {}
        self.frames_dir = frames_dir
        self.vers = [v for v in cmp.versions(folder)] + cmp.other_characters(frames_dir, folder)   # Phase 11
        self.fps_default, self.fps_from = tp.find_fps(frames_dir or folder)   # the move's frame rate
        self.win = w = tk.Toplevel(root, bg=hud.BG)
        w.title("Analytics: " + (title or os.path.basename(folder)))
        w.transient(root)
        w.resizable(False, False)
        w.protocol("WM_DELETE_WINDOW", self.close)
        P = dict(padx=14)
        hud.Header(w, "Analytics  ·  " + (title or os.path.basename(folder))).pack(fill="x", pady=(12, 2), **P)
        hud.label(w, "Measurements of your traced move. Time comes from the frame rate. Pixels are not metres: pick "
                     "the units, and give a height or a scale for real-world or game numbers.", fg=hud.DIM,
                  font=hud.SMALL, anchor="w", justify="left", wraplength=GW).pack(fill="x", pady=(0, 8), **P)

        r1 = tk.Frame(w, bg=hud.BG)
        r1.pack(fill="x", **P)
        hud.label(r1, "VERSION", font=hud.BOLD).pack(side="left")
        self.version = tk.StringVar(value=self.vers[0][0] if self.vers else "")
        self.combo(r1, self.version, [v[0] for v in self.vers], 44)
        hud.label(r1, "DATA", font=hud.BOLD).pack(side="left", padx=(12, 0))
        self.data = tk.StringVar(value=DATA[0][1])
        self.combo(r1, self.data, [t for _, t in DATA], 28)

        r2 = tk.Frame(w, bg=hud.BG)
        r2.pack(fill="x", pady=(6, 0), **P)
        hud.label(r2, "FPS", font=hud.BOLD).pack(side="left")
        self.fps = tk.StringVar(value=f"{self.fps_default:g}")
        e = ttk.Entry(r2, textvariable=self.fps, width=6)
        e.pack(side="left", padx=(6, 4))
        e.bind("<Return>", lambda ev: self.refresh())
        e.bind("<FocusOut>", lambda ev: self.refresh())
        hud.label(r2, f"(from {self.fps_from})", fg=hud.DIM if self.fps_from != "a guess" else hud.AMBER,
                  font=hud.SMALL).pack(side="left")
        hud.label(r2, "UNITS", font=hud.BOLD).pack(side="left", padx=(16, 0))
        self.unit = tk.StringVar(value=an.UNITS[0][1])
        self.combo(r2, self.unit, [t for _, t in an.UNITS], 30)
        self.height = tk.StringVar(value="1.75")
        self.upp = tk.StringVar(value="0.0112")
        hud.label(r2, "height m", fg=hud.DIM, font=hud.SMALL).pack(side="left", padx=(8, 2))
        he = ttk.Entry(r2, textvariable=self.height, width=6)
        he.pack(side="left")
        hud.label(r2, "units / px", fg=hud.DIM, font=hud.SMALL).pack(side="left", padx=(8, 2))
        ue = ttk.Entry(r2, textvariable=self.upp, width=8)
        ue.pack(side="left")
        for ent in (he, ue):
            ent.bind("<Return>", lambda ev: self.refresh())
            ent.bind("<FocusOut>", lambda ev: self.refresh())
        self.note = hud.label(w, "", fg=hud.DIM, font=hud.SMALL, anchor="w")
        self.note.pack(fill="x", pady=(4, 0), **P)

        self.sum_lbl = hud.label(w, "", fg=hud.TEXT, font=hud.SMALL, anchor="w", justify="left", wraplength=GW)
        self.sum_lbl.pack(fill="x", pady=(6, 0), **P)

        r3 = tk.Frame(w, bg=hud.BG)
        r3.pack(fill="x", pady=(8, 2), **P)
        hud.label(r3, "JOINT", font=hud.BOLD).pack(side="left")
        self.joint = tk.StringVar(value="frontHand")
        self.combo(r3, self.joint, an.ORDER, 12, redraw_only=True)
        hud.label(r3, "ANGLE", font=hud.BOLD).pack(side="left", padx=(12, 0))
        self.angle = tk.StringVar(value="front elbow")
        self.combo(r3, self.angle, list(an.ANGLES), 12, redraw_only=True)
        self.graph = tk.Canvas(w, width=GW, height=GH, bg="#16161a", highlightthickness=0)
        self.graph.pack(**P)

        tf = tk.Frame(w, bg=hud.BG)
        tf.pack(fill="x", pady=(8, 0), **P)
        self.text = tk.Text(tf, height=13, width=118, font=(hud.MONO, 9), bg=hud.PANEL, fg=hud.TEXT, bd=0,
                            highlightthickness=1, highlightbackground=hud.LINE, wrap="none")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="x", expand=True)
        self.text.tag_configure("head", foreground=hud.DIM)
        self.text.tag_configure("hi", foreground=hud.AMBER)
        bar = tk.Frame(w, bg=hud.BG)
        bar.pack(fill="x", pady=12, **P)
        hud.Button(bar, "Close", self.close).pack(side="right", padx=(4, 0))
        hud.Button(bar, "Save CSV…", self.save_csv).pack(side="right", padx=(4, 0))
        hud.Button(bar, "Copy Summary", self.copy).pack(side="right")
        self.status = hud.label(bar, "", fg=hud.GREEN, font=hud.SMALL, anchor="w")
        self.status.pack(side="left")
        w.bind("<Escape>", lambda ev: self.close())
        self.refresh()

    def combo(self, parent, var, values, width, redraw_only=False):
        cb = ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=width)
        cb.pack(side="left", padx=(6, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self.draw_graphs() if redraw_only else self.refresh())
        return cb

    # ---- settings
    def settings(self):
        """-> (poses, fps, factor, unit, note) or raises ValueError with a message for the user."""
        v = next((x for x in self.vers if x[0] == self.version.get()), None)
        if not v:
            raise ValueError("This move has no trace yet.")
        poses = cmp.load_poses(v[1])
        mode = next(k for k, t in DATA if t == self.data.get())
        if mode == "frames":
            full = {f: P for f, P in poses.items() if all(n in P for n in an.ORDER)}
            if len(full) < 2:
                raise ValueError("'Every frame' needs at least 2 frames with all 12 joints.")
            poses = an.every_frame(full)
        try:
            fps = float(self.fps.get())
            assert fps > 0
        except (ValueError, AssertionError):
            raise ValueError("Type a frame rate above 0 (frames per second).")
        unit = next(k for k, t in an.UNITS if t == self.unit.get())

        def num(var):
            try:
                return float(var.get())
            except ValueError:
                return None
        k, label, note = an.unit_factor(poses, unit, num(self.height), num(self.upp))
        return poses, fps, k, label, note

    def refresh(self):
        try:
            poses, fps, k, unit, note = self.settings()
        except (ValueError, OSError, KeyError, TypeError) as e:
            self.res = None
            self.note.configure(text=str(e), fg=hud.AMBER)
            self.sum_lbl.configure(text="")
            self.graph.delete("all")
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.configure(state="disabled")
            return
        self.poses, self.fps_now, self.k, self.u = poses, fps, k, unit
        self.note.configure(text="Units: " + note + ("   ·   frame rate is a guess: type the real one"
                                                    if self.fps_from == "a guess" else ""), fg=hud.DIM)
        self.res = an.analyse(poses, fps, k, unit, kp.load(self.dir)["poses"])
        warn = any(line.startswith("!") for line in self.res["summary"])
        self.sum_lbl.configure(text="\n".join(self.res["summary"]), fg=hud.AMBER if warn else hud.TEXT)
        self.draw_graphs()
        self.fill_text()

    # ---- graphs: path, speed and angle
    def draw_graphs(self):
        c = self.graph
        c.delete("all")
        if not self.res:
            return
        j, a = self.joint.get(), self.angle.get()
        js = an.joint_series(self.poses, j, self.fps_now, self.k)
        ags = an.angle_series(self.poses, a, self.fps_now)
        pw, gap = (GW - 20 - 40) / 3, 20
        x0s = [10, 10 + pw + gap, 10 + 2 * (pw + gap)]
        self.panel_path(x0s[0], pw, js, j)
        self.panel_series(x0s[1], pw, [(r["frame"], r["speed"]) for r in js if r["speed"] is not None],
                          f"{j} speed ({self.u}/s)", "#ff8c00")
        self.panel_series(x0s[2], pw, [(r["frame"], r["angle"]) for r in ags], f"{a} angle (°)", "#22d3ee")

    def frame_box(self, x0, pw, title):
        c = self.graph
        y0, y1 = 20, GH - 8
        c.create_rectangle(x0, y0, x0 + pw, y1, outline=hud.LINE)
        c.create_text(x0 + 2, 3, text=title, anchor="nw", fill=hud.DIM, font=hud.SMALL)
        return y0, y1

    def panel_path(self, x0, pw, rows, j):
        c = self.graph
        y0, y1 = self.frame_box(x0, pw, f"{j} path (y down)")
        if len(rows) < 2:
            return
        xs, ys = [r["x"] for r in rows], [r["y"] for r in rows]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
        k = min(pw - 16, y1 - y0 - 16) / span
        cx, cy = x0 + pw / 2, (y0 + y1) / 2
        mx, my = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        pts = [(cx + (x - mx) * k, cy + (y - my) * k) for x, y in zip(xs, ys)]
        c.create_line(*[v for p in pts for v in p], fill="#ff8c00", width=2)
        for i, (px, py) in enumerate(pts):
            col = "#46c66f" if i == 0 else "#ff434b" if i == len(pts) - 1 else "#ebebee"
            c.create_oval(px - 2.5, py - 2.5, px + 2.5, py + 2.5, fill=col, outline="")
        c.create_text(x0 + pw - 4, y1 - 4, text="green start · red end", anchor="se", fill=hud.DIM, font=hud.TINY)

    def panel_series(self, x0, pw, pts, title, colour):
        c = self.graph
        y0, y1 = self.frame_box(x0, pw, title)
        if len(pts) < 2:
            return
        fs, vs = [p[0] for p in pts], [p[1] for p in pts]
        lo, hi = min(vs), max(vs)
        hi = hi if hi - lo > 1e-9 else lo + 1

        def tx(f):
            return x0 + 30 + (f - fs[0]) / max(fs[-1] - fs[0], 1) * (pw - 38)

        def ty(v):
            return y1 - 6 - (v - lo) / (hi - lo) * (y1 - y0 - 14)
        c.create_text(x0 + 3, ty(hi), text=f"{hi:.3g}", anchor="w", fill=hud.DIM, font=hud.TINY)
        c.create_text(x0 + 3, ty(lo), text=f"{lo:.3g}", anchor="w", fill=hud.DIM, font=hud.TINY)
        c.create_line(*[v for f, val in pts for v in (tx(f), ty(val))], fill=colour, width=2)
        for f, val in pts:
            c.create_oval(tx(f) - 2, ty(val) - 2, tx(f) + 2, ty(val) + 2, fill=colour, outline="")
        c.create_text(x0 + pw - 4, y1 - 4, text=f"frames {fs[0]}–{fs[-1]}", anchor="se", fill=hud.DIM,
                      font=hud.TINY)

    # ---- tables
    def fill_text(self):
        t, res, u = self.text, self.res, self.u
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("end", f"{'joint':<12}{'path':>10}{'net':>10}{'mean speed':>12}{'peak speed':>12}{' at':<6}"
                        f"{'peak accel':>12}{' at':<6}{'x range':>10}{'y range':>10}    ({u}, {u}/s, {u}/s²)\n", "head")
        fastest = max(res["joints"].values(), key=lambda s: s["peak_speed"][0])["peak_speed"][0] if res["joints"] else 0
        for j, s in res["joints"].items():
            line = (f"{j:<12}{s['path']:>10.2f}{s['net']:>10.2f}{s['mean_speed']:>12.2f}{s['peak_speed'][0]:>12.2f}"
                    f" f{str(s['peak_speed'][1]):<4}{s['peak_accel'][0]:>12.1f} f{str(s['peak_accel'][1]):<4}"
                    f"{s['x_range']:>10.2f}{s['y_range']:>10.2f}\n")
            t.insert("end", line, "hi" if s["peak_speed"][0] == fastest else ())
        t.insert("end", f"\n{'angle':<12}{'min':>8}{' at':<6}{'max':>8}{' at':<6}{'range':>8}{'turned':>9}"
                        f"{'peak °/s':>10}{' at':<6}\n", "head")
        for a, s in res["angles"].items():
            t.insert("end", f"{a:<12}{s['min'][0]:>7.0f}° f{str(s['min'][1]):<4}{s['max'][0]:>7.0f}° "
                            f"f{str(s['max'][1]):<4}{s['range']:>7.0f}°{s['total_turn']:>8.0f}°"
                            f"{s['peak_ang_speed'][0]:>10.0f} f{str(s['peak_ang_speed'][1]):<4}\n")
        tm = res["timing"]
        t.insert("end", f"\ntiming   {tm['frames']} frames · {tm['duration']:.3f} s at {tm['fps']:g} fps\n", "head")
        iv = tm["intervals"]
        if len(iv) <= 40:
            t.insert("end", "  between traced frames: " + ",  ".join(f"{a}→{b}: {n} fr {s:.3f}s"
                                                                     for a, b, n, s in iv) + "\n")
        if tm["pose_intervals"]:
            t.insert("end", "  between your key poses:\n")
            for a, la, b, lb, n, s in tm["pose_intervals"]:
                t.insert("end", f"    {la} (f{a}) → {lb} (f{b}): {n} frames, {s:.3f} s\n")
        else:
            t.insert("end", "  (no key poses marked yet: K in Review)\n", "head")
        b = res["body"]
        if b:
            t.insert("end", f"\nbody   hip travel {b['travel_x']:+.2f} {u} sideways, {b['travel_y']:+.2f} {u} up "
                            f"(+ = right / up), straight-line {b['travel']:.2f} {u}; rises {b['hip_rise']:.2f} {u} "
                            f"(frame {b['hip_rise_frame']}), drops {b['hip_drop']:.2f} {u}\n")
        for line in self.between_lines():   # Phase 11: distances to the other characters
            t.insert("end", line[0], line[1])
        t.configure(state="disabled")

    def between_lines(self):
        """Distances between this character and every other visible one, as traced, on every frame both are on."""
        import characters as chars
        if not self.frames_dir or not chars.is_multi(self.frames_dir):
            return []
        mine = trace_io.find_file(self.dir, trace_io.TRACE)
        if not mine:
            return []

        def every(path):
            P = {f: Q for f, Q in cmp.load_poses(path).items() if all(n in Q for n in an.ORDER)}
            return an.every_frame(P) if len(P) >= 2 else P
        A = every(mine)
        out = [("\nbetween characters   as traced, on every frame both are on (" + self.u + ")\n", "head")]
        here = os.path.normcase(os.path.normpath(self.dir))
        for c in chars.list_characters(self.frames_dir):
            if os.path.normcase(os.path.normpath(c["trace_dir"])) == here or not c["visible"]:
                continue
            t = trace_io.find_file(c["trace_dir"], trace_io.TRACE)
            r = an.between(A, every(t), self.k) if t else None
            if not r:
                out.append((f"  {c['name']}: no frame in common\n", ()))
                continue
            text = f"  {c['name']}: frames {r['first']}–{r['last']}"
            if r["hip_min"]:
                text += (f" · hips {r['hip_min'][0]:.2f}–{r['hip_max'][0]:.2f} apart (closest f{r['hip_min'][1]}, "
                         f"farthest f{r['hip_max'][1]})")
            if r["closest"]:
                d, f, ja, jb = r["closest"]
                text += f" · closest: {ja} to its {jb}, {d:.2f} at f{f}"
            out.append((text + "\n", ()))
        return out if len(out) > 1 else []

    # ---- actions
    def copy(self):
        if not self.res:
            return
        self.win.clipboard_clear()
        self.win.clipboard_append(an.report(f"Analytics: {os.path.basename(self.dir)} ({self.version.get()}, "
                                            f"{self.data.get()})", self.res, self.note.cget("text")))
        self.status.configure(text="Summary copied to the clipboard.", fg=hud.GREEN)

    def save_csv(self, path=None):
        if not self.res:
            return None
        if path is None:
            path = filedialog.asksaveasfilename(parent=self.win, defaultextension=".csv",
                                                initialfile=os.path.basename(self.dir) + "_analytics.csv",
                                                initialdir=self.dir, filetypes=[("CSV", "*.csv")])
        if not path:
            return None
        try:
            n = an.write_csv(path, self.poses, self.fps_now, self.k, self.u)
        except OSError as e:
            self.status.configure(text=f"Couldn't save: {e}", fg=hud.RED_HI)
            return None
        self.status.configure(text=f"Saved {n} rows to {path}", fg=hud.GREEN)
        return path

    def close(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close()

"""The Compare window of 03 PLAY / FIX (upgrade Phase 7). Opened with C or COMPARE… in the player.

Pick pose A and pose B (a version: your trace, the fixed trace or a dated backup, and a frame), see them side by side
and overlaid (A as a grey ghost, B in colour, a line from each joint of A to the same joint of B: green small, amber
medium, red big), with every joint's displacement, the joint angles, the body position and a short summary.
Read-only: nothing here changes any file. COPY REPORT puts the numbers on the clipboard.
"""
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

import compare as cmp
import hud

PW, PH = 320, 270           # one picture panel (small enough for the window to fit a 1080-px screen)
BG_RGB = (22, 22, 26)


class CompareDialog:
    def __init__(self, player):
        self.p = player
        self.cache = {}
        self.photos = []
        self.res = None
        self.vers = cmp.versions(player.tdir) + cmp.other_characters(player.dir, player.tdir)   # Phase 11
        self.win = w = tk.Toplevel(player.win.winfo_toplevel(), bg=hud.BG)
        w.title("Compare poses")
        w.transient(player.win.winfo_toplevel())
        w.resizable(False, False)
        w.protocol("WM_DELETE_WINDOW", self.close)
        P = dict(padx=14)
        hud.Header(w, "Compare poses").pack(fill="x", pady=(12, 2), **P)
        hud.label(w, "Two frames, or the same frame in two versions (your trace, the fixed trace, a backup). "
                     "Differences are in pixels and in bones (A's median bone length). Nothing is changed.",
                  fg=hud.DIM, font=hud.SMALL, anchor="w", justify="left", wraplength=3 * PW + 40).pack(
            fill="x", pady=(0, 8), **P)

        labels = [v[0] for v in self.vers]
        self.sel = {}
        for side in ("A", "B"):
            row = tk.Frame(w, bg=hud.BG)
            row.pack(fill="x", pady=2, **P)
            hud.label(row, side, font=(hud.F_SEMI, 13), fg=hud.TEXT if side == "A" else hud.AMBER, width=2).pack(
                side="left")
            vv = tk.StringVar(value=labels[0] if labels else "")
            vb = ttk.Combobox(row, textvariable=vv, values=labels, state="readonly", width=58)
            vb.pack(side="left", padx=(4, 8))
            hud.label(row, "frame", fg=hud.DIM, font=hud.SMALL).pack(side="left")
            fv = tk.StringVar()
            fb = ttk.Combobox(row, textvariable=fv, values=[], state="readonly", width=6)
            fb.pack(side="left", padx=(4, 0))
            vb.bind("<<ComboboxSelected>>", lambda e, s=side: self.version_changed(s))
            fb.bind("<<ComboboxSelected>>", lambda e: self.refresh())
            self.sel[side] = (vv, fv, fb)

        tools = tk.Frame(w, bg=hud.BG)
        tools.pack(fill="x", pady=(6, 0), **P)
        for text, cmd in (("This Frame vs Previous Key", lambda: self.preset_neighbour(-1)),
                          ("This Frame vs Next Key", lambda: self.preset_neighbour(1)),
                          ("Original vs Fixed (this frame)", self.preset_fixed), ("Swap A ⇄ B", self.swap)):
            hud.Button(tools, text, cmd, padx=8, font=hud.SMALL).pack(side="left", padx=(0, 4))
        opts = tk.Frame(w, bg=hud.BG)
        opts.pack(fill="x", pady=(6, 0), **P)
        hud.label(opts, "ALIGN", font=hud.BOLD).pack(side="left")
        self.align = tk.StringVar(value=cmp.ALIGN[0][1])
        ab = ttk.Combobox(opts, textvariable=self.align, values=[t for _, t in cmp.ALIGN], state="readonly",
                          width=32)
        ab.pack(side="left", padx=8)
        ab.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        self.pictures = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Reference pictures (your trace and its backups only)", variable=self.pictures,
                        command=self.refresh).pack(side="left", padx=(12, 0))

        self.canvas = tk.Canvas(w, width=3 * PW + 20, height=PH + 22, bg=hud.BG, highlightthickness=0)
        self.canvas.pack(pady=(10, 0), **P)
        self.sum_lbl = hud.label(w, "", fg=hud.TEXT, font=hud.SMALL, anchor="w", justify="left",
                                 wraplength=3 * PW + 20)
        self.sum_lbl.pack(fill="x", pady=(8, 0), **P)
        tf = tk.Frame(w, bg=hud.BG)
        tf.pack(fill="x", pady=(6, 0), **P)
        self.text = tk.Text(tf, height=11, width=118, font=(hud.MONO, 9), bg=hud.PANEL, fg=hud.TEXT, bd=0,
                            highlightthickness=1, highlightbackground=hud.LINE, wrap="none")
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="x", expand=True)
        for tag, col in (("small", "#46c66f"), ("medium", hud.AMBER), ("big", hud.RED_HI), ("head", hud.DIM)):
            self.text.tag_configure(tag, foreground=col)
        bar = tk.Frame(w, bg=hud.BG)
        bar.pack(fill="x", pady=12, **P)
        hud.Button(bar, "Close", self.close).pack(side="right", padx=(4, 0))
        hud.Button(bar, "Copy Report", self.copy).pack(side="right")
        self.status = hud.label(bar, "", fg=hud.GREEN, font=hud.SMALL, anchor="w")
        self.status.pack(side="left")
        w.bind("<Escape>", lambda e: self.close())
        self.preset_neighbour(1, quiet=True)

    # ---- versions and frames
    def version(self, side):
        label = self.sel[side][0].get()
        return next((v for v in self.vers if v[0] == label), None)

    def poses(self, side):
        v = self.version(side)
        if not v:
            return {}
        if v[1] not in self.cache:
            try:
                self.cache[v[1]] = cmp.load_poses(v[1])
            except (OSError, ValueError, KeyError, TypeError):
                self.cache[v[1]] = {}
        return self.cache[v[1]]

    def frames(self, side):
        return sorted(f for f, P in self.poses(side).items() if P)

    def version_changed(self, side, frame=None):
        vv, fv, fb = self.sel[side]
        fs = self.frames(side)
        fb.configure(values=[str(f) for f in fs])
        if frame is None:
            frame = int(fv.get()) if fv.get().isdigit() else None
        if fs:
            fv.set(str(frame if frame in fs else min(fs, key=lambda f: abs(f - (frame or fs[0])))))
        else:
            fv.set("")
        self.refresh()

    def set_side(self, side, label, frame):
        self.sel[side][0].set(label)
        self.version_changed(side, frame)

    def preset_neighbour(self, d, quiet=False):
        """A = your trace at the player's frame (or the nearest traced one), B = the key before / after it."""
        if not self.vers:
            return
        label = self.vers[0][0]
        self.sel["A"][0].set(label)
        fs = self.frames("A")
        if not fs:
            return
        cur = self.p.current_frame()
        a = min(fs, key=lambda f: abs(f - cur))
        k = fs.index(a)
        b = fs[min(len(fs) - 1, max(0, k + d))]
        if b == a and len(fs) > 1:
            b = fs[k - d] if 0 <= k - d < len(fs) else fs[0]
        self.set_side("A", label, a)
        self.set_side("B", label, b)
        if not quiet:
            self.status.configure(text=f"A = frame {a}, B = frame {b} of your trace.", fg=hud.GREEN)

    def preset_fixed(self):
        fixed = next((v for v in self.vers if v[2] == "fixed" and v[1].lower().endswith("trace_fixed.json")), None)
        if not fixed:
            self.status.configure(text="This move has no fixed trace yet (Save Fixed Trace in Review).",
                                  fg=hud.AMBER)
            return
        cur = self.p.current_frame()
        self.set_side("A", self.vers[0][0], cur)
        self.set_side("B", fixed[0], cur)
        self.align.set(cmp.ALIGN[1][1])          # the fix can move and resize the body: compare the shape
        self.refresh()
        self.status.configure(text="A = your trace, B = the fixed trace, same frame, hips together + same size.",
                              fg=hud.GREEN)

    def swap(self):
        (va, fa, _), (vb, fb, _) = self.sel["A"], self.sel["B"]
        a, b = (va.get(), fa.get()), (vb.get(), fb.get())
        self.set_side("A", b[0], int(b[1]) if b[1].isdigit() else None)
        self.set_side("B", a[0], int(a[1]) if a[1].isdigit() else None)

    def pose(self, side):
        f = self.sel[side][1].get()
        return self.poses(side).get(int(f), {}) if f.isdigit() else {}

    # ---- drawing and numbers
    def mode(self):
        return next(k for k, t in cmp.ALIGN if t == self.align.get())

    def refresh(self):
        A, B = self.pose("A"), self.pose("B")
        self.canvas.delete("all")
        self.photos = []
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if not A or not B:
            self.sum_lbl.configure(text="Pick a version and a frame for A and for B.")
            self.text.configure(state="disabled")
            self.res = None
            return
        self.res = res = cmp.compare(A, B, self.mode())
        fa, fb = int(self.sel["A"][1].get()), int(self.sel["B"][1].get())
        k = min(self.fit(A), self.fit(B), self.fit({**A, **{f"b{n}": p for n, p in res["aligned"].items()}}))
        self.panel(0, "A", A, fa, self.version("A"), k)
        self.panel(1, "B", B, fb, self.version("B"), k)
        self.overlay(2, A, res, fa, k)
        lines = res["summary"]
        short = lines[:4] + ([f"… {len(lines) - 4} more line(s) at the top of the table below."]
                             if len(lines) > 4 else [])
        self.sum_lbl.configure(text="\n".join(short))
        self.fill_text(res)

    def fit(self, P):
        xs, ys = [p[0] for p in P.values()], [p[1] for p in P.values()]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        return min((PW - 60) / max(w, 1), (PH - 60) / max(h, 1))

    def frame_layer(self, P, f, version, k):
        """The panel background and the mapping frame px -> panel px, centred on P at zoom k."""
        xs, ys = [p[0] for p in P.values()], [p[1] for p in P.values()]
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        ox, oy = PW / 2 - cx * k, PH / 2 - cy * k
        img = Image.new("RGB", (PW, PH), BG_RGB)
        if self.pictures.get() and version and version[2] == "trace":
            src = self.p.frame_image(f)
            if src is not None:
                ref = src.transform((PW, PH), Image.AFFINE, (1 / k, 0, -ox / k, 0, 1 / k, -oy / k),
                                    resample=Image.BILINEAR, fillcolor=BG_RGB)
                img = Image.blend(img, ref, 0.55)
        return img, (lambda x, y: (x * k + ox, y * k + oy))

    def put(self, col, img, title, colour):
        x0 = col * (PW + 10)
        ph = ImageTk.PhotoImage(img)
        self.photos.append(ph)
        self.canvas.create_text(x0 + 4, 2, text=title, anchor="nw", fill=colour, font=hud.SMALL)
        self.canvas.create_image(x0, 20, image=ph, anchor="nw")
        self.canvas.create_rectangle(x0, 20, x0 + PW, 20 + PH, outline=hud.LINE)

    def panel(self, col, side, P, f, version, k):
        img, to = self.frame_layer(P, f, version, k)
        cmp.draw_pose(img, P, to)
        name = version[0].split(" (")[0] if version else ""
        self.put(col, img, f"{side}: frame {f}  ·  {name}", hud.TEXT if side == "A" else hud.AMBER)

    def overlay(self, col, A, res, fa, k):
        both = {**A, **{"_" + n: p for n, p in res["aligned"].items()}}
        img, to = self.frame_layer(both, fa, self.version("A"), k)
        cmp.draw_pose(img, A, to, ghost=True)
        cmp.draw_pose(img, res["aligned"], to)
        cmp.draw_diffs(img, res, to)
        d = ImageDraw.Draw(img)
        d.text((6, PH - 16), "grey = A   colour = B   lines: green / amber / red = small / medium / big",
               fill=(200, 200, 205))
        self.put(col, img, "A and B together  ·  " + self.align.get().split(" (")[0], hud.TEXT)

    def fill_text(self, res):
        t = self.text
        t.insert("end", "summary\n", "head")
        for line in res["summary"]:
            t.insert("end", "  " + line + "\n")
        t.insert("end", "\n")
        t.insert("end", f"{'joint':<12}{'A x, y':>16}{'B x, y':>16}{'dx':>9}{'dy':>9}{'distance':>11}{'bones':>8}\n",
                 "head")
        for n, j in res["joints"].items():
            line = (f"{n:<12}{j['a'][0]:>8.1f},{j['a'][1]:>7.1f}{j['b'][0]:>8.1f},{j['b'][1]:>7.1f}"
                    f"{j['dx']:>+9.1f}{j['dy']:>+9.1f}{j['dist']:>9.1f}px{j['bones']:>8.2f}  {j['level']}\n")
            t.insert("end", line, j["level"])
        if res["angles"]:
            t.insert("end", f"\n{'angle':<12}{'A':>8}{'B':>8}{'change':>9}\n", "head")
            for name, (a, b, d) in res["angles"].items():
                lvl = "big" if abs(d) >= 30 else "medium" if abs(d) >= 15 else "small"
                t.insert("end", f"{name:<12}{a:>7.0f}°{b:>7.0f}°{d:>+8.0f}°\n", lvl)
        body = res["body"]
        t.insert("end", "\nbody position\n", "head")
        if "hip moved" in body:
            t.insert("end", f"  hip moved on screen   {body['hip moved'][0]:.1f} px ({body['hip moved'][1]:.2f} bones)\n")
        if "torso lean" in body:
            a, b, d = body["torso lean"]
            t.insert("end", f"  torso lean            {a:+.0f}° → {b:+.0f}°  ({d:+.0f}°, + = to the right)\n")
        if "height" in body:
            a, b, r = body["height"]
            t.insert("end", f"  height head → foot    {a:.0f} → {b:.0f} px  ({r:.2f}×)\n")
        a, b, r = body["body size (median bone)"]
        t.insert("end", f"  body size (median bone) {a:.1f} → {b:.1f} px  ({r:.2f}×)\n")
        if "stance width" in body:
            a, b = body["stance width"]
            t.insert("end", f"  stance width          {a:.0f} → {b:.0f} px\n")
        t.configure(state="disabled")

    def copy(self):
        if not self.res:
            return
        name_a = f"{self.sel['A'][0].get()}, frame {self.sel['A'][1].get()}"
        name_b = f"{self.sel['B'][0].get()}, frame {self.sel['B'][1].get()}"
        self.win.clipboard_clear()
        self.win.clipboard_append(cmp.report(name_a, name_b, self.res))
        self.status.configure(text="Report copied to the clipboard.", fg=hud.GREEN)

    def close(self):
        self.p.cmp_dialog = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass

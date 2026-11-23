"""SPRITE SHEET… (v3.0): the Sprite Sheet Export window, opened from 02 TRACE and 05 ANIMATE.
Pick the animation and characters, set the layout, watch the preview, export PNG + JSON. Sources are only read."""
import os
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox

from PIL import Image, ImageTk

import hud
import spritesheet as S

NUMS = [("columns", "Columns"), ("rows", "Rows (0 = as needed)"), ("per_sheet", "Frames per sheet (0 = all)"),
        ("spacing_x", "Spacing X"), ("spacing_y", "Spacing Y"), ("padding", "Outer padding"),
        ("height", "Render height (Trace)"), ("scale", "Scale"), ("frame_w", "Frame width (0 = auto)"),
        ("frame_h", "Frame height (0 = auto)")]
FLAGS = [("in_place", "In place (the hip stays put; jumps kept)"), ("trim", "Trim empty space (same for every frame)"),
         ("transparent", "Transparent background"), ("combine", "Combine the ticked characters into One sheet"),
         ("free_layers", "Include free drawing layers (Animate: background, effects)"),
         ("fixed", "Use the fixed trace where there is one (Trace)"), ("metadata", "Write the JSON metadata file")]


class SpriteSheetDialog:
    def __init__(self, root, images, kind=None, path=None):
        self.root, self.images = root, images
        self.s = dict(S.DEFAULTS)
        self.src = None
        self.pending = None
        self.photo = None
        w = self.win = tk.Toplevel(root, bg=hud.BG)
        w.title("Sprite Sheet Export")
        w.geometry("1280x820")
        w.transient(root)
        left = hud.panel(w, padx=12, pady=10)
        left.pack(side="left", fill="y", padx=(10, 6), pady=10)
        hud.tag(left, "Sprite sheet", bg=hud.PANEL).pack(anchor="w")
        self.sources = S.sources(images)
        labels = [f"{'ANIMATE' if k == 'animate' else 'TRACE'} · {os.path.basename(p)}" for k, p in self.sources]
        self.v_src = tk.StringVar(w)
        om = tk.OptionMenu(left, self.v_src, *(labels or ["(no finished animations)"]),
                           command=lambda v: self.load_source())
        om.configure(bg=hud.FIELD, fg=hud.TEXT, highlightthickness=0, relief="flat", font=hud.SMALL, width=34)
        om.pack(fill="x", pady=(6, 4))
        self.labels = labels
        hud.label(left, "Characters", bg=hud.PANEL, fg=hud.DIM, font=hud.TINY).pack(anchor="w")
        self.char_box = tk.Frame(left, bg=hud.PANEL)
        self.char_box.pack(fill="x")
        self.cvars = {}
        self.vars = {}
        for key, text in (("frames", "Frames (empty = all, e.g. 1-12, 20)"),
                          ("sequences", "Sequences (e.g. run: 1-32; slash: 33-50)")):
            hud.label(left, text, bg=hud.PANEL, fg=hud.DIM, font=hud.TINY).pack(anchor="w", pady=(6, 0))
            self.vars[key] = tk.StringVar(w, value=self.s[key])
            e = tk.Entry(left, textvariable=self.vars[key], bg=hud.FIELD, fg=hud.TEXT, insertbackground=hud.TEXT,
                         relief="flat", font=hud.SMALL)
            e.pack(fill="x", ipady=2)
        hud.label(left, "Layout", bg=hud.PANEL, fg=hud.DIM, font=hud.TINY).pack(anchor="w", pady=(6, 0))
        lay = tk.Frame(left, bg=hud.PANEL)
        lay.pack(fill="x")
        self.vars["layout"] = tk.StringVar(w, value=self.s["layout"])
        for v in S.LAYOUTS:
            tk.Radiobutton(lay, text=v, value=v, variable=self.vars["layout"], command=self.changed, bg=hud.PANEL,
                           fg=hud.TEXT, selectcolor=hud.FIELD, activebackground=hud.PANEL,
                           font=hud.SMALL).pack(side="left")
        g = tk.Frame(left, bg=hud.PANEL)
        g.pack(fill="x", pady=(4, 0))
        for i, (key, text) in enumerate(NUMS):
            hud.label(g, text, bg=hud.PANEL, fg=hud.DIM, font=hud.TINY).grid(row=i, column=0, sticky="w")
            self.vars[key] = tk.StringVar(w, value=str(self.s[key]))
            tk.Entry(g, textvariable=self.vars[key], width=7, bg=hud.FIELD, fg=hud.TEXT, insertbackground=hud.TEXT,
                     relief="flat", font=hud.SMALL).grid(row=i, column=1, sticky="w", pady=1)
        for key, text in FLAGS:
            self.vars[key] = tk.BooleanVar(w, value=self.s[key])
            tk.Checkbutton(left, text=text, variable=self.vars[key], command=self.changed, bg=hud.PANEL,
                           fg=hud.TEXT, selectcolor=hud.FIELD, activebackground=hud.PANEL, font=hud.SMALL,
                           anchor="w").pack(fill="x")
        row = tk.Frame(left, bg=hud.PANEL)
        row.pack(fill="x", pady=(2, 0))
        hud.label(row, "Solid colour", bg=hud.PANEL, fg=hud.DIM, font=hud.TINY).pack(side="left")
        self.swatch = tk.Label(row, text="    ", bg=self.s["colour"], cursor="hand2")
        self.swatch.pack(side="left", padx=6)
        self.swatch.bind("<Button-1>", lambda e: self.pick_colour())
        hud.label(left, "Save in", bg=hud.PANEL, fg=hud.DIM, font=hud.TINY).pack(anchor="w", pady=(8, 0))
        dr = tk.Frame(left, bg=hud.PANEL)
        dr.pack(fill="x")
        self.v_dest = tk.StringVar(w, value="")
        tk.Entry(dr, textvariable=self.v_dest, bg=hud.FIELD, fg=hud.TEXT, insertbackground=hud.TEXT, relief="flat",
                 font=hud.TINY).pack(side="left", fill="x", expand=True, ipady=2)
        hud.Button(dr, "Browse…", self.browse, padx=6, pady=1, font=hud.TINY).pack(side="left", padx=(4, 0))
        hud.Button(left, "Export Sprite Sheets", self.export, kind="red").pack(fill="x", pady=(10, 0))
        right = tk.Frame(w, bg=hud.BG)
        right.pack(side="left", fill="both", expand=True, padx=(0, 10), pady=10)
        self.info = hud.label(right, "", fg=hud.DIM, font=hud.SMALL, justify="left", anchor="w")
        self.info.pack(fill="x")
        self.canvas = tk.Canvas(right, bg="#2a2a30", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=(6, 0))
        self.canvas.bind("<Configure>", lambda e: self.changed())
        for v in self.vars.values():
            if isinstance(v, tk.StringVar):
                v.trace_add("write", lambda *a: self.changed())
        pick = 0
        for i, (k, p) in enumerate(self.sources):
            if kind == k and path and os.path.normcase(os.path.normpath(p)) == os.path.normcase(os.path.normpath(path)):
                pick = i
        if labels:
            self.v_src.set(labels[pick])
            self.load_source()

    # ---- state
    def settings(self):
        s = dict(S.DEFAULTS)
        for k, v in self.vars.items():
            val = v.get()
            if k in dict(NUMS):
                try:
                    val = float(val) if k == "scale" else int(float(val))
                except ValueError:
                    raise S.SheetError(f"{dict(NUMS)[k]} must be a number.")
                if val < 0 or (k == "scale" and val <= 0):
                    raise S.SheetError(f"{dict(NUMS)[k]} can't be below zero.")
            s[k] = val
        s["colour"] = self.s["colour"]
        return s

    def char_ids(self):
        return [cid for cid, v in self.cvars.items() if v.get()]

    def load_source(self):
        if self.v_src.get() not in self.labels:
            return
        kind, path = self.sources[self.labels.index(self.v_src.get())]
        try:
            self.src = S.Source(kind, path, fixed=self.vars["fixed"].get())
        except Exception as e:   # a broken or unfinished animation: say why, keep the window
            self.src = None
            self.info.configure(text=f"Can't use it: {e}", fg=hud.AMBER)
            return
        for w in self.char_box.winfo_children():
            w.destroy()
        self.cvars = {}
        for cid, name in self.src.characters:
            v = tk.BooleanVar(self.win, value=True)
            self.cvars[cid] = v
            tk.Checkbutton(self.char_box, text=name, variable=v, command=self.changed, bg=hud.PANEL, fg=hud.TEXT,
                           selectcolor=hud.FIELD, activebackground=hud.PANEL, font=hud.SMALL,
                           anchor="w").pack(fill="x")
        self.v_dest.set(S.default_dest(self.images, self.src))
        self.changed()

    def changed(self):
        if self.pending:
            self.win.after_cancel(self.pending)
        self.pending = self.win.after(250, self.preview)

    # ---- preview
    def preview(self):
        self.pending = None
        c = self.canvas
        c.delete("all")
        if not self.src:
            return
        if self.src.kind == "trace" and self.src.fixed != self.vars["fixed"].get():
            return self.load_source()
        try:
            s = self.settings()
            js = S.jobs(self.src, s, self.char_ids())
            sheets, meta = S.make(self.src, js[0], s)
        except S.SheetError as e:
            self.info.configure(text=str(e), fg=hud.AMBER)
            return
        sheet = sheets[0]
        W, H = max(10, c.winfo_width()), max(10, c.winfo_height())
        z = min(1.0, (W - 20) / sheet.width, (H - 20) / sheet.height)
        view = sheet.resize((max(1, int(sheet.width * z)), max(1, int(sheet.height * z))), Image.LANCZOS)
        board = Image.new("RGBA", view.size, (255, 255, 255, 255))
        sq = 10
        for y in range(0, view.height, sq):
            for x in range((y // sq % 2) * sq, view.width, 2 * sq):
                board.paste((214, 214, 214, 255), (x, y, x + sq, y + sq))
        board.alpha_composite(view)
        self.photo = ImageTk.PhotoImage(board)
        c.create_image(W / 2, H / 2, image=self.photo)
        sh = meta["sheets"][0]
        files = len(js) * len(sheets)
        self.info.configure(fg=hud.DIM, text=(
            f"{len(js)} sprite sheet set{'s' if len(js) > 1 else ''} ({', '.join(j['character'] + ' · ' + j['sequence'] for j in js[:4])}"
            f"{' …' if len(js) > 4 else ''})   ·   preview: {js[0]['character']} · {js[0]['sequence']}, sheet 1 of "
            f"{len(sheets)}\n{sh['width']} × {sh['height']} px   ·   {sh['columns']} × {sh['rows']} grid   ·   "
            f"frames {meta['frame_width']} × {meta['frame_height']} px   ·   {meta['frame_count']} frames at "
            f"{meta['fps']:g} fps ({meta['frame_duration_ms']:g} ms each)   ·   about {files} PNG file"
            f"{'s' if files > 1 else ''}"))

    # ---- actions
    def pick_colour(self):
        col = colorchooser.askcolor(self.s["colour"], parent=self.win)[1]
        if col:
            self.s["colour"] = col
            self.swatch.configure(bg=col)
            self.changed()

    def browse(self):
        d = filedialog.askdirectory(parent=self.win, title="Save the sprite sheets in…")
        if d:
            self.v_dest.set(os.path.normpath(d))

    def export(self):
        if not self.src:
            return None
        try:
            out = S.run(self.src, self.settings(), self.char_ids(), self.v_dest.get().strip())
        except (S.SheetError, OSError) as e:
            messagebox.showinfo("Sprite sheets", f"Nothing was exported: {e}", parent=self.win)
            return None
        messagebox.showinfo("Sprite sheets", f"Saved {len(out)} file(s) in\n{os.path.dirname(out[0])}\n\n"
                            + "\n".join(os.path.basename(p) for p in out[:12]) + ("\n…" if len(out) > 12 else ""),
                            parent=self.win)
        self.v_dest.set(S.default_dest(self.images, self.src))   # the next export goes into a new folder
        return out

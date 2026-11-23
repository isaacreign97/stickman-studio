"""GROUP… (M) in 02 TRACE (Stickman Studio Multi-Character Support, Phase 11): transform several characters together.

The selected characters (Ctrl+click their chips; A selects every visible one) that are visible and unlocked are
changed together, with exactly the same transformation of every joint, so their positions relative to each other are
kept (for a move) or change the same way for everyone (scale, flip, rotate):

    Move      x += dx, y += dy                                   (frame pixels)
    Scale     p = c + k (p - c)                                  about the group's centre, or each character's own hip
    Flip      x = 2 cx - x                                       about the group's centre; joint names stay the same
    Rotate    p = c + R(angle) (p - c)                           about the group's centre, clockwise on screen

The group's centre on a frame = the mean of the selected characters' hips there. Scope: this frame, the key frames
from A to B, or every key frame (each character only on its own key frames). Plain coordinate maths, no AI.
A cyan preview shows the result on this frame; APPLY backs up every changed character first ("group") and is ONE
undo step across all of them. Points pushed outside the picture become guesses, as when you drag them there.
"""
import math
import tkinter as tk

import hud

KINDS = [("move", "Move"), ("scale", "Scale"), ("flip", "Flip horizontally"), ("rotate", "Rotate")]
SCOPES = [("this", "This frame"), ("range", "Key frames"), ("all", "Every key frame")]


def centre(poses):
    """The group centre of {char id: {joint: (x, y)}}: the mean of the hips (or of every point without hips)."""
    hips = [P["hip"] for P in poses.values() if "hip" in P]
    pts = hips or [p for P in poses.values() for p in P.values()]
    if not pts:
        return 0.0, 0.0
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def transform(P, kind, value, c):
    """One pose {joint: (x, y)} moved / scaled / flipped / rotated about c = (cx, cy). value: (dx, dy) for move,
    a factor for scale (1.2 = 20 % bigger), degrees (clockwise on screen) for rotate; unused for flip."""
    cx, cy = c
    out = {}
    if kind == "rotate":
        a = math.radians(value)
        ca, sa = math.cos(a), math.sin(a)
    for n, (x, y) in P.items():
        if kind == "move":
            out[n] = (x + value[0], y + value[1])
        elif kind == "scale":
            out[n] = (cx + value * (x - cx), cy + value * (y - cy))
        elif kind == "flip":
            out[n] = (2 * cx - x, y)
        elif kind == "rotate":   # y points down on screen, so this turns clockwise for a positive angle
            dx, dy = x - cx, y - cy
            out[n] = (cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)
        else:
            raise ValueError(f"unknown transformation {kind}")
    return out


def apply_to_frame(poses, kind, value, about="group"):
    """Every character's pose on one frame transformed together. poses = {char id: {joint: (x, y)}}."""
    c = centre(poses)
    return {cid: transform(P, kind, value, c if about == "group" or kind != "scale" else P.get("hip", c))
            for cid, P in poses.items()}


class GroupDialog:
    """Non-modal, like SMOOTH: you can change frames while it's open; the cyan preview follows."""

    def __init__(self, app):
        self.app = app
        self.win = w = tk.Toplevel(app.root, bg=hud.BG)
        w.title("Group: move characters together")
        w.transient(app.root)
        w.resizable(False, False)
        w.protocol("WM_DELETE_WINDOW", self.close)
        w.bind("<Escape>", lambda e: self.close())
        P = dict(padx=14)
        hud.Header(w, "Move characters together").pack(fill="x", pady=(12, 4), **P)
        hud.label(w, "The selected characters (Ctrl+click their chips, A = every visible one) change together, with "
                     "exactly the same maths for every joint. Hidden or locked characters are left out. One undo step; "
                     "every changed character is backed up first.", fg=hud.DIM, font=hud.SMALL, anchor="w",
                  justify="left", wraplength=600).pack(fill="x", pady=(0, 6), **P)
        self.who = hud.label(w, "", fg=hud.AMBER, font=hud.SMALL, anchor="w", justify="left", wraplength=560)
        self.who.pack(fill="x", **P)
        self.kind = tk.StringVar(w, "move")
        self.scope = tk.StringVar(w, "this")
        self.about = tk.StringVar(w, "group")
        self.vals = {k: tk.StringVar(w, v) for k, v in (("dx", "0"), ("dy", "0"), ("scale", "100"), ("angle", "0"),
                                                         ("from", ""), ("to", ""))}
        g = tk.Frame(w, bg=hud.BG)
        g.pack(fill="x", pady=8, **P)

        def radio(parent, var, value, text):
            return tk.Radiobutton(parent, text=text, variable=var, value=value, command=self.changed, bg=hud.BG,
                                  fg=hud.TEXT, selectcolor=hud.FIELD, activebackground=hud.BG,
                                  activeforeground=hud.TEXT, font=hud.SMALL, anchor="w")

        def entry(parent, key, width=6):
            e = tk.Entry(parent, textvariable=self.vals[key], width=width, bg=hud.FIELD, fg=hud.TEXT,
                         insertbackground=hud.TEXT, font=hud.SMALL, relief="flat")
            e.bind("<KeyRelease>", lambda ev: self.changed())
            return e

        rows = [("move", [("dx", "x"), ("dy", "y")], "px (+x right, +y down)"),
                ("scale", [("scale", "")], "% of the size now"),
                ("flip", [], "mirror left-right about the group's centre (front stays front)"),
                ("rotate", [("angle", "")], "degrees, clockwise on screen, about the group's centre")]
        for r, (k, fields, unit) in enumerate(rows):
            radio(g, self.kind, k, dict(KINDS)[k]).grid(row=r, column=0, sticky="w")
            f = tk.Frame(g, bg=hud.BG)
            f.grid(row=r, column=1, sticky="w", padx=(10, 0))
            for key, lab in fields:
                if lab:
                    hud.label(f, lab, fg=hud.DIM, font=hud.SMALL).pack(side="left", padx=(0, 3))
                entry(f, key).pack(side="left", padx=(0, 8))
            hud.label(f, unit, fg=hud.FAINT, font=hud.SMALL).pack(side="left")
        ab = tk.Frame(w, bg=hud.BG)
        ab.pack(fill="x", **P)
        hud.label(ab, "Scale About", fg=hud.DIM, font=hud.TINY).pack(side="left", padx=(0, 8))
        radio(ab, self.about, "group", "the group's centre").pack(side="left")
        radio(ab, self.about, "own", "each character's own hip").pack(side="left")
        sc = tk.Frame(w, bg=hud.BG)
        sc.pack(fill="x", pady=(8, 0), **P)
        hud.label(sc, "ON", fg=hud.DIM, font=hud.TINY).pack(side="left", padx=(0, 8))
        for k, text in SCOPES:
            radio(sc, self.scope, k, text).pack(side="left")
            if k == "range":
                hud.label(sc, "from", fg=hud.DIM, font=hud.SMALL).pack(side="left", padx=(0, 3))
                entry(sc, "from", 4).pack(side="left")
                hud.label(sc, "to", fg=hud.DIM, font=hud.SMALL).pack(side="left", padx=3)
                entry(sc, "to", 4).pack(side="left", padx=(0, 10))
        self.msg = hud.label(w, "", fg=hud.DIM, font=hud.SMALL, anchor="w", justify="left", wraplength=560)
        self.msg.pack(fill="x", pady=(10, 0), **P)
        bar = tk.Frame(w, bg=hud.BG)
        bar.pack(fill="x", pady=12, **P)
        hud.Button(bar, "Close", self.close).pack(side="right", padx=(4, 0))
        self.go_btn = hud.Button(bar, "Apply", self.apply, kind="red")
        self.go_btn.pack(side="right")
        self.changed()
        try:   # low on the screen, so it doesn't cover the figures (usually in the middle or top of the frame)
            w.update_idletasks()
            top = app.root.winfo_toplevel()
            x = top.winfo_rootx() + 30
            y = max(0, top.winfo_rooty() + top.winfo_height() - w.winfo_reqheight() - 60)
            w.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    def params(self):
        """-> (kind, value, about, scope, frm, to). Raises ValueError for a number that isn't one."""
        k = self.kind.get()
        v = self.vals
        if k == "move":
            value = (float(v["dx"].get() or 0), float(v["dy"].get() or 0))
        elif k == "scale":
            pc = float(v["scale"].get() or 100)
            if pc <= 0:
                raise ValueError("The size must be more than 0 %.")
            value = pc / 100.0
        elif k == "rotate":
            value = float(v["angle"].get() or 0)
        else:
            value = None
        frm = to = None
        if self.scope.get() == "range":
            frm, to = int(v["from"].get()), int(v["to"].get())
        return k, value, self.about.get(), self.scope.get(), frm, to

    def changed(self):
        members, left = self.app.group_members()
        names = [self.app.char(c)["name"] for c in members]
        self.who.configure(text=(f"Together: {', '.join(names)}." if names else "No character to change on this "
                                 "frame: select some (Ctrl+click chips, A for all).")
                           + (f"  Left out: {', '.join(left)}." if left else ""))
        try:
            kind, value, about, scope, frm, to = self.params()
        except ValueError as e:
            self.app.group_preview = None
            self.msg.configure(text=f"{e}" if str(e).startswith("The") else "Type plain numbers.", fg=hud.RED_HI)
            self.go_btn.configure(state="disabled")
            self.app.draw_overlay()
            return
        self.app.group_preview = self.app.group_result(kind, value, about) if members else None
        self.go_btn.configure(state="normal" if members else "disabled")
        self.msg.configure(text="Cyan: the result on this frame." if members else "", fg=hud.DIM)
        self.app.draw_overlay()

    def apply(self):
        try:
            kind, value, about, scope, frm, to = self.params()
        except ValueError as e:
            self.msg.configure(text=f"Nothing was changed: {e}", fg=hud.RED_HI)
            return None
        done = self.app.apply_group(kind, value, about, scope, frm, to)
        if done:
            self.msg.configure(text=f"Done: {done}. Ctrl+Z undoes it in one step.", fg=hud.GREEN)
        self.changed()
        return done

    def close(self):
        self.app.group_preview = None
        self.app.group_dlg = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.app.draw_overlay()

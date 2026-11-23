"""The History window of 02 TRACE (U) (Stickman Studio upgrade, Phase 9).

Lists every undo step of the trace, newest at the top, with its time, what it was and the frames it changed. Steps
you undid are shown greyed above "NOW" (Ctrl+Y redoes them). Picking a step shows its key frame as it was before that
step (grey) against how it is now (colour), with an amber line for every joint that has moved since.
GO BACK undoes everything down to and including the chosen step; REDO UP TO redoes the greyed steps down to the chosen
one. Both are ordinary undo / redo steps, so nothing is lost. The steps are saved in trace_history.json (history.py),
so they are still here after a restart. Below the steps is the move's log: editing sessions, checkpoints, restores,
copies and project backups.
"""
import math
import os
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

import history
import hud
import trace_io
from restore_dialog import chain_colour, frame_image

PAD = 60   # frame pixels around the frame, for joints placed outside it


class HistoryDialog:
    def __init__(self, app):
        self.app = app
        self.rows = []         # listbox row -> ("redo", index in app.redo) | ("now", None) | ("undo", index in app.undo)
        self.photo = None
        self.job = None
        self.win = w = tk.Toplevel(app.root, bg=hud.BG)
        w.title(f"History: {os.path.basename(os.path.normpath(app.dir))}")
        w.geometry("1060x680")
        w.minsize(860, 520)
        w.transient(app.root)
        w.protocol("WM_DELETE_WINDOW", self.close)
        w.bind("<Escape>", lambda e: self.close())
        w.bind("<Control-z>", lambda e: (app.do_undo(), self.refresh()))
        w.bind("<Control-y>", lambda e: (app.do_redo(), self.refresh()))

        head = tk.Frame(w, bg=hud.BG)
        head.pack(fill="x", padx=12, pady=(12, 6))
        hud.Header(head, "Trace history", "Every change, newest at the top. Grey steps were undone (Ctrl+Y redoes "
                   "them). Pick a step to see its frame before that step (grey) against now (colour). Go Back undoes "
                   "everything down to and including it, as ordinary undo steps, so Ctrl+Y brings them back. The steps "
                   "are saved with the move, so they survive a restart.").pack(fill="x")

        body = tk.Frame(w, bg=hud.BG)
        body.pack(fill="both", expand=True, padx=12)
        left = hud.panel(body, width=470)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        hud.label(left, "Undo Steps", bg=hud.PANEL, fg=hud.DIM, font=hud.TINY, anchor="w").pack(fill="x", padx=8,
                                                                                               pady=(6, 0))
        self.listbox = tk.Listbox(left, bg=hud.PANEL, fg=hud.TEXT, selectbackground=hud.RED,
                                  selectforeground="#ffffff", font=hud.SMALL, activestyle="none",
                                  highlightthickness=0, bd=0, exportselection=False)
        self.listbox.pack(fill="both", expand=True, padx=6, pady=(2, 6))
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.show())
        self.listbox.bind("<Double-Button-1>", lambda e: self.act())
        hud.label(left, "Log of This Move", bg=hud.PANEL, fg=hud.DIM, font=hud.TINY, anchor="w").pack(fill="x", padx=8)
        self.log = tk.Listbox(left, bg=hud.PANEL, fg=hud.DIM, font=hud.SMALL, height=7, activestyle="none",
                              highlightthickness=0, bd=0, exportselection=False, selectbackground=hud.PANEL2)
        self.log.pack(fill="x", padx=6, pady=(2, 6))

        right = tk.Frame(body, bg=hud.BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.stage = tk.Canvas(right, bg="#16161a", highlightthickness=0)
        self.stage.pack(fill="both", expand=True)
        self.stage.bind("<Configure>", lambda e: self.show())
        self.info = hud.label(right, "", fg=hud.DIM, font=hud.SMALL, anchor="w", justify="left")
        self.info.pack(fill="x", pady=(6, 0))
        hud.wrap_to_width(self.info)

        bar = tk.Frame(w, bg=hud.BG)
        bar.pack(fill="x", padx=12, pady=10)
        hud.Button(bar, "Close", self.close).pack(side="right", padx=(4, 0))   # buttons first: a long message
        self.act_btn = hud.Button(bar, "Go Back to Before This Step", self.act, kind="red")   # can't hide them
        self.act_btn.pack(side="right", padx=(4, 0))
        hud.Button(bar, "Save Checkpoint…", self.checkpoint).pack(side="right", padx=(4, 0))
        self.msg = hud.label(bar, "", fg=hud.DIM, font=hud.SMALL, anchor="w")
        self.msg.pack(side="left", fill="x", expand=True)
        app.flush_history()   # so the log already shows this session
        self.refresh(now=True)
        w.focus_set()

    # ---- the lists
    def refresh(self, now=False):
        """Rebuild the lists (soon, not on every mouse event, unless now=True)."""
        if not now:
            if self.job is None:
                self.job = self.win.after(120, lambda: self.refresh(now=True))
            return
        if self.job is not None:   # refreshing now: drop the one that was waiting
            try:
                self.win.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None
        if not self.win.winfo_exists():
            return
        a = self.app
        keep = self.current_key()
        lb = self.listbox
        lb.delete(0, "end")
        self.rows = []
        for r, step in enumerate(a.redo):           # the furthest undone step first
            lb.insert("end", "  ↷ undone   " + self.step_text(step))
            lb.itemconfigure("end", fg=hud.FAINT)
            self.rows.append(("redo", r))
        lb.insert("end", f"  ━━━━━━━━  Now  ·  {len(a.undo)} step{'s' if len(a.undo) != 1 else ''} to undo"
                         f"{f'  ·  {len(a.redo)} to redo' if a.redo else ''}  ━━━━━━━━")
        lb.itemconfigure("end", fg=hud.RED_HI)
        self.rows.append(("now", None))
        for j in range(len(a.undo) - 1, -1, -1):    # newest first
            lb.insert("end", "  " + self.step_text(a.undo[j]))
            self.rows.append(("undo", j))
        pick = self.rows.index(keep) if keep in self.rows else self.rows.index(("now", None))
        lb.selection_clear(0, "end")
        lb.selection_set(pick)
        lb.see(pick)
        self.log.delete(0, "end")
        evs = history.events(a.dir)
        for e in evs[:200]:
            self.log.insert("end", f"  {history.when(float(e.get('time') or 0))}   {e.get('text') or e.get('what')}")
        if not evs:
            self.log.insert("end", "  Nothing logged yet.")
        self.show()

    def step_text(self, step):
        i, snap, label, t = step[:4]
        who = ""
        if len(step) > 4 and getattr(self.app, "cast", None):   # Phase 11: whose step
            who = self.app.char(step[4])["name"] + (" + " + ", ".join(self.app.char(c)["name"] for c in step[5])
                                                    if step[5] else "") + ":  "
        return f"{history.when(t) if t else '—':>14}   {who}{label}   ·  {history.frames_text(snap)}"

    def current_key(self):
        sel = self.listbox.curselection()
        if sel and sel[0] < len(self.rows):
            return self.rows[sel[0]]
        return None

    def selected_step(self):
        k = self.current_key()
        if not k or k[0] == "now":
            return k, None
        try:
            return k, (self.app.redo if k[0] == "redo" else self.app.undo)[k[1]]
        except IndexError:
            return None, None

    # ---- the preview: the step's frame then (grey) and now (colour)
    def show(self):
        c = self.stage
        a = self.app
        k, step = self.selected_step()
        if not k:
            return
        if k[0] == "now":
            f, then, what = a.frame(), None, "Now"
            self.act_btn.configure(text="Go Back to Before This Step", state="disabled")
            self.info.configure(text=f"This is where you are now. {len(a.undo)} step(s) can be undone"
                                     + (f" and {len(a.redo)} redone." if a.redo else "."))
        else:
            i, snap, label, t = step[:4]
            owner = step[4] if len(step) > 4 else None
            frames, states = a.frames_of(owner), a.states_of(owner)   # Phase 11: the step's own character
            f = frames[i] if i < len(frames) and frames[i] in snap else sorted(snap)[0]
            then = snap[f]
            if owner and owner != a.active:
                label = f"{a.char(owner)['name']}: {label}"
            if k[0] == "undo":
                what = f"Before “{label}”"
                n = len(a.undo) - k[1]
                self.act_btn.configure(text=f"Go Back to Before This Step  ({n} undo{'s' if n > 1 else ''})",
                                       state="normal")
            else:
                what = f"After “{label}” (undone)"
                n = len(a.redo) - k[1]
                self.act_btn.configure(text=f"Redo Up to This Step  ({n} redo{'s' if n > 1 else ''})", state="normal")
            moved = self.moved(then, states[f])
            extra = f"  This step changed {history.frames_text(snap)}." if len(snap) > 1 else ""
            self.info.configure(text=(f"Frame {f}: {what} (grey) against now (colour). "
                                      + (", ".join(f"{n} {d:.0f} px" for n, d in moved[:6])
                                         + (" …" if len(moved) > 6 else "") + " differ from now."
                                         if moved else "No joint differs from now.") + extra))
        W, H = c.winfo_width(), c.winfo_height()
        if W < 50 or H < 50:
            return
        now = a.states[f] if k[0] == "now" else states[f]
        img = self.render(f, then, now, W, H, what)
        self.photo = ImageTk.PhotoImage(img)
        c.delete("all")
        c.create_image(0, 0, image=self.photo, anchor="nw")

    @staticmethod
    def moved(then, now):
        """[(joint, distance px)] of joints placed or moved between two frame states, biggest first."""
        out = []
        for n in trace_io.ORDER:
            a, b = then.pts.get(n), now.pts.get(n)
            if a and b:
                d = math.dist(a, b)
                if d >= 0.05:
                    out.append((n, d))
            elif a or b:
                out.append((n, float("inf")))
        return sorted(out, key=lambda t: -t[1])

    def render(self, f, then, now, W, H, what):
        img = Image.new("RGB", (W, H), (22, 22, 26))
        pic = frame_image(self.app.dir, int(f))
        fw, fh = pic.size if pic else (320, 240)
        big = Image.new("RGB", (fw + 2 * PAD, fh + 2 * PAD), (40, 40, 44))
        if pic:
            big.paste(pic, (PAD, PAD))
        pts = [p for st in (then, now) if st for p in st.pts.values()]
        if pts:   # crop round the body (both poses), so it's big enough to see
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            m = max(40, 0.35 * max(max(xs) - min(xs), max(ys) - min(ys)))
            box = (max(0, int(min(xs) - m + PAD)), max(0, int(min(ys) - m + PAD)),
                   min(big.width, int(max(xs) + m + PAD)), min(big.height, int(max(ys) + m + PAD)))
        else:
            box = (0, 0, big.width, big.height)
        crop = big.crop(box)
        k = min((W - 20) / max(1, crop.width), (H - 40) / max(1, crop.height))
        k = max(0.05, k)
        crop = crop.resize((max(1, int(crop.width * k)), max(1, int(crop.height * k))), Image.BILINEAR)
        ox, oy = (W - crop.width) // 2, 30 + (H - 40 - crop.height) // 2
        img.paste(crop, (ox, oy))
        d = ImageDraw.Draw(img)

        def to(p):
            return ox + (p[0] + PAD - box[0]) * k, oy + (p[1] + PAD - box[1]) * k

        r = max(3, int(4 * min(2.0, k)))
        if then:
            for n in trace_io.ORDER:   # amber: where a joint went since
                if n in then.pts and n in now.pts and math.dist(then.pts[n], now.pts[n]) >= 0.5:
                    d.line([to(then.pts[n]), to(now.pts[n])], fill=(227, 162, 58), width=2)
            for ch in trace_io.CHAINS:
                for a, b in zip(ch, ch[1:]):
                    if a in then.pts and b in then.pts:
                        d.line([to(then.pts[a]), to(then.pts[b])], fill=(150, 150, 158), width=3)
            for n, p in then.pts.items():
                x, y = to(p)
                d.ellipse([x - r, y - r, x + r, y + r], outline=(150, 150, 158), width=2)
        for ch in trace_io.CHAINS:
            for a, b in zip(ch, ch[1:]):
                if a in now.pts and b in now.pts:
                    d.line([to(now.pts[a]), to(now.pts[b])], fill=chain_colour(ch), width=3)
        for n, p in now.pts.items():
            x, y = to(p)
            faded = n not in now.ok
            d.ellipse([x - r, y - r, x + r, y + r], fill=None if faded else (255, 255, 255),
                      outline=(255, 255, 0) if n in now.guess else (0, 0, 0) if not faded else (200, 200, 200))
        d.rectangle((0, 0, W, 24), fill=(0, 0, 0))
        d.text((8, 6), f"Frame {f}   ·   grey: {what}   ·   colour: now" if then else f"Frame {f}   ·   now",
               fill=(235, 235, 238))
        return img

    # ---- actions
    def act(self):
        a = self.app
        k, step = self.selected_step()
        if not k or k[0] == "now":
            return
        label = step[2]
        if k[0] == "undo":
            n = a.undo_to(k[1])
            self.msg.configure(text=f"Went back {n} step{'s' if n > 1 else ''}: “{label}” and everything after it "
                                    "are undone. Ctrl+Y (or Redo Up to) brings them back.", fg=hud.GREEN)
        else:
            n = a.redo_to(k[1])
            self.msg.configure(text=f"Redid {n} step{'s' if n > 1 else ''}, up to “{label}”.", fg=hud.GREEN)
        self.refresh(now=True)

    def checkpoint(self):
        made = self.app.save_checkpoint()
        if made:
            self.msg.configure(text="Checkpoint saved: Backups… on the Trace home puts it back.", fg=hud.GREEN)
        self.refresh(now=True)

    def close(self):
        if self.job is not None:
            try:
                self.win.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None
        self.app.history_dlg = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass

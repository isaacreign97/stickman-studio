"""The "Backups" window of 02 TRACE (Stickman Studio upgrade, Phase 1; checkpoints and single frames in Phase 9).

Lists the dated backups of a move (<move>\\backups\\, made by trace_io), shows the selected one drawn over its frames
next to the current trace, and puts it back on request. Restoring first backs up the file it replaces, so a restore
can itself be undone from the same list. Nothing here deletes a backup.
Phase 9: show ALL / CHECKPOINTS / TRACE / FIXED; checkpoints carry their names; a trace backup says on which key
frames it differs from now, and RESTORE FRAMES… puts back only the frames you tick (the rest of trace.json stays).
SAVE CHECKPOINT… names a copy of the trace as it is now. Restores are written in the move's log (trace_history.json).
A protected (read-only) trace is never overwritten, and a fixed trace never goes back as trace.json.

usage: python -I restore_dialog.py <move folder>      (on its own; inside the studio: BACKUPS… in 02 TRACE)
"""
import os
import sys
import time
import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageDraw, ImageTk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python -I leaves the script's folder out
import history  # noqa: E402
import hud  # noqa: E402
import trace_io  # noqa: E402

FILTERS = [("all", "ALL"), ("checkpoint", "CHECKPOINTS"), ("trace", "TRACE"), ("fixed", "FIXED")]


def keep(b, flt):
    return flt == "all" or (flt == "checkpoint" and b.get("label")) or b["kind"] == flt

FRONT, BACK, BODY = (255, 140, 0), (30, 110, 255), (30, 200, 60)
PAD = 60   # frame pixels around each frame in the preview, for joints placed outside it


def chain_colour(chain):
    return BODY if chain[1] == "waist" else FRONT if chain[1].startswith("front") else BACK


def frame_image(folder, f):
    p = os.path.join(folder, f"f{f:02d}.png")
    try:
        return Image.open(p).convert("RGB")
    except OSError:
        return None


def render(folder, path, W, H, title):
    """A W x H picture of the trace in path: every key frame with its points, side by side."""
    img = Image.new("RGB", (max(W, 10), max(H, 10)), (22, 22, 26))
    d = ImageDraw.Draw(img)
    d.text((8, 6), title, fill=(235, 235, 238))
    try:
        J = trace_io.read_json(path)
        frames, pts = list(J["frames"]), list(J["pts"])
        est = J.get("estimated") or [[] for _ in frames]
    except (OSError, ValueError, KeyError, TypeError) as e:
        d.text((8, 28), f"Can't read it: {e}", fill=(255, 67, 75))
        return img
    if not frames:
        d.text((8, 28), "No key frames in this trace.", fill=(141, 141, 152))
        return img
    xs = [v[0] for P in pts for n, v in P.items() if n in trace_io.ORDER]
    ys = [v[1] for P in pts for n, v in P.items() if n in trace_io.ORDER]
    crop = None
    if xs:   # one box round the body in every frame, so the poses stay the same size and are big enough to see
        m = max(40, 0.2 * max(max(xs) - min(xs), max(ys) - min(ys)))
        crop = (min(xs) - m + PAD, min(ys) - m + PAD, max(xs) + m + PAD, max(ys) + m + PAD)
    tiles = []
    for f, P, E in zip(frames, pts, est):
        im = frame_image(folder, int(f))
        w, h = (im.size if im else (320, 240))
        t = Image.new("RGB", (w + 2 * PAD, h + 2 * PAD), (40, 40, 44))
        if im:
            t.paste(im, (PAD, PAD))
        td = ImageDraw.Draw(t)
        Q = {n: (v[0] + PAD, v[1] + PAD) for n, v in P.items() if n in trace_io.ORDER}
        for ch in trace_io.CHAINS:
            for a, b in zip(ch, ch[1:]):
                if a in Q and b in Q:
                    td.line([Q[a], Q[b]], fill=chain_colour(ch), width=max(2, w // 120))
        r = max(3, w // 90)
        for n, (x, y) in Q.items():
            if n in E:
                td.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 0), width=2)
            else:
                td.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255), outline=(0, 0, 0))
        if crop:
            box = tuple(int(round(v)) for v in crop)
            t = t.crop((max(0, box[0]), max(0, box[1]), min(t.width, box[2]), min(t.height, box[3])))
            td = ImageDraw.Draw(t)
        missing = 12 - len(Q)
        td.rectangle((0, 0, 110, 14), fill=(0, 0, 0))
        td.text((4, 2), f"frame {f}" + (f"  ({missing} missing)" if missing else ""), fill=(255, 255, 255))
        tiles.append(t)
    top = 24
    n = len(tiles)
    tw, th = max(t.width for t in tiles), max(t.height for t in tiles)
    best = None
    for cols in range(1, n + 1):   # the grid that makes the tiles biggest
        rows = (n + cols - 1) // cols
        k = min((W - 6 * (cols + 1)) / (cols * tw), (H - top - 6 * (rows + 1)) / (rows * th))
        if best is None or k > best[0]:
            best = (k, cols)
    k, cols = best
    k = max(k, 0.05)
    for i, t in enumerate(tiles):
        s = t.resize((max(1, int(t.width * k)), max(1, int(t.height * k))), Image.BILINEAR)
        x = 6 + (i % cols) * (int(tw * k) + 6)
        y = top + 6 + (i // cols) * (int(th * k) + 6)
        img.paste(s, (x, y))
    return img


class FramePicker:
    """A small window: tick the key frames of a backup to put back. Frames that differ from now start ticked.
    .result = sorted list of frames, or None when cancelled."""

    def __init__(self, parent, frames, differ, what):
        self.result = None
        d = self.win = tk.Toplevel(parent, bg=hud.PANEL, padx=18, pady=14)
        d.title("Restore frames")
        d.transient(parent)
        d.resizable(False, False)
        hud.label(d, f"Put back these key frames from the backup of\n{what}:", bg=hud.PANEL, justify="left",
                  anchor="w").pack(fill="x")
        hud.label(d, "Ticked frames are replaced by the backup's points; every other key frame of trace.json stays "
                     "as it is. trace.json is backed up first.", bg=hud.PANEL, fg=hud.DIM, font=hud.SMALL,
                  justify="left", anchor="w", wraplength=420).pack(fill="x", pady=(4, 8))
        grid = tk.Frame(d, bg=hud.PANEL)
        grid.pack(fill="x")
        self.vars = {}
        for k, f in enumerate(frames):
            v = tk.BooleanVar(d, value=f in differ)
            self.vars[f] = v
            tk.Checkbutton(grid, text=f"frame {f}" + ("" if f in differ else "  (same as now)"), variable=v,
                           bg=hud.PANEL, fg=hud.AMBER if f in differ else hud.DIM, selectcolor=hud.FIELD,
                           activebackground=hud.PANEL, activeforeground=hud.TEXT, font=hud.SMALL,
                           anchor="w").grid(row=k // 4, column=k % 4, sticky="w", padx=(0, 12))
        row = tk.Frame(d, bg=hud.PANEL)
        row.pack(anchor="e", pady=(12, 0))
        hud.Button(row, "Cancel", d.destroy).pack(side="right", padx=(4, 0))
        hud.Button(row, "Put Back Ticked Frames", self.ok, kind="red").pack(side="right")
        d.bind("<Escape>", lambda e: d.destroy())
        d.grab_set()
        d.wait_window()

    def ok(self):
        self.result = sorted(f for f, v in self.vars.items() if v.get()) or None
        self.win.destroy()


class RestoreDialog:
    """on_restored(folder) is called after a backup was put back (the studio reloads the move)."""

    def __init__(self, root, folder, on_restored=None, frames_dir=None, title=None):
        self.root, self.folder, self.on_restored = root, os.path.normpath(folder), on_restored
        # Phase 11: folder = the trace's folder (a traced character's); the pictures and the move's log are in the
        # move folder (frames_dir); title names the character
        self.frames_dir = os.path.normpath(frames_dir) if frames_dir else self.folder
        self.title = title or os.path.basename(self.folder)
        self.backups = []
        self.photo = None
        self.flt = "all"
        self.win = w = tk.Toplevel(root, bg=hud.BG)
        w.title(f"Backups: {self.title}")
        w.geometry("1180x720")
        w.minsize(900, 520)
        w.transient(root)

        head = tk.Frame(w, bg=hud.BG)
        head.pack(fill="x", padx=12, pady=(12, 6))
        hud.Header(head, "Backups of " + self.title,
                   "A dated copy is made every time this move's trace is opened, before a new fixed trace is saved "
                   "and before a restore; checkpoints are the ones you named. Pick one to see it next to the current "
                   "trace. Restoring backs up the current file first, so you can always go back. Your trace and the "
                   "fixed trace are kept apart: each backup only goes back to its own file.").pack(fill="x")

        body = tk.Frame(w, bg=hud.BG)
        body.pack(fill="both", expand=True, padx=12)
        left = hud.panel(body, width=500)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        fr = tk.Frame(left, bg=hud.PANEL)
        fr.pack(fill="x", padx=6, pady=(6, 0))
        self.filter_btns = {}
        for key, text in FILTERS:
            b = hud.Button(fr, text, lambda k=key: self.set_filter(k), padx=6, font=hud.SMALL)
            b.pack(side="left", expand=True, fill="x", padx=(0, 3))
            self.filter_btns[key] = b
        self.listbox = tk.Listbox(left, bg=hud.PANEL, fg=hud.TEXT, selectbackground=hud.RED,
                                  selectforeground="#ffffff", font=hud.SMALL, activestyle="none",
                                  highlightthickness=0, bd=0, exportselection=False)
        self.listbox.pack(fill="both", expand=True, padx=6, pady=6)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.show())
        self.info = hud.label(left, "", bg=hud.PANEL, fg=hud.DIM, font=hud.SMALL, anchor="w", justify="left")
        self.info.pack(fill="x", padx=8, pady=(0, 8))
        hud.wrap_to_width(self.info)

        right = tk.Frame(body, bg=hud.BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.stage = tk.Canvas(right, bg="#16161a", highlightthickness=0)
        self.stage.pack(fill="both", expand=True)
        self.stage.bind("<Configure>", lambda e: self.show())

        bar = tk.Frame(w, bg=hud.BG)
        bar.pack(fill="x", padx=12, pady=(10, 0))
        self.msg = hud.label(w, "", fg=hud.DIM, font=hud.SMALL, anchor="w")   # its own line: a long message
        self.msg.pack(fill="x", padx=12, pady=(4, 8))                          # never pushes a button out
        hud.Button(bar, "Close", w.destroy).pack(side="right", padx=(4, 0))
        self.restore_btn = hud.Button(bar, "Restore This Backup", self.restore, kind="red")
        self.restore_btn.pack(side="right", padx=(4, 0))
        self.frames_btn = hud.Button(bar, "Restore Frames…", self.restore_frames)
        self.frames_btn.pack(side="right", padx=(4, 0))
        hud.Button(bar, "Open Backups Folder", self.open_folder).pack(side="right", padx=(4, 0))
        hud.Button(bar, "Save Checkpoint…", self.checkpoint).pack(side="right", padx=(4, 0))
        hud.Button(bar, "Back Up Now", self.backup_now).pack(side="right", padx=(4, 0))
        w.bind("<Escape>", lambda e: w.destroy())
        self.reload()
        w.focus_set()

    # ---- the list
    def set_filter(self, key):
        self.flt = key
        self.reload()

    def reload(self, select=0):
        self.backups = [b for b in trace_io.list_backups(self.folder) if keep(b, self.flt)]
        for key, b in self.filter_btns.items():
            b.set_kind("red" if key == self.flt else "normal")
        lb = self.listbox
        lb.delete(0, "end")
        for b in self.backups:
            try:
                s = trace_io.summary(b["path"])
                extra = f"{s['frames']} key frames · {s['points']} points"
            except (OSError, ValueError, KeyError, TypeError):
                extra = "unreadable"
            lb.insert("end", f" {trace_io.describe(b)}  ·  {extra}")
            if b.get("label"):
                lb.itemconfigure("end", fg=hud.AMBER)
        if not self.backups:
            lb.insert("end", " No backups yet. One is made the next time this trace is opened." if self.flt == "all"
                      else " None of this kind.")
            self.restore_btn.configure(state="disabled")
        else:
            lb.selection_set(min(select, len(self.backups) - 1))
            self.restore_btn.configure(state="normal")
        self.show()

    def selected(self):
        sel = self.listbox.curselection()
        if not sel or not self.backups or sel[0] >= len(self.backups):
            return None
        return self.backups[sel[0]]

    # ---- the preview: current file on top, the backup under it
    def show(self):
        c = self.stage
        b = self.selected()
        self.frames_btn.configure(state="normal" if b and b["kind"] == "trace" else "disabled")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 50 or H < 50:
            return
        img = Image.new("RGB", (W, H), (22, 22, 26))
        if b is None:
            self.info.configure(text="")
        else:
            current = trace_io.fixed_path(self.folder) if b["kind"] == "fixed" else trace_io.trace_path(self.folder)
            name = os.path.basename(current)
            if os.path.exists(current):
                img.paste(render(self.frames_dir, current, W, H // 2 - 2, f"Now: {name}"), (0, 0))
            else:
                ImageDraw.Draw(img).text((8, 6), f"Now: there is no {name}", fill=(141, 141, 152))
            img.paste(render(self.frames_dir, b["path"], W, H - H // 2 - 2, f"Backup: {b['name']}"), (0, H // 2 + 2))
            ImageDraw.Draw(img).line((0, H // 2, W, H // 2), fill=(227, 34, 43), width=2)
            same = os.path.exists(current) and trace_io.same_bytes(current, b["path"])
            self.info.configure(text=f"{trace_io.describe(b)}\n{b['path']}"
                                     + ("\nIdentical to the current file." if same else self.diff_text(b, current)))
        self.photo = ImageTk.PhotoImage(img)
        c.delete("all")
        c.create_image(0, 0, image=self.photo, anchor="nw")

    @staticmethod
    def diff_text(b, current):
        """For a trace backup: on which key frames it differs from the current trace."""
        if b["kind"] != "trace" or not os.path.exists(current):
            return ""
        try:
            diff = trace_io.differing_frames(current, b["path"])
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return ""
        return ("\nSame points as now on every key frame (only the layout differs)." if not diff else
                f"\nDiffers from now on {history.frames_text(diff)}: Restore Frames… can put back just those.")

    # ---- actions
    def restore(self):
        b = self.selected()
        if not b:
            return
        target = "trace_fixed.json" if b["kind"] == "fixed" else "trace.json"
        if not messagebox.askyesno(
                "Restore backup", f"Replace {target} of {os.path.basename(self.folder)} with the backup from\n"
                                  f"{trace_io.describe(b)}?\n\nThe current {target} is backed up first, so this "
                                  "can be undone from this list.", parent=self.win):
            return
        try:
            done, safety = trace_io.restore(self.folder, b["path"])
        except (OSError, ValueError, KeyError, TypeError) as e:
            messagebox.showerror("Restore backup", f"Nothing was changed.\n\n{e}", parent=self.win)
            return
        history.add_event(self.frames_dir, "restore", f"Put back {target}"
                          + (f" of {self.title}" if self.frames_dir != self.folder else "")
                          + f" from the backup of {trace_io.describe(b)}")
        self.reload(select=0)
        self.msg.configure(text=f"Restored {os.path.basename(done)}." + (
            f"  The file it replaced is the backup at the top of the list." if safety else ""), fg=hud.GREEN)
        if self.on_restored:
            self.on_restored(self.folder)

    def restore_frames(self):
        """Put back only some key frames of the selected trace backup."""
        b = self.selected()
        if not b or b["kind"] != "trace":
            return
        current = trace_io.trace_path(self.folder)
        try:
            theirs, order = trace_io.read_frames(b["path"])
            diff = set(trace_io.differing_frames(current, b["path"]))
        except (OSError, ValueError, KeyError, TypeError, IndexError) as e:
            messagebox.showerror("Restore frames", f"That backup can't be read.\n\n{e}", parent=self.win)
            return
        picked = FramePicker(self.win, sorted(theirs), diff, trace_io.describe(b)).result
        if not picked:
            return
        try:
            done, safety, frames = trace_io.restore_frames(self.folder, b["path"], picked)
        except (OSError, ValueError, KeyError, TypeError) as e:
            messagebox.showerror("Restore frames", f"Nothing was changed.\n\n{e}", parent=self.win)
            return
        history.add_event(self.frames_dir, "restore", f"Put back {history.frames_text(frames)} from the backup of "
                                                  f"{trace_io.describe(b)}", frames=frames)
        self.reload(select=0)
        self.msg.configure(text=f"Put back {history.frames_text(frames)} into trace.json; every other key frame is "
                                "as it was." + ("  The trace before this is the backup at the top of the list."
                                                if safety else ""), fg=hud.GREEN)
        if self.on_restored:
            self.on_restored(self.folder)

    def checkpoint(self):
        name = hud.ask_text(self.win, "Save checkpoint", "Name this checkpoint: a copy of the trace (and of the fixed "
                            "trace, if there is one) as it is now.", time.strftime("checkpoint %d %b %H:%M"))
        if name is None:
            return
        try:
            made = trace_io.checkpoint(self.folder, name)
        except OSError as e:
            self.msg.configure(text=f"Couldn't save the checkpoint: {e}", fg=hud.RED_HI)
            return
        if not made:
            self.msg.configure(text="There's no trace yet to save a checkpoint of.", fg=hud.DIM)
            return
        history.add_event(self.frames_dir, "checkpoint", f"Checkpoint “{trace_io.list_backups(self.folder)[0]['label']}” "
                                                     "saved")
        self.reload()
        self.msg.configure(text=f"Checkpoint saved ({len(made)} file{'s' if len(made) > 1 else ''}).", fg=hud.GREEN)

    def backup_now(self):
        try:
            made = trace_io.backup(self.folder, "manual")
        except OSError as e:
            self.msg.configure(text=f"Couldn't back up: {e}", fg=hud.RED_HI)
            return
        self.reload()
        self.msg.configure(text=f"Made {len(made)} backup(s)." if made else
                           "Nothing new to back up: the newest backups already match.",
                           fg=hud.GREEN if made else hud.DIM)

    def open_folder(self):
        d = trace_io.backup_folder(self.folder)
        os.makedirs(d, exist_ok=True)
        os.startfile(d)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    root = tk.Tk()
    hud.setup(root)
    root.withdraw()
    dlg = RestoreDialog(root, os.path.abspath(sys.argv[1]))
    dlg.win.protocol("WM_DELETE_WINDOW", root.destroy)
    dlg.win.bind("<Destroy>", lambda e: e.widget is dlg.win and root.destroy())
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

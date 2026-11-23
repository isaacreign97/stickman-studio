"""Stickman Studio: Video Tool, Trace Clicker, the stickman player and Game Settings in one window.

  01 SOURCE     step through a video / GIF / photos frame by frame, mark the move (I / O), save PNG frames (F),
                a GIF (G) or one frame (S). Saving frames goes straight on to 02.
  02 TRACE      pick a move folder, click the key frames on the thumbnails, then click the 12 joints.
  03 PLAY/FIX   watch the trace as the game's stickman; fix camera angle, size, travel and ground; save.
  04 SETTINGS   Game Settings: keys, values, moves linked to traces, notes and feedback -> a prompt for Claude.

usage: python -I studio.py [--images DIR] [--settings DIR] [--unity DIR] [--screen source|trace|play|settings]
                           [video | gif | images | image folder | frames folder | trace.json | project.json | Unity folder]
Used by "Stickman Studio.bat" (drag any of those onto it, or double-click it).
Ctrl+1 .. Ctrl+5 switch screens.
"""
import json
import os
import re
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # python -I leaves the script's folder out
import hud  # noqa: E402
import ribbon  # noqa: E402  (v3.3: title bar and ribbons)
import characters as chars  # noqa: E402  (Phase 11: traced characters)
import project  # noqa: E402
import trace_clicker as tc  # noqa: E402
import trace_io  # noqa: E402
import trace_player as tp  # noqa: E402
import video_tool as vt  # noqa: E402
from character_bar import CharacterBar  # noqa: E402
from project_dialog import ProjectDialog  # noqa: E402
from restore_dialog import RestoreDialog  # noqa: E402
from tour import Tour  # noqa: E402
from PIL import Image, ImageTk  # noqa: E402

VERSION = "3.3"   # bump per feature (1.2 backups 1.3 tracing 1.4 carry 1.5 smooth 1.6 trails 1.7 keys 1.8 compare
#                   1.9 analytics 2.0 project management and recovery 2.1 batch export 3.0 multi-character 3.1 optional joints 3.2 creative tools
#                   3.3 ribbon interface)
FRAME = re.compile(r"^f(\d+)\.png$", re.IGNORECASE)
THUMB_W = 168
MODES = [("source", "1   Source"), ("trace", "2   Trace"), ("play", "3   Review"),
         ("settings", "4   Game Settings"), ("animate", "5   Animate")]
MODE_TIPS = {"source": "Open a video, GIF or images and save the frames of a move (Ctrl+1)",
             "trace": "Choose key frames and place the 12 joints (Ctrl+2)",
             "play": "Play the trace as the game's stickman and correct it (Ctrl+3)",
             "settings": "Keys, values and moves for the game, and the prompt for Claude (Ctrl+4)",
             "animate": "Animate without a video: pose, draw, paint and tell stories (Ctrl+5)"}
SHORTCUTS = {
    "source": [("← / →", "Previous / next frame"), ("Shift+← / →", "10 frames back / forward"),
               ("Space", "Play / pause"), ("[ / ]", "Slower / faster"), ("Home / End", "First / last frame"),
               ("Mouse wheel", "Step through frames"), ("I / O", "Set range start / end"), ("C", "Clear range"),
               ("F", "Save frames as PNG"), ("G", "Make GIF"), ("S", "Save this frame"), ("Ctrl+O", "Open file")],
    "trace": [("Enter", "Start tracing / next frame"), ("Ctrl+A", "Select all frames"), ("Space", "Keep the ghost point"),
              ("Right-click", "Place a guessed point"), ("Tab / Ctrl+click", "Select a point"),
              ("Alt+arrows", "Nudge the selected point"), ("Delete", "Remove the selected point"),
              ("Ctrl+Z / Ctrl+Y", "Undo / redo"), ("U", "History"), ("Ctrl+S", "Save a checkpoint"),
              ("N", "Next unfinished frame"), ("Z / + / −", "Zoom to figure / in / out"), ("C", "Carry forward"),
              ("S", "Smooth"), ("R", "Refresh ghost"), ("T", "Trails"), ("P", "Play")],
    "play": [("Space", "Play / pause"), ("← / →", "Step"), ("S", "Smooth"), ("L", "Loop"), ("R", "Reference"),
             ("B", "Grey back limbs"), ("G", "Ground line"), ("T", "Trails"), ("K", "Key poses"), ("C", "Compare"),
             ("A", "Analytics")],
    "settings": [("Click a key box", "Then press the key to use")],
    "animate": [("Space", "Play / pause"), ("← / →", "Previous / next frame"), ("K", "Set key"), ("Q", "Pose"),
                ("J", "Build"), ("H", "Path"), ("P / B / E", "Pen / brush / eraser"), ("L", "Line"), ("F", "Fill"),
                ("G", "Gradient"), ("I", "Pick colour"), ("S", "Select"), ("D", "Edit shapes"), ("O", "Onion skin"),
                ("A", "Select all characters"), ("[ / ]", "Smaller / larger size"), ("Ctrl+C / X / V", "Copy / cut / paste"),
                ("Ctrl+Z / Ctrl+Y", "Undo / redo"), ("Ctrl+S", "Save")],
}

GS_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "stickman-movement-system", os.path.basename(HERE)))   # same folder name in both skills ("scripts")
if not os.path.isfile(os.path.join(GS_DIR, "game_settings.py")):   # a stand-alone copy keeps it beside studio.py
    GS_DIR = HERE


def ranges(nums):
    """[0, 1, 2, 3, 7, 9, 10] -> "0–3, 7, 9–10" (runs of three or more as a range)."""
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out += [f"{nums[i]}–{nums[j]}"] if j - i >= 2 else [str(n) for n in nums[i:j + 1]]
        i = j + 1
    return ", ".join(out)


def frame_numbers(folder):
    try:
        return sorted(int(m.group(1)) for m in (FRAME.match(n) for n in os.listdir(folder)) if m)
    except OSError:
        return []


def trace_file(folder):
    for n in os.listdir(folder):
        if n.lower() == "trace.json":
            return os.path.join(folder, n)
    return None


def move_status(folder):
    """-> (frames, finished key frames, key frames, has fixed trace)."""
    n = len(frame_numbers(folder))
    t = trace_file(folder)
    done = total = 0
    if t:
        try:
            keys, unfinished = tp.read_trace(t)
            done, total = len(keys), len(keys) + len(unfinished)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return n, done, total, os.path.exists(tp.fixed_path(folder))


# ---------------------------------------------------------------- 02 TRACE: the move list and key frame picker
class TraceHome:
    def __init__(self, parent, studio):
        self.studio = studio
        self.frame = tk.Frame(parent, bg=hud.BG)
        self.folder = None
        self.thumbs = {}       # folder -> {frame number: PhotoImage}
        self.selected = []     # key frames, in click order
        self.tiles = {}
        self.sort = "name"     # Phase 9: the move list by name or by the latest change
        self.keymap = {"<Return>": lambda e: self.start(), "<Control-a>": lambda e: self.select_all()}

        # v3.3: a ribbon. Home has the everyday actions; Export and View hold the rest.
        rb = self.ribbon = ribbon.Ribbon(self.frame, [
            ("Open Images Folder", self.open_folder), ("Refresh Move List", self.refresh_list, "F5"), None,
            ("Export Moves…", self.open_export), ("Sprite Sheet…", self.open_sprites), None,
            ("Move Project…", self.open_project), ("Backups…", self.open_backups)])
        rb.pack(fill="x", padx=12, pady=(8, 0))
        g = rb.tab("Home").group("Trace")
        self.start_btn = g.button("Start Tracing", self.start, "Trace the selected key frames (Enter)", kind="red")
        self.cont_btn = g.button("Continue Tracing", self.continue_trace, "Open the saved trace to carry on")
        self.play_btn = g.button("Review", self.play, "Play the saved trace as the game's stickman")
        g = rb.tab("Home").group("Key frames")
        g.button("Select All", self.select_all, "Select every frame (Ctrl+A)")
        g.button("Clear", self.clear, "Clear the selection")
        g = rb.tab("Home").group("Move")
        self.project_btn = g.button("Project…", self.open_project,
                                    "Status and checks, protection, copies and full backups of this move")
        self.backups_btn = g.button("Backups…", self.open_backups, "Earlier versions of the trace, to compare or restore")
        g = rb.tab("Export").group("Export")
        g.button("Export Moves…", self.open_export, "Export several traced moves at once")
        g.button("Sprite Sheet…", self.open_sprites, "Sprite sheets for Unity and other game engines")
        g = rb.tab("View").group("Sort moves")
        self.sort_btns = {}
        for key, text in (("name", "A–Z"), ("recent", "Latest Change")):
            self.sort_btns[key] = g.button(text, lambda k=key: self.set_sort(k))
        g = rb.tab("View").group("Folder")
        g.button("Open Images Folder", self.open_folder)
        g.button("Refresh", self.refresh_list, "Read the Images folder again (F5)")
        self.keymap["<F5>"] = lambda e: self.refresh_list()

        main = tk.Frame(self.frame, bg=hud.BG)
        main.pack(fill="both", expand=True)
        left = tk.Frame(main, bg=hud.PANEL, width=300, highlightthickness=1, highlightbackground=hud.LINE)
        left.pack(side="left", fill="y", padx=(12, 0), pady=10)
        left.pack_propagate(False)
        hud.Header(left, "Moves", "Move folders in Images. Select one.", bg=hud.PANEL).pack(
            fill="x", padx=12, pady=(12, 6))
        lw = tk.Frame(left, bg=hud.PANEL)
        lw.pack(fill="both", expand=True, padx=(12, 4))
        self.list_canvas = tk.Canvas(lw, bg=hud.PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(lw, orient="vertical", command=self.list_canvas.yview)
        self.list_inner = tk.Frame(self.list_canvas, bg=hud.PANEL)
        self.list_win = self.list_canvas.create_window(0, 0, window=self.list_inner, anchor="nw")
        self.list_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.list_canvas.pack(side="left", fill="both", expand=True)
        self.list_inner.bind("<Configure>", lambda e: self.list_canvas.configure(
            scrollregion=self.list_canvas.bbox("all")))
        self.list_canvas.bind("<Configure>", lambda e: self.list_canvas.itemconfigure(self.list_win, width=e.width))
        tk.Frame(left, bg=hud.PANEL, height=10).pack(fill="x")

        right = tk.Frame(main, bg=hud.BG)
        right.pack(side="left", fill="both", expand=True, padx=12, pady=10)
        head = tk.Frame(right, bg=hud.BG)
        head.pack(fill="x")
        self.title = hud.label(head, "Select a move", font=(hud.F_SEMI, 18), anchor="w")
        self.title.pack(side="left")
        self.sub = hud.label(head, "", fg=hud.DIM, font=hud.SMALL, anchor="w")
        self.sub.pack(side="left", padx=14, pady=(8, 0))
        self.charbar = CharacterBar(right, studio.root, on_change=self.characters_changed)   # Phase 11
        self.charbar.pack(fill="x", pady=(6, 0))
        self.marks = None    # multi-character moves: [(colour, {frames}, active)] per visible character
        hud.Header(right, "Key frames", "Select the frames where the motion changes: the start, the lowest point "
                                        "of the wind-up, the impact or peak, the landing and the end (usually 4 to "
                                        "8).").pack(
            fill="x", pady=(8, 6))
        gw = hud.panel(right, bg=hud.PANEL)
        gw.pack(fill="both", expand=True)
        self.grid = tk.Canvas(gw, bg=hud.PANEL, highlightthickness=0)
        gsb = ttk.Scrollbar(gw, orient="vertical", command=self.grid.yview)
        self.grid.configure(yscrollcommand=gsb.set)
        gsb.pack(side="right", fill="y")
        self.grid.pack(side="left", fill="both", expand=True)
        self.grid.bind("<Configure>", lambda e: self.layout())
        self.grid.bind("<Button-1>", self.on_click)
        self.grid.bind("<MouseWheel>", lambda e: self.grid.yview_scroll(-1 if e.delta > 0 else 1, "units"))

        bar = tk.Frame(right, bg=hud.BG)
        bar.pack(fill="x", pady=(8, 0))
        self.sel_lbl = hud.label(bar, "", fg=hud.AMBER, font=hud.BOLD, anchor="w")
        self.sel_lbl.pack(side="left", fill="x", expand=True)
        self.refresh_list()
        self.update_bar()

    # ---- the move list
    def set_sort(self, key):
        self.sort = key
        self.refresh_list()

    def refresh_list(self):
        for w in self.list_inner.winfo_children():
            w.destroy()
        for key, b in self.sort_btns.items():
            b.set_kind("red" if key == self.sort else "normal")
        images = self.studio.images
        folders = project.sort_moves(project.moves(images), self.sort) if os.path.isdir(images) else []
        if self.folder and self.folder not in folders and os.path.isdir(self.folder):
            folders.insert(0, self.folder)
        if not folders:
            hud.label(self.list_inner, "No frames yet.\nSave some in Source (F).", bg=hud.PANEL, fg=hud.DIM,
                      justify="left", anchor="w").pack(fill="x", pady=8)
        for d in folders:
            n, done, total, fixed = move_status(d)
            here = self.folder and os.path.normcase(d) == os.path.normcase(self.folder)
            bg = hud.RED_BG if here else hud.PANEL
            row = tk.Frame(self.list_inner, bg=bg, highlightthickness=1,
                           highlightbackground=hud.RED if here else hud.PANEL, cursor="hand2")
            row.pack(fill="x", pady=1)
            tk.Frame(row, bg=hud.RED if here else hud.LINE, width=3).pack(side="left", fill="y")
            txt = tk.Frame(row, bg=bg)
            txt.pack(side="left", fill="x", expand=True, padx=8, pady=4)
            hud.label(txt, os.path.basename(d), bg=bg, font=hud.BOLD, anchor="w").pack(fill="x")
            state = f"{n} frames"
            many = self.characters_of(d)
            if many:   # Phase 11: a multi-character move
                state += (f"  ·  {len(many)} characters  ·  traced {sum(c['done'] for c in many)}/"
                          f"{sum(c['frames'] for c in many)}")
                done, total = sum(c["done"] for c in many), sum(c["frames"] for c in many)
            elif total:
                state += f"  ·  traced {done}/{total}" + ("  ·  fixed" if fixed else "")
            hud.label(txt, state, bg=bg, fg=hud.GREEN if total and done == total else hud.DIM, font=hud.SMALL,
                      anchor="w").pack(fill="x")
            flags = self.flags(d)
            if flags:   # Phase 9: protected, problems found by the check, an out-of-date fixed trace
                hud.wrap_to_width(hud.label(txt, flags, bg=bg, fg=hud.AMBER, font=hud.TINY, anchor="w",
                                            justify="left")).pack(fill="x")
            for w in (row, txt, *txt.winfo_children()):
                w.bind("<Button-1>", lambda e, d=d: self.choose(d))
                w.bind("<MouseWheel>", lambda e: self.list_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))

    @staticmethod
    def flags(folder):
        """The move's warning line in the list: protected, fixed trace out of date, problems to check."""
        try:
            st = project.status(folder)
        except Exception:   # a list label only: never break the list over one odd folder
            return "Can't Be Checked (Project…)"
        parts = []
        if st["protected"]:
            parts.append("PROTECTED")
        if st["fixed"] == "stale":
            parts.append("Fixed Trace Out of Date")
        n = st["counts"]["error"] + st["counts"]["warning"] - (st["fixed"] == "stale")
        if n:
            parts.append(f"{n} to check in Project…")
        return "  ·  ".join(parts)

    def open_folder(self):
        d = filedialog.askdirectory(parent=self.studio.root, title="A folder with f01.png, f02.png ...",
                                    initialdir=self.studio.images if os.path.isdir(self.studio.images) else None)
        if d:
            if not frame_numbers(d):
                messagebox.showinfo("Trace", "That folder has no frames (f01.png, f02.png ...).\n"
                                             "Open the video or images in Source and save frames with F.",
                                    parent=self.studio.root)
                return
            self.choose(os.path.normpath(d))

    # ---- the key frame picker
    @staticmethod
    def characters_of(folder):
        """The traced characters of a multi-character move (summary list), or None for a single-character move."""
        try:
            return project.status(folder).get("characters")
        except Exception:   # a list label only
            return None

    def characters_changed(self, bar):
        """The character bar changed (active character, list, flags): show that character's key frames."""
        if self.folder:
            self.choose(self.folder)

    def choose(self, folder, preselect=None, character=None):
        nums = frame_numbers(folder)
        if not nums:   # e.g. a trace.json dropped from a folder without frames (v1.1 crashed here)
            messagebox.showinfo("Trace", f"{os.path.basename(os.path.normpath(folder)) or folder} has no frames "
                                         "(f01.png, f02.png ...), so there's nothing to trace or play there.\n\n"
                                         "Pick a move on the left, or save frames in Source (F).",
                                parent=self.studio.root)
            return
        self.folder = os.path.normpath(folder)
        self.studio.set_folder(self.folder)
        self.charbar.load(self.folder, active=character)   # Phase 11: whose key frames are shown
        t = trace_file(self.folder)
        if self.charbar.multi:
            t = trace_io.find_file(os.path.dirname(chars.trace_path(self.folder, self.charbar.active)),
                                   trace_io.TRACE)
        saved = []
        if t:
            try:
                with open(t, encoding="utf-8") as fh:
                    import json
                    saved = [int(f) for f in json.load(fh)["frames"]]
            except (OSError, ValueError, KeyError, TypeError):
                saved = []
        self.saved = [f for f in saved if f in nums]
        self.selected = list(preselect) if preselect else list(self.saved)
        self.marks = None
        if self.charbar.multi:
            self.marks = []
            for c in chars.list_characters(self.folder):
                if c["visible"]:
                    fs = {f for f, _ in chars.keys(self.folder, c["id"])}
                    pt = trace_io.find_file(c["trace_dir"], trace_io.TRACE)
                    try:
                        fs |= {int(f) for f in trace_io.read_json(pt)["frames"]} if pt else set()
                    except (OSError, ValueError, KeyError, TypeError):
                        pass
                    self.marks.append((c["colour"], fs, c["id"] == self.charbar.active))
        n, done, total, fixed = move_status(self.folder)
        self.title.configure(text=os.path.basename(self.folder))
        rate, where = tp.find_fps(self.folder)
        if self.charbar.multi:   # Phase 11: the active character's progress
            done, total = self.charbar.cs.progress(self.charbar.active)
        self.sub.configure(text=f"{n} frames  ·  f{nums[0]:02d} to f{nums[-1]:02d}  ·  {rate:.3g} fps"
                                + (f"  ·  {self.charbar.active_entry()['name']}" if self.charbar.multi else "")
                                + (f"  ·  traced {done}/{total}" if total else "  ·  not traced yet"))
        self.load_thumbs()
        self.layout()
        self.refresh_list()
        self.update_bar()

    def load_thumbs(self):
        if self.folder in self.thumbs:
            return
        th = {}
        for f in frame_numbers(self.folder):
            try:
                im = Image.open(os.path.join(self.folder, f"f{f:02d}.png")).convert("RGB")
            except OSError:
                continue
            im.thumbnail((THUMB_W, THUMB_W * 2), Image.LANCZOS)
            th[f] = ImageTk.PhotoImage(im)
        self.thumbs[self.folder] = th

    def layout(self):
        g = self.grid
        g.delete("all")
        self.tiles = {}
        if not self.folder:
            g.create_text(max(g.winfo_width(), 200) / 2, 120, text="Pick a move on the left.", fill=hud.DIM,
                          font=hud.TITLE)
            return
        th = self.thumbs.get(self.folder, {})
        if not th:
            return
        W = max(g.winfo_width(), THUMB_W + 40)
        th_h = max(p.height() for p in th.values())
        cw, chh, gap = THUMB_W, th_h + 22, 12
        cols = max(1, (W - gap) // (cw + gap))
        x0 = (W - cols * (cw + gap) + gap) / 2
        for i, f in enumerate(sorted(th)):
            x = x0 + (i % cols) * (cw + gap)
            y = gap + (i // cols) * (chh + gap)
            self.tiles[f] = (x, y, x + cw, y + chh)
            g.create_rectangle(x - 1, y - 1, x + cw + 1, y + chh + 1, fill="#000000", outline=hud.LINE, tags=f"t{f}")
            g.create_image(x + cw / 2, y + th_h / 2, image=th[f])
            g.create_text(x + 6, y + th_h + 11, text=f"F{f:02d}", anchor="w", fill=hud.DIM, font=hud.TINY)
            self.draw_mark(f)
        rows = (len(th) + cols - 1) // cols
        g.configure(scrollregion=(0, 0, W, gap + rows * (chh + gap)))

    def draw_mark(self, f):
        g = self.grid
        g.delete(f"m{f}")
        x0, y0, x1, y1 = self.tiles[f]
        if f in self.selected:
            k = self.selected.index(f) + 1
            g.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1, outline=hud.RED, width=3, tags=f"m{f}")
            g.create_rectangle(x1 - 30, y1 - 20, x1, y1, fill=hud.RED, outline="", tags=f"m{f}")
            g.create_text(x1 - 15, y1 - 10, text=str(k), fill="#ffffff", font=hud.BOLD, tags=f"m{f}")
        if self.marks is not None:   # Phase 11: a dot per character traced on this frame, in its colour
            x = x0 + 6
            for colour, fs, active in self.marks:
                if f in fs:
                    r = 6 if active else 4
                    g.create_oval(x, y0 + 8 - r, x + 2 * r, y0 + 8 + r, fill=colour,
                                  outline="#ffffff" if active else "#000000", tags=f"m{f}")
                    x += 2 * r + 3
        elif f in self.saved:
            g.create_text(x0 + 6, y0 + 6, text="●", anchor="nw", fill=hud.GREEN, font=hud.SMALL, tags=f"m{f}")

    def on_click(self, e):
        x, y = self.grid.canvasx(e.x), self.grid.canvasy(e.y)
        for f, (x0, y0, x1, y1) in self.tiles.items():
            if x0 <= x <= x1 and y0 <= y <= y1:
                if f in self.selected:
                    self.selected.remove(f)
                else:
                    self.selected.append(f)
                for g in self.selected + [f]:
                    self.draw_mark(g)
                self.update_bar()
                return

    def select_all(self):
        if self.folder:
            self.selected = sorted(self.thumbs.get(self.folder, {}))
            self.layout()
            self.update_bar()

    def clear(self):
        self.selected = []
        if self.folder:
            self.layout()
        self.update_bar()

    def update_bar(self):
        n = len(self.selected)
        if not self.folder:
            self.sel_lbl.configure(text="")
        elif n:
            self.sel_lbl.configure(text=f"{n} key frames selected: " + ranges(sorted(self.selected))
                                   + "   ·   Start Tracing (Enter)")
        else:
            self.sel_lbl.configure(text="Select the key frames below.")
        has_trace = bool(self.folder and getattr(self, "saved", None))
        if self.folder and self.charbar.multi and n:   # Phase 11: whose key frames these are
            self.sel_lbl.configure(text=f"{self.charbar.active_entry()['name']}  ·  "
                                        + self.sel_lbl.cget("text"))
        self.start_btn.configure(state="normal" if n else "disabled")
        self.cont_btn.configure(state="normal" if has_trace else "disabled")
        self.play_btn.configure(state="normal" if has_trace else "disabled")
        tdir = self.active_dir()
        has_backups = bool(self.folder and (trace_io.list_backups(tdir) or trace_io.find_file(
            tdir, trace_io.TRACE) or trace_io.find_file(tdir, trace_io.FIXED)))
        self.backups_btn.configure(state="normal" if has_backups else "disabled")
        self.project_btn.configure(state="normal" if self.folder else "disabled")

    # ---- actions
    def active_dir(self):
        """The active character's trace folder (the move folder for a single-character move)."""
        if self.folder and self.charbar.multi:
            try:
                return self.charbar.cs.trace_dir(self.charbar.active)
            except chars.CharacterError:
                pass
        return self.folder

    def start(self):
        if self.folder and self.selected:
            self.studio.start_tracing(self.folder, sorted(self.selected), character=self.charbar.active)

    def continue_trace(self):
        if self.folder and self.saved:
            self.studio.start_tracing(self.folder, [], character=self.charbar.active)

    def play(self):
        if self.folder and self.saved:
            self.studio.open_player(self.folder, character=self.charbar.active)

    def open_backups(self, folder=None):
        """BACKUPS…: the active character's backups (folder given: that move's own trace, from PROJECT…)."""
        if folder is None and self.folder and self.charbar.multi:
            move = self.folder
            return RestoreDialog(self.studio.root, self.active_dir(), frames_dir=move,
                                 on_restored=lambda f: self.studio.trace_restored(move),
                                 title=f"{os.path.basename(move)} › {self.charbar.active_entry()['name']}")
        folder = folder or self.folder
        if folder:
            return RestoreDialog(self.studio.root, folder, on_restored=self.studio.trace_restored)

    def open_export(self):
        """EXPORT MOVES… (Phase 10): batch export; every traced move is ticked to start with."""
        from export_dialog import ExportDialog
        return ExportDialog(self.studio.root, self.studio.images, self.studio.prefs_path())

    def open_sprites(self):
        """SPRITE SHEET… (v3.0): the picked move's sprite sheets (PNG + JSON metadata)."""
        from spritesheet_dialog import SpriteSheetDialog
        return SpriteSheetDialog(self.studio.root, self.studio.images, "trace", self.folder)

    def open_project(self):
        """PROJECT… (Phase 9): status, check, protect, duplicate and whole-move backups of the picked move."""
        if self.folder:
            return ProjectDialog(self.studio.root, self.folder, self.studio.images,
                                 on_changed=lambda f: self.refresh_list(), on_open=self.choose,
                                 on_backups=self.open_backups)


# ---------------------------------------------------------------- the window
class Studio:
    def __init__(self, root, images, paths, settings_home=None, unity=None, screen=None):
        self.root, self.images = root, os.path.normpath(images)
        self.settings_home = settings_home or os.path.join(os.path.dirname(self.images), "Game Settings")
        self.unity = unity or ""
        self.settings = None
        self.settings_open = None    # a project .json or Unity folder to open when 04 first shows
        self.mode = None
        self.bound = []
        self.folder = None
        self.tracer = None
        self.player = None
        self.player_folder = None
        self.animate = None        # v3.0: 05 ANIMATE, made the first time it's shown
        hud.setup(root)
        root.title("Stickman Studio")
        root.minsize(1200, 720)
        try:
            root.state("zoomed")
        except tk.TclError:
            root.geometry("1500x900")

        # v3.3: a title bar like Paint's (Save, Undo, Redo, the open item, Help), then the five screens as tabs
        self.titlebar = ribbon.TitleBar(root, "Stickman Studio", self.quick_save, self.quick_undo, self.quick_redo,
                                        self.quick_menu, self.help_menu)
        self.titlebar.pack(fill="x", padx=12, pady=(6, 0))
        head = tk.Frame(root, bg=hud.BG)
        head.pack(fill="x", padx=12, pady=(6, 0))
        self.nav = {}
        # 4 Game Settings belongs to a Unity game: it only shows when a Unity project is set (--unity), or when one
        # (or a Game Settings project) is opened; everyone else sees Source, Trace, Review and Animate
        self.game_tab = bool(self.unity)
        for key, text in MODES:
            b = hud.Button(head, text, lambda k=key: self.show(k), padx=16, font=hud.BOLD)
            if key != "settings" or self.game_tab:
                b.pack(side="left", padx=(0, 4))
            ribbon.tooltip(b, MODE_TIPS[key])
            self.nav[key] = b
        self.move_lbl = hud.label(head, "", fg=hud.DIM, font=hud.SMALL)
        self.move_lbl.pack(side="right", padx=4)

        body = tk.Frame(root, bg=hud.BG)
        body.pack(fill="both", expand=True)
        self.pages = {}
        for key, _ in MODES:
            p = tk.Frame(body, bg=hud.BG)
            p.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[key] = p
        self.source = vt.App(root, [], self.images, parent=self.pages["source"], on_frames_saved=self.frames_saved)
        self.home = TraceHome(self.pages["trace"], self)
        self.home.frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.trace_box = None
        self.play_empty = hud.label(self.pages["play"], "", fg=hud.DIM, font=hud.TITLE, justify="center")
        self.play_empty.place(relx=0.5, rely=0.45, anchor="center")
        self.settings_msg = hud.label(self.pages["settings"], "", fg=hud.DIM, font=hud.TITLE, justify="center")
        self.settings_msg.place(relx=0.5, rely=0.45, anchor="center")

        for i, (key, _) in enumerate(MODES, 1):
            root.bind(f"<Control-Key-{i}>", lambda e, k=key: self.show(k))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<F1>", lambda e: self.start_tour())
        self.tour = None
        self.start(paths, screen)
        if not self.prefs().get("tour_seen"):
            root.after(900, self.start_tour)     # the first time: show the tour

    # ---- v3.3: the title bar's quick commands act on the screen that's showing
    def screen_obj(self):
        return {"source": self.source, "trace": self.tracer or self.home, "play": self.player,
                "settings": self.settings, "animate": self.animate}.get(self.mode)

    def quick(self, name):
        """(function or None) for "save" / "undo" / "redo" on this screen."""
        o = self.screen_obj()
        if o is None:
            return None
        if self.mode == "trace" and self.tracer:
            return {"save": o.save, "undo": o.do_undo, "redo": o.do_redo}[name]
        if self.mode == "animate":
            return {"save": o.save, "undo": o.undo, "redo": o.redo}[name]
        if self.mode == "settings":
            return {"save": getattr(o, "save", None), "undo": None, "redo": None}[name]
        if self.mode == "play":
            return {"save": getattr(o, "save_fixed", None), "undo": None, "redo": None}[name]
        return None

    def quick_save(self):
        fn = self.quick("save")
        fn and fn()

    def quick_undo(self):
        fn = self.quick("undo")
        fn and fn()

    def quick_redo(self):
        fn = self.quick("redo")
        fn and fn()

    def refresh_titlebar(self):
        if not hasattr(self, "titlebar"):
            return
        self.titlebar.set_enabled(save=bool(self.quick("save")), undo=bool(self.quick("undo")),
                                  redo=bool(self.quick("redo")))
        doc = None
        if self.mode == "animate" and self.animate and self.animate.proj:
            doc = self.animate.proj.doc["name"]
        elif self.folder and self.mode in ("trace", "play"):
            doc = os.path.basename(self.folder)
        screen = dict(MODES)[self.mode].split(maxsplit=1)[1] if self.mode else None
        self.titlebar.set_title(f"{doc}  ·  {screen}" if doc else screen)

    def quick_menu(self):
        return [("Open Images Folder", self.open_images), None, ("Guided Tour", self.start_tour, "F1"),
                ("Keyboard Shortcuts", self.show_shortcuts)]

    def help_menu(self):
        return [("Guided Tour", self.start_tour, "F1"), ("Keyboard Shortcuts", self.show_shortcuts),
                ("Tutorial", self.open_tutorial), None, (f"About Stickman Studio {VERSION}", self.about)]

    def show_shortcuts(self):
        d = tk.Toplevel(self.root, bg=hud.PANEL, padx=18, pady=14)
        d.title("Keyboard shortcuts")
        d.transient(self.root)
        name = dict(MODES)[self.mode].split(maxsplit=1)[1]
        hud.Header(d, f"{name} screen", bg=hud.PANEL).pack(fill="x")
        grid = tk.Frame(d, bg=hud.PANEL)
        grid.pack(fill="x", pady=(8, 0))
        for r, (k, what) in enumerate(SHORTCUTS.get(self.mode, [])):
            tk.Label(grid, text=k, bg=hud.PANEL, fg=hud.AMBER, font=(hud.MONO, 9), anchor="w").grid(
                row=r, column=0, sticky="w", padx=(0, 16), pady=1)
            tk.Label(grid, text=what, bg=hud.PANEL, fg=hud.TEXT, font=hud.SMALL, anchor="w").grid(row=r, column=1,
                                                                                                 sticky="w")
        tk.Label(d, text="Ctrl+1 … Ctrl+5 switch screens · F1 starts the guided tour", bg=hud.PANEL, fg=hud.DIM,
                 font=hud.SMALL).pack(anchor="w", pady=(10, 0))
        hud.Button(d, "Close", d.destroy).pack(anchor="e", pady=(10, 0))
        return d

    def open_tutorial(self):
        top = os.path.dirname(self.images)
        for p in (os.path.join(top, "TUTORIAL_TRACING.md"),
                  os.path.join(os.path.dirname(top), "Stick fights animation", "TUTORIAL_TRACING.md")):
            if os.path.isfile(p):
                os.startfile(os.path.normpath(p))
                return
        messagebox.showinfo("Tutorial", "The tutorial (TUTORIAL_TRACING.md) wasn't found.", parent=self.root)

    def about(self):
        messagebox.showinfo("About", f"Stickman Studio {VERSION}\n\nTrace reference moves, review them as the "
                                     "game's stickman, set up the game, and animate. No AI: everything is manual "
                                     "tracing, geometry and image processing.", parent=self.root)

    # ---- screens
    def show(self, mode):
        if mode == self.mode or (mode == "settings" and not self.game_tab):
            return
        if self.mode == "source":
            self.source.pause()
        if self.mode == "play" and self.player:
            self.player.pause()
        if self.mode == "animate" and self.animate:
            self.animate.leave()
        self.mode = mode
        for k, b in self.nav.items():
            b.set_kind("red" if k == mode else "normal")
        if mode == "play" and (self.player is None or self.player_folder != self.folder):
            self.open_player(self.folder, switch=False)
        if mode == "settings" and self.settings is None:
            self.open_settings()
        if mode == "animate" and self.animate is None:
            from animate_tab import AnimateTab
            self.animate = AnimateTab(self.pages["animate"], self)
            self.animate.frame_ui.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.pages[mode].tkraise()
        self.set_folder(self.folder)
        self.bind_keys()
        self.refresh_titlebar()

    def bind_keys(self):
        for seq in self.bound:
            self.root.unbind(seq)
        if self.mode == "source":
            km = self.source.keymap
        elif self.mode == "trace":
            km = self.tracer.keymap if self.tracer else self.home.keymap
        elif self.mode == "settings":
            km = self.settings.keymap if self.settings else {}
        elif self.mode == "animate":
            km = self.animate.keymap if self.animate else {}
        else:
            km = self.player.keymap if self.player else {}
        for seq, fn in km.items():
            self.root.bind(seq, fn)
        self.bound = list(km)
        self.refresh_titlebar()   # v3.3: the editor opened or closed: Save / Undo / Redo follow

    def set_folder(self, folder):
        self.folder = folder
        if folder and self.mode in ("trace", "play", None):   # v3.3: the move's status only where it matters
            n, done, total, fixed = move_status(folder)
            self.move_lbl.configure(text=f"Move: {os.path.basename(folder)}   ·   {n} frames"
                                         + (f"   ·   {done} of {total} key frames traced" if total else ""))
        else:
            self.move_lbl.configure(text="")
        self.refresh_titlebar()

    def open_images(self):
        os.makedirs(self.images, exist_ok=True)
        os.startfile(self.images)

    # ---- 01 -> 02
    def frames_saved(self, folder, count, moved):
        self.home.choose(folder)
        self.show("trace")
        note = f"Saved {count} frames." + (f" The old ones are in {os.path.basename(moved)}." if moved else "")
        self.home.sub.configure(text=note + "  Now select the key frames below.")

    # ---- 02: tracing
    def character_dir(self, folder, character=None):
        """(character id or None, its trace folder) for a move: the active character of a multi-character move."""
        if not folder or not chars.is_multi(folder):
            return None, folder
        cid = character or (self.home.charbar.active if self.home.folder and os.path.normcase(self.home.folder)
                            == os.path.normcase(folder) else None)
        try:
            cs = chars.CharacterSet.open(folder)
            cid = cid if cid in cs.ids() else cs.active
            return cid, cs.trace_dir(cid)
        except chars.CharacterError:
            return None, folder

    def start_tracing(self, folder, nums, character=None):
        cid, tdir = self.character_dir(folder, character)   # Phase 11: the character being traced
        if trace_io.protected(tdir):   # Phase 9: a protected trace is only changed after you say so
            choice = tp.ask_choice(
                self.root, "Protected move",
                f"{os.path.basename(folder)} is protected: its trace.json is read-only, so the editor can't save "
                "changes to it.\n\nTrace a copy of the move instead (the original stays as it is), or unprotect it "
                "and edit it?", ["Trace a copy", "Unprotect and edit", "Cancel"], 0)
            if choice == 0:
                try:
                    folder = project.duplicate(folder, project.copy_name(folder))
                except (OSError, ValueError) as err:
                    messagebox.showinfo("Trace", f"No copy was made: {err}", parent=self.root)
                    return
            elif choice == 1:
                try:
                    if cid and cid != chars.PRIMARY:
                        trace_io.set_protected(tdir, False)
                    else:
                        project.unprotect(folder)
                except (OSError, ValueError) as err:
                    messagebox.showinfo("Trace", f"It couldn't be unprotected: {err}", parent=self.root)
                    return
            else:
                return
            self.home.refresh_list()
            cid, tdir = self.character_dir(folder, cid)
        try:
            frames, states, out, notes = tc.open_session(folder, nums, trace_dir=tdir)
        except ValueError as err:
            messagebox.showinfo("Trace", str(err), parent=self.root)
            return
        cast = None
        if cid:   # Phase 11: every other character is loaded too (drawn underneath, switchable)
            cs = chars.CharacterSet.open(folder)
            cast = {"active": cid, "characters": cs.characters,
                    "sessions": {c["id"]: tc.new_session(folder, cs.trace_dir(c["id"]))
                                 for c in cs.characters if c["id"] != cid}}
        self.close_tracer(save=True)
        self.trace_box = tk.Frame(self.pages["trace"], bg=hud.BG)
        self.trace_box.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.tracer = tc.App(self.root, folder, frames, states, out, parent=self.trace_box,
                             on_play=lambda t: self.open_player(t.dir, live=t),
                             on_finish=self.finished, on_back=lambda t: self.back_to_moves(), cast=cast)
        if self.tracer.history_note:
            notes.append(self.tracer.history_note)
        if notes:
            self.tracer.msg("  ".join(notes))
        self.set_folder(folder)
        self.mode = None
        self.show("trace")

    def close_tracer(self, save=True):
        if self.tracer:
            if save:
                self.tracer.save()
            self.tracer.release()   # Phase 9: write the undo history now, close the History window
            if self.player and self.player_folder == self.tracer.dir:
                self.player_folder = None     # it read the live points: reopen it from the file next time
            self.tracer = None
        if self.trace_box:
            self.trace_box.destroy()
            self.trace_box = None

    def back_to_moves(self):
        folder = self.tracer.dir if self.tracer else self.folder
        self.close_tracer()
        self.home.choose(folder)
        self.home.frame.tkraise()
        self.mode = None
        self.show("trace")

    def finished(self, tracer, complete):
        folder, tdir, cid = tracer.dir, tracer.tdir, tracer.active
        self.close_tracer(save=False)
        self.home.choose(folder, character=cid)
        self.home.frame.tkraise()
        if complete:
            check = os.path.join(tdir, "trace_check.png")
            if os.path.exists(check):
                os.startfile(check)
        self.open_player(folder, character=cid)

    def trace_restored(self, folder):
        """A backup was put back (BACKUPS… in 02): reload the move, and make 03 read the file again."""
        if self.player_folder and os.path.normcase(self.player_folder) == os.path.normcase(folder):
            self.player_folder = None
        self.home.choose(folder)   # (also redraws the move list, whose status follows the files)

    # ---- 03: the player
    def open_player(self, folder, live=None, switch=True, character=None):
        for w in self.pages["play"].winfo_children():
            if w is not self.play_empty:
                w.destroy()
        self.player = None
        self.player_folder = folder
        trace = trace_file(folder) if folder else None
        cid, tdir = self.character_dir(folder, character or (live.active if live is not None and
                                                             getattr(live, "cast", None) else None))
        if cid:   # Phase 11: a traced character's own trace (and fixed trace, key poses)
            trace = trace_io.find_file(tdir, trace_io.TRACE)
        if not folder or (not live and not trace):
            self.play_empty.configure(text="Nothing to review yet\n\nSelect a move in Trace and trace it."
                                      if not folder else f"{os.path.basename(folder)} hasn't been traced yet\n\n"
                                      "Select its key frames in Trace.")
            self.play_empty.lift()
        else:
            box = tk.Frame(self.pages["play"], bg=hud.BG)
            box.place(relx=0, rely=0, relwidth=1, relheight=1)
            get = live.keys_now if live else tp.file_keys(trace)
            title = os.path.basename(folder) + (f" › {chars.CharacterSet.open(folder).get(cid)['name']}"
                                                if cid else "")
            pcast = None
            if cid:   # Phase 11: the other visible characters play together with this one
                listed = chars.list_characters(folder)
                others = []
                for c in listed:
                    t = trace_io.find_file(c["trace_dir"], trace_io.TRACE)
                    if c["id"] != cid and c["visible"] and t:
                        others.append({"id": c["id"], "name": c["name"], "colour": c["colour"],
                                       "tdir": c["trace_dir"], "trace": t})
                pcast = {"active": cid, "ids": [(c["id"], c["name"]) for c in listed], "others": others}
            self.player = tp.Player(box, folder, get, title, embedded=True, trace_dir=tdir, cast=pcast,
                                    on_character=lambda c, f=folder: self.player_character(f, c))
        if switch:
            self.mode = None
            self.show("play")
        elif self.mode == "play":
            self.bind_keys()

    def player_character(self, folder, cid):
        """03's character picker: play / fix / analyse another character of the move (it becomes the active one)."""
        if self.home.folder and os.path.normcase(self.home.folder) == os.path.normcase(folder):
            self.home.charbar.click(cid)
        self.open_player(folder, character=cid)

    # ---- 04: Game Settings
    def open_settings(self):
        if GS_DIR not in sys.path:
            sys.path.insert(0, GS_DIR)
        try:
            import game_settings as gs
        except ImportError as err:
            self.settings_msg.configure(text=f"Game Settings isn't installed\n\n{err}")
            return
        box = tk.Frame(self.pages["settings"], bg=hud.BG)
        box.place(relx=0, rely=0, relwidth=1, relheight=1)
        os.makedirs(self.settings_home, exist_ok=True)
        self.settings = gs.App(self.root, self.settings_home, self.unity, self.settings_open, parent=box,
                               on_preview=self.preview_folder, on_open_source=self.open_in_source,
                               images=self.images)

    def preview_folder(self, folder):
        """Game Settings' Preview: show that move in 03 PLAY / FIX (Phase 11: or that traced character of it)."""
        move, cid = chars.locate(folder)
        if move:
            self.home.choose(move, character=cid)
            self.open_player(move, character=cid)
            return
        self.home.choose(folder)
        self.open_player(folder)

    def open_in_source(self, path):
        self.show("source")
        self.source.open([path])

    # ---- the guided tour
    def prefs_path(self):
        return os.path.join(self.settings_home, "studio.json")

    def prefs(self):
        try:
            with open(self.prefs_path(), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def start_tour(self):
        if self.tour is None:
            self.tour = Tour(self)
        self.tour.start()

    def tour_done(self):
        p = self.prefs()
        if not p.get("tour_seen"):
            p["tour_seen"] = True
            try:
                os.makedirs(self.settings_home, exist_ok=True)
                with open(self.prefs_path(), "w", encoding="utf-8") as fh:
                    json.dump(p, fh)
            except OSError:
                pass

    def enable_game_tab(self):
        """Show 4 Game Settings (hidden until a Unity project or a Game Settings project is in use)."""
        if not self.game_tab:
            self.game_tab = True
            self.nav["settings"].pack(side="left", padx=(0, 4), before=self.nav["animate"])

    # ---- start-up and closing
    def start(self, paths, screen=None):
        paths = [os.path.normpath(p) for p in paths]
        if not paths:
            self.show(screen if screen in dict(MODES) else "source")
            return
        first = paths[0]
        base = os.path.basename(first)
        in_backups = os.path.basename(os.path.dirname(first)).lower() == trace_io.BACKUP_DIR
        move, character = chars.locate(first)   # Phase 11: inside <move>\characters\
        if move:
            self.home.choose(move, character=character)
            self.show("trace")
        elif (base.lower().endswith(".json") and base.lower() not in trace_io.TRACE_JSON and not in_backups) or \
                (os.path.isdir(first) and os.path.isdir(os.path.join(first, "Assets"))):
            self.settings_open = first     # a Game Settings project, or a Unity project to read
            self.enable_game_tab()
            self.show("settings")
        elif os.path.isdir(first) and frame_numbers(first):
            self.home.choose(first)
            self.show("trace")
        elif base.lower() in trace_io.TRACE_JSON | {"all.png"}:
            self.home.choose(os.path.dirname(first))
            self.show("trace")
        elif base.lower().endswith(".json") and in_backups:
            # a dated backup, or another file of a move's backups folder (checkpoints.json): its move
            self.home.choose(os.path.dirname(os.path.dirname(first)))
            self.show("trace")
        elif all(FRAME.match(os.path.basename(p)) for p in paths) and \
                len({os.path.dirname(p) for p in paths}) == 1:
            self.home.choose(os.path.dirname(first),
                             preselect=sorted(int(FRAME.match(os.path.basename(p)).group(1)) for p in paths))
            self.show("trace")
        else:
            self.show("source")
            if self.source.open(paths):
                stem = os.path.join(self.images, self.source.src.name)
                if os.path.isdir(stem) and frame_numbers(stem):
                    self.home.choose(stem)   # already has frames: ready in 02 TRACE

    def close(self):
        if self.tour:
            self.tour.end(quiet=True)
        self.close_tracer(save=True)
        if self.settings:
            self.settings.close()
        if self.player:
            self.player.pause()
        if self.animate:
            self.animate.leave()
        self.source.quit()
        self.root.destroy()


def main(args):
    images = settings = unity = screen = icon = None
    rest = []
    i = 0
    while i < len(args):
        if args[i] in ("--images", "--settings", "--unity", "--screen", "--icon") and i + 1 < len(args):
            value = args[i + 1].strip().strip('"')
            if args[i] == "--images":
                images = value
            elif args[i] == "--settings":
                settings = value
            elif args[i] == "--unity":
                unity = value
            elif args[i] == "--icon":
                icon = value
            else:
                screen = value
            i += 2
        else:
            rest.append(args[i].strip().strip('"'))
            i += 1
    if not images:   # a fresh install keeps its work in Documents\Stickman Studio (never inside Program Files)
        images = os.path.join(os.path.expanduser("~"), "Documents", "Stickman Studio", "Images")
    os.makedirs(images, exist_ok=True)
    paths = [os.path.abspath(p) for p in rest if p]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        print("Can't find:", *missing, sep="\n  ")
        return 1
    try:   # sharp (not blurry) window on scaled Windows displays
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    icon = icon or os.path.join(HERE, "studio.ico")
    if os.path.exists(icon):
        try:
            root.iconbitmap(default=icon)    # the window and taskbar icon
        except tk.TclError:
            pass
    Studio(root, images, paths, settings, unity, screen)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

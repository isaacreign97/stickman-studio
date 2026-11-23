"""Video Tool: step through a video (or GIF, or images) frame by frame, like VLC, and save any part of it
as PNG frames (f01.png, f02.png, ... in a named folder such as Images\\jumping) or as a GIF.

usage: python -I video_tool.py [--images DIR] [video | gif | image files | image folder]
Screen 01 SOURCE of Stickman Studio (studio.py); also runs on its own.
--images DIR is the home folder for frames and GIFs (the .bat passes "Images" next to itself).

Keys:  Right / Left  (or . / ,  or E)  = one frame forward / back      Shift+arrow = 10 frames
       Space = play / pause      [ / ] = slower / faster      Home / End = first / last frame
       I = start here      O = end here      C = clear start / end
       F = save frames as PNG (f01, f02, ...)      G = make GIF      Ctrl+O = open
Mouse: wheel on the picture = step frames      click or drag the timeline = jump there
Needs OpenCV for videos:  python -m pip install opencv-python-headless
"""
import collections
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence, ImageTk

try:
    import cv2
except ImportError:
    cv2 = None

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".jfif", ".bmp", ".webp", ".tif", ".tiff", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".3gp"}
OPEN_TYPES = [("Videos, GIFs and images", " ".join("*" + e for e in sorted(VIDEO_EXT | IMAGE_EXT))),
              ("All files", "*.*")]
FRAME_FILE = re.compile(r"^f(\d+)\.png$", re.IGNORECASE)
TRACE_FILES = {"all.png", "trace.json", "trace_backup.json", "trace_check.png", "timing.json", "trace_fixed.json",
               # upgrade side files and folders: they belong to the trace, so they move with it into "old <date>"
               "trace_history.json", "key_poses.json", "backups",
               # Phase 11: every traced character goes with the frames, never left pointing at new ones
               "characters.json", "characters"}
BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
SPEEDS = [0.1, 0.25, 0.5, 1.0, 1.5, 2.0]
CACHE = 40               # decoded frames kept for fast stepping back
CACHE_BOX = (1600, 1000)  # cached frames are shrunk to fit this (display only; saving reads full size)
RATES = [50, 30, 25, 24, 20, 15, 12, 10, 8, 5]
WIDTHS = [1280, 960, 720, 640, 480, 360, 320]
IMAGE_FPS = 12           # how fast a set of still images plays
sys.path.insert(0, HERE)   # python -I leaves the script's folder out
import hud  # noqa: E402

BG = hud.BG
BAR = hud.PANEL
FONT = hud.FONT


def clock(sec):
    m, s = divmod(max(0.0, sec), 60)
    return f"{int(m)}:{s:05.2f}"


def natural(path):
    """Sort key so photo2.jpg comes before photo10.jpg."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", os.path.basename(path))]


def flatten(im):
    """Any image -> RGB, transparent parts on white."""
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.getchannel("A"))
        return bg
    return im.convert("RGB")


def load_image(path):
    with Image.open(path) as im:
        return flatten(ImageOps.exif_transpose(im))


def is_animated(path):
    try:
        with Image.open(path) as im:
            return getattr(im, "n_frames", 1) > 1
    except OSError:
        return False


class Source:
    """Frames by number: get(n) for the screen, full(numbers) for saving."""
    kind = "video"
    count = 0

    def __init__(self):
        self.cache = collections.OrderedDict()

    def get(self, n):
        n = max(0, min(n, self.count - 1))
        if n in self.cache:
            self.cache.move_to_end(n)
            return self.cache[n]
        img = self.read(n)
        if img is None:
            return None
        img = img.copy()
        img.thumbnail(CACHE_BOX, Image.BILINEAR)
        self.cache[n] = img
        while len(self.cache) > CACHE:
            self.cache.popitem(last=False)
        return img

    def close(self):
        pass


class Video(Source):
    """Reads frames by number. Reading forward is sequential; jumping back seeks."""

    def __init__(self, path):
        super().__init__()
        if cv2 is None:
            raise OSError("Reading videos needs OpenCV. Install it once with:\n"
                          "python -m pip install opencv-python-headless")
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.where = os.path.dirname(path)
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise OSError("This video can't be opened.")
        fps = self.cap.get(cv2.CAP_PROP_FPS) or 0
        self.fps = fps if 1 <= fps <= 240 else 30.0
        self.w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if self.count <= 0:   # some files don't say: count them
            while self.cap.grab():
                self.count += 1
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self.pos = 0          # the frame the next read() returns (-1 = unknown)
        if self.count <= 0 or self.get(0) is None:
            raise OSError("No frames could be read from this file.")

    def read(self, n):
        if n != self.pos:
            if 0 <= self.pos < n <= self.pos + 30:   # short hop forward: decoding is faster than seeking
                while self.pos < n and self.cap.grab():
                    self.pos += 1
            if n != self.pos:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, n)
                self.pos = n
        ok, bgr = self.cap.read()
        if not ok:              # the file said it had more frames than it has
            self.pos = -1
            if n == 0:
                return None
            self.count = n
            return self.get(n - 1)
        self.pos = n + 1
        return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

    def full(self, numbers):
        cap = cv2.VideoCapture(self.path)
        want = set(numbers)
        cap.set(cv2.CAP_PROP_POS_FRAMES, numbers[0])
        n = numbers[0]
        while n <= numbers[-1]:
            ok, bgr = cap.read()
            if not ok:
                break
            if n in want:
                yield Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            n += 1
        cap.release()

    def close(self):
        self.cap.release()


class Stills(Source):
    """A set of image files (played in name order), or the frames of one animated GIF / WebP / PNG."""
    kind = "images"

    def __init__(self, paths, folder=None):
        super().__init__()
        self.frames = None
        if len(paths) == 1 and is_animated(paths[0]):
            self.path = paths[0]
            self.name = os.path.splitext(os.path.basename(paths[0]))[0]
            with Image.open(paths[0]) as im:
                self.frames, total = [], 0
                for f in ImageSequence.Iterator(im):
                    self.frames.append(flatten(f.copy()))
                    total += f.info.get("duration") or 100
            self.kind = "animation"
            self.fps = min(50.0, max(1.0, 1000 * len(self.frames) / max(1, total)))
            self.files = []
            self.count = len(self.frames)
        else:
            self.files = sorted(paths, key=natural)
            self.path = folder or self.files[0]
            self.name = os.path.basename(folder) if folder else os.path.splitext(os.path.basename(self.files[0]))[0]
            self.fps = float(IMAGE_FPS)
            self.count = len(self.files)
        self.where = folder or os.path.dirname(self.path)
        if self.frames is None:
            try:
                load_image(self.files[0])
            except OSError:
                raise OSError(f"{os.path.basename(self.files[0])} can't be read as an image.")
        self.w, self.h = self.read(0).size
        self.get(0)

    def read(self, n):
        if self.frames is not None:
            return self.frames[n]
        try:
            return load_image(self.files[n])
        except OSError:   # a broken file in the set: show a dark red frame instead of stopping
            return Image.new("RGB", (getattr(self, "w", 640), getattr(self, "h", 360)), "#800000")

    def full(self, numbers):
        for n in numbers:
            yield self.read(n)


def open_source(paths):
    """Work out what was dropped / picked and open it."""
    paths = [os.path.abspath(p) for p in paths]
    if len(paths) == 1 and os.path.isdir(paths[0]):
        folder = paths[0]
        files = [os.path.join(folder, n) for n in os.listdir(folder)
                 if os.path.splitext(n)[1].lower() in IMAGE_EXT and n.lower() not in TRACE_FILES]
        if not files:
            raise OSError(f"There are no images in {os.path.basename(folder)}.")
        return Stills(files, folder)
    ext = [os.path.splitext(p)[1].lower() for p in paths]
    if len(paths) == 1 and ext[0] not in IMAGE_EXT:
        return Video(paths[0])
    if any(e not in IMAGE_EXT for e in ext):
        raise OSError("Open one video at a time, or only images.")
    if len(paths) > 1 and any(is_animated(p) for p in paths):
        raise OSError("Open one GIF at a time (or only still images).")
    return Stills(paths)


class App:
    """The frame-by-frame player. On its own it fills the window; inside Stickman Studio it lives in a panel
    (parent=...) and its keys are collected in self.keymap, which the studio binds while this screen shows."""

    def __init__(self, root, paths, images_dir, parent=None, on_frames_saved=None):
        self.root = root
        self.embedded = parent is not None
        self.box = parent if parent is not None else root
        self.on_frames_saved = on_frames_saved
        self.images_dir = images_dir
        self.src = None
        self.frame = None
        self.n = 0
        self.a = self.b = None     # start / end frame for saving
        self.playing = False
        self.speed = 1.0
        self.tick_id = None
        self.photo = None
        self.drag_target = None
        self.flash_id = None
        self.keymap = {}
        if not self.embedded:
            hud.setup(root)
            root.minsize(1100, 640)
            try:
                root.state("zoomed")
            except tk.TclError:
                root.geometry("1400x850")
        box = self.box

        import ribbon   # v3.3: open / range / save in a ribbon; the side shows what's open and the range
        rb = self.ribbon = ribbon.Ribbon(box, [("Open File…", self.open_dialog, "Ctrl+O"),
                                               ("Open Folder of Images…", self.open_folder_dialog), None,
                                               ("Open Images Folder", self.show_images_dir)])
        rb.pack(fill="x", padx=12, pady=(8, 0))
        g = rb.tab("Home").group("Open")
        self.open_btn = g.button("Open File…", self.open_dialog, "A video, a GIF or images (Ctrl+O)")
        g.button("Open Folder…", self.open_folder_dialog, "A folder of images")
        g = rb.tab("Home").group("Range")
        g.button("Set Start", self.set_start, "The move starts on this frame (I)")
        g.button("Set End", self.set_end, "The move ends on this frame (O)")
        g.button("Clear", self.clear_range, "Use the whole source (C)")
        g = rb.tab("Home").group("Save")
        self.save_btn = g.button("Save Frames as PNG", lambda: self.save_dialog("frames"),
                                 "Save the range as numbered PNG frames, ready to trace (F)", kind="red")
        g.button("Make GIF", lambda: self.save_dialog("gif"), "Save the range as a looping GIF (G)")
        g.button("Save This Frame", self.save_frame, "Save the current frame as a picture (S)")

        main = tk.Frame(box, bg=hud.BG)
        main.pack(fill="both", expand=True, padx=12, pady=(10, 0))
        side = tk.Frame(main, bg=hud.BG, width=262)
        side.pack(side="right", fill="y", padx=(14, 0))
        side.pack_propagate(False)
        screen = hud.panel(main, bg="#000000")
        screen.pack(side="left", fill="both", expand=True)
        self.view = tk.Canvas(screen, bg="#000000", highlightthickness=0)
        self.view.pack(fill="both", expand=True)
        self.img_id = self.view.create_image(0, 0, anchor="center")
        self.view.bind("<Configure>", lambda e: self.render())
        self.view.bind("<MouseWheel>", lambda e: self.step(-1 if e.delta > 0 else 1))

        hud.Header(side, "Source").pack(fill="x")
        self.name_lbl = hud.label(side, "Nothing open", font=hud.BOLD, anchor="w", justify="left", wraplength=250)
        self.name_lbl.pack(fill="x", pady=(6, 0))
        gauges = tk.Frame(side, bg=hud.BG)
        gauges.pack(pady=(8, 2))
        self.g_frame = hud.Gauge(gauges, size=110, label="frame")
        self.g_frame.pack(side="left")
        self.g_time = hud.Gauge(gauges, size=110, label="seconds")
        self.g_time.pack(side="left", padx=(12, 0))
        self.facts = hud.label(side, "", fg=hud.DIM, font=(hud.MONO, 9), anchor="w", justify="left")
        self.facts.pack(fill="x")

        hud.Header(side, "Range", "Set Start and Set End mark the part of the move you want (I / O).").pack(
            fill="x", pady=(16, 0))
        self.range_lbl = hud.label(side, "", fg=hud.AMBER, font=hud.SMALL, anchor="w", justify="left",
                                   wraplength=250)
        self.range_lbl.pack(fill="x", pady=(4, 4))
        self.range_lbl.bind("<Button-1>", self.show_saved)
        self.range_row = tk.Frame(side, bg=hud.BG)
        self.range_row.pack(fill="x")

        self.line = tk.Canvas(box, height=38, bg=hud.BG, highlightthickness=0, cursor="hand2")
        self.line.pack(fill="x", padx=12, pady=(8, 0))
        self.line.bind("<Configure>", lambda e: self.draw_line())
        self.line.bind("<Button-1>", self.on_line)
        self.line.bind("<B1-Motion>", self.on_line)

        bar = tk.Frame(box, bg=hud.BG)
        bar.pack(fill="x", padx=12, pady=(4, 2))
        for text, cmd in (("⏮", lambda: self.go(0)), ("◀", lambda: self.step(-1))):
            hud.Button(bar, text, cmd, padx=10).pack(side="left", padx=(0, 4))
        self.play_btn = hud.Button(bar, "▶  Play", self.toggle, kind="red", padx=16)
        self.play_btn.pack(side="left", padx=(0, 4))
        for text, cmd in (("▶", lambda: self.step(1)),
                          ("⏭", lambda: self.go(self.src.count - 1 if self.src else 0))):
            hud.Button(bar, text, cmd, padx=10).pack(side="left", padx=(0, 4))
        hud.label(bar, "   Speed", fg=hud.DIM, font=hud.SMALL).pack(side="left")
        self.speed_box = ttk.Combobox(bar, width=6, state="readonly", takefocus=False,
                                      values=[f"{s:g}×" for s in SPEEDS])
        self.speed_box.set("1×")
        self.speed_box.bind("<<ComboboxSelected>>", self.on_speed)
        self.speed_box.pack(side="left", padx=4)
        self.info = hud.label(bar, "", font=(hud.MONO, 10), fg=hud.TEXT)
        self.info.pack(side="right")

        tk.Frame(box, bg=hud.BG, height=6).pack(fill="x")

        keys = {
            "<Right>": lambda e: self.step(1), "<Left>": lambda e: self.step(-1),
            "<period>": lambda e: self.step(1), "<comma>": lambda e: self.step(-1),
            "<Shift-Right>": lambda e: self.step(10), "<Shift-Left>": lambda e: self.step(-10),
            "<space>": lambda e: self.toggle(), "<Home>": lambda e: self.go(0),
            "<End>": lambda e: self.go(self.src.count - 1 if self.src else 0),
            "<bracketleft>": lambda e: self.change_speed(-1), "<bracketright>": lambda e: self.change_speed(1),
            "<Control-o>": lambda e: self.open_dialog(),
        }
        for ch, f in {"e": lambda e: self.step(1), "i": lambda e: self.set_start(), "o": lambda e: self.set_end(),
                      "c": lambda e: self.clear_range(), "f": lambda e: self.save_dialog("frames"),
                      "s": lambda e: self.save_frame(), "g": lambda e: self.save_dialog("gif")}.items():
            keys[f"<KeyPress-{ch}>"] = f
            keys[f"<KeyPress-{ch.upper()}>"] = f
        self.keymap = keys
        if not self.embedded:
            for k, f in keys.items():
                root.bind(k, f)
            root.protocol("WM_DELETE_WINDOW", self.quit)

        self.empty_labels()
        if paths:
            self.open(paths)
        elif not self.embedded:
            root.after(100, self.open_dialog)

    # ---- opening -------------------------------------------------------------
    def start_dir(self):
        return self.src.where if self.src else self.images_dir

    def open_dialog(self):
        self.pause()
        paths = filedialog.askopenfilenames(parent=self.root, title="Open a video, a GIF or images",
                                            initialdir=self.start_dir(), filetypes=OPEN_TYPES)
        if paths:
            self.open(list(paths))
        elif not self.src and not self.embedded:
            self.quit()

    def open_folder_dialog(self):
        self.pause()
        folder = filedialog.askdirectory(parent=self.root, title="Open a folder of images",
                                         initialdir=self.start_dir())
        if folder:
            self.open([folder])

    def show_images_dir(self):
        os.makedirs(self.images_dir, exist_ok=True)
        os.startfile(self.images_dir)

    def open(self, paths):
        self.pause()
        try:
            src = open_source(paths)
        except OSError as err:
            messagebox.showerror("Open", f"Can't open {os.path.basename(paths[0])}\n\n{err}", parent=self.root)
            if not self.src and not self.embedded:
                self.root.after(10, self.open_dialog)
            return False
        if self.src:
            self.src.close()
        self.src = src
        self.a = self.b = None
        what = os.path.basename(src.path) if src.kind != "images" or len(src.files) == 1 else \
            f"{src.name} ({src.count} images)"
        self.name_lbl.configure(text=what)
        if not self.embedded:
            self.root.title(f"Video Tool - {what}")
        self.show(0)
        return True

    def empty_labels(self):
        self.g_frame.set(0, 1, "–", "frame")
        self.g_time.set(0, 1, "–", "seconds")
        self.facts.configure(text="")
        self.range_lbl.configure(text="")
        self.info.configure(text="")

    # ---- moving --------------------------------------------------------------
    def show(self, n):
        if not self.src:
            return
        self.n = max(0, min(n, self.src.count - 1))
        self.frame = self.src.get(self.n)
        self.n = min(self.n, self.src.count - 1)
        self.render()
        self.draw_line()
        self.update_labels()

    def go(self, n):
        self.pause()
        self.show(n)

    def step(self, d):
        if self.src:
            self.go(self.n + d)

    def render(self):
        cw, ch = self.view.winfo_width(), self.view.winfo_height()
        if cw < 2 or ch < 2:
            return
        self.view.delete("empty")
        if not self.src or self.frame is None:
            self.view.itemconfigure(self.img_id, image="")
            self.view.create_text(cw / 2, ch / 2 - 16, text="No source open", fill=hud.RED, font=(hud.F_SEMI, 16),
                                  tags="empty")
            self.view.create_text(cw / 2, ch / 2 + 18, fill=hud.DIM, font=hud.FONT, justify="center", tags="empty",
                                  text="Open a video, a GIF or images with Open File… (Ctrl+O),\n"
                                       "or drag them onto Stickman Studio.bat.")
            return
        fw, fh = self.frame.size
        scale = min(cw / fw, ch / fh)
        size = (max(1, round(fw * scale)), max(1, round(fh * scale)))
        img = self.frame if size == self.frame.size else self.frame.resize(size, Image.BILINEAR)
        self.photo = ImageTk.PhotoImage(img)
        self.view.itemconfigure(self.img_id, image=self.photo)
        self.view.coords(self.img_id, cw / 2, ch / 2)

    def update_labels(self):
        s = self.src
        last = s.count - 1
        size = f"{self.frame.width}×{self.frame.height}" if s.kind == "images" and self.frame else f"{s.w}×{s.h}"
        self.g_frame.set(self.n + 1, s.count, self.n + 1, f"frame / {s.count}")
        self.g_time.set(self.n / s.fps, max(last / s.fps, 1e-9), f"{self.n / s.fps:.2f}",
                        f"of {last / s.fps:.2f} s")
        kind = {"video": "VIDEO", "animation": "GIF", "images": "IMAGES"}.get(s.kind, "")
        extra = f"\n{os.path.basename(s.files[self.n])}" if s.kind == "images" else ""
        self.facts.configure(text=f"{kind:<7}{size}\nRate   {s.fps:.3g} fps\nFrames {s.count}{extra}")
        self.info.configure(text=f"Frame {self.n + 1:>4} / {s.count}    {clock(self.n / s.fps)} / {clock(last / s.fps)}"
                                 f"    Speed {self.speed:g}×")
        if self.flash_id:   # a "Saved ..." message is showing: leave it for now
            return
        a, b = self.save_range()
        if self.a is None and self.b is None:
            txt = "Using everything. Press I where the move starts and O where it ends."
        else:
            txt = f"Frames {a + 1} to {b + 1}  ·  {b - a + 1} frames  ·  {clock((b - a + 1) / s.fps)}"
        self.range_lbl.configure(text=txt)

    def draw_line(self):
        c = self.line
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        c.create_line(6, 18, w - 6, 18, fill=hud.LINE, width=2)
        if not self.src:
            return
        last = max(1, self.src.count - 1)

        def x(n):
            return 6 + (w - 12) * n / last

        step = max(1, round(last / max(1, (w - 12) / 8)))
        for n in range(0, last + 1, step):
            big = n % (step * 5) == 0
            c.create_line(x(n), 18, x(n), 18 + (8 if big else 4), fill=hud.LINE2 if big else hud.LINE)
            if big and n:
                c.create_text(x(n), 34, text=str(n + 1), fill=hud.FAINT, font=hud.TINY)
        if self.a is not None or self.b is not None:
            a, b = self.save_range()
            c.create_rectangle(x(a), 10, x(b), 26, fill=hud.RED_BG, outline="")
            c.create_line(x(a), 6, x(a), 30, fill=hud.RED, width=2)
            c.create_line(x(b), 6, x(b), 30, fill=hud.RED, width=2)
        c.create_line(6, 18, x(self.n), 18, fill=hud.RED, width=2)
        px = x(self.n)
        c.create_line(px, 4, px, 32, fill=hud.TEXT, width=2)
        c.create_polygon(px - 5, 2, px + 5, 2, px, 8, fill=hud.RED, outline="")

    def on_line(self, e):
        if not self.src:
            return
        w = self.line.winfo_width()
        last = self.src.count - 1
        n = round((e.x - 6) / max(1, w - 12) * last)
        self.pause()
        if self.drag_target is None:   # coalesce fast drags into one decode per idle
            self.root.after_idle(self.finish_drag)
        self.drag_target = max(0, min(n, last))

    def finish_drag(self):
        n, self.drag_target = self.drag_target, None
        if n is not None:
            self.show(n)

    # ---- playing -------------------------------------------------------------
    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if not self.src or self.playing:
            return
        if self.n >= self.src.count - 1:
            self.show(0)
        self.playing = True
        self.play_btn.configure(text="❚❚  Pause")
        self.t0, self.f0 = time.perf_counter(), self.n
        self.tick()

    def tick(self):
        if not self.playing:
            return
        target = self.f0 + int((time.perf_counter() - self.t0) * self.src.fps * self.speed)
        last = self.src.count - 1
        if target >= last:
            self.show(last)
            self.pause()
            return
        if target != self.n:
            self.show(target)
        wait = 1000 / (self.src.fps * self.speed)
        self.tick_id = self.root.after(max(1, int(wait / 2)), self.tick)

    def pause(self):
        self.playing = False
        if self.tick_id:
            self.root.after_cancel(self.tick_id)
            self.tick_id = None
        self.play_btn.configure(text="▶  Play")

    def set_speed(self, s):
        self.speed = s
        self.speed_box.set(f"{s:g}×")
        if self.playing:
            self.t0, self.f0 = time.perf_counter(), self.n
        if self.src:
            self.update_labels()

    def on_speed(self, e):
        self.set_speed(SPEEDS[self.speed_box.current()])
        self.root.focus_set()

    def change_speed(self, d):
        i = min(range(len(SPEEDS)), key=lambda k: abs(SPEEDS[k] - self.speed))
        self.set_speed(SPEEDS[max(0, min(len(SPEEDS) - 1, i + d))])

    # ---- range ---------------------------------------------------------------
    def save_range(self):
        a = 0 if self.a is None else self.a
        b = self.src.count - 1 if self.b is None else self.b
        return a, b

    def set_start(self):
        if self.src:
            self.a = self.n
            if self.b is not None and self.b < self.a:
                self.b = None
            self.draw_line()
            self.update_labels()

    def set_end(self):
        if self.src:
            self.b = self.n
            if self.a is not None and self.a > self.b:
                self.a = None
            self.draw_line()
            self.update_labels()

    def clear_range(self):
        if self.src:
            self.a = self.b = None
            self.draw_line()
            self.update_labels()

    # ---- saving one frame (a screenshot) -------------------------------------
    def save_frame(self):
        """Save the frame on screen, full size, to Images\\Screenshots\\<name>_frame<N>.png."""
        if not self.src:
            return
        self.pause()
        folder = os.path.join(self.images_dir, "Screenshots")
        path = os.path.join(folder, f"{self.src.name}_frame{self.n + 1}.png")
        try:
            img = next(iter(self.src.full([self.n])), None)
            if img is None:
                raise OSError("this frame couldn't be read")
            os.makedirs(folder, exist_ok=True)
            img.save(path)
        except OSError as err:
            self.flash(f"Couldn't save the frame: {err}", hud.RED_HI)
            return
        self.last_saved = path
        self.flash(f"Saved frame {self.n + 1}:\n{path}\n(click here to show it)", hud.GREEN)

    def flash(self, text, colour):
        """Show a message in the Range box for a few seconds, then go back to the range text."""
        self.range_lbl.configure(text=text, fg=colour, cursor="hand2" if colour == hud.GREEN else "")
        if self.flash_id:
            self.root.after_cancel(self.flash_id)
        self.flash_id = self.root.after(6000, self.end_flash)

    def end_flash(self):
        self.flash_id = None
        self.range_lbl.configure(fg=hud.AMBER, cursor="")
        if self.src:
            self.update_labels()

    def show_saved(self, e=None):
        path = getattr(self, "last_saved", None)
        if path and self.range_lbl.cget("cursor") == "hand2" and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    # ---- saving (PNG frames or GIF) ------------------------------------------
    def save_dialog(self, mode):
        if not self.src:
            return
        self.pause()
        s = self.src
        a, b = self.save_range()
        gif = mode == "gif"
        P = hud.PANEL

        d = tk.Toplevel(self.root)
        d.title("Make GIF" if gif else "Save frames as PNG")
        d.configure(bg=P, padx=20, pady=16)
        d.transient(self.root)
        d.resizable(False, False)
        d.grab_set()
        d.columnconfigure(1, weight=1)

        def label(r, text):
            hud.label(d, text.upper(), bg=P, fg=hud.DIM, font=hud.SMALL, anchor="w").grid(
                row=r, column=0, sticky="w", pady=5, padx=(0, 10))

        hud.Header(d, "Make GIF" if gif else "Save frames", bg=P).grid(row=0, column=0, columnspan=3, sticky="we")
        hud.label(d, f"Frames {a + 1} to {b + 1}  ·  {b - a + 1} frames  ·  {clock((b - a + 1) / s.fps)}", bg=P,
                  font=hud.BOLD, anchor="w").grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 6))

        rates = rate_options(s, gif)
        rate_box = ttk.Combobox(d, state="readonly", width=34, values=[t for t, _, _ in rates])
        rate_box.current(0)
        label(2, "Frames")
        rate_box.grid(row=2, column=1, columnspan=2, sticky="we", pady=5)

        widths = [(f"Original ({s.w} px wide)", None)] + [(f"{w} px wide", w) for w in WIDTHS if w < s.w]
        w_box = ttk.Combobox(d, state="readonly", width=34, values=[t for t, _ in widths])
        default_w = 0
        if gif and s.w > 720 and len(widths) > 1:
            default_w = next(i for i, (_, w) in enumerate(widths) if w and w <= 640)
        w_box.current(default_w)
        label(3, "Size")
        w_box.grid(row=3, column=1, columnspan=2, sticky="we", pady=5)

        base = s.name
        if self.a is not None or self.b is not None:
            base = f"{s.name}_{a + 1}-{b + 1}"
        name = tk.StringVar()
        entry = ttk.Entry(d, textvariable=name, width=58)
        where = hud.label(d, "", bg=P, fg=hud.DIM, font=hud.SMALL, anchor="w", justify="left")
        if gif:
            name.set(os.path.join(self.images_dir, base + ".gif"))
            label(4, "Save as")
            entry.grid(row=4, column=1, sticky="we", pady=5)

            def browse():
                p = filedialog.asksaveasfilename(parent=d, defaultextension=".gif", filetypes=[("GIF", "*.gif")],
                                                 initialdir=os.path.dirname(name.get()) or self.images_dir,
                                                 initialfile=os.path.basename(name.get()))
                if p:
                    name.set(os.path.normpath(p))

            hud.Button(d, "Browse…", browse).grid(row=4, column=2, padx=(6, 0))
        else:
            name.set("")
            label(4, "Move name")
            entry.grid(row=4, column=1, columnspan=2, sticky="we", pady=5)
            where.grid(row=5, column=1, columnspan=2, sticky="w")

        est = hud.label(d, "", bg=P, fg=hud.DIM, anchor="w")
        est.grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))

        def picks():
            _, take, rate = rates[rate_box.current()]
            return sample(a, b, s.fps, take), rate

        def refresh(*_):
            idx, rate = picks()
            if gif:
                est.configure(text=f"The GIF will have {len(idx)} frames at {rate:.3g} fps.")
                return
            folder = name.get().strip()
            if not folder:
                where.configure(text=f"Type a name for this move, e.g. jumping or walk.\n"
                                     f"It becomes a folder in {self.images_dir}", fg=hud.DIM)
            elif BAD_NAME.search(folder):
                where.configure(text='A folder name can\'t have any of  \\ / : * ? " < > |', fg=hud.RED_HI)
            else:
                where.configure(text=os.path.join(self.images_dir, folder, "f01.png") + "  …", fg=hud.DIM)
            last = f"f{len(idx):02d}.png"
            est.configure(text=f"{len(idx)} frames will be saved as f01.png to {last}, plus all.png "
                               f"(every frame on one sheet).")

        rate_box.bind("<<ComboboxSelected>>", refresh)
        name.trace_add("write", refresh)
        refresh()

        prog = ttk.Progressbar(d, length=480, mode="determinate")
        prog.grid(row=7, column=0, columnspan=3, sticky="we", pady=(12, 4))
        buttons = tk.Frame(d, bg=P)
        buttons.grid(row=8, column=0, columnspan=3, sticky="e", pady=(8, 0))

        def go():
            idx, rate = picks()
            width = widths[w_box.current()][1]
            if gif:
                path = name.get().strip()
                if not path:
                    return
                if not path.lower().endswith(".gif"):
                    path += ".gif"
                if os.path.exists(path) and not messagebox.askyesno(
                        "Make GIF", f"{os.path.basename(path)} already exists. Replace it?", parent=d):
                    return
                target = path
            else:
                folder = name.get().strip().rstrip(". ")
                if not folder:
                    messagebox.showinfo("Save frames", "Type a name for the move first, e.g. jumping.", parent=d)
                    entry.focus_set()
                    return
                if BAD_NAME.search(folder):
                    messagebox.showinfo("Save frames", 'A folder name can\'t have any of  \\ / : * ? " < > |',
                                        parent=d)
                    return
                target = os.path.join(self.images_dir, folder)
                if s.kind == "images" and os.path.normcase(os.path.abspath(target)) == \
                        os.path.normcase(os.path.abspath(s.where)):
                    messagebox.showinfo("Save frames", "That's the folder these images are in. "
                                                       "Pick another name.", parent=d)
                    return
                old = existing_frames(target)
                if any(n.lower() == "trace.json" and not os.access(os.path.join(target, n), os.W_OK) for n in old):
                    messagebox.showinfo("Save frames", f"{folder} is protected (its trace.json is read-only), so its "
                                                       "frames aren't replaced. Pick another name, or unprotect it "
                                                       "in Trace → Project….", parent=d)   # Phase 9
                    return
                if old:
                    if not messagebox.askyesno(
                            "Save frames", f"{folder} already has {len(old)} frame/trace files.\n\n"
                                           "Replace them? The old ones are moved into a folder named "
                                           "\"old ...\" inside it, so nothing is lost."
                                           + ("\n\nIt's a multi-character move: every traced character moves "
                                              "there too, together with the frames it was traced on."
                                              if "characters.json" in {n.lower() for n in old} else ""), parent=d):
                        return
            make.configure(state="disabled")
            try:
                if gif:
                    count = write_gif(s, idx, rate, width, target, prog, d)
                else:
                    moved = move_old(target)
                    count = write_frames(s, idx, width, target, prog, d, rate)
            except Exception as err:   # report any failure in the window instead of a hidden console
                messagebox.showerror(d.title(), f"Something went wrong:\n\n{err}", parent=d)
                make.configure(state="normal")
                return
            d.destroy()
            if gif:
                size = os.path.getsize(target) / 1e6
                self.flash(f"Saved the GIF ({count} frames, {size:.1f} MB):\n{target}", hud.GREEN)
                self.last_saved = target
                return
            if self.on_frames_saved:   # Stickman Studio: go straight on to picking the key frames
                self.on_frames_saved(target, count, moved)
                return
            msg = f"Saved {count} frames (f01.png to f{count:02d}.png) in\n{target}"
            if moved:
                msg += f"\n\nThe old files are in {os.path.basename(moved)}."
            if messagebox.askyesno("Saved", msg + "\n\nTrace it in Stickman Studio now?", parent=self.root):
                open_trace_clicker(target)
            else:
                os.startfile(target)

        make = hud.Button(buttons, "Make GIF" if gif else "Save Frames", go, kind="red")
        make.pack(side="left", padx=4)
        hud.Button(buttons, "Cancel", d.destroy).pack(side="left")
        d.bind("<Return>", lambda e: go())
        d.bind("<Escape>", lambda e: d.destroy())
        if not gif:
            entry.focus_set()

    def quit(self):
        self.pause()
        if self.src:
            self.src.close()
            self.src = None
        if not self.embedded:
            self.root.destroy()


def rate_options(src, gif):
    """(label, frames-per-second to keep or None for all, rate the GIF plays at)."""
    if src.kind != "video":   # images: keep them all, choose how fast the GIF plays
        if not gif:
            return [("Every frame", None, src.fps)]
        rates = sorted({round(src.fps, 3)} | {r for r in RATES if r <= 30}, reverse=True)
        return [(f"Every frame, played at {r:.3g} fps", None, r) for r in rates]
    opts = []
    if not gif or src.fps <= 50.5:
        opts.append((f"Every frame ({src.fps:.3g} fps)", None, src.fps))
    opts += [(f"{r} per second" if not gif else f"{r} fps", r, r) for r in RATES if r < src.fps - 0.5]
    return opts


def sample(a, b, src_fps, take):
    """Frame numbers to keep between a and b: all of them, or `take` per second."""
    if take is None:
        return list(range(a, b + 1))
    idx, k = [], 0
    while True:
        n = a + round(k * src_fps / take)
        if n > b:
            break
        idx.append(n)
        k += 1
    return idx


def durations(count, fps):
    """GIF delays are in 1/100 s; spread the rounding so the total time stays right."""
    out, prev = [], 0
    for k in range(1, count + 1):
        end = round(k * 100 / fps)
        out.append(max(2, end - prev) * 10)
        prev = end
    return out


def sized(img, width):
    if width and img.width != width:
        return img.resize((width, max(1, round(img.height * width / img.width))), Image.LANCZOS)
    return img


def write_gif(src, idx, fps, width, path, prog, win):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    frames = []
    prog.configure(maximum=len(idx) + 1, value=0)
    for img in src.full(idx):
        frames.append(sized(img, width))
        prog.configure(value=len(frames))
        win.update()
    if not frames:
        raise OSError("No frames could be read.")
    import gifwrite   # one palette for the whole clip (no colour flicker), dithered because it's video
    gifwrite.write_gif(path, frames, fps, dither=True)
    prog.configure(value=len(idx) + 1)
    win.update()
    return len(frames)


def existing_frames(folder):
    if not os.path.isdir(folder):
        return []
    return [n for n in os.listdir(folder) if FRAME_FILE.match(n) or n.lower() in TRACE_FILES]


def move_old(folder):
    """Move earlier frames and traces out of the way (into folder\\old <date time>). Returns that folder."""
    old = existing_frames(folder)
    if not old:
        return None
    dest = os.path.join(folder, "old " + time.strftime("%Y-%m-%d %H%M%S"))
    os.makedirs(dest)
    for n in old:
        shutil.move(os.path.join(folder, n), os.path.join(dest, n))
    return dest


def write_frames(src, idx, width, folder, prog, win, fps=None):
    os.makedirs(folder, exist_ok=True)
    if fps:   # so the trace player knows the real speed
        with open(os.path.join(folder, "timing.json"), "w") as fh:
            json.dump({"fps": round(fps, 3)}, fh)
    prog.configure(maximum=len(idx) + 1, value=0)
    thumbs = []
    for k, img in enumerate(src.full(idx), 1):
        img = sized(img, width)
        img.save(os.path.join(folder, f"f{k:02d}.png"))
        thumbs.append(img)
        prog.configure(value=k)
        win.update()
    if not thumbs:
        raise OSError("No frames could be read.")
    contact_sheet(thumbs, os.path.join(folder, "all.png"))
    prog.configure(value=len(idx) + 1)
    win.update()
    return len(thumbs)


def contact_sheet(frames, path):
    """Every frame on one image with its number (1 = f01.png) in yellow, to pick key frames from."""
    n = len(frames)
    tw = min(360, max(f.width for f in frames))
    th = max(1, round(max(f.height * tw / f.width for f in frames)))
    cols = max(1, min(8, n, round(math.sqrt(n * th / tw * 1.6)) or 1))
    rows = math.ceil(n / cols)
    sheet = Image.new("RGB", (tw * cols, th * rows), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arialbd.ttf", max(16, tw // 9))
    except OSError:
        font = ImageFont.load_default()
    for i, f in enumerate(frames):
        t = f.copy()
        t.thumbnail((tw, th), Image.LANCZOS)
        x, y = (i % cols) * tw, (i // cols) * th
        sheet.paste(t, (x + (tw - t.width) // 2, y + (th - t.height) // 2))
        draw.rectangle((x, y, x + tw - 1, y + th - 1), outline="#999999")
        draw.text((x + 6, y + 4), str(i + 1), fill="yellow", font=font, stroke_width=3, stroke_fill="black")
    sheet.save(path)


def open_trace_clicker(target):
    """Open Stickman Studio on a GIF or frames folder (it goes straight to picking the key frames)."""
    studio = os.path.join(HERE, "studio.py")
    images = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(target))), "Images")
    args = [sys.executable, "-I", studio]
    if os.path.isdir(images):
        args += ["--images", images]
    subprocess.Popen(args + [target], creationflags=subprocess.CREATE_NO_WINDOW)


def main(args):
    images_dir = os.path.join(os.getcwd(), "Images")
    if len(args) >= 2 and args[0] == "--images":
        images_dir, args = os.path.abspath(args[1]), args[2:]
    os.makedirs(images_dir, exist_ok=True)
    paths = [os.path.abspath(a.strip().strip('"')) for a in args if a.strip()]
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
    root.title("Video Tool")
    App(root, paths, images_dir)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

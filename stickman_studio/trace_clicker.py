"""Click-to-trace: put the 12 joints on each key frame with the mouse. trace.json is written for you.

usage:
  python -I trace_clicker.py <frames_dir> 1 4 7     trace frames f01, f04, f07 (made by extract_frames.py)
  python -I trace_clicker.py <frames_dir>           reopen <frames_dir>/trace.json to fix or finish it

Mouse:  click = place the point named in the panel (in order: head, neck, waist, hip, legs, arms)
        drag a point = move it (the selected joint wins when points overlap)
        Ctrl+click a point = select it (click again on the same spot: the next joint under the cursor)
        right-click a point = mark / unmark it as a guess (yellow)   right-click empty space = place as a guess
        wheel = zoom at the cursor   Shift+wheel / Ctrl+wheel = pan sideways / up and down
        right-drag or middle-drag = pan
Keys:   Space = keep the faded point where it is      Ctrl+Z or Backspace = undo   Ctrl+Y = redo
        Enter = next frame (keeps any faded points)   Left / Right = change frame   Home / End = first / last
        N / Shift+N = next / previous frame with missing points
        Tab / Shift+Tab = select the next / previous joint     Esc = back to the normal order
        Alt+arrows = nudge the selected joint by one screen pixel (finer the more you zoom in)
        G = guess on / off for the selected joint     Delete = remove the selected joint from this frame
        + / - = zoom   Z = zoom to the selected joint   F = fit the frame   H = hide / show the points
        L = names on / off (the selected joint keeps its name)     K = bone-length check on / off
        C = Carry Forward: copy chosen joints of this frame to chosen key frames (faded, or as traced points)
        R = refresh this frame's faded points from the nearest traced frames (your placed points stay)
        S = Smooth: take the jitter out of joint paths (4 methods, strength, preview, protects fast moves)
        T = motion trails on / off (the bar above the frame: joints, length, past / future, visibility)
        P = play the traced frames as a stickman animation (trace_player.py; it follows your edits live)
        U = History: every undo step with its time; go back (or forward) to any of them
        Ctrl+S = save a named checkpoint of the trace (restore it from BACKUPS… on the 02 TRACE home)
Undo / redo steps are kept in trace_history.json, so Ctrl+Z still works after a restart (as long as trace.json wasn't
changed elsewhere in between). Saving skips a write when nothing changed, and if trace.json was changed outside the
editor since it was opened, that version is backed up (reason "outside") before it is overwritten.
Coordinates are kept to 0.1 frame pixel. A bone more than twice / under half its usual length (relative to the body's
size in that frame) is drawn dashed red and named in the panel: a hint to look, since turns also change 2D lengths.
A frame starts with a faded copy of every joint it doesn't have yet, from the nearest key frame where you placed
that joint (earlier frames first), at exactly the same spot: nothing looks at the picture. On an empty frame your
first click moves the whole faded figure with it, so the rest lands nearby: click each real spot, or press Space if
it's already right. Enter keeps the faded points left and says which ones.
Points placed outside the frame are marked as guesses automatically.
Saves <frames_dir>/trace.json after every change (an old file is copied to trace_backup.json first).
When every frame is done, closing the window also writes trace_check.png (with draw_trace.py).
"""
import copy
import json
import math
import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # for trace_player and hud (python -I leaves it out)

ORDER = ["head", "neck", "waist", "hip", "backKnee", "backFoot", "frontKnee", "frontFoot",
         "frontElbow", "frontHand", "backElbow", "backHand"]
HINT = {
    "head": "Centre of the head.",
    "neck": "Where the neck meets the shoulders.",
    "waist": "Middle of the torso, where it bends.",
    "hip": "Where the legs start: at the waistline, even under a dress or gi. Too low makes the legs short.",
    "backKnee": "Knee of the Back leg (further from the opponent).",
    "backFoot": "Foot of the Back leg (further from the opponent).",
    "frontKnee": "Knee of the Front leg (nearer the opponent, the side the character faces).",
    "frontFoot": "Foot of the Front leg (nearer the opponent, the side the character faces).",
    "frontElbow": "Elbow of the Front arm (nearer the opponent).",
    "frontHand": "Hand of the Front arm (nearer the opponent).",
    "backElbow": "Elbow of the Back arm (further away).",
    "backHand": "Hand of the Back arm (further away).",
    # v3.0 optional joints: never asked for and never required. Click the name below, then click the spot.
    "frontShoulder": "Optional. Shoulder of the Front arm: the arm then starts here instead of at the neck.",
    "backShoulder": "Optional. Shoulder of the Back arm: the arm then starts here instead of at the neck.",
    "frontHandTip": "Optional. Tip of the Front hand (the fingers): points the hand.",
    "backHandTip": "Optional. Tip of the Back hand (the fingers): points the hand.",
    "frontToe": "Optional. Toe of the Front foot: points the foot (without it the foot points forward from the shin).",
    "backToe": "Optional. Toe of the Back foot: points the foot (without it the foot points forward from the shin).",
}
CHAINS = [("hip", "backKnee", "backFoot"), ("hip", "frontKnee", "frontFoot"), ("hip", "waist", "neck", "head"),
          ("neck", "frontElbow", "frontHand"), ("neck", "backElbow", "backHand")]
BONES = [(a, b) for ch in CHAINS for a, b in zip(ch, ch[1:])]   # the 11 bones
PAD = 150   # frame pixels of empty room around the frame, for joints that are off-screen
HIT = 10    # screen pixels: how close a press must be to grab a point
MOVE = 3    # screen pixels: a press that moves less than this is a click, not a drag
ZOOM_MIN, ZOOM_MAX = 0.25, 16.0
ZOOM_TO = 4.0          # Z zooms to at least this, centred on the selected joint
LENGTH_HI, LENGTH_LO = 2.0, 0.5   # bone-length check: flag a bone over 2x or under 0.5x its usual (relative) length.
# Set from your own Jumping / jump traces: flips and turns legitimately change 2D bone lengths a lot (0.16x-2.3x seen),
# so only extreme cases are flagged. K switches the check off.
import hud  # noqa: E402  (same folder; the path is added above)
import trace_io  # noqa: E402  (versioned backups and the trace.json writer)
import smoothing  # noqa: E402  (Phase 4: joint smoothing maths)
import trails  # noqa: E402  (Phase 5: motion trails)
import history  # noqa: E402  (Phase 9: saved undo steps and the move's log)

EXTRAS = trace_io.EXTRAS   # v3.0: optional shoulders, hand tips and toes (a frame is finished without them)
ALL = trace_io.ALL
BG = hud.PANEL
FONT = hud.FONT


def colour(name):   # same colours as draw_trace.py
    return "#ff8c00" if name.startswith("front") else "#1e6eff" if name.startswith("back") else "#1ec83c"


def shape_points(name, x, y, r):
    """Each group has its own marker shape, so joints can be told apart without colour:
    torso = circle, front limbs = square, back limbs = diamond. -> ("oval" | "rect" | "poly", coordinates)."""
    if name.startswith("front"):
        return "rect", (x - r, y - r, x + r, y + r)
    if name.startswith("back"):
        q = r * 1.3
        return "poly", (x, y - q, x + q, y, x, y + q, x - q, y)
    return "oval", (x - r, y - r, x + r, y + r)


def draw_marker(c, name, x, y, r, tags, **kw):
    kind, xy = shape_points(name, x, y, r)
    if kind == "rect":
        return c.create_rectangle(*xy, tags=tags, **kw)
    if kind == "poly":
        return c.create_polygon(*xy, tags=tags, **kw)
    return c.create_oval(*xy, tags=tags, **kw)


def _median(vals):
    vals = sorted(vals)
    k = len(vals)
    return vals[k // 2] if k % 2 else (vals[k // 2 - 1] + vals[k // 2]) / 2


def body_scale(st):
    """The frame's body size: the median length of its placed bones (one misplaced joint barely moves it)."""
    Ls = [math.dist(st.pts[a], st.pts[b]) for a, b in BONES if a in st.ok and b in st.ok]
    return _median(Ls) if len(Ls) >= 5 else None


def bone_flags(states, frames, f):
    """Bones of frame f whose length, RELATIVE TO THE BODY'S SIZE in that frame (so a camera zoom doesn't count), is
    more than LENGTH_HI x or less than LENGTH_LO x the same bone's median in your other traced frames.
    -> {(a, b): (length px, usual length px at this frame's size)}. Needs the bone in at least 2 other frames.
    Plain geometry: a turn towards the camera also shortens a limb, so it's a hint to look, not an error."""
    st = states[f]
    sf = body_scale(st)
    if not sf:
        return {}
    scales = {g: body_scale(states[g]) for g in frames if g != f}
    out = {}
    for a, b in BONES:
        if a not in st.ok or b not in st.ok:
            continue
        others = [math.dist(states[g].pts[a], states[g].pts[b]) / s for g, s in scales.items()
                  if s and a in states[g].ok and b in states[g].ok]
        if len(others) < 2:
            continue
        usual = _median(others) * sf
        L = math.dist(st.pts[a], st.pts[b])
        if usual > 1 and not (LENGTH_LO <= L / usual <= LENGTH_HI):
            out[(a, b)] = (L, usual)
    return out


def text_colour(name):   # brighter versions, readable on the dark panel
    return "#ffa23a" if name.startswith("front") else "#5b9bff" if name.startswith("back") else "#46d46a"


class FrameState:
    def __init__(self):
        self.pts = {}       # name -> [x, y] in frame pixels
        self.ok = set()     # points you placed or checked (faded copies are not in here, and are not saved)
        self.guess = set()  # estimated points (hidden or off-screen)

    @classmethod
    def make(cls, pts, ok, guess):
        st = cls()
        st.pts, st.ok, st.guess = pts, set(ok), set(guess)
        return st


# ---------------------------------------------------------------- carry-forward (Phase 3: coordinate propagation)
# Plain copying of YOUR coordinates between frames. Nothing here looks at the pictures: a copied point stays exactly
# where it was until you move it.
def neighbour_order(k, count):
    """Key frame indexes to copy from, for index k: earlier ones first (nearest first), then later ones."""
    return list(range(k - 1, -1, -1)) + list(range(k + 1, count))


def fill_missing(states, frames, k):
    """Give frame k a faded starting point for every joint it doesn't have yet, copied from the nearest key frame
    where you placed that joint (earlier frames first). Points already there are never touched. -> joints filled."""
    st = states[frames[k]]
    filled = []
    for n in ALL:   # v3.0: an optional joint you placed on an earlier frame comes as a faded copy too
        if n in st.pts:
            continue
        for j in neighbour_order(k, len(frames)):
            src = states[frames[j]]
            if n in src.ok:
                st.pts[n] = list(src.pts[n])
                filled.append(n)
                break
    return filled


def refresh_faded(states, frames, k):
    """Throw away frame k's faded (unconfirmed) points and copy them again from the nearest traced frames, e.g. after
    you fixed the frame before. Your placed points stay. -> joints refreshed."""
    st = states[frames[k]]
    for n in [n for n in st.pts if n not in st.ok]:
        del st.pts[n]
    return fill_missing(states, frames, k)


def carry_points(states, src_f, targets, joints, as_traced=False, replace=False, dry=False):
    """Copy the chosen joints of frame src_f (only the ones you placed there) to every frame in targets.
    as_traced  False: they arrive as faded starting points you confirm (Space / Enter); True: saved as traced points
               (a joint you marked as a guess stays a guess).
    replace    False: joints you already placed on a target frame are kept (only missing / faded ones are set);
               True: they are overwritten too.
    dry        only count, change nothing.
    -> {"set": [(frame, joint)], "replaced": [(frame, joint)], "kept": [(frame, joint)], "not_on_source": [joint]}"""
    src = states[src_f]
    use = [n for n in ORDER if n in joints and n in src.ok]
    out = {"set": [], "replaced": [], "kept": [], "not_on_source": [n for n in ORDER if n in joints and n not in src.ok]}
    for f in targets:
        if f == src_f:
            continue
        st = states[f]
        for n in use:
            mine = n in st.ok
            if mine and not replace:
                out["kept"].append((f, n))
                continue
            if mine:
                out["replaced"].append((f, n))
            out["set"].append((f, n))
            if dry:
                continue
            st.pts[n] = list(src.pts[n])
            if as_traced:
                st.ok.add(n)
                if n in src.guess:
                    st.guess.add(n)
                else:
                    st.guess.discard(n)
            else:
                st.ok.discard(n)
                st.guess.discard(n)
    return out


def frame_path(d, f):
    return os.path.join(d, f"f{f:02d}.png")


def find_trace(d):
    for n in os.listdir(d):
        if n.lower() == "trace.json":
            return os.path.join(d, n)
    return os.path.join(d, "trace.json")


def load_trace(path):
    with open(path) as fh:
        J = json.load(fh)
    frames = list(J["frames"])
    est = J.get("estimated") or [[] for _ in frames]
    states = {}
    for f, P, E in zip(frames, J["pts"], est):
        st = FrameState()
        for k, v in P.items():
            if k in ALL:
                st.pts[k] = [float(v[0]), float(v[1])]
                st.ok.add(k)
        st.guess = set(E) & st.ok
        states[f] = st
    return frames, states


def save_trace(path, frames, states):
    """Only confirmed points are saved (faded copies aren't). The text itself is made by trace_io.format_trace."""
    pts = [{n: states[f].pts[n] for n in ALL if n in states[f].ok} for f in frames]
    est = [[n for n in ALL if n in states[f].guess and n in states[f].ok] for f in frames]
    trace_io.write_trace(path, frames, pts, est)


def versioned_backup(d, reason="open"):
    """A dated copy in <folder>\\backups (skipped when nothing changed). -> a note for the user, or None."""
    try:
        trace_io.backup(d, reason)
    except OSError as e:
        return f"Couldn't make a dated backup ({e}); trace_backup.json was still made."
    return None


class App:
    """The click-to-trace window. On its own it fills the window; inside Stickman Studio it lives in a panel
    (parent=...), its keys are collected in self.keymap, and on_play / on_finish / on_back are called instead of
    opening a player window or closing."""

    def __init__(self, root, frames_dir, frames, states, out_path, parent=None, on_play=None, on_finish=None,
                 on_back=None, cast=None):
        self.root, self.dir, self.frames, self.states, self.out = root, frames_dir, frames, states, out_path
        # Phase 11: tdir = the trace's own folder (a traced character's folder; the frames folder for character 1).
        # cast (multi-character moves): {"active": id, "characters": [registry entries], "sessions": {id: session}}
        self.tdir = os.path.dirname(os.path.abspath(out_path))
        self.cast = cast
        self.active = cast["active"] if cast else None
        self.sessions = dict(cast["sessions"]) if cast else {}
        self.charbar = None
        self.group_preview, self.group_dlg = None, None   # step 5: GROUP… (M) and its cyan preview
        self.embedded = parent is not None
        self.box = parent if parent is not None else root
        self.on_play, self.on_finish, self.on_back = on_play, on_finish, on_back
        self.images, self.sizes = {}, {}
        self.i = 0
        self.forced = None        # the selected joint: picked in the list, with Tab or Ctrl+click; (re)placed next
        # undo / redo steps: (key frame index, {frame: FrameState before (undo) / after (redo)}, label, time).
        # Phase 9: kept in trace_history.json and brought back when trace.json is the trace they were saved with.
        hist, problem = history.load(frames_dir)
        if cast:   # one undo list for every character (a group edit is one step), kept in the move's folder
            self.undo, self.redo, note = history.restore_steps_multi(hist, self.trace_files(), FrameState.make)
        else:
            self.undo, self.redo, note = history.restore_steps(hist, out_path, frames, FrameState.make)
        self.history_note = problem or note or (
            f"{len(self.undo)} undo step(s) from last time are back: Ctrl+Z works across restarts (U lists them)."
            if self.undo or self.redo else None)
        self.session = {"id": f"{time.time():.3f}", "start": time.time(), "changes": 0, "frames": set()}
        self.hist_dirty, self.hist_job, self.history_dlg = False, None, None
        self.save_problem = None   # set while saving fails (e.g. a protected trace), so the warning stays in view
        try:   # what trace.json holds on disk, to notice a change made elsewhere before overwriting it
            with open(out_path) as fh:
                self.disk_text = fh.read()
        except OSError:
            self.disk_text = None
        self.s, self.ox, self.oy = 1.0, 0.0, 0.0   # zoom, and the frame position at the canvas's top-left
        self.labels = True
        self.show_points = True   # H hides the points to see the picture underneath
        self.cycle = None         # Ctrl+click cycling through overlapping joints: (x, y, [names], index)
        self.flags = {}           # bones of this frame with an unusual length: {(a, b): (length, usual length)}
        self.checks = True        # K: the bone-length check on / off
        self.smooth_preview = None   # {frame: {joint: [x, y]}} while the Smooth window shows a preview
        self.smooth_dlg = None
        self.trail_on = False        # T: motion trails (Phase 5)
        self.press = None         # what the current mouse press is doing
        self.fitted = False
        self.photo = self.lphoto = None
        self.player = None
        if not self.embedded:
            hud.setup(root)
            root.title("Trace clicker")

        box = self.box
        bar = tk.Frame(box, bg=hud.BG)
        bar.pack(side="bottom", fill="x")
        self.msg_label = tk.Label(bar, anchor="w", font=hud.SMALL, bg=hud.BG, fg=hud.DIM)
        self.msg_label.pack(side="left", fill="x", expand=True, padx=12, pady=4)
        self.xy_label = tk.Label(bar, anchor="e", font=(hud.MONO, 9), bg=hud.BG, fg=hud.DIM, width=44)
        self.xy_label.pack(side="right", padx=12)
        self.build_ribbon(box)   # v3.3: the commands live in a ribbon (Home, Tools, View)

        outer = tk.Frame(box, width=356, bg=BG, highlightthickness=1, highlightbackground=hud.LINE)
        outer.pack(side="right", fill="y", padx=(0, 12), pady=(10, 0))
        outer.pack_propagate(False)
        # v3.0: the side panel scrolls (scroll bar or mouse wheel), so long moves never push its buttons off screen
        self.side_canvas = sc = tk.Canvas(outer, bg=BG, highlightthickness=0, width=338)
        vsb = tk.Scrollbar(outer, orient="vertical", command=sc.yview)
        sc.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        sc.pack(side="left", fill="both", expand=True)
        side = tk.Frame(sc, bg=BG)
        side_win = sc.create_window(0, 0, window=side, anchor="nw")
        side.bind("<Configure>", lambda e: sc.configure(scrollregion=(0, 0, e.width, e.height)))
        sc.bind("<Configure>", lambda e: sc.itemconfigure(side_win, width=e.width))
        self.side = side
        root.bind_class("TraceSide", "<MouseWheel>", self.side_wheel)
        screen = hud.panel(box, bg="#16161a")
        screen.pack(side="left", fill="both", expand=True, padx=12, pady=(10, 0))
        if cast:   # Phase 11: the character chips (click or 1-9 switches; Ctrl+click selects several)
            from character_bar import CharacterBar
            self.charbar = CharacterBar(screen, root, on_change=self.cast_changed, bg="#16161a")
            self.charbar.load(frames_dir, active=self.active)
            self.charbar.pack(fill="x", padx=8, pady=(6, 0))
        self.canvas = tk.Canvas(screen, bg="#16161a", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        top = tk.Frame(side, bg=BG)
        top.pack(fill="x", padx=12, pady=(12, 0))
        self.gauge = hud.Gauge(top, size=92, label="points", bg=BG)
        self.gauge.pack(side="left")
        tt = tk.Frame(top, bg=BG)
        tt.pack(side="left", fill="x", expand=True, padx=(12, 0))
        hud.tag(tt, os.path.basename(os.path.normpath(frames_dir)), bg=BG).pack(anchor="w")
        self.title_label = tk.Label(tt, font=hud.TITLE, bg=BG, fg=hud.TEXT, anchor="w")
        self.title_label.pack(fill="x", pady=(6, 0))
        self.count_label = tk.Label(tt, font=hud.SMALL, bg=BG, fg=hud.DIM, anchor="w")
        self.count_label.pack(fill="x")

        hud.Header(side, "Key frames", bg=BG).pack(fill="x", padx=12, pady=(12, 4))
        self.fb_box = tk.Frame(side, bg=BG)
        self.fb_box.pack(fill="x", padx=12)
        self.frame_buttons = []
        self.build_frame_buttons()

        hud.Header(side, "Next point", bg=BG).pack(fill="x", padx=12, pady=(12, 0))
        self.ask_label = tk.Label(side, font=(hud.F_SEMI, 15), bg=BG, anchor="w")
        self.ask_label.pack(fill="x", padx=12, pady=(4, 0))
        self.hint_label = tk.Label(side, font=hud.SMALL, bg=BG, fg=hud.DIM, anchor="nw", justify="left",
                                   wraplength=310, height=3)
        self.hint_label.pack(fill="x", padx=12)
        self.check_label = tk.Label(side, font=hud.SMALL, bg=BG, fg=hud.AMBER, anchor="nw", justify="left",
                                    wraplength=310, height=3)
        self.check_label.pack(fill="x", padx=12)
        pl = tk.Frame(side, bg=BG)
        pl.pack(fill="x", padx=12, pady=(4, 0))
        self.rows = {}
        for k, n in enumerate(ORDER):
            r = tk.Label(pl, font=hud.SMALL, anchor="w", bg=BG, fg=text_colour(n), cursor="hand2", padx=4)
            r.grid(row=k // 2, column=k % 2, sticky="we")
            r.bind("<Button-1>", lambda e, n=n: self.pick(n))
            self.rows[n] = r
        pl.columnconfigure(0, weight=1)
        pl.columnconfigure(1, weight=1)
        tk.Label(pl, text="Optional (never required): select one, then click its position", font=hud.TINY,
                 fg=hud.FAINT, bg=BG, anchor="w").grid(row=7, column=0, columnspan=2, sticky="we", pady=(4, 0))
        for k, n in enumerate(EXTRAS):   # v3.0: shoulders, hand tips, toes
            r = tk.Label(pl, font=hud.SMALL, anchor="w", bg=BG, fg=text_colour(n), cursor="hand2", padx=4)
            r.grid(row=8 + k // 2, column=k % 2, sticky="we")
            r.bind("<Button-1>", lambda e, n=n: self.pick(n))
            self.rows[n] = r
        tk.Label(side, text="Select a joint by its name, with Tab, or Ctrl+click on its point.", font=hud.TINY,
                 fg=hud.FAINT, bg=BG, anchor="w").pack(fill="x", padx=12)
        hud.wrap_to_width(tk.Label(side, font=hud.TINY, bg=BG, anchor="nw", justify="left", fg=hud.FAINT, text=(
            "Click to place · drag to move · right-click for a guessed point · mouse wheel to zoom · right-drag to "
            "pan.  Torso ●  front ■  back ◆.  All shortcuts: Help → Keyboard Shortcuts."))).pack(
            fill="x", padx=12, pady=(10, 8))
        self.wheel_tag(sc)

        c = self.canvas
        c.bind("<Configure>", self.on_resize)
        c.bind("<ButtonPress-1>", self.on_press1)
        c.bind("<Control-ButtonPress-1>", self.on_ctrl_click)
        c.bind("<B1-Motion>", self.on_drag1)
        c.bind("<ButtonRelease-1>", self.on_release1)
        c.bind("<Shift-ButtonPress-1>", self.on_group_press)     # Phase 11: Shift+drag moves the selected
        c.bind("<Shift-B1-Motion>", self.on_group_drag)          # characters together
        c.bind("<Shift-ButtonRelease-1>", self.on_group_release)
        c.bind("<ButtonPress-3>", self.on_press3)
        c.bind("<B3-Motion>", self.on_drag3)
        c.bind("<ButtonRelease-3>", self.on_release3)
        c.bind("<ButtonPress-2>", self.on_press2)
        c.bind("<B2-Motion>", self.on_drag3)
        c.bind("<ButtonRelease-2>", lambda e: setattr(self, "press", None))
        c.bind("<MouseWheel>", self.on_wheel)
        c.bind("<Shift-MouseWheel>", lambda e: self.pan_steps(-1 if e.delta > 0 else 1, 0))
        c.bind("<Control-MouseWheel>", lambda e: self.pan_steps(0, -1 if e.delta > 0 else 1))
        c.bind("<Motion>", self.on_motion)
        c.bind("<Leave>", lambda e: (c.delete("loupe"), self.xy_label.config(text=self.zoom_text())))
        self.keymap = {}
        for key, fn in [("<space>", self.keep), ("<Return>", self.next_frame), ("<KP_Enter>", self.next_frame),
                        ("<Right>", lambda e=None: self.go(self.i + 1)), ("<Left>", lambda e=None: self.go(self.i - 1)),
                        ("<Home>", lambda e=None: self.go(0)), ("<End>", lambda e=None: self.go(len(self.frames) - 1)),
                        ("<n>", lambda e=None: self.go_unfinished(1)), ("<N>", lambda e=None: self.go_unfinished(-1)),
                        ("<Control-z>", self.do_undo), ("<Control-Z>", self.do_undo), ("<BackSpace>", self.do_undo),
                        ("<Control-y>", self.do_redo), ("<Control-Y>", self.do_redo),
                        ("<Tab>", lambda e=None: self.select_step(1)),
                        ("<Shift-Tab>", lambda e=None: self.select_step(-1)),
                        ("<Alt-Left>", lambda e=None: self.nudge(-1, 0)), ("<Alt-Right>", lambda e=None: self.nudge(1, 0)),
                        ("<Alt-Up>", lambda e=None: self.nudge(0, -1)), ("<Alt-Down>", lambda e=None: self.nudge(0, 1)),
                        ("<g>", self.toggle_guess), ("<G>", self.toggle_guess), ("<Delete>", self.delete_point),
                        ("<plus>", lambda e=None: self.zoom_key(1.25)), ("<equal>", lambda e=None: self.zoom_key(1.25)),
                        ("<KP_Add>", lambda e=None: self.zoom_key(1.25)), ("<minus>", lambda e=None: self.zoom_key(0.8)),
                        ("<KP_Subtract>", lambda e=None: self.zoom_key(0.8)),
                        ("<z>", self.zoom_to_selected), ("<Z>", self.zoom_to_selected),
                        ("<h>", self.toggle_points), ("<H>", self.toggle_points),
                        ("<k>", self.toggle_checks), ("<K>", self.toggle_checks),
                        ("<t>", self.toggle_trails), ("<T>", self.toggle_trails),
                        ("<c>", self.open_carry), ("<C>", self.open_carry),
                        ("<s>", self.open_smooth), ("<S>", self.open_smooth),
                        ("<r>", self.refresh_faded), ("<R>", self.refresh_faded),
                        ("<u>", self.open_history), ("<U>", self.open_history),
                        ("<Control-s>", self.save_checkpoint), ("<Control-S>", self.save_checkpoint),
                        ("<f>", self.fit), ("<F>", self.fit), ("<l>", self.toggle_labels), ("<L>", self.toggle_labels),
                        ("<Escape>", self.clear_pick), ("<p>", self.play), ("<P>", self.play)]:
            self.keymap[key] = lambda e, fn=fn: fn()
        if cast:   # Phase 11: 1-9 make that character active; A selects all; M = GROUP…; Shift+Alt+arrows nudge them
            for k in range(1, 10):
                self.keymap[f"<Key-{k}>"] = lambda e, k=k: self.switch_index(k - 1)
            for key, fn in [("<a>", self.select_all_characters), ("<A>", self.select_all_characters),
                            ("<m>", self.open_group), ("<M>", self.open_group),
                            ("<Shift-Alt-Left>", lambda: self.group_nudge(-1, 0)),
                            ("<Shift-Alt-Right>", lambda: self.group_nudge(1, 0)),
                            ("<Shift-Alt-Up>", lambda: self.group_nudge(0, -1)),
                            ("<Shift-Alt-Down>", lambda: self.group_nudge(0, 1))]:
                self.keymap[key] = lambda e, fn=fn: fn()
        if not self.embedded:
            for key, fn in self.keymap.items():
                root.bind(key, fn)
            root.protocol("WM_DELETE_WINDOW", self.close)
        c.focus_set()
        self.enter_frame(0)

    # ---------- state helpers ----------
    def frame(self):
        return self.frames[self.i]

    def st(self):
        return self.states[self.frame()]

    def complete(self, f):
        return all(n in self.states[f].ok for n in ORDER)

    def inside(self, x, y):
        w, h = self.sizes[self.frame()]
        return 0 <= x < w and 0 <= y < h

    def current(self):
        if self.forced:
            return self.forced
        st = self.st()
        for n in ORDER:
            if n not in st.ok:
                return n
        return None

    def image(self):
        f = self.frame()
        if f not in self.images:
            im = Image.open(frame_path(self.dir, f)).convert("RGB")
            padded = Image.new("RGB", (im.width + 2 * PAD, im.height + 2 * PAD), (22, 22, 26))
            padded.paste(im, (PAD, PAD))
            self.images[f], self.sizes[f] = padded, im.size
        return self.images[f]

    def push_undo(self, frames=None, label="Change", others=None):
        """Remember the frames about to change (default: this one) as ONE undo step, so a batch change across
        several frames is undone (and redone) in one go. label says what the step was, for the History window.
        Phase 11: in a multi-character move the step also records whose it is, and others = {char id: [frames]}
        of other characters a group edit is about to change (still one step)."""
        fs = list(frames) if frames else [self.frame()]
        step = (self.i, {f: copy.deepcopy(self.states[f]) for f in fs}, label, time.time())
        if self.cast:
            step = step + (self.active, {cid: {g: copy.deepcopy(self.sessions[cid]["states"][g]) for g in gs}
                                         for cid, gs in (others or {}).items()})
        self.undo.append(step)
        del self.undo[:-history.MAX_STEPS]
        self.redo.clear()   # a new change ends the redo chain
        self.session["changes"] += 1
        self.session["frames"].update(fs)
        self.history_changed()

    # ---------- traced characters (Phase 11, Multi-Character Support) ----------
    def build_frame_buttons(self):
        """The key-frame chips of the side panel (rebuilt when another character becomes active)."""
        for b in self.frame_buttons:
            b.destroy()
        self.frame_buttons = []
        for k, f in enumerate(self.frames):
            b = tk.Label(self.fb_box, text=str(f), width=5, font=hud.BOLD, bg=hud.PANEL2, fg=hud.TEXT, cursor="hand2",
                         highlightthickness=1, highlightbackground=hud.LINE2, pady=3)
            b.grid(row=k // 5, column=k % 5, padx=2, pady=2)
            b.bind("<Button-1>", lambda e, k=k: self.go(k))
            self.frame_buttons.append(b)
            if hasattr(self, "side_canvas"):
                self.wheel_tag(b)

    def wheel_tag(self, w):
        """The mouse wheel scrolls the side panel over w and everything in it (v3.0)."""
        tags = w.bindtags()
        if "TraceSide" not in tags:
            w.bindtags((tags[0], "TraceSide") + tags[1:])
        for c in w.winfo_children():
            self.wheel_tag(c)

    def side_wheel(self, e):
        sc = self.side_canvas
        if sc.winfo_exists() and self.side.winfo_height() > sc.winfo_height():
            sc.yview_scroll(-1 if e.delta > 0 else 1, "units")
        return "break"

    def char(self, cid=None):
        """The registry entry of a character (default: the active one)."""
        cid = cid or self.active
        for c in (self.cast or {}).get("characters", []):
            if c["id"] == cid:
                return c
        return {"id": cid, "name": str(cid), "colour": "#888888", "visible": True, "locked": False}

    def is_locked(self, cid=None):
        return bool(self.cast) and bool(self.char(cid).get("locked"))

    def locked_now(self):
        """True (with a message) when the active character is locked: every edit asks this first."""
        if self.is_locked():
            self.msg(f"“{self.char()['name']}” is locked: unlock it (Lock on its chip) to edit it.", error=True)
            return True
        return False

    def session_data(self):
        return {"frames": self.frames, "states": self.states, "out": self.out, "tdir": self.tdir,
                "disk_text": self.disk_text, "save_problem": self.save_problem, "i": self.i}

    def trace_files(self):
        """{character id: (its trace.json path, its key frames)} for every character (the active one as it is now)."""
        out = {cid: (s["out"], list(s["frames"])) for cid, s in self.sessions.items()}
        if self.active:
            out[self.active] = (self.out, list(self.frames))
        return out

    def states_of(self, cid=None):
        if not self.cast or cid in (None, self.active):
            return self.states
        return self.sessions[cid]["states"]

    def frames_of(self, cid=None):
        if not self.cast or cid in (None, self.active):
            return self.frames
        return self.sessions[cid]["frames"]

    def switch_index(self, k):
        """Keys 1-9: make the k-th character active."""
        if self.cast and 0 <= k < len(self.cast["characters"]):
            self.select_character(self.cast["characters"][k]["id"])
        return "break"

    def select_character(self, cid):
        """Make cid active through the character bar, so its chip, the saved list and the editor all follow."""
        if self.charbar is not None and self.charbar.cs and cid in self.charbar.cs.ids():
            self.charbar.click(cid)
        else:
            self.switch_to(cid)

    def cast_changed(self, bar):
        """The character bar changed something: names, colours, shown / locked, added or deleted characters, or the
        active one. A deleted character's session and undo steps are dropped (its files are archived, not lost)."""
        if not bar.cs:
            return
        entries = bar.cs.characters
        ids = {c["id"] for c in entries}
        for c in entries:
            if c["id"] != self.active and c["id"] not in self.sessions:
                self.sessions[c["id"]] = new_session(self.dir, bar.cs.trace_dir(c["id"]))
        gone = [cid for cid in list(self.sessions) + [self.active] if cid not in ids]
        self.cast["characters"] = entries
        if gone:
            def keep(step):
                return not (len(step) > 4 and (step[4] in gone or any(cid in gone for cid in step[5])))
            self.undo = [s for s in self.undo if keep(s)]
            self.redo = [s for s in self.redo if keep(s)]
            for cid in gone:
                self.sessions.pop(cid, None)
            self.history_changed()
        if bar.active != self.active:
            self.switch_to(bar.active, from_bar=True)
        else:
            self.redraw()
            self.update_panel()
        if self.group_dlg is not None:
            self.group_dlg.changed()

    def switch_to(self, cid, quiet=False, from_bar=False):
        """Make another character the one being edited. The one you leave is saved first and kept in memory with
        its key frame, faded copies and undo, so nothing is lost. -> True when it switched."""
        if not self.cast or cid == self.active or cid not in self.sessions:
            return False
        s = self.sessions[cid]
        if not s["frames"]:   # not traced yet: it starts on the key frames you're looking at
            s["frames"] = list(self.frames)
            s["states"] = {f: FrameState() for f in s["frames"]}
        f = self.frame() if self.frames else None
        if self.active in {c["id"] for c in self.cast["characters"]}:
            self.save()
            self.sessions[self.active] = self.session_data()
        if self.smooth_dlg is not None:
            self.smooth_dlg.close()
        self.active = cid
        self.frames, self.states, self.out, self.tdir = s["frames"], s["states"], s["out"], s["tdir"]
        self.disk_text, self.save_problem = s["disk_text"], s["save_problem"]
        self.forced = self.cycle = self.press = None
        self.build_frame_buttons()
        k = self.frames.index(f) if f in self.frames else min(range(len(self.frames)),
                                                              key=lambda j: abs(self.frames[j] - (f or 0)))
        self.enter_frame(k)
        if self.fitted:
            self.redraw()
        self.update_panel()
        if not from_bar and self.charbar is not None and self.charbar.cs and cid in self.charbar.cs.ids():
            self.charbar.cs.set_active(cid)
            self.charbar.load(self.dir)
        if not quiet:
            self.msg(f"Now editing “{self.char()['name']}”. The others are drawn thin in their colours "
                     "and can't be moved from here.")
        return True

    def save_session(self, cid):
        """Write a character that isn't the active one (after an undo / redo of a group step changed it)."""
        s = self.sessions[cid]
        pts = [{n: s["states"][f].pts[n] for n in ALL if n in s["states"][f].ok} for f in s["frames"]]
        est = [[n for n in ALL if n in s["states"][f].guess and n in s["states"][f].ok] for f in s["frames"]]
        text = trace_io.format_trace(s["frames"], pts, est)
        try:
            with open(s["out"]) as fh:
                disk = fh.read()
        except OSError:
            disk = None
        if disk == text:
            s["disk_text"] = text
            return
        try:
            if disk is not None and disk != s["disk_text"]:
                trace_io.backup_file(s["tdir"], s["out"], "trace", "outside")
            os.makedirs(s["tdir"], exist_ok=True)
            trace_io.write_atomic(s["out"], text)
            s["disk_text"] = text
            self.history_changed()
        except OSError as e:
            self.msg(f"Couldn't save “{self.char(cid)['name']}”: {e}", error=True)

    def other_poses(self):
        """[(entry, pose, is_key)] of the other VISIBLE characters on this frame: their own key pose here, or (dashed)
        the in-between PLAY would draw, inside their traced frames."""
        if not self.cast or not self.frames:
            return []
        f = self.frame()
        out = []
        for c in self.cast["characters"]:
            cid = c["id"]
            if cid == self.active or not c.get("visible", True) or cid not in self.sessions:
                continue
            s = self.sessions[cid]
            st = s["states"].get(f)
            if st is not None and st.ok:
                out.append((c, {n: tuple(st.pts[n]) for n in ORDER if n in st.ok}, True))
                continue
            keys = sorted((g, {n: tuple(s["states"][g].pts[n]) for n in ORDER}) for g in s["frames"]
                          if all(n in s["states"][g].ok for n in ORDER))
            if len(keys) >= 2 and keys[0][0] <= f <= keys[-1][0]:
                import trace_player
                P = trace_player.Motion(keys).pose(float(f))
                out.append((c, {n: (float(P[n][0]), float(P[n][1])) for n in ORDER}, False))
        return out

    def draw_others(self):
        c = self.canvas
        for entry, P, is_key in self.other_poses():
            col = entry.get("colour", "#888888")
            w = 3 if entry["id"] in self.selection() else 2   # selected for group editing: thicker
            kw = {"width": w} if is_key else {"width": w, "dash": (4, 4)}
            for ch in CHAINS:
                for a, b in zip(ch, ch[1:]):
                    if a in P and b in P:
                        c.create_line(*self.to_view(*P[a]), *self.to_view(*P[b]), fill=col, tags=("ov", "other"), **kw)
            for n, p in P.items():
                x, y = self.to_view(*p)
                c.create_oval(x - 3, y - 3, x + 3, y + 3, outline=col, width=1, tags=("ov", "other"))
            if "head" in P:
                x, y = self.to_view(*P["head"])
                c.create_text(x, y - 16, text=entry["name"] + ("" if is_key else "  (in-between)"), fill=col,
                              font=("Segoe UI", 8, "bold"), tags=("ov", "other"))

    # ---------- editing several characters together (Phase 11, step 5) ----------
    def selection(self):
        """The selected characters (Ctrl+click their chips): group edits change these."""
        return set(self.charbar.selected) if self.charbar is not None else {self.active}

    def select_all_characters(self):
        """A: select every visible character."""
        if not self.cast or self.charbar is None:
            return
        self.charbar.selected = {c["id"] for c in self.cast["characters"] if c.get("visible", True)} | {self.active}
        self.charbar.render()
        self.redraw()
        if self.group_dlg is not None:
            self.group_dlg.changed()
        self.msg(f"Selected {len(self.charbar.selected)} characters: Shift+drag moves them together, "
                 "Shift+Alt+arrows nudge them, M transforms them. A click still edits only the active one.")

    def tdir_of(self, cid):
        return self.tdir if cid == self.active else self.sessions[cid]["tdir"]

    def group_members(self, f=None):
        """(the selected characters a group edit on frame f changes, [the selected ones left out, and why])."""
        if not self.cast:
            return [], []
        f = self.frame() if f is None else f
        sel = self.selection()
        members, left = [], []
        for c in self.cast["characters"]:
            cid = c["id"]
            if cid not in sel or (cid != self.active and cid not in self.sessions):
                continue
            if not c.get("visible", True):
                left.append(f"{c['name']} (hidden)")
                continue
            if c.get("locked"):
                left.append(f"{c['name']} (locked)")
                continue
            st = self.states_of(cid).get(f) if f in self.frames_of(cid) else None
            if st is None or not st.pts:
                left.append(f"{c['name']} (not traced on frame {f})")
                continue
            members.append(cid)
        return members, left

    def size_of(self, f):
        if f not in self.sizes:
            try:
                with Image.open(frame_path(self.dir, f)) as im:
                    self.sizes[f] = im.size
            except OSError:
                return None
        return self.sizes[f]

    def mark_outside(self, st, f):
        """Placed points pushed outside the picture become guesses (as when you drag them there)."""
        wh = self.size_of(f)
        if wh:
            w, h = wh
            for n, (x, y) in st.pts.items():
                if n in st.ok and not (0 <= x < w and 0 <= y < h):
                    st.guess.add(n)

    def group_undo(self, changes, label):
        """Back up every character about to change ("group"), then ONE undo step for all of them.
        changes = {char id: [frames]}. Raises OSError when a backup can't be made (then nothing changed)."""
        for cid in changes:
            trace_io.backup(self.tdir_of(cid), "group")
        self.push_undo(frames=changes.get(self.active) or None, label=label,
                       others={c: fs for c, fs in changes.items() if c != self.active})

    def finish_group(self, changes, text):
        for cid, fs in changes.items():
            for f in fs:
                self.mark_outside(self.states_of(cid)[f], f)
        for cid in changes:
            if cid != self.active:
                self.save_session(cid)
        self.changed()
        if self.group_dlg is not None:
            self.group_dlg.changed()
        self.msg(text)

    def names(self, ids):
        return ", ".join(self.char(c)["name"] for c in ids)

    def on_group_press(self, e):
        """Shift+press: start moving the selected characters together (a plain click still edits only the active one)."""
        if not self.cast:
            return self.on_press1(e)
        self.canvas.focus_set()
        members, left = self.group_members()
        if not members:
            self.press = None
            self.msg("Shift+drag moves the selected characters together: select some that are traced on this frame "
                     "(Ctrl+click their chips, or A for all).", error=True)
            return "break"
        self.press = {"kind": "group", "x": e.x, "y": e.y, "members": members, "left": left, "moved": False}
        return "break"

    def on_group_drag(self, e):
        p = self.press
        if not p or p.get("kind") != "group":
            return self.on_drag1(e)
        f = self.frame()
        if not p["moved"]:
            if math.hypot(e.x - p["x"], e.y - p["y"]) < MOVE:
                return
            p["changes"] = {cid: [f] for cid in p["members"]}
            try:
                self.group_undo(p["changes"], f"Moved {self.names(p['members'])} together")
            except OSError as err:
                self.press = None
                self.msg(f"Couldn't make the backups, so nothing was moved: {err}", error=True)
                return
            p["moved"] = True
            p["orig"] = {cid: {n: list(v) for n, v in self.states_of(cid)[f].pts.items()} for cid in p["members"]}
        dx, dy = (e.x - p["x"]) / self.s, (e.y - p["y"]) / self.s
        for cid, P in p["orig"].items():
            st = self.states_of(cid)[f]
            for n, (x, y) in P.items():
                st.pts[n] = [x + dx, y + dy]
        self.draw_overlay()

    def on_group_release(self, e):
        p = self.press
        if not p or p.get("kind") != "group":
            return self.on_release1(e)
        self.press = None
        if p["moved"]:
            self.finish_group(p["changes"], f"Moved {self.names(p['members'])} together (one undo step)."
                              + (f"  Left out: {', '.join(p['left'])}." if p["left"] else ""))
        return "break"

    def group_nudge(self, dx, dy):
        """Shift+Alt+arrows: nudge the selected characters together by one screen pixel."""
        if not self.cast:
            return self.nudge(dx, dy)
        members, left = self.group_members()
        if not members:
            self.msg("Select the characters to nudge together first (Ctrl+click their chips, or A for all).",
                     error=True)
            return "break"
        f = self.frame()
        changes = {cid: [f] for cid in members}
        try:
            self.group_undo(changes, f"Nudged {self.names(members)} together")
        except OSError as err:
            self.msg(f"Couldn't make the backups, so nothing was moved: {err}", error=True)
            return "break"
        step = 1.0 / self.s
        for cid in members:
            st = self.states_of(cid)[f]
            for n, (x, y) in list(st.pts.items()):
                st.pts[n] = [x + dx * step, y + dy * step]
        self.finish_group(changes, f"Nudged {self.names(members)} together."
                          + (f"  Left out: {', '.join(left)}." if left else ""))
        return "break"

    def open_group(self):
        """M: the GROUP… window (move / scale / flip / rotate the selected characters together)."""
        if not self.cast:
            self.msg("Group works on a move with several traced characters (+ Character on the move page).")
            return
        if self.group_dlg is not None:
            self.group_dlg.win.lift()
            return
        import group_dialog
        self.group_dlg = group_dialog.GroupDialog(self)

    def group_result(self, kind, value, about="group", f=None):
        """What a group transformation would make of this frame: {char id: {joint: (x, y)}} (the cyan preview)."""
        import group_dialog as gd
        f = self.frame() if f is None else f
        members, _ = self.group_members(f)
        poses = {cid: {n: tuple(p) for n, p in self.states_of(cid)[f].pts.items()} for cid in members}
        return gd.apply_to_frame(poses, kind, value, about) if poses else {}

    def apply_group(self, kind, value, about="group", scope="this", frm=None, to=None):
        """Transform the selected (visible, unlocked) characters together on this frame, the key frames frm..to, or
        all their key frames: ONE undo step, every changed character backed up first. -> a summary, or None."""
        import group_dialog as gd
        if not self.cast:
            return None
        cur = self.frame()

        def in_scope(f):
            return f == cur if scope == "this" else (frm <= f <= to if scope == "range" else True)
        sel = self.selection()
        changes = {}
        for c in self.cast["characters"]:
            cid = c["id"]
            if cid not in sel or not c.get("visible", True) or c.get("locked") or \
                    (cid != self.active and cid not in self.sessions):
                continue
            fs = [f for f in self.frames_of(cid) if in_scope(f) and self.states_of(cid)[f].pts]
            if fs:
                changes[cid] = fs
        if not changes:
            self.msg("Nothing to change: no selected, visible, unlocked character is traced on those frames.",
                     error=True)
            return None
        what = dict(gd.KINDS)[kind].lower()
        try:
            self.group_undo(changes, f"Group {what}: {self.names(changes)}")
        except OSError as err:
            self.msg(f"Couldn't make the backups, so nothing was changed: {err}", error=True)
            return None
        for f in sorted({f for fs in changes.values() for f in fs}):
            poses = {cid: {n: tuple(p) for n, p in self.states_of(cid)[f].pts.items()}
                     for cid, fs in changes.items() if f in fs}
            for cid, P in gd.apply_to_frame(poses, kind, value, about).items():
                st = self.states_of(cid)[f]
                for n, p in P.items():
                    st.pts[n] = [p[0], p[1]]
        n = sum(len(fs) for fs in changes.values())
        done = f"{what} of {self.names(changes)} ({n} frame{'s' if n > 1 else ''})"
        self.finish_group(changes, f"Group {done}. One undo step; each character was backed up first.")
        return done

    def checkpoint_all(self, name):
        """Ctrl+S: a checkpoint of this trace; in a multi-character move, of every character (same name)."""
        if not self.cast:
            return trace_io.checkpoint(self.dir, name)
        made = []
        for cid, s in self.sessions.items():
            if cid != self.active and trace_io.find_file(s["tdir"], trace_io.TRACE):
                made += trace_io.checkpoint(s["tdir"], name)
        return trace_io.checkpoint(self.tdir, name) + made

    def msg(self, text, error=False):
        problem = getattr(self, "save_problem", None)
        if problem and not error:   # Phase 9: "not saved" stays in view until a save works again
            text, error = problem + "   " + text, True
        self.msg_label.config(text=text, fg=hud.RED_HI if error else hud.DIM)

    # ---------- coordinates ----------
    def to_view(self, x, y):
        return (x - self.ox) * self.s, (y - self.oy) * self.s

    def to_world(self, sx, sy):
        return sx / self.s + self.ox, sy / self.s + self.oy

    def hits(self, sx, sy):
        """Joints within HIT screen pixels of (sx, sy), nearest first."""
        near = []
        for n, p in self.st().pts.items():
            vx, vy = self.to_view(*p)
            d = math.hypot(vx - sx, vy - sy)
            if d <= HIT:
                near.append((d, ALL.index(n), n))
        return [n for _, _, n in sorted(near)]

    def hit(self, sx, sy):
        """The joint to grab at (sx, sy): the selected one when it is under the cursor, otherwise the nearest."""
        near = self.hits(sx, sy)
        if self.forced in near:
            return self.forced
        return near[0] if near else None

    # ---------- frames ----------
    def enter_frame(self, i):
        self.i, self.forced, self.press = i, None, None
        self.image()
        # every joint this frame doesn't have yet starts as a faded copy from the nearest frame where you placed it
        # (v1.1 did this only for a completely empty frame)
        fill_missing(self.states, self.frames, i)
        if self.fitted:
            self.redraw()
        self.update_panel()
        if self.smooth_dlg is not None:
            self.smooth_dlg.draw_graphs()     # move the graphs' "this frame" line
        if getattr(self, "group_dlg", None) is not None:
            self.group_dlg.changed()          # the GROUP… preview follows the frame

    def go(self, k):
        if 0 <= k < len(self.frames) and k != self.i:
            self.enter_frame(k)

    def next_frame(self):
        st, f = self.st(), self.frame()
        faded = [n for n in ORDER if n in st.pts and n not in st.ok]
        if faded and not self.is_locked():
            self.push_undo(label=f"Kept {len(faded)} faded point{'s' if len(faded) > 1 else ''}")
            st.ok.update(faded)
            st.guess.update(n for n in faded if not self.inside(*st.pts[n]))
            self.save()
        kept = (f"Kept {len(faded)} faded point{'s' if len(faded) > 1 else ''} on frame {f} as traced "
                f"({', '.join(faded) if len(faded) <= 4 else ', '.join(faded[:4]) + ' …'}); Ctrl+Z undoes it.  "
                if faded else "")
        if self.i + 1 < len(self.frames):
            self.enter_frame(self.i + 1)
            if kept:
                self.msg(kept)
        else:
            self.redraw()
            self.update_panel()
            done = all(self.complete(f) for f in self.frames)
            self.msg(kept + "That was the last frame. " + ("Every frame is done: close the window to finish."
                     if done else "Some frames still have missing points (see the buttons)."))

    # ---------- carry-forward ----------
    def refresh_faded(self):
        """R: copy this frame's faded points again from the nearest traced frames (your placed points stay)."""
        if self.locked_now():
            return
        st = self.st()
        if all(n in st.ok for n in ORDER):
            self.msg("Every point on this frame is placed: there are no faded points to refresh.")
            return
        self.push_undo(label="Refreshed faded points")
        got = refresh_faded(self.states, self.frames, self.i)
        self.redraw()
        self.update_panel()
        self.msg(f"Refreshed {len(got)} faded point(s) from the nearest traced frames. Ctrl+Z undoes it."
                 if got else "Nothing to copy: no other frame has those joints placed yet.")

    def open_carry(self):
        """C: the Carry Forward window."""
        if self.locked_now():
            return
        if not self.st().ok:
            self.msg("Place or keep some points on this frame first: Carry Forward copies the points you placed here.")
            return
        CarryDialog(self)

    def apply_carry(self, targets, joints, as_traced, replace, also=()):
        """Run a carry-forward as one undo step. A dated backup is made first whenever saved points change.
        Phase 11: also = other characters that do the same, each copying ITS OWN points of this frame to its own
        key frames among targets (visible, unlocked ones traced on this frame); still one undo step."""
        if self.locked_now():
            return None
        f = self.frame()
        plan = carry_points(self.states, f, targets, joints, as_traced, replace, dry=True)
        others = {}
        for cid in also or ():
            if cid == self.active or cid not in self.sessions or self.is_locked(cid) or \
                    not self.char(cid).get("visible", True):
                continue
            s = self.sessions[cid]
            if f not in s["frames"] or not s["states"][f].ok:
                continue
            tg = [t for t in targets if t in s["frames"] and t != f]
            p2 = carry_points(s["states"], f, tg, joints, as_traced, replace, dry=True)
            if p2["set"]:
                others[cid] = (tg, p2)
        if not plan["set"] and not others:
            self.msg("Nothing to carry: those joints are already placed on those frames (or not placed here).")
            return plan
        try:
            if as_traced or plan["replaced"]:
                trace_io.backup(self.tdir, "batch")
            for cid, (tg, p2) in others.items():
                if as_traced or p2["replaced"]:
                    trace_io.backup(self.sessions[cid]["tdir"], "batch")
        except OSError as e:
            self.msg(f"Couldn't make the backup, so nothing was changed: {e}", error=True)
            return None
        self.push_undo(frames=[t for t in targets if t != f] or None,
                       label=f"Carry forward from frame {f} ({len(plan['set'])} point{'s' if len(plan['set']) != 1 else ''})"
                             + (f" + {self.names(others)}" if others else ""),
                       others={cid: tg for cid, (tg, _) in others.items()})
        done = carry_points(self.states, f, targets, joints, as_traced, replace)
        for cid, (tg, _) in others.items():
            carry_points(self.sessions[cid]["states"], f, tg, joints, as_traced, replace)
            self.save_session(cid)
        self.save()
        self.redraw()
        self.update_panel()
        frames = sorted({t for t, _ in done["set"]})
        self.msg(f"Carried {len(done['set'])} point(s) from frame {f} to frame{'s' if len(frames) > 1 else ''} "
                 f"{', '.join(map(str, frames))} as {'traced points' if as_traced else 'faded starting points'}"
                 + (f"; replaced {len(done['replaced'])} of yours" if done["replaced"] else "")
                 + (f"; kept {len(done['kept'])} of yours" if done["kept"] else "")
                 + (f"; the same for {self.names(others)}" if others else "") + ".  Ctrl+Z undoes it all.")
        return done

    # ---------- smoothing (Phase 4) ----------
    def placed_points(self):
        """{frame: {joint: [x, y]}} of the points you placed (faded ones are left out)."""
        return {f: {n: list(self.states[f].pts[n]) for n in ORDER if n in self.states[f].ok} for f in self.frames}

    def open_smooth(self):
        """S: the Smooth window (non-modal, so you can keep moving between frames to check the preview)."""
        if self.locked_now():
            return
        if self.smooth_dlg is not None:
            self.smooth_dlg.win.lift()
            return
        if len([f for f in self.frames if self.states[f].ok]) < 3:
            self.msg("Smoothing needs at least 3 key frames with placed points.")
            return
        self.smooth_dlg = SmoothDialog(self)

    def apply_smooth(self, new, label):
        """Write the smoothed positions as ONE undo step, after a dated backup of the current trace."""
        if self.locked_now():
            return False
        if not new:
            self.msg("Nothing to change: no point would move.")
            return False
        try:
            trace_io.backup(self.tdir, "smooth")
        except OSError as e:
            self.msg(f"Couldn't make the backup, so nothing was changed: {e}", error=True)
            return False
        self.push_undo(frames=list(new), label=f"Smoothing ({label})")
        w, h = self.sizes.get(self.frame(), (None, None))
        for f, J in new.items():
            st = self.states[f]
            for n, p in J.items():
                st.pts[n] = list(p)
                if w and not (0 <= p[0] < w and 0 <= p[1] < h):
                    st.guess.add(n)     # pushed outside the frame: a guess, as when you drag it there
        self.smooth_preview = None
        self.save()
        self.redraw()
        self.update_panel()
        k = sum(len(J) for J in new.values())
        self.msg(f"Smoothed {k} point(s) on {len(new)} frame(s) ({label}). Ctrl+Z undoes it; the trace before "
                 "smoothing is also in Backups….")
        return True

    # ---------- editing ----------
    def place(self, name, x, y, guess=False):
        if self.locked_now():
            return
        st = self.st()
        self.push_undo(label=("Placed " if name not in st.ok else "Re-placed ") + name
                       + (" (the faded figure followed)" if not st.ok and name in st.pts else ""))
        if not st.ok and name in st.pts:   # first click on a faded copy: the whole copy follows it
            dx, dy = x - st.pts[name][0], y - st.pts[name][1]
            for n in st.pts:
                st.pts[n] = [st.pts[n][0] + dx, st.pts[n][1] + dy]
        st.pts[name] = [x, y]
        st.ok.add(name)
        if guess or not self.inside(x, y):
            st.guess.add(name)
        else:
            st.guess.discard(name)
        self.forced = None
        self.changed()

    def keep(self):
        if self.locked_now():
            return
        cur, st = self.current(), self.st()
        if cur is None:
            self.msg("All 12 points are placed on this frame. Drag one to fix it, or press Enter for the next frame.")
        elif cur in st.pts and cur not in st.ok:
            self.push_undo(label=f"Kept faded {cur}")
            st.ok.add(cur)
            if not self.inside(*st.pts[cur]):
                st.guess.add(cur)
            self.forced = None
            self.changed()
        else:
            self.msg(f"There's no faded {cur} to keep: click where it is.")

    def pick(self, name):
        self.forced = name
        self.canvas.focus_set()
        self.draw_overlay()
        self.update_panel()

    def clear_pick(self):
        self.forced = None
        self.cycle = None
        self.draw_overlay()
        self.update_panel()

    # ---------- selecting and correcting (keyboard and Ctrl+click) ----------
    def select_step(self, d):
        """Tab / Shift+Tab: select the next / previous joint. The first Tab selects the joint being asked for."""
        if self.forced is None:
            target = self.current() or (ALL[0] if d > 0 else ALL[-1])
        else:   # v3.0: Tab also reaches the optional joints, after the 12
            target = ALL[(ALL.index(self.forced) + d) % len(ALL)]
        self.pick(target)
        self.say_selected()
        return "break"   # keep Tab from moving the keyboard focus

    def say_selected(self):
        n, st = self.forced, self.st()
        if not n:
            return
        if n in st.pts:
            x, y = st.pts[n]
            state = "" if n in st.ok else " (faded copy)"
            self.msg(f"{n} selected at x {x:.1f}, y {y:.1f}{state}.  Alt+arrows nudge it, Del removes it, G = guess, "
                     "a click re-places it, Esc = normal order.")
        else:
            self.msg(f"{n} selected. It isn't placed on this frame yet: click where it is.")

    def on_ctrl_click(self, e):
        """Ctrl+click: select the joint under the cursor. Clicking the same spot again steps through joints that
        overlap there (a hand on the face, crossed legs)."""
        self.canvas.focus_set()
        near = self.hits(e.x, e.y)
        if not near:
            self.msg("No point there. Ctrl+click on a point to select it.")
            return "break"
        c = self.cycle
        if c and abs(c[0] - e.x) <= 3 and abs(c[1] - e.y) <= 3 and c[2] == near:
            k = (c[3] + 1) % len(near)
        else:
            k = 0
        self.cycle = (e.x, e.y, near, k)
        self.pick(near[k])
        self.say_selected()
        if len(near) > 1:
            self.msg(self.msg_label.cget("text") + f"  ({k + 1} of {len(near)} here: Ctrl+click again for the next)")
        return "break"

    def target(self, need_placed=True):
        """The selected joint, or (with nothing selected) the joint being asked for."""
        n = self.forced or self.current()
        if n and need_placed and n not in self.st().pts:
            return None
        return n

    def nudge(self, dx, dy):
        """Alt+arrows: move the selected joint by one screen pixel (0.25 frame px at 4x zoom, and so on)."""
        if self.locked_now():
            return "break"
        n, st = self.forced, self.st()
        if not n or n not in st.pts:
            self.msg("Select a joint first: Tab, Ctrl+click it, or click its name in the list.")
            return "break"
        self.push_undo(label=f"Nudged {n}")
        step = 1.0 / self.s
        x, y = st.pts[n][0] + dx * step, st.pts[n][1] + dy * step
        st.pts[n] = [x, y]
        st.ok.add(n)
        if not self.inside(x, y):
            st.guess.add(n)
        self.changed()
        self.say_selected()
        return "break"

    def toggle_guess(self):
        if self.locked_now():
            return
        n, st = self.target(), self.st()
        if not n:
            self.msg("Select a placed joint first (Tab or Ctrl+click), then press G.")
            return
        self.push_undo(label=f"{n}: guess {'off' if n in st.ok and n in st.guess else 'on'}")
        if n in st.ok and n in st.guess:
            st.guess.discard(n)
        else:
            st.guess.add(n)
        st.ok.add(n)
        self.changed()
        self.msg(f"{n} is {'now a guess (yellow)' if n in st.guess else 'no longer a guess'}.")

    def delete_point(self):
        """Del: take the selected joint off this frame (it becomes the next point to place). Undo brings it back."""
        if self.locked_now():
            return
        n, st = self.forced, self.st()
        if not n or n not in st.pts:
            self.msg("Select the joint to remove first (Tab, Ctrl+click or its name), then press Delete.")
            return
        self.push_undo(label=f"Removed {n}")
        st.pts.pop(n, None)
        st.ok.discard(n)
        st.guess.discard(n)
        self.changed()
        self.msg(f"Removed {n} from frame {self.frame()}. Click to place it again, or Ctrl+Z to undo.")

    def go_unfinished(self, d):
        """N / Shift+N: the next / previous key frame that still has missing (or unchecked) points."""
        k = len(self.frames)
        for step in range(1, k + 1):
            j = (self.i + d * step) % k
            if not self.complete(self.frames[j]):
                if j == self.i:
                    break
                self.enter_frame(j)
                return
        self.msg("Every other key frame has all 12 points." if not self.complete(self.frame())
                 else "Every key frame has all 12 points.")

    # ---------- zoom and pan ----------
    def zoom_at(self, factor, sx, sy):
        wx, wy = self.to_world(sx, sy)
        self.s = min(ZOOM_MAX, max(ZOOM_MIN, self.s * factor))
        self.ox, self.oy = wx - sx / self.s, wy - sy / self.s
        self.redraw()
        self.xy_label.config(text=self.zoom_text())

    def zoom_key(self, factor):
        """+ / -: zoom at the mouse when it is over the picture, else at the middle of the view."""
        c = self.canvas
        sx, sy = c.winfo_pointerx() - c.winfo_rootx(), c.winfo_pointery() - c.winfo_rooty()
        if not (0 <= sx < c.winfo_width() and 0 <= sy < c.winfo_height()):
            sx, sy = c.winfo_width() / 2, c.winfo_height() / 2
        self.zoom_at(factor, sx, sy)

    def zoom_to_selected(self):
        n = self.target()
        if not n:
            self.msg("Select a placed joint first (Tab or Ctrl+click), then press Z.")
            return
        c = self.canvas
        x, y = self.st().pts[n]
        self.s = min(ZOOM_MAX, max(self.s, ZOOM_TO))
        self.ox, self.oy = x - c.winfo_width() / (2 * self.s), y - c.winfo_height() / (2 * self.s)
        self.redraw()
        self.xy_label.config(text=self.zoom_text())

    def pan_steps(self, dx, dy):
        self.ox += dx * 60 / self.s
        self.oy += dy * 60 / self.s
        self.redraw()

    def zoom_text(self):
        return f"zoom {self.s * 100:.0f}%"

    def toggle_points(self):
        self.show_points = not self.show_points
        self.redraw()
        self.msg("Points shown." if self.show_points else "Points hidden, to see the picture. Press H to show them.")

    # ---------- motion trails (Phase 5) ----------
    def build_ribbon(self, box):
        """v3.3: the editor's ribbon. Home: placing points and moving through frames. Tools: carry forward,
        smoothing, history. View: zoom, labels and motion trails (they were a bar over the frame)."""
        import ribbon
        file_items = [("Finish Tracing", self.close), None,
                      ("Save Checkpoint…", self.save_checkpoint, "Ctrl+S"), ("History…", self.open_history, "U")]
        if self.embedded:
            file_items.insert(0, ("Back to Moves", lambda: self.on_back and self.on_back(self)))
        rb = self.ribbon = ribbon.Ribbon(box, file_items)
        rb.pack(side="top", fill="x", padx=12, pady=(8, 0))
        home = rb.tab("Home")
        g = home.group("Point")
        g.button("Keep", self.keep, "Keep the ghost point from the previous frame (Space)")
        g.button("Guess", self.toggle_guess, "Mark the selected point as a guess for a hidden joint (G)")
        g.button("Delete", self.delete_point, "Remove the selected point (Delete)")
        g = home.group("Frame")
        g.button("◀", lambda: self.go(self.i - 1), "Previous key frame (←)", padx=6)
        g.button("Next Frame", self.next_frame, "Go to the next key frame (Enter)")
        g.button("Next Unfinished", lambda: self.go_unfinished(1), "The next frame that still needs points (N)")
        g = home.group("Review")
        g.button("Play", self.play, "Play the animation as the game's stickman (P)")
        g.button("Finish", self.close, "Save and finish tracing", kind="red")
        if self.embedded:
            g = home.group("Moves")
            g.button("Back to Moves", lambda: self.on_back and self.on_back(self), "Return to the move list")
        tools = rb.tab("Tools")
        g = tools.group("Points")
        g.button("Carry Forward…", self.open_carry, "Copy chosen joints to other key frames (C)")
        g.button("Refresh Ghost", self.refresh_faded, "Rebuild the faded copy from the previous frame (R)")
        g = tools.group("Clean up")
        g.button("Smooth…", self.open_smooth, "Remove jitter from joint paths, with a preview (S)")
        g.button("Length Check", self.toggle_checks, "Flag bones that are much longer or shorter than usual (K)")
        g = tools.group("History")
        g.button("History…", self.open_history, "Every step, with undo to any point (U)")
        g.button("Checkpoint…", self.save_checkpoint, "Save a named checkpoint (Ctrl+S)")
        view = rb.tab("View")
        g = view.group("Zoom")
        g.button("Fit", self.fit, "Fit the frame in the window (F)")
        g.button("Zoom to Point", self.zoom_to_selected, "Zoom in on the selected point (Z)")
        g.button("+", lambda: self.zoom_key(1.25), "Zoom in (+)", padx=6)
        g.button("−", lambda: self.zoom_key(0.8), "Zoom out (−)", padx=6)
        g = view.group("Show")
        g.button("Joint Names", self.toggle_labels, "Show or hide the joint names (L)")
        g.button("Hide Points", self.toggle_points, "Hide the points to see the frame (H)")
        self.build_trail_bar(view)

    def build_trail_bar(self, view):
        """Motion trails (Phase 5), now in the ribbon's View tab: on / off, which joints, how long, past / future,
        visibility."""
        g = view.group("Trails")
        self.trail_bar = g
        self.trail_btn = g.button("Trails", self.toggle_trails, "Show the paths of the chosen joints (T)")
        self.trail_vars = {n: tk.BooleanVar(value=n in trails.DEFAULT_JOINTS) for n in ORDER}
        mb = tk.Menubutton(g.cur(), text="Joints ▾", bg=hud.PANEL2, fg=hud.TEXT, activebackground=hud.RED_LO,
                           activeforeground=hud.TEXT, font=hud.SMALL, relief="flat", padx=8, pady=2,
                           highlightthickness=1, highlightbackground=hud.LINE2, cursor="hand2")
        menu = tk.Menu(mb, tearoff=False)
        for n in ORDER:
            menu.add_checkbutton(label=n, variable=self.trail_vars[n], command=self.trails_changed)
        mb.configure(menu=menu)
        g.place(mb)
        for text, cmd in (("Hands", lambda: self.trail_preset("hands")), ("Feet", lambda: self.trail_preset("feet")),
                          ("Head", lambda: self.trail_preset("head")), ("Selected", self.trail_selected)):
            g.button(text, cmd)
        g = view.group("Trail options")
        g.label("Length")
        self.trail_len = tk.StringVar(value=trails.DEFAULT_LENGTH)
        lb = ttk.Combobox(g.cur(), textvariable=self.trail_len, values=trails.LENGTHS, state="readonly", width=4)
        g.place(lb, padx=(0, 6))
        lb.bind("<<ComboboxSelected>>", lambda e: self.trails_changed())
        self.trail_past = tk.BooleanVar(value=True)
        self.trail_future = tk.BooleanVar(value=True)
        for text, var in (("Past", self.trail_past), ("Future", self.trail_future)):
            g.check(text, var, self.trails_changed)
        g.row()
        g.label("Visibility")
        self.trail_alpha = tk.IntVar(value=int(trails.DEFAULT_ALPHA * 100))
        sc = tk.Scale(g.cur(), from_=20, to=100, orient="horizontal", variable=self.trail_alpha, length=80,
                      command=lambda v: self.trails_changed())
        hud.style_scale(sc, bg=hud.PANEL)
        g.place(sc, padx=(0, 6))
        g.button("Clear", self.clear_trails, "Turn every trail joint off")
        g.button("Reset", self.reset_trails, "Back to the default trails")

    def trail_joints(self):
        return [n for n in ORDER if self.trail_vars[n].get()]

    def trails_changed(self):
        if not self.trail_on and self.trail_joints():
            self.set_trails(True, quiet=True)
        self.redraw()

    def set_trails(self, on, quiet=False):
        self.trail_on = on
        self.trail_btn.set_kind("red" if on else "normal")
        self.trail_btn.configure(text="Trails On" if on else "Trails")
        if self.fitted:
            self.redraw()
        if not quiet:
            j = self.trail_joints()
            self.msg(("Trails on: " + (", ".join(j) if j else "no joints picked (Joints ▾ or a preset)") +
                      f". Solid = past, dashed = future, {self.trail_len.get()} key frame(s) each way.")
                     if on else "Trails off (T turns them back on).")

    def toggle_trails(self):
        self.set_trails(not self.trail_on)

    def trail_preset(self, key):
        for n, v in self.trail_vars.items():
            v.set(n in trails.PRESETS[key])
        self.set_trails(True)

    def trail_selected(self):
        if not self.forced:
            self.msg("Select a joint first (Tab, Ctrl+click or its name), then Selected shows its trail.")
            return
        for n, v in self.trail_vars.items():
            v.set(n == self.forced)
        self.set_trails(True)

    def clear_trails(self):
        for v in self.trail_vars.values():
            v.set(False)
        self.redraw()
        self.msg("Trails cleared. Pick joints (Joints ▾, Hands, Feet, Head, Selected) or Reset.")

    def reset_trails(self):
        for n, v in self.trail_vars.items():
            v.set(n in trails.DEFAULT_JOINTS)
        self.trail_len.set(trails.DEFAULT_LENGTH)
        self.trail_past.set(True)
        self.trail_future.set(True)
        self.trail_alpha.set(int(trails.DEFAULT_ALPHA * 100))
        self.set_trails(True)

    def trail_paths(self):
        """{joint: (past, future)} for the chosen joints: placed points on the other key frames, plus this frame's
        point (placed or faded) so the lines meet the joint you're working on."""
        cur = self.frame()
        out = {}
        for n in self.trail_joints():
            pos = {f: tuple(self.states[f].pts[n]) for f in self.frames if n in self.states[f].ok}
            if n in self.st().pts:
                pos[cur] = tuple(self.st().pts[n])
            past, future = trails.split(pos, self.frames, cur, self.trail_len.get())
            if len(past) + len(future) > 1:
                out[n] = (past, future)
        return out

    def blend_trails(self, img, dx, dy):
        """Blend the trails into the frame picture (img = what the canvas shows, placed at canvas (dx, dy)).
        Done in draw_image, which already runs on every pan, zoom, frame change and edit, so the trails cost
        almost nothing extra; while you drag a point they wait and catch up when you let go."""
        if not (self.trail_on and self.show_points):
            return
        paths = self.trail_paths()
        if paths:
            def to_img(x, y):
                vx, vy = self.to_view(x, y)
                return vx - dx, vy - dy
            trails.draw(img, paths, to_img, alpha=self.trail_alpha.get() / 100, show_past=self.trail_past.get(),
                        show_future=self.trail_future.get())

    def toggle_checks(self):
        self.checks = not self.checks
        self.draw_overlay()
        self.update_panel()
        self.msg("Bone-length check on." if self.checks else "Bone-length check off (K turns it back on).")

    def bone_report(self, n):
        """The selected joint's bones on this frame next to the same bones on the previous key frame (plain info)."""
        st = self.st()
        prev = next((self.states[self.frames[j]] for j in range(self.i - 1, -1, -1)
                     if self.states[self.frames[j]].ok), None)
        parts = []
        for a, b in BONES:
            if n in (a, b) and a in st.ok and b in st.ok:
                L = math.dist(st.pts[a], st.pts[b])
                other = b if a == n else a
                txt = f"to {other} {L:.0f} px"
                if prev and a in prev.ok and b in prev.ok:
                    txt += f" (before {math.dist(prev.pts[a], prev.pts[b]):.0f})"
                parts.append(txt)
        return f"{n}: " + ",  ".join(parts) if parts else ""

    def do_undo(self):
        if not self.undo:
            self.msg("Nothing to undo.")
            return
        self.apply_step(self.undo, self.redo, "Undone")

    def do_redo(self):
        if not self.redo:
            self.msg("Nothing to redo.")
            return
        self.apply_step(self.redo, self.undo, "Redone")

    def apply_step(self, src, dst, word):
        """Take the last step off src, put what it replaces on dst (so it can be reversed again) and restore it.
        Phase 11: a step belongs to a character (the editor switches to it first) and a group step also changes
        other characters; a locked character's step is refused."""
        step = src[-1]
        owner = step[4] if len(step) > 4 else None
        extra = step[5] if len(step) > 5 else {}
        if self.cast:
            for cid in [owner, *extra]:
                if cid and self.is_locked(cid):
                    self.msg(f"\u201c{self.char(cid)['name']}\u201d is locked: unlock it to "
                             f"{'undo' if word == 'Undone' else 'redo'} this step.", error=True)
                    return
            if owner and owner != self.active:
                self.switch_to(owner, quiet=True)
        src.pop()
        i, snap, label, t = step[:4]
        back = (i, {f: copy.deepcopy(self.states[f]) for f in snap}, label, t)
        if len(step) > 4:
            back = back + (owner, {cid: {g: copy.deepcopy(self.sessions[cid]["states"][g]) for g in gs}
                                   for cid, gs in extra.items()})
        dst.append(back)
        for cid, gs in extra.items():   # the other characters a group step changed
            for g, st in gs.items():
                self.sessions[cid]["states"][g] = copy.deepcopy(st)
            self.save_session(cid)
        self.history_changed()
        self.restore_snapshot(i, snap)
        n = len(snap) + sum(len(gs) for gs in extra.values())
        self.msg(f"{word}: {label}" + (f" ({n} frames)" if n > 1 else "") + "."
                 + ("  Ctrl+Y redoes it." if word == "Undone" and self.redo else ""))

    # ---------- history and checkpoints (Phase 9) ----------
    def history_changed(self):
        """The undo / redo steps or the trace changed: write trace_history.json a moment later (not on every
        mouse move), and keep the History window up to date."""
        self.hist_dirty = True
        if self.hist_job is None:
            try:
                self.hist_job = self.root.after(1500, self.flush_history)
            except (tk.TclError, RuntimeError):
                self.hist_job = None

    def flush_history(self):
        """Write the undo / redo steps and this session's log entry to trace_history.json now (if anything changed)."""
        if self.hist_job is not None:
            try:
                self.root.after_cancel(self.hist_job)
            except (tk.TclError, RuntimeError):
                pass
            self.hist_job = None
        if not self.hist_dirty:
            return
        try:
            data, _ = history.load(self.dir)   # keep log entries other windows added meanwhile
            if self.cast:   # Phase 11: one list for all characters, tied to every character's trace text
                self.sessions[self.active] = self.session_data()
                data["version"], data["trace_sha1"], data["frames"] = 2, None, []
                data["traces"] = {cid: history.text_sha1(s["out"]) for cid, s in self.sessions.items()}
                data["frames_by"] = {cid: list(s["frames"]) for cid, s in self.sessions.items()}
            else:   # a single-character move writes version 1, also after it had characters (Phase 11)
                data["version"] = history.VERSION
                data.pop("traces", None)
                data.pop("frames_by", None)
                data["trace_sha1"] = history.text_sha1(self.out)
                data["frames"] = list(self.frames)
            data["undo"] = [history.encode_step(s) for s in self.undo]
            data["redo"] = [history.encode_step(s) for s in self.redo]
            ses = self.session
            if ses["changes"]:
                ev = next((e for e in data["events"] if isinstance(e, dict) and e.get("id") == ses["id"]), None)
                if ev is None:
                    ev = {"what": "edit", "id": ses["id"], "time": round(ses["start"], 2)}
                    data["events"].append(ev)
                ev["end"], ev["changes"] = round(time.time(), 2), ses["changes"]
                ev["frames"] = sorted(ses["frames"])
                ev["text"] = (f"Edited in Trace: {ses['changes']} change{'s' if ses['changes'] > 1 else ''} on "
                              f"{history.frames_text(ses['frames'])}")
            history.save(self.dir, data)
            self.hist_dirty = False
        except OSError as e:
            self.msg(f"Couldn't save the undo history ({e}); your trace itself is saved.", error=True)
        if self.history_dlg is not None:
            self.history_dlg.refresh()

    def release(self):
        """The editor is about to go away (studio: back to the moves, another move, closing): write the history now
        and close the History window."""
        self.flush_history()
        if self.history_dlg is not None:
            self.history_dlg.close()

    def open_history(self):
        """U: the History window (every undo / redo step; go back or forward to any of them)."""
        if self.history_dlg is not None:
            self.history_dlg.win.lift()
            self.history_dlg.refresh()
            return
        import history_dialog
        self.history_dlg = history_dialog.HistoryDialog(self)

    def undo_to(self, k):
        """Undo until len(self.undo) == k (so step k and everything after it is undone). -> steps undone."""
        n = 0
        while len(self.undo) > max(0, k):
            self.do_undo()
            n += 1
        return n

    def redo_to(self, r):
        """Redo until self.redo has r steps left (so redo step r, counted from the far end, is done). -> steps."""
        n = 0
        while len(self.redo) > max(0, r):
            self.do_redo()
            n += 1
        return n

    def save_checkpoint(self, name=None):
        """Ctrl+S: save the trace now and keep a named copy of it (a checkpoint) in backups\\."""
        self.save()
        if name is None:
            name = hud.ask_text(self.root, "Save checkpoint",
                                "Name this checkpoint. It's a copy of the trace as it is now (and of the fixed trace, "
                                "if there is one). Put it back any time from Backups… on the Trace home.",
                                time.strftime("checkpoint %d %b %H:%M"))
            if name is None:
                self.msg("No checkpoint saved.")
                return None
        try:
            made = self.checkpoint_all(name)
        except OSError as e:
            self.msg(f"Couldn't save the checkpoint: {e}", error=True)
            return None
        if not made:
            self.msg("There's no trace on disk yet to save a checkpoint of: place a point first.", error=True)
            return None
        label = trace_io.list_backups(self.tdir)[0].get("label") or name
        history.add_event(self.dir, "checkpoint", f"Checkpoint “{label}” saved")
        self.msg(f"Checkpoint “{label}” saved ({len(made)} file{'s' if len(made) > 1 else ''}). "
                 "Backups… on the Trace home puts it back.")
        if self.history_dlg is not None:
            self.history_dlg.refresh()
        return made

    def restore_snapshot(self, i, snap):
        for f, st in snap.items():
            self.states[f] = copy.deepcopy(st)
        if i != self.i:
            self.i = i
            self.image()
            self.forced = None   # on the same frame the selection stays, so undoing a nudge keeps the joint picked
        self.changed()

    def play(self):
        """Open the stickman player. It reads the points live, so edits show up while it plays."""
        if self.on_play:
            self.save()
            self.on_play(self)
            return
        if self.player and self.player.alive:
            self.player.win.deiconify()
            self.player.win.lift()
            self.player.win.focus_force()
            return
        import trace_player
        self.player = trace_player.Player(tk.Toplevel(self.root), self.dir, self.keys_now,
                                          os.path.basename(self.dir), trace_dir=self.tdir)

    def keys_now(self):
        keys, unfinished = [], []
        for f in self.frames:
            st = self.states[f]
            if all(n in st.ok for n in ORDER):
                keys.append((f, {n: (float(st.pts[n][0]), float(st.pts[n][1])) for n in ALL if n in st.ok}))
            else:
                unfinished.append(f)
        return sorted(keys), sorted(unfinished)

    def toggle_labels(self):
        self.labels = not self.labels
        self.draw_overlay()

    def changed(self):
        if self.smooth_dlg is not None:     # the Smooth window's preview follows your edits
            self.smooth_dlg.schedule()
        self.save()
        self.redraw()
        self.update_panel()
        if self.history_dlg is not None:
            self.history_dlg.refresh()

    def save(self):
        """Write trace.json (only confirmed points). Phase 9: nothing is written when the file already says exactly
        this, and a trace.json that was changed outside the editor since it was opened (another window, a restore) is
        backed up first (reason "outside"), so neither version is lost."""
        pts = [{n: self.states[f].pts[n] for n in ALL if n in self.states[f].ok} for f in self.frames]
        est = [[n for n in ALL if n in self.states[f].guess and n in self.states[f].ok] for f in self.frames]
        text = trace_io.format_trace(self.frames, pts, est)
        try:
            with open(self.out) as fh:
                disk = fh.read()
        except OSError:
            disk = None
        if disk is None and self.cast and not any(self.states[f].ok for f in self.frames):
            return   # Phase 11: a character with no point yet gets no (empty) trace.json
        if disk == text:
            self.disk_text, self.save_problem = text, None
            self.msg("Saved " + self.out)
            return
        try:
            if disk is not None and disk != self.disk_text:
                trace_io.backup_file(self.tdir, self.out, "trace", "outside")
            trace_io.write_atomic(self.out, text)
            self.disk_text, self.save_problem = text, None
            self.history_changed()
            self.msg("Saved " + self.out)
        except OSError as e:
            if trace_io.is_protected(self.out):
                self.save_problem = ("Not Saved: this trace is protected (read-only). Unprotect it in Trace → "
                                     "Project…, or trace a copy there (Duplicate).")
            else:
                self.save_problem = f"Not Saved: {e}."
            self.msg("")

    # ---------- mouse ----------
    def on_press1(self, e):
        self.canvas.focus_set()
        n = self.hit(e.x, e.y)
        self.press = {"kind": "left", "x": e.x, "y": e.y, "point": n, "moved": False,
                      "start": list(self.st().pts[n]) if n else None}

    def on_drag1(self, e):
        p = self.press
        if not p or p["kind"] != "left" or not p["point"]:
            return
        if not p["moved"] and math.hypot(e.x - p["x"], e.y - p["y"]) < MOVE:
            return
        if not p["moved"]:
            if self.locked_now():
                self.press = None
                return
            p["moved"] = True
            self.push_undo(label=f"Moved {p['point']}")
        st = self.st()
        st.pts[p["point"]] = [p["start"][0] + (e.x - p["x"]) / self.s, p["start"][1] + (e.y - p["y"]) / self.s]
        self.draw_overlay()
        self.on_motion(e)

    def on_release1(self, e):
        if self.press and self.press.get("kind") == "group":   # Shift let go before the mouse button
            return self.on_group_release(e)
        p, self.press = self.press, None
        if not p or p["kind"] != "left":
            return
        if p["moved"]:   # a drag: the point stays where you dropped it
            st, n = self.st(), p["point"]
            st.ok.add(n)
            if not self.inside(*st.pts[n]):
                st.guess.add(n)
            elif not self.inside(*p["start"]):   # dragged in from outside: no longer an automatic guess
                st.guess.discard(n)
            self.changed()
            return
        cur = self.current()   # a click: place the next point exactly there
        if cur is None:
            self.msg("All 12 points are placed on this frame. Drag one to fix it, or press Enter for the next frame.")
            return
        self.place(cur, *self.to_world(e.x, e.y))

    def on_press3(self, e):
        self.canvas.focus_set()
        self.press = {"kind": "right", "x": e.x, "y": e.y, "ox": self.ox, "oy": self.oy, "moved": False}

    def on_press2(self, e):
        self.press = {"kind": "pan", "x": e.x, "y": e.y, "ox": self.ox, "oy": self.oy, "moved": True}

    def on_drag3(self, e):
        p = self.press
        if not p or p["kind"] not in ("right", "pan"):
            return
        if not p["moved"] and math.hypot(e.x - p["x"], e.y - p["y"]) < MOVE + 2:
            return
        p["moved"] = True
        self.ox = p["ox"] - (e.x - p["x"]) / self.s
        self.oy = p["oy"] - (e.y - p["y"]) / self.s
        self.redraw()

    def on_release3(self, e):
        p, self.press = self.press, None
        if not p or p["kind"] != "right" or p["moved"]:
            return
        n, st = self.hit(e.x, e.y), self.st()
        if n:   # toggle "guess" on a point (a faded one becomes a checked guess)
            if self.locked_now():
                return
            self.push_undo(label=f"{n}: guess {'off' if n in st.ok and n in st.guess else 'on'}")
            if n in st.ok and n in st.guess:
                st.guess.discard(n)
            else:
                st.guess.add(n)
            st.ok.add(n)
            self.changed()
            return
        cur = self.current()
        if cur:
            self.place(cur, *self.to_world(e.x, e.y), guess=True)

    def on_wheel(self, e):
        self.zoom_at(1.2 ** (e.delta / 120), e.x, e.y)
        self.draw_loupe(e.x, e.y)

    def on_motion(self, e):
        x, y = self.to_world(e.x, e.y)
        xy = f"x {x:.1f},  y {y:.1f}" if self.s >= 2 else f"x {math.floor(x)},  y {math.floor(y)}"
        self.xy_label.config(text=xy + ("" if self.inside(x, y) else "  (outside)") + "   ·   " + self.zoom_text())
        self.draw_loupe(e.x, e.y)

    def on_resize(self, e):
        if not self.fitted:
            self.fitted = True
            self.fit()
        else:
            self.redraw()

    def fit(self):
        c = self.canvas
        W, H = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
        w, h = self.sizes[self.frame()]
        self.s = min(W / (w + 80), H / (h + 80))
        self.ox = -(W / self.s - w) / 2
        self.oy = -(H / self.s - h) / 2
        self.redraw()

    # ---------- drawing ----------
    def redraw(self):
        self.draw_image()
        self.draw_overlay()

    def draw_image(self):
        c = self.canvas
        W, H = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        x0, y0 = self.ox + PAD, self.oy + PAD
        ix0, iy0 = math.floor(x0), math.floor(y0)
        ix1, iy1 = math.ceil(x0 + W / self.s) + 1, math.ceil(y0 + H / self.s) + 1
        crop = self.image().crop((ix0, iy0, ix1, iy1))
        size = (max(1, round((ix1 - ix0) * self.s)), max(1, round((iy1 - iy0) * self.s)))
        res = Image.Resampling.NEAREST if self.s >= 3 else Image.Resampling.BILINEAR
        shown = crop.resize(size, res)
        dx, dy = (ix0 - x0) * self.s, (iy0 - y0) * self.s
        self.blend_trails(shown, dx, dy)     # motion trails (Phase 5), see-through, under the points
        self.photo = ImageTk.PhotoImage(shown)
        c.delete("img", "loupe")   # the magnifier comes back on the next mouse move
        c.create_image(dx, dy, image=self.photo, anchor="nw", tags="img")
        c.tag_lower("img")

    def draw_overlay(self):
        c, st = self.canvas, self.st()
        c.delete("ov")
        w, h = self.sizes[self.frame()]
        c.create_rectangle(*self.to_view(0, 0), *self.to_view(w, h), outline="#9a9a9a", dash=(4, 4), tags="ov")
        self.flags = bone_flags(self.states, self.frames, self.frame()) if self.checks else {}
        if not self.show_points:
            c.create_text(12, c.winfo_height() - 12, anchor="sw", text="Points Hidden  ·  H to show",
                          fill="#ff8c00", font=("Segoe UI", 10, "bold"), tags="ov")
            c.tag_raise("loupe")
            return
        self.draw_others()   # Phase 11: the other visible characters, thin, in their colours, never grabbed
        cur = self.current()
        limbs = trace_io.chains(st.pts)   # v3.0: with the optional joints that are there
        for ch in limbs:   # the selected joint's bones get a white edge, so its limb stands out
            for a, b in zip(ch, ch[1:]):
                if cur in (a, b) and a in st.pts and b in st.pts:
                    c.create_line(*self.to_view(*st.pts[a]), *self.to_view(*st.pts[b]), fill="#ffffff", width=8,
                                  tags="ov")
        for ch in limbs:
            for a, b in zip(ch, ch[1:]):
                if a in st.pts and b in st.pts:
                    faded = a not in st.ok or b not in st.ok
                    kw = {"width": 2, "dash": (6, 4)} if faded else {"width": 4}
                    c.create_line(*self.to_view(*st.pts[a]), *self.to_view(*st.pts[b]), fill=colour(ch[1]),
                                  tags="ov", **kw)
        for (a, b), (L, med) in self.flags.items():   # unusual bone length: dashed red, with a "!"
            (ax, ay), (bx, by) = self.to_view(*st.pts[a]), self.to_view(*st.pts[b])
            c.create_line(ax, ay, bx, by, fill="#ff3030", width=2, dash=(4, 3), tags="ov")
            c.create_text((ax + bx) / 2 + 8, (ay + by) / 2, text="!", fill="#ff3030",
                          font=("Segoe UI", 12, "bold"), anchor="w", tags="ov")
        prev = (self.smooth_preview or {}).get(self.frame(), {})
        for n, (px, py) in prev.items():   # Smooth preview: where each point would move (cyan)
            if n in st.pts:
                ax, ay = self.to_view(*st.pts[n])
                bx, by = self.to_view(px, py)
                c.create_line(ax, ay, bx, by, fill="#22d3ee", width=2, tags="ov")
                draw_marker(c, n, bx, by, 5, "ov", outline="#22d3ee", width=2, fill="")
        for cid, GP in (self.group_preview or {}).items():   # GROUP… preview (cyan): the result on this frame
            for ch in CHAINS:
                for a, b in zip(ch, ch[1:]):
                    if a in GP and b in GP:
                        c.create_line(*self.to_view(*GP[a]), *self.to_view(*GP[b]), fill="#22d3ee", width=2,
                                      dash=(3, 2), tags="ov")
            for n, (px, py) in GP.items():
                x, y = self.to_view(px, py)
                c.create_oval(x - 3, y - 3, x + 3, y + 3, outline="#22d3ee", width=2, tags="ov")
        if cur in st.pts:   # selected joint: red ring and cross-hair under the marker
            sx, sy = self.to_view(*st.pts[cur])
            c.create_line(sx - 22, sy, sx - 9, sy, fill="#ff3030", width=2, tags="ov")
            c.create_line(sx + 9, sy, sx + 22, sy, fill="#ff3030", width=2, tags="ov")
            c.create_line(sx, sy - 22, sx, sy - 9, fill="#ff3030", width=2, tags="ov")
            c.create_line(sx, sy + 9, sx, sy + 22, fill="#ff3030", width=2, tags="ov")
            c.create_oval(sx - 14, sy - 14, sx + 14, sy + 14, outline="#ff3030", width=3, tags="ov")
        for n in ALL:
            if n not in st.pts:
                continue
            sx, sy = self.to_view(*st.pts[n])
            r = 6
            if n not in st.ok:      # faded copy: dashed grey outline
                draw_marker(c, n, sx, sy, r, "ov", outline="#dddddd", width=2, dash=(2, 2), fill="")
            elif n in st.guess:     # guess: yellow outline
                draw_marker(c, n, sx, sy, r, "ov", outline="#ffff00", width=3, fill="")
            else:                   # placed: white, edged in its group colour
                draw_marker(c, n, sx, sy, r, "ov", fill="white", outline=colour(n), width=2)
            if self.labels or n == cur:
                t = c.create_text(sx + 11, sy - 11, text=n, fill=colour(n), anchor="w",
                                  font=("Segoe UI", 9, "bold"), tags="ov")
                x0, y0, x1, y1 = c.bbox(t)
                c.tag_lower(c.create_rectangle(x0 - 2, y0, x1 + 2, y1, fill="#111111",
                                               outline="#ff3030" if n == cur else "", tags="ov"), t)
        c.tag_raise("loupe")

    def draw_loupe(self, sx, sy):
        c = self.canvas
        c.delete("loupe")
        R, Z = 15, 6   # 31 x 31 frame pixels, 6x bigger
        size = (2 * R + 1) * Z
        x, y = self.to_world(sx, sy)
        ix, iy = math.floor(x + PAD) - R, math.floor(y + PAD) - R
        crop = self.image().crop((ix, iy, ix + 2 * R + 1, iy + 2 * R + 1))
        self.lphoto = ImageTk.PhotoImage(crop.resize((size, size), Image.Resampling.NEAREST))
        lx = 10 if not (sx < size + 40 and sy < size + 40) else c.winfo_width() - size - 10
        ly = 10
        c.create_image(lx, ly, image=self.lphoto, anchor="nw", tags="loupe")
        for n, p in self.st().pts.items():
            qx, qy = lx + (p[0] + PAD - ix) * Z, ly + (p[1] + PAD - iy) * Z
            if lx <= qx <= lx + size and ly <= qy <= ly + size:
                c.create_oval(qx - 5, qy - 5, qx + 5, qy + 5, outline=colour(n), width=2, tags="loupe")
        px, py = lx + (x + PAD - ix) * Z, ly + (y + PAD - iy) * Z
        c.create_line(px, ly, px, ly + size, fill="#ff3030", tags="loupe")
        c.create_line(lx, py, lx + size, py, fill="#ff3030", tags="loupe")
        c.create_rectangle(lx, ly, lx + size, ly + size, outline="white", width=2, tags="loupe")

    def update_panel(self):
        f, st = self.frame(), self.st()
        self.title_label.config(text=f"Frame {f}")
        done = sum(self.complete(x) for x in self.frames)
        if self.cast:   # Phase 11: whose frames these are (short, so a long name still fits)
            self.count_label.config(text=f"{self.char()['name']}  ·  {self.i + 1}/{len(self.frames)}  ·  "
                                         f"{done} done", fg=self.char().get("colour", hud.DIM))
        else:
            self.count_label.config(text=f"{self.i + 1} of {len(self.frames)} key frames  ·  {done} done")
        req = len([n for n in ORDER if n in st.ok])   # the optional joints don't count towards the 12
        self.gauge.set(req, len(ORDER), f"{req}", "of 12 points")
        for k, b in enumerate(self.frame_buttons):
            fk = self.frames[k]
            done = self.complete(fk)
            here = k == self.i
            b.config(text=f"{fk} ✓" if done else str(fk), bg=hud.RED if here else hud.PANEL2,
                     fg="#ffffff" if here else (hud.GREEN if done else hud.TEXT),
                     highlightbackground=hud.RED if here else (hud.GREEN if done else hud.LINE2))
        cur = self.current()
        if cur:
            self.ask_label.config(text=("Re-place  " if cur in st.ok else "Click  ") + cur.upper(),
                                  fg=text_colour(cur))
            extra = ""
            if cur in st.pts and cur not in st.ok:
                extra = ("\nThe faded point is copied from the last frame. Click the real spot, "
                         "or press Space if it's already right.")
            elif cur in st.ok and self.forced == cur:
                x, y = st.pts[cur]
                extra = f"\nAt x {x:.1f}, y {y:.1f}. Click to re-place, drag, or Alt+arrows to nudge."
            self.hint_label.config(text=HINT[cur] + extra)
        else:
            self.ask_label.config(text="Frame Done  ✓", fg=hud.GREEN)
            last = self.i + 1 == len(self.frames)
            self.hint_label.config(text="Drag any point to fix it. " + (
                ("This is the last frame: click Finish when you're happy." if self.embedded else
                 "This is the last frame: close the window when you're happy.") if last
                else "Press Enter for the next frame."))
        for n in ALL:
            if n in st.ok and n in st.guess:
                t = f"?   {n}   (guess)"
            elif n in st.ok:
                t = f"✓   {n}"
            elif n in st.pts:
                t = f"·   {n}   (faded copy)"
            else:
                t = f"+   {n}" if n in EXTRAS else f"     {n}"
            if any(n in bone for bone in self.flags):
                t += "  !"
            self.rows[n].config(text=t, bg=hud.RED_BG if n == cur else BG,
                                font=hud.BOLD if n == cur else hud.SMALL)
        lines = []   # tracing feedback
        if self.flags:   # bones far longer / shorter than usual for this body size
            # (a zero-length bone, two joints on the same spot, crashed this sort before Phase 9: log(0))
            parts = [f"{a}→{b} {L:.0f} px, usually about {usual:.0f}"
                     for (a, b), (L, usual) in sorted(self.flags.items(),
                                                      key=lambda t: -abs(math.log(max(t[1][0], 1e-3) / t[1][1])))]
            more = f" (+{len(parts) - 1} more)" if len(parts) > 1 else ""
            lines.append("! Check " + parts[0] + more + ". A turn can explain it (K = check off).")
        if self.forced and self.forced in st.ok:
            rep = self.bone_report(self.forced)
            if rep:
                lines.append(rep)
        self.check_label.config(text="\n".join(lines), fg=hud.AMBER if self.flags else hud.DIM)

    def close(self):
        self.save()
        self.flush_history()
        todo = []
        for f in self.frames:
            miss = [n for n in ORDER if n not in self.states[f].ok]
            if miss:
                todo.append(f"frame {f}: {len(miss)} point(s) not placed or not checked")
        if todo and not messagebox.askyesno(
                "Not finished", "These frames aren't finished:\n\n" + "\n".join(todo)
                + "\n\nEverything you placed is saved. Finish anyway?\n(Open the folder again to carry on.)",
                parent=self.root):
            return
        if self.embedded:
            check = os.path.join(self.tdir, "trace_check.png")
            drawer = os.path.join(os.path.dirname(os.path.abspath(__file__)), "draw_trace.py")
            if not todo and os.path.exists(drawer):
                subprocess.run([sys.executable, "-I", drawer, self.out, self.dir, check],
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if self.on_finish:
                self.on_finish(self, not todo)
            return
        self.root.destroy()
        print("Saved", self.out)
        for f in self.frames:
            st = self.states[f]
            g = [n for n in ORDER if n in st.guess and n in st.ok]
            print(f"  frame {f}: {len(st.ok)} of 12 points" + (f", guesses: {', '.join(g)}" if g else ""))
        if not todo:
            check = os.path.join(self.tdir, "trace_check.png")
            drawer = os.path.join(os.path.dirname(os.path.abspath(__file__)), "draw_trace.py")
            if os.path.exists(drawer):
                subprocess.run([sys.executable, "-I", drawer, self.out, self.dir, check])


class SmoothDialog:
    """Smooth (S): smooth joint paths over the key frames, with a live preview on the frame (cyan), graphs of the
    original (grey) and smoothed (orange) paths, and numbers. Nothing changes until APPLY (one undo step + backup)."""

    GW, GH = 760, 170     # graph area

    def __init__(self, app):
        self.app = app
        self.job = None
        self.new, self.stats = {}, {}
        self.win = w = tk.Toplevel(app.root, bg=hud.BG)
        w.title("Smooth joint paths")
        w.transient(app.root)
        w.resizable(False, False)
        w.protocol("WM_DELETE_WINDOW", self.close)
        P = dict(padx=14)
        hud.Header(w, "Smooth joint paths").pack(fill="x", pady=(12, 2), **P)
        hud.label(w, "Takes the jitter out of joint paths across your key frames. Cyan on the frame and orange in "
                     "the graphs show the result; nothing changes until Apply. You can keep changing frame in the "
                     "main window (click it, then ← →) to check the preview.", fg=hud.DIM, font=hud.SMALL,
                  anchor="w", justify="left", wraplength=self.GW).pack(fill="x", pady=(0, 8), **P)

        row = tk.Frame(w, bg=hud.BG)
        row.pack(fill="x", **P)
        hud.label(row, "METHOD", font=hud.BOLD).pack(side="left")
        self.method = tk.StringVar(value=smoothing.METHODS[0][1])
        cb = ttk.Combobox(row, textvariable=self.method, values=[t for _, t in smoothing.METHODS], state="readonly",
                          width=34)
        cb.pack(side="left", padx=(8, 18))
        cb.bind("<<ComboboxSelected>>", lambda e: self.schedule())
        hud.label(row, "STRENGTH", font=hud.BOLD).pack(side="left")
        self.strength = tk.IntVar(value=2)
        sc = tk.Scale(row, from_=1, to=10, orient="horizontal", variable=self.strength, length=170,
                      command=lambda v: self.schedule())
        hud.style_scale(sc)
        sc.pack(side="left", padx=8)
        self.s_lbl = hud.label(row, "", fg=hud.DIM, font=hud.SMALL, width=16, anchor="w")
        self.s_lbl.pack(side="left")

        opts = tk.Frame(w, bg=hud.BG)
        opts.pack(fill="x", pady=(6, 0), **P)
        self.protect = tk.BooleanVar(value=True)
        self.keep_ends = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Protect fast moves (keeps the tip of a punch, the top of a jump)",
                        variable=self.protect, command=self.schedule).pack(side="left")
        ttk.Checkbutton(opts, text="Keep first and last frame", variable=self.keep_ends,
                        command=self.schedule).pack(side="left", padx=(18, 0))

        jh = tk.Frame(w, bg=hud.BG)
        jh.pack(fill="x", pady=(10, 0), **P)
        hud.label(jh, "JOINTS", font=hud.BOLD).pack(side="left")
        hud.Button(jh, "All", lambda: self.set_joints(ORDER), padx=6, font=hud.SMALL).pack(side="right")
        hud.Button(jh, "None", lambda: self.set_joints([]), padx=6, font=hud.SMALL).pack(side="right", padx=4)
        if app.forced:
            hud.Button(jh, "Selected Only", lambda: self.set_joints([app.forced]), padx=6,
                       font=hud.SMALL).pack(side="right")
        jg = tk.Frame(w, bg=hud.BG)
        jg.pack(fill="x", pady=(4, 0), **P)
        self.jvars = {}
        groups = [("Torso", ["head", "neck", "waist", "hip"]),
                  ("Front", ["frontElbow", "frontHand", "frontKnee", "frontFoot"]),
                  ("Back", ["backElbow", "backHand", "backKnee", "backFoot"])]
        for col, (title, names) in enumerate(groups):
            hud.label(jg, title, fg=hud.DIM, font=hud.SMALL).grid(row=0, column=col, sticky="w", padx=(0, 30))
            for r, n in enumerate(names, 1):
                v = tk.BooleanVar(value=(n == app.forced) if app.forced else True)
                ttk.Checkbutton(jg, text=n, variable=v, command=self.schedule).grid(row=r, column=col, sticky="w",
                                                                                    padx=(0, 30))
                self.jvars[n] = v

        gh = tk.Frame(w, bg=hud.BG)
        gh.pack(fill="x", pady=(10, 2), **P)
        hud.label(gh, "COMPARE", font=hud.BOLD).pack(side="left")
        self.show = tk.StringVar(value=app.forced or "frontHand")
        self.show_box = ttk.Combobox(gh, textvariable=self.show, values=ORDER, state="readonly", width=14)
        self.show_box.pack(side="left", padx=8)
        self.show_box.bind("<<ComboboxSelected>>", lambda e: self.draw_graphs())
        hud.label(gh, "grey = your trace · orange = smoothed · red line = this frame", fg=hud.DIM,
                  font=hud.SMALL).pack(side="left", padx=8)
        self.graph = tk.Canvas(w, width=self.GW, height=self.GH, bg="#16161a", highlightthickness=0)
        self.graph.pack(pady=(2, 0), **P)

        self.stats_lbl = hud.label(w, "", fg=hud.TEXT, font=hud.SMALL, anchor="w", justify="left", wraplength=760)
        self.stats_lbl.pack(fill="x", pady=(8, 0), **P)
        self.warn_lbl = hud.label(w, "", fg=hud.AMBER, font=hud.SMALL, anchor="w", justify="left", wraplength=760)
        self.warn_lbl.pack(fill="x", **P)
        bar = tk.Frame(w, bg=hud.BG)
        bar.pack(fill="x", pady=12, **P)
        hud.Button(bar, "Close", self.close).pack(side="right", padx=(4, 0))
        self.apply_btn = hud.Button(bar, "Apply", self.apply, kind="red")
        self.apply_btn.pack(side="right")
        w.bind("<Escape>", lambda e: self.close())
        self.refresh()
        w.update_idletasks()   # bottom-left of the main window, so the middle of the frame stays visible
        r = app.root
        x = r.winfo_rootx() + 16
        y = r.winfo_rooty() + max(0, r.winfo_height() - w.winfo_reqheight() - 60)
        w.geometry(f"+{x}+{y}")

    # ---- choices
    def method_key(self):
        return next(k for k, t in smoothing.METHODS if t == self.method.get())

    def joints(self):
        return [n for n in ORDER if self.jvars[n].get()]

    def set_joints(self, names):
        for n, v in self.jvars.items():
            v.set(n in names)
        self.schedule()

    def label(self):
        return f"{self.method.get().split(' (')[0]}, strength {self.strength.get()}" + \
               ("" if self.protect.get() else ", fast moves not protected")

    # ---- preview
    def schedule(self, *_):
        if self.job is not None:
            self.win.after_cancel(self.job)
        self.job = self.win.after(120, self.refresh)

    def refresh(self):
        self.job = None
        if not self.win.winfo_exists():
            return
        joints = self.joints()
        k = self.strength.get()
        self.s_lbl.configure(text=f"{k}  ({'light' if k <= 2 else 'medium' if k <= 5 else 'strong'})")
        pts = self.app.placed_points()
        self.new, self.stats = smoothing.smooth(pts, joints, self.method_key(), k, self.protect.get(),
                                                self.keep_ends.get()) if joints else ({}, {})
        self.app.smooth_preview = self.new
        self.app.draw_overlay()
        st = self.stats
        if not joints:
            self.stats_lbl.configure(text="Pick at least one joint.")
            self.warn_lbl.configure(text="")
            self.apply_btn.configure(state="disabled")
            self.draw_graphs()
            return
        jb, ja = st["jitter_before"], st["jitter_after"]
        drop = f" ({100 * (ja / jb - 1):+.0f}%)" if jb > 1e-9 else ""
        at = st["max_at"]
        self.stats_lbl.configure(text=(
            f"Points that move: {st['changed']} of {st['points']}  ·  average move {st['mean_move']:.1f} px  ·  "
            f"largest {st['max_move']:.1f} px" + (f" ({at[1]}, frame {at[0]})" if at[0] is not None else "")
            + f"\nJitter (frame-to-frame change in speed) of these joints: {jb:.1f} → {ja:.1f} px/frame²{drop}"))
        warn = []
        nk = len([f for f in self.app.frames if self.app.states[f].ok])
        gaps = [b - a for a, b in zip(self.app.frames, self.app.frames[1:])]
        if nk < 6 or (gaps and max(gaps) > 2):
            warn.append(f"Only {nk} key frames" + (f", up to {max(gaps)} frames apart" if gaps and max(gaps) > 1 else "")
                        + ": smoothing works best on a move traced frame by frame. Few, very different key poses "
                          "are real motion, not jitter.")
        scales = [smoothing.body_scale(P) for P in pts.values()]
        scales = [s for s in scales if s]
        bone = sorted(scales)[len(scales) // 2] if scales else None
        if bone and st["max_move"] > 0.5 * bone:
            warn.append(f"Big changes: up to {st['max_move']:.0f} px, more than half a bone ({bone:.0f} px). "
                        "Check the preview: this is reshaping the move, not just steadying it.")
        if not self.protect.get():
            warn.append("Protect fast moves is off: the tips of punches and kicks and the top of jumps get flattened.")
        self.warn_lbl.configure(text="\n".join("! " + x for x in warn))
        self.apply_btn.configure(state="normal" if self.new else "disabled")
        self.draw_graphs()

    def draw_graphs(self):
        """Three panels for one joint: x over time, y over time, and its path in the picture."""
        c = self.graph
        c.delete("all")
        j = self.show.get()
        pts = self.app.placed_points()
        fs = [f for f in self.app.frames if j in pts[f]]
        if len(fs) < 2:
            c.create_text(self.GW / 2, self.GH / 2, text=f"{j} is placed on fewer than 2 key frames.", fill=hud.DIM,
                          font=hud.SMALL)
            return
        orig = {f: pts[f][j] for f in fs}
        sm = {f: self.new.get(f, {}).get(j, orig[f]) for f in fs}
        gap = 20
        pw = (self.GW - 20 - 2 * gap) / 3      # three panels between 10 px margins
        panels = [(10, "x over frames", 0), (10 + pw + gap, "y over frames", 1), (10 + 2 * (pw + gap), "path", None)]
        cur = self.app.frame()
        for x0, title, axis in panels:
            y0, y1, x1 = 22, self.GH - 10, x0 + pw
            c.create_rectangle(x0, y0, x1, y1, outline=hud.LINE)
            c.create_text(x0 + 4, 4, text=title if axis is None else f"{title} ({j})", anchor="nw",
                          fill=hud.DIM, font=hud.SMALL)
            if axis is not None:
                vals = [orig[f][axis] for f in fs] + [sm[f][axis] for f in fs]
                lo, hi = min(vals), max(vals)
                hi = hi if hi - lo > 1e-6 else lo + 1

                def tx(f, x0=x0):
                    return x0 + 6 + (f - fs[0]) / max(fs[-1] - fs[0], 1) * (pw - 12)

                def ty(v, lo=lo, hi=hi, y0=y0, y1=y1):
                    return y1 - 6 - (v - lo) / (hi - lo) * (y1 - y0 - 12)

                if fs[0] <= cur <= fs[-1]:
                    c.create_line(tx(cur), y0, tx(cur), y1, fill="#ff3030")
                c.create_line(*[p for f in fs for p in (tx(f), ty(orig[f][axis]))], fill="#8d8d98", width=1)
                for f in fs:
                    c.create_oval(tx(f) - 2, ty(orig[f][axis]) - 2, tx(f) + 2, ty(orig[f][axis]) + 2, fill="#8d8d98",
                                  outline="")
                c.create_line(*[p for f in fs for p in (tx(f), ty(sm[f][axis]))], fill="#ff8c00", width=2)
            else:   # the path, same scale on both axes, y down as in the picture
                xs = [p[0] for D in (orig, sm) for p in D.values()]
                ys = [p[1] for D in (orig, sm) for p in D.values()]
                span = max(max(xs) - min(xs), max(ys) - min(ys), 1)
                k = min(pw - 12, y1 - y0 - 12) / span
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                mx, my = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2

                def P(p, cx=cx, cy=cy, mx=mx, my=my, k=k):
                    return cx + (p[0] - mx) * k, cy + (p[1] - my) * k

                c.create_line(*[v for f in fs for v in P(orig[f])], fill="#8d8d98", width=1)
                c.create_line(*[v for f in fs for v in P(sm[f])], fill="#ff8c00", width=2)
                if cur in orig:
                    px, py = P(sm[cur])
                    c.create_oval(px - 4, py - 4, px + 4, py + 4, outline="#ff3030", width=2)

    # ---- actions
    def apply(self):
        self.refresh()          # use the current trace, in case it changed since the last preview
        if self.app.apply_smooth(self.new, self.label()):
            self.close()

    def close(self):
        if self.job is not None:
            try:
                self.win.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None
        self.app.smooth_preview = None
        self.app.smooth_dlg = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.app.draw_overlay()


class CarryDialog:
    """Carry Forward (C): copy chosen joints of the current frame to chosen key frames, in one undoable step.
    Plain copying: the points land exactly where they are on this frame."""

    def __init__(self, app):
        self.app = app
        f = app.frame()
        st = app.st()
        self.win = w = tk.Toplevel(app.root, bg=hud.BG)
        w.title(f"Carry forward from frame {f}")
        w.transient(app.root)
        w.resizable(False, False)
        P = dict(padx=14)
        hud.Header(w, f"Carry forward from frame {f}",
                   "Copies the points you placed on this frame to other key frames, at exactly the same spots. "
                   "Nothing looks at the pictures: move them where they belong afterwards.").pack(
            fill="x", pady=(12, 8), **P)

        # joints
        jh = tk.Frame(w, bg=hud.BG)
        jh.pack(fill="x", **P)
        hud.label(jh, "JOINTS", font=hud.BOLD).pack(side="left")
        hud.Button(jh, "All", lambda: self.set_joints(ORDER), padx=6, font=hud.SMALL).pack(side="right")
        hud.Button(jh, "None", lambda: self.set_joints([]), padx=6, font=hud.SMALL).pack(side="right", padx=4)
        if app.forced:
            hud.Button(jh, "Selected Only", lambda: self.set_joints([app.forced]), padx=6,
                       font=hud.SMALL).pack(side="right")
        jg = tk.Frame(w, bg=hud.BG)
        jg.pack(fill="x", pady=(4, 8), **P)
        self.jvars = {}
        groups = [("Torso", ["head", "neck", "waist", "hip"]),
                  ("Front", ["frontElbow", "frontHand", "frontKnee", "frontFoot"]),
                  ("Back", ["backElbow", "backHand", "backKnee", "backFoot"])]
        start = [app.forced] if app.forced in st.ok else [n for n in ORDER if n in st.ok]
        for col, (title, names) in enumerate(groups):
            hud.label(jg, title, fg=hud.DIM, font=hud.SMALL).grid(row=0, column=col, sticky="w", padx=(0, 18))
            for r, n in enumerate(names, 1):
                v = tk.BooleanVar(value=n in start)
                here = n in st.ok
                cb = ttk.Checkbutton(jg, text=n + ("" if here else "  (not placed here)"), variable=v,
                                     command=self.update_summary, state="normal" if here else "disabled")
                cb.grid(row=r, column=col, sticky="w", padx=(0, 18))
                self.jvars[n] = v

        # frames
        fh = tk.Frame(w, bg=hud.BG)
        fh.pack(fill="x", **P)
        hud.label(fh, "To Key Frames", font=hud.BOLD).pack(side="left")
        later = [g for g in app.frames if g > f]
        hud.Button(fh, "None", lambda: self.set_frames([]), padx=6, font=hud.SMALL).pack(side="right")
        hud.Button(fh, "All", lambda: self.set_frames([g for g in app.frames if g != f]), padx=6,
                   font=hud.SMALL).pack(side="right", padx=4)
        hud.Button(fh, "All After", lambda: self.set_frames(later), padx=6, font=hud.SMALL).pack(side="right")
        hud.Button(fh, "Next", lambda: self.set_frames(later[:1]), padx=6, font=hud.SMALL).pack(side="right",
                                                                                              padx=4)
        fg = tk.Frame(w, bg=hud.BG)
        fg.pack(fill="x", pady=(4, 8), **P)
        self.fvars = {}
        for k, g in enumerate([g for g in app.frames if g != f]):
            v = tk.BooleanVar(value=bool(later) and g == later[0])
            done = app.complete(g)
            ttk.Checkbutton(fg, text=f"{g}{' ✓' if done else ''}", variable=v, command=self.update_summary).grid(
                row=k // 8, column=k % 8, sticky="w", padx=(0, 10))
            self.fvars[g] = v

        # how
        self.as_traced = tk.BooleanVar(value=False)
        self.replace = tk.BooleanVar(value=False)
        hud.label(w, "AS", font=hud.BOLD, anchor="w").pack(fill="x", **P)
        for val, text in ((False, "Faded starting points: you check each one (Space / Enter / click), as now"),
                          (True, "Traced points: saved straight away (for joints that really don't move)")):
            ttk.Radiobutton(w, text=text, variable=self.as_traced, value=val, command=self.update_summary).pack(
                anchor="w", **P)
        hud.label(w, "Your Points on Those Frames", font=hud.BOLD, anchor="w").pack(fill="x", pady=(8, 0), **P)
        for val, text in ((False, "Keep them: only joints that are missing or faded there are set"),
                          (True, "Replace them too (a dated backup is made first, and Ctrl+Z undoes it)")):
            ttk.Radiobutton(w, text=text, variable=self.replace, value=val, command=self.update_summary).pack(
                anchor="w", **P)

        self.also = tk.BooleanVar(value=False)   # Phase 11: the other selected characters do the same
        others = sorted(app.selection() - {app.active}) if app.cast else []
        if others:
            ttk.Checkbutton(w, text="Also for the other selected characters (" + app.names(others) + "): each copies "
                                    "its own points of this frame to its own key frames", variable=self.also).pack(
                anchor="w", pady=(8, 0), **P)
        self.summary = hud.label(w, "", fg=hud.AMBER, font=hud.SMALL, anchor="w", justify="left", wraplength=560)
        self.summary.pack(fill="x", pady=(10, 0), **P)
        bar = tk.Frame(w, bg=hud.BG)
        bar.pack(fill="x", pady=12, **P)
        hud.Button(bar, "Cancel", w.destroy).pack(side="right", padx=(4, 0))
        self.go_btn = hud.Button(bar, "Carry", self.go, kind="red")
        self.go_btn.pack(side="right")
        w.bind("<Return>", lambda e: self.go())
        w.bind("<Escape>", lambda e: w.destroy())
        self.update_summary()
        w.grab_set()
        w.focus_set()

    def set_joints(self, names):
        for n, v in self.jvars.items():
            v.set(n in names and n in self.app.st().ok)
        self.update_summary()

    def set_frames(self, frames):
        for g, v in self.fvars.items():
            v.set(g in frames)
        self.update_summary()

    def choice(self):
        joints = [n for n, v in self.jvars.items() if v.get()]
        frames = [g for g, v in self.fvars.items() if v.get()]
        return joints, frames

    def update_summary(self):
        joints, frames = self.choice()
        if not joints or not frames:
            self.summary.configure(text="Pick at least one joint and one key frame.", fg=hud.DIM)
            self.go_btn.configure(state="disabled")
            return
        plan = carry_points(self.app.states, self.app.frame(), frames, joints, self.as_traced.get(),
                            self.replace.get(), dry=True)
        text = f"Will set {len(plan['set'])} point(s) on {len({g for g, _ in plan['set']})} frame(s)"
        if plan["kept"]:
            text += f";  {len(plan['kept'])} of your points stay as they are"
        if plan["replaced"]:
            text += f";  {len(plan['replaced'])} of your points will be replaced"
        self.summary.configure(text=text + ".", fg=hud.RED_HI if plan["replaced"] else hud.AMBER)
        self.go_btn.configure(state="normal" if plan["set"] else "disabled")

    def go(self):
        joints, frames = self.choice()
        if not joints or not frames:
            return
        plan = carry_points(self.app.states, self.app.frame(), frames, joints, self.as_traced.get(),
                            self.replace.get(), dry=True)
        if plan["replaced"]:
            lines = [f"frame {g}: {n}" for g, n in plan["replaced"][:10]]
            more = f"\n… and {len(plan['replaced']) - 10} more" if len(plan["replaced"]) > 10 else ""
            if not messagebox.askyesno("Replace your points?",
                                       f"These {len(plan['replaced'])} point(s) you placed will be replaced:\n\n"
                                       + "\n".join(lines) + more + "\n\nA dated backup is made first and Ctrl+Z "
                                       "undoes it. Replace them?", parent=self.win):
                return
        self.win.destroy()
        self.app.apply_carry(frames, joints, self.as_traced.get(), self.replace.get(),
                             also=sorted(self.app.selection() - {self.app.active}) if self.also.get() else ())


def open_session(d, nums, trace_dir=None):
    """Load (or start) the trace of frames folder d. nums = key frames to trace ([] = the saved ones).
    trace_dir: where the trace lives (Phase 11: a traced character's folder; default d).
    -> (frames, states, out_path, notes). Raises ValueError with a message when it can't start."""
    td = trace_dir or d
    out = find_trace(td) if os.path.isdir(td) else os.path.join(td, "trace.json")
    old_frames, old = [], {}
    notes = []
    if os.path.exists(out):
        shutil.copyfile(out, os.path.join(td, "trace_backup.json"))
        note = versioned_backup(td, "open")
        if note:
            notes.append(note)
        try:
            old_frames, old = load_trace(out)
        except (ValueError, KeyError, TypeError, IndexError) as e:
            notes.append(f"Couldn't read the old trace ({e}); it's kept as trace_backup.json.")
    frames = list(dict.fromkeys(nums)) or old_frames
    if not frames:
        raise ValueError("Pick the key frames to trace first.")
    missing = [f for f in frames if not os.path.exists(frame_path(d, f))]
    if missing:
        raise ValueError("These frames aren't in the folder: " +
                         ", ".join(os.path.basename(frame_path(d, f)) for f in missing))
    dropped = [f for f in old_frames if f not in frames]
    if dropped:
        notes.append(f"Frames {dropped} from the old trace are left out (they're still in trace_backup.json).")
    return frames, {f: old.get(f, FrameState()) for f in frames}, out, notes


def new_session(frames_dir, trace_dir, nums=()):
    """A traced character's working state for the editor (Phase 11): its saved trace, or an empty one."""
    try:
        frames, states, out, notes = open_session(frames_dir, list(nums), trace_dir=trace_dir)
    except ValueError:
        frames, states, out = [], {}, os.path.join(trace_dir, "trace.json")
    try:
        with open(out) as fh:
            disk = fh.read()
    except OSError:
        disk = None
    return {"frames": frames, "states": states, "out": out, "tdir": trace_dir, "disk_text": disk,
            "save_problem": None, "i": 0}


def make_root():
    try:   # sharp (not blurry) window on scaled Windows displays
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    try:
        root.state("zoomed")
    except tk.TclError:
        root.geometry("1400x850")
    return root


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    d = os.path.abspath(sys.argv[1])
    nums = []
    for a in sys.argv[2:]:
        nums += [int(x) for x in a.replace(",", " ").split()]
    nums = list(dict.fromkeys(nums))
    out = find_trace(d)
    old_frames, old = [], {}
    if os.path.exists(out):
        shutil.copyfile(out, os.path.join(d, "trace_backup.json"))
        note = versioned_backup(d, "open")
        if note:
            print(note)
        try:
            old_frames, old = load_trace(out)
        except (ValueError, KeyError, TypeError, IndexError) as e:
            print(f"Couldn't read {out} ({e}). Starting fresh; the old file is kept as trace_backup.json.")
    frames = nums or old_frames
    if not frames:
        print("Which frames? Add the key frame numbers after the folder, e.g.:")
        print(f'  python -I trace_clicker.py "{d}" 1 4 7')
        sys.exit(1)
    missing = [f for f in frames if not os.path.exists(frame_path(d, f))]
    if missing:
        print("These frames aren't in the folder:", ", ".join(os.path.basename(frame_path(d, f)) for f in missing))
        sys.exit(1)
    dropped = [f for f in old_frames if f not in frames]
    if dropped:
        print("Note: frames", dropped, "from the old trace.json are left out (they're still in trace_backup.json).")
    states = {f: old.get(f, FrameState()) for f in frames}
    print("Tracing frames", ", ".join(map(str, frames)), "->", out)
    root = make_root()
    app = App(root, d, frames, states, out)
    if app.history_note:
        app.msg(app.history_note)
    root.mainloop()


if __name__ == "__main__":
    main()

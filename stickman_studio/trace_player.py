"""Play a trace as an animation: the key frames in trace.json drawn as the game's stickman
(solid black, round head on the shoulders, thick rounded limbs, small feet), moving smoothly between
the keys (monotone cubic, knees relative to the hip->foot line, like the baked clips) or key poses only.

usage: python -I trace_player.py <frames folder | trace.json>
Also opened from Trace Clicker (P key or the Play button), or by dropping a traced folder or trace.json
in Stickman Studio (screen 03 PLAY / FIX). A trace that is still being edited is re-read live.

Keys:  Space = play / pause     Left / Right = one frame     Shift+Left / Right = previous / next key
       Home / End     [ / ] = slower / faster     S = smooth on / off     R = reference frames on / off
       L = loop on / off     B = back limbs grey     G = ground line     Esc = close
       T = motion trails of the hands, feet and head (10 frames back solid, 10 ahead dashed, one dot per frame)
       K = Key Poses: frames suggested by coordinate rules (accept / reject), mark your own; amber on the timeline
       C = Compare two frames, or a frame in two versions (trace / fixed / backup): side by side, numbers, summary
       A = Analytics: displacement, speed, acceleration, angles, timing (px / bones / metres / game units), CSV
Frame rate: from timing.json in the folder, else from the GIF the frames came from, else 12 fps.
"""
import json
import math
import os
import statistics
import sys
import time
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

ORDER = ["head", "neck", "waist", "hip", "backKnee", "backFoot", "frontKnee", "frontFoot",
         "frontElbow", "frontHand", "backElbow", "backHand"]
SPEEDS = [0.1, 0.25, 0.5, 1.0, 1.5, 2.0]
TRAIL_SPAN = 10           # frames of trail behind and ahead of the stickman (T)
RATES = [5, 6, 8, 10, 12, 15, 20, 24, 25, 30, 50, 60]
SS = 3                    # supersampling for smooth (anti-aliased) edges
PAPER = (247, 247, 247)
INK = (0, 0, 0)
BACK_INK = (115, 115, 115)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # for hud (python -I leaves it out)
import hud  # noqa: E402
import trace_io  # noqa: E402
import trails  # noqa: E402  (motion trails, upgrade Phase 5)
import keyposes  # noqa: E402  (key poses, upgrade Phase 6)

BAR = hud.BG
FONT = hud.FONT


# ---------------------------------------------------------------- trace + timing
def trace_path(target):
    if os.path.isdir(target):
        for n in os.listdir(target):
            if n.lower() == "trace.json":
                return os.path.join(target, n)
        return os.path.join(target, "trace.json")
    return target


def read_trace(path):
    """-> (keys, unfinished): keys = sorted [(frame, {joint: (x, y)})] with all 12 points."""
    with open(path) as fh:
        J = json.load(fh)
    keys, unfinished = [], []
    for f, P in zip(J["frames"], J["pts"]):
        if all(n in P for n in ORDER):   # the 12 make a frame finished; optional joints come along when placed
            keys.append((int(f), {n: (float(P[n][0]), float(P[n][1])) for n in trace_io.ALL if n in P}))
        else:
            unfinished.append(int(f))
    return sorted(keys), sorted(unfinished)


def gif_fps(path):
    try:
        with Image.open(path) as im:
            total, n = 0, 0
            while True:
                total += im.info.get("duration") or 100
                n += 1
                im.seek(im.tell() + 1)
    except EOFError:
        return 1000 * n / max(1, total)
    except OSError:
        return None


def find_fps(folder):
    """-> (fps, where it came from)."""
    tj = os.path.join(folder, "timing.json")
    if os.path.exists(tj):
        try:
            with open(tj) as fh:
                fps = float(json.load(fh)["fps"])
            if fps > 0:
                return fps, "timing.json"
        except (OSError, ValueError, KeyError, TypeError):
            pass
    name = os.path.basename(os.path.normpath(folder))
    parent = os.path.dirname(os.path.normpath(folder))
    for gif in (os.path.join(parent, name + ".gif"), os.path.join(os.path.dirname(parent), name + ".gif")):
        if os.path.exists(gif):
            fps = gif_fps(gif)
            if fps:
                return fps, os.path.basename(gif)
    return 12.0, "a guess"


# ---------------------------------------------------------------- motion
def pchip_slopes(xs, ys):
    """Monotone cubic (Fritsch-Carlson) slopes: smooth through the keys, never overshooting them."""
    n = len(xs)
    if n < 2:
        return [0.0] * n
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    if n == 2:
        return [d[0], d[0]]
    m = [0.0] * n
    for i in range(1, n - 1):
        if d[i - 1] * d[i] > 0:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])

    def end(h0, h1, d0, d1):
        s = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
        if s * d0 <= 0:
            return 0.0
        if d0 * d1 < 0 and abs(s) > 3 * abs(d0):
            return 3 * d0
        return s

    m[0] = end(h[0], h[1], d[0], d[1])
    m[-1] = end(h[-1], h[-2], d[-1], d[-2])
    return m


def hermite(x0, x1, y0, y1, m0, m1, x):
    h = x1 - x0
    t = (x - x0) / h
    t2, t3 = t * t, t * t * t
    return ((2 * t3 - 3 * t2 + 1) * y0 + (t3 - 2 * t2 + t) * h * m0
            + (-2 * t3 + 3 * t2) * y1 + (t3 - t2) * h * m1)


KNEES = {"backKnee": "backFoot", "frontKnee": "frontFoot"}


class Motion:
    def __init__(self, keys):
        self.keys = keys
        self.times = [float(f) for f, _ in keys]
        self.chan = {}
        for name in ORDER:
            for axis in (0, 1):
                if name in KNEES:
                    vals = [knee_param(P, name)[axis] for _, P in keys]
                else:
                    vals = [P[name][axis] for _, P in keys]
                self.chan[(name, axis)] = (vals, pchip_slopes(self.times, vals))
        self.extra = {}   # v3.0 optional joints: angle and length relative to their bone, over the keys that have them
        for name in trace_io.EXTRAS:
            ks = [(float(f), extra_param(P, name)) for f, P in keys if name in P]
            if ks:
                ts = [t for t, _ in ks]
                angs = unwrap([a for _, (a, _) in ks])
                lens = [r for _, (_, r) in ks]
                self.extra[name] = (ts, angs, pchip_slopes(ts, angs), lens, pchip_slopes(ts, lens))

    def extras_at(self, P, t):
        """Add the optional joints to an in-between pose P (each follows its bone; between the keys that have it)."""
        for name, (ts, angs, ma, lens, ml) in self.extra.items():
            if len(ts) == 1 or t <= ts[0]:
                a, r = angs[0], lens[0]
            elif t >= ts[-1]:
                a, r = angs[-1], lens[-1]
            else:
                i = max(k for k in range(len(ts) - 1) if ts[k] <= t)
                a = hermite(ts[i], ts[i + 1], angs[i], angs[i + 1], ma[i], ma[i + 1], t)
                r = hermite(ts[i], ts[i + 1], lens[i], lens[i + 1], ml[i], ml[i + 1], t)
            P[name] = extra_from(P, name, a, r)
        return P

    def key_at(self, t):
        """Index of the last key at or before t."""
        i = 0
        for k, kt in enumerate(self.times):
            if kt <= t + 1e-9:
                i = k
        return i

    def pose(self, t, smooth=True):
        if len(self.keys) == 1 or not smooth:
            return dict(self.keys[self.key_at(t)][1])
        t = min(max(t, self.times[0]), self.times[-1])
        i = min(self.key_at(t), len(self.times) - 2)
        x0, x1 = self.times[i], self.times[i + 1]
        val = {}
        for (name, axis), (vals, m) in self.chan.items():
            val[(name, axis)] = hermite(x0, x1, vals[i], vals[i + 1], m[i], m[i + 1], t)
        P = {n: (val[(n, 0)], val[(n, 1)]) for n in ORDER if n not in KNEES}
        for knee, foot in KNEES.items():
            P[knee] = knee_from(P["hip"], P[foot], val[(knee, 0)], val[(knee, 1)])
        return self.extras_at(P, t)


def extra_param(P, name):
    """An optional joint as (angle in degrees from its reference bone, length in that bone's lengths)."""
    a, b = trace_io.EXTRA_REF[name]
    p = P[trace_io.EXTRA_PARENT[name]]
    rx, ry = P[b][0] - P[a][0], P[b][1] - P[a][1]
    ex, ey = P[name][0] - p[0], P[name][1] - p[1]
    ref = math.hypot(rx, ry) or 1.0
    ang = math.degrees(math.atan2(ey, ex) - math.atan2(ry, rx))
    return (ang + 180.0) % 360.0 - 180.0, math.hypot(ex, ey) / ref


def extra_from(P, name, ang, ratio):
    a, b = trace_io.EXTRA_REF[name]
    p = P[trace_io.EXTRA_PARENT[name]]
    rx, ry = P[b][0] - P[a][0], P[b][1] - P[a][1]
    L = math.hypot(rx, ry) * ratio
    th = math.atan2(ry, rx) + math.radians(ang)
    return p[0] + L * math.cos(th), p[1] + L * math.sin(th)


def unwrap(vals):
    out = [vals[0]] if vals else []
    for v in vals[1:]:
        out.append(out[-1] + ((v - out[-1] + 180.0) % 360.0 - 180.0))
    return out


def knee_param(P, knee):
    """Knee as (how far along hip->foot, how far off to the side), both in hip->foot lengths."""
    hx, hy = P["hip"]
    lx, ly = P[KNEES[knee]][0] - hx, P[KNEES[knee]][1] - hy
    kx, ky = P[knee][0] - hx, P[knee][1] - hy
    L2 = lx * lx + ly * ly
    if L2 < 1e-6:
        return 0.5, 0.0
    return (kx * lx + ky * ly) / L2, (lx * ky - ly * kx) / L2


def knee_from(hip, foot, u, v):
    lx, ly = foot[0] - hip[0], foot[1] - hip[1]
    return hip[0] + u * lx - v * ly, hip[1] + u * ly + v * lx


# ---------------------------------------------------------------- the stickman's look
class Look:
    """Sizes taken from the reference stickman, scaled to the traced body."""

    def __init__(self, keys):
        def med(f):
            return statistics.median(f(P) for _, P in keys)

        def d(P, a, b):
            return math.dist(P[a], P[b])

        hn = med(lambda P: d(P, "head", "neck"))
        torso = med(lambda P: d(P, "neck", "waist") + d(P, "waist", "hip"))
        leg = med(lambda P: (d(P, "hip", "backKnee") + d(P, "backKnee", "backFoot")
                             + d(P, "hip", "frontKnee") + d(P, "frontKnee", "frontFoot")) / 2)
        body = max(1.0, torso + leg)
        self.r = min(max(0.85 * hn, 0.11 * body), 0.2 * body)        # head sits on the shoulders
        self.height = body + hn + self.r
        self.torso_w = 0.1 * self.height
        self.leg_w = 0.08 * self.height
        self.arm_w = 0.072 * self.height
        self.foot_len = 0.075 * self.height
        lean = sum(P["frontFoot"][0] + P["frontHand"][0] + P["frontKnee"][0] + P["frontElbow"][0]
                   - P["backFoot"][0] - P["backHand"][0] - P["backKnee"][0] - P["backElbow"][0] for _, P in keys)
        self.facing = -1 if lean < 0 else 1
        self.ground = max(max(P["backFoot"][1], P["frontFoot"][1]) for _, P in keys) + self.leg_w / 2
        xs = [P[n][0] for _, P in keys for n in ORDER]
        ys = [P[n][1] for _, P in keys for n in ORDER]
        pad = self.r + self.foot_len + self.leg_w
        self.box = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def stroke(draw, pts, w):
    """A thick line with round joints and round ends."""
    draw.line(pts, fill=255, width=max(1, round(w)), joint="curve")
    r = w / 2
    for x, y in pts:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=255)


def foot_tip(knee, foot, look):
    sx, sy = foot[0] - knee[0], foot[1] - knee[1]
    n = math.hypot(sx, sy) or 1.0
    px, py = look.facing * sy / n, -look.facing * sx / n   # across the shin, toward the way he faces
    return foot[0] + px * look.foot_len, foot[1] + py * look.foot_len


def draw_stickman(P, look, to_screen, back_draw, front_draw, k):
    """Draw pose P into two masks (back limbs / everything else). k = screen pixels per trace pixel."""
    S = {n: to_screen(*P[n]) for n in trace_io.ALL if n in P}
    for side, dr in (("back", back_draw), ("front", front_draw)):
        knee, foot = P[side + "Knee"], P[side + "Foot"]
        # v3.0: a placed toe points the foot; without one the foot points forward from the shin, as before
        tip = S[side + "Toe"] if side + "Toe" in S else to_screen(*foot_tip(knee, foot, look))
        stroke(dr, [S["hip"], S[side + "Knee"], S[side + "Foot"], tip], look.leg_w * k)
        arm = [S["neck"]] + [S[n] for n in (side + "Shoulder",) if n in S] + [S[side + "Elbow"], S[side + "Hand"]] \
            + [S[n] for n in (side + "HandTip",) if n in S]
        stroke(dr, arm, look.arm_w * k)
        if side == "back":   # torso and head go over the back limbs
            stroke(front_draw, [S["hip"], S["waist"], S["neck"], S["head"]], look.torso_w * k)
            hx, hy = S["head"]
            r = look.r * k
            front_draw.ellipse((hx - r, hy - r, hx + r, hy + r), fill=255)


# ---------------------------------------------------------------- fixing a trace (angle, size, travel)
FIX_DEFAULT = {"angle": False, "turn": 0.0, "tilt": 0.0, "zoom": False, "resize": False, "height": 200.0,
               "inplace": False, "ground": True}
BONE_TYPES = {
    "thigh": [("hip", "backKnee"), ("hip", "frontKnee")], "shin": [("backKnee", "backFoot"), ("frontKnee", "frontFoot")],
    "upper arm": [("neck", "frontElbow"), ("neck", "backElbow")],
    "forearm": [("frontElbow", "frontHand"), ("backElbow", "backHand")],
    "lower torso": [("hip", "waist")], "upper torso": [("waist", "neck")], "head": [("neck", "head")],
}


def body_length(P):
    d = math.dist
    return (d(P["head"], P["neck"]) + d(P["neck"], P["waist"]) + d(P["waist"], P["hip"])
            + (d(P["hip"], P["backKnee"]) + d(P["backKnee"], P["backFoot"])
               + d(P["hip"], P["frontKnee"]) + d(P["frontKnee"], P["frontFoot"])) / 2)


def torso_length(P):
    d = math.dist
    return d(P["head"], P["neck"]) + d(P["neck"], P["waist"]) + d(P["waist"], P["hip"])


def length_spread(keys):
    """How much each bone's length changes between frames (0.1 = +-10%), averaged over the bones.
    A camera at an angle makes limbs shorter in some frames than others; the right angle brings it down."""
    if len(keys) < 2:
        return 0.0
    out = []
    for pairs in BONE_TYPES.values():
        vals = [math.dist(P[a], P[b]) for _, P in keys for a, b in pairs]
        m = sum(vals) / len(vals)
        if m > 1e-6:
            out.append(math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals)) / m)
    return sum(out) / len(out) if out else 0.0


def unturn(keys, turn, tilt):
    """Undo the camera angle. The stickman moves in one flat plane facing sideways (a 2D fighter), so a camera
    turned by `turn` degrees and tilted by `tilt` degrees sees that plane through a simple squash and slant:
    u = X cos(turn), v = Y cos(tilt) + X sin(turn) sin(tilt). This solves it back for X and Y."""
    th, ph = math.radians(turn), math.radians(tilt)
    c, sp, cp = math.cos(th), math.sin(th) * math.sin(ph), math.cos(ph)
    ox, oy = keys[0][1]["hip"]
    out = []
    for f, P in keys:
        Q = {}
        for n, (x, y) in P.items():
            X = (x - ox) / c
            Q[n] = (ox + X, oy + ((y - oy) - sp * X) / cp)
        out.append((f, Q))
    return out


def even_zoom(keys):
    """Same body size in every frame (a camera zooming in and out), measured on the head + torso."""
    if len(keys) < 2:
        return keys
    tl = [torso_length(P) for _, P in keys]
    m = statistics.median(tl)
    out = []
    for (f, P), t in zip(keys, tl):
        k = m / t if t > 1e-6 else 1.0
        hx, hy = P["hip"]
        out.append((f, {n: (hx + (x - hx) * k, hy + (y - hy) * k) for n, (x, y) in P.items()}))
    return out


def apply_fix(keys, fix):
    """-> (fixed keys, info). Order: camera angle, even out zoom, resize, in place."""
    info = {}
    if not keys:
        return keys, info
    out = [(f, dict(P)) for f, P in keys]
    info["spread_before"] = length_spread(even_zoom(out) if fix.get("zoom") else out)
    if fix.get("angle") and (fix.get("turn") or fix.get("tilt")):
        out = unturn(out, fix.get("turn", 0.0), fix.get("tilt", 0.0))
    if fix.get("zoom"):
        out = even_zoom(out)
    info["spread_after"] = length_spread(out)
    info["height_before"] = statistics.median(body_length(P) for _, P in out)
    if fix.get("resize") and info["height_before"] > 1e-6:
        k = float(fix.get("height", 200.0)) / info["height_before"]
        ox, oy = out[0][1]["hip"]
        out = [(f, {n: (ox + (x - ox) * k, oy + (y - oy) * k) for n, (x, y) in P.items()}) for f, P in out]
    info["height_after"] = statistics.median(body_length(P) for _, P in out)
    if len(out) > 1:   # the steady travel (measured always; taken away for "in place")
        ts = [float(f) for f, _ in out]
        xs = [P["hip"][0] for _, P in out]
        mt, mx = sum(ts) / len(ts), sum(xs) / len(xs)
        den = sum((t - mt) ** 2 for t in ts)
        slope = sum((t - mt) * (x - mx) for t, x in zip(ts, xs)) / den if den else 0.0
        info["travel"] = slope * (ts[-1] - ts[0])
        info["travel_per_frame"] = slope
        if fix.get("inplace"):   # the body's own sway stays
            out = [(f, {n: (x - slope * (f - ts[0]), y) for n, (x, y) in P.items()}) for f, P in out]
    if fix.get("ground", True):
        g0, slope, reach = ground_line(out)
        t0 = float(out[0][0])
        info["ground"], info["ground_reach"], info["ground_slope"] = g0, reach, slope
        moved = 0.0
        snapped = []
        for f, P in out:
            lift = slope * (f - t0)      # level the floor (a camera that drifts up or down)
            P = {n: (x, y - lift) for n, (x, y) in P.items()}
            Q, d = on_ground(P, g0, reach)
            snapped.append((f, Q))
            moved = max(moved, abs(d - lift))
        out = snapped
        info["ground_moved"] = moved
    return out, info


def lowest_foot(P):
    return max(P["backFoot"][1], P["frontFoot"][1])   # image y points down: bigger = lower


def ground_line(keys):
    """-> (ground y at the first key, slope per frame, reach). The ground is the lowest straight line every frame
    stands on or above (it runs through the frames where the feet are lowest, e.g. a jump's take-off and landing),
    so mid-air frames never pull it up; a slope means the camera drifted and gets levelled. Of the possible lines,
    the one most frames stand near wins. reach = how high above it a foot still counts as standing."""
    legs = statistics.median((math.dist(P["hip"], P["backKnee"]) + math.dist(P["backKnee"], P["backFoot"])
                              + math.dist(P["hip"], P["frontKnee"]) + math.dist(P["frontKnee"], P["frontFoot"])) / 2
                             for _, P in keys)
    reach = 0.2 * legs
    pts = [(float(f), lowest_foot(P)) for f, P in keys]
    t0 = pts[0][0]
    if len(pts) == 1:
        return pts[0][1], 0.0, reach
    best = None
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            (ta, ya), (tb, yb) = pts[i], pts[j]
            if tb - ta < 1e-9:
                continue
            slope = (yb - ya) / (tb - ta)
            line = [ya + slope * (t - ta) for t, _ in pts]
            if any(y > ly + 1e-6 for (_, y), ly in zip(pts, line)):   # a foot would be below this line
                continue
            support = sum(1 for (_, y), ly in zip(pts, line) if ly - y <= reach)
            score = (support, tb - ta, -abs(slope))
            if best is None or score > best[0]:
                best = (score, ya + slope * (t0 - ta), slope)
    if best is None:   # can't happen with real numbers, but stay safe: flat at the lowest foot
        return max(y for _, y in pts), 0.0, reach
    return best[1], best[2], reach


def on_ground(P, g, reach):
    """Put a standing pose's lowest foot on the ground, and lift any foot that sinks below it. A pose clearly in the
    air (more than 2 x reach up) is left alone; in between it eases over, so a jump takes off without a pop.
    -> (pose, how far it moved down)."""
    gap = g - lowest_foot(P)          # > 0: floating above the ground; < 0: sinking into it
    if gap <= reach:
        d = gap
    elif gap < 2 * reach:
        d = 2 * reach - gap
    else:
        d = 0.0
    if abs(d) < 1e-9:
        return P, 0.0
    return {n: (x, y + d) for n, (x, y) in P.items()}, d


def auto_angle(keys, zoom=False):
    """The camera turn and tilt that make the bone lengths steadiest from frame to frame
    (with zoom=True the camera's zooming is taken out first, so it doesn't count as length changes)."""
    def score(ks):
        return length_spread(even_zoom(ks) if zoom else ks)

    best = (score(keys), 0.0, 0.0)
    for turn in range(-78, 79, 2):
        for tilt in range(-45, 46, 3):
            s = score(unturn(keys, turn, tilt))
            if s < best[0] - 1e-9:
                best = (s, float(turn), float(tilt))
    return best[1], best[2]


def fix_summary(fix, info, fps=None):
    parts = []
    if fix.get("angle") and (fix.get("turn") or fix.get("tilt")):
        parts.append(f"camera turned {fix['turn']:g}°" + (f", tilted {fix['tilt']:g}°" if fix.get("tilt") else ""))
    if fix.get("zoom"):
        parts.append("zoom evened out")
    if fix.get("resize"):
        parts.append(f"resized to {fix['height']:g} px tall (was {info.get('height_before', 0):.0f})")
    t = info.get("travel", 0.0)
    per_s = f", {abs(info.get('travel_per_frame', 0.0)) * fps:.0f} px/s" if fps else ""
    if fix.get("inplace"):
        parts.append(f"in place (removed {abs(t):.0f} px of travel{per_s})")
    elif abs(t) >= 1:
        parts.append(f"moving ({abs(t):.0f} px of travel{per_s})")
    if fix.get("ground", True) and info.get("ground_moved", 0) >= 0.5:
        parts.append("feet kept on the ground")
    return ", ".join(parts)


def fixed_path(folder):
    return os.path.join(folder, "trace_fixed.json")


def load_fix(folder):
    p = fixed_path(folder)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as fh:
                saved = json.load(fh).get("fix")
            if isinstance(saved, dict):
                return {**FIX_DEFAULT, **saved}
        except (OSError, ValueError):
            pass
    return None


def ask_choice(win, title, text, buttons, default=0):
    """A small window with a message and buttons. -> the index of the button clicked, or None."""
    d = tk.Toplevel(win)
    d.title(title)
    d.configure(bg=BAR, padx=18, pady=14)
    d.transient(win)
    d.resizable(False, False)
    result = {"i": None}
    tk.Label(d, text=text, bg=BAR, font=FONT, justify="left", wraplength=420).pack(anchor="w")
    row = tk.Frame(d, bg=BAR)
    row.pack(anchor="e", pady=(12, 0))

    def pick(i):
        result["i"] = i
        d.destroy()

    for i, b in enumerate(buttons):
        w = ttk.Button(row, text=b, command=lambda i=i: pick(i))
        w.pack(side="left", padx=3)
        if i == default:
            w.focus_set()
            d.bind("<Return>", lambda e, i=i: pick(i))
    d.bind("<Escape>", lambda e: d.destroy())
    d.grab_set()
    d.wait_window()
    return result["i"]


# ---------------------------------------------------------------- the player window
class Player:
    """The stickman player. win is a Tk / Toplevel window (it becomes the player window) or, with
    embedded=True, a frame inside Stickman Studio; then its keys are collected in self.keymap for the studio."""

    def __init__(self, win, folder, get_keys, title="trace", embedded=False, trace_dir=None, cast=None,
                 on_character=None):
        self.win, self.dir, self.get_keys = win, folder, get_keys
        # Phase 11: cast = {"active": id, "ids": [(id, name)], "others": [{"id", "name", "colour", "tdir", "trace"}]}
        # for a multi-character move (the other VISIBLE characters, drawn together with this one)
        self.cast, self.on_character = cast, on_character
        self.others = [dict(o, get=file_keys(o["trace"]), sig=None, raw=[], motion=None, look=None, fmotion=None,
                            flook=None, fground=None, fix_changes=False) for o in (cast or {}).get("others", [])]
        self.v_others = tk.BooleanVar(value=True)
        self.v_colours = tk.BooleanVar(value=False)
        self.v_hold = tk.BooleanVar(value=False)
        self.v_fixedpos = tk.BooleanVar(value=False)
        # Phase 11: the trace's own folder (a traced character's): its fixed trace and key poses live there;
        # the frames and the frame rate belong to the move (self.dir)
        self.tdir = trace_dir or folder
        self.embedded = embedded
        self.alive = True
        self.sig = None
        self.motion = self.look = None
        self.keys, self.unfinished = [], []
        self.t = 0.0
        self.playing = False
        self.speed = 1.0
        self.fps, self.fps_from = find_fps(folder)
        self.tick_id = self.poll_id = None
        self.photo = None
        self.ref_cache = {}
        self.hold_until = None
        saved = load_fix(self.tdir)
        self.fix = dict(saved or FIX_DEFAULT)
        self.saved_fix = dict(saved) if saved else None
        self.raw_keys = []
        self.kp_data = keyposes.load(self.tdir)   # key poses (Phase 6): yours, rejected suggestions, thresholds
        self.kp_suggest = []
        self.kp_dialog = None
        self.cmp_dialog = None       # Compare window (Phase 7)
        self.an_dialog = None        # Analytics window (Phase 8)
        self.ghost_motion = self.ghost_look = None
        self.fix_info = {}
        self.building = True
        P = hud.PANEL

        if not embedded:
            hud.setup(win)
            win.title(f"Play - {title}")
            win.geometry("1240x880")
            win.minsize(980, 640)
        win.configure(bg=hud.BG)

        bottom = tk.Frame(win, bg=hud.BG)
        bottom.pack(side="bottom", fill="x", padx=12, pady=(0, 8))
        import ribbon   # v3.3: playback, analysis and display options in a ribbon; the side keeps the corrections
        rb = self.ribbon = ribbon.Ribbon(win, [("Save Fixed Trace", self.save_fixed)])
        rb.pack(side="top", fill="x", padx=12, pady=(8, 0))
        main = tk.Frame(win, bg=hud.BG)
        main.pack(fill="both", expand=True, padx=12, pady=(10, 0))
        side = tk.Frame(main, bg=P, width=318, highlightthickness=1, highlightbackground=hud.LINE)
        side.pack(side="right", fill="y", padx=(12, 0))
        side.pack_propagate(False)
        screen = hud.panel(main, bg=hud.PAPER, border=hud.LINE2)
        screen.pack(side="left", fill="both", expand=True)
        self.stage = tk.Canvas(screen, bg=hud.PAPER, highlightthickness=0)
        self.stage.pack(fill="both", expand=True)
        self.stage.bind("<Configure>", lambda e: self.render())
        self.stage.bind("<MouseWheel>", lambda e: self.step(-1 if e.delta > 0 else 1))

        # ---- side column: name, gauges, view options, fix panel
        if cast and cast.get("ids") and on_character:   # Phase 11: the move's name + which character, on one row
            tr = tk.Frame(side, bg=P)
            tr.pack(fill="x", padx=12, pady=(12, 0))
            hud.tag(tr, os.path.basename(os.path.normpath(folder)), bg=P).pack(side="left")
            names = [n for _, n in cast["ids"]]
            self.char_var = tk.StringVar(value=dict(cast["ids"]).get(cast.get("active"), names[0]))
            cbx = ttk.Combobox(tr, textvariable=self.char_var, values=names, state="readonly", width=16)
            cbx.pack(side="right")
            cbx.bind("<<ComboboxSelected>>", self.pick_character)
        else:
            hud.tag(side, title, bg=P).pack(anchor="w", padx=12, pady=(12, 0))
        gauges = tk.Frame(side, bg=P)
        gauges.pack(pady=(8, 0))
        self.g_time = hud.Gauge(gauges, size=100, label="seconds", bg=P)
        self.g_time.pack(side="left")
        self.g_key = hud.Gauge(gauges, size=100, label="key", bg=P)
        self.g_key.pack(side="left", padx=(12, 0))

        self.smooth = tk.BooleanVar(value=True)
        self.loop = tk.BooleanVar(value=True)
        self.ref = tk.BooleanVar(value=False)
        self.grey = tk.BooleanVar(value=False)
        self.ground = tk.BooleanVar(value=True)
        self.trail = tk.BooleanVar(value=False)
        g = rb.tab("Home").group("Analyse")
        g.button("Key Poses…", self.open_key_poses, "Find, accept or mark the key poses (K)")
        g.button("Compare…", self.open_compare, "Compare two frames, the fixed trace or a backup (C)")
        g.button("Analytics…", self.open_analytics, "Speeds, angles and timing, with a CSV export (A)")
        g = rb.tab("View").group("Display")
        for text, var, tip in (("Smooth", self.smooth, "Smooth in-betweens (S)"), ("Loop", self.loop, "Loop (L)"),
                               ("Reference", self.ref, "Show the reference frames (R)"),
                               ("Grey Back Limbs", self.grey, "Draw the back arm and leg grey (B)")):
            g.check(text, var, self.render, tip)
        g.row()
        for text, var, tip in (("Ground Line", self.ground, "Show the ground (G)"),
                               ("Trails", self.trail, "Paths of the hands, feet and head (T)")):
            g.check(text, var, self.render, tip)
        if self.cast is not None:   # Phase 11: the other characters
            g = rb.tab("View").group("Other characters")
            for k, (text, var) in enumerate((("Show Others", self.v_others), ("Their Colours", self.v_colours),
                                             ("Hold Outside", self.v_hold), ("Fixed Positions", self.v_fixedpos))):
                if k == 2:
                    g.row()
                g.check(text, var, self.others_changed)

        hud.Header(side, "Correct the trace", "Preview the corrections here, then save.", bg=P).pack(
            fill="x", padx=12, pady=(12, 2))
        fx = tk.Frame(side, bg=P)
        fx.pack(fill="x", padx=12)
        self.v_angle = tk.BooleanVar(value=self.fix["angle"])
        ar = tk.Frame(fx, bg=P)
        ar.pack(fill="x")
        ttk.Checkbutton(ar, text="Camera angle", variable=self.v_angle, takefocus=False, style="Panel.TCheckbutton",
                        command=self.fix_changed).pack(side="left")
        hud.Button(ar, "Auto", self.auto, padx=10, pady=1).pack(side="right")
        for name, lo, hi in (("Turn", -80, 80), ("Tilt", -60, 60)):
            row = tk.Frame(fx, bg=P)
            row.pack(fill="x")
            hud.label(row, name, bg=P, fg=hud.DIM, font=hud.TINY, width=5, anchor="w").pack(side="left")
            val = hud.label(row, "0°", bg=P, font=(hud.MONO, 9), width=5, anchor="e")
            val.pack(side="right")
            sc = hud.style_scale(tk.Scale(row, from_=lo, to=hi, orient="horizontal", resolution=1, takefocus=0,
                                          command=lambda v, val=val: (val.configure(text=f"{float(v):g}°"),
                                                                      self.slider_moved())), bg=P)
            sc.pack(side="left", fill="x", expand=True, pady=4)
            setattr(self, "turn_scale" if name == "Turn" else "tilt_scale", sc)
        self.spread_lbl = hud.label(fx, "", bg=P, fg=hud.DIM, font=hud.TINY, anchor="w", justify="left",
                                    wraplength=290)
        self.spread_lbl.pack(fill="x")
        self.v_zoom = tk.BooleanVar(value=self.fix["zoom"])
        self.v_resize = tk.BooleanVar(value=self.fix["resize"])
        self.v_inplace = tk.BooleanVar(value=self.fix["inplace"])
        self.v_ghost = tk.BooleanVar(value=True)
        self.v_ground = tk.BooleanVar(value=self.fix.get("ground", True))
        ttk.Checkbutton(fx, text="Even out camera zoom", variable=self.v_zoom, takefocus=False,
                        style="Panel.TCheckbutton", command=self.fix_changed).pack(anchor="w", pady=(4, 0))
        rr = tk.Frame(fx, bg=P)
        rr.pack(fill="x")
        ttk.Checkbutton(rr, text="Resize to", variable=self.v_resize, takefocus=False, style="Panel.TCheckbutton",
                        command=self.fix_changed).pack(side="left")
        self.height_var = tk.StringVar(value=f"{self.fix['height']:g}")
        ttk.Entry(rr, textvariable=self.height_var, width=6).pack(side="left", padx=4)
        self.height_var.trace_add("write", lambda *_: self.fix_changed())
        hud.label(rr, "px tall", bg=P, fg=hud.DIM, font=hud.SMALL).pack(side="left")
        for text, var, cmd in (("In place (no travel)", self.v_inplace, self.fix_changed),
                               ("Feet on the ground", self.v_ground, self.fix_changed),
                               ("Show the original (grey)", self.v_ghost, self.render)):
            ttk.Checkbutton(fx, text=text, variable=var, takefocus=False, style="Panel.TCheckbutton",
                            command=cmd).pack(anchor="w")
        self.fix_box = fx
        self.save_btn = hud.Button(side, "Save Fixed Trace", self.save_fixed, kind="red")
        self.save_btn.pack(fill="x", padx=12, pady=(10, 4))
        self.fix_lbl = hud.label(side, "", bg=P, fg=hud.GREEN, font=hud.SMALL, anchor="nw", justify="left",
                                 wraplength=292)
        self.fix_lbl.pack(fill="x", padx=12)
        self.turn_scale.set(self.fix["turn"])
        self.tilt_scale.set(self.fix["tilt"])

        # ---- bottom: timeline, transport, info
        self.line = tk.Canvas(bottom, height=54, bg=hud.BG, highlightthickness=0, cursor="hand2")
        self.line.pack(fill="x", pady=(8, 0))
        self.line.bind("<Configure>", lambda e: self.draw_line())
        self.line.bind("<Button-1>", self.on_line)
        self.line.bind("<B1-Motion>", self.on_line)
        bar = tk.Frame(bottom, bg=hud.BG)
        bar.pack(fill="x", pady=(2, 0))
        for text, cmd in (("⏮", lambda: self.seek(self.start())), ("◀", lambda: self.step(-1))):
            hud.Button(bar, text, cmd, padx=10).pack(side="left", padx=(0, 4))
        self.play_btn = hud.Button(bar, "▶  Play", self.toggle, kind="red", padx=16)
        self.play_btn.pack(side="left", padx=(0, 4))
        for text, cmd in (("▶", lambda: self.step(1)), ("⏭", lambda: self.seek(self.end()))):
            hud.Button(bar, text, cmd, padx=10).pack(side="left", padx=(0, 4))
        g = rb.tab("Home").group("Playback")
        g.label("Speed")
        bar_ = bar
        bar = g.cur()
        self.speed_box = ttk.Combobox(bar, width=6, state="readonly", values=[f"{s:g}×" for s in SPEEDS],
                                      takefocus=False)
        self.speed_box.set("1×")
        self.speed_box.bind("<<ComboboxSelected>>", lambda e: (self.set_speed(SPEEDS[self.speed_box.current()]),
                                                               self.win.focus_set()))
        self.speed_box.pack(side="left", padx=(0, 10))
        g.label("Frame rate")
        rates = sorted(set(RATES) | {round(self.fps, 2)})
        self.rate_values = rates
        self.rate_box = ttk.Combobox(bar, width=9, state="readonly", values=[f"{r:g} fps" for r in rates],
                                     takefocus=False)
        self.rate_box.set(f"{round(self.fps, 2):g} fps")
        self.rate_box.bind("<<ComboboxSelected>>", self.on_rate)
        self.rate_box.pack(side="left", padx=(0, 4))
        bar = bar_
        g = rb.tab("Home").group("Save")
        g.button("Save Fixed Trace", self.save_fixed, "Save the corrected trace (your trace is never changed)",
                 kind="red")
        self.info = hud.label(bar, "", font=(hud.MONO, 10))
        self.info.pack(side="right")
        self.note = hud.label(bottom, "", fg=hud.AMBER, font=hud.SMALL, anchor="w")
        self.note.pack(fill="x")

        keys = {"<space>": self.toggle, "<Right>": lambda: self.step(1), "<Left>": lambda: self.step(-1),
                "<Shift-Right>": lambda: self.jump_key(1), "<Shift-Left>": lambda: self.jump_key(-1),
                "<Home>": lambda: self.seek(self.start()), "<End>": lambda: self.seek(self.end()),
                "<bracketleft>": lambda: self.change_speed(-1), "<bracketright>": lambda: self.change_speed(1)}
        if not embedded:
            keys["<Escape>"] = self.close

        def typing():
            try:
                return isinstance(win.focus_get(), (tk.Entry, ttk.Entry))
            except (KeyError, tk.TclError):
                return False

        self.keymap = {}
        for k, f in keys.items():
            self.keymap[k] = lambda e, f=f: None if typing() and e.keysym != "Escape" else f()
        for ch, var in (("s", self.smooth), ("l", self.loop), ("r", self.ref), ("b", self.grey), ("g", self.ground),
                        ("t", self.trail)):
            for c in (ch, ch.upper()):
                self.keymap[f"<KeyPress-{c}>"] = (
                    lambda e, v=var: None if typing() else (v.set(not v.get()), self.render()))
        for c in ("k", "K"):
            self.keymap[f"<KeyPress-{c}>"] = lambda e: None if typing() else self.open_key_poses()
        for c in ("c", "C"):
            self.keymap[f"<KeyPress-{c}>"] = lambda e: None if typing() else self.open_compare()
        for c in ("a", "A"):
            self.keymap[f"<KeyPress-{c}>"] = lambda e: None if typing() else self.open_analytics()
        if self.cast is not None:   # Phase 11: O = the other characters on / off
            for c in ("o", "O"):
                self.keymap[f"<KeyPress-{c}>"] = lambda e: None if typing() else (
                    self.v_others.set(not self.v_others.get()), self.others_changed())
        if not embedded:
            for k, f in self.keymap.items():
                win.bind(k, f)
            win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Destroy>", self.on_destroy)

        self.building = False
        self.refresh()
        self.refresh_others()
        self.t = self.start()
        self.render()
        if not embedded:
            self.win.focus_force()
        self.poll()

    # ---- data -----------------------------------------------------------------
    def refresh(self):
        """Re-read the trace; rebuild the motion if it changed. Returns True when it changed."""
        try:
            keys, unfinished = self.get_keys()
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return False
        sig = repr((keys, unfinished))
        if sig == self.sig:
            return False
        self.sig = sig
        self.raw_keys, self.unfinished = keys, unfinished
        self.rebuild()
        self.show_notes()
        return True

    def show_notes(self):
        notes = []
        unfinished = self.unfinished
        if unfinished:
            notes.append("Frame" + ("s " if len(unfinished) > 1 else " ") + ", ".join(map(str, unfinished))
                         + (" aren't" if len(unfinished) > 1 else " isn't") + " finished yet, so "
                         + ("they're" if len(unfinished) > 1 else "it's") + " skipped.")
        if self.fps_from == "a guess":
            notes.append(f"Frame rate {self.fps:g} fps is a guess: pick the real one below.")
        if getattr(self, "others", None) and self.combined() and self.v_fixedpos.get():
            moved = [o["name"] for o in self.others if o["fix_changes"]] + (
                ["this character"] if self.fixing() and (self.fix.get("resize") or self.fix.get("inplace")
                                                         or self.fix.get("zoom") or self.fix.get("angle")) else [])
            if moved:
                notes.append("Fixed positions: " + ", ".join(moved) + " " + ("is" if len(moved) == 1 else "are")
                             + " resized, moved in place or turned by its fix, so the distances between characters "
                               "aren't the traced ones. Untick Fixed positions to see them as traced.")
        try:   # Phase 9: the fixed trace on disk is kept apart from your trace; say when it's behind
            import project
            if project.fixed_state(self.tdir)[0] == "stale":
                notes.append("The saved fixed trace was made from an older version of your trace: "
                             "Save Fixed Trace again to bring it up to date.")
        except Exception:   # a note only: never stop the player over it
            pass
        self.note.configure(text="   ".join(notes))

    def rebuild(self):
        """Apply the fix to the traced keys and rebuild the motion (and the grey original)."""
        raw = self.raw_keys
        if raw:
            self.keys, self.fix_info = apply_fix(raw, self.fix)
            self.motion, self.look = Motion(self.keys), Look(self.keys)
            self.ghost_motion, self.ghost_look = Motion(raw), Look(raw)
            self.t = min(max(self.t, self.start()), self.end())
        else:
            self.keys, self.fix_info = [], {}
            self.motion = self.look = self.ghost_motion = self.ghost_look = None
        self.update_fix_labels()
        self.update_key_poses()

    # ---- key poses (Phase 6) ----------------------------------------------------
    def update_key_poses(self):
        """Suggestions from the rules, on the poses shown (after the fix). Your marked poses are in kp_data."""
        self.kp_suggest = keyposes.detect(self.keys, self.kp_data["settings"]) if self.keys else []
        if self.kp_dialog is not None:
            self.kp_dialog.refresh()

    def current_frame(self):
        return int(round(self.t))

    def open_key_poses(self):
        if not self.keys:
            return
        if self.kp_dialog is not None:
            self.kp_dialog.win.lift()
            return
        from keypose_dialog import KeyPoseDialog
        self.kp_dialog = KeyPoseDialog(self)

    def open_compare(self):
        """C: compare two frames, or a frame in two versions (Phase 7). Read-only."""
        if self.cmp_dialog is not None:
            self.cmp_dialog.win.lift()
            return
        from compare_dialog import CompareDialog
        self.cmp_dialog = CompareDialog(self)

    def open_analytics(self):
        """A: measurements of this move (Phase 8): speeds, angles, timing, in px / bones / metres / game units."""
        if self.an_dialog is not None:
            self.an_dialog.win.lift()
            return
        from analytics_dialog import AnalyticsDialog

        def gone():
            self.an_dialog = None
        self.an_dialog = AnalyticsDialog(self.win.winfo_toplevel(), self.tdir, os.path.basename(self.dir), gone,
                                         frames_dir=self.dir)

    def fixing(self):
        f = self.fix
        return bool((f["angle"] and (f["turn"] or f["tilt"])) or f["zoom"] or f["resize"] or f["inplace"]
                    or (f.get("ground", True) and self.fix_info.get("ground_moved", 0) >= 0.5))

    def slider_moved(self):
        if not self.building:
            self.v_angle.set(True)
            self.fix_changed()

    def fix_changed(self):
        if self.building:
            return
        try:
            h = float(self.height_var.get())
            if h <= 0:
                raise ValueError
        except ValueError:
            h = self.fix["height"]
        self.fix = {"angle": self.v_angle.get(), "turn": float(self.turn_scale.get()),
                    "tilt": float(self.tilt_scale.get()), "zoom": self.v_zoom.get(), "resize": self.v_resize.get(),
                    "height": h, "inplace": self.v_inplace.get(), "ground": self.v_ground.get()}
        self.rebuild()
        self.render()

    def update_fix_labels(self):
        if not hasattr(self, "fix_lbl"):
            return
        i = self.fix_info
        if "spread_before" in i and len(self.raw_keys) > 1:
            text = f"Bone length wobble: {i['spread_before'] * 100:.0f}%"
            if self.fix["angle"] and (self.fix["turn"] or self.fix["tilt"]):
                text += f" -> {i['spread_after'] * 100:.0f}%"
            self.spread_lbl.configure(text=text + "  (lower = more side-on)")
        else:
            self.spread_lbl.configure(text="")
        summary = fix_summary(self.fix, i, self.fps) if self.fixing() else ""
        if summary:
            text = "Fixed: " + summary
        elif i:
            text = f"No fix yet. The body is {i.get('height_before', 0):.0f} px tall in the trace."
        else:
            text = ""
        self.fix_lbl.configure(text=text, fg=hud.GREEN)
        unsaved = self.fixing() and self.fix != self.saved_fix
        self.save_btn.configure(text="Save Fixed Trace  *" if unsaved else "Save Fixed Trace")

    def auto(self):
        if len(self.raw_keys) < 2:
            self.fix_lbl.configure(text="Auto needs at least 2 finished frames.", fg=hud.RED_HI)
            return
        self.fix_lbl.configure(text="Looking for the camera angle…", fg=hud.GREEN)
        self.win.update_idletasks()
        turn, tilt = auto_angle(self.raw_keys, self.v_zoom.get())
        self.building = True
        self.turn_scale.set(turn)
        self.tilt_scale.set(tilt)
        self.v_angle.set(True)
        self.building = False
        self.fix_changed()

    def save_fixed(self):
        if not self.keys:
            return
        travel = abs(self.fix_info.get("travel", 0.0))
        choice = ask_choice(
            self.win, "Save fixed trace",
            f"Save it moving or in place?\n\nMoving keeps the travel across the screen ({travel:.0f} px). "
            "In place takes it away, like a treadmill; the speed it travelled is saved either way.",
            ["Moving", "In place", "Cancel"], 1 if self.fix["inplace"] else 0)
        if choice not in (0, 1):
            return
        self.building = True
        self.v_inplace.set(choice == 1)
        self.building = False
        self.fix_changed()
        est = {}
        try:
            with open(trace_path(self.tdir), encoding="utf-8") as fh:
                J = json.load(fh)
            est = {int(f): E for f, E in zip(J["frames"], J.get("estimated") or [])}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        info = self.fix_info
        data = {"frames": [f for f, _ in self.keys],
                "pts": [{n: [round(P[n][0], 1), round(P[n][1], 1)] for n in trace_io.ALL if n in P}
                        for _, P in self.keys],
                "estimated": [est.get(f, []) for f, _ in self.keys],
                "fix": self.fix, "from": "trace.json", "summary": fix_summary(self.fix, info, self.fps),
                "fps": round(self.fps, 3), "in_place": bool(self.fix["inplace"]),
                "travel_px": round(info.get("travel", 0.0), 1),
                "travel_px_per_s": round(info.get("travel_per_frame", 0.0) * self.fps, 1)}
        if "ground" in info:
            data["ground_y"] = round(info["ground"], 1)
        path = fixed_path(self.tdir)
        try:   # a dated copy of the fixed trace this replaces, in backups\ (upgrade data protection)
            trace_io.backup_file(self.tdir, trace_io.find_file(self.tdir, trace_io.FIXED), "fixed", "fix")
        except OSError:
            pass
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=1)
            os.replace(tmp, path)
        except OSError as e:   # e.g. a read-only trace_fixed.json: say so, leave the old file as it was
            if os.path.exists(tmp):
                os.remove(tmp)   # only our own half-written file
            self.fix_lbl.configure(text=f"Couldn't save the fixed trace ({e}); the old one is unchanged."
                                   + ("  It's read-only." if trace_io.is_protected(path) else ""), fg=hud.RED_HI)
            return
        self.saved_fix = dict(self.fix)
        self.update_fix_labels()
        self.fix_lbl.configure(text=f"Saved {path}  ({data['summary']}). Your trace.json is unchanged.",
                               fg=hud.GREEN)
        self.show_notes()

    # ---- Phase 11: every visible character together (combined playback) --------------------------------
    def refresh_others(self):
        """Re-read the other characters' traces (only when a file changed). -> True when something changed."""
        if self.cast is None:
            return False
        changed = False
        for o in self.others:
            try:
                keys, _ = o["get"]()
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                keys = []
            sig = repr(keys)
            if sig == o["sig"]:
                continue
            o["sig"], changed = sig, True
            o["raw"] = keys
            o["motion"] = Motion(keys) if keys else None
            o["look"] = Look(keys) if keys else None
            o["fmotion"] = o["flook"] = o["fground"] = None
            o["fix_changes"] = False
            fx = load_fix(o["tdir"]) if keys else None
            if fx:   # its own saved fix settings, applied to its trace (what PLAY / FIX shows for it)
                fk, info = apply_fix(keys, fx)
                o["fmotion"], o["flook"] = Motion(fk), Look(fk)
                o["fix_changes"] = bool(fx.get("resize") or fx.get("inplace") or fx.get("zoom")
                                        or (fx.get("angle") and (fx.get("turn") or fx.get("tilt"))))
                if fx.get("ground", True) and "ground" in info:
                    o["fground"] = (info["ground"], info["ground_reach"])
        return changed

    def combined(self):
        return bool(self.cast is not None and self.others and self.v_others.get())

    def all_times(self):
        ts = list(self.motion.times) if self.motion else []
        if self.combined():
            for o in self.others:
                if o["motion"]:
                    ts += [o["motion"].times[0], o["motion"].times[-1]]
        return sorted(ts)

    def figures(self):
        """[(entry or None for this character, motion, look, ground or None)] to draw, this character last."""
        fixed = self.v_fixedpos.get()
        out = []
        for o in self.others:
            if fixed and o["fmotion"]:
                out.append((o, o["fmotion"], o["flook"], o["fground"]))
            elif o["motion"]:
                out.append((o, o["motion"], o["look"], None))
        if self.motion:
            if fixed:
                g = ((self.fix_info["ground"], self.fix_info["ground_reach"])
                     if self.fix.get("ground", True) and "ground" in self.fix_info else None)
                out.append((None, self.motion, self.look, g))
            else:   # as traced: everyone in the same picture space, so the true relative positions
                out.append((None, self.ghost_motion, self.ghost_look, None))
        return out

    def compose_all(self, W, H):
        """The picture at time self.t with every visible character: each with its own in-betweens; outside its
        traced frames it's left out (or holds its first / last pose with "Hold outside")."""
        figs = self.figures()
        boxes = [lk.box for _, _, lk, _ in figs if lk]
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        margin = 30
        k = min((W - 2 * margin) / max(1e-6, x1 - x0), (H - 2 * margin) / max(1e-6, y1 - y0))
        ox = (W - (x1 - x0) * k) / 2 - x0 * k
        oy = (H - (y1 - y0) * k) / 2 - y0 * k
        img = Image.new("RGB", (W, H), PAPER)
        f = round(self.t)
        if self.ref.get():
            src = self.frame_image(f)
            if src is not None:
                ref = src.transform((W, H), Image.AFFINE, (1 / k, 0, -ox / k, 0, 1 / k, -oy / k),
                                    resample=Image.BILINEAR, fillcolor=PAPER)
                img = Image.blend(img, ref, 0.4)
        d = ImageDraw.Draw(img)
        mine = self.look if self.v_fixedpos.get() else self.ghost_look
        if self.ground.get() and mine:
            gy = mine.ground * k + oy
            d.line((0, gy, W, gy), fill=(200, 200, 200), width=2)
        if self.trail.get() and self.v_fixedpos.get() and self.motion:
            trails.draw(img, self.trail_paths(), lambda x, y: (x * k + ox, y * k + oy), alpha=0.9)
        hold = self.v_hold.get()
        for o, m, lk, g in figs:
            first, last = m.times[0], m.times[-1]
            if not (first - 1e-9 <= self.t <= last + 1e-9) and not hold:
                continue
            P = m.pose(min(max(self.t, first), last), self.smooth.get())
            if g:
                P = on_ground(P, g[0], g[1])[0]
            if o is None:
                front = INK
                back = BACK_INK if self.grey.get() else INK
            else:
                front = hex_rgb(o["colour"]) if self.v_colours.get() else OTHER_INK
                back = tuple((c + p) // 2 for c, p in zip(front, PAPER))
            self.draw_figure(img, P, lk, k, ox, oy, back, front)
            if o is not None:   # its name above its head
                hx, hy = P["head"][0] * k + ox, P["head"][1] * k + oy - lk.r * k - 14
                ImageDraw.Draw(img).text((hx, hy), o["name"], fill=front, anchor="ms")
        return img

    def others_changed(self):
        self.show_notes()
        self.render()

    def pick_character(self, e=None):
        name = self.char_var.get()
        cid = next((c for c, n in self.cast.get("ids", []) if n == name), None)
        if cid and cid != self.cast.get("active") and self.on_character:
            self.on_character(cid)

    def poll(self):
        if not self.alive:
            return
        mine = self.refresh()
        theirs = self.refresh_others()   # Phase 11: the other characters' files
        if mine or theirs:
            self.render()
        self.poll_id = self.win.after(400, self.poll)

    def start(self):
        ts = self.all_times()   # Phase 11: every shown character's frames
        return ts[0] if ts else 0.0

    def end(self):
        ts = self.all_times()
        return ts[-1] if ts else 0.0

    # ---- moving ---------------------------------------------------------------
    def seek(self, t):
        self.pause()
        self.t = min(max(t, self.start()), self.end())
        self.render()

    def step(self, d):
        self.seek(round(self.t) + d)

    def jump_key(self, d):
        if not self.motion:
            return
        ts = self.motion.times
        if d > 0:
            nxt = [k for k in ts if k > self.t + 1e-6]
            self.seek(nxt[0] if nxt else ts[-1])
        else:
            prev = [k for k in ts if k < self.t - 1e-6]
            self.seek(prev[-1] if prev else ts[0])

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if not self.motion or len(self.motion.times) < 2:
            return
        if self.t >= self.end() - 1e-6:
            self.t = self.start()
        self.playing = True
        self.play_btn.configure(text="❚❚  Pause")
        self.clock0, self.t0, self.hold_until = time.perf_counter(), self.t, None
        self.tick()

    def tick(self):
        if not self.playing or not self.alive:
            return
        now = time.perf_counter()
        if self.hold_until is not None:      # short pause on the last pose before looping
            if now >= self.hold_until:
                self.clock0, self.t0, self.hold_until = now, self.start(), None
        else:
            self.t = self.t0 + (now - self.clock0) * self.fps * self.speed
            if self.t >= self.end():
                self.t = self.end()
                if self.loop.get():
                    self.hold_until = now + 0.5
                else:
                    self.render()
                    self.pause()
                    return
        self.render()
        self.tick_id = self.win.after(15, self.tick)

    def pause(self):
        self.playing = False
        if self.tick_id:
            self.win.after_cancel(self.tick_id)
            self.tick_id = None
        self.play_btn.configure(text="▶  Play")

    def set_speed(self, s):
        self.speed = s
        self.speed_box.set(f"{s:g}×")
        if self.playing:
            self.clock0, self.t0 = time.perf_counter(), self.t
        self.render()

    def change_speed(self, d):
        i = min(range(len(SPEEDS)), key=lambda k: abs(SPEEDS[k] - self.speed))
        self.set_speed(SPEEDS[max(0, min(len(SPEEDS) - 1, i + d))])

    def on_rate(self, e):
        self.fps = float(self.rate_values[self.rate_box.current()])
        self.fps_from = "you"
        self.refresh_note_rate()
        if self.playing:
            self.clock0, self.t0 = time.perf_counter(), self.t
        self.win.focus_set()
        self.render()

    def refresh_note_rate(self):
        self.sig = None      # rebuilds the note text
        self.refresh()

    def on_line(self, e):
        if not self.motion:
            return
        w = self.line.winfo_width()
        a, b = self.start(), self.end()
        self.seek(a + (b - a) * min(1, max(0, (e.x - 14) / max(1, w - 28))))

    # ---- drawing --------------------------------------------------------------
    def frame_image(self, f):
        path = os.path.join(self.dir, f"f{f:02d}.png")
        if f not in self.ref_cache:
            try:
                self.ref_cache[f] = Image.open(path).convert("RGB") if os.path.exists(path) else None
            except OSError:
                self.ref_cache[f] = None
            if len(self.ref_cache) > 120:
                self.ref_cache.pop(next(iter(self.ref_cache)))
        return self.ref_cache[f]

    def render(self):
        if not self.alive:
            return
        c = self.stage
        W, H = c.winfo_width(), c.winfo_height()
        if W < 10 or H < 10:
            return
        self.draw_line()
        if not self.motion:
            c.delete("all")
            c.create_text(W / 2, H / 2, font=hud.TITLE, fill="#555555", justify="center",
                          text="Nothing to play yet.\nFinish at least one frame (all 12 points) in Trace Clicker.")
            self.info.configure(text="")
            return
        img = self.compose(W, H)
        f = round(self.t)
        self.photo = ImageTk.PhotoImage(img)
        c.delete("all")
        c.create_image(0, 0, image=self.photo, anchor="nw")

        ts = self.motion.times
        on_key = any(abs(self.t - kt) < 1e-6 for kt in ts)
        kind = f"key {ts.index(min(ts, key=lambda kt: abs(kt - self.t))) + 1} of {len(ts)}" if on_key else \
            ("between keys" if self.smooth.get() else "holding the last key")
        self.info.configure(text=f"Frame {f}  ({kind})    {(self.t - ts[0]) / self.fps:.2f} / "
                                 f"{(ts[-1] - ts[0]) / self.fps:.2f} s    {self.fps:.3g} FPS    {self.speed:g}×")
        total = (ts[-1] - ts[0]) / self.fps
        self.g_time.set((self.t - ts[0]) / self.fps, max(total, 1e-9), f"{(self.t - ts[0]) / self.fps:.2f}",
                        f"of {total:.2f} s")
        ki = self.motion.key_at(self.t)
        self.g_key.set(ki + 1, len(ts), ki + 1, f"key / {len(ts)}")

    def compose(self, W, H):
        """The picture at time self.t, W x H pixels."""
        if self.combined():   # Phase 11: every visible character together
            return self.compose_all(W, H)
        look = self.look
        x0, y0, x1, y1 = look.box
        ghost = self.v_ghost.get() and self.fixing() and self.ghost_motion is not None
        if ghost:
            gx0, gy0, gx1, gy1 = self.ghost_look.box
            x0, y0, x1, y1 = min(x0, gx0), min(y0, gy0), max(x1, gx1), max(y1, gy1)
        margin = 30
        k = min((W - 2 * margin) / (x1 - x0), (H - 2 * margin) / (y1 - y0))
        ox = (W - (x1 - x0) * k) / 2 - x0 * k
        oy = (H - (y1 - y0) * k) / 2 - y0 * k

        img = Image.new("RGB", (W, H), PAPER)
        f = round(self.t)
        if self.ref.get():
            src = self.frame_image(f)
            if src is not None:   # the real frame behind the stickman, faded
                ref = src.transform((W, H), Image.AFFINE, (1 / k, 0, -ox / k, 0, 1 / k, -oy / k),
                                    resample=Image.BILINEAR, fillcolor=PAPER)
                img = Image.blend(img, ref, 0.4)
        d = ImageDraw.Draw(img)
        if self.ground.get():
            gy = look.ground * k + oy
            d.line((0, gy, W, gy), fill=(200, 200, 200), width=2)

        if ghost:
            G = self.ghost_motion.pose(self.t, self.smooth.get())
            self.draw_figure(img, G, self.ghost_look, k, ox, oy, (205, 205, 205), (190, 190, 190))
        if self.trail.get():
            trails.draw(img, self.trail_paths(), lambda x, y: (x * k + ox, y * k + oy), alpha=0.9)
        P = self.motion.pose(self.t, self.smooth.get())
        if self.fix.get("ground", True) and "ground" in self.fix_info:   # in-betweens stay on the ground too
            P = on_ground(P, self.fix_info["ground"], self.fix_info["ground_reach"])[0]
        self.draw_figure(img, P, look, k, ox, oy, BACK_INK if self.grey.get() else INK, INK)
        return img

    def trail_paths(self, span=TRAIL_SPAN):
        """Trails for the hands, feet and head: the stickman's own (in-between) positions, one dot per frame, up to
        span frames back (solid) and ahead (dashed). Dot spacing shows the speed."""
        ts = self.motion.times
        t = min(max(self.t, ts[0]), ts[-1])
        smooth = self.smooth.get()
        ground = self.fix.get("ground", True) and "ground" in self.fix_info

        def pose(tt):
            P = self.motion.pose(tt, smooth)
            return on_ground(P, self.fix_info["ground"], self.fix_info["ground_reach"])[0] if ground else P

        back = [t - i for i in range(span, 0, -1) if t - i >= ts[0] - 1e-9]
        ahead = [t + i for i in range(1, span + 1) if t + i <= ts[-1] + 1e-9]
        poses = {tt: pose(tt) for tt in back + [t] + ahead}
        out = {}
        for n in trails.DEFAULT_JOINTS:
            past = [(tt, tuple(poses[tt][n])) for tt in back + [t]]
            future = [(tt, tuple(poses[tt][n])) for tt in [t] + ahead]
            out[n] = (past, future)
        return out

    def draw_figure(self, img, P, look, k, ox, oy, back_ink, front_ink):
        W, H = img.size
        # draw only the area around the figure, at SS x size, then shrink it: smooth edges, still fast
        xs = [P[n][0] for n in ORDER]
        ys = [P[n][1] for n in ORDER]
        pad = look.r + look.foot_len + look.leg_w
        bx0 = max(0, int((min(xs) - pad) * k + ox) - 2)
        by0 = max(0, int((min(ys) - pad) * k + oy) - 2)
        bx1 = min(W, int((max(xs) + pad) * k + ox) + 3)
        by1 = min(H, int((max(ys) + pad) * k + oy) + 3)
        if bx1 > bx0 and by1 > by0:
            size = ((bx1 - bx0) * SS, (by1 - by0) * SS)
            back, front = Image.new("L", size, 0), Image.new("L", size, 0)

            def to_screen(x, y):
                return ((x * k + ox - bx0) * SS, (y * k + oy - by0) * SS)

            draw_stickman(P, look, to_screen, ImageDraw.Draw(back), ImageDraw.Draw(front), k * SS)
            back = back.reduce(SS)
            front = front.reduce(SS)
            region = img.crop((bx0, by0, bx1, by1))
            region.paste(back_ink, (0, 0), back)
            region.paste(front_ink, (0, 0), front)
            img.paste(region, (bx0, by0))

    def draw_line(self):
        c = self.line
        c.delete("all")
        if not self.motion:
            return
        w = c.winfo_width()
        a, b = self.start(), self.end()

        def x(t):
            return 14 + (w - 28) * ((t - a) / (b - a) if b > a else 0)

        c.create_line(14, 12, w - 14, 12, fill=hud.LINE, width=2)
        c.create_line(14, 12, x(self.t), 12, fill=hud.RED, width=2)
        if self.combined():   # Phase 11: the other characters' key frames, in their colours
            for o in self.others:
                if o["motion"]:
                    for kt in o["motion"].times:
                        if a <= kt <= b:
                            c.create_line(x(kt), 8, x(kt), 16, fill=o["colour"], width=3)
        for kt in self.motion.times:
            c.create_line(x(kt), 5, x(kt), 19, fill=hud.TEXT, width=2)
            c.create_text(x(kt), 30, text=f"{kt:g}", font=hud.TINY, fill=hud.DIM)
        for u in self.unfinished:
            if a <= u <= b:
                c.create_line(x(u), 4, x(u), 20, fill=hud.RED_HI, width=2, dash=(2, 2))
        mine = {q["frame"]: q["label"] for q in self.kp_data["poses"]}
        taken = set(mine) | set(self.kp_data["rejected"])
        for sgt in self.kp_suggest:          # suggestions: hollow amber diamonds
            f = sgt["frame"]
            if f not in taken and a <= f <= b:
                c.create_polygon(x(f), 6, x(f) + 5, 12, x(f), 18, x(f) - 5, 12, fill="", outline=hud.AMBER,
                                 width=2, tags="kp")
        for f, label in mine.items():        # your key poses: filled amber diamonds with their label
            if a <= f <= b:
                c.create_polygon(x(f), 5, x(f) + 6, 12, x(f), 19, x(f) - 6, 12, fill=hud.AMBER, outline="",
                                 tags="kp")
                xf = x(f)
                anchor = "w" if xf < 70 else "e" if xf > w - 70 else "center"   # keep end labels on screen
                c.create_text(max(2, min(w - 2, xf)), 46, text=label[:18], font=hud.TINY, fill=hud.AMBER,
                              anchor=anchor, tags="kp")
        px = x(self.t)
        c.create_line(px, 2, px, 22, fill=hud.RED_HI, width=2)
        c.create_polygon(px - 5, 0, px + 5, 0, px, 6, fill=hud.RED, outline="")

    # ---- closing --------------------------------------------------------------
    def on_destroy(self, e):
        if e.widget is self.win:
            self.alive = False
            if self.kp_dialog is not None:     # another move was opened: its Key Poses window goes too
                self.kp_dialog.close()
            if self.cmp_dialog is not None:
                self.cmp_dialog.close()
            if self.an_dialog is not None:
                self.an_dialog.close()
            for i in (self.tick_id, self.poll_id):
                if i:
                    try:
                        self.win.after_cancel(i)
                    except tk.TclError:
                        pass

    def close(self):
        self.pause()
        if not self.embedded:
            self.win.destroy()


OTHER_INK = (96, 96, 96)   # Phase 11: the other characters, when not in their own colours


def hex_rgb(colour):
    c = str(colour).lstrip("#")
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return OTHER_INK


def file_keys(path):
    """A get_keys for a trace.json on disk (re-read only when the file changes)."""
    cache = {"mtime": None, "val": ([], [])}

    def get():
        m = os.path.getmtime(path)
        if m != cache["mtime"]:
            cache["val"] = read_trace(path)
            cache["mtime"] = m
        return cache["val"]
    return get


def main(args):
    if not args:
        print(__doc__)
        return 1
    target = os.path.abspath(args[0].strip().strip('"'))
    path = trace_path(target)
    if not os.path.exists(path):
        print("There's no trace.json in", os.path.dirname(path) if os.path.isdir(target) else target)
        return 1
    folder = os.path.dirname(path)
    try:
        read_trace(path)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"Can't read {path}: {e}")
        return 1
    try:   # sharp (not blurry) window on scaled Windows displays
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    Player(root, folder, file_keys(path), os.path.basename(folder))
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

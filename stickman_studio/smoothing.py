"""Joint smoothing for Stickman Studio traces (upgrade Phase 4). Plain maths with NumPy, no AI.

Each joint's path is smoothed on its own, in TIME (frame numbers), so key frames that are 1, 3 or 5 frames apart are
handled correctly. Only points you placed are used and changed; faded or missing points are left alone.

Methods (strength 1-10, higher = smoother):
    moving      moving average of the points within +-strength frames
    weighted    weighted moving average: nearer frames count more (triangle weights)
    exponential exponential smoothing run forwards and then backwards, so it doesn't lag behind the motion
    savgol      Savitzky-Golay: fits a small curve (degree 2) through the points within +-(strength+1) frames; it
                keeps peaks (the end of a punch, the top of a jump) better than averaging

Protect fast moves (on by default): jitter needs only small corrections, about the size of the joint's own noise.
Flattening a real fast move (the tip of a punch, the top of a jump, a landing) would need a correction many times
bigger than that, so such large corrections are faded out: for each joint the typical correction size ("noise") is
measured robustly, and a point whose correction is more than PROTECT_K x that keeps (nearly) its traced position.
(A speed rule doesn't work: at the very tip of a punch the hand is momentarily still.)
Keep ends: the first and last frame of each joint are never moved.
"""
import math

import numpy as np

import trace_io

METHODS = [("savgol", "Savitzky–Golay (keeps peaks best)"), ("weighted", "Weighted moving average"),
           ("moving", "Moving average"), ("exponential", "Exponential (forwards + backwards)")]
BONES = [(a, b) for ch in trace_io.CHAINS for a, b in zip(ch, ch[1:])]
PROTECT_K = 2.5        # corrections bigger than this many times the joint's typical correction are faded out
NOISE_FLOOR = 0.3      # px: the typical correction is never taken as smaller than this
NOISE_MAX = 0.1        # bone lengths: tracing jitter is small, so the typical correction is never taken as bigger
#                        than this. Without the cap, a move made only of big, real pose changes (a flip traced on a
#                        few key frames) would look like "all noise" and be flattened.


def _series(t, v, method, strength):
    """Smooth one coordinate series v (floats) over times t (increasing frame numbers)."""
    n = len(v)
    if n < 3:
        return v.copy()
    out = np.empty(n)
    if method == "exponential":
        tau = 0.6 * strength

        def run(tt, vv):
            y = np.empty(len(vv))
            y[0] = vv[0]
            for i in range(1, len(vv)):
                a = 1.0 - math.exp(-abs(tt[i] - tt[i - 1]) / tau)
                y[i] = y[i - 1] + a * (vv[i] - y[i - 1])
            return y

        fwd = run(t, v)
        return run(t[::-1], fwd[::-1])[::-1]
    h = float(strength) + (1.0 if method == "savgol" else 0.0)
    for i in range(n):
        dt = t - t[i]
        m = np.abs(dt) <= h + 1e-9
        if method == "moving":
            out[i] = v[m].mean()
        elif method == "weighted":
            w = (1.0 - np.abs(dt[m]) / (h + 1.0))
            out[i] = float(np.sum(w * v[m]) / np.sum(w))
        else:   # savgol: local least-squares polynomial (works with uneven frame gaps too)
            k = int(m.sum())
            deg = 2 if k >= 4 else (1 if k >= 2 else 0)
            if deg == 0:
                out[i] = v[i]
                continue
            A = np.vander(dt[m], deg + 1)
            coef, *_ = np.linalg.lstsq(A, v[m], rcond=None)
            out[i] = coef[-1]        # the fitted value at dt = 0
    return out


def body_scale(P):
    """A frame's body size: the median length of its bones (all placed joints of that frame)."""
    Ls = [math.dist(P[a], P[b]) for a, b in BONES if a in P and b in P]
    return float(np.median(Ls)) if len(Ls) >= 5 else None


def smooth(pts, joints, method="savgol", strength=3, protect=True, keep_ends=True):
    """pts = {frame: {joint: [x, y]}} (only placed points). -> ({frame: {joint: [x, y]}} new positions for every
    point it would move, stats). The input is not changed."""
    frames = sorted(pts)
    scales = {f: body_scale(pts[f]) for f in frames}
    known = [s for s in scales.values() if s]
    default_scale = float(np.median(known)) if known else 40.0
    new = {}
    for j in joints:
        fs = [f for f in frames if j in pts[f]]
        if len(fs) < 3:
            continue
        t = np.array(fs, float)
        xy = np.array([pts[f][j] for f in fs], float)
        sm = np.column_stack([_series(t, xy[:, 0], method, strength), _series(t, xy[:, 1], method, strength)])
        if protect:
            corr = np.hypot(*(sm - xy).T)                       # how far each point would move
            scale = float(np.median([scales[f] or default_scale for f in fs]))
            noise = 1.4826 * float(np.median(corr))             # robust typical correction (MAD-style)
            noise = min(max(NOISE_FLOOR, noise), max(NOISE_FLOOR, NOISE_MAX * scale))
            w = 1.0 / (1.0 + (corr / (PROTECT_K * noise)) ** 4)  # ~1 for jitter-sized moves, ~0 for big ones
            sm = xy + w[:, None] * (sm - xy)
        if keep_ends:
            sm[0], sm[-1] = xy[0], xy[-1]
        for i, f in enumerate(fs):
            if np.hypot(*(sm[i] - xy[i])) >= 0.05:
                new.setdefault(f, {})[j] = [float(sm[i][0]), float(sm[i][1])]
    return new, stats(pts, new, joints)


def jitter(pts, joints):
    """Mean size of the frame-to-frame change in velocity (px per frame²) over the joints: lower = steadier."""
    vals = []
    for j in joints:
        fs = [f for f in sorted(pts) if j in pts[f]]
        for a, b, c in zip(fs, fs[1:], fs[2:]):
            pa, pb, pc = (np.array(pts[f][j], float) for f in (a, b, c))
            v1, v2 = (pb - pa) / (b - a), (pc - pb) / (c - b)
            vals.append(float(np.hypot(*(v2 - v1))) / ((c - a) / 2))
    return float(np.mean(vals)) if vals else 0.0


def apply(pts, new):
    out = {f: {j: list(p) for j, p in P.items()} for f, P in pts.items()}
    for f, J in new.items():
        out[f].update({j: list(p) for j, p in J.items()})
    return out


def stats(pts, new, joints):
    moves = [(math.dist(pts[f][j], p), f, j) for f, J in new.items() for j, p in J.items()]
    after = apply(pts, new)
    total = sum(1 for f in pts for j in joints if j in pts[f])
    big = max(moves) if moves else (0.0, None, None)
    return {"points": total, "changed": len(moves), "mean_move": float(np.mean([m[0] for m in moves])) if moves else 0.0,
            "max_move": big[0], "max_at": (big[1], big[2]), "jitter_before": jitter(pts, joints),
            "jitter_after": jitter(after, joints)}

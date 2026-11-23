"""Key pose identification (upgrade Phase 6): important frames found with coordinate rules and thresholds you set.

No AI and no movement recognition: every suggestion says which rule found it and why ("frontHand turns 140°").
The labels (starting position, preparation, maximum extension, contact or impact, recovery, ending position, ...) are
only labels; a suggested label is a rough guess from the rule, for you to change.

Rules (each can be switched off; sizes are measured in BONES = the median bone length of that frame, and speeds in
bones per frame, so camera zoom and frame size don't matter):
    first_last   the first and last traced frame
    direction    a joint reverses / turns sharply: the angle between its movement into and out of the frame is at
                 least direction_deg (both movements must be real, not jitter: over MIN_MOVE bones per frame)
    extension    an arm (neck to hand) or leg (hip to foot) reaches furthest: a peak of its length that stands out by
                 at least extension_prom of that limb's whole range
    angles       an elbow, knee or torso angle is at a minimum or maximum that stands out by angle_prom degrees
    sudden       a joint's speed changes suddenly by sudden_ratio x or more (fast in, slow out = a stop or impact;
                 slow in, fast out = a sudden start)
    stationary   the whole body is (nearly) still: every joint moves less than still_speed bones per frame, in and
                 out; a run of still frames gives one suggestion

Stored next to the trace in key_poses.json (never inside trace.json):
    {"schema": 1, "poses": [{"frame": 4, "label": "maximum extension", "source": "suggested" | "manual",
                             "why": "..."}],
     "rejected": [4, 9], "settings": {...}}
"""
import json
import math
import os

import trace_io

FILE = "key_poses.json"
LABELS = ["starting position", "preparation", "maximum extension", "contact or impact", "recovery",
          "ending position", "hold", "direction change", "other"]
DEFAULTS = {"first_last": True, "direction": True, "direction_deg": 100,
            "direction_joints": ["head", "frontHand", "backHand", "frontFoot", "backFoot"],
            "extension": True, "extension_prom": 0.5, "angles": True, "angle_prom": 30,
            "sudden": True, "sudden_ratio": 2.5, "stationary": True, "still_speed": 0.05}
MIN_MOVE = 0.08        # bones / frame: slower than this is jitter, not a movement with a direction
MIN_FAST = 0.25        # bones / frame: the fast side of a "sudden" change must be at least this fast
LIMBS = {"front arm": ("neck", "frontHand"), "back arm": ("neck", "backHand"),
         "front leg": ("hip", "frontFoot"), "back leg": ("hip", "backFoot")}
ANGLES = {"front elbow": ("neck", "frontElbow", "frontHand"), "back elbow": ("neck", "backElbow", "backHand"),
          "front knee": ("hip", "frontKnee", "frontFoot"), "back knee": ("hip", "backKnee", "backFoot"),
          "torso bend": ("neck", "waist", "hip")}
BONES = [(a, b) for ch in trace_io.CHAINS for a, b in zip(ch, ch[1:])]
PRIORITY = ["first_last", "sudden", "extension", "stationary", "direction", "angles"]


def scale(P):
    Ls = sorted(math.dist(P[a], P[b]) for a, b in BONES if a in P and b in P)
    if not Ls:
        return 1.0
    k = len(Ls)
    return max(1e-6, Ls[k // 2] if k % 2 else (Ls[k // 2 - 1] + Ls[k // 2]) / 2)


def angle_at(P, a, b, c):
    """Angle in degrees at joint b between b->a and b->c (180 = straight)."""
    ax, ay = P[a][0] - P[b][0], P[a][1] - P[b][1]
    cx, cy = P[c][0] - P[b][0], P[c][1] - P[b][1]
    na, nc = math.hypot(ax, ay), math.hypot(cx, cy)
    if na < 1e-9 or nc < 1e-9:
        return 180.0
    return math.degrees(math.acos(max(-1.0, min(1.0, (ax * cx + ay * cy) / (na * nc)))))


def peaks(vals, min_prom):
    """Indexes of interior local maxima whose prominence (how far they stand above the higher of the two lowest
    points before reaching something taller on each side) is at least min_prom. -> [(index, prominence)]."""
    out = []
    n = len(vals)
    for i in range(1, n - 1):
        v = vals[i]
        if not (v > vals[i - 1] and v >= vals[i + 1]):
            continue
        lo_l = v
        for j in range(i - 1, -1, -1):
            if vals[j] > v:
                break
            lo_l = min(lo_l, vals[j])
        lo_r = v
        for j in range(i + 1, n):
            if vals[j] > v:
                break
            lo_r = min(lo_r, vals[j])
        prom = v - max(lo_l, lo_r)
        if prom >= min_prom:
            out.append((i, prom))
    return out


def detect(keys, settings=None):
    """keys = [(frame, {joint: (x, y)})] in frame order, all 12 joints. -> suggestions, sorted by frame:
    [{"frame": f, "label": suggested label, "rules": [...], "why": "reason; reason"}]."""
    s = dict(DEFAULTS, **(settings or {}))
    keys = sorted(keys, key=lambda k: k[0])
    n = len(keys)
    found = {}

    def add(i, rule, why):
        f = keys[i][0]
        e = found.setdefault(f, {"frame": f, "rules": [], "reasons": []})
        if rule not in e["rules"]:
            e["rules"].append(rule)
        e["reasons"].append(why)

    if n == 0:
        return []
    F = [f for f, _ in keys]
    # v3.0: measured on the 12 required joints. The optional ones (shoulders, hand tips, toes) may be on some key
    # frames only, and a rule comparing frame to frame would ask for one a frame doesn't have (KeyError).
    P = [{n: p[n] for n in trace_io.ORDER if n in p} for _, p in keys]
    S = [scale(p) for p in P]
    if s["first_last"]:
        add(0, "first_last", "first frame")
        if n > 1:
            add(n - 1, "first_last", "last frame")
    if n < 3:
        return finish(found, keys)

    def speed(j, k):            # joint j between key k and k+1, in bones per frame
        return math.dist(P[k][j], P[k + 1][j]) / max(F[k + 1] - F[k], 1e-9) / ((S[k] + S[k + 1]) / 2)

    joints = list(P[0])
    if s["direction"]:
        for i in range(1, n - 1):
            best = None
            for j in s["direction_joints"]:
                if j not in P[i]:
                    continue
                a = (P[i][j][0] - P[i - 1][j][0], P[i][j][1] - P[i - 1][j][1])
                b = (P[i + 1][j][0] - P[i][j][0], P[i + 1][j][1] - P[i][j][1])
                if speed(j, i - 1) < MIN_MOVE or speed(j, i) < MIN_MOVE:
                    continue
                cos = (a[0] * b[0] + a[1] * b[1]) / (math.hypot(*a) * math.hypot(*b))
                ang = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
                if ang >= s["direction_deg"] and (best is None or ang > best[1]):
                    best = (j, ang)
            if best:
                add(i, "direction", f"{best[0]} turns {best[1]:.0f}°")
    if s["extension"]:
        for limb, (root, end) in LIMBS.items():
            r = [math.dist(p[root], p[end]) / sc for p, sc in zip(P, S)]
            rng = max(r) - min(r)
            if rng < 0.15:          # this limb hardly changes length: nothing stands out
                continue
            for i, prom in peaks(r, s["extension_prom"] * rng):
                add(i, "extension", f"{limb} at full reach ({r[i]:.1f} bones from {root})")
    if s["angles"]:
        for name, (a, b, c) in ANGLES.items():
            v = [angle_at(p, a, b, c) for p in P]
            for i, prom in peaks(v, s["angle_prom"]):
                add(i, "angles", f"{name} straightest ({v[i]:.0f}°)")
            for i, prom in peaks([-x for x in v], s["angle_prom"]):
                add(i, "angles", f"{name} most bent ({v[i]:.0f}°)")
    if s["sudden"]:
        for i in range(1, n - 1):
            best = None
            for j in joints:
                vin, vout = speed(j, i - 1), speed(j, i)
                if vin >= MIN_FAST and vin >= s["sudden_ratio"] * max(vout, 1e-6):
                    cand = ("stop", j, vin, vout, vin / max(vout, 1e-6))
                elif vout >= MIN_FAST and vout >= s["sudden_ratio"] * max(vin, 1e-6):
                    cand = ("start", j, vin, vout, vout / max(vin, 1e-6))
                else:
                    continue
                if best is None or cand[4] > best[4]:
                    best = cand
            if best:
                kind, j, vin, vout, _ = best
                add(i, "sudden_" + kind, f"{j} {'stops' if kind == 'stop' else 'starts'} suddenly "
                                         f"({vin:.2f} → {vout:.2f} bones/frame)")
    if s["stationary"]:
        still = []
        for i in range(n):
            moves = []
            if i > 0:
                moves += [speed(j, i - 1) for j in joints]
            if i < n - 1:
                moves += [speed(j, i) for j in joints]
            still.append(bool(moves) and max(moves) < s["still_speed"])
        i = 0
        while i < n:
            if still[i]:
                k = i
                while k + 1 < n and still[k + 1]:
                    k += 1
                add(i, "stationary", "body still" + (f" from frame {F[i]} to {F[k]}" if k > i else ""))
                i = k + 1
            else:
                i += 1
    return finish(found, keys)


def finish(found, keys):
    """Give each found frame a suggested label (a guess from its rules, for you to change)."""
    F = [f for f, _ in keys]
    ext = [f for f, e in found.items() if "extension" in e["rules"]]
    peak = min(ext) if ext else None
    out = []
    for f in sorted(found):
        e = found[f]
        r = e["rules"]
        if "first_last" in r:
            label = "starting position" if f == F[0] else "ending position"
        elif "sudden_stop" in r:
            label = "contact or impact"
        elif "extension" in r:
            label = "maximum extension"
        elif "stationary" in r:
            label = "hold"
        elif "sudden_start" in r or "direction" in r or "angles" in r:
            label = "preparation" if peak is not None and f < peak else ("recovery" if peak is not None
                                                                          else "direction change")
        else:
            label = "other"
        out.append({"frame": f, "label": label, "rules": r, "why": "; ".join(e["reasons"])})
    return out


# ---------------------------------------------------------------- key_poses.json
def path(folder):
    return trace_io.find_file(folder, FILE) or os.path.join(folder, FILE)


def load(folder):
    p = path(folder)
    data = {"schema": 1, "poses": [], "rejected": [], "settings": dict(DEFAULTS)}
    try:
        with open(p, encoding="utf-8") as fh:
            J = json.load(fh)
        data["poses"] = [q for q in J.get("poses", []) if isinstance(q, dict) and "frame" in q]
        data["rejected"] = [int(f) for f in J.get("rejected", [])]
        data["settings"].update({k: v for k, v in J.get("settings", {}).items() if k in DEFAULTS})
    except (OSError, ValueError, TypeError):
        pass
    return data


def save(folder, data):
    out = {"schema": 1, "poses": sorted(data["poses"], key=lambda q: q["frame"]),
           "rejected": sorted(set(data["rejected"])), "settings": data["settings"]}
    trace_io.write_atomic(path(folder), json.dumps(out, indent=1) + "\n")


def mark(data, frame, label, source="manual", why=""):
    """Add or relabel the key pose at frame (one per frame)."""
    data["poses"] = [q for q in data["poses"] if q["frame"] != frame]
    data["poses"].append({"frame": int(frame), "label": label, "source": source, "why": why})
    data["rejected"] = [f for f in data["rejected"] if f != frame]


def unmark(data, frame):
    data["poses"] = [q for q in data["poses"] if q["frame"] != frame]


def reject(data, frame):
    unmark(data, frame)
    if frame not in data["rejected"]:
        data["rejected"].append(int(frame))


def open_suggestions(suggestions, data):
    """Suggestions you haven't accepted or rejected yet."""
    taken = {q["frame"] for q in data["poses"]} | set(data["rejected"])
    return [s for s in suggestions if s["frame"] not in taken]

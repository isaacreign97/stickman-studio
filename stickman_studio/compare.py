"""Frame comparison and pose differences (upgrade Phase 7). Plain geometry on your coordinates, no AI.

Compares two poses, A and B: two frames of a trace, or the same frame in two versions (your trace, the fixed trace,
a dated backup). Differences are in pixels and in BONES (the median bone length of pose A), so they mean the same at
any zoom.

Alignment (how B is placed over A before measuring):
    none        as traced, pixel for pixel (e.g. your trace against an older backup of it)
    hips        B moved so its hip sits on A's hip: compares the POSE, not where the body is on screen
    hips_size   moved and scaled to A's body size too: compares the shape, even when the camera zoomed

Colours for joint differences: green under SMALL bones, amber under BIG bones, red above.
"""
import json
import math

from PIL import ImageDraw

import trace_io

ORDER = trace_io.ORDER
BONES = [(a, b) for ch in trace_io.CHAINS for a, b in zip(ch, ch[1:])]
ANGLES = {"front elbow": ("neck", "frontElbow", "frontHand"), "back elbow": ("neck", "backElbow", "backHand"),
          "front knee": ("hip", "frontKnee", "frontFoot"), "back knee": ("hip", "backKnee", "backFoot"),
          "torso bend": ("neck", "waist", "hip"), "neck–head": ("waist", "neck", "head")}
ALIGN = [("hips", "Hips together (compare the pose)"), ("hips_size", "Hips together + same size"),
         ("none", "As traced (pixel for pixel)")]
SMALL, BIG = 0.25, 0.5          # bones
GREEN, AMBER, RED = (70, 200, 110), (227, 162, 58), (255, 67, 75)


# ---------------------------------------------------------------- reading versions
def load_poses(path):
    """{frame: {joint: (x, y)}} from a trace.json / trace_fixed.json / backup (partly traced frames included)."""
    with open(path, encoding="utf-8") as fh:
        J = json.load(fh)
    out = {}
    for f, P in zip(J["frames"], J["pts"]):
        out[int(f)] = {n: (float(v[0]), float(v[1])) for n, v in P.items() if n in ORDER}
    return out


def other_characters(move, active_dir):
    """Phase 11: the OTHER traced characters of a multi-character move as versions [(label, path, kind)], so A and
    B can be two characters (they share the frames, so their traces are in the same picture space)."""
    import os
    import characters as chars
    out = []
    if not move or not chars.is_multi(move):
        return out
    here = os.path.normcase(os.path.normpath(active_dir))
    for c in chars.list_characters(move):
        if os.path.normcase(os.path.normpath(c["trace_dir"])) == here:
            continue
        t = trace_io.find_file(c["trace_dir"], trace_io.TRACE)
        fx = trace_io.find_file(c["trace_dir"], trace_io.FIXED)
        if t:
            out.append((f"{c['name']}: trace (trace.json)", t, "trace"))
        if fx:
            out.append((f"{c['name']}: fixed trace", fx, "fixed"))
    return out


def versions(folder):
    """The versions of a move you can compare: [(label, path, kind)]. kind "trace" = in reference-frame pixels
    (the picture can be shown under it); "fixed" = after the PLAY / FIX corrections (no picture)."""
    out = []
    t = trace_io.find_file(folder, trace_io.TRACE)
    if t:
        out.append(("Your trace (trace.json)", t, "trace"))
    fx = trace_io.find_file(folder, trace_io.FIXED)
    if fx:
        out.append(("Fixed trace (trace_fixed.json)", fx, "fixed"))
    for b in trace_io.list_backups(folder):
        out.append(("Backup " + trace_io.describe(b), b["path"], b["kind"]))
    return out


# ---------------------------------------------------------------- measuring
def scale(P):
    Ls = sorted(math.dist(P[a], P[b]) for a, b in BONES if a in P and b in P)
    if not Ls:
        return 1.0
    k = len(Ls)
    return max(1e-6, Ls[k // 2] if k % 2 else (Ls[k // 2 - 1] + Ls[k // 2]) / 2)


def angle_at(P, a, b, c):
    ax, ay = P[a][0] - P[b][0], P[a][1] - P[b][1]
    cx, cy = P[c][0] - P[b][0], P[c][1] - P[b][1]
    na, nc = math.hypot(ax, ay), math.hypot(cx, cy)
    if na < 1e-9 or nc < 1e-9:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, (ax * cx + ay * cy) / (na * nc)))))


def lean(P):
    """Torso lean in degrees: the hip→neck line against straight up. + = leaning right on screen."""
    if "hip" not in P or "neck" not in P:
        return None
    dx, dy = P["neck"][0] - P["hip"][0], P["neck"][1] - P["hip"][1]
    return math.degrees(math.atan2(dx, -dy))


def height(P):
    """Head to the lowest foot, in pixels (y is down)."""
    if "head" not in P:
        return None
    feet = [P[n][1] for n in ("frontFoot", "backFoot") if n in P]
    return max(feet) - P["head"][1] if feet else None


def align(A, B, mode):
    """B placed over A: 'none', 'hips' (B's hip moved onto A's hip) or 'hips_size' (also scaled to A's size)."""
    if mode == "none" or "hip" not in A or "hip" not in B:
        return dict(B)
    k = scale(A) / scale(B) if mode == "hips_size" else 1.0
    hx, hy = B["hip"]
    ax, ay = A["hip"]
    return {n: (ax + (x - hx) * k, ay + (y - hy) * k) for n, (x, y) in B.items()}


def level(bones):
    return "big" if bones > BIG else "medium" if bones > SMALL else "small"


def compare(A, B, mode="hips"):
    """-> {"joints": {joint: {...}}, "angles": {name: (a, b, b - a)}, "body": {...}, "mean_bones", "worst",
           "summary": [lines], "aligned": B placed over A}"""
    Bv = align(A, B, mode)
    s = scale(A)
    joints = {}
    for n in ORDER:
        if n in A and n in Bv:
            dx, dy = Bv[n][0] - A[n][0], Bv[n][1] - A[n][1]
            d = math.hypot(dx, dy)
            joints[n] = {"a": A[n], "b": B[n], "b_aligned": Bv[n], "dx": dx, "dy": dy, "dist": d, "bones": d / s,
                         "level": level(d / s)}
    angles = {}
    for name, (a, b, c) in ANGLES.items():
        if all(n in A for n in (a, b, c)) and all(n in B for n in (a, b, c)):
            x, y = angle_at(A, a, b, c), angle_at(B, a, b, c)
            if x is not None and y is not None:
                angles[name] = (x, y, y - x)
    body = {}
    if "hip" in A and "hip" in B:
        d = math.dist(A["hip"], B["hip"])
        body["hip moved"] = (d, d / s)
    la, lb = lean(A), lean(B)
    if la is not None and lb is not None:
        body["torso lean"] = (la, lb, lb - la)
    ha, hb = height(A), height(B)
    if ha and hb:
        body["height"] = (ha, hb, hb / ha)
    body["body size (median bone)"] = (s, scale(B), scale(B) / s)
    if "frontFoot" in A and "backFoot" in A and "frontFoot" in B and "backFoot" in B:
        body["stance width"] = (abs(A["frontFoot"][0] - A["backFoot"][0]), abs(B["frontFoot"][0] - B["backFoot"][0]))
    mean = sum(j["bones"] for j in joints.values()) / len(joints) if joints else 0.0
    worst = max(joints, key=lambda n: joints[n]["dist"]) if joints else None
    return {"joints": joints, "angles": angles, "body": body, "mean_bones": mean, "worst": worst,
            "aligned": Bv, "mode": mode, "scale": s, "summary": summary(joints, angles, body, mean, worst, mode)}


def summary(joints, angles, body, mean, worst, mode):
    lines = []
    if not joints:
        return ["No joint is placed in both poses."]
    big = [n for n, j in joints.items() if j["level"] == "big"]
    med = [n for n, j in joints.items() if j["level"] == "medium"]
    w = joints[worst]
    how = {"hips": "with the hips together", "hips_size": "with the hips together and the same size",
           "none": "as traced"}[mode]
    lines.append(f"Compared {how}: average difference {mean:.2f} bones; {len(big)} joint(s) differ a lot "
                 f"(over {BIG} bones), {len(med)} somewhat.")
    lines.append(f"Biggest difference: {worst}, {w['dist']:.1f} px ({w['bones']:.2f} bones).")
    if big:
        lines.append("Differ a lot: " + ", ".join(big) + ".")
    turned = sorted(((abs(d), name, d) for name, (a, b, d) in angles.items() if abs(d) >= 15), reverse=True)
    for _, name, d in turned[:3]:
        a, b, _ = angles[name]
        lines.append(f"{name}: {a:.0f}° → {b:.0f}° ({'straighter' if d > 0 else 'more bent'} by {abs(d):.0f}°).")
    if "torso lean" in body and abs(body["torso lean"][2]) >= 10:
        lines.append(f"Torso leans {body['torso lean'][2]:+.0f}° more in B (+ = to the right).")
    if "body size (median bone)" in body and abs(body["body size (median bone)"][2] - 1) >= 0.15:
        lines.append(f"B's body is {body['body size (median bone)'][2]:.2f}× the size of A's "
                     "(camera zoom, or a turn towards the camera).")
    if "hip moved" in body and body["hip moved"][1] >= 0.5:
        lines.append(f"The body moved {body['hip moved'][0]:.0f} px ({body['hip moved'][1]:.1f} bones) on screen.")
    return lines


def report(name_a, name_b, res):
    """A plain-text report (for the clipboard)."""
    out = [f"A: {name_a}", f"B: {name_b}", ""] + res["summary"] + ["", "Joint differences (B - A):"]
    for n, j in res["joints"].items():
        out.append(f"  {n:<11} dx {j['dx']:+7.1f}  dy {j['dy']:+7.1f}  = {j['dist']:6.1f} px  "
                   f"{j['bones']:5.2f} bones  {j['level']}")
    if res["angles"]:
        out.append("Angles (A → B):")
        for name, (a, b, d) in res["angles"].items():
            out.append(f"  {name:<11} {a:6.1f}° → {b:6.1f}°  ({d:+.1f}°)")
    return "\n".join(out)


# ---------------------------------------------------------------- drawing
def colour(name):
    return (255, 140, 0) if name.startswith("front") else (60, 130, 255) if name.startswith("back") else (40, 210, 80)


def draw_pose(img, P, to_screen, ghost=False, width=3):
    """A pose on a PIL image: coloured limbs, or a thin light-grey 'ghost' for comparison."""
    d = ImageDraw.Draw(img)
    for ch in trace_io.CHAINS:
        for a, b in zip(ch, ch[1:]):
            if a in P and b in P:
                fill = (225, 225, 230) if ghost else colour(ch[1])
                d.line((*to_screen(*P[a]), *to_screen(*P[b])), fill=fill, width=2 if ghost else width)
    for n, p in P.items():
        x, y = to_screen(*p)
        r = 3 if ghost else 4
        d.ellipse((x - r, y - r, x + r, y + r), fill=(225, 225, 230) if ghost else (255, 255, 255),
                  outline=(0, 0, 0))


def draw_diffs(img, res, to_screen):
    """An arrow-like line from each joint in A to the same joint in B, coloured by how big the difference is."""
    d = ImageDraw.Draw(img)
    for n, j in res["joints"].items():
        (ax, ay), (bx, by) = to_screen(*j["a"]), to_screen(*j["b_aligned"])
        col = {"small": GREEN, "medium": AMBER, "big": RED}[j["level"]]
        d.line((ax, ay, bx, by), fill=col, width=2)
        d.ellipse((bx - 5, by - 5, bx + 5, by + 5), outline=col, width=2)

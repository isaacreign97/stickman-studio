"""Animation analytics (upgrade Phase 8): measurements of a traced move. Plain maths, no AI.

    displacement  d = sqrt((x2 - x1)^2 + (y2 - y1)^2)      between two frames
    velocity      v = d / dt                              dt = frames apart / fps   (seconds)
    acceleration  a = |v_out - v_in| / dt                  (velocity as a vector, so a turn counts too)
    angles        at the elbows, knees, torso (neck-waist-hip) and neck (waist-neck-head), in degrees
    angular speed change of an angle / dt                 (degrees per second)

Time comes from the frame rate (timing.json next to the frames, or the one you type in). PIXELS ARE NOT METRES:
distances can be shown as
    px      pixels of the reference frames (what you traced)
    bones   the median bone length of the body (same at any zoom: good for comparing moves)
    m       metres, if you give the character's standing height (the tallest head-to-foot height in the move is
            taken as that height; turns and crouches make the body look shorter, so this is approximate)
    units   game units, if you give how many game units one reference pixel is

Data: the traced key frames as they are, or every frame from the first to the last key as PLAY shows it (the
in-betweens the player draws; needs frames with all 12 joints).
"""
import csv
import math

import trace_io

ORDER = trace_io.ORDER
BONES = [(a, b) for ch in trace_io.CHAINS for a, b in zip(ch, ch[1:])]
ANGLES = {"front elbow": ("neck", "frontElbow", "frontHand"), "back elbow": ("neck", "backElbow", "backHand"),
          "front knee": ("hip", "frontKnee", "frontFoot"), "back knee": ("hip", "backKnee", "backFoot"),
          "torso bend": ("neck", "waist", "hip"), "neck": ("waist", "neck", "head")}
UNITS = [("px", "pixels"), ("bones", "bone lengths"), ("m", "metres (needs a height)"),
         ("units", "game units (needs units per px)")]
SIZE_WARN = 1.25       # body size changing more than this between frames -> warn that camera zoom is mixed in


# ---------------------------------------------------------------- data
def median(vals):
    vals = sorted(vals)
    if not vals:
        return 0.0
    k = len(vals)
    return vals[k // 2] if k % 2 else (vals[k // 2 - 1] + vals[k // 2]) / 2


def body_scale(P):
    return median([math.dist(P[a], P[b]) for a, b in BONES if a in P and b in P]) or 1.0


def body_height(P):
    if "head" not in P:
        return None
    feet = [P[n][1] for n in ("frontFoot", "backFoot") if n in P]
    return max(feet) - P["head"][1] if feet else None


def every_frame(poses):
    """The in-between poses PLAY draws, one per frame from the first to the last complete key frame."""
    import trace_player   # only needed here (it brings the player's interpolation)
    keys = sorted((f, P) for f, P in poses.items() if all(n in P for n in ORDER))
    if len(keys) < 2:
        return dict(keys)
    m = trace_player.Motion(keys)
    return {f: {n: tuple(v) for n, v in m.pose(float(f)).items()} for f in range(keys[0][0], keys[-1][0] + 1)}


def unit_factor(poses, unit, height_m=None, units_per_px=None):
    """-> (factor that turns px into the unit, unit label, note). Raises ValueError when the unit needs a number."""
    if unit == "bones":
        s = median([body_scale(P) for P in poses.values() if P])
        return 1.0 / max(s, 1e-9), "bones", f"1 bone = {s:.1f} px (median bone length)"
    if unit == "m":
        if not height_m or height_m <= 0:
            raise ValueError("Type the character's standing height in metres.")
        hs = [h for h in (body_height(P) for P in poses.values()) if h and h > 0]
        if not hs:
            raise ValueError("No frame has the head and a foot, so the height can't be measured.")
        tall = max(hs)
        return height_m / tall, "m", f"{height_m:g} m = the tallest pose, {tall:.0f} px (approximate)"
    if unit == "units":
        if not units_per_px or units_per_px <= 0:
            raise ValueError("Type how many game units one reference pixel is (for example 0.0112).")
        return units_per_px, "units", f"1 px = {units_per_px:g} game units"
    return 1.0, "px", "pixels of the reference frames"


# ---------------------------------------------------------------- measurements
def joint_series(poses, joint, fps, k=1.0):
    """[{frame, t, x, y, step, speed, accel}] for one joint (distances x k; speed per second, accel per second²).
    speed = over the interval INTO that frame; accel = change of the velocity vector across that frame."""
    fs = sorted(f for f, P in poses.items() if joint in P)
    rows = []
    vel = [None]
    for i, f in enumerate(fs):
        x, y = poses[f][joint]
        row = {"frame": f, "t": (f - fs[0]) / fps, "x": x * k, "y": y * k, "step": None, "speed": None,
               "accel": None}
        if i:
            px, py = poses[fs[i - 1]][joint]
            dt = (f - fs[i - 1]) / fps
            row["step"] = math.hypot(x - px, y - py) * k
            row["speed"] = row["step"] / dt
            vel.append(((x - px) * k / dt, (y - py) * k / dt))
        rows.append(row)
    for i in range(1, len(fs) - 1):
        (ax, ay), (bx, by) = vel[i], vel[i + 1]
        dt = (fs[i + 1] - fs[i - 1]) / 2 / fps
        rows[i]["accel"] = math.hypot(bx - ax, by - ay) / dt
    return rows


def joint_stats(rows):
    if not rows:
        return None
    steps = [r["step"] for r in rows if r["step"] is not None]
    speeds = [(r["speed"], r["frame"]) for r in rows if r["speed"] is not None]
    accs = [(r["accel"], r["frame"]) for r in rows if r["accel"] is not None]
    first, last = rows[0], rows[-1]
    dur = last["t"] - first["t"]
    path = sum(steps)
    return {"path": path, "net": math.hypot(last["x"] - first["x"], last["y"] - first["y"]),
            "mean_speed": path / dur if dur > 0 else 0.0,
            "peak_speed": max(speeds) if speeds else (0.0, None), "peak_accel": max(accs) if accs else (0.0, None),
            "x_range": max(r["x"] for r in rows) - min(r["x"] for r in rows),
            "y_range": max(r["y"] for r in rows) - min(r["y"] for r in rows)}


def angle_at(P, a, b, c):
    ax, ay = P[a][0] - P[b][0], P[a][1] - P[b][1]
    cx, cy = P[c][0] - P[b][0], P[c][1] - P[b][1]
    na, nc = math.hypot(ax, ay), math.hypot(cx, cy)
    if na < 1e-9 or nc < 1e-9:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, (ax * cx + ay * cy) / (na * nc)))))


def angle_series(poses, name, fps):
    """[{frame, t, angle, change, ang_speed}] for one angle (degrees; ang_speed in degrees per second)."""
    a, b, c = ANGLES[name]
    fs = sorted(f for f, P in poses.items() if all(n in P for n in (a, b, c)))
    rows = []
    for i, f in enumerate(fs):
        v = angle_at(poses[f], a, b, c)
        if v is None:
            continue
        row = {"frame": f, "t": (f - fs[0]) / fps, "angle": v, "change": None, "ang_speed": None}
        if rows:
            prev = rows[-1]
            row["change"] = v - prev["angle"]
            row["ang_speed"] = abs(row["change"]) / ((f - prev["frame"]) / fps)
        rows.append(row)
    return rows


def angle_stats(rows):
    if not rows:
        return None
    vals = [(r["angle"], r["frame"]) for r in rows]
    sp = [(r["ang_speed"], r["frame"]) for r in rows if r["ang_speed"] is not None]
    return {"min": min(vals), "max": max(vals), "range": max(vals)[0] - min(vals)[0],
            "total_turn": sum(abs(r["change"]) for r in rows if r["change"] is not None),
            "peak_ang_speed": max(sp) if sp else (0.0, None)}


def timing(frames, fps, key_poses=()):
    """Duration and the intervals between traced frames and between your key poses (frames and seconds)."""
    fs = sorted(frames)
    out = {"frames": len(fs), "first": fs[0] if fs else None, "last": fs[-1] if fs else None,
           "duration": (fs[-1] - fs[0]) / fps if fs else 0.0, "fps": fps,
           "intervals": [(a, b, b - a, (b - a) / fps) for a, b in zip(fs, fs[1:])], "pose_intervals": []}
    kp = sorted(key_poses, key=lambda q: q["frame"])
    out["pose_intervals"] = [(p["frame"], p["label"], q["frame"], q["label"], q["frame"] - p["frame"],
                              (q["frame"] - p["frame"]) / fps) for p, q in zip(kp, kp[1:])]
    return out


def body(poses, k=1.0):
    """Root (hip) travel and how high it rises, in the chosen unit."""
    fs = sorted(f for f, P in poses.items() if "hip" in P)
    if not fs:
        return {}
    x0, y0 = poses[fs[0]]["hip"]
    x1, y1 = poses[fs[-1]]["hip"]
    ys = [poses[f]["hip"][1] for f in fs]
    xs = [poses[f]["hip"][0] for f in fs]
    up = y0 - min(ys)          # y is down in pictures: a smaller y is higher
    return {"travel_x": (x1 - x0) * k, "travel_y": (y0 - y1) * k, "travel": math.hypot(x1 - x0, y1 - y0) * k,
            "hip_rise": max(0.0, up) * k, "hip_rise_frame": fs[ys.index(min(ys))],
            "hip_drop": max(0.0, max(ys) - y0) * k, "x_range": (max(xs) - min(xs)) * k}


def analyse(poses, fps, k=1.0, unit="px", key_poses=()):
    """Everything for the window and the report."""
    joints = {j: joint_stats(joint_series(poses, j, fps, k)) for j in ORDER}
    joints = {j: s for j, s in joints.items() if s}
    angles = {a: angle_stats(angle_series(poses, a, fps)) for a in ANGLES}
    angles = {a: s for a, s in angles.items() if s}
    scales = [body_scale(P) for P in poses.values() if len(P) >= 6]
    size_change = max(scales) / min(scales) if scales and min(scales) > 0 else 1.0
    res = {"joints": joints, "angles": angles, "timing": timing([f for f, P in poses.items() if P], fps, key_poses),
           "body": body(poses, k), "unit": unit, "size_change": size_change}
    res["summary"] = summary(res)
    return res


def summary(res):
    u = res["unit"]
    t = res["timing"]
    lines = [f"{t['frames']} frames, {t['first']} to {t['last']}: {t['duration']:.2f} s at {t['fps']:g} fps."]
    if res["joints"]:
        fast = max(res["joints"], key=lambda j: res["joints"][j]["peak_speed"][0])
        sp, f = res["joints"][fast]["peak_speed"]
        lines.append(f"Fastest joint: {fast}, {sp:.2f} {u}/s (into frame {f}).")
        far = max(res["joints"], key=lambda j: res["joints"][j]["path"])
        lines.append(f"Longest path: {far}, {res['joints'][far]['path']:.2f} {u}.")
    b = res["body"]
    if b:
        lines.append(f"Hip travels {b['travel_x']:+.2f} {u} sideways and {b['travel_y']:+.2f} {u} up "
                     f"(+ = right / up); highest rise {b['hip_rise']:.2f} {u} at frame {b['hip_rise_frame']}.")
    if res["angles"]:
        big = max(res["angles"], key=lambda a: res["angles"][a]["range"])
        s = res["angles"][big]
        lines.append(f"Biggest angle change: {big}, {s['min'][0]:.0f}° to {s['max'][0]:.0f}° "
                     f"(range {s['range']:.0f}°).")
    if res.get("size_change", 1.0) > SIZE_WARN:
        lines.append(f"! The body's size changes up to {res['size_change']:.1f}× between frames (camera zoom, or "
                     "turns towards the camera), so distances and speeds include camera movement. For real-world "
                     "numbers use the fixed trace with 'Even out camera zoom', or compare in bone lengths.")
    return lines


# ---------------------------------------------------------------- report and CSV
def report(title, res, note=""):
    u = res["unit"]
    out = [title] + ([note] if note else []) + [""] + res["summary"] + ["", f"Joints ({u}, {u}/s, {u}/s²):"]
    for j, s in res["joints"].items():
        out.append(f"  {j:<11} path {s['path']:8.2f}  net {s['net']:8.2f}  mean speed {s['mean_speed']:8.2f}  "
                   f"peak {s['peak_speed'][0]:8.2f} (f{s['peak_speed'][1]})  peak accel {s['peak_accel'][0]:9.2f}"
                   f" (f{s['peak_accel'][1]})")
    out.append("Angles (°, °/s):")
    for a, s in res["angles"].items():
        out.append(f"  {a:<11} min {s['min'][0]:6.1f} (f{s['min'][1]})  max {s['max'][0]:6.1f} (f{s['max'][1]})  "
                   f"range {s['range']:6.1f}  peak speed {s['peak_ang_speed'][0]:7.1f} (f{s['peak_ang_speed'][1]})")
    t = res["timing"]
    out.append("Intervals between traced frames: " + ", ".join(f"{a}→{b} {n} fr {s:.3f}s"
                                                               for a, b, n, s in t["intervals"]))
    if t["pose_intervals"]:
        out.append("Between your key poses: " + "; ".join(f"{la} (f{a}) → {lb} (f{b}): {n} fr, {s:.3f}s"
                                                          for a, la, b, lb, n, s in t["pose_intervals"]))
    return "\n".join(out)


LIMBS = ("frontHand", "backHand", "frontFoot", "backFoot")
TARGETS = ("head", "neck", "waist", "hip")


def between(A, B, k=1.0):
    """Phase 11: two traced characters of one move (same picture space), on the frames both have.
    A, B = {frame: {joint: (x, y)}}. -> {"frames", "first", "last", "hip_min": (distance, frame), "hip_max",
    "closest": (distance, frame, A's hand / foot, B's head / neck / waist / hip)} in the unit of k, or None."""
    common = sorted(f for f in set(A) & set(B) if A[f] and B[f])
    if not common:
        return None
    hips = [(math.dist(A[f]["hip"], B[f]["hip"]) * k, f) for f in common if "hip" in A[f] and "hip" in B[f]]
    close = None
    for f in common:
        for ja in LIMBS:
            for jb in TARGETS:
                if ja in A[f] and jb in B[f]:
                    d = math.dist(A[f][ja], B[f][jb]) * k
                    if close is None or d < close[0]:
                        close = (d, f, ja, jb)
    return {"frames": len(common), "first": common[0], "last": common[-1],
            "hip_min": min(hips) if hips else None, "hip_max": max(hips) if hips else None, "closest": close}


def write_csv(path, poses, fps, k=1.0, unit="px"):
    """One row per frame: time, each joint's x / y in pixels, its hip-relative position in bones (y down, as in
    the picture) and its speed in the chosen unit, plus every angle. Opens in Excel / Google Sheets."""
    fs = sorted(f for f, P in poses.items() if P)
    speed = {j: {r["frame"]: r["speed"] for r in joint_series(poses, j, fps, k)} for j in ORDER}
    head = ["frame", "time_s"]
    for j in ORDER:
        head += [f"{j}_x_px", f"{j}_y_px", f"{j}_x_rel_bones", f"{j}_y_rel_bones", f"{j}_speed_{unit}_per_s"]
    head += [f"angle_{a.replace(' ', '_')}_deg" for a in ANGLES]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        for f in fs:
            P = poses[f]
            s = body_scale(P)
            hx, hy = P.get("hip", (0.0, 0.0))
            row = [f, round((f - fs[0]) / fps, 4)]
            for j in ORDER:
                if j in P:
                    x, y = P[j]
                    sp = speed[j].get(f)
                    row += [round(x, 2), round(y, 2), round((x - hx) / s, 4), round((y - hy) / s, 4),
                            "" if sp is None else round(sp, 4)]
                else:
                    row += ["", "", "", "", ""]
            for a, (p, q, r) in ANGLES.items():
                v = angle_at(P, p, q, r) if all(n in P for n in (p, q, r)) else None
                row.append("" if v is None else round(v, 2))
            w.writerow(row)
    return len(fs)
